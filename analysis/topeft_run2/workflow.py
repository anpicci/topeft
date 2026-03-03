"""Workflow utilities for orchestrating Run 2 analyses.

This module provides a small collection of helper classes that encapsulate the
core steps performed by :mod:`analysis.topeft_run2.run_analysis`.  The helpers
are designed to be lightweight wrappers around the existing functionality while
making the orchestration of a run easier to understand and reuse from Python
code.  The main entry point is :class:`RunWorkflow` together with the
``run_workflow`` convenience function.  A detailed walkthrough of the execution
flow, systematic catalogue, and extension hooks lives in
``docs/analysis_processing.md``.

During planning the workflow records every histogram combination that will be
submitted to Coffea.  Each entry tracks the ``(sample, channel, variable,
application, systematic)`` tuple that uniquely identifies a histogram fill.
The combinations are exposed through :class:`HistogramPlan` and printed just
before task submission.  The ``summary_verbosity`` configuration controls
whether no summary (``"none"``), only a table (``"brief"``), or both a table
and structured YAML/JSON dump (``"full"``) are emitted.  When the
``log_tasks`` flag is enabled, the futures executor also emits a concise
single-line log echoing the identifying tuple for each submitted histogram
task.
"""

from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
import getpass
import gzip
import importlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import warnings
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from functools import partial, wraps
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
    Set,
    Tuple,
)

import numpy as np
import topcoffea

from topeft.modules.channel_metadata import build_channel_label
from topeft.modules.executor import (
    _is_port_allocation_error,
    _select_manager_port,
    build_futures_executor,
    build_taskvine_args,
    futures_runner_overrides,
    instantiate_taskvine_executor,
    parse_port_range,
    resolve_environment_file,
    taskvine_log_configurator,
)
from topeft.modules import remote_environment as topeft_remote_environment
from topeft.modules.logging_config import dev_debug_enabled
from topeft.modules.runner_output import normalise_runner_output, tuple_dict_stats

logger = logging.getLogger(__name__)
_DEV_DEBUG = dev_debug_enabled()
_DDR_DEBUG_T0: Optional[float] = None
_DDR_DEBUG_RUN_INFO_PATH: Optional[Path] = None
_DEFAULT_DDR_CERT_PROBE_URL = (
    "root://cmsxrootd.crc.nd.edu//store/user/awightma/skims/mc/new-lepMVA-v2/"
    "central_bkgd_p5/fix_ext_stats_jsons/v1/UL18_WWW_4F/output_157.root"
)


def _topeft_ddr_debug_enabled() -> bool:
    value = os.environ.get("TOPEFT_DDR_DEBUG")
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _set_ddr_debug_context(
    *,
    t0: Optional[float] = None,
    run_info_path: Optional[Path] = None,
) -> None:
    global _DDR_DEBUG_T0
    global _DDR_DEBUG_RUN_INFO_PATH
    if t0 is not None:
        _DDR_DEBUG_T0 = float(t0)
    if run_info_path is not None:
        _DDR_DEBUG_RUN_INFO_PATH = Path(run_info_path)


def _clear_ddr_debug_context() -> None:
    global _DDR_DEBUG_T0
    global _DDR_DEBUG_RUN_INFO_PATH
    _DDR_DEBUG_T0 = None
    _DDR_DEBUG_RUN_INFO_PATH = None


def _resolve_run_info_paths(run_info_path: Path) -> Dict[str, str]:
    run_info_root = Path(run_info_path)
    most_recent_target: Optional[Path] = None
    newest_run_info: Optional[Path] = None

    most_recent_link = run_info_root / "most-recent"
    try:
        if most_recent_link.exists():
            resolved = most_recent_link.resolve()
            if resolved.is_dir():
                most_recent_target = resolved
    except Exception:
        most_recent_target = None

    if run_info_root.exists() and run_info_root.is_dir():
        candidates: List[Path] = []
        for entry in run_info_root.iterdir():
            if not entry.is_dir():
                continue
            if entry.name in {"most-recent", "vine-cache"}:
                continue
            if entry.is_symlink():
                continue
            candidates.append(entry)
        if candidates:
            newest_run_info = max(candidates, key=lambda item: item.stat().st_mtime)

    chosen_run_info = most_recent_target or newest_run_info
    tx_most_recent = (
        str(most_recent_target / "vine-logs" / "transactions")
        if most_recent_target is not None
        else "<none>"
    )
    tx_newest = (
        str(newest_run_info / "vine-logs" / "transactions")
        if newest_run_info is not None
        else "<none>"
    )
    transactions_path = (
        str(chosen_run_info / "vine-logs" / "transactions")
        if chosen_run_info is not None
        else "<none>"
    )
    return {
        "run_info_path": str(run_info_root),
        "most_recent": str(most_recent_target) if most_recent_target is not None else "<none>",
        "tx_most_recent": tx_most_recent,
        "newest_run_info": str(newest_run_info) if newest_run_info is not None else "<none>",
        "tx_newest": tx_newest,
        "transactions_path": transactions_path,
    }


def _count_transaction_tokens(transactions_path: Path) -> Tuple[int, int, int]:
    if not transactions_path.exists() or not transactions_path.is_file():
        return (0, 0, 0)

    category_lines = 0
    processing_tokens = 0
    accumulating_tokens = 0
    with transactions_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if "CATEGORY " in line:
                category_lines += 1
            processing_tokens += line.count("processing#")
            accumulating_tokens += line.count("accumulating#")
    return category_lines, processing_tokens, accumulating_tokens


def _emit_transactions_snapshot(context: str) -> None:
    if not _topeft_ddr_debug_enabled():
        return
    if _DDR_DEBUG_RUN_INFO_PATH is None:
        _ddr_debug_emit(
            f"transactions_snapshot context={context} run_info_path=<none>",
            include_paths=False,
        )
        return

    resolved_paths = _resolve_run_info_paths(_DDR_DEBUG_RUN_INFO_PATH)
    tx_path_str = resolved_paths.get("transactions_path", "<none>")
    tx_path = Path(tx_path_str) if tx_path_str != "<none>" else None
    category_lines = 0
    processing_tokens = 0
    accumulating_tokens = 0
    if tx_path is not None:
        category_lines, processing_tokens, accumulating_tokens = _count_transaction_tokens(
            tx_path
        )

    _ddr_debug_emit(
        "transactions_snapshot "
        f"context={context} "
        f"final_transactions_path={tx_path_str} "
        f"category_lines={category_lines} "
        f"processing_tokens={processing_tokens} "
        f"accumulating_tokens={accumulating_tokens}",
        include_paths=True,
    )


def _ddr_debug_emit(message: str, *, include_paths: bool = False) -> None:
    if not _topeft_ddr_debug_enabled():
        return
    ts_unix = time.time()
    if _DDR_DEBUG_T0 is None:
        dt_text = "na"
    else:
        dt_text = f"{ts_unix - _DDR_DEBUG_T0:.3f}"
    prefix = f"ts_unix={ts_unix:.3f} dt_since_ddr_start_s={dt_text}"
    if _DDR_DEBUG_RUN_INFO_PATH is not None:
        prefix += f" run_info_path={_DDR_DEBUG_RUN_INFO_PATH}"
        if include_paths:
            resolved_paths = _resolve_run_info_paths(_DDR_DEBUG_RUN_INFO_PATH)
            prefix += (
                f" most_recent={resolved_paths['most_recent']}"
                f" tx_most_recent={resolved_paths['tx_most_recent']}"
                f" newest_run_info={resolved_paths['newest_run_info']}"
                f" tx_newest={resolved_paths['tx_newest']}"
                f" transactions_path={resolved_paths['transactions_path']}"
            )
    print(f"[TOPEFT_DDR_DEBUG] {prefix} {message}", file=sys.stderr, flush=True)


def _env_flag_enabled(name: str) -> bool:
    value = os.environ.get(name)
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _trim_probe_text(text: str, *, limit: int = 12000) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]} ... <truncated {len(text) - limit} chars>"


def _json_safe_payload(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_payload(item) for item in value]
    return str(value)


def _decode_probe_stream(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def _build_ddr_worker_probe_command() -> str:
    return """set -eu
echo "[DDR_WORKER_PROBE] whoami=$(whoami 2>/dev/null || true)"
echo "[DDR_WORKER_PROBE] hostname=$(hostname 2>/dev/null || true)"
echo "[DDR_WORKER_PROBE] pwd=$(pwd)"
echo "[DDR_WORKER_PROBE] env_X509_USER_PROXY=${X509_USER_PROXY:-<unset>}"
echo "[DDR_WORKER_PROBE] env_X509_CERT_DIR=${X509_CERT_DIR:-<unset>}"
echo "[DDR_WORKER_PROBE] env_OASIS_CERTIFICATES=${OASIS_CERTIFICATES:-<unset>}"
echo "[DDR_WORKER_PROBE] env_HOME=${HOME:-<unset>}"
echo "[DDR_WORKER_PROBE] env_USER=${USER:-<unset>}"
echo "[DDR_WORKER_PROBE] ls_cwd_begin"
ls -lah || true
echo "[DDR_WORKER_PROBE] ls_cwd_end"
if [ -n "${X509_USER_PROXY:-}" ]; then
  ls -lah "$X509_USER_PROXY" || true
else
  echo "[DDR_WORKER_PROBE] X509_USER_PROXY missing"
fi
ls -lah proxy.pem || true
if [ -n "${X509_CERT_DIR:-}" ]; then
  ls -lah "$X509_CERT_DIR" || true
else
  echo "[DDR_WORKER_PROBE] X509_CERT_DIR missing"
fi
ls -lah /cvmfs/oasis.opensciencegrid.org/mis/certificates || true
echo "[DDR_WORKER_PROBE] which_xrdcp=$(command -v xrdcp || echo missing)"
if command -v xrdcp >/dev/null 2>&1; then
  xrdcp --version || true
fi
python - <<'PY'
import os
import traceback

url = os.environ.get("TOPEFT_DDR_PROBE_URL", "").strip()
print(f"[DDR_WORKER_PROBE] test_url={url or '<unset>'}")
try:
    import sys
    print(f"[DDR_WORKER_PROBE] python={sys.executable}")
except Exception:
    pass

if not url:
    raise RuntimeError("TOPEFT_DDR_PROBE_URL is unset")

try:
    import uproot
    tree = uproot.open(f"{url}:Events")
    entries = int(getattr(tree, "num_entries"))
    print(f"[DDR_WORKER_PROBE] uproot_open_ok=1 num_entries={entries}")
except Exception as exc:
    print(f"[DDR_WORKER_PROBE] uproot_open_ok=0 error={exc.__class__.__name__}: {exc}")
    traceback.print_exc()
    raise
PY
"""


def _resolve_ddr_probe_report_path(run_info_path: Path) -> Path:
    resolved = _resolve_run_info_paths(Path(run_info_path))
    for key in ("newest_run_info", "most_recent"):
        candidate = resolved.get(key, "<none>")
        if candidate and candidate != "<none>":
            base = Path(candidate)
            logs_dir = base / "vine-logs"
            if logs_dir.exists() and logs_dir.is_dir():
                return logs_dir / "ddr_worker_probe.txt"
            return base / "ddr_worker_probe.txt"
    return Path(run_info_path) / "ddr_worker_probe.txt"


def _resolve_ddr_probe_output_paths(run_info_path: Path) -> Dict[str, Path]:
    report_path = _resolve_ddr_probe_report_path(run_info_path)
    logs_dir = report_path.parent
    return {
        "report_path": report_path,
        "stdout_path": logs_dir / "worker_probe.stdout",
        "stderr_path": logs_dir / "worker_probe.stderr",
    }


def _write_ddr_probe_streams(
    run_info_path: Path,
    *,
    stdout_text: str,
    stderr_text: str,
) -> Mapping[str, str]:
    output_paths = _resolve_ddr_probe_output_paths(run_info_path)
    stdout_path = output_paths["stdout_path"]
    stderr_path = output_paths["stderr_path"]
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_path.write_text(stdout_text or "", encoding="utf-8")
    stderr_path.write_text(stderr_text or "", encoding="utf-8")
    return {
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }


def _write_ddr_probe_report(run_info_path: Path, payload: Mapping[str, Any]) -> Path:
    output_path = _resolve_ddr_probe_output_paths(run_info_path)["report_path"]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    safe_payload = _json_safe_payload(payload)
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write("[DDR_WORKER_PROBE] begin\n")
        for key in (
            "status",
            "successful",
            "task_id",
            "result",
            "exit_code",
            "hostname",
            "stdout_path",
            "stderr_path",
        ):
            if key in safe_payload:
                handle.write(f"[DDR_WORKER_PROBE] {key}={safe_payload.get(key)}\n")
        handle.write("[DDR_WORKER_PROBE] payload_json_begin\n")
        json.dump(safe_payload, handle, indent=2, sort_keys=True)
        handle.write("\n[DDR_WORKER_PROBE] payload_json_end\n")
    return output_path


def _run_ddr_worker_cert_probe_task(
    manager: Any,
    *,
    extra_files: Sequence[str],
    environment_variables: Mapping[str, str],
    run_info_path: Path,
    test_url: str,
    timeout_seconds: int = 20,
) -> Mapping[str, Any]:
    import ndcctools.taskvine as vine

    probe_command = _build_ddr_worker_probe_command()
    task = vine.Task(probe_command)
    task.set_tag("ddr-worker-cert-probe")
    task.set_category("ddr-worker-cert-probe")
    task.set_cores(1)
    task.set_memory(1024)
    task.set_disk(512)
    task.set_time_max(max(60, int(timeout_seconds) * 3))

    staging_errors: List[str] = []
    for path in extra_files:
        try:
            declared = manager.declare_file(str(path), cache=True)
            task.add_input(declared, Path(path).name)
        except Exception as exc:
            staging_errors.append(f"{path}: {exc.__class__.__name__}: {exc}")

    for key, value in (environment_variables or {}).items():
        task.set_env_var(str(key), str(value))
    task.set_env_var("TOPEFT_DDR_PROBE_URL", str(test_url))
    task.set_env_var("TOPEFT_DDR_PROBE_TIMEOUT", str(int(timeout_seconds)))

    task_id = int(manager.submit(task))
    deadline = time.time() + max(120, int(timeout_seconds) * 4)
    completed_task = None
    while time.time() < deadline:
        candidate = manager.wait(5)
        if candidate is None:
            continue
        if int(getattr(candidate, "id", -1)) != task_id:
            continue
        completed_task = candidate
        break

    result: Dict[str, Any] = {
        "task_id": task_id,
        "status": "timeout" if completed_task is None else "completed",
        "command": probe_command,
        "staging_errors": staging_errors,
        "environment_variables": dict(environment_variables or {}),
    }
    if completed_task is None:
        stream_paths = _write_ddr_probe_streams(
            run_info_path,
            stdout_text="",
            stderr_text="",
        )
        result.update(stream_paths)
        report_path = _write_ddr_probe_report(run_info_path, result)
        result["report_path"] = str(report_path)
        return result

    result["successful"] = bool(completed_task.successful())
    result["result"] = str(getattr(completed_task, "result", None))
    result["exit_code"] = getattr(completed_task, "exit_code", None)
    result["hostname"] = getattr(completed_task, "hostname", None)
    stdout_raw = None
    stderr_raw = None
    try:
        stdout_raw = completed_task.std_output
    except Exception as exc:
        result["std_output_error"] = f"{exc.__class__.__name__}: {exc}"
    if stdout_raw is None:
        try:
            stdout_raw = completed_task.output
        except Exception as exc:
            result["output_error"] = f"{exc.__class__.__name__}: {exc}"
    try:
        stderr_raw = completed_task.std_error
    except Exception:
        stderr_raw = None

    stdout_text = _trim_probe_text(_decode_probe_stream(stdout_raw), limit=200000)
    stderr_text = _trim_probe_text(_decode_probe_stream(stderr_raw), limit=200000)
    stream_paths = _write_ddr_probe_streams(
        run_info_path,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
    )
    result.update(stream_paths)
    result["output_preview"] = _trim_probe_text(stdout_text, limit=12000)
    if stderr_text:
        result["stderr_preview"] = _trim_probe_text(stderr_text, limit=12000)

    report_path = _write_ddr_probe_report(run_info_path, result)
    result["report_path"] = str(report_path)
    return result


def _resolve_processor_file_path(processor: str | Path) -> Path:
    """Resolve the configured processor module path to an existing ``.py`` file."""

    raw_value = str(processor).strip() if processor is not None else ""
    if not raw_value:
        raise ValueError("Processor path is empty. Pass --processor <module.py>.")

    candidate = Path(raw_value).expanduser()
    if candidate.suffix.lower() != ".py":
        raise ValueError(
            f"Processor path must point to a .py file, received: {candidate}."
        )

    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        search_roots = (
            Path.cwd(),
            Path(__file__).resolve().parent,
        )
        resolved = None
        for root in search_roots:
            probe = (root / candidate).resolve()
            if probe.exists():
                resolved = probe
                break
        if resolved is None:
            searched = ", ".join(str(root) for root in search_roots)
            raise FileNotFoundError(
                f"Processor file '{candidate}' was not found. Searched roots: {searched}."
            )

    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(f"Processor file does not exist: {resolved}.")
    return resolved


def _load_processor_module_from_file(
    processor_file: Path,
    *,
    required_symbol: str = "AnalysisProcessor",
) -> Tuple[Any, str]:
    """Import the processor module by filename stem and validate its symbol."""

    module_name = processor_file.stem
    module_dir = str(processor_file.parent)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)

    existing = sys.modules.get(module_name)
    existing_file = getattr(existing, "__file__", None) if existing is not None else None
    if existing_file:
        try:
            if Path(existing_file).resolve() != processor_file.resolve():
                del sys.modules[module_name]
        except Exception:
            del sys.modules[module_name]

    importlib.invalidate_caches()
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        raise ImportError(
            f"Failed to import processor module '{module_name}' from {processor_file}."
        ) from exc

    if not hasattr(module, required_symbol):
        public_attrs = [name for name in dir(module) if not name.startswith("_")]
        attr_preview = ", ".join(public_attrs[:20]) if public_attrs else "<none>"
        raise AttributeError(
            f"Processor module '{module_name}' from {processor_file} does not define "
            f"'{required_symbol}'. Public attributes: {attr_preview}"
        )

    return module, module_name


