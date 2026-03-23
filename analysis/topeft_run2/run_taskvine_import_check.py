#!/usr/bin/env python
"""Submit minimal TaskVine tasks that only exercise worker-side imports."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import ndcctools.taskvine as vine

DEFAULT_ENV_TAR = Path(
    "/users/apiccine/work/ChUpdate/topeft/analysis/topeft_run2/topeft-envs/"
    "env_spec_729160ab_edit_HEAD.tar.gz"
)


def _debug_enabled() -> bool:
    value = os.environ.get("TOPEFT_DDR_DEBUG")
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _debug(message: str) -> None:
    if _debug_enabled():
        print(f"[TOPEFT_DDR_DEBUG] {message}", file=sys.stderr, flush=True)


def _parse_port(value: str) -> Tuple[int, int]:
    pieces = [piece.strip() for piece in str(value).split("-") if piece.strip()]
    if not pieces:
        raise ValueError("Invalid --port value: expected PORT or PORT_MIN-PORT_MAX")
    if len(pieces) == 1:
        port = int(pieces[0])
        return (port, port)
    if len(pieces) == 2:
        return (int(pieces[0]), int(pieces[1]))
    raise ValueError("Invalid --port value: expected PORT or PORT_MIN-PORT_MAX")


def _safe_manager_call(manager: Any, attr: str) -> Any:
    value = getattr(manager, attr, None)
    if callable(value):
        try:
            return value()
        except Exception:
            return "<call-failed>"
    return value


def _worker_command(manager_name: str, env_tar: Optional[Path]) -> str:
    tokens: List[str] = ["vine_submit_workers", "-M", manager_name]
    if env_tar is not None:
        tokens.extend(["--python-env", str(env_tar)])
    tokens.append("<worker-host-or-factory-options>")
    return " ".join(tokens)


def _render_payload(with_pandas: bool, task_index: int) -> str:
    pandas_block = ""
    if with_pandas:
        pandas_block = """
try:
    import pandas as pd
    print("IMPORT_OK pandas", pd.__version__, pd.__file__)
except Exception as exc:
    failures.append("pandas")
    print("IMPORT_FAIL pandas", type(exc).__name__, exc)
    traceback.print_exc()

try:
    import pandas._libs._cyutility as cy
    print("IMPORT_OK pandas._libs._cyutility", cy.__file__)
except Exception as exc:
    failures.append("pandas._libs._cyutility")
    print("IMPORT_FAIL pandas._libs._cyutility", type(exc).__name__, exc)
    traceback.print_exc()
"""
    payload = f"""python - <<'PY'
import platform
import sys
import traceback

failures = []
print("IMPORT_CHECK_BEGIN task={task_index}")
print("sys.executable", sys.executable)
print("sys.version", sys.version.replace("\\n", " "))
print("platform", platform.platform())
print("sys.path.begin")
for path_entry in sys.path[:50]:
    print(path_entry)
print("sys.path.end")

try:
    import numpy as np
    print("IMPORT_OK numpy", np.__version__, np.__file__)
except Exception as exc:
    failures.append("numpy")
    print("IMPORT_FAIL numpy", type(exc).__name__, exc)
    traceback.print_exc()
{pandas_block}
if failures:
    print("IMPORT_CHECK_RESULT FAIL", ",".join(failures))
    raise SystemExit(41)

