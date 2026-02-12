#!/usr/bin/env python

"""Command-line entrypoint for Run-2 histogram production.

Purpose:
- Parse CLI/YAML options and launch the Run-2 workflow planner/executor stack.

Inputs/outputs:
- Reads sample manifests (JSON/CFG) plus optional YAML option profiles.
- Writes tuple-keyed histogram pickles and run summaries to the configured
  output directory.

Side effects:
- Creates output files/directories and may dispatch tasks to futures/TaskVine.

How to run:
- ``python analysis/topeft_run2/run_analysis.py --help``
- ``python analysis/topeft_run2/run_analysis.py --options analysis/topeft_run2/configs/fullR2_run.yml:cr``
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
from typing import Sequence

import topcoffea

from analysis.topeft_run2 import metadata_authority


def _verify_numpy_pandas_abi() -> None:
    """Ensure pandas and NumPy load with matching binary interfaces.

    When a pandas wheel compiled against an older NumPy ABI sneaks into the
    environment, imports can fail deep inside the Run 2 workflow (for example
    during ``topeft.modules.systematics`` initialization).  Catch the issue
    early with a lightweight import and extension-module check so users see an
    actionable hint instead of an opaque crash.
    """

    try:
        np = importlib.import_module("numpy")
        pd = importlib.import_module("pandas")
    except Exception as exc:  # pragma: no cover - environment guard
        raise RuntimeError(
            "Failed to import numpy/pandas before launching the workflow. "
            "Recreate the coffea2025 environment and rebuild the TaskVine "
            "tarball before rerunning: `conda env update -f environment.yml "
            "--prune` and `python -m topcoffea.modules.remote_environment`."
        ) from exc

    try:  # pragma: no cover - environment guard
        from pandas import _libs as _pd_libs

        # Touching a compiled extension exercises the linked NumPy ABI.
        _ = _pd_libs.hashtable.Int64HashTable
    except Exception as exc:
        raise RuntimeError(
            "Detected a pandas/NumPy ABI mismatch (numpy "
            f"{np.__version__}, pandas {pd.__version__}). Recreate the "
            "coffea2025 environment and rebuild the TaskVine tarball: "
            "`conda env update -f environment.yml --prune` followed by "
            "`python -m topcoffea.modules.remote_environment`. Use the "
            "refreshed environment for both futures and TaskVine runs."
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
from topeft.modules.executor import resolve_environment_file

from analysis.topeft_run2.workflow import run_workflow
from topeft.modules.logging_config import configure_topeft_logging

logger = logging.getLogger(__name__)

remote_environment = topcoffea.modules.remote_environment

SUPPORTED_EXECUTORS: tuple[str, ...] = ("futures", "iterative", "taskvine")


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
        include_manager_name=True,
        include_manager_template=True,
        include_scratch_dir=True,
        include_resource_monitor=True,
        include_resources_mode=True,
        resource_monitor_default="measure",
        resources_mode_default="auto",
    ),
    extra_pip_local={"topeft": ["topeft", "setup.py"]},
    extra_conda=["pyyaml"],
    default_environment="cached",
)


def build_parser() -> argparse.ArgumentParser:
    """Return the CLI argument parser used by ``run_analysis.py``."""

    parser = argparse.ArgumentParser(
        description="You can customize your run",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "TaskVine workers can be launched with:\n"
            "  vine_submit_workers --python-env \"$(python -m topcoffea.modules.remote_environment)\" \\\n"
            "    --cores 4 --memory 16000 --disk 16000 -M <manager-name>\n"
            "run_analysis expects a cached remote environment tarball by default\n"
            "(--environment-file=cached). Use --environment-file auto to rebuild\n"
            "the archive on demand. Adjust the resources and manager name to\n"
            "match your deployment."
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
        "--nworkers",
        "-n",
        type=int,
        default=8,
        help="Number of workers",
    )
    parser.add_argument(
        "--chunksize",
        "-s",
        type=int,
        default=100000,
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


def _argument_supplied(
    argv: Sequence[str],
    long_opt: str,
    short_opt: str | None = None,
) -> bool:
    """Return True when ``long_opt``/``short_opt`` appear in ``argv``."""

    for token in argv:
        if token == long_opt or token.startswith(f"{long_opt}="):
            return True
        if short_opt:
            if token == short_opt:
                return True
            if token.startswith(short_opt) and token != short_opt:
                return True
    return False


def main(argv: Sequence[str] | None = None) -> None:
    _verify_numpy_pandas_abi()

    parser = build_parser()
    parser_defaults = parser.parse_args([])
    if argv is None:
        argv_list = list(sys.argv[1:])
    else:
        argv_list = list(argv)
    enforce_options_single_source(parser, argv_list, options_allowlist(parser))

    args = parser.parse_args(argv_list)

    executor_from_cli = _argument_supplied(argv_list, "--executor", "-x")
    chunksize_from_cli = _argument_supplied(argv_list, "--chunksize", "-s")
    nchunks_from_cli = _argument_supplied(argv_list, "--nchunks", "-c")
    metadata_from_cli = _argument_supplied(argv_list, "--metadata")
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

    metadata_cli_value = getattr(args, "metadata", None) if metadata_from_cli else None
    if config.options_path:
        metadata_cli_value = None
    try:
        scenario_name, metadata_bundle, metadata_provenance = _apply_scenario_metadata_defaults(
            config,
            metadata_cli_value,
        )
    except (ValueError, FileNotFoundError, KeyError, TypeError) as exc:
        message = str(exc)
        if message:
            logger.error("%s", message)
        else:
            logger.error("Failed to resolve metadata scenario")
        sys.exit(1)

    if chunksize_from_cli:
        config.chunksize = getattr(args, "chunksize", config.chunksize)
    if nchunks_from_cli:
        config.nchunks = getattr(args, "nchunks", config.nchunks)

    current_executor = _normalize_executor_name(getattr(config, "executor", ""))
    if executor_from_cli:
        current_executor = executor_choice
    elif not current_executor:
        current_executor = executor_choice
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

    config.log_level = effective_log_level
    logger.info(
        "Using executor: %s | chunksize=%s | maxchunks=%s",
        config.executor,
        config.chunksize,
        config.nchunks if config.nchunks is not None else "unbounded",
    )

    if config.executor == "taskvine":
        config.environment_file = resolve_environment_file(
            config.environment_file,
            remote_environment,
            extra_pip_local={"topeft": ["topeft", "setup.py"]},
            extra_conda=["pyyaml"],
        )

    run_workflow(config, metadata_bundle=metadata_bundle)


if __name__ == "__main__":
    main()