def _collect_processor_extra_files(processor_file: Path) -> List[str]:
    """Collect processor-adjacent python files to stage with DDR tasks."""

    processor_file = processor_file.resolve()
    processor_dir = processor_file.parent
    path_candidates: List[Path] = [processor_file]

    for module_path in sorted(processor_dir.glob("analysis_processor*.py")):
        if module_path.name == "__init__.py":
            continue
        path_candidates.append(module_path.resolve())

    helpers_dir = processor_dir / "analysis_processor_helpers"
    if helpers_dir.is_dir():
        for helper_path in sorted(helpers_dir.rglob("*.py")):
            if helper_path.name == "__init__.py":
                continue
            path_candidates.append(helper_path.resolve())

    dedup_by_path: List[Path] = []
    seen_paths: Set[Path] = set()
    for path in path_candidates:
        if path in seen_paths:
            continue
        seen_paths.add(path)
        dedup_by_path.append(path)

    staged_paths = [str(path) for path in dedup_by_path]
    _validate_staged_basename_collisions(
        staged_paths,
        context="TaskVine DDR processor staging",
    )

    processor_file_str = str(processor_file)
    ordered: List[str] = []
    if processor_file_str in staged_paths:
        ordered.append(processor_file_str)
    ordered.extend(
        path
        for path in sorted(staged_paths, key=lambda item: Path(item).name)
        if path != processor_file_str
    )
    return ordered


def _canonical_staged_path(entry: str | Path) -> str:
    return str(Path(entry).expanduser().resolve(strict=False))


def _deduplicate_staged_paths(entries: Iterable[str | Path]) -> List[str]:
    deduplicated: List[str] = []
    seen: Set[str] = set()
    for entry in entries:
        canonical = _canonical_staged_path(entry)
        if canonical in seen:
            continue
        seen.add(canonical)
        deduplicated.append(canonical)
    return deduplicated


def _validate_staged_basename_collisions(
    entries: Iterable[str | Path],
    *,
    context: str,
) -> None:
    basenames: Dict[str, Set[str]] = {}
    for entry in entries:
        canonical = _canonical_staged_path(entry)
        basenames.setdefault(Path(canonical).name, set()).add(canonical)

    collisions = {
        basename: sorted(paths)
        for basename, paths in basenames.items()
        if len(paths) > 1
    }
    if not collisions:
        return

    lines = [
        f"Basename collision detected in {context}.",
        "TaskVine stages extra files by basename, so each staged file must have a unique filename.",
    ]
    for basename, paths in sorted(collisions.items()):
        lines.append(f"basename={basename}")
        lines.extend(f"  path={path}" for path in paths)
    lines.append(
        "Remediation: rename colliding files or move them so staged basenames are unique."
    )
    raise ValueError("\n".join(lines))


def _safe_manager_call(manager: Any, attr: str) -> Any:
    value = getattr(manager, attr, None)
    if callable(value):
        try:
            return value()
        except Exception:
            return "<call-failed>"
    return value


def _summarize_ddr_input(data: Mapping[str, Any]) -> Tuple[int, int, Optional[int]]:
    dataset_count = len(data)
    total_files = 0
    total_entries = 0
    saw_entries = False
    for dataset_specs in data.values():
        files = dataset_specs.get("files") if isinstance(dataset_specs, Mapping) else None
        if not isinstance(files, Mapping):
            continue
        total_files += len(files)
        for file_info in files.values():
            if not isinstance(file_info, Mapping):
                continue
            num_entries = file_info.get("num_entries")
            if isinstance(num_entries, (int, float)) and not isinstance(num_entries, bool):
                total_entries += int(num_entries)
                saw_entries = True
    return dataset_count, total_files, total_entries if saw_entries else None


def _emit_ddr_knob_message(message: str) -> None:
    if _topeft_ddr_debug_enabled():
        _ddr_debug_emit(message)
    else:
        logger.info(message)


@contextmanager
def _ddr_debug_stage(stage: str, *, details: Optional[str] = None) -> Iterator[None]:
    """Emit begin/end markers for debug-only DDR stages."""

    debug_enabled = _topeft_ddr_debug_enabled()
    started = time.monotonic()
    if debug_enabled:
        suffix = f" {details}" if details else ""
        _ddr_debug_emit(f"stage={stage} begin{suffix}", include_paths=True)

    succeeded = False
    try:
        yield
        succeeded = True
    except Exception as exc:
        if debug_enabled:
            _ddr_debug_emit(
                f"stage={stage} exception type={exc.__class__.__name__} message={exc}",
                include_paths=True,
            )
            traceback.print_exc(file=sys.stderr)
        raise
    finally:
        if debug_enabled:
            elapsed_seconds = time.monotonic() - started
            status = "end" if succeeded else "end_error"
            _ddr_debug_emit(
                f"stage={stage} {status} elapsed_seconds={elapsed_seconds:.3f}",
                include_paths=True,
            )


def _parse_ddr_processor_slice(raw_slice: str) -> Optional[Tuple[Optional[int], Optional[int]]]:
    """Parse ``TOPEFT_DDR_PROCESSOR_SLICE`` values of the form ``start:stop``."""

    if ":" not in raw_slice:
        _emit_ddr_knob_message(
            "Ignoring TOPEFT_DDR_PROCESSOR_SLICE: expected 'start:stop' syntax, "
            f"received {raw_slice!r}."
        )
        return None

    start_text, stop_text = raw_slice.split(":", 1)
    try:
        start = int(start_text) if start_text.strip() else None
        stop = int(stop_text) if stop_text.strip() else None
    except ValueError:
        _emit_ddr_knob_message(
            "Ignoring TOPEFT_DDR_PROCESSOR_SLICE: non-integer bound in "
            f"{raw_slice!r}."
        )
        return None

    if start is not None and start < 0:
        _emit_ddr_knob_message(
            "Ignoring TOPEFT_DDR_PROCESSOR_SLICE: start must be >= 0, "
            f"received {start}."
        )
        return None
    if stop is not None and stop < 0:
        _emit_ddr_knob_message(
            "Ignoring TOPEFT_DDR_PROCESSOR_SLICE: stop must be >= 0, "
            f"received {stop}."
        )
        return None

    return start, stop


def _apply_ddr_processor_subset(processors: Mapping[str, Any]) -> Dict[str, Any]:
    """Apply deterministic prefix/slice filtering to processor mappings.

    Precedence is fixed as:
    1) ``TOPEFT_DDR_PROCESSOR_KEY_PREFIX``
    2) ``TOPEFT_DDR_PROCESSOR_SLICE``
    3) ``TOPEFT_DDR_MAX_PROCESSORS`` (applied later by caller)
    """

    processors_dict = dict(processors)
    raw_prefix = os.environ.get("TOPEFT_DDR_PROCESSOR_KEY_PREFIX")
    raw_slice = os.environ.get("TOPEFT_DDR_PROCESSOR_SLICE")
    if raw_prefix is None and raw_slice is None:
        return processors_dict

    sorted_items = sorted(processors_dict.items(), key=lambda item: str(item[0]))
    original_count = len(sorted_items)
    filtered_items = sorted_items

    prefix_value = raw_prefix if raw_prefix is not None else None
    if prefix_value is not None:
        filtered_items = [
            (key, value)
            for key, value in filtered_items
            if str(key).startswith(prefix_value)
        ]
    after_prefix_count = len(filtered_items)

    applied_slice = None
    if raw_slice is not None:
        slice_spec = str(raw_slice).strip()
        parsed_bounds = _parse_ddr_processor_slice(slice_spec)
        if parsed_bounds is not None:
            start, stop = parsed_bounds
            filtered_items = filtered_items[slice(start, stop)]
            applied_slice = slice_spec
        else:
            applied_slice = f"invalid:{slice_spec!r}"

    after_slice_count = len(filtered_items)
    first_keys = (
        ", ".join(str(key) for key, _ in filtered_items[:5])
        if filtered_items
        else "<none>"
    )
    _emit_ddr_knob_message(
        "Applied TOPEFT_DDR_PROCESSOR_SUBSET "
        f"order=prefix->slice->max "
        f"original={original_count} "
        f"after_prefix={after_prefix_count} "
        f"after_slice={after_slice_count} "
        f"prefix={prefix_value!r} "
        f"slice={applied_slice!r} "
        f"first_keys=[{first_keys}]"
    )
    return {key: value for key, value in filtered_items}


def _format_ddr_task_label(task: Any) -> str:
    if task is None:
        return "<none>"
    description = getattr(task, "description", None)
    if callable(description):
        try:
            desc = str(description())
        except Exception:
            desc = "<description-failed>"
    else:
        desc = str(task)

    task_dataset = getattr(getattr(task, "dataset", None), "name", None)
    if task_dataset is not None:
        desc = f"{desc} dataset={task_dataset}"
    return desc


def _wrap_ddr_stage_method(
    original: Any,
    *,
    stage: str,
    details_getter: Optional[Any] = None,
) -> Any:
    """Wrap a DDR instance method with stage begin/end markers."""

    @wraps(original)
    def wrapped(instance, *args, **kwargs):
        details_text = None
        if callable(details_getter):
            try:
                details_text = details_getter(instance, args, kwargs)
            except Exception as exc:
                details_text = f"details_error={exc.__class__.__name__}:{exc}"

        with _ddr_debug_stage(stage, details=details_text):
            return original(instance, *args, **kwargs)

    return wrapped


def _wrap_ddr_generate_processing_args(original: Any) -> Any:
    """Wrap ``generate_processing_args`` to expose task materialization boundaries."""

    @wraps(original)
    def wrapped(instance, datasets, *args, **kwargs):
        dataset_count = len(datasets) if isinstance(datasets, Mapping) else "<unknown>"
        with _ddr_debug_stage(
            "task_materialization",
            details=f"datasets={dataset_count}",
        ):
            yielded = 0
            try:
                for item in original(instance, datasets, *args, **kwargs):
                    yielded += 1
                    if yielded <= 3 or yielded % 5000 == 0:
                        if _topeft_ddr_debug_enabled():
                            processor_name = "<unknown>"
                            dataset_name = "<unknown>"
                            if isinstance(item, tuple) and len(item) >= 2:
                                processor_name = str(getattr(item[0], "name", "<unknown>"))
                                dataset_name = str(getattr(item[1], "name", "<unknown>"))
                            _ddr_debug_emit(
                                "stage=task_materialization yielded "
                                f"count={yielded} processor={processor_name} dataset={dataset_name}"
                            )
                    yield item
            except Exception as exc:
                if _topeft_ddr_debug_enabled():
                    _ddr_debug_emit(
                        "stage=task_materialization exception "
                        f"type={exc.__class__.__name__} message={exc}"
                    )
                    traceback.print_exc(file=sys.stderr)
                raise
            finally:
                if _topeft_ddr_debug_enabled():
                    _ddr_debug_emit(
                        f"stage=task_materialization summary yielded={yielded}"
                    )

    return wrapped