print("IMPORT_CHECK_RESULT OK")
PY"""
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Submit minimal TaskVine tasks that only probe numpy/pandas imports "
            "inside worker python environments."
        )
    )
    default_manager = f"{os.environ.get('USER', 'user')}-taskvine-coffea"
    default_staging = Path(f"/tmp/topeft/{default_manager}")
    parser.add_argument("--manager-name", default=default_manager)
    parser.add_argument("--port", default="9123-9130")
    parser.add_argument("--staging-dir", default=str(default_staging))
    parser.add_argument("--run-info", default=None)
    parser.add_argument("--env-tar", default=str(DEFAULT_ENV_TAR))
    parser.add_argument("--n-tasks", type=int, default=10)
    parser.add_argument("--timeout-s", type=int, default=120)
    parser.add_argument("--with-pandas", dest="with_pandas", action="store_true", default=True)
    parser.add_argument("--without-pandas", dest="with_pandas", action="store_false")
    return parser


def _summarize_task(task: vine.Task) -> Mapping[str, Any]:
    output = task.std_output if task.std_output is not None else task.output
    if isinstance(output, bytes):
        output_text = output.decode("utf-8", errors="replace")
    else:
        output_text = str(output) if output is not None else ""
    return {
        "id": getattr(task, "id", None),
        "tag": getattr(task, "tag", None),
        "result": getattr(task, "result", None),
        "exit_code": getattr(task, "exit_code", None),
        "successful": bool(task.successful()) if hasattr(task, "successful") else None,
        "hostname": getattr(task, "hostname", None),
        "output": output_text,
    }


def main() -> int:
    args = _parser().parse_args()

    manager_name = str(args.manager_name)
    port_min, port_max = _parse_port(args.port)
    manager_port: Any = port_min if port_min == port_max else [port_min, port_max]
    staging_dir = Path(args.staging_dir).expanduser()
    run_info = (
        Path(args.run_info).expanduser()
        if args.run_info
        else (staging_dir / "vine-run-info")
    )
    env_tar = Path(args.env_tar).expanduser() if args.env_tar else None
    n_tasks = max(1, int(args.n_tasks))
    timeout_s = max(1, int(args.timeout_s))

    staging_dir.mkdir(parents=True, exist_ok=True)
    run_info.mkdir(parents=True, exist_ok=True)

    if env_tar is not None and not env_tar.exists():
        print(f"ERROR: --env-tar does not exist: {env_tar}", file=sys.stderr, flush=True)
        return 2

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

    env_file = mgr.declare_poncho(str(env_tar)) if env_tar is not None else None

    print(
        "TaskVine import-check: "
        f"manager={manager_name} port={manager_port} staging={staging_dir} "
        f"run_info={run_info} env_tar={env_tar} n_tasks={n_tasks} "
        f"with_pandas={args.with_pandas} timeout_s={timeout_s}",
        file=sys.stderr,
        flush=True,
    )
    print(
        f"Suggested worker command: {_worker_command(manager_name, env_tar)}",
        file=sys.stderr,
        flush=True,
    )
    _debug(
        "manager_stats "
        f"workers_connected={_safe_manager_call(mgr, 'workers_connected')} "
        f"hungry={_safe_manager_call(mgr, 'hungry')} "
        f"empty={_safe_manager_call(mgr, 'empty')}"
    )

    pending: MutableMapping[int, str] = {}
    for task_index in range(1, n_tasks + 1):
        task = vine.Task(_render_payload(args.with_pandas, task_index))
        task.set_tag(f"import-check-{task_index}")
        task.set_category("import-check")
        task.set_cores(1)
        task.set_memory(512)
        task.set_disk(512)
        if env_file is not None:
            task.add_environment(env_file)
        task_id = mgr.submit(task)
        pending[int(task_id)] = task.tag

    print(
        f"Submitted tasks={len(pending)}. Waiting for completion...",
        file=sys.stderr,
        flush=True,
    )

    completed: List[Mapping[str, Any]] = []
    deadline = time.time() + timeout_s
    while pending and time.time() < deadline:
        task = mgr.wait(5)
        if task is None:
            continue
        task_id = int(getattr(task, "id", -1))
        pending.pop(task_id, None)
        summary = _summarize_task(task)
        completed.append(summary)
        print(
            f"\n=== TASK_RESULT id={summary['id']} tag={summary['tag']} "
            f"success={summary['successful']} result={summary['result']} "
            f"exit_code={summary['exit_code']} host={summary['hostname']} ===",
            file=sys.stderr,
            flush=True,
        )
        print(summary["output"], file=sys.stderr, flush=True)

    timed_out = bool(pending)
    if timed_out:
        print(
            f"TIMEOUT: pending_tasks={len(pending)} timeout_s={timeout_s}. "
            "Some workers may be unavailable.",
            file=sys.stderr,
            flush=True,
        )
        _debug(f"pending_task_ids={sorted(pending.keys())[:20]}")

    success_count = 0
    fail_count = 0
    for summary in completed:
        if summary["successful"]:
            success_count += 1
        else:
            fail_count += 1
    print(
        "SUMMARY "
        f"completed={len(completed)} success={success_count} "
        f"failed={fail_count} pending={len(pending)}",
        file=sys.stderr,
        flush=True,
    )

    try:
        mgr.shutdown()
    except Exception:
        pass

    if timed_out and not completed:
        return 2
    if fail_count > 0:
        return 1
    if timed_out:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
