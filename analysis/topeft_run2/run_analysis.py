#!/usr/bin/env python

"""Command-line entrypoint for Run-2 histogram production.

Purpose:
- Parse CLI/YAML options and launch the Run-2 workflow planner/executor stack.

Inputs/outputs:
- Reads sample manifests (JSON/CFG) plus optional YAML option profiles.
- Writes histogram pickles and run summaries to the configured output
  directory. TaskVine DDR runs default to the canonical flattened schema,
  while local futures/iterative execution preserves tuple-keyed outputs.

Side effects:
- Creates output files/directories and may dispatch tasks to futures/TaskVine.

How to run:
- ``python analysis/topeft_run2/run_analysis.py --help``
- ``python analysis/topeft_run2/run_analysis.py --options analysis/topeft_run2/configs/fullR2_run.yml:cr``
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import importlib
import logging
import os
import shlex
import sys
import traceback
from pathlib import Path
from typing import IO, Iterator, Sequence

from analysis.topeft_run2 import metadata_authority


def _optional_import_modules() -> list[str]:
    value = os.environ.get("TOPEFT_IMPORT_CHECK_MODULES")
    if value is None:
        return []
    modules = [token.strip() for token in value.split(",")]
    return [module for module in modules if module]


def _verify_numpy_abi() -> None:
    """Verify required runtime imports, with optional module checks on demand."""

    try:
        importlib.import_module("numpy")
    except Exception as exc:  # pragma: no cover - environment guard
        raise RuntimeError(
            "Failed to import numpy before launching the workflow. "
            "Recreate the coffea2025 environment and rebuild the TaskVine "
            "tarball before rerunning: `conda env update -f environment.yml "
            "--prune` and `python -m topeft.modules.remote_environment`."
        ) from exc

    optional_modules = _optional_import_modules()
    if not optional_modules:
        return

    print(
        "[topeft.run_analysis] Optional import checks enabled via "
        "TOPEFT_IMPORT_CHECK_MODULES="
        f"{','.join(optional_modules)}",
        file=sys.stderr,
        flush=True,
    )
    for module_name in optional_modules:
        try:  # pragma: no cover - environment guard
            importlib.import_module(module_name)
        except Exception as exc:
            print(
                "[topeft.run_analysis] Optional import check failed for "
                f"module '{module_name}' while TOPEFT_IMPORT_CHECK_MODULES is set.",
                file=sys.stderr,
                flush=True,
            )
            raise RuntimeError(
                "Optional module import check failed for "
                f"'{module_name}'. Recreate the coffea2025 environment and "
                "rebuild the TaskVine tarball: `conda env update -f "
                "environment.yml --prune` followed by "
                "`python -m topeft.modules.remote_environment`."
            ) from exc

from analysis.topeft_run2.run_analysis_helpers import (
    RunConfig,
    RunConfigBuilder,
    _normalize_executor_name,
    enforce_options_single_source,
    options_allowlist,
)
from topeft.modules.executor_cli import (
    ExecutorCLIHelper,
    FuturesArgumentSpec,
    TaskVineArgumentSpec,
)
from topeft.modules import remote_environment as topeft_remote_environment

from topeft.modules.logging_config import configure_topeft_logging

logger = logging.getLogger(__name__)

remote_environment = topeft_remote_environment

SUPPORTED_EXECUTORS: tuple[str, ...] = ("futures", "iterative", "taskvine")


class TaskVineEnvironmentBuildError(RuntimeError):
    """Raised when TaskVine env tarball auto-build fails."""


class _TeeStream:
    """Write to a primary stream and optionally mirror into a logfile."""

    def __init__(self, primary: IO[str], mirror: IO[str]) -> None:
        self._primary = primary
        self._mirror = mirror

    def write(self, data: str) -> int:
        self._primary.write(data)
        self._mirror.write(data)
        return len(data)

    def flush(self) -> None:
        self._primary.flush()
        self._mirror.flush()

    def isatty(self) -> bool:
        return bool(getattr(self._primary, "isatty", lambda: False)())

    @property
    def encoding(self) -> str:
        return getattr(self._primary, "encoding", "utf-8")


@contextmanager
def _driver_log_context(driver_log_path: str | None) -> Iterator[None]:
    """Mirror stdout/stderr to ``driver_log_path`` when configured."""

    if not driver_log_path:
        yield
        return

    log_path = Path(driver_log_path).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        sys.stdout = _TeeStream(original_stdout, handle)
        sys.stderr = _TeeStream(original_stderr, handle)
        try:
            yield
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr


def _write_exit_marker(path: str | None, status: int) -> None:
    if not path:
        return
    marker_path = Path(path).expanduser()
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(f"{int(status)}\n", encoding="utf-8")


def _emit_exit_debug(enabled: bool, status: int) -> None:
    if not enabled:
        return
    print(
        f"run_analysis.py: driver_status={int(status)}",
        file=sys.stderr,
        flush=True,
    )


def _log_taskvine_ddr_knob_summary(config: RunConfig) -> None:
    """Emit a stable summary block for TaskVine/DDR driver knobs."""

    summary_items = [
        ("taskvine_manager_name", config.manager_name),
        ("taskvine_manager_name_template", config.manager_name_template),
        ("taskvine_proxy_path", config.ddr_x509_proxy),
        ("ddr_debug", config.ddr_debug),
        ("ddr_worker_probe_enabled", config.ddr_worker_probe_enabled),
        ("ddr_worker_probe_url", config.ddr_worker_probe_url),
        ("ddr_worker_probe_timeout", config.ddr_worker_probe_timeout),
        ("driver_log_path", config.driver_log_path),
        ("exit_marker_path", config.exit_marker_path),
        ("exit_debug", config.exit_debug),
    ]

    logger.info("Resolved TaskVine/DDR driver knobs:")
    for key, value in summary_items:
        logger.info("  %s=%s", key, value if value not in (None, "") else "<none>")


def _environment_file_is_unset_or_empty(value: str | None) -> bool:
    """Return ``True`` when ``value`` is unset/empty."""

    if value is None:
        return True
    return str(value).strip() == ""


def _environment_file_is_explicit_none(value: str | None) -> bool:
    """Return ``True`` when ``value`` explicitly disables env shipping."""

    if value is None:
        return False
    return str(value).strip().lower() == "none"


def ensure_taskvine_environment_file(
    config: RunConfig,
    *,
    repo_root: Path | None = None,
) -> str:
    """Ensure TaskVine runs have an environment tarball path."""

    if (
        getattr(config, "environment_file_explicit_none", False)
        or _environment_file_is_explicit_none(config.environment_file)
    ):
        raise TaskVineEnvironmentBuildError(
            "TaskVine requires an environment_file. "
            "'--environment-file none' and '--no-environment-file' are not supported "
            "with executor=taskvine. Leave environment_file unset/empty to auto-build, "
            "or set a tarball path, 'cached', or 'auto'."
        )

    if not _environment_file_is_unset_or_empty(config.environment_file):
        return str(config.environment_file)

    logger.info("TaskVine environment_file not set; building environment tarball...")
    try:
        built_path = Path(str(remote_environment.get_environment())).expanduser()
    except Exception as exc:
        raise TaskVineEnvironmentBuildError(
            "TaskVine environment_file not set and automatic tarball build failed."
        ) from exc

    if not built_path.is_absolute():
        resolved_root = Path(repo_root or metadata_authority.get_repo_root()).resolve()
        built_path = (resolved_root / built_path).resolve()

    if not built_path.is_file():
        raise TaskVineEnvironmentBuildError(
            f"TaskVine environment tarball build returned a missing path: {built_path}"
        )

    config.environment_file = str(built_path)
    logger.info("Built environment tarball at: %s", config.environment_file)
    return config.environment_file


EXECUTOR_CLI = ExecutorCLIHelper(
    remote_environment=remote_environment,
    futures_spec=FuturesArgumentSpec(
        workers_default=8,
        include_status=True,
        include_tail_timeout=True,
        include_memory=True,
        include_prefetch=True,
        include_retries=True,
        include_retry_wait=True,
    ),
    taskvine_spec=TaskVineArgumentSpec(
        include_manager_name=False,
        include_manager_template=False,
        include_scratch_dir=True,
        include_resource_monitor=True,
        include_resources_mode=True,
        resource_monitor_default="measure",
        resources_mode_default="auto",
    ),
    default_environment=None,
)


def build_parser() -> argparse.ArgumentParser:
    """Return the CLI argument parser used by ``run_analysis.py``."""

    parser = argparse.ArgumentParser(
        description="You can customize your run",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "TaskVine workers can be launched with:\n"
            "  vine_submit_workers --python-env \"$(python -m topeft.modules.remote_environment)\" \\\n"
            "    --cores 4 --memory 16000 --disk 16000 -M <manager-name>\n"
            "TaskVine DDR uses worker-provided --python-env tarballs and stages the\n"
            "--processor module file to workers (Model S). --environment-file is\n"
            "still supported, but worker --python-env tarballs remain the recommended\n"
            "path for TaskVine DDR."
        ),
    )
    parser.add_argument(
        "jsonFiles",
        nargs="?",
        default="",
        help="Json file(s) containing files and metadata",
    )
    parser.add_argument(
        "--prefix",
        "-r",
        nargs="?",
        default="",
        help="Prefix or redirector to look for the files",
    )
    parser.add_argument(
        "--test",
        "-t",
        action="store_true",
        help="To perform a test, run over a few events in a couple of chunks",
    )
    parser.add_argument(
        "--pretend",
        action="store_true",
        help="Read json files but do not execute the analysis",
    )
    EXECUTOR_CLI.configure_parser(parser)
    parser.add_argument(
        "--chunksize",
        "-s",
        type=int,
        default=500000,
        help="Number of events per chunk",
    )
    parser.add_argument(
        "--nchunks",
        "-c",
        type=int,
        default=None,
        help="You can choose to run only a number of chunks",
    )
    parser.add_argument(
        "--outname",
        "-o",
        default="plotsTopEFT",
        help="Name of the output file with histograms",
    )
    parser.add_argument(
        "--outpath",
        "-p",
        default="histos",
        help="Name of the output directory",
    )
    parser.add_argument(
        "--treename",
        default="Events",
        help="Name of the tree inside the files",
    )
    parser.add_argument(
        "--processor",
        default="analysis_processor.py",
        help=(
            "Path to the processor module file staged to TaskVine workers. "
            "The module is imported by top-level filename stem (Model S)."
        ),
    )
    parser.add_argument(
        "--metadata",
        default=None,
        help=(
            "Path to the metadata YAML bundle. Cannot be combined with --options."
        ),
    )
    parser.add_argument(
        "--do-errors",
        action="store_true",
        help="Save the w**2 coefficients",
    )
    parser.add_argument(
        "--do-systs",
        action="store_true",
        help="Compute systematic variations",
    )
    parser.add_argument(
        "--split-lep-flavor",
        action="store_true",
        help="Split up categories by lepton flavor",
    )
    parser.add_argument(
        "--summary-verbosity",
        choices=["none", "brief", "full"],
        default="brief",
        help=(
            "Control the histogram summary emitted before task submission. "
            "'none' disables the summary, 'brief' prints bullet lists of the "
            "planned samples, channel/application pairs, variables, and "
            "systematics, and 'full' prepends those lists to the per-combination "
            "table plus the structured dump (including a note when "
            "--split-lep-flavor is active)."
        ),
    )
    parser.add_argument(
        "--log-level",
        default=None,
        help=(
            "Set the Python logging level to control topeft/topcoffea output. "
            "Allowed values: none, info, warning, error, debug. Defaults to info when unset."
        ),
    )
    parser.add_argument(
        "--log-tasks",
        action="store_true",
        help=(
            "Print a single-line futures submission log for each histogram task, "
            "showing the (sample, channel, variable, application, systematic) tuple."
        ),
    )
    parser.add_argument(
        "--produce-sidecars",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Enable sidecar payloads (variation summaries, region_yields). "
            "Disabled by default."
        ),
    )
    parser.add_argument(
        "--scenario",
        dest="scenarios",
        action="append",
        help=(
            "Scenario name defined in metadata to select channel groups."
            " Defaults to 'TOP_22_006' when not provided. Can be supplied"
            " multiple times to combine scenarios."
        ),
    )
    parser.add_argument(
        "--allow-partial-channel-groups",
        action="store_true",
        help=(
            "Allow runs to proceed when a scenario is missing some channel groups"
            " in the provided metadata. By default a missing group raises an error."
        ),
    )
    parser.add_argument(
        "--skip-sr",
        action="store_true",
        help="Skip all signal region categories",
    )
    parser.add_argument(
        "--skip-cr",
        action="store_true",
        help="Skip all control region categories",
    )
    parser.add_argument(
        "--do-np",
        action="store_true",
        help=(
            "Perform nonprompt estimation on the output hist, and save a new hist "
            "with the np contribution included. Signal, background and data samples "
            "must all be processed together."
        ),
    )
    parser.add_argument(
        "--do-renormfact-envelope",
        action="store_true",
        help=(
            "Perform renorm/fact envelope calculation on the output hist "
            "(saves the modified with the same name as the original)."
        ),
    )
    parser.add_argument(
        "--wc-list",
        action="extend",
        nargs="+",
        help="Specify a list of Wilson coefficients to use in filling histograms.",
    )
    parser.add_argument(
        "--ecut",
        default=None,
        help="Energy cut threshold i.e. throw out events above this (GeV)",
    )
    parser.add_argument(
        "--no-port-negotiation",
        dest="negotiate_manager_port",
        action="store_false",
        help=(
            "Disable automatic TaskVine port negotiation. When set the first value "
            "from --port is used directly and any allocation failure aborts the run."
        ),
    )
    parser.add_argument(
        "--taskvine-manager-name",
        dest="taskvine_manager_name",
        default=None,
        help=(
            "TaskVine manager/project name override. "
            "YAML key: taskvine_manager_name."
        ),
    )
    parser.add_argument(
        "--taskvine-manager-name-template",
        dest="taskvine_manager_name_template",
        default=None,
        help=(
            "TaskVine manager template override. "
            "YAML key: taskvine_manager_name_template."
        ),
    )
    parser.add_argument(
        "--ddr-debug",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Enable deterministic DDR debug markers from workflow/taskvine handoff. "
            "YAML key: ddr_debug."
        ),
    )
    parser.add_argument(
        "--ddr-worker-probe-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Enable the worker-side cert/xrootd probe task before DDR preprocess. "
            "YAML key: ddr_worker_probe_enabled."
        ),
    )
    parser.add_argument(
        "--ddr-worker-probe-url",
        default=None,
        help=(
            "ROOT URL used by the worker probe task. "
            "YAML key: ddr_worker_probe_url."
        ),
    )
    parser.add_argument(
        "--ddr-worker-probe-timeout",
        type=int,
        default=None,
        help=(
            "Probe timeout in seconds for the worker-side cert/xrootd probe. "
            "YAML key: ddr_worker_probe_timeout."
        ),
    )
    parser.add_argument(
        "--ddr-processor-key-delim",
        default="-",
        help=(
            "Delimiter used to build TaskVine DDR processor keys from "
            "(channel, variable, application, systematic_label)."
        ),
    )
    parser.add_argument(
        "--ddr-preserve-sidecars",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "When flattening DDR output, keep non-hist sidecars under a reserved key. "
            "Disabled by default."
        ),
    )
    parser.add_argument(
        "--ddr-sidecars-key",
        default="__sidecars__",
        help="Reserved top-level key used when --ddr-preserve-sidecars is enabled.",
    )
    parser.add_argument(
        "--ddr-output-schema",
        choices=("flat", "tuple"),
        default="flat",
        help=(
            "Schema used when serializing TaskVine DDR output: "
            "'flat' -> (sample, channel, var, application, systematic), "
            "'tuple' -> (var, channel, application, sample, systematic)."
        ),
    )
    parser.add_argument(
        "--ddr-step-size",
        type=int,
        default=None,
        help="Override DDR step size (events per task chunk). Defaults to --chunksize when unset.",
    )
    parser.add_argument(
        "--ddr-max-task-retries",
        type=int,
        default=None,
        help="Override DDR max task retries.",
    )
    parser.add_argument(
        "--ddr-results-directory",
        default=None,
        help="Override the DDR results directory (defaults to taskvine staging logs path).",
    )
    parser.add_argument(
        "--ddr-verbose",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable/disable verbose DDR logging at the CoffeaDynamicDataReduction layer.",
    )
    parser.add_argument(
        "--taskvine-proxy-path",
        default=None,
        help=(
            "Path to an x509 proxy file used by TaskVine DDR workers. "
            "When set, run_analysis stages it as proxy.pem. "
            "YAML key: taskvine_proxy_path."
        ),
    )
    parser.add_argument(
        "--ddr-preprocessed-data",
        default=None,
        help=(
            "Path to preprocessed DDR mapping (JSON or cloudpickle). "
            "When set, preprocess() is skipped."
        ),
    )
    parser.add_argument(
        "--ddr-save-preprocess",
        default=None,
        help=(
            "Path where run_analysis writes the DDR preprocess payload after preprocess()."
        ),
    )
    parser.add_argument(
        "--ddr-auto-save-preprocess",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Automatically save DDR preprocess payload to a deterministic artifact path "
            "when --ddr-preprocessed-data is not provided."
        ),
    )
    parser.add_argument(
        "--ddr-preprocess-artifact",
        default=None,
        help=(
            "Override the deterministic default path used by --ddr-auto-save-preprocess."
        ),
    )
    parser.add_argument(
        "--options",
        default=None,
        help=(
            "YAML file that specifies command-line options. Accepts either"
            " 'path.yml' for the default profile or 'path.yml:profile' to select"
            " a specific profile. When provided, CLI flags are ignored in favour"
            " of the YAML configuration. --options and --metadata are mutually "
            "exclusive, and passing other config flags is an error."
        ),
    )
    parser.add_argument(
        "--driver-log-path",
        default=None,
        help=(
            "Mirror run_analysis stdout/stderr to this logfile. "
            "YAML key: driver_log_path."
        ),
    )
    parser.add_argument(
        "--exit-marker-path",
        default=None,
        help=(
            "Write the final run_analysis exit status to this file. "
            "YAML key: exit_marker_path."
        ),
    )
    parser.add_argument(
        "--exit-debug",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Emit a final run_analysis exit-status debug line to stderr. "
            "YAML key: exit_debug."
        ),
    )
    parser.set_defaults(negotiate_manager_port=True)
    return parser


def _ensure_supported_executor(value: str) -> None:
    """Raise an error when ``value`` is not a supported executor."""

    if value and value not in SUPPORTED_EXECUTORS:
        raise ValueError(
            f"Unsupported executor '{value}'. "
            f"Valid options are: {', '.join(SUPPORTED_EXECUTORS)}."
        )


def _apply_scenario_metadata_defaults(
    config: RunConfig,
    metadata_cli: str | None,
) -> tuple[str, metadata_authority.MetadataBundle, str]:
    """Resolve the effective scenario and metadata selection."""

    scenario_names = config.scenario_names or ["TOP_22_006"]
    config.scenario_names = scenario_names

    if len(scenario_names) != 1:
        raise ValueError(
            "Multiple scenarios in one run are not supported yet. "
            "Requested scenarios: %s. Run them separately or wait for the "
            "future all_analysis meta-scenario." % ", ".join(scenario_names)
        )

    scenario_name = scenario_names[0]
    metadata_options = config.metadata_path if config.options_path else None
    metadata_path, provenance = metadata_authority.select_metadata_source(
        metadata_cli,
        metadata_options,
        metadata_authority.DEFAULT_METADATA_RELATIVE,
    )
    bundle = metadata_authority.load_metadata_bundle(
        metadata_path,
        scenario_name,
        strict=config.channel_groups_strict,
        required_sections=("channels", "variables"),
        metadata_source=provenance,
    )
    config.metadata_path = str(bundle.metadata_path)
    return scenario_name, bundle, provenance


def _build_equivalent_cli_call(
    config: RunConfig,
    *,
    scenario_name: str,
    metadata_path: str,
) -> str:
    """Return a deterministic equivalent CLI command without ``--options``."""

    tokens: list[str] = ["python", "analysis/topeft_run2/run_analysis.py"]
    tokens.extend(str(path) for path in config.json_files if str(path).strip())

    if config.prefix:
        tokens.extend(["--prefix", str(config.prefix)])
    if config.test:
        tokens.append("--test")
    if config.pretend:
        tokens.append("--pretend")

    tokens.extend(["--executor", str(config.executor or "taskvine")])
    tokens.extend(["--nworkers", str(config.nworkers)])
    tokens.extend(["--chunksize", str(config.chunksize)])
    if config.nchunks is not None:
        tokens.extend(["--nchunks", str(config.nchunks)])
    tokens.extend(["--outname", str(config.outname)])
    tokens.extend(["--outpath", str(config.outpath)])
    tokens.extend(["--treename", str(config.treename)])
    tokens.extend(["--processor", str(config.processor)])
    tokens.extend(["--metadata", str(metadata_path)])
    tokens.extend(["--scenario", str(scenario_name)])

    if config.do_errors:
        tokens.append("--do-errors")
    if config.do_systs:
        tokens.append("--do-systs")
    if config.split_lep_flavor:
        tokens.append("--split-lep-flavor")
    if config.skip_sr:
        tokens.append("--skip-sr")
    if config.skip_cr:
        tokens.append("--skip-cr")
    if config.do_np:
        tokens.append("--do-np")
    if config.do_renormfact_envelope:
        tokens.append("--do-renormfact-envelope")
    if config.wc_list:
        tokens.append("--wc-list")
        tokens.extend(str(value) for value in config.wc_list)
    if config.ecut is not None:
        tokens.extend(["--ecut", str(config.ecut)])
    if not config.channel_groups_strict:
        tokens.append("--allow-partial-channel-groups")

    if config.summary_verbosity:
        tokens.extend(["--summary-verbosity", str(config.summary_verbosity)])
    if config.log_level:
        tokens.extend(["--log-level", str(config.log_level).lower()])
    if config.log_tasks:
        tokens.append("--log-tasks")

    if config.port:
        tokens.extend(["--port", str(config.port)])
    if not config.negotiate_manager_port:
        tokens.append("--no-port-negotiation")
    if config.manager_name:
        tokens.extend(["--taskvine-manager-name", str(config.manager_name)])
    if config.manager_name_template:
        tokens.extend(["--taskvine-manager-name-template", str(config.manager_name_template)])
    if config.scratch_dir:
        tokens.extend(["--scratch-dir", str(config.scratch_dir)])
    if config.resource_monitor:
        tokens.extend(["--resource-monitor", str(config.resource_monitor)])
    if config.resources_mode:
        tokens.extend(["--resources-mode", str(config.resources_mode)])
    if config.environment_file:
        tokens.extend(["--environment-file", str(config.environment_file)])
    if not config.taskvine_print_stdout:
        tokens.append("--no-taskvine-print-stdout")
    if config.ddr_debug:
        tokens.append("--ddr-debug")
    if config.ddr_worker_probe_enabled:
        tokens.append("--ddr-worker-probe-enabled")
    if config.ddr_worker_probe_url:
        tokens.extend(["--ddr-worker-probe-url", str(config.ddr_worker_probe_url)])
    if config.ddr_worker_probe_timeout is not None:
        tokens.extend(["--ddr-worker-probe-timeout", str(config.ddr_worker_probe_timeout)])

    if config.futures_status is not None:
        tokens.append("--futures-status" if config.futures_status else "--no-futures-status")
    if config.futures_tail_timeout is not None:
        tokens.extend(["--futures-tail-timeout", str(config.futures_tail_timeout)])
    if config.futures_memory is not None:
        tokens.extend(["--futures-memory", str(config.futures_memory)])
    if config.futures_prefetch is not None:
        tokens.extend(["--futures-prefetch", str(config.futures_prefetch)])
    tokens.extend(["--futures-retries", str(config.futures_retries)])
    tokens.extend(["--futures-retry-wait", str(config.futures_retry_wait)])

    if config.produce_sidecars:
        tokens.append("--produce-sidecars")
    tokens.extend(["--ddr-processor-key-delim", str(config.ddr_processor_key_delim)])
    tokens.extend(["--ddr-output-schema", str(config.ddr_output_schema)])
    if config.ddr_preserve_sidecars:
        tokens.append("--ddr-preserve-sidecars")
    if config.ddr_sidecars_key and (
        config.ddr_preserve_sidecars or config.ddr_sidecars_key != "__sidecars__"
    ):
        tokens.extend(["--ddr-sidecars-key", str(config.ddr_sidecars_key)])
    if config.ddr_step_size is not None:
        tokens.extend(["--ddr-step-size", str(config.ddr_step_size)])
    if config.ddr_max_task_retries is not None:
        tokens.extend(["--ddr-max-task-retries", str(config.ddr_max_task_retries)])
    if config.ddr_results_directory:
        tokens.extend(["--ddr-results-directory", str(config.ddr_results_directory)])
    if config.ddr_verbose is not None:
        tokens.append("--ddr-verbose" if config.ddr_verbose else "--no-ddr-verbose")
    if config.ddr_x509_proxy:
        tokens.extend(["--taskvine-proxy-path", str(config.ddr_x509_proxy)])
    if config.ddr_preprocessed_data:
        tokens.extend(["--ddr-preprocessed-data", str(config.ddr_preprocessed_data)])
    if config.ddr_save_preprocess:
        tokens.extend(["--ddr-save-preprocess", str(config.ddr_save_preprocess)])
    tokens.append(
        "--ddr-auto-save-preprocess"
        if config.ddr_auto_save_preprocess
        else "--no-ddr-auto-save-preprocess"
    )
    if config.ddr_preprocess_artifact:
        tokens.extend(["--ddr-preprocess-artifact", str(config.ddr_preprocess_artifact)])
    if config.driver_log_path:
        tokens.extend(["--driver-log-path", str(config.driver_log_path)])
    if config.exit_marker_path:
        tokens.extend(["--exit-marker-path", str(config.exit_marker_path)])
    if config.exit_debug:
        tokens.append("--exit-debug")

    return " ".join(shlex.quote(token) for token in tokens)


def main(argv: Sequence[str] | None = None) -> int:
    marker_path: str | None = None
    driver_log_path: str | None = None
    exit_debug: bool = False
    status_code = 1
    try:
        _verify_numpy_abi()

        parser = build_parser()
        parser_defaults = parser.parse_args([])
        if argv is None:
            argv_list = list(sys.argv[1:])
        else:
            argv_list = list(argv)
        enforce_options_single_source(parser, argv_list, options_allowlist(parser))

        args = parser.parse_args(argv_list)

        executor_default = _normalize_executor_name(getattr(parser_defaults, "executor", ""))
        if not executor_default:
            executor_default = "taskvine"
        executor_choice = _normalize_executor_name(getattr(args, "executor", ""))
        if not executor_choice:
            executor_choice = executor_default
        setattr(args, "executor", executor_choice)

        config_builder = RunConfigBuilder(parser_defaults)
        try:
            config = config_builder.build(
                args,
                getattr(args, "options", None),
            )
        except (ValueError, TypeError, KeyError) as exc:
            parser.error(str(exc))

        marker_path = config.exit_marker_path
        driver_log_path = config.driver_log_path
        exit_debug = bool(config.exit_debug)

        metadata_cli_value = getattr(args, "metadata", None)
        if config.options_path:
            metadata_cli_value = None
        try:
            scenario_name, metadata_bundle, metadata_provenance = _apply_scenario_metadata_defaults(
                config,
                metadata_cli_value,
            )
        except (ValueError, FileNotFoundError, KeyError, TypeError) as exc:
            message = str(exc) or "Failed to resolve metadata scenario"
            parser.error(message)

        current_executor = _normalize_executor_name(getattr(config, "executor", "")) or executor_choice
        _ensure_supported_executor(current_executor)
        config.executor = current_executor

        # Currently configures logging for the driver process; futures workers keep
        # their default handlers until we plumb a per-worker hook.
        try:
            effective_log_level = configure_topeft_logging(
                config.log_level,
                executor=config.executor,
                allow_dev_debug=True,
            )
        except ValueError as exc:
            parser.error(str(exc))

        logger.info(
            "Using scenario '%s' with metadata '%s' (source: %s)",
            scenario_name,
            metadata_bundle.metadata_path,
            metadata_provenance,
        )

        with _driver_log_context(driver_log_path):
            if config.executor == "taskvine":
                ensure_taskvine_environment_file(
                    config,
                    repo_root=metadata_authority.get_repo_root(),
                )

            _log_taskvine_ddr_knob_summary(config)
            logger.info(
                "Informational (best-effort): resolved equivalent CLI without --options:\n  %s",
                _build_equivalent_cli_call(
                    config,
                    scenario_name=scenario_name,
                    metadata_path=str(metadata_bundle.metadata_path),
                ),
            )

            config.log_level = effective_log_level
            logger.info(
                "Using executor: %s | chunksize=%s | maxchunks=%s",
                config.executor,
                config.chunksize,
                config.nchunks if config.nchunks is not None else "unbounded",
            )

            if config.executor == "taskvine" and config.environment_file:
                logger.warning(
                    "TaskVine DDR Model S recommends worker '--python-env <tarball>' "
                    "submission. --environment-file=%s is still honored for this run.",
                    config.environment_file,
                )

            # Import lazily so module import stays lightweight and avoids pulling
            # optional runtime dependencies before execution is requested.
            from analysis.topeft_run2.workflow import run_workflow

            run_workflow(config, metadata_bundle=metadata_bundle)
        status_code = 0
        return status_code
    except TaskVineEnvironmentBuildError as exc:
        status_code = 2
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
        return status_code
    except KeyboardInterrupt:
        status_code = 130
        raise
    except SystemExit as exc:
        if isinstance(exc.code, int):
            status_code = int(exc.code)
        elif exc.code is None:
            status_code = 0
        else:
            status_code = 1
        raise
    finally:
        _write_exit_marker(marker_path, status_code)
        _emit_exit_debug(exit_debug, status_code)


if __name__ == "__main__":
    raise SystemExit(main())