def _wrap_ddr_submit_method(original: Any) -> Any:
    """Wrap ``submit`` to expose task submission boundaries with light rate limiting."""

    @wraps(original)
    def wrapped(instance, task, *args, **kwargs):
        submit_calls = int(getattr(instance, "_topeft_ddr_submit_calls", 0)) + 1
        setattr(instance, "_topeft_ddr_submit_calls", submit_calls)
        should_emit = submit_calls <= 10 or submit_calls % 100 == 0
        label = _format_ddr_task_label(task)

        if should_emit and _topeft_ddr_debug_enabled():
            _ddr_debug_emit(
                "stage=submission_to_manager begin "
                f"submit_call={submit_calls} task={label}"
            )

        try:
            task_id = original(instance, task, *args, **kwargs)
        except Exception as exc:
            if _topeft_ddr_debug_enabled():
                _ddr_debug_emit(
                    "stage=submission_to_manager exception "
                    f"submit_call={submit_calls} task={label} "
                    f"type={exc.__class__.__name__} message={exc}"
                )
                traceback.print_exc(file=sys.stderr)
            raise

        if should_emit and _topeft_ddr_debug_enabled():
            _ddr_debug_emit(
                "stage=submission_to_manager end "
                f"submit_call={submit_calls} task_id={task_id}"
            )
        return task_id

    return wrapped


@contextmanager
def _instrument_ddr_runtime_stages(ddr_helpers: Any) -> Iterator[None]:
    """Temporarily instrument DDR internals for TOPEFT debug runs."""

    if not _topeft_ddr_debug_enabled():
        yield
        return

    ddr_cls = getattr(ddr_helpers, "CoffeaDynamicDataReduction", None)
    if ddr_cls is None:
        _ddr_debug_emit(
            "stage=runtime_instrumentation skipped reason=missing_CoffeaDynamicDataReduction"
        )
        yield
        return

    patched_methods: List[Tuple[str, Any]] = []

    def _patch(method_name: str, wrapper: Any) -> None:
        original = getattr(ddr_cls, method_name, None)
        if not callable(original):
            _ddr_debug_emit(
                f"stage=runtime_instrumentation missing_method={method_name}"
            )
            return
        setattr(ddr_cls, method_name, wrapper(original))
        patched_methods.append((method_name, original))

    _patch(
        "_set_resources",
        lambda original: _wrap_ddr_stage_method(
            original,
            stage="category_creation",
            details_getter=lambda instance, _args, _kwargs: (
                f"datasets={len(instance.data.get('datasets', {}))}"
            ),
        ),
    )
    _patch("generate_processing_args", _wrap_ddr_generate_processing_args)
    _patch("submit", _wrap_ddr_submit_method)
    _patch(
        "compute",
        lambda original: _wrap_ddr_stage_method(
            original,
            stage="compute",
            details_getter=lambda instance, _args, _kwargs: (
                f"processors={len(getattr(instance, 'processors', {}))} "
                f"datasets={len(getattr(instance, 'data', {}).get('datasets', {}))}"
            ),
        ),
    )

    patched_names = ", ".join(name for name, _ in patched_methods) or "<none>"
    _ddr_debug_emit(
        f"stage=runtime_instrumentation begin patched_methods={patched_names}"
    )
    try:
        yield
    finally:
        for method_name, original in reversed(patched_methods):
            setattr(ddr_cls, method_name, original)
        _ddr_debug_emit("stage=runtime_instrumentation end")


def _ddr_probe_processor(events, **_kwargs):
    return {"n_events": int(len(events))}


def _build_ddr_probe_processor():
    try:
        from analysis.topeft_run2.run_processor_vineReduce_light import (
            _build_probe_processor as _light_probe_builder,
        )
    except Exception as exc:
        _emit_ddr_knob_message(
            "TOPEFT_DDR_USE_PROBE_PROCESSOR=1: using local probe processor "
            f"(light-runner import failed: {exc.__class__.__name__}: {exc})"
        )
        return _ddr_probe_processor

    try:
        probe = _light_probe_builder()
    except Exception as exc:
        _emit_ddr_knob_message(
            "TOPEFT_DDR_USE_PROBE_PROCESSOR=1: using local probe processor "
            f"(light-runner builder failed: {exc.__class__.__name__}: {exc})"
        )
        return _ddr_probe_processor

    if not callable(probe):
        _emit_ddr_knob_message(
            "TOPEFT_DDR_USE_PROBE_PROCESSOR=1: using local probe processor "
            "(light-runner probe is not callable)"
        )
        return _ddr_probe_processor

    _emit_ddr_knob_message(
        "TOPEFT_DDR_USE_PROBE_PROCESSOR=1: using probe processor imported from light runner."
    )
    return probe


def _apply_ddr_processor_limit(processors: Mapping[str, Any]) -> Dict[str, Any]:
    raw_limit = os.environ.get("TOPEFT_DDR_MAX_PROCESSORS")
    processors_dict = dict(processors)
    if raw_limit is None:
        return processors_dict

    raw_limit = str(raw_limit).strip()
    try:
        max_processors = int(raw_limit)
    except ValueError:
        _emit_ddr_knob_message(
            "Ignoring TOPEFT_DDR_MAX_PROCESSORS: expected integer > 0, "
            f"received {raw_limit!r}."
        )
        return processors_dict

    if max_processors <= 0:
        _emit_ddr_knob_message(
            "Ignoring TOPEFT_DDR_MAX_PROCESSORS: expected integer > 0, "
            f"received {max_processors}."
        )
        return processors_dict

    sorted_keys = sorted(processors_dict)
    limited_keys = sorted_keys[:max_processors]
    limited = {key: processors_dict[key] for key in limited_keys}
    first_keys = ", ".join(str(key) for key in limited_keys[:5]) if limited_keys else "<none>"
    max_key_len = max((len(str(key)) for key in limited_keys), default=0)
    _emit_ddr_knob_message(
        "Applied TOPEFT_DDR_MAX_PROCESSORS "
        f"original={len(processors_dict)} limited={len(limited)} "
        f"first_keys=[{first_keys}] max_key_len={max_key_len}"
    )
    return limited


def _emit_ddr_processor_key_sanity(processors: Mapping[str, Any]) -> None:
    if not _topeft_ddr_debug_enabled():
        return

    keys = [str(key) for key in processors]
    hash_keys = [key for key in keys if "#" in key]
    newline_keys = [key for key in keys if ("\n" in key or "\r" in key)]
    max_key_len = max((len(key) for key in keys), default=0)
    _ddr_debug_emit(
        "processor_key_sanity "
        f"total={len(keys)} "
        f"keys_with_hash={len(hash_keys)} "
        f"keys_with_newline={len(newline_keys)} "
        f"max_key_len={max_key_len}"
    )
    if hash_keys:
        _ddr_debug_emit(
            "processor_key_sanity hash_examples="
            + ", ".join(repr(key) for key in hash_keys[:3])
        )
    if newline_keys:
        _ddr_debug_emit(
            "processor_key_sanity newline_examples="
            + ", ".join(repr(key) for key in newline_keys[:3])
        )


def _import_topcoffea_submodule(submodule: str):
    module_name = f"{topcoffea.__name__}.modules.{submodule}"
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise ImportError(
            (
                "Unable to import required topcoffea helper module '%s'. "
                "Ensure the sibling topcoffea checkout is available and on the "
                "coordinated ref for this topeft checkout. See "
                "topcoffea/docs/topeft_integration.md for compatibility policy."
            )
            % module_name
        ) from exc


def _merge_region_yields(
    target: Dict[Tuple[str, str, str, str], np.ndarray],
    incoming: Mapping[Tuple[str, str, str, str], Any],
) -> None:
    """Accumulate region yield arrays into ``target`` in place."""

    if not incoming:
        return
    for key, value in incoming.items():
        arr = np.asarray(value, dtype=float)
        current = target.get(key)
        if current is None:
            target[key] = arr
        else:
            target[key] = np.asarray(current, dtype=float) + arr


def _normalise_systematic_label(systematic: Any) -> str:
    """Return a stable string representation for systematic labels."""

    if isinstance(systematic, (tuple, list)):
        return ":".join(str(component) for component in systematic)
    return str(systematic)


def build_ddr_processor_key(
    channel: Any,
    variable: Any,
    application: Any,
    systematic_label: Any,
    *,
    delim: str = "-",
) -> str:
    """Build a delimiter-safe DDR processor key.

    The key layout is:
    ``<channel><DELIM><var><DELIM><application><DELIM><systematic_label>``.
    """

    delimiter = str(delim)
    if delimiter == "":
        raise ValueError("DDR processor key delimiter cannot be empty.")

    components = {
        "channel": str(channel),
        "var": str(variable),
        "application": str(application),
        "systematic_label": str(systematic_label),
    }
    for field_name, field_value in components.items():
        if delimiter in field_value:
            raise ValueError(
                "Cannot build DDR processor key with delimiter collision: "
                f"{field_name}={field_value!r} contains delimiter {delimiter!r}."
            )

    return delimiter.join(
        (
            components["channel"],
            components["var"],
            components["application"],
            components["systematic_label"],
        )
    )


def _parse_ddr_processor_key(
    key: str,
    *,
    delim: str = "-",
) -> Tuple[str, str, str, str]:
    """Parse a DDR processor key built by :func:`build_ddr_processor_key`."""

    delimiter = str(delim)
    if delimiter == "":
        raise ValueError("DDR processor key delimiter cannot be empty.")

    parts = str(key).split(delimiter)
    if len(parts) != 4:
        raise ValueError(
            "Malformed DDR processor key "
            f"{key!r}: expected 4 fields split by {delimiter!r}, found {len(parts)}."
        )
    return parts[0], parts[1], parts[2], parts[3]


def _tuple_sort_key(key: Tuple[str, str, str, str, str]) -> Tuple[str, str, str, str, str]:
    """Return a deterministic tuple sort key."""

    return tuple(str(piece) for piece in key)


def flatten_ddr_output(
    ddr_payload: Mapping[str, Any],
    *,
    delim: str = "-",
    output_schema: str = "flat",
    preserve_sidecars: bool = False,
    sidecars_key: str = "__sidecars__",
) -> "OrderedDict[Any, Any]":
    """Flatten DDR nested output into canonical 5-tuple histogram mappings."""

    if not isinstance(ddr_payload, Mapping):
        raise TypeError(
            "DDR output must be a mapping of processor_key -> dataset payload."
        )

    schema_name = str(output_schema).strip().lower()
    if schema_name not in {"flat", "tuple"}:
        raise ValueError("output_schema must be 'flat' or 'tuple'.")

    flattened: Dict[Tuple[str, str, str, str, str], Any] = {}
    flattened_origins: Dict[Tuple[str, str, str, str, str], Tuple[str, str, Tuple[Any, ...]]] = {}
    sidecars: Dict[Tuple[str, str], "OrderedDict[str, Any]"] = {}

    for processor_key, dataset_payload in ddr_payload.items():
        if not isinstance(dataset_payload, Mapping):
            raise TypeError(
                f"DDR output for processor {processor_key!r} must be a mapping, got {type(dataset_payload)!r}."
            )

        key_channel, key_var, key_application, key_systematic = _parse_ddr_processor_key(
            str(processor_key),
            delim=delim,
        )

        for dataset_name, leaf_output in dataset_payload.items():
            if not isinstance(leaf_output, Mapping):
                raise TypeError(
                    "DDR dataset payload must be a mapping of histogram keys; "
                    f"processor={processor_key!r} dataset={dataset_name!r} type={type(leaf_output)!r}."
                )

            for leaf_key, leaf_value in leaf_output.items():
                if not isinstance(leaf_key, tuple):
                    if preserve_sidecars:
                        bucket = sidecars.setdefault(
                            (str(processor_key), str(dataset_name)),
                            OrderedDict(),
                        )
                        bucket[str(leaf_key)] = leaf_value
                    continue

                if len(leaf_key) != 5:
                    raise ValueError(
                        "DDR leaf histogram keys must be 5-tuples "
                        "(var, channel, application, sample, systematic). "
                        f"Found key {leaf_key!r} under processor {processor_key!r}."
                    )

                tuple_var, tuple_channel, tuple_application, tuple_sample, tuple_systematic = leaf_key
                tuple_systematic_label = _normalise_systematic_label(tuple_systematic)
                if (
                    str(tuple_channel) != key_channel
                    or str(tuple_var) != key_var
                    or str(tuple_application) != key_application
                    or tuple_systematic_label != key_systematic
                ):
                    raise ValueError(
                        "DDR schema mismatch between processor key and histogram key: "
                        f"processor={processor_key!r}, histogram_key={leaf_key!r}."
                    )

                sample_label = str(tuple_sample)
                if schema_name == "flat":
                    target_key = (
                        sample_label,
                        str(tuple_channel),
                        str(tuple_var),
                        str(tuple_application),
                        tuple_systematic_label,
                    )
                else:
                    target_key = (
                        str(tuple_var),
                        str(tuple_channel),
                        str(tuple_application),
                        sample_label,
                        tuple_systematic_label,
                    )

                if target_key not in flattened:
                    flattened[target_key] = leaf_value
                    flattened_origins[target_key] = (
                        str(processor_key),
                        str(dataset_name),
                        tuple(leaf_key),
                    )
                    continue

                first_processor, first_dataset, first_leaf_key = flattened_origins[target_key]
                raise ValueError(
                    "Duplicate flattened DDR key collision detected: "
                    f"key={target_key!r}, "
                    f"first_origin=(processor={first_processor!r}, dataset={first_dataset!r}, "
                    f"histogram_key={first_leaf_key!r}), "
                    f"second_origin=(processor={processor_key!r}, dataset={dataset_name!r}, "
                    f"histogram_key={leaf_key!r}). "
                    "Duplicate key indicates unexpected DDR duplication; check processor grouping "
                    "or systematic labeling."
                )

    ordered_output: "OrderedDict[Any, Any]" = OrderedDict()
    for key in sorted(flattened.keys(), key=_tuple_sort_key):
        ordered_output[key] = flattened[key]

    if preserve_sidecars and sidecars:
        reserved_key = str(sidecars_key or "__sidecars__")
        if reserved_key in ordered_output:
            raise ValueError(
                f"Cannot store preserved sidecars because reserved key {reserved_key!r} collides with histogram keys."
            )
        ordered_sidecars: "OrderedDict[Tuple[str, str], OrderedDict[str, Any]]" = OrderedDict()
        for sidecar_bucket_key in sorted(sidecars.keys()):
            ordered_sidecars[sidecar_bucket_key] = sidecars[sidecar_bucket_key]
        ordered_output[reserved_key] = ordered_sidecars

    return ordered_output


