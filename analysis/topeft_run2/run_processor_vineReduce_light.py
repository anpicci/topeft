#!/usr/bin/env python
"""Lightweight TaskVine DDR runner for submission-path isolation tests."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Mapping, MutableMapping, Optional, Tuple

import cloudpickle
import ndcctools.taskvine as vine
from coffea.nanoevents import NanoAODSchema
from dynamic_data_reduction import CoffeaDynamicDataReduction


def _debug_enabled() -> bool:
    value = os.environ.get("TOPEFT_DDR_DEBUG")
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _debug(message: str) -> None:
    if not _debug_enabled():
        return
    print(f"[TOPEFT_DDR_DEBUG] {message}", file=sys.stderr, flush=True)


def _parse_port(value: str) -> Tuple[int, int]:
    parts = [piece.strip() for piece in str(value).split("-") if piece.strip()]
    if not parts:
        raise ValueError("Invalid --port value: expected PORT or PORT_MIN-PORT_MAX.")
    if len(parts) == 1:
        port = int(parts[0])
        return (port, port)
    if len(parts) == 2:
        return (int(parts[0]), int(parts[1]))
    raise ValueError("Invalid --port value: expected PORT or PORT_MIN-PORT_MAX.")


def _load_preprocessed_data(path: Path) -> Mapping[str, Mapping[str, Any]]:
    payload: Any
    data = path.read_bytes()
    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception:
        payload = cloudpickle.loads(data)
    if not isinstance(payload, Mapping):
        raise TypeError(
            f"Preprocessed payload must be a mapping, found {type(payload)!r} at {path}."
        )
    return payload


def _summarize_payload(payload: Mapping[str, Mapping[str, Any]]) -> Tuple[int, int, Optional[int]]:
    dataset_count = len(payload)
    total_files = 0
    total_entries = 0
    saw_entries = False
    for dataset_specs in payload.values():
        files = dataset_specs.get("files")
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


def _safe_manager_call(manager: Any, attr: str) -> Any:
    value = getattr(manager, attr, None)
    if callable(value):
        try:
            return value()
        except Exception:
            return "<call-failed>"
    return value


def _extract_relevant_lines(text: str, manager_name: str) -> Tuple[str, ...]:
    keep = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if manager_name in line or "processing#" in line or "accumulating#" in line:
            keep.append(line)
    return tuple(keep)


def _poll_vine_status(
    *,
    manager_name: str,
    log_path: Path,
    stop_event: threading.Event,
    interval_seconds: float = 30.0,
    max_duration_seconds: float = 300.0,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(
            f"# vine_status poll start manager={manager_name} "
            f"interval={interval_seconds}s max_duration={max_duration_seconds}s\n"
        )
        handle.flush()
        while not stop_event.is_set() and (time.time() - started) <= max_duration_seconds:
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
            try:
                from subprocess import run

                completed = run(
                    ["vine_status", "--verbose"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=25,
                )
                lines = _extract_relevant_lines(completed.stdout or "", manager_name)
                handle.write(f"[{timestamp}] rc={completed.returncode} lines={len(lines)}\n")
                for line in lines[:25]:
                    handle.write(f"  {line}\n")
            except Exception as exc:
                handle.write(f"[{timestamp}] vine_status failed: {exc.__class__.__name__}: {exc}\n")
            handle.flush()
            stop_event.wait(interval_seconds)
        handle.write("# vine_status poll stop\n")
        handle.flush()


def _build_probe_processor():
    def _processor(events, **_kwargs):
        return {"n_events": int(len(events))}

    return _processor


def _accumulate_counts(left: Mapping[str, Any], right: Mapping[str, Any]) -> Dict[str, int]:
    left_value = int((left or {}).get("n_events", 0))
    right_value = int((right or {}).get("n_events", 0))
    return {"n_events": left_value + right_value}


def _prepare_env_tar(env_tar: Optional[Path], work_dir: Path) -> None:
    if env_tar is None:
        return
    if not env_tar.exists():
        raise FileNotFoundError(f"--env-tar path does not exist: {env_tar}")
    target = work_dir / "env.tar.gz"
    if target.exists() or target.is_symlink():
        if target.resolve() == env_tar.resolve():
            return
        target.unlink()
    target.symlink_to(env_tar)


def _stage_proxy(proxy_path: Optional[Path], staging_dir: Path) -> Optional[Path]:
    if proxy_path is None:
        return None
    if not proxy_path.exists():
        raise FileNotFoundError(f"--x509-proxy path does not exist: {proxy_path}")
    staged = staging_dir / "proxy.pem"
    staged.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(proxy_path, staged)
    return staged


def _worker_cmd(manager_name: str, env_tar: Optional[Path]) -> str:
    tokens = ["vine_submit_workers", "-M", manager_name]
    if env_tar is not None:
        tokens.extend(["--python-env", str(env_tar)])
    tokens.extend(["<worker-host-or-factory-options>"])
    return " ".join(tokens)


def resolve_light_manager_project_name(
    manager_name: Optional[str],
    *,
    default_manager: str,
) -> str:
    """Resolve the TaskVine project name for the light runner."""

    resolved_name, _ = resolve_light_manager_project_name_with_source(
        manager_name,
        default_manager=default_manager,
    )
    return resolved_name


def resolve_light_manager_project_name_with_source(
    manager_name: Optional[str],
    *,
    default_manager: str,
) -> Tuple[str, str]:
    """Resolve the TaskVine project name and source for the light runner."""

    if manager_name is None:
        return default_manager, "default"
    candidate = str(manager_name).strip()
    if candidate:
        return candidate, "config"
    return default_manager, "default"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a minimal direct CoffeaDynamicDataReduction workflow for TaskVine isolation."
    )
    default_manager = f"{os.environ.get('USER', 'user')}-taskvine-coffea"
    default_staging = Path(f"/tmp/topeft/{default_manager}")
    parser.add_argument("--manager-name", default=default_manager)
    parser.add_argument("--port", default="9123-9130")
    parser.add_argument("--staging-dir", default=str(default_staging))
    parser.add_argument("--run-info", default=None)
    parser.add_argument(
        "--preprocessed-json",
        default=str(default_staging / "logs" / "taskvine-results" / "ddr_preprocessed_data.json"),
    )
    parser.add_argument("--processor-file", default="analysis_processor.py")
    parser.add_argument("--env-tar", default=None)
    parser.add_argument("--x509-proxy", default=None)
    parser.add_argument("--step-size", type=int, default=500000)
    parser.add_argument("--max-task-retries", type=int, default=10)
    parser.add_argument("--resources-processing-cores", type=int, default=1)
    parser.add_argument("--resources-accumulating-cores", type=int, default=1)
    return parser


def main() -> int:
    args = _parser().parse_args()

    default_manager = f"{os.environ.get('USER', 'user')}-taskvine-coffea"
    manager_name, manager_source = resolve_light_manager_project_name_with_source(
        args.manager_name,
        default_manager=default_manager,
    )
    port_min, port_max = _parse_port(args.port)
    staging_dir = Path(args.staging_dir).expanduser()
    run_info = (
        Path(args.run_info).expanduser()
        if args.run_info
        else (staging_dir / "vine-run-info")
    )
    preprocessed_path = Path(args.preprocessed_json).expanduser()
    env_tar = Path(args.env_tar).expanduser() if args.env_tar else None
    proxy_path = Path(args.x509_proxy).expanduser() if args.x509_proxy else None
    processor_file = Path(args.processor_file).expanduser()
    if not processor_file.is_absolute():
        processor_file = (Path.cwd() / processor_file).resolve()

    if not preprocessed_path.exists():
        print(
            f"Missing preprocessed payload: {preprocessed_path}. "
            "Generate preprocess output first or pass --preprocessed-json.",
            file=sys.stderr,
            flush=True,
        )
        return 2

    staging_dir.mkdir(parents=True, exist_ok=True)
    run_info.mkdir(parents=True, exist_ok=True)
    _prepare_env_tar(env_tar, Path.cwd())
    staged_proxy = _stage_proxy(proxy_path, staging_dir)
    preprocessed_data = _load_preprocessed_data(preprocessed_path)
    datasets_count, files_count, entries_count = _summarize_payload(preprocessed_data)

    manager_port: Any
    if port_min == port_max:
        manager_port = port_min
    else:
        manager_port = [port_min, port_max]

    manager_template: Optional[str] = None
    _debug(
        " ".join(
            (
                f"manager_project={manager_name}",
                f"manager_port={manager_port}",
                f"manager_template={manager_template}",
                f"manager_source={manager_source}",
                f"staging_dir={staging_dir}",
                f"run_info={run_info}",
            )
        )
    )
    mgr = vine.Manager(
        port=manager_port,
        name=manager_name,
        staging_path=str(staging_dir),
        run_info_path=str(run_info),
    )
    mgr.tune("hungry-minimum", 1)
    try:
        mgr.enable_monitoring(watchdog=False)
    except Exception:
        _debug("manager.enable_monitoring(watchdog=False) failed; continuing")

    results_dir = staging_dir / "logs" / "taskvine-results-light"
    results_dir.mkdir(parents=True, exist_ok=True)

    extra_files = []
    if processor_file.exists():
        extra_files.append(str(processor_file))
    if staged_proxy is not None:
        extra_files.append(str(staged_proxy))

    processors = {"tensors": _build_probe_processor()}
    print(
        "DDR light runner: "
        f"manager={manager_name} "
        f"port={manager_port} "
        f"manager_template={manager_template} "
        f"manager_source={manager_source} "
        f"staging={staging_dir} "
        f"run_info={run_info} "
        f"preprocessed={preprocessed_path} "
        f"processors={len(processors)} "
        f"datasets={datasets_count} "
        f"files={files_count}",
        file=sys.stderr,
        flush=True,
    )
    print(
        f"Suggested worker command: {_worker_cmd(manager_name, env_tar)}",
        file=sys.stderr,
        flush=True,
    )
    _debug(
        "manager_stats "
        f"workers_connected={_safe_manager_call(mgr, 'workers_connected')} "
        f"hungry={_safe_manager_call(mgr, 'hungry')} "
        f"empty={_safe_manager_call(mgr, 'empty')} "
        f"entries={entries_count}"
    )

    ddr = CoffeaDynamicDataReduction(
        mgr,
        data=preprocessed_data,
        processors=processors,
        schema=NanoAODSchema,
        accumulator=_accumulate_counts,
        extra_files=extra_files,
        max_task_retries=int(args.max_task_retries),
        step_size=max(1, int(args.step_size)),
        resources_processing={"cores": max(1, int(args.resources_processing_cores))},
        resources_accumulating={"cores": max(1, int(args.resources_accumulating_cores))},
        results_directory=str(results_dir),
        x509_proxy=str(staged_proxy) if staged_proxy is not None else None,
        verbose=True,
    )
    if staged_proxy is not None:
        ddr_env = getattr(ddr, "environment_variables", None)
        if isinstance(ddr_env, MutableMapping):
            ddr_env["X509_USER_PROXY"] = "proxy.pem"

    poll_thread = None
    poll_stop = threading.Event()
    if _debug_enabled():
        poll_log = run_info / "topeft_ddr_debug_vine_status.log"
        poll_thread = threading.Thread(
            target=_poll_vine_status,
            kwargs={
                "manager_name": manager_name,
                "log_path": poll_log,
                "stop_event": poll_stop,
                "interval_seconds": 30.0,
                "max_duration_seconds": 300.0,
            },
            daemon=True,
        )
        poll_thread.start()
        _debug(f"started vine_status poller log={poll_log}")

    try:
        output = ddr.compute()
    finally:
        poll_stop.set()
        if poll_thread is not None:
            poll_thread.join(timeout=1.0)
        try:
            mgr.shutdown()
        except Exception:
            pass

    print(
        f"DDR light runner finished. output_keys={list(output.keys())[:5]}",
        file=sys.stderr,
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
