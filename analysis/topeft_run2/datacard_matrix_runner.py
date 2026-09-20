#!/usr/bin/env python3
"""Execute a prequalified datacard-row manifest sequentially and fail closed."""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from typing import Any


WORKSPACE_ROOT = Path("/users/apiccine/work/correction-lib")
WRAPPER = WORKSPACE_ROOT / "codex-run.sh"
PYTHON_ENV = Path("/users/apiccine/work/miniconda3/envs/clib-env/bin/python")
MANIFEST_SCHEMA = "topeft_datacard_matrix_v1"
RECEIPT_SCHEMA = "topeft_datacard_execution_receipt_v1"
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
TOP_LEVEL_FIELDS = {"schema", "control_root", "lock_path", "rows"}
ROW_FIELDS = {
    "row_id",
    "attempt_id",
    "era",
    "working_directory",
    "input_pkl",
    "output_root",
    "distribution",
    "physical_channels",
    "years",
    "missing_parton_path",
    "sr_registry",
    "merge_report_path",
    "snapshot_directory",
    "log_path",
    "expected_output_paths",
    "producer_argv",
}
SNAPSHOT_NAMES = {
    "selected_wcs": "selectedWCs.txt",
    "scalings": "scalings-preselect.json",
    "merge_report": "merge_report.json",
}