def _resolve_ddr_preprocess_paths(
    config: RunConfig,
    *,
    results_dir: Path,
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve preprocess input/output artifact paths for DDR execution."""

    preprocessed_data_path = getattr(config, "ddr_preprocessed_data", None)
    explicit_save_path = getattr(config, "ddr_save_preprocess", None)
    auto_save = bool(getattr(config, "ddr_auto_save_preprocess", True))
    artifact_override = getattr(config, "ddr_preprocess_artifact", None)

    save_path: Optional[str] = None
    if preprocessed_data_path:
        # Reuse mode skips preprocess() unless the user explicitly asks for a save.
        if explicit_save_path:
            save_path = str(Path(explicit_save_path).expanduser())
    elif explicit_save_path:
        save_path = str(Path(explicit_save_path).expanduser())
    elif auto_save:
        if artifact_override:
            save_path = str(Path(artifact_override).expanduser())
        else:
            save_path = str((results_dir / "ddr_preprocessed_data.json").resolve())

    if preprocessed_data_path:
        preprocessed_data_path = str(Path(preprocessed_data_path).expanduser())
    return preprocessed_data_path, save_path


def stage_ddr_proxy(proxy_path: str, *, staging_dir: Path) -> Path:
    """Copy a user proxy to ``staging_dir/proxy.pem`` and validate readability."""

    source_path = Path(proxy_path).expanduser()
    if not source_path.exists():
        raise FileNotFoundError(f"DDR proxy file does not exist: {source_path}")
    if not source_path.is_file():
        raise FileNotFoundError(f"DDR proxy path is not a file: {source_path}")
    if not os.access(source_path, os.R_OK):
        raise PermissionError(f"DDR proxy file is not readable: {source_path}")

    staging_dir.mkdir(parents=True, exist_ok=True)
    staged_proxy = staging_dir / "proxy.pem"
    shutil.copyfile(source_path, staged_proxy)
    os.chmod(staged_proxy, 0o600)
    return staged_proxy


topcoffea_utils = _import_topcoffea_submodule("utils")

from .run_analysis_helpers import (  # noqa: E402
    DEFAULT_WEIGHT_VARIATIONS,
    RunConfig,
    SampleLoader,
    unique_preserving_order,
    weight_variations_from_metadata,
)
from . import metadata_authority  # noqa: E402
from .nanoevents_helpers import nanoevents_factory_from_root  # noqa: E402
from .systematics_validation import (  # noqa: E402
    metadata_non_nominal_bases,
    validate_histogram_plan_systematics,
)

DEFAULT_SCENARIO_NAME = "TOP_22_006"

if TYPE_CHECKING:  # pragma: no cover - used only for type checking
    from topeft.modules.channel_metadata import ChannelMetadataHelper
    from topeft.modules.systematics import SystematicsHelper

LST_OF_KNOWN_EXECUTORS = ["futures", "iterative", "taskvine"]


@dataclass(frozen=True)
class TaskVineContext:
    """Describe directories and settings shared by TaskVine/DDR executions."""

    executor: str
    port_range: Tuple[int, int]
    staging_dir: Path
    logs_dir: Path
    manager_name: Optional[str]
    manager_template: Optional[str]
    manager_source: str
    environment_file: Optional[str]
    extra_input_files: Tuple[str, ...]


def resolve_taskvine_manager_project_name_with_source(
    *,
    configured_manager_name: Optional[str],
    default_manager_name: str,
    env: Optional[Mapping[str, str]] = None,
) -> Tuple[str, str]:
    """Resolve the TaskVine project/manager name for std DDR runs.

    Priority:
    1. `TOPEFT_DDR_MANAGER_NAME` when set to a non-empty string.
    2. Configured `manager_name` from CLI/options.
    3. Existing default manager name.
    """

    source_env = env if env is not None else os.environ
    env_manager_name = source_env.get("TOPEFT_DDR_MANAGER_NAME")
    if isinstance(env_manager_name, str):
        candidate = env_manager_name.strip()
        if candidate:
            return candidate, "env"

    if configured_manager_name is not None:
        candidate = str(configured_manager_name).strip()
        if candidate:
            return candidate, "config"

    return default_manager_name, "default"


def resolve_taskvine_manager_project_name(
    *,
    configured_manager_name: Optional[str],
    default_manager_name: str,
    env: Optional[Mapping[str, str]] = None,
) -> str:
    resolved_name, _ = resolve_taskvine_manager_project_name_with_source(
        configured_manager_name=configured_manager_name,
        default_manager_name=default_manager_name,
        env=env,
    )
    return resolved_name


class ChannelPlanner:
    """Resolve channel metadata into lookups used during processing."""

    def __init__(
        self,
        channel_helper: "ChannelMetadataHelper",
        *,
        skip_sr: bool = False,
        skip_cr: bool = False,
        scenario_names: Optional[Sequence[str]] = None,
        channel_groups_strict: bool = True,
        warn_on_partial_groups: bool = True,
    ) -> None:
        self._channel_helper = channel_helper
        self._skip_sr = bool(skip_sr)
        self._skip_cr = bool(skip_cr)
        self._scenario_names = list(scenario_names or [])
        self._channel_groups_strict = bool(channel_groups_strict)
        self._warn_on_partial_groups = bool(warn_on_partial_groups)

        self._sr_groups = None
        self._cr_groups = None
        self._active_features: Optional[Tuple[str, ...]] = None
        self._channel_app_cache: Dict[bool, Dict[str, List[str]]] = {}

    @property
    def active_features(self) -> Tuple[str, ...]:
        """Return the set of metadata features activated for this run."""

        if self._active_features is None:
            self._resolve_groups()
        return self._active_features or ()

    def resolve_groups(self) -> Tuple[Tuple[Any, ...], Tuple[Any, ...], Tuple[str, ...]]:
        """Expose the resolved channel groups and active features."""

        return self._resolve_groups()

    def build_channel_dict(
        self,
        channel: str,
        application: str,
        *,
        is_data: bool,
    ) -> Mapping[str, Any]:
        """Return the metadata describing ``channel`` and ``application``."""

        sr_groups, cr_groups, active_features = self._resolve_groups()

        base_channel = channel
        jet_suffix = None

        import re

        match = re.search(r"_(?:exactly_|atmost_|atleast_)?(\d+j)$", channel)
        if match:
            jet_suffix = match.group(1)
            base_channel = channel[: -(len(match.group(0)))]

        nlep_match = re.match(r"(\d+l)", base_channel)
        nlep_cat = nlep_match.group(1) if nlep_match else None

        def _normalize_group(group_list: Iterable[Any]) -> Optional[Mapping[str, Any]]:
            for group in group_list:
                candidate_categories = []

                for category in group.categories():
                    if any(region.name == base_channel for region in category.region_definitions):
                        candidate_categories.append(category)

                if not candidate_categories and nlep_cat is not None:
                    category = group.category(nlep_cat)
                    if category is not None:
                        candidate_categories.append(category)

                for category in candidate_categories:
                    appl_list = category.application_tags(is_data)
                    if application not in appl_list:
                        continue
                    for region in category.region_definitions:
                        if region.name != base_channel:
                            continue
                        jet_bins = category.jet_bins or [None]
                        for jet_cat in jet_bins:
                            jet_key = None
                            if jet_cat is not None:
                                jet_key = normalize_jet_category(jet_cat)
                                if jet_suffix and not jet_key.endswith(jet_suffix):
                                    continue
                            elif jet_suffix:
                                continue
                            include_set = set(category.histogram_includes)
                            exclude_set = set(category.histogram_excludes)
                            include_set.update(region.include_histograms)
                            exclude_set.update(region.exclude_histograms)
                            if include_set:
                                exclude_set.difference_update(include_set)
                            features = set(active_features)
                            features.update(group.features)
                            chan_def_lst = self._normalize_channel_definition(
                                region.to_legacy_list(), active_features
                            )
                            channel_label = build_channel_label(
                                chan_def_lst,
                                jet_selection=jet_key,
                            )
                            return {
                                "jet_selection": jet_key,
                                "chan_def_lst": chan_def_lst,
                                "lep_flav_lst": category.lepton_flavors,
                                "appl_region": application,
                                "features": tuple(sorted(features)),
                                "channel_var_whitelist": tuple(sorted(include_set))
                                if include_set
                                else (),
                                "channel_var_blacklist": tuple(sorted(exclude_set)),
                                "channel_label": channel_label,
                            }
            return None

        channel_info: Optional[Mapping[str, Any]] = None
        if not self._skip_sr:
            channel_info = _normalize_group(sr_groups)
        if channel_info is None and not self._skip_cr:
            channel_info = _normalize_group(cr_groups)

        if channel_info is None:
            if (application.startswith("isSR") and self._skip_sr) or (
                application.startswith("isCR") and self._skip_cr
            ):
                return {}
            raise ValueError(f"Channel {channel} with application {application} not found")

        return channel_info

    def channel_app_map(self, *, is_data: bool) -> Mapping[str, List[str]]:
        """Return a mapping of channel names to application tags."""

        if is_data in self._channel_app_cache:
            return self._channel_app_cache[is_data]

        sr_groups, cr_groups, _ = self._resolve_groups()

        def _collect(groups: Iterable[Any], result: Dict[str, List[str]]) -> None:
            for group in groups:
                for category in group.categories():
                    appl_list = category.application_tags(is_data)
                    if not appl_list:
                        continue
                    for region in category.region_definitions:
                        base_ch = region.name
                        jet_bins = category.jet_bins or [None]
                        for jet_cat in jet_bins:
                            if jet_cat is None:
                                continue
                            jet_selection = normalize_jet_category(jet_cat)
                            ch_name = build_channel_label(
                                [base_ch],
                                jet_selection=jet_selection,
                            )
                            current = result.setdefault(ch_name, [])
                            for appl in appl_list:
                                if appl not in current:
                                    current.append(appl)

        result: Dict[str, List[str]] = {}
        if not self._skip_sr:
            _collect(sr_groups, result)
        if not self._skip_cr:
            _collect(cr_groups, result)

        self._channel_app_cache[is_data] = {k: sorted(v) for k, v in result.items()}
        return self._channel_app_cache[is_data]

    def _resolve_groups(self) -> Tuple[Tuple[Any, ...], Tuple[Any, ...], Tuple[str, ...]]:
        if self._sr_groups is not None and self._cr_groups is not None:
            return self._sr_groups, self._cr_groups, self._active_features or ()

        sr_groups: List[Any] = []
        cr_groups: List[Any] = []
        active_features = set()
        seen_groups = set()

        channel_helper = self._channel_helper

        def _load_group(name: str):
            group = channel_helper.group(name)
            if name not in seen_groups:
                active_features.update(group.features)
                seen_groups.add(name)
            return group

        def _register_group(name: str) -> None:
            group = _load_group(name)
            if name.endswith("_CR"):
                if not self._skip_cr and group not in cr_groups:
                    cr_groups.append(group)
            else:
                if not self._skip_sr and group not in sr_groups:
                    sr_groups.append(group)

        group_names = channel_helper.selected_group_names(
            self._scenario_names,
            strict=self._channel_groups_strict,
            warn_on_partial=self._warn_on_partial_groups,
        )
        for group_name in group_names:
            _register_group(group_name)

        if not sr_groups and not cr_groups and not seen_groups:
            raise ValueError("No channel groups selected. Please specify at least one scenario")

        self._sr_groups = tuple(sr_groups)
        self._cr_groups = tuple(cr_groups)
        self._active_features = tuple(sorted(active_features))
        return self._sr_groups, self._cr_groups, self._active_features

    @staticmethod
    def _normalize_channel_definition(
        chan_def_lst: Sequence[str], active_features: Iterable[str]
    ) -> List[str]:
        """Return ``chan_def_lst`` adjusted for active metadata features."""

        normalized = list(chan_def_lst)
        if "offz_split" in set(active_features) and "3l_offZ" in normalized:
            normalized = ["3l_offZ_split" if entry == "3l_offZ" else entry for entry in normalized]
        return normalized


def normalize_jet_category(jet_cat: Any) -> str:
    """Return a standardized jet category suffix."""

    jet_cat = str(jet_cat).strip()
    if jet_cat.startswith("="):
        tag = "exactly_"
    elif jet_cat.startswith("<"):
        tag = "atmost_"
    elif jet_cat.startswith(">"):
        tag = "atleast_"
    else:
        raise ValueError(f"jet_cat {jet_cat} misses =,<,> !")

    return f"{tag}{jet_cat[1:]}j"


@dataclass(frozen=True)
class HistogramTask:
    """Description of a single histogram filling task."""

    sample: str
    variable: str
    clean_channel: str
    application: str
    group_descriptor: Any
    variations: Tuple[Any, ...]
    hist_keys: Mapping[str, Tuple[Tuple[Any, ...], ...]]
    variable_info: Mapping[str, Any]
    available_systematics: Mapping[str, Sequence[str]]
    channel_metadata: Mapping[str, Any]


@dataclass(frozen=True)
class HistogramCombination:
    """Canonical tuple describing a histogram that will be filled."""

    sample: str
    channel: str
    variable: str
    application: str
    systematic: str


@dataclass(frozen=True)
class ChannelApplicationSelection:
    """Filtered description of a channel/application pair for a variable."""

    clean_channel: str
    application: str
    metadata: Mapping[str, Any]
    flavored_channels: Tuple[str, ...]


@dataclass(frozen=True)
class SystematicExpansion:
    """Expansion of grouped systematic variations for a histogram task."""

    group_descriptor: Any
    variations: Tuple[Any, ...]
    hist_keys: Mapping[str, Tuple[Tuple[Any, ...], ...]]
    summary_entries: Tuple[HistogramCombination, ...]


@dataclass
class SummaryAccumulator:
    """Collect and deduplicate histogram summary combinations."""

    seen: Set[HistogramCombination] = field(default_factory=set)
    entries: List[HistogramCombination] = field(default_factory=list)

    def add_entries(self, new_entries: Iterable[HistogramCombination]) -> None:
        for entry in new_entries:
            if entry in self.seen:
                continue
            self.seen.add(entry)
            self.entries.append(entry)

    def as_tuple(self) -> Tuple[HistogramCombination, ...]:
        return tuple(self.entries)


@dataclass(frozen=True)
class HistogramPlan:
    """Collection of histogram tasks computed for a workflow."""

    tasks: List[HistogramTask]
    histogram_names: Sequence[str]
    summary: Sequence[HistogramCombination]


class HistogramPlanner:
    """Compute the histogram tasks required for a run."""

    def __init__(
        self,
        *,
        config: RunConfig,
        variable_definitions: Mapping[str, MutableMapping[str, Any]],
        channel_planner: ChannelPlanner,
    ) -> None:
        self._config = config
        self._var_defs = variable_definitions
        self._channel_planner = channel_planner
        self._channel_metadata_log_count = 0
        self._channel_metadata_log_limit = 8

    def plan(
        self,
        samplesdict: Mapping[str, Mapping[str, Any]],
        systematics_helper: "SystematicsHelper",
    ) -> HistogramPlan:
        hist_lst = unique_preserving_order(self._var_defs.keys())
        if not hist_lst:
            raise ValueError("Histogram selection resolved to an empty list")

        available_systematics_by_sample_type = {
            "mc": systematics_helper.names_by_type("mc", include_systematics=self._config.do_systs),
            "data": systematics_helper.names_by_type("data", include_systematics=self._config.do_systs),
        }

        tasks: List[HistogramTask] = []
        summary_accumulator = SummaryAccumulator()

        channel_map_mc = self._channel_planner.channel_app_map(is_data=False)
        channel_map_data = self._channel_planner.channel_app_map(is_data=True)

        for sample, sample_info in samplesdict.items():
            ch_map = channel_map_data if sample_info.get("isData") else channel_map_mc
            grouped_variations = systematics_helper.grouped_variations_for_sample(
                sample_info, include_systematics=self._config.do_systs
            )
            sample_type_key = "data" if sample_info.get("isData") else "mc"
            available_systematics = available_systematics_by_sample_type[sample_type_key]

            for var in hist_lst:
                var_info = dict(self._var_defs[var])
                selections = self._iter_channel_applications(
                    sample_info=sample_info,
                    variable=var,
                    channel_map=ch_map,
                )
                for selection in selections:
                    expansions = self._expand_systematics(
                        sample=sample,
                        variable=var,
                        clean_channel=selection.clean_channel,
                        application=selection.application,
                        grouped_variations=grouped_variations,
                        flavored_channel_names=selection.flavored_channels,
                    )

                    for expansion in expansions:
                        summary_accumulator.add_entries(expansion.summary_entries)
                        tasks.append(
                            HistogramTask(
                                sample=sample,
                                variable=var,
                                clean_channel=selection.clean_channel,
                                application=selection.application,
                                group_descriptor=expansion.group_descriptor,
                                variations=expansion.variations,
                                hist_keys=expansion.hist_keys,
                                variable_info=var_info,
                                available_systematics=available_systematics,
                                channel_metadata=selection.metadata,
                            )
                        )

        return HistogramPlan(
            tasks=tasks,
            histogram_names=hist_lst,
            summary=summary_accumulator.as_tuple(),
        )

    def _iter_channel_applications(
        self,
        *,
        sample_info: Mapping[str, Any],
        variable: str,
        channel_map: Mapping[str, Sequence[str]],
    ) -> Iterator[ChannelApplicationSelection]:
        is_data = sample_info.get("isData", False)
        for clean_ch, appl_list in channel_map.items():
            for appl in appl_list:
                try:
                    channel_metadata = self._channel_planner.build_channel_dict(
                        clean_ch,
                        appl,
                        is_data=is_data,
                    )
                except ValueError:
                    continue

                if not channel_metadata:
                    continue

                whitelist = tuple(channel_metadata.get("channel_var_whitelist") or ())
                blacklist = set(channel_metadata.get("channel_var_blacklist") or ())

                if whitelist and variable not in whitelist:
                    continue
                if variable in blacklist:
                    continue

                flavored_channels = self._resolve_flavored_channels(channel_metadata)
                channel_label = channel_metadata.get("channel_label") or clean_ch

                if self._channel_metadata_log_count < self._channel_metadata_log_limit:
                    logger.info(
                        "Channel metadata: channel_label=%s, chan_def_lst=%s, jet_selection=%s, appregion=%s, features=%s",
                        channel_label,
                        channel_metadata.get("chan_def_lst"),
                        channel_metadata.get("jet_selection"),
                        channel_metadata.get("appl_region"),
                        channel_metadata.get("features"),
                    )
                    self._channel_metadata_log_count += 1

                yield ChannelApplicationSelection(
                    clean_channel=channel_label,
                    application=appl,
                    metadata=channel_metadata,
                    flavored_channels=flavored_channels,
                )

    def _resolve_flavored_channels(
        self,
        channel_metadata: Mapping[str, Any],
    ) -> Tuple[str, ...]:
        if not self._config.split_lep_flavor:
            return ()

        flavored_candidates: List[str] = []
        lep_flavors = channel_metadata.get("lep_flav_lst") or []
        lep_chan_defs = channel_metadata.get("chan_def_lst") or []
        jet_selection = channel_metadata.get("jet_selection")
        lep_base = lep_chan_defs[0] if lep_chan_defs else None
        if lep_base:
            for lep_flavor in lep_flavors:
                if not lep_flavor:
                    continue
                flavored_name = build_channel_label(
                    [lep_base],
                    jet_selection=jet_selection,
                    lep_flav=lep_flavor,
                )
                flavored_candidates.append(flavored_name)
        return tuple(flavored_candidates)

    def _expand_systematics(
        self,
        *,
        sample: str,
        variable: str,
        clean_channel: str,
        application: str,
        grouped_variations: Mapping[Any, Sequence[Any]],
        flavored_channel_names: Sequence[str],
    ) -> Tuple[SystematicExpansion, ...]:
        expansions: List[SystematicExpansion] = []
        flavored_channel_names = tuple(flavored_channel_names)

        for group_descriptor, variations in grouped_variations.items():
            hist_keys: Dict[str, Tuple[Tuple[Any, ...], ...]] = {}
            summary_candidates: List[HistogramCombination] = []

            variations_tuple = tuple(variations)
            for variation in variations_tuple:
                syst_label = (
                    (group_descriptor.name, variation.name) if len(variations_tuple) > 1 else variation.name
                )
                base_entry = (variable, clean_channel, application, sample, syst_label)
                key_entries: List[Tuple[Any, ...]] = [base_entry]
                if flavored_channel_names:
                    key_entries.extend(
                        (variable, flavored_name, application, sample, syst_label)
                        for flavored_name in flavored_channel_names
                    )
                hist_keys[variation.name] = tuple(key_entries)

                for entry in key_entries:
                    systematic = entry[4]
                    if isinstance(systematic, tuple):
                        systematic_str = ":".join(str(component) for component in systematic)
                    else:
                        systematic_str = str(systematic)

                    summary_candidates.append(
                        HistogramCombination(
                            sample=str(entry[3]),
                            channel=str(entry[1]),
                            variable=str(entry[0]),
                            application=str(entry[2]),
                            systematic=systematic_str,
                        )
                    )

            expansions.append(
                SystematicExpansion(
                    group_descriptor=group_descriptor,
                    variations=variations_tuple,
                    hist_keys=hist_keys,
                    summary_entries=tuple(summary_candidates),
                )
            )

        return tuple(expansions)


class ExecutorFactory:
    """Create Coffea runners for the configured executor type."""

    def __init__(self, config: RunConfig) -> None:
        self._config = config
        self._remote_environment = topeft_remote_environment

    def create_runner(self) -> Any:
        import coffea.processor as processor
        from coffea.nanoevents import NanoAODSchema

        executor = (self._config.executor or "taskvine").lower()

        def _build_runner(exec_instance: Any, **runner_kwargs: Any) -> Any:
            return processor.Runner(
                executor=exec_instance,
                schema=NanoAODSchema,
                chunksize=self._config.chunksize,
                maxchunks=self._config.nchunks,
                **runner_kwargs,
            )

        runner_fields = set(getattr(processor.Runner, "__dataclass_fields__", {}))
        runner_kwargs: Dict[str, Any] = {}
        if "nanoevents_factory" in runner_fields:
            runner_kwargs["nanoevents_factory"] = partial(nanoevents_factory_from_root, mode="numpy")

        if executor == "futures":
            workers = self._config.nworkers or 1
            exec_instance = build_futures_executor(
                processor,
                workers=workers,
                status=self._config.futures_status,
                tailtimeout=self._config.futures_tail_timeout,
            )

            runner_kwargs.update(
                futures_runner_overrides(
                    runner_fields,
                    memory=self._config.futures_memory,
                    prefetch=self._config.futures_prefetch,
                )
            )
            return _build_runner(exec_instance, **runner_kwargs)

        if executor == "iterative":
            try:
                exec_instance = processor.IterativeExecutor()
            except AttributeError:  # pragma: no cover - depends on coffea build
                exec_instance = processor.iterative_executor()
            return _build_runner(exec_instance, **runner_kwargs)

        if executor == "taskvine":
            context = self.taskvine_context(executor)
            taskvine_args = build_taskvine_args(
                staging_dir=context.staging_dir,
                logs_dir=context.logs_dir,
                manager_name=context.manager_name,
                manager_name_template=context.manager_template,
                extra_input_files=context.extra_input_files,
                resource_monitor=self._config.resource_monitor,
                resources_mode=self._config.resources_mode,
                environment_file=context.environment_file,
                print_stdout=self._config.taskvine_print_stdout,
                custom_init=taskvine_log_configurator(context.logs_dir),
            )
            exec_instance = instantiate_taskvine_executor(
                processor,
                taskvine_args,
                port_range=context.port_range,
                negotiate_port=bool(self._config.negotiate_manager_port),
            )

            return _build_runner(
                exec_instance,
                skipbadfiles=True,
                xrootdtimeout=300,
                **runner_kwargs,
            )

        raise ValueError(f"Unknown executor '{executor}'")

    def taskvine_context(
        self,
        executor: str,
        *,
        processor_path: Optional[Path] = None,
        use_environment_file: bool = True,
    ) -> TaskVineContext:
        """Return TaskVine/DDR runtime metadata derived from config."""

        port_range = parse_port_range(self._config.port)
        staging_dir = self._distributed_staging_dir(executor)
        logs_dir = self._executor_logs_dir(executor, staging_dir)
        manager_default = self._manager_name_base(executor)
        manager_name, manager_source = resolve_taskvine_manager_project_name_with_source(
            configured_manager_name=self._config.manager_name,
            default_manager_name=manager_default,
        )
        manager_template = self._config.manager_name_template
        if manager_template is None and manager_name:
            manager_template = f"{manager_name}-{{pid}}"
        environment_file: Optional[str] = None
        if use_environment_file:
            environment_file = resolve_environment_file(
                self._config.environment_file,
                self._remote_environment,
            )
        extra_input_files = tuple(
            self._processor_extra_input_files(processor_path=processor_path)
        )
        return TaskVineContext(
            executor=executor,
            port_range=port_range,
            staging_dir=staging_dir,
            logs_dir=logs_dir,
            manager_name=manager_name,
            manager_template=manager_template,
            manager_source=manager_source,
            environment_file=environment_file,
            extra_input_files=extra_input_files,
        )

    def _distributed_staging_dir(self, executor: str) -> Path:
        configured = getattr(self._config, "scratch_dir", None)
        if configured:
            staging = Path(configured).expanduser()
        else:
            base_dir = os.environ.get("TOPEFT_EXECUTOR_STAGING")
            if base_dir:
                staging = Path(base_dir).expanduser()
            else:
                staging = Path(tempfile.gettempdir()) / "topeft" / self._manager_name_base(executor)
        staging.mkdir(parents=True, exist_ok=True)
        return staging

    def _manager_name_base(self, executor: str) -> str:
        user = os.environ.get("USER")
        if not user:
            try:
                user = getpass.getuser()
            except Exception:  # pragma: no cover - best effort fallback
                user = "coffea"
        return f"{user}-{executor}-coffea"

    def _executor_logs_dir(self, executor: str, staging_dir: Path) -> Path:
        if executor == "taskvine":
            logs_dir = staging_dir / "logs" / "taskvine"
        else:
            logs_dir = staging_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return logs_dir

    def _processor_extra_input_files(self, *, processor_path: Optional[Path] = None) -> list[str]:
        if processor_path is None:
            processor_path = _resolve_processor_file_path(self._config.processor)
        return _collect_processor_extra_files(processor_path)


class RunWorkflow:
    def __init__(
        self,
        *,
        config: RunConfig,
        metadata: Mapping[str, Any],
        sample_loader: SampleLoader,
        channel_planner: ChannelPlanner,
        histogram_planner: HistogramPlanner,
        executor_factory: ExecutorFactory,
        weight_variations: Sequence[str],
        metadata_path: str,
    ) -> None:
        self._config = config
        self._metadata = metadata
        self._sample_loader = sample_loader
        self._channel_planner = channel_planner
        self._histogram_planner = histogram_planner
        self._executor_factory = executor_factory
        self._weight_variations = list(weight_variations)
        self._metadata_path = metadata_path
        self._golden_json_cache: Dict[str, Optional[str]] = {}

    def _log_task_submission(self, task: HistogramTask) -> None:
        """Emit a concise log describing the histogram combinations for ``task``."""

        if self._config.executor != "futures" or not getattr(self._config, "log_tasks", False):
            return

        combination_labels: List[str] = []
        for entries in task.hist_keys.values():
            for var, channel, application, sample, systematic in entries:
                if isinstance(systematic, tuple):
                    systematic_label = ":".join(str(component) for component in systematic)
                else:
                    systematic_label = str(systematic)

                combination_labels.append(
                    "({0}, {1}, {2}, {3}, {4})".format(
                        str(sample),
                        str(channel),
                        str(var),
                        str(application),
                        systematic_label,
                    )
                )

        if not combination_labels:
            return

        unique_labels = unique_preserving_order(combination_labels)
        logger.info("[futures] submitting histogram task for %s", ", ".join(unique_labels))

    def _log_variation_recap(
        self,
        *,
        task_index: int,
        total_tasks: int,
        task: HistogramTask,
        summary_entries: Sequence[Mapping[str, Any]],
    ) -> None:
        """Emit a single INFO log describing which variations actually ran."""

        def _unique_strings(values: Iterable[Any]) -> List[str]:
            normalized = []
            for value in values:
                if value in (None, ""):
                    continue
                normalized.append(str(value))
            return unique_preserving_order(normalized)

        def _flatten(entry_key: str) -> List[str]:
            return _unique_strings(value for entry in summary_entries for value in entry.get(entry_key, ()))

        def _format(values: Sequence[str]) -> str:
            return "[" + ", ".join(values) + "]" if values else "[]"

        if not summary_entries:
            logger.info(
                "Completed histogram task %d/%d: sample=%s channel=%s variable=%s application=%s (no variation summary returned)",
                task_index,
                total_tasks,
                task.sample,
                task.clean_channel,
                task.variable,
                task.application,
            )
            return

        requested_variations = _unique_strings(entry.get("requested_name") for entry in summary_entries)
        object_variations = _unique_strings(entry.get("object_variation") for entry in summary_entries)
        histogram_labels = _unique_strings(entry.get("histogram_label") for entry in summary_entries)
        executed_weight_variations = _flatten("executed_weight_variations")
        requested_weight_variations = _flatten("requested_weight_variations")
        skipped_weights = [
            weight for weight in requested_weight_variations if weight not in set(executed_weight_variations)
        ]

        logger.info(
            (
                "Completed histogram task %d/%d: sample=%s channel=%s variable=%s application=%s "
                "requested_variations=%s object_variations=%s executed_weight_variations=%s "
                "histogram_labels=%s skipped_weight_variations=%s"
            ),
            task_index,
            total_tasks,
            task.sample,
            task.clean_channel,
            task.variable,
            task.application,
            _format(requested_variations),
            _format(object_variations),
            _format(executed_weight_variations),
            _format(histogram_labels),
            _format(_unique_strings(skipped_weights)),
        )

    def _build_processor_instance(
        self,
        *,
        task: HistogramTask,
        sample_dict: Mapping[str, Any],
        channel_dict: Mapping[str, Any],
        analysis_processor_module: Any,
        coffea_processor_module: Any,
        golden_jsons: Mapping[str, str],
        ecut_threshold: Optional[float],
        hist_keys: Optional[Mapping[str, Tuple[Tuple[Any, ...], ...]]] = None,
        systematic_variations: Optional[Sequence[Any]] = None,
        available_systematics: Optional[Mapping[str, Sequence[str]]] = None,
        golden_json_paths: Optional[Mapping[str, str]] = None,
    ) -> Any:
        if hist_keys is None:
            hist_keys = task.hist_keys
        if systematic_variations is None:
            systematic_variations = task.variations
        if available_systematics is None:
            available_systematics = {
                key: tuple(values)
                for key, values in (task.available_systematics or {}).items()
            }

        golden_json_path = None
        if "isData" in sample_dict:
            golden_json_path = self._resolve_golden_json(sample_dict, golden_jsons)

        processor_instance = analysis_processor_module.AnalysisProcessor(
            sample_dict,
            self._config.wc_list,
            hist_keys=hist_keys,
            var_info=task.variable_info,
            ecut_threshold=ecut_threshold,
            do_errors=self._config.do_errors,
            split_by_lepton_flavor=self._config.split_lep_flavor,
            channel_dict=channel_dict,
            golden_json_path=golden_json_path,
            golden_json_paths=golden_json_paths,
            systematic_variations=systematic_variations,
            available_systematics=available_systematics,
            metadata_path=self._metadata_path,
            executor_mode=self._config.executor,
            debug_logging=_DEV_DEBUG,
            produce_sidecars=bool(getattr(self._config, "produce_sidecars", False)),
        )
        if not isinstance(processor_instance, coffea_processor_module.ProcessorABC):
            raise TypeError(
                "AnalysisProcessor is not an instance of coffea.processor.ProcessorABC. "
                f"Active coffea.processor module: {getattr(coffea_processor_module, '__file__', 'unknown')}"
            )
        return processor_instance

    def _resolve_golden_json(
        self,
        sample_dict: Mapping[str, Any],
        golden_jsons: Mapping[str, str],
    ) -> Optional[str]:
        if not sample_dict.get("isData"):
            return None
        year_key = str(sample_dict.get("year"))
        if not year_key:
            return None
        cache = getattr(self, "_golden_json_cache", None)
        if cache is None:
            cache = {}
            self._golden_json_cache = cache
        if year_key in cache:
            return cache[year_key]
        try:
            golden_json_path = metadata_authority.golden_json_for_year(
                {"golden_jsons": golden_jsons},
                year_key,
            )
        except KeyError as exc:
            raise ValueError(
                f"No golden JSON configured for data year '{year_key}' in {self._metadata_path}."
            ) from exc
        if not os.path.exists(golden_json_path):
            raise FileNotFoundError(
                f"Golden JSON file '{golden_json_path}' for year '{year_key}' was not found."
            )
        cache[year_key] = golden_json_path
        return golden_json_path

    def _execute_ddr(
        self,
        *,
        histogram_plan: HistogramPlan,
        samplesdict: Mapping[str, Mapping[str, Any]],
        flist: Mapping[str, Any],
        golden_jsons: Mapping[str, str],
        ecut_threshold: Optional[float],
        analysis_processor_module: Any,
        processor_file: Path,
        processor_module_name: str,
        coffea_processor_module: Any,
    ) -> Mapping[str, Any]:
        try:
            ddr_helpers = topcoffea.modules.dynamic_data_reduction
        except (ImportError, AttributeError) as exc:  # pragma: no cover - dependency guard
            raise RuntimeError(
                "The 'taskvine' executor requires topcoffea.modules.dynamic_data_reduction. "
                "Update the topcoffea checkout to include tc/feat-ddr-helpers."
            ) from exc

        from coffea.nanoevents import NanoAODSchema

        context = self._executor_factory.taskvine_context(
            "taskvine",
            processor_path=processor_file,
        )
        data = ddr_helpers.build_ddr_data_from_flist(
            flist,
            object_path=self._config.treename or "Events",
        )
        with _ddr_debug_stage(
            "processor_map_build",
            details=f"histogram_tasks={len(histogram_plan.tasks)}",
        ):
            processors = self._build_ddr_processors(
                histogram_plan=histogram_plan,
                samplesdict=samplesdict,
                golden_jsons=golden_jsons,
                analysis_processor_module=analysis_processor_module,
                coffea_processor_module=coffea_processor_module,
                ecut_threshold=ecut_threshold,
            )

        with _ddr_debug_stage(
            "processor_map_filter",
            details="order=prefix->slice->max->probe",
        ):
            processors = _apply_ddr_processor_subset(processors)
            processors = _apply_ddr_processor_limit(processors)
            if _env_flag_enabled("TOPEFT_DDR_USE_PROBE_PROCESSOR"):
                processors = {"tensors": _build_ddr_probe_processor()}
        if not processors:
            logger.warning(
                "TaskVine executor selected but no histogram tasks were constructed; returning empty output."
            )
            return {}

        logger.info("[taskvine] Launching CoffeaDynamicDataReduction with %d processors", len(processors))
        run_info_path = context.staging_dir / "vine-run-info"
        if _topeft_ddr_debug_enabled():
            _set_ddr_debug_context(
                t0=time.time(),
                run_info_path=run_info_path,
            )
            _ddr_debug_emit("ddr_debug_context begin", include_paths=True)
        manager = self._create_ddr_manager(context)
        if _topeft_ddr_debug_enabled():
            datasets_count, total_files, total_entries = _summarize_ddr_input(data)
            _ddr_debug_emit(
                "handoff manager_name="
                f"{context.manager_name} "
                f"manager_port={_safe_manager_call(manager, 'port')} "
                f"staging_dir={context.staging_dir} "
                f"run_info_path={run_info_path} "
                f"workers_connected={_safe_manager_call(manager, 'workers_connected')} "
                f"hungry={_safe_manager_call(manager, 'hungry')} "
                f"empty={_safe_manager_call(manager, 'empty')} "
                f"processors={len(processors)} "
                f"datasets={datasets_count} "
                f"total_files={total_files} "
                f"total_entries={total_entries}",
                include_paths=True,
            )
        log_configurator = taskvine_log_configurator(context.logs_dir)
        try:
            log_configurator(manager)
        except Exception:
            logger.debug("DDR log configuration failed", exc_info=True)
        try:
            manager.enable_monitoring(watchdog=False)
        except Exception:
            logger.debug("DDR manager monitoring setup failed", exc_info=True)
        try:
            manager.tune("hungry-minimum", 1)
        except Exception:
            logger.debug("DDR manager tuning failed", exc_info=True)

        results_dir = context.logs_dir.parent / "taskvine-results"
        results_dir.mkdir(parents=True, exist_ok=True)
        preprocessed_data_path, save_preprocess_path = _resolve_ddr_preprocess_paths(
            self._config,
            results_dir=results_dir,
        )
        resources_processing = (
            dict(self._config.ddr_resources_processing)
            if getattr(self._config, "ddr_resources_processing", None)
            # Per-task TaskVine cores requests should stay small by default.
            # Oversized defaults can make tasks unschedulable on many workers.
            else {"cores": 1}
        )
        resources_accumulating = (
            dict(self._config.ddr_resources_accumulating)
            if getattr(self._config, "ddr_resources_accumulating", None)
            else None
        )
        step_size = (
            int(self._config.ddr_step_size)
            if getattr(self._config, "ddr_step_size", None) is not None
            else int(self._config.chunksize)
        )
        step_size = max(step_size, 1)
        max_task_retries = (
            int(self._config.ddr_max_task_retries)
            if getattr(self._config, "ddr_max_task_retries", None) is not None
            else None
        )
        ddr_verbose = (
            bool(self._config.ddr_verbose)
            if getattr(self._config, "ddr_verbose", None) is not None
            else None
        )
        ddr_environment_variables = dict(
            getattr(self._config, "ddr_environment_variables", {}) or {}
        )
        extra_files = list(context.extra_input_files)
        processor_file_str = str(processor_file)
        if processor_file_str not in extra_files:
            extra_files.append(processor_file_str)
        staged_proxy_path: Optional[str] = None
        ddr_x509_proxy_effective: Optional[str] = None
        if self._config.ddr_x509_proxy:
            staged_proxy = stage_ddr_proxy(
                self._config.ddr_x509_proxy,
                staging_dir=context.staging_dir,
            )
            staged_proxy_path = str(staged_proxy)
            ddr_x509_proxy_effective = "proxy.pem"
            extra_files.append(staged_proxy_path)
            # DDR tasks run in worker sandboxes where staged files are referenced by basename.
            ddr_environment_variables["X509_USER_PROXY"] = ddr_x509_proxy_effective
        extra_files = _deduplicate_staged_paths(extra_files)
        _validate_staged_basename_collisions(
            extra_files,
            context="TaskVine DDR extra_files",
        )
        staged_sample_names = ", ".join(Path(path).name for path in extra_files[:8])
        if len(extra_files) > 8:
            staged_sample_names = f"{staged_sample_names}, ..."
        logger.info(
            "[taskvine] Model S processor: file=%s module=%s extra_files=%d processor_staged=%s staged_names=[%s]",
            processor_file,
            processor_module_name,
            len(extra_files),
            processor_file_str in extra_files,
            staged_sample_names if staged_sample_names else "<none>",
        )

        preprocess_kwargs = dict(
            getattr(self._config, "ddr_preprocess_kwargs", {}) or {}
        )
        if getattr(self._config, "ddr_preprocess_timeout", None) is not None:
            preprocess_kwargs["timeout"] = int(self._config.ddr_preprocess_timeout)
        if getattr(self._config, "ddr_preprocess_max_retries", None) is not None:
            preprocess_kwargs["max_retries"] = int(
                self._config.ddr_preprocess_max_retries
            )
        if getattr(self._config, "ddr_preprocess_batch_size", None) is not None:
            preprocess_kwargs["batch_size"] = int(self._config.ddr_preprocess_batch_size)
        if getattr(self._config, "ddr_preprocess_show_progress", None) is not None:
            preprocess_kwargs["show_progress"] = bool(
                self._config.ddr_preprocess_show_progress
            )
        if staged_proxy_path and ddr_x509_proxy_effective:
            preprocess_kwargs["x509_proxy"] = ddr_x509_proxy_effective
            preprocess_env = dict(
                preprocess_kwargs.get("environment_variables", {}) or {}
            )
            preprocess_env.update(ddr_environment_variables)
            preprocess_env["X509_USER_PROXY"] = ddr_x509_proxy_effective
            preprocess_kwargs["environment_variables"] = preprocess_env
        elif ddr_environment_variables:
            preprocess_kwargs.setdefault(
                "environment_variables",
                dict(ddr_environment_variables),
            )

        ddr_kwargs = dict(getattr(self._config, "ddr_kwargs", {}) or {})
        ddr_kwargs.setdefault(
            "results_directory",
            str(getattr(self._config, "ddr_results_directory") or results_dir),
        )
        ddr_kwargs.setdefault("resources_processing", resources_processing)
        if resources_accumulating is not None:
            ddr_kwargs.setdefault("resources_accumulating", resources_accumulating)
        ddr_kwargs.setdefault("step_size", step_size)
        if max_task_retries is not None:
            ddr_kwargs.setdefault("max_task_retries", max_task_retries)
        if ddr_verbose is not None:
            ddr_kwargs.setdefault("verbose", ddr_verbose)
        if ddr_environment_variables:
            ddr_kwargs.setdefault("environment_variables", ddr_environment_variables)
        if staged_proxy_path and ddr_x509_proxy_effective:
            ddr_kwargs["x509_proxy"] = ddr_x509_proxy_effective
            ddr_env = dict(ddr_kwargs.get("environment_variables", {}) or {})
            ddr_env["X509_USER_PROXY"] = ddr_x509_proxy_effective
            ddr_kwargs["environment_variables"] = ddr_env
        if _topeft_ddr_debug_enabled():
            proxy_staged_exists = (
                int(Path(staged_proxy_path).exists()) if staged_proxy_path else 0
            )
            _ddr_debug_emit(
                "proxy staging "
                f"staging_dir={context.staging_dir} "
                f"proxy_source={self._config.ddr_x509_proxy} "
                f"proxy_staged_path={staged_proxy_path} "
                f"proxy_staged_exists={proxy_staged_exists} "
                f"ddr_x509_proxy_effective={ddr_x509_proxy_effective} "
                f"x509_env={ddr_environment_variables.get('X509_USER_PROXY')}",
                include_paths=True,
            )
            _ddr_debug_emit(
                "handoff paths "
                f"preprocessed_data_path={preprocessed_data_path} "
                f"save_preprocess_path={save_preprocess_path} "
                f"results_dir={results_dir} "
                f"processor_file={processor_file} "
                f"processor_module={processor_module_name} "
                f"extra_files={len(extra_files)} "
                f"processor_staged={int(processor_file_str in extra_files)} "
                f"has_staged_proxy={int(bool(staged_proxy_path))} "
                f"ddr_x509_proxy_effective={ddr_x509_proxy_effective} "
                f"resources_processing={ddr_kwargs.get('resources_processing')} "
                f"resources_accumulating={ddr_kwargs.get('resources_accumulating')}",
                include_paths=True,
            )
            _emit_ddr_processor_key_sanity(processors)
        probe_enabled = _topeft_ddr_debug_enabled() and (
            _env_flag_enabled("TOPEFT_DDR_WORKER_PROBE")
            or _env_flag_enabled("TOPEFT_DDR_CERT_PROBE")
        )
        if probe_enabled:
            probe_url = str(
                os.environ.get(
                    "TOPEFT_DDR_WORKER_PROBE_URL",
                    os.environ.get("TOPEFT_DDR_CERT_PROBE_URL", _DEFAULT_DDR_CERT_PROBE_URL),
                )
            )
            timeout_raw = os.environ.get(
                "TOPEFT_DDR_WORKER_PROBE_TIMEOUT",
                os.environ.get("TOPEFT_DDR_CERT_PROBE_TIMEOUT", "20"),
            )
            try:
                probe_timeout = max(5, int(timeout_raw))
            except ValueError:
                probe_timeout = 20
            probe_env = dict(preprocess_kwargs.get("environment_variables", {}) or {})
            probe_payload = _run_ddr_worker_cert_probe_task(
                manager,
                extra_files=extra_files,
                environment_variables=probe_env,
                run_info_path=run_info_path,
                test_url=probe_url,
                timeout_seconds=probe_timeout,
            )
            logger.info(
                "[taskvine] DDR worker cert probe status=%s successful=%s report=%s",
                probe_payload.get("status"),
                probe_payload.get("successful"),
                probe_payload.get("report_path"),
            )
            _ddr_debug_emit(
                "worker cert probe "
                f"status={probe_payload.get('status')} "
                f"successful={probe_payload.get('successful')} "
                f"report_path={probe_payload.get('report_path')} "
                f"stdout_path={probe_payload.get('stdout_path')} "
                f"stderr_path={probe_payload.get('stderr_path')} "
                f"task_id={probe_payload.get('task_id')}",
                include_paths=True,
            )
            if probe_payload.get("staging_errors"):
                logger.warning(
                    "[taskvine] DDR worker cert probe staging_errors=%s",
                    probe_payload.get("staging_errors"),
                )

        try:
            with _instrument_ddr_runtime_stages(ddr_helpers):
                with _ddr_debug_stage(
                    "compute_handoff",
                    details=(
                        f"processors={len(processors)} "
                        f"datasets={len(data)} "
                        f"manager={context.manager_name}"
                    ),
                ):
                        raw_output = ddr_helpers.run_ddr(
                            manager=manager,
                            data=data,
                            processors=processors,
                            schema=NanoAODSchema,
                        extra_files=extra_files,
                        tree_name=self._config.treename or "Events",
                        preprocessed_data_path=preprocessed_data_path,
                        save_preprocess_path=save_preprocess_path,
                            preprocess_kwargs=preprocess_kwargs or None,
                            ddr_kwargs=ddr_kwargs,
                        )
            return raw_output
        finally:
            if _topeft_ddr_debug_enabled():
                _emit_transactions_snapshot("finally_before_manager_shutdown")
            try:
                manager.shutdown()
            except Exception:
                logger.debug("DDR manager shutdown encountered an error", exc_info=True)
            if _topeft_ddr_debug_enabled():
                _ddr_debug_emit("ddr_debug_context end", include_paths=True)
            _clear_ddr_debug_context()

    def _build_ddr_processors(
        self,
        *,
        histogram_plan: HistogramPlan,
        samplesdict: Mapping[str, Mapping[str, Any]],
        golden_jsons: Mapping[str, str],
        analysis_processor_module: Any,
        coffea_processor_module: Any,
        ecut_threshold: Optional[float],
    ) -> Dict[str, Any]:
        processors: Dict[str, Any] = {}
        grouped_processors: Dict[str, Dict[str, Any]] = {}
        processor_key_delim = getattr(self._config, "ddr_processor_key_delim", "-")
        total_tasks = len(histogram_plan.tasks)
        for idx, task in enumerate(histogram_plan.tasks):
            channel_dict = task.channel_metadata
            if not channel_dict:
                logger.debug(
                    "[taskvine] Skipping task %s (%s/%s) due to missing channel metadata",
                    idx,
                    task.sample,
                    task.clean_channel,
                )
                continue
            sample_name = task.sample
            sample_info = samplesdict.get(sample_name)
            if sample_info is None:
                logger.warning(
                    "[taskvine] Skipping task %s (%s/%s) because sample is absent from samplesdict",
                    idx,
                    sample_name,
                    task.clean_channel,
                )
                continue

            if not isinstance(task.available_systematics, Mapping):
                raise TypeError(
                    "HistogramTask.available_systematics must be a mapping of systematic categories to names."
                )

            variations_by_name = {
                getattr(variation, "name", None): variation for variation in task.variations
            }
            if not variations_by_name:
                raise ValueError(
                    f"Task {idx} ({task.sample}/{task.clean_channel}) has no systematic variations."
                )

            for variation_label, hist_entries in task.hist_keys.items():
                if variation_label not in variations_by_name:
                    raise KeyError(
                        f"Variation label '{variation_label}' is missing from task variations for "
                        f"sample={task.sample} channel={task.clean_channel} var={task.variable} app={task.application}."
                    )
                if not hist_entries:
                    continue

                systematic_label = _normalise_systematic_label(hist_entries[0][4])
                processor_key = build_ddr_processor_key(
                    task.clean_channel,
                    task.variable,
                    task.application,
                    systematic_label,
                    delim=processor_key_delim,
                )

                grouped_entry = grouped_processors.get(processor_key)
                if grouped_entry is None:
                    grouped_entry = {
                        "task_template": task,
                        "channel_dict": channel_dict,
                        "variation_label": variation_label,
                        "variation": variations_by_name[variation_label],
                        "sample_dict": OrderedDict(),
                        "hist_entries": [],
                        "hist_entries_set": set(),
                        "available_systematics": {
                            key: set(value)
                            for key, value in task.available_systematics.items()
                        },
                        "golden_json_paths": {},
                    }
                    grouped_processors[processor_key] = grouped_entry
                else:
                    if grouped_entry["variation_label"] != variation_label:
                        raise ValueError(
                            "Conflicting variations mapped to the same DDR processor key "
                            f"{processor_key!r}: {grouped_entry['variation_label']!r} vs {variation_label!r}."
                        )
                    for key, value in task.available_systematics.items():
                        grouped_entry["available_systematics"].setdefault(key, set()).update(value)

                grouped_entry["sample_dict"][sample_name] = sample_info
                if sample_info.get("isData"):
                    golden_json_path = self._resolve_golden_json(sample_info, golden_jsons)
                    grouped_entry["golden_json_paths"][sample_name] = golden_json_path

                for hist_entry in hist_entries:
                    normalized_entry = tuple(hist_entry)
                    if len(normalized_entry) != 5:
                        raise ValueError(
                            "DDR histogram entries must be 5-tuples "
                            f"(found {normalized_entry!r} for processor key {processor_key!r})."
                        )
                    entry_systematic = _normalise_systematic_label(normalized_entry[4])
                    if entry_systematic != systematic_label:
                        raise ValueError(
                            "DDR histogram entry systematic does not match processor grouping key: "
                            f"processor_key={processor_key!r}, entry={normalized_entry!r}."
                        )
                    if normalized_entry in grouped_entry["hist_entries_set"]:
                        continue
                    grouped_entry["hist_entries_set"].add(normalized_entry)
                    grouped_entry["hist_entries"].append(normalized_entry)

        for processor_key in sorted(grouped_processors.keys()):
            grouped_entry = grouped_processors[processor_key]
            task_template = grouped_entry["task_template"]
            hist_entries = tuple(grouped_entry["hist_entries"])
            if not hist_entries:
                continue
            variation_label = grouped_entry["variation_label"]
            hist_keys = {variation_label: hist_entries}
            available_systematics = {
                key: tuple(sorted(values))
                for key, values in grouped_entry["available_systematics"].items()
            }

            processor_instance = self._build_processor_instance(
                task=task_template,
                sample_dict=grouped_entry["sample_dict"],
                channel_dict=grouped_entry["channel_dict"],
                analysis_processor_module=analysis_processor_module,
                coffea_processor_module=coffea_processor_module,
                golden_jsons=golden_jsons,
                ecut_threshold=ecut_threshold,
                hist_keys=hist_keys,
                systematic_variations=(grouped_entry["variation"],),
                available_systematics=available_systematics,
                golden_json_paths=grouped_entry["golden_json_paths"] or None,
            )
            processors[processor_key] = processor_instance
            logger.debug(
                "[taskvine] Added processor %s for %d samples (channel=%s variable=%s application=%s variation=%s)",
                processor_key,
                len(grouped_entry["sample_dict"]),
                task_template.clean_channel,
                task_template.variable,
                task_template.application,
                variation_label,
            )
        logger.info(
            "[taskvine] Constructed %d processors from %d histogram tasks",
            len(processors),
            total_tasks,
        )
        return processors

    def _create_ddr_manager(self, context: TaskVineContext) -> Any:
        import ndcctools.taskvine as vine

        port_min, port_max = context.port_range
        staging_dir = context.staging_dir
        run_info_path = staging_dir / "vine-run-info"
        run_info_path.mkdir(parents=True, exist_ok=True)

        def _instantiate(port: int) -> Any:
            _ddr_debug_emit(
                "manager instantiate "
                f"name={context.manager_name} "
                f"port={port} "
                f"staging_dir={staging_dir} "
                f"run_info_path={run_info_path}"
            )
            _ddr_debug_emit(
                " ".join(
                    (
                        f"manager_project={context.manager_name}",
                        f"manager_port={port}",
                        f"manager_template={context.manager_template}",
                        f"manager_source={context.manager_source}",
                        f"staging_dir={staging_dir}",
                        f"run_info={run_info_path}",
                    )
                ),
                include_paths=False,
            )
            return vine.Manager(
                port=port,
                name=context.manager_name,
                staging_path=str(staging_dir),
                run_info_path=str(run_info_path),
            )

        if not bool(self._config.negotiate_manager_port):
            try:
                return _instantiate(port_min)
            except Exception as exc:  # pragma: no cover - best effort
                if _is_port_allocation_error(exc):
                    raise RuntimeError(f"DDR manager could not bind port {port_min}.") from exc
                raise

        attempted: Set[int] = set()
        last_error: Optional[BaseException] = None
        for _ in range(port_min, port_max + 1):
            port = _select_manager_port(port_min, port_max, exclude=attempted)
            attempted.add(port)
            try:
                return _instantiate(port)
            except Exception as exc:
                if _is_port_allocation_error(exc):
                    last_error = exc
                    continue
                raise

        range_desc = f"{port_min}-{port_max}" if port_min != port_max else str(port_min)
        message = f"DDR manager could not bind a port in range {range_desc}."
        if last_error is not None:
            raise RuntimeError(message) from last_error
        raise RuntimeError(message)

    def run(self) -> None:
        from topeft.modules.systematics import SystematicsHelper
        import coffea.processor as coffea_processor

        self._validate_config()

        sample_specs = self._sample_loader.collect(self._config.json_files)
        samplesdict, flist = self._sample_loader.load(sample_specs)

        if self._config.do_systs:
            self._ensure_weight_variations(samplesdict)

        nevts_total = sum(sample["nEvents"] for sample in samplesdict.values())

        golden_jsons = self._metadata.get("golden_jsons", {}) if self._metadata else {}
        if not golden_jsons:
            raise ValueError(f"golden_jsons mapping missing from metadata ({self._metadata_path}).")

        var_defs = self._metadata.get("variables")
        if not isinstance(var_defs, Mapping):
            raise TypeError(
                "metadata['variables'] must be a mapping of histogram definitions "
                f"(source: {self._metadata_path})"
            )

        sample_years = {
            str(samplesdict[sample_name]["year"])
            for sample_name in samplesdict
            if "year" in samplesdict[sample_name]
        }

        active_features = set(self._channel_planner.active_features)
        tau_analysis = "requires_tau" in active_features
        systematics_helper = SystematicsHelper(
            self._metadata,
            sample_years=sample_years,
            tau_analysis=tau_analysis,
        )

        histogram_plan = self._histogram_planner.plan(samplesdict, systematics_helper)
        has_mc_samples = any(not sample.get("isData") for sample in samplesdict.values())
        has_data_samples = any(sample.get("isData") for sample in samplesdict.values())
        validate_histogram_plan_systematics(
            metadata=self._metadata,
            tasks=histogram_plan.tasks,
            do_systs=self._config.do_systs,
            has_mc_samples=has_mc_samples,
            has_data_samples=has_data_samples,
            tau_analysis=tau_analysis,
            metadata_source=self._metadata_path,
        )

        self._emit_histogram_summary(histogram_plan)

        if self._config.pretend:
            logger.info("Pretend mode active; validated configuration and histogram plan without executing.")
            return

        self._ensure_wilson_coefficients(samplesdict)

        ecut_threshold = self._config.ecut if self._config.ecut is None else float(self._config.ecut)

        tstart = time.time()
        executor_mode = (self._config.executor or "taskvine").strip().lower()
        allowed_executors = set(LST_OF_KNOWN_EXECUTORS)
        if executor_mode not in allowed_executors:
            raise ValueError(
                f"Unsupported executor mode '{executor_mode}'. Expected one of: {', '.join(LST_OF_KNOWN_EXECUTORS)}."
            )
        self._config.executor = executor_mode
        processor_file = _resolve_processor_file_path(self._config.processor)
        analysis_processor_module, processor_module_name = _load_processor_module_from_file(
            processor_file
        )
        logger.info(
            "Processor selection: file=%s module=%s",
            processor_file,
            processor_module_name,
        )

        if executor_mode == "taskvine":
            ddr_output = self._execute_ddr(
                histogram_plan=histogram_plan,
                samplesdict=samplesdict,
                flist=flist,
                golden_jsons=golden_jsons,
                ecut_threshold=ecut_threshold,
                analysis_processor_module=analysis_processor_module,
                processor_file=processor_file,
                processor_module_name=processor_module_name,
                coffea_processor_module=coffea_processor,
            )
            output_schema = getattr(self._config, "ddr_output_schema", "flat")
            if output_schema == "flat":
                output = flatten_ddr_output(
                    ddr_output,
                    delim=getattr(self._config, "ddr_processor_key_delim", "-"),
                    output_schema="flat",
                    preserve_sidecars=bool(getattr(self._config, "ddr_preserve_sidecars", False)),
                    sidecars_key=str(getattr(self._config, "ddr_sidecars_key", "__sidecars__")),
                )
            elif output_schema == "tuple":
                output = flatten_ddr_output(
                    ddr_output,
                    delim=getattr(self._config, "ddr_processor_key_delim", "-"),
                    output_schema="tuple",
                    preserve_sidecars=bool(getattr(self._config, "ddr_preserve_sidecars", False)),
                    sidecars_key=str(getattr(self._config, "ddr_sidecars_key", "__sidecars__")),
                )
            else:
                raise ValueError(
                    f"Unsupported ddr_output_schema '{output_schema}'. Expected 'flat' or 'tuple'."
                )
            dt = time.time() - tstart
            if nevts_total:
                logger.info(
                    "[taskvine] Processed %d events in %.2f seconds (%.2f evts/sec)",
                    nevts_total,
                    dt,
                    (nevts_total / dt) if dt else 0.0,
                )
            else:
                logger.info("[taskvine] CoffeaDynamicDataReduction finished in %.2f seconds", dt)
            self._store_output(output)
            return

        runner = self._executor_factory.create_runner()

        output: Dict[str, Any] = {}
        merged_region_yields: Dict[Tuple[str, str, str, str], np.ndarray] = {}

        total_tasks = len(histogram_plan.tasks)
        for idt, task in enumerate(histogram_plan.tasks):
            logger.info(
                "Starting histogram task %d/%d: sample=%s channel=%s variable=%s application=%s variations=%d",
                idt + 1,
                total_tasks,
                task.sample,
                task.clean_channel,
                task.variable,
                task.application,
                len(task.variations),
            )
            sample_dict = samplesdict[task.sample]
            sample_files = list(flist[task.sample])
            if self._config.executor == "futures":
                prefetch_files = self._config.futures_prefetch
                if prefetch_files is None or prefetch_files <= 0:
                    sample_flist = sample_files
                else:
                    sample_flist = sample_files[: int(prefetch_files)]
            else:
                sample_flist = sample_files

            channel_dict = task.channel_metadata
            if not channel_dict:
                continue

            if _DEV_DEBUG:
                logger.info("Channel %s metadata: %s", task.clean_channel, channel_dict)
                logger.info("Task detail: %s", task)

            processor_instance = self._build_processor_instance(
                task=task,
                sample_dict=sample_dict,
                channel_dict=channel_dict,
                analysis_processor_module=analysis_processor_module,
                coffea_processor_module=coffea_processor,
                golden_jsons=golden_jsons,
                ecut_threshold=ecut_threshold,
            )

            self._log_task_submission(task)

            attempt = 0
            max_retries = 0
            if self._config.executor == "futures" and self._config.futures_retries:
                max_retries = max(int(self._config.futures_retries), 0)
            retry_wait = 0.0
            if self._config.executor == "futures" and self._config.futures_retry_wait is not None:
                retry_wait = max(float(self._config.futures_retry_wait), 0.0)

            while True:
                try:
                    out = runner(
                        {task.sample: sample_flist},
                        processor_instance,
                        self._config.treename,
                        # coffea Runner.__call__ expects (fileset, processor_instance, treename)
                    )
                except Exception as exc:
                    if attempt >= max_retries:
                        raise
                    attempt += 1
                    logger.warning(
                        "[futures] task for %s failed (attempt %d/%d): %s",
                        task.sample,
                        attempt,
                        max_retries,
                        exc,
                    )
                    if retry_wait > 0:
                        time.sleep(retry_wait)
                    continue
                else:
                    break

            summary_payload = out.pop(analysis_processor.AnalysisProcessor.VARIATION_SUMMARY_KEY, ())
            region_yields_payload = out.pop("region_yields", None)
            if region_yields_payload:
                _merge_region_yields(merged_region_yields, region_yields_payload)
            self._log_variation_recap(
                task_index=idt + 1,
                total_tasks=total_tasks,
                task=task,
                summary_entries=summary_payload or (),
            )
            output.update(out)

        if merged_region_yields:
            output["region_yields"] = merged_region_yields
        dt = time.time() - tstart

        if self._config.executor == "futures":
            logger.info(
                "Processing time: %.2f s with %d workers (%.2f s cpu overall)",
                dt,
                self._config.nworkers,
                dt * self._config.nworkers,
            )

        self._store_output(output)

    def _emit_histogram_summary(self, plan: HistogramPlan) -> None:
        """Print the planned histogram combinations based on the configured verbosity."""

        verbosity = getattr(self._config, "summary_verbosity", "brief") or "brief"
        verbosity = str(verbosity).strip().lower()
        if verbosity not in {"none", "brief", "full"}:
            verbosity = "brief"

        if not plan.summary or verbosity == "none":
            return

        samples = unique_preserving_order(str(entry.sample) for entry in plan.summary)
        channel_pairs = unique_preserving_order((str(entry.channel), str(entry.application)) for entry in plan.summary)
        variables = unique_preserving_order(str(entry.variable) for entry in plan.summary)
        systematics = unique_preserving_order(str(entry.systematic) for entry in plan.summary)

        def _format_values(values: Sequence[str]) -> str:
            return ", ".join(values) if values else "None"

        logger.info("Planned histogram summary:")
        logger.info("- Samples: %s", _format_values(samples))
        logger.info(
            "- Channels & applications: %s",
            _format_values([f"{channel} ({application})" for channel, application in channel_pairs]),
        )
        logger.info("- Variables: %s", _format_values(variables))
        logger.info("- Systematics: %s", _format_values(systematics))

        if verbosity == "brief":
            return

        headers = ("Sample", "Channel", "Variable", "Application", "Systematic")
        rows = [
            (str(entry.sample), str(entry.channel), str(entry.variable), str(entry.application), str(entry.systematic))
            for entry in plan.summary
        ]

        column_widths = [
            max(len(header), *(len(row[idx]) for row in rows)) if rows else len(header)
            for idx, header in enumerate(headers)
        ]
        row_format = "  ".join(f"{{:{width}}}" for width in column_widths)

        if getattr(self._config, "split_lep_flavor", False):
            logger.info(
                "Note: lepton-flavor channels reuse the processor task configured for their base channel when flavor splitting is enabled."
            )

        logger.info("Planned histogram combinations:")
        logger.info(row_format.format(*headers))
        logger.info("  ".join("-" * width for width in column_widths))
        for row in rows:
            logger.info(row_format.format(*row))

        summary_payload = [asdict(entry) for entry in plan.summary]

        logger.info("Structured summary:")
        try:
            import yaml  # type: ignore

            dumped = yaml.safe_dump(summary_payload, sort_keys=False).strip()
            logger.info("%s", dumped or "[]")
        except Exception:  # pragma: no cover - optional dependency
            logger.info("%s", json.dumps(summary_payload, indent=2))

    def _validate_config(self) -> None:
        if self._config.executor not in LST_OF_KNOWN_EXECUTORS:
            raise Exception(
                f'The "{self._config.executor}" executor is not known. Please specify an executor from the known executors '
                f"({LST_OF_KNOWN_EXECUTORS}). Exiting."
            )
        if self._config.do_renormfact_envelope:
            if not self._config.do_systs:
                raise Exception("Error: Cannot specify do_renormfact_envelope if we are not including systematics.")
            if not self._config.do_np:
                raise Exception(
                    "Error: Cannot specify do_renormfact_envelope if we have not already done the integration across the appl axis that occurs in the data driven estimator step."
                )
        if self._config.test:
            if self._config.executor == "futures":
                self._config.nchunks = 2
                self._config.chunksize = 100
                self._config.nworkers = 1
                logger.info(
                    "Running a fast futures test with %d workers, %d chunks of %d events",
                    self._config.nworkers,
                    self._config.nchunks,
                    self._config.chunksize,
                )
            elif self._config.executor == "iterative":
                self._config.nchunks = 2
                self._config.chunksize = 100
                logger.info(
                    "Running a fast iterative test with %d chunks of %d events",
                    self._config.nchunks,
                    self._config.chunksize,
                )
            else:
                raise Exception(
                    f'The "test" option is not set up to work with the {self._config.executor} executor. Exiting.'
                )

    def _ensure_weight_variations(self, samplesdict: Mapping[str, Mapping[str, Any]]) -> None:
        missing_default_variations = [variation for variation in DEFAULT_WEIGHT_VARIATIONS if variation not in self._weight_variations]
        if missing_default_variations:
            warnings.warn(
                "Default sum-of-weights variations will not be processed: " + ", ".join(missing_default_variations),
                RuntimeWarning,
            )

        for sample_info in samplesdict.values():
            if sample_info.get("isData"):
                continue
            for wgt_var in self._weight_variations:
                if wgt_var not in sample_info:
                    raise Exception(f'Missing weight variation "{wgt_var}".')

    def _ensure_wilson_coefficients(self, samplesdict: Mapping[str, Mapping[str, Any]]) -> None:
        if self._config.wc_list:
            return
        for sample_info in samplesdict.values():
            for wc in sample_info.get("WCnames", []) or []:
                if wc not in self._config.wc_list:
                    self._config.wc_list.append(wc)
        if self._config.wc_list:
            if len(self._config.wc_list) == 1:
                wc_print = self._config.wc_list[0]
            elif len(self._config.wc_list) == 2:
                wc_print = " and ".join(self._config.wc_list)
            else:
                wc_print = ", ".join(self._config.wc_list[:-1]) + ", and " + self._config.wc_list[-1]
            logger.info("Wilson coefficients: %s", wc_print)
        else:
            logger.info("No Wilson coefficients specified")

    def _store_output(self, output: Mapping[str, Any]) -> None:
        if not os.path.isdir(self._config.outpath):
            os.system("mkdir -p %s" % self._config.outpath)
        out_pkl_file = os.path.join(self._config.outpath, self._config.outname + ".pkl.gz")

        serialised_output = normalise_runner_output(output)
        if isinstance(serialised_output, Mapping):
            total_bins, filled_bins = tuple_dict_stats(serialised_output)
            if total_bins:
                fill_fraction = 100 * filled_bins / total_bins
                logger.info("Filled %.0f bins, nonzero bins: %1.1f %%", total_bins, fill_fraction)

        logger.info("Saving output in %s", out_pkl_file)
        with gzip.open(out_pkl_file, "wb") as fout:
            import cloudpickle

            cloudpickle.dump(serialised_output, fout)
        logger.info("Finished writing %s", out_pkl_file)

        if self._config.do_np:
            logger.info("Starting nonprompt estimation")
            out_pkl_file_name_np = os.path.join(self._config.outpath, self._config.outname + "_np.pkl.gz")
            from topeft.modules.dataDrivenEstimation import DataDrivenProducer

            ddp = DataDrivenProducer(out_pkl_file, out_pkl_file_name_np)
            logger.info("Saving nonprompt output in %s", out_pkl_file_name_np)
            ddp.dumpToPickle()
            logger.info("Finished writing nonprompt output")
            if self._config.do_renormfact_envelope:
                logger.info("Applying renorm/fact envelope to nonprompt output")
                from topeft.modules.get_renormfact_envelope import get_renormfact_envelope

                dict_of_histos = topcoffea_utils.get_hist_from_pkl(out_pkl_file_name_np, allow_empty=False)
                dict_of_histos_after_applying_envelope = get_renormfact_envelope(dict_of_histos)
                topcoffea_utils.dump_to_pkl(out_pkl_file_name_np, dict_of_histos_after_applying_envelope)


def run_workflow(
    config: RunConfig,
    *,
    metadata_bundle: metadata_authority.MetadataBundle | None = None,
) -> None:
    """Convenience wrapper mirroring the behaviour of ``run_analysis.py``."""

    from topeft.modules.channel_metadata import ChannelMetadataHelper

    scenario_names = unique_preserving_order(config.scenario_names)
    if not scenario_names:
        scenario_names = [DEFAULT_SCENARIO_NAME]
    config.scenario_names = list(scenario_names)
    primary_scenario = config.scenario_names[0]

    if metadata_bundle is None:
        metadata_source = config.metadata_path
        if not metadata_source:
            raise ValueError(
                "RunConfig.metadata_path is not set. Provide a metadata bundle before launching run_workflow."
            )
        metadata_bundle = metadata_authority.load_metadata_bundle(
            metadata_source,
            primary_scenario,
            strict=config.channel_groups_strict,
            required_sections=("channels", "variables"),
            metadata_source="explicit",
        )

    if metadata_bundle.scenario.name != primary_scenario:
        raise ValueError(
            "Scenario mismatch between RunConfig and metadata bundle: "
            f"{primary_scenario!r} vs {metadata_bundle.scenario.name!r}."
        )

    if len(config.scenario_names) > 1:
        logger.warning(
            "Multiple scenarios were requested (%s); using primary scenario '%s' for channel selection.",
            ", ".join(config.scenario_names),
            primary_scenario,
        )
        config.scenario_names = [primary_scenario]

    primary_scenario = metadata_bundle.scenario.name
    metadata_file = metadata_bundle.metadata_path
    metadata = metadata_bundle.metadata
    channels_data = metadata_bundle.channels
    config.metadata_path = str(metadata_file)

    metadata_variations = metadata_non_nominal_bases(metadata)
    if metadata_variations:
        logger.info(
            "Metadata '%s' exposes %d non-nominal systematics: %s",
            metadata_file,
            len(metadata_variations),
            ", ".join(sorted(metadata_variations)),
        )
    else:
        logger.info("Metadata '%s' defines only the nominal variation.", metadata_file)

    if config.do_systs and not metadata_variations:
        raise ValueError(
            f"--do-systs requested but metadata '{metadata_file}' does not define non-nominal systematics."
        )
    if not config.do_systs and metadata_variations:
        logger.info(
            "Systematic variations are available but disabled (--do-systs not set). "
            "Only nominal histograms will be produced."
        )

    weight_variations = weight_variations_from_metadata(metadata, DEFAULT_WEIGHT_VARIATIONS)
    sample_loader = SampleLoader(default_prefix=config.prefix, weight_variables=weight_variations)

    if not channels_data:
        raise ValueError(
            f"Channel metadata is missing for scenario '{primary_scenario}' (source: {metadata_file})."
        )

    channel_helper = ChannelMetadataHelper(channels_data)

    strict_mode = bool(config.channel_groups_strict)
    channel_planner = ChannelPlanner(
        channel_helper,
        skip_sr=config.skip_sr,
        skip_cr=config.skip_cr,
        scenario_names=config.scenario_names,
        channel_groups_strict=strict_mode,
        warn_on_partial_groups=True,
    )

    var_defs = metadata.get("variables")
    if not isinstance(var_defs, Mapping):
        raise TypeError("metadata['variables'] must be a mapping of histogram definitions")

    histogram_planner = HistogramPlanner(config=config, variable_definitions=var_defs, channel_planner=channel_planner)

    executor_factory = ExecutorFactory(config)

    workflow = RunWorkflow(
        config=config,
        metadata=metadata,
        sample_loader=sample_loader,
        channel_planner=channel_planner,
        histogram_planner=histogram_planner,
        executor_factory=executor_factory,
        weight_variations=weight_variations,
        metadata_path=str(metadata_file),
    )
    workflow.run()


__all__ = [
    "ChannelPlanner",
    "HistogramPlanner",
    "HistogramPlan",
    "HistogramCombination",
    "HistogramTask",
    "ExecutorFactory",
    "RunWorkflow",
    "run_workflow",
    "normalize_jet_category",
]