class RunnerError(Exception):
    def __init__(self, code: str, message: str, *, row_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.row_id = row_id


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def require_exact_fields(obj: dict[str, Any], fields: set[str], label: str) -> None:
    missing = sorted(fields - set(obj))
    extra = sorted(set(obj) - fields)
    if missing or extra:
        raise RunnerError(
            "manifest_schema_error",
            f"{label} fields differ: missing={missing}, extra={extra}",
        )


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RunnerError("manifest_schema_error", f"{label} must be a nonempty string")
    return value


def require_string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise RunnerError("manifest_schema_error", f"{label} must be a nonempty list")
    if any(not isinstance(item, str) or not item for item in value):
        raise RunnerError(
            "manifest_schema_error", f"{label} entries must be nonempty strings"
        )
    return value


def require_absolute_path(value: Any, label: str) -> Path:
    text = require_string(value, label)
    path = Path(text)
    if not path.is_absolute() or os.path.normpath(text) != text:
        raise RunnerError(
            "manifest_schema_error", f"{label} must be an absolute normalized path"
        )
    return path


def ensure_within(path: Path, root: Path, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise RunnerError(
            "manifest_schema_error", f"{label} must be within control_root"
        ) from exc


def option_values(argv: list[str], option: str) -> list[str]:
    positions = [index for index, item in enumerate(argv) if item == option]
    if len(positions) != 1:
        raise RunnerError(
            "manifest_schema_error", f"producer_argv must contain {option} exactly once"
        )
    values: list[str] = []
    for item in argv[positions[0] + 1 :]:
        if item.startswith("--"):
            break
        values.append(item)
    if not values:
        raise RunnerError(
            "manifest_schema_error", f"producer_argv option {option} needs a value"
        )
    return values


def validate_row(row: dict[str, Any], index: int, control_root: Path) -> None:
    label = f"rows[{index}]"
    require_exact_fields(row, ROW_FIELDS, label)
    row_id = require_string(row["row_id"], f"{label}.row_id")
    attempt_id = require_string(row["attempt_id"], f"{label}.attempt_id")
    if not IDENTIFIER_RE.fullmatch(row_id) or not IDENTIFIER_RE.fullmatch(attempt_id):
        raise RunnerError(
            "manifest_schema_error",
            f"{label} row_id and attempt_id must be portable identifiers",
        )
    for key in ("era", "distribution", "missing_parton_path", "sr_registry"):
        require_string(row[key], f"{label}.{key}")
    for key in (
        "working_directory",
        "input_pkl",
        "output_root",
        "merge_report_path",
        "snapshot_directory",
        "log_path",
    ):
        require_absolute_path(row[key], f"{label}.{key}")
    channels = require_string_list(row["physical_channels"], f"{label}.physical_channels")
    years = require_string_list(row["years"], f"{label}.years")
    expected = require_string_list(
        row["expected_output_paths"], f"{label}.expected_output_paths"
    )
    for expected_index, path in enumerate(expected):
        expected_path = require_absolute_path(
            path, f"{label}.expected_output_paths[{expected_index}]"
        )
        try:
            expected_path.relative_to(Path(row["output_root"]))
        except ValueError as exc:
            raise RunnerError(
                "manifest_schema_error",
                f"{label} expected outputs must be below output_root",
            ) from exc
    if len(set(expected)) != len(expected):
        raise RunnerError("manifest_schema_error", f"{label} repeats an expected output")
    if len(set(channels)) != len(channels) or len(set(years)) != len(years):
        raise RunnerError(
            "manifest_schema_error", f"{label} repeats a channel or year"
        )

    argv = require_string_list(row["producer_argv"], f"{label}.producer_argv")
    if Path(argv[0]).name != "make_cards.py":
        raise RunnerError(
            "manifest_schema_error", f"{label}.producer_argv must start with make_cards.py"
        )
    forbidden = {"--condor", "-C", "--merge-only", "--select-only"}
    selected_forbidden = sorted(forbidden.intersection(argv))
    if selected_forbidden:
        raise RunnerError(
            "manifest_schema_error",
            f"{label}.producer_argv selects non-row mode(s): {selected_forbidden}",
        )
    if row["input_pkl"] not in argv[1:]:
        raise RunnerError(
            "manifest_schema_error", f"{label}.input_pkl is absent from producer_argv"
        )
    exact_options = {
        "--out-dir": [row["output_root"]],
        "--var-lst": [row["distribution"]],
        "--ch-lst": channels,
        "--year": years,
        "--miss-parton-file": [row["missing_parton_path"]],
        "--sr-registry": [row["sr_registry"]],
        "--merge-report": [row["merge_report_path"]],
    }
    for option, expected_values in exact_options.items():
        observed_values = option_values(argv, option)
        if observed_values != expected_values:
            raise RunnerError(
                "manifest_schema_error",
                f"{label} {option} mismatch: {observed_values!r} != {expected_values!r}",
            )
    snapshot_directory = Path(row["snapshot_directory"])
    ensure_within(
        snapshot_directory,
        control_root,
        f"{label}.snapshot_directory",
    )


def load_manifest(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise RunnerError("manifest_read_error", str(exc)) from exc
    manifest_sha256 = hashlib.sha256(raw).hexdigest()
    try:
        manifest = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunnerError("manifest_schema_error", f"invalid UTF-8 JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise RunnerError("manifest_schema_error", "manifest root must be an object")
    require_exact_fields(manifest, TOP_LEVEL_FIELDS, "manifest")
    if manifest["schema"] != MANIFEST_SCHEMA:
        raise RunnerError(
            "manifest_schema_error", f"schema must be {MANIFEST_SCHEMA!r}"
        )
    control_root = require_absolute_path(manifest["control_root"], "control_root")
    lock_path = require_absolute_path(manifest["lock_path"], "lock_path")
    ensure_within(lock_path, control_root, "lock_path")
    rows = manifest["rows"]
    if not isinstance(rows, list) or not rows:
        raise RunnerError("manifest_schema_error", "rows must be a nonempty list")
    row_ids: list[str] = []
    attempt_keys: list[tuple[str, str]] = []
    row_owned_paths: list[str] = []
    snapshot_directories: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise RunnerError(
                "manifest_schema_error", f"rows[{index}] must be an object"
            )
        validate_row(row, index, control_root)
        row_ids.append(row["row_id"])
        attempt_keys.append((row["row_id"], row["attempt_id"]))
        row_owned_paths.extend(row["expected_output_paths"])
        row_owned_paths.extend([row["merge_report_path"], row["log_path"]])
        snapshot_directories.append(row["snapshot_directory"])
    if len(set(row_ids)) != len(row_ids):
        raise RunnerError("manifest_schema_error", "duplicate row_id")
    if len(set(attempt_keys)) != len(attempt_keys):
        raise RunnerError("manifest_schema_error", "duplicate row/attempt pair")
    if len(set(row_owned_paths)) != len(row_owned_paths):
        raise RunnerError(
            "manifest_schema_error", "row-owned output/report/log paths must be unique"
        )
    if len(set(snapshot_directories)) != len(snapshot_directories):
        raise RunnerError(
            "manifest_schema_error", "snapshot_directory must be unique per row attempt"
        )
    return manifest, manifest_sha256


def receipt_path(manifest: dict[str, Any], row: dict[str, Any]) -> Path:
    filename = f"{row['row_id']}__{row['attempt_id']}.json"
    return Path(manifest["control_root"]) / "receipts" / filename


def resolved_python_argv(row: dict[str, Any]) -> list[str]:
    producer_argv = list(row["producer_argv"])
    script = Path(producer_argv[0])
    if not script.is_absolute():
        script = Path(row["working_directory"]) / script
    return [str(PYTHON_ENV), str(script), *producer_argv[1:]]


def wrapper_invocation(row: dict[str, Any]) -> list[str]:
    shell_program = (
        'set -euo pipefail; working_directory=$1; shift; '
        'cd "$working_directory"; exec "$@"'
    )
    return [
        str(WRAPPER),
        "/bin/bash",
        "--noprofile",
        "--norc",
        "-c",
        shell_program,
        "datacard-matrix-row",
        row["working_directory"],
        *resolved_python_argv(row),
    ]


def nonzero_summary(paths: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "path": path,
            "exists": Path(path).is_file(),
            "nonzero": Path(path).is_file() and Path(path).stat().st_size > 0,
        }
        for path in paths
    ]


def artifact_record(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": sha256_path(path)}


def snapshot_paths(row: dict[str, Any]) -> dict[str, Path]:
    root = Path(row["snapshot_directory"])
    return {key: root / name for key, name in SNAPSHOT_NAMES.items()}


def unreceipted_paths(row: dict[str, Any]) -> list[str]:
    candidates = [
        *[Path(path) for path in row["expected_output_paths"]],
        Path(row["merge_report_path"]),
        Path(row["log_path"]),
        *snapshot_paths(row).values(),
    ]
    return [str(path) for path in candidates if path.exists()]


def validate_artifact(record: Any, expected_path: Path) -> bool:
    return (
        isinstance(record, dict)
        and record.get("path") == str(expected_path)
        and isinstance(record.get("sha256"), str)
        and expected_path.is_file()
        and expected_path.stat().st_size > 0
        and sha256_path(expected_path) == record["sha256"]
    )


def validate_receipt(
    receipt: Any,
    manifest: dict[str, Any],
    manifest_sha256: str,
    row: dict[str, Any],
) -> tuple[bool, str]:
    if not isinstance(receipt, dict):
        return False, "receipt root is not an object"
    scalar_expectations = {
        "schema": RECEIPT_SCHEMA,
        "manifest_sha256": manifest_sha256,
        "row_id": row["row_id"],
        "attempt_id": row["attempt_id"],
        "exact_resolved_argv": resolved_python_argv(row),
        "wrapper_invocation": wrapper_invocation(row),
        "command_return_code": 0,
        "expected_output_paths": row["expected_output_paths"],
    }
    for key, expected in scalar_expectations.items():
        if receipt.get(key) != expected:
            return False, f"receipt field {key} does not match"
    for key in ("start_timestamp", "end_timestamp"):
        if not isinstance(receipt.get(key), str) or not receipt[key]:
            return False, f"receipt field {key} is missing"
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, dict):
        return False, "receipt artifacts are missing"
    expected_artifacts = {
        "merge_report": Path(row["merge_report_path"]),
        "selected_wcs_snapshot": snapshot_paths(row)["selected_wcs"],
        "scalings_snapshot": snapshot_paths(row)["scalings"],
        "merge_report_snapshot": snapshot_paths(row)["merge_report"],
        "log": Path(row["log_path"]),
    }
    for key, path in expected_artifacts.items():
        if not validate_artifact(artifacts.get(key), path):
            return False, f"artifact {key} is missing, empty, moved, or hash-mismatched"
    observed = receipt.get("observed_expected_outputs")
    current = nonzero_summary(row["expected_output_paths"])
    if observed != current or not all(item["nonzero"] for item in current):
        return False, "expected-output summary is stale or incomplete"
    return True, "receipt and all referenced artifacts match"


def classify_row(
    manifest: dict[str, Any], manifest_sha256: str, row: dict[str, Any]
) -> dict[str, Any]:
    path = receipt_path(manifest, row)
    base = {
        "row_id": row["row_id"],
        "attempt_id": row["attempt_id"],
        "receipt_path": str(path),
    }
    if path.exists():
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return {**base, "status": "invalid_receipt", "reason": str(exc)}
        valid, reason = validate_receipt(receipt, manifest, manifest_sha256, row)
        return {
            **base,
            "status": "complete" if valid else "invalid_receipt",
            "reason": reason,
        }
    existing = unreceipted_paths(row)
    if existing:
        return {
            **base,
            "status": "unreceipted_output",
            "reason": "row-owned artifacts exist without a receipt",
            "existing_paths": existing,
        }
    return {**base, "status": "not_started", "reason": "no row-owned artifacts"}


def read_only_result(
    mode: str, manifest: dict[str, Any], manifest_sha256: str
) -> dict[str, Any]:
    rows = []
    for row in manifest["rows"]:
        status = classify_row(manifest, manifest_sha256, row)
        if mode == "plan_only":
            action = {
                "complete": "skip",
                "not_started": "execute",
                "invalid_receipt": "block",
                "unreceipted_output": "block",
            }[status["status"]]
            status.update(
                {
                    "action": action,
                    "output_root": row["output_root"],
                    "expected_output_paths": row["expected_output_paths"],
                    "snapshot_directory": row["snapshot_directory"],
                    "log_path": row["log_path"],
                    "exact_resolved_argv": resolved_python_argv(row),
                    "wrapper_invocation": wrapper_invocation(row),
                }
            )
        rows.append(status)
    return {
        "schema": "topeft_datacard_matrix_read_only_result_v1",
        "mode": mode,
        "manifest_sha256": manifest_sha256,
        "mutated": False,
        "rows": rows,
    }


def validate_runtime_inputs(manifest: dict[str, Any]) -> None:
    if not WRAPPER.is_file() or not os.access(WRAPPER, os.X_OK):
        raise RunnerError("runtime_preflight_error", f"wrapper unavailable: {WRAPPER}")
    if not PYTHON_ENV.is_file() or not os.access(PYTHON_ENV, os.X_OK):
        raise RunnerError(
            "runtime_preflight_error", f"pinned Python unavailable: {PYTHON_ENV}"
        )
    for row in manifest["rows"]:
        row_id = row["row_id"]
        working_directory = Path(row["working_directory"])
        input_pkl = Path(row["input_pkl"])
        script = Path(resolved_python_argv(row)[1])
        required = {
            "working_directory": working_directory,
            "input_pkl": input_pkl,
            "producer_script": script,
        }
        for label, path in required.items():
            exists = path.is_dir() if label == "working_directory" else path.is_file()
            if not exists:
                raise RunnerError(
                    "runtime_preflight_error",
                    f"{label} unavailable: {path}",
                    row_id=row_id,
                )


def make_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def atomic_copy_no_overwrite(source: Path, destination: Path) -> None:
    if not source.is_file() or source.stat().st_size == 0:
        raise RunnerError(
            "snapshot_failure", f"snapshot source is missing or empty: {source}"
        )
    make_parent(destination)
    if destination.exists():
        raise RunnerError("snapshot_failure", f"snapshot exists: {destination}")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=destination.parent, prefix=f".{destination.name}.", delete=False
        ) as output:
            temporary = Path(output.name)
            with source.open("rb") as input_handle:
                shutil.copyfileobj(input_handle, output)
            output.flush()
            os.fsync(output.fileno())
        if temporary.stat().st_size == 0:
            raise RunnerError("snapshot_failure", f"empty temporary snapshot: {source}")
        os.link(temporary, destination)
    except FileExistsError as exc:
        raise RunnerError("snapshot_failure", f"snapshot exists: {destination}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def atomic_json_no_overwrite(payload: dict[str, Any], destination: Path) -> None:
    make_parent(destination)
    if destination.exists():
        raise RunnerError("receipt_write_failure", f"receipt exists: {destination}")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            delete=False,
        ) as output:
            temporary = Path(output.name)
            json.dump(payload, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        json.loads(temporary.read_text(encoding="utf-8"))
        os.link(temporary, destination)
    except FileExistsError as exc:
        raise RunnerError(
            "receipt_write_failure", f"receipt exists: {destination}"
        ) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def execute_row(
    manifest: dict[str, Any], manifest_sha256: str, row: dict[str, Any]
) -> dict[str, Any]:
    row_id = row["row_id"]
    log_path = Path(row["log_path"])
    make_parent(log_path)
    try:
        log_handle = log_path.open("xb")
    except FileExistsError as exc:
        raise RunnerError(
            "interrupted_row_requires_external_reconciliation",
            f"log already exists without a valid receipt: {log_path}",
            row_id=row_id,
        ) from exc

    invocation = wrapper_invocation(row)
    started = utc_now()
    return_code: int | None = None
    try:
        with log_handle:
            header = {
                "attempt_id": row["attempt_id"],
                "exact_resolved_argv": resolved_python_argv(row),
                "row_id": row_id,
                "start_timestamp": started,
                "wrapper_invocation": invocation,
            }
            log_handle.write((json.dumps(header, sort_keys=True) + "\n").encode("utf-8"))
            log_handle.flush()
            process = subprocess.Popen(
                invocation,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            assert process.stdout is not None
            for block in iter(lambda: process.stdout.read(8192), b""):
                log_handle.write(block)
                log_handle.flush()
                sys.stdout.buffer.write(block)
                sys.stdout.buffer.flush()
            return_code = process.wait()
            os.fsync(log_handle.fileno())
    except BaseException:
        raise
    ended = utc_now()
    if return_code != 0:
        raise RunnerError(
            "row_command_failed",
            f"wrapper command returned {return_code}; no retry was attempted",
            row_id=row_id,
        )

    output_summary = nonzero_summary(row["expected_output_paths"])
    if not all(item["nonzero"] for item in output_summary):
        raise RunnerError(
            "expected_output_check_failed",
            "one or more expected outputs are missing or empty",
            row_id=row_id,
        )
    merge_report = Path(row["merge_report_path"])
    output_root = Path(row["output_root"])
    sources = {
        "selected_wcs": output_root / "selectedWCs.txt",
        "scalings": output_root / "scalings-preselect.json",
        "merge_report": merge_report,
    }
    for label, source in sources.items():
        if not source.is_file() or source.stat().st_size == 0:
            raise RunnerError(
                "snapshot_failure",
                f"{label} source is missing or empty: {source}",
                row_id=row_id,
            )
    destinations = snapshot_paths(row)
    for label in ("selected_wcs", "scalings", "merge_report"):
        atomic_copy_no_overwrite(sources[label], destinations[label])

    receipt = {
        "schema": RECEIPT_SCHEMA,
        "manifest_sha256": manifest_sha256,
        "row_id": row_id,
        "attempt_id": row["attempt_id"],
        "exact_resolved_argv": resolved_python_argv(row),
        "wrapper_invocation": invocation,
        "start_timestamp": started,
        "end_timestamp": ended,
        "command_return_code": return_code,
        "merge_report_path": str(merge_report),
        "expected_output_paths": row["expected_output_paths"],
        "observed_expected_outputs": output_summary,
        "artifacts": {
            "merge_report": artifact_record(merge_report),
            "selected_wcs_snapshot": artifact_record(destinations["selected_wcs"]),
            "scalings_snapshot": artifact_record(destinations["scalings"]),
            "merge_report_snapshot": artifact_record(destinations["merge_report"]),
            "log": artifact_record(log_path),
        },
    }
    final_receipt = receipt_path(manifest, row)
    atomic_json_no_overwrite(receipt, final_receipt)
    return {
        "row_id": row_id,
        "attempt_id": row["attempt_id"],
        "action": "executed",
        "receipt_path": str(final_receipt),
    }


def execute_manifest(
    manifest: dict[str, Any], manifest_sha256: str
) -> dict[str, Any]:
    control_root = Path(manifest["control_root"])
    lock_path = Path(manifest["lock_path"])
    control_root.mkdir(parents=True, exist_ok=True)
    make_parent(lock_path)
    with lock_path.open("a+b") as lock_handle:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RunnerError(
                "execution_lock_held",
                f"another runner owns the advisory lock: {lock_path}",
            ) from exc

        statuses = [
            classify_row(manifest, manifest_sha256, row) for row in manifest["rows"]
        ]
        for row, status in zip(manifest["rows"], statuses):
            if status["status"] == "invalid_receipt":
                raise RunnerError(
                    "stale_or_invalid_execution_receipt",
                    status["reason"],
                    row_id=status["row_id"],
                )
            if status["status"] == "unreceipted_output":
                interruption_paths = {
                    row["merge_report_path"],
                    row["log_path"],
                    *[str(path) for path in snapshot_paths(row).values()],
                }
                status_code = (
                    "interrupted_row_requires_external_reconciliation"
                    if interruption_paths.intersection(status["existing_paths"])
                    else "preexisting_unreceipted_output"
                )
                raise RunnerError(
                    status_code,
                    f"{status['reason']}: {status['existing_paths']}",
                    row_id=status["row_id"],
                )
        validate_runtime_inputs(manifest)

        results = []
        for row, status in zip(manifest["rows"], statuses):
            if status["status"] == "complete":
                results.append(
                    {
                        "row_id": row["row_id"],
                        "attempt_id": row["attempt_id"],
                        "action": "skipped_valid_receipt",
                        "receipt_path": status["receipt_path"],
                    }
                )
                continue
            results.append(execute_row(manifest, manifest_sha256, row))
        return {
            "schema": "topeft_datacard_matrix_execution_result_v1",
            "manifest_sha256": manifest_sha256,
            "owner": {"pid": os.getpid(), "hostname": socket.gethostname()},
            "rows": results,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a prequalified datacard matrix with fail-closed receipts."
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--plan-only", action="store_true")
    modes.add_argument("--status", action="store_true")
    parser.add_argument("manifest", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest, manifest_sha256 = load_manifest(args.manifest)
        if args.plan_only or args.status:
            mode = "plan_only" if args.plan_only else "status"
            result = read_only_result(mode, manifest, manifest_sha256)
        else:
            result = execute_manifest(manifest, manifest_sha256)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except RunnerError as exc:
        failure = {
            "schema": "topeft_datacard_matrix_error_v1",
            "status": exc.code,
            "message": str(exc),
        }
        if exc.row_id is not None:
            failure["row_id"] = exc.row_id
        print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
