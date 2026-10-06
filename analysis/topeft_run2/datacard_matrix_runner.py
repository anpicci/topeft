#!/usr/bin/env python3
"""Run an opaque, prequalified datacard manifest without a shell intermediary."""
from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
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

UNIT_SCHEMA = "topeft_datacard_execution_unit_v1"
MANIFEST_SCHEMA = "topeft_datacard_matrix_v3"
RECEIPT_SCHEMA = "topeft_datacard_execution_receipt_v2"
OWNER_SCHEMA = "topeft_datacard_runner_owner_v1"
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TOP_FIELDS = {"schema", "control_root", "lock_path", "runtime_contract", "rows"}
RUNTIME_FIELDS = {"contract_id", "python_executable", "make_cards_path", "fingerprints"}
FINGERPRINT_FIELDS = {"path", "sha256"}
ROW_FIELDS = {"row_id", "logical_row_id", "attempt_id", "era", "working_directory", "input_pkl", "output_root", "distribution", "physical_channels", "years", "missing_parton_path", "merge_report_path", "snapshot_directory", "log_path", "expected_output_paths", "producer_args"}
SNAPSHOTS = {"selected_wcs": "selectedWCs.txt", "scalings": "scalings-preselect.json", "merge_report": "merge_report.json"}
INTENT_SCHEMA = "topeft_datacard_attempt_intent_v1"
INTENT_MARKER = ".datacard_attempt_intent.json"
ATTEMPT_RE = re.compile(r"^attempt_([0-9]{6})$")


class RunnerError(Exception):
    def __init__(self, code: str, message: str, *, row_id: str | None = None):
        super().__init__(message)
        self.code, self.row_id = code, row_id


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def exact_fields(value: Any, allowed: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RunnerError("manifest_schema_error", f"{label} must be an object")
    missing, extra = sorted(allowed - set(value)), sorted(set(value) - allowed)
    if missing or extra:
        raise RunnerError("manifest_schema_error", f"{label} fields differ: missing={missing}, extra={extra}")
    return value


def text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RunnerError("manifest_schema_error", f"{label} must be a nonempty string")
    return value


def strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        raise RunnerError("manifest_schema_error", f"{label} must be a nonempty string list")
    return value


def absolute(value: Any, label: str) -> Path:
    path = Path(text(value, label))
    if not path.is_absolute() or os.path.normpath(str(path)) != str(path):
        raise RunnerError("manifest_schema_error", f"{label} must be an absolute normalized path")
    return path


def inside(path: Path, root: Path, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise RunnerError("manifest_schema_error", f"{label} must be within control_root") from exc


def option_values(args: list[str], option: str) -> list[str]:
    positions = [index for index, value in enumerate(args) if value == option]
    if len(positions) != 1:
        raise RunnerError("manifest_schema_error", f"producer_args must contain {option} exactly once")
    values: list[str] = []
    for value in args[positions[0] + 1:]:
        if value.startswith("--"):
            break
        values.append(value)
    if not values:
        raise RunnerError("manifest_schema_error", f"producer_args option {option} needs a value")
    return values


def runtime_digest(contract: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_runtime(contract: Any, verify_files: bool = True) -> dict[str, Any]:
    contract = exact_fields(contract, RUNTIME_FIELDS, "runtime_contract")
    text(contract["contract_id"], "runtime_contract.contract_id")
    python = absolute(contract["python_executable"], "runtime_contract.python_executable")
    make_cards = absolute(contract["make_cards_path"], "runtime_contract.make_cards_path")
    fingerprints = contract["fingerprints"]
    if not isinstance(fingerprints, list) or not fingerprints:
        raise RunnerError("manifest_schema_error", "runtime_contract.fingerprints must be nonempty")
    seen: set[str] = set()
    for index, item in enumerate(fingerprints):
        item = exact_fields(item, FINGERPRINT_FIELDS, f"runtime_contract.fingerprints[{index}]")
        path = absolute(item["path"], f"runtime_contract.fingerprints[{index}].path")
        digest = text(item["sha256"], f"runtime_contract.fingerprints[{index}].sha256")
        if not SHA256_RE.fullmatch(digest) or str(path) in seen:
            raise RunnerError("manifest_schema_error", "runtime fingerprints require unique absolute paths and lowercase SHA256")
        seen.add(str(path))
    if verify_files:
        if not python.is_file() or not os.access(python, os.X_OK):
            raise RunnerError("runtime_contract_mismatch", f"python executable unavailable: {python}")
        if not make_cards.is_file():
            raise RunnerError("runtime_contract_mismatch", f"make_cards path unavailable: {make_cards}")
        for item in fingerprints:
            path = Path(item["path"])
            if not path.is_file() or hash_file(path) != item["sha256"]:
                raise RunnerError("runtime_contract_mismatch", f"runtime fingerprint mismatch: {path}")
    return contract


def validate_row(row: Any, index: int, control_root: Path) -> dict[str, Any]:
    row = exact_fields(row, ROW_FIELDS, f"rows[{index}]")
    row_id, attempt = text(row["row_id"], "row_id"), text(row["attempt_id"], "attempt_id")
    logical_row_id = text(row["logical_row_id"], "logical_row_id")
    if not all(IDENTIFIER_RE.fullmatch(value) for value in (row_id, logical_row_id, attempt)):
        raise RunnerError("manifest_schema_error", "row_id, logical_row_id and attempt_id must be portable identifiers")
    for key in ("era", "distribution"):
        text(row[key], key)
    for key in ("working_directory", "input_pkl", "output_root", "missing_parton_path", "merge_report_path", "snapshot_directory", "log_path"):
        absolute(row[key], key)
    channels, years = strings(row["physical_channels"], "physical_channels"), strings(row["years"], "years")
    outputs, args = strings(row["expected_output_paths"], "expected_output_paths"), strings(row["producer_args"], "producer_args")
    if len(set(channels)) != len(channels) or len(set(years)) != len(years) or len(set(outputs)) != len(outputs):
        raise RunnerError("manifest_schema_error", "row repeats a channel, year, or output path")
    for output in outputs:
        try:
            absolute(output, "expected_output_path").relative_to(Path(row["output_root"]))
        except ValueError as exc:
            raise RunnerError("manifest_schema_error", "expected outputs must be below output_root") from exc
    if {"--condor", "-C", "--merge-only", "--select-only", "--cache-merged-pkl"}.intersection(args):
        raise RunnerError("manifest_schema_error", "producer_args selects a non-row mode")
    if "--sr-registry" in args:
        raise RunnerError("manifest_schema_error", "v3 producer_args must not contain --sr-registry")
    required = {"--out-dir": [row["output_root"]], "--var-lst": [row["distribution"]], "--ch-lst": channels, "--year": years, "--miss-parton-file": [row["missing_parton_path"]], "--merge-report": [row["merge_report_path"]]}
    for option, expected in required.items():
        if option_values(args, option) != expected:
            raise RunnerError("manifest_schema_error", f"{option} differs from structured row field")
    inside(Path(row["snapshot_directory"]), control_root, "snapshot_directory")
    return row


def load_manifest(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
        manifest = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunnerError("manifest_read_error", str(exc)) from exc
    manifest = exact_fields(manifest, TOP_FIELDS, "manifest")
    if manifest["schema"] == "topeft_datacard_matrix_v2":
        raise RunnerError("manifest_schema_error", "Historical datacard matrix schema `topeft_datacard_matrix_v2` is not accepted by the current datacard workflow. Generate a new `topeft_datacard_matrix_v3` manifest with make_datacard_matrix_manifest.py.")
    if manifest["schema"] != MANIFEST_SCHEMA:
        raise RunnerError("manifest_schema_error", f"schema must be {MANIFEST_SCHEMA}")
    root, lock = absolute(manifest["control_root"], "control_root"), absolute(manifest["lock_path"], "lock_path")
    inside(lock, root, "lock_path")
    validate_runtime(manifest["runtime_contract"], verify_files=False)
    if not isinstance(manifest["rows"], list) or not manifest["rows"]:
        raise RunnerError("manifest_schema_error", "rows must be nonempty")
    rows = [validate_row(row, index, root) for index, row in enumerate(manifest["rows"])]
    row_ids = [row["row_id"] for row in rows]
    attempts = [(row["row_id"], row["attempt_id"]) for row in rows]
    owned = [value for row in rows for value in [*row["expected_output_paths"], row["merge_report_path"], row["log_path"], row["snapshot_directory"]]]
    if len(set(row_ids)) != len(row_ids):
        raise RunnerError("manifest_schema_error", "duplicate row_id")
    if len(set(attempts)) != len(attempts):
        raise RunnerError("manifest_schema_error", "duplicate row/attempt identity")
    if len(set(owned)) != len(owned):
        raise RunnerError("manifest_schema_error", "row-owned paths must be unique")
    return manifest, hashlib.sha256(raw).hexdigest()


def validate_unit_layout(manifest: dict[str, Any]) -> None:
    roots = [Path(row["output_root"]).resolve() for row in manifest["rows"]]
    if any(a == b or a in b.parents or b in a.parents for i, a in enumerate(roots) for b in roots[i + 1:]):
        raise RunnerError("manifest_schema_error", "execution units require disjoint output roots")


def derive_units(path: Path) -> list[dict[str, Any]]:
    """Derive dispatch selectors; the original manifest remains workload authority."""
    manifest, manifest_hash = load_manifest(path)
    validate_unit_layout(manifest)
    return [{"schema": UNIT_SCHEMA, "parent_manifest": str(path.resolve()),
             "parent_integrity": manifest_hash, "row_id": row["row_id"]}
            for row in manifest["rows"]]


def resolve_unit(unit: Any) -> tuple[dict[str, Any], str, dict[str, Any]]:
    unit = exact_fields(unit, {"schema", "parent_manifest", "parent_integrity", "row_id"}, "execution_unit")
    if unit["schema"] != UNIT_SCHEMA:
        raise RunnerError("unit_schema_error", "unsupported execution-unit schema")
    manifest, manifest_hash = load_manifest(absolute(unit["parent_manifest"], "parent_manifest"))
    if unit["parent_integrity"] != manifest_hash:
        raise RunnerError("stale_dispatch_input", "parent manifest bytes changed after unit derivation")
    return manifest, manifest_hash, select_row(manifest, unit["row_id"])


def select_row(manifest: dict[str, Any], row_id: str) -> dict[str, Any]:
    for row in manifest["rows"]:
        if row["row_id"] == row_id:
            return row
    raise RunnerError("unit_schema_error", f"unknown execution unit: {row_id}")


def unit_lock_path(row: dict[str, Any]) -> Path:
    output = Path(row["output_root"])
    if output.is_symlink():
        raise RunnerError("canonical_collision_or_ambiguous_state", "output root is a symlink")
    output = output.resolve()
    return output.parent / f".{output.name}.datacard.lock"


def unit_owner_path(row: dict[str, Any]) -> Path:
    return unit_lock_path(row).with_suffix(".owner.json")


def unit_owner(row: dict[str, Any]) -> dict[str, Any] | None:
    try:
        value = json.loads(unit_owner_path(row).read_text())
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def reject_nested_domain(output: Path) -> None:
    for ancestor in output.parents:
        if ancestor == ancestor.parent:
            continue
        marker = ancestor / INTENT_MARKER
        lock = ancestor.parent / f".{ancestor.name}.datacard.lock"
        if lock.exists() or lock.is_symlink() or marker.exists():
            raise RunnerError("canonical_collision_or_ambiguous_state", f"output is nested in an existing ownership domain: {ancestor}")


def existing_parent(path: Path) -> Path:
    parent = path.parent
    while not parent.is_dir():
        parent = parent.parent
    return parent


@contextmanager
def unit_lease(manifest: dict[str, Any], row: dict[str, Any]):
    """Lease one output domain; initialize paths under a short filesystem mutex.

    The setup mutex prevents a rejected nested unit from creating the active
    owner's canonical directory. It is released before execution. Persistent
    lock inodes are never removed. Producer inheritance keeps ownership alive
    if the manager dies. The shared legacy lock excludes older global runners.
    """
    legacy = Path(manifest["lock_path"])
    lock = unit_lock_path(row)
    output = Path(row["output_root"]).resolve()
    with ExitStack() as handles:
        while True:
            reject_nested_domain(output)
            parent = existing_parent(output)
            setup_path = parent / ".datacard_lease_setup.lock"
            if setup_path.is_symlink():
                raise RunnerError("canonical_collision_or_ambiguous_state", "setup lock is a symlink")
            with setup_path.open("a+b") as setup:
                fcntl.flock(setup.fileno(), fcntl.LOCK_EX)
                if existing_parent(output) != parent:
                    continue  # Parent creation won a race; use its setup mutex.
                reject_nested_domain(output)
                legacy.parent.mkdir(parents=True, exist_ok=True)
                lock.parent.mkdir(parents=True, exist_ok=True)
                if lock.is_symlink() or legacy.is_symlink():
                    raise RunnerError("canonical_collision_or_ambiguous_state", "lock path is a symlink", row_id=row["row_id"])
                legacy_handle = handles.enter_context(legacy.open("a+b"))
                unit_handle = handles.enter_context(lock.open("a+b"))
                try:
                    fcntl.flock(legacy_handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                    fcntl.flock(unit_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise RunnerError("execution_lock_held", f"execution ownership unavailable: {lock}", row_id=row["row_id"]) from exc
                break
        yield (legacy_handle.fileno(), unit_handle.fileno())


def receipt_path(manifest: dict[str, Any], row: dict[str, Any]) -> Path:
    return Path(manifest["control_root"]) / "receipts" / f"{row['row_id']}__{row['attempt_id']}.json"


def owner_path(manifest: dict[str, Any]) -> Path:
    return Path(manifest["control_root"]) / "runner_owner.json"


def snapshots(row: dict[str, Any]) -> dict[str, Path]:
    return {key: Path(row["snapshot_directory"]) / name for key, name in SNAPSHOTS.items()}


def resolved_argv(manifest: dict[str, Any], row: dict[str, Any]) -> list[str]:
    contract = manifest["runtime_contract"]
    return [contract["python_executable"], contract["make_cards_path"], row["input_pkl"], *row["producer_args"]]


def path_availability(path: Path, *, executable: bool = False) -> dict[str, Any]:
    regular_file = path.is_file()
    readable = regular_file and os.access(path, os.R_OK)
    executable_ok = not executable or (regular_file and os.access(path, os.X_OK))
    return {
        "path": str(path),
        "exists": path.exists(),
        "regular_file": regular_file,
        "readable": readable,
        "executable": executable_ok if executable else None,
        "available": regular_file and readable and executable_ok,
    }


def execution_input_availability(manifest: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    runtime = manifest["runtime_contract"]
    checks = {
        "working_directory": {
            "path": row["working_directory"],
            "exists": Path(row["working_directory"]).exists(),
            "directory": Path(row["working_directory"]).is_dir(),
            "available": Path(row["working_directory"]).is_dir(),
        },
        "input_pkl": path_availability(Path(row["input_pkl"])),
        "missing_parton_path": path_availability(Path(row["missing_parton_path"])),
        "python_executable": path_availability(Path(runtime["python_executable"]), executable=True),
        "make_cards_path": path_availability(Path(runtime["make_cards_path"])),
    }
    fingerprint_checks = []
    for item in runtime["fingerprints"]:
        path = Path(item["path"])
        available = path.is_file() and os.access(path, os.R_OK)
        observed_sha256 = hash_file(path) if available else None
        fingerprint_checks.append({
            "path": str(path),
            "available": available,
            "expected_sha256": item["sha256"],
            "observed_sha256": observed_sha256,
            "matches": available and observed_sha256 == item["sha256"],
        })
    checks["runtime_fingerprints"] = fingerprint_checks
    ready = all(check["available"] for key, check in checks.items() if key != "runtime_fingerprints") and all(item["matches"] for item in fingerprint_checks)
    return {"required": True, "checked": True, "ready": ready, "checks": checks}


def validate_row_inputs(row: dict[str, Any]) -> None:
    working_directory = Path(row["working_directory"])
    if not working_directory.is_dir():
        raise RunnerError("runtime_preflight_error", f"working directory unavailable: {working_directory}", row_id=row["row_id"])
    input_pkl = Path(row["input_pkl"])
    if not input_pkl.is_file() or not os.access(input_pkl, os.R_OK):
        raise RunnerError("runtime_preflight_error", f"input_pkl unavailable: {input_pkl}", row_id=row["row_id"])
    missing_parton = Path(row["missing_parton_path"])
    if not missing_parton.is_file() or not os.access(missing_parton, os.R_OK):
        raise RunnerError("runtime_preflight_error", f"missing_parton_path unavailable: {missing_parton}", row_id=row["row_id"])


def record(path: Path) -> dict[str, Any]:
    return {"path": str(path), "size_bytes": path.stat().st_size, "sha256": hash_file(path)}


def valid_record(value: Any, path: Path) -> bool:
    return isinstance(value, dict) and set(value) == {"path", "size_bytes", "sha256"} and value.get("path") == str(path) and isinstance(value.get("size_bytes"), int) and isinstance(value.get("sha256"), str) and path.is_file() and path.stat().st_size == value["size_bytes"] and hash_file(path) == value["sha256"]


def validate_receipt(receipt: Any, manifest: dict[str, Any], manifest_hash: str, row: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(receipt, dict):
        return False, "receipt root is not an object"
    runtime = manifest["runtime_contract"]
    expected = {"schema": RECEIPT_SCHEMA, "manifest_sha256": manifest_hash, "row_id": row["row_id"], "attempt_id": row["attempt_id"], "resolved_argv": resolved_argv(manifest, row), "command_return_code": 0, "runtime_contract_id": runtime["contract_id"], "python_executable": runtime["python_executable"], "make_cards_path": runtime["make_cards_path"], "runtime_fingerprints": runtime["fingerprints"], "runtime_contract_digest": runtime_digest(runtime)}
    if any(receipt.get(key) != value for key, value in expected.items()):
        return False, "receipt contract does not match"
    if "physical_attempt_id" in receipt or "execution_argv" in receipt:
        physical = receipt.get("physical_attempt_id")
        if not isinstance(physical, str) or not ATTEMPT_RE.fullmatch(physical):
            return False, "physical attempt identity is invalid"
        if receipt.get("execution_argv") != staged_argv(manifest, row, attempt_root(manifest_hash, row) / physical):
            return False, "execution argv does not match physical attempt"
    if not all(isinstance(receipt.get(key), str) and receipt[key] for key in ("start_timestamp", "end_timestamp")):
        return False, "receipt timestamps missing"
    outputs = receipt.get("primary_outputs")
    if not isinstance(outputs, list) or len(outputs) != len(row["expected_output_paths"]) or any(not valid_record(item, Path(path)) for item, path in zip(outputs, row["expected_output_paths"])):
        return False, "primary output is missing, size-mismatched, or hash-mismatched"
    artifacts = {"merge_report": Path(row["merge_report_path"]), "selected_wcs_snapshot": snapshots(row)["selected_wcs"], "scalings_snapshot": snapshots(row)["scalings"], "merge_report_snapshot": snapshots(row)["merge_report"], "log": Path(row["log_path"])}
    if not isinstance(receipt.get("artifacts"), dict) or set(receipt["artifacts"]) != set(artifacts) or any(not valid_record(receipt["artifacts"][key], path) for key, path in artifacts.items()):
        return False, "control artifact is missing, size-mismatched, or hash-mismatched"
    return True, "receipt and byte-bound artifacts match"


def read_owner(manifest: dict[str, Any]) -> dict[str, Any] | None:
    try:
        owner = json.loads(owner_path(manifest).read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return owner if isinstance(owner, dict) else None


def probe_lock(path: Path) -> tuple[bool | None, str | None]:
    if not path.exists():
        return False, None
    try:
        with path.open("rb") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                return True, None
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return False, None
    except FileNotFoundError:
        return False, None
    except OSError as exc:
        return None, f"{type(exc).__name__}: {exc}"


def attempt_root(manifest_hash: str, row: dict[str, Any]) -> Path:
    output = Path(row["output_root"])
    return output.parent / f".{output.name}.{manifest_hash}.{row['attempt_id']}.attempts"


def attempts(manifest_hash: str, row: dict[str, Any]) -> list[Path]:
    root = attempt_root(manifest_hash, row)
    if not root.exists():
        return []
    if not root.is_dir() or root.is_symlink():
        raise RunnerError("canonical_collision_or_ambiguous_state", f"attempt namespace is not a directory: {root}", row_id=row["row_id"])
    entries = sorted(root.iterdir())
    if any(not ATTEMPT_RE.fullmatch(path.name) or not path.is_dir() or path.is_symlink() for path in entries):
        raise RunnerError("canonical_collision_or_ambiguous_state", f"unexpected attempt namespace entry: {root}", row_id=row["row_id"])
    return entries


def staged_paths(row: dict[str, Any], attempt: Path) -> tuple[list[Path], dict[str, Path]]:
    root = Path(row["output_root"])
    outputs = [attempt / "cards" / Path(path).relative_to(root) for path in row["expected_output_paths"]]
    artifacts = {
        "merge_report": attempt / "merge_report.json",
        "selected_wcs_snapshot": attempt / "snapshots" / SNAPSHOTS["selected_wcs"],
        "scalings_snapshot": attempt / "snapshots" / SNAPSHOTS["scalings"],
        "merge_report_snapshot": attempt / "snapshots" / SNAPSHOTS["merge_report"],
        "log": attempt / "producer.log",
    }
    return outputs, artifacts


def canonical_artifacts(row: dict[str, Any]) -> dict[str, Path]:
    return {"merge_report": Path(row["merge_report_path"]), "selected_wcs_snapshot": snapshots(row)["selected_wcs"], "scalings_snapshot": snapshots(row)["scalings"], "merge_report_snapshot": snapshots(row)["merge_report"], "log": Path(row["log_path"])}


def staged_argv(manifest: dict[str, Any], row: dict[str, Any], attempt: Path) -> list[str]:
    # The first three argv entries identify the interpreter, producer and input.
    argv = resolved_argv(manifest, row)
    output_paths, _ = staged_paths(row, attempt)
    destinations = {row["output_root"]: str(attempt / "cards"), row["merge_report_path"]: str(attempt / "merge_report.json")}
    destinations.update(zip(row["expected_output_paths"], map(str, output_paths)))
    return [*argv[:3], *(destinations.get(value, value) for value in argv[3:])]


def valid_intent(manifest: dict[str, Any], manifest_hash: str, row: dict[str, Any], attempt: Path) -> tuple[bool, str, dict[str, Any] | None]:
    path = attempt / "intent.json"
    try:
        intent = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return False, str(exc), None
    if not isinstance(intent, dict):
        return False, "intent is not an object", None
    expected = {"schema": INTENT_SCHEMA, "manifest_sha256": manifest_hash, "row_id": row["row_id"], "attempt_id": row["attempt_id"], "physical_attempt_id": attempt.name, "resolved_argv": resolved_argv(manifest, row), "execution_argv": staged_argv(manifest, row, attempt), "runtime_contract_digest": runtime_digest(manifest["runtime_contract"]), "command_return_code": 0}
    if any(intent.get(key) != value for key, value in expected.items()):
        return False, "intent identity or execution contract differs", None
    if not all(isinstance(intent.get(key), str) and intent[key] for key in ("start_timestamp", "end_timestamp")):
        return False, "intent timestamps missing", None
    outputs, artifacts = staged_paths(row, attempt)
    if not isinstance(intent.get("primary_outputs"), list) or len(intent["primary_outputs"]) != len(outputs) or any(path.is_symlink() or not valid_record(item, path) or path.stat().st_size == 0 for item, path in zip(intent["primary_outputs"], outputs)):
        return False, "staged primary outputs differ from intent", None
    if not isinstance(intent.get("artifacts"), dict) or set(intent["artifacts"]) != set(artifacts) or any(path.is_symlink() or not valid_record(intent["artifacts"][key], path) or path.stat().st_size == 0 for key, path in artifacts.items()):
        return False, "staged control artifacts differ from intent", None
    return True, "complete validated attempt", intent


def candidate_attempt(manifest: dict[str, Any], manifest_hash: str, row: dict[str, Any], entries: list[Path]) -> tuple[Path, dict[str, Any]] | None:
    candidates = []
    for attempt in entries:
        if (attempt / "intent.json").exists():
            valid, reason, intent = valid_intent(manifest, manifest_hash, row, attempt)
            if not valid:
                raise RunnerError("canonical_collision_or_ambiguous_state", reason, row_id=row["row_id"])
            candidates.append((attempt, intent))
    if len(candidates) > 1:
        raise RunnerError("canonical_collision_or_ambiguous_state", "multiple complete attempts for one public row", row_id=row["row_id"])
    return candidates[0] if candidates else None


def publication_state(row: dict[str, Any], attempt: Path, intent: dict[str, Any]) -> tuple[str, str]:
    root = Path(row["output_root"])
    marker = root / INTENT_MARKER
    source_outputs, source_artifacts = staged_paths(row, attempt)
    canonical_outputs = [Path(path) for path in row["expected_output_paths"]]
    artifacts = canonical_artifacts(row)
    if root.is_symlink():
        return "canonical_collision_or_ambiguous_state", "canonical root is a symlink"
    if not root.exists():
        if any(path.exists() for path in artifacts.values()):
            return "canonical_collision_or_ambiguous_state", "control artifact exists before canonical publication"
        return "complete_validated_staging_not_promoted", "validated attempt awaits publication"
    if not root.is_dir() or root.is_symlink() or not marker.is_file() or not os.path.samefile(marker, attempt / "intent.json"):
        return "canonical_collision_or_ambiguous_state", "canonical directory has no matching attempt marker"
    allowed = {marker, root / "selectedWCs.txt", root / "scalings-preselect.json", *canonical_outputs}
    if any(path.is_symlink() or (path.is_file() and path not in allowed) or (path.is_dir() and not any(path in expected.parents for expected in allowed)) for path in root.rglob("*")):
        return "canonical_collision_or_ambiguous_state", "unexpected canonical entry"
    pairs = list(zip(canonical_outputs, intent["primary_outputs"]))
    pairs += [(root / "selectedWCs.txt", record(source_artifacts["selected_wcs_snapshot"])), (root / "scalings-preselect.json", record(source_artifacts["scalings_snapshot"]))]
    pairs += [(artifacts[key], intent["artifacts"][key]) for key in artifacts]
    missing = False
    for destination, source_record in pairs:
        if not destination.exists():
            missing = True
        elif destination.is_symlink() or not valid_record({**source_record, "path": str(destination)}, destination):
            return "canonical_collision_or_ambiguous_state", f"published bytes differ: {destination}"
    return ("promoted_incomplete", "matching publication marker; missing canonical files") if missing else ("promoted_complete_without_receipt", "canonical bytes match validated attempt")


def classify(manifest: dict[str, Any], manifest_hash: str, row: dict[str, Any], held: bool | None = None, owner: dict[str, Any] | None = None) -> dict[str, Any]:
    receipt = receipt_path(manifest, row)
    base = {"row_id": row["row_id"], "attempt_id": row["attempt_id"], "receipt_path": str(receipt)}
    if receipt.exists():
        try:
            valid, reason = validate_receipt(json.loads(receipt.read_text()), manifest, manifest_hash, row)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            valid, reason = False, str(exc)
        return {**base, "status": "complete" if valid else "invalid_receipt", "reason": reason}
    if held is None:
        legacy_held = probe_lock(Path(manifest["lock_path"]))[0]
        unit_held = probe_lock(unit_lock_path(row))[0]
        held = True if True in (legacy_held, unit_held) else None if None in (legacy_held, unit_held) else False
    owner = (unit_owner(row) or read_owner(manifest)) if owner is None else owner
    active = held is True and isinstance(owner, dict) and owner.get("schema_version") == OWNER_SCHEMA and owner.get("manifest_sha256") == manifest_hash and owner.get("current_row_id") == row["row_id"] and owner.get("current_attempt_id") == row["attempt_id"]
    stale_owner = held is False and isinstance(owner, dict) and owner.get("schema_version") == OWNER_SCHEMA and owner.get("manifest_sha256") == manifest_hash and owner.get("current_row_id") == row["row_id"] and owner.get("current_attempt_id") == row["attempt_id"]
    if active:
        return {**base, "status": "active", "reason": "lock and owner identify current row", "active_log_path": owner.get("current_log_path"), "stale_owner_free_lock": False}
    if held is not False:
        return {**base, "status": "held_lock_active_or_unknown", "reason": "output ownership held or unknown", "stale_owner_free_lock": False}
    try:
        entries = attempts(manifest_hash, row)
        candidate = candidate_attempt(manifest, manifest_hash, row, entries)
        if candidate:
            attempt, intent = candidate
            status, reason = publication_state(row, attempt, intent)
            return {**base, "status": status, "reason": reason, "physical_attempt_id": attempt.name, "stale_owner_free_lock": stale_owner}
    except (RunnerError, OSError, ValueError) as exc:
        return {**base, "status": "canonical_collision_or_ambiguous_state", "reason": str(exc), "stale_owner_free_lock": stale_owner}
    canonical = Path(row["output_root"])
    legacy = [str(path) for path in [Path(row["merge_report_path"]), Path(row["log_path"]), *snapshots(row).values()] if path.exists()]
    if canonical.exists() or legacy:
        return {**base, "status": "canonical_collision_or_ambiguous_state", "reason": "canonical or public control bytes have no validated attempt", "existing_paths": ([str(canonical)] if canonical.exists() else []) + legacy, "stale_owner_free_lock": stale_owner}
    if held is None and entries:
        return {**base, "status": "held_lock_active_or_unknown", "reason": "lock state unknown with attempt evidence", "stale_owner_free_lock": False}
    if held is True and entries:
        return {**base, "status": "held_lock_active_or_unknown", "reason": "lock held without matching row owner", "stale_owner_free_lock": False}
    if entries:
        return {**base, "status": "partial_staging_attempt", "reason": "incomplete attempt preserved; explicit rerun may start a fresh physical attempt", "physical_attempt_id": entries[-1].name, "stale_owner_free_lock": stale_owner}
    if stale_owner:
        return {**base, "status": "stale_owner_free_lock", "reason": "owner metadata is stale; OS lock is free", "stale_owner_free_lock": True}
    return {**base, "status": "not_started", "reason": "no row-owned artifacts", "stale_owner_free_lock": False}


def read_only(mode: str, manifest: dict[str, Any], manifest_hash: str, row_id: str | None = None) -> dict[str, Any]:
    held, lock_probe_error = probe_lock(Path(manifest["lock_path"]))
    owner = read_owner(manifest)
    selected = [select_row(manifest, row_id)] if row_id else manifest["rows"]
    rows = []
    for row in selected:
        unit_held, unit_error = probe_lock(unit_lock_path(row))
        row_held = True if True in (held, unit_held) else None if None in (held, unit_held) else False
        row_owner = unit_owner(row) or owner
        state = classify(manifest, manifest_hash, row, row_held, row_owner)
        state.update(lock_path=str(unit_lock_path(row)), lock_held=row_held,
                     lock_probe_error=unit_error or lock_probe_error, owner_metadata=row_owner)
        rows.append(state)
    if mode == "plan_only":
        for row, status in zip(selected, rows):
            status["action"] = "skip" if status["status"] == "complete" else "execute" if status["status"] in {"not_started", "stale_owner_free_lock", "partial_staging_attempt"} else "reconcile" if status["status"] in {"complete_validated_staging_not_promoted", "promoted_incomplete", "promoted_complete_without_receipt"} else "block"
            status["resolved_argv"] = resolved_argv(manifest, row)
            if status["action"] == "execute":
                availability = execution_input_availability(manifest, row)
                status["execution_input_availability"] = availability
                if not availability["ready"]:
                    status["action"] = "block"
                    status["reason"] = "execution inputs are not launch-ready"
            else:
                status["execution_input_availability"] = {
                    "required": False,
                    "checked": False,
                    "ready": status["action"] in {"skip", "reconcile"},
                    "reason": "valid receipt permits skip without historical execution inputs" if status["action"] == "skip" else "validated attempt permits reconciliation without historical execution inputs" if status["action"] == "reconcile" else "row state blocks before execution-input checks",
                }
    result = {"schema": "topeft_datacard_matrix_read_only_result_v2", "mode": mode, "manifest_sha256": manifest_hash, "runtime_contract_digest": runtime_digest(manifest["runtime_contract"]), "lock_held": True if any(row["lock_held"] is True for row in rows) else None if any(row["lock_held"] is None for row in rows) else False, "lock_probe_error": lock_probe_error, "owner_metadata": owner, "mutated": False, "rows": rows}
    if mode == "plan_only":
        result["launch_ready"] = all(row["action"] in {"skip", "execute", "reconcile"} for row in rows)
    return result


def atomic_json(payload: dict[str, Any], destination: Path, overwrite: bool) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite and destination.exists():
        raise RunnerError("receipt_write_failure", f"destination exists: {destination}")
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent, prefix=f".{destination.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush(); os.fsync(handle.fileno())
    try:
        json.loads(temporary.read_text())
        if overwrite:
            os.replace(temporary, destination)
        else:
            os.link(temporary, destination)
    except FileExistsError as exc:
        raise RunnerError("receipt_write_failure", f"destination exists: {destination}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def copy_once(source: Path, destination: Path) -> None:
    if not source.is_file() or source.stat().st_size == 0:
        raise RunnerError("snapshot_failure", f"control source missing or empty: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise RunnerError("snapshot_failure", f"snapshot exists: {destination}")
    with tempfile.NamedTemporaryFile(mode="wb", dir=destination.parent, prefix=f".{destination.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        with source.open("rb") as input_handle:
            shutil.copyfileobj(input_handle, handle)
        handle.flush(); os.fsync(handle.fileno())
    try:
        os.link(temporary, destination)
    except FileExistsError as exc:
        raise RunnerError("snapshot_failure", f"snapshot exists: {destination}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def owner_payload(manifest: dict[str, Any], manifest_hash: str, owner_started_at: str, row: dict[str, Any] | None = None, log_path: Path | None = None) -> dict[str, Any]:
    runtime = manifest["runtime_contract"]
    return {"schema_version": OWNER_SCHEMA, "pid": os.getpid(), "hostname": socket.gethostname(), "started_at": owner_started_at, "manifest_sha256": manifest_hash, "lock_path": manifest["lock_path"], "current_row_id": row["row_id"] if row else None, "current_attempt_id": row["attempt_id"] if row else None, "current_row_started_at": now() if row else None, "current_log_path": str(log_path) if log_path else None, "python_executable": runtime["python_executable"], "make_cards_path": runtime["make_cards_path"]}


def publish_matching(source: Path, destination: Path, source_record: dict[str, Any]) -> None:
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink():
            raise RunnerError("canonical_collision_or_ambiguous_state", f"published path is a symlink: {destination}")
        if not valid_record({**source_record, "path": str(destination)}, destination):
            raise RunnerError("canonical_collision_or_ambiguous_state", f"published bytes differ: {destination}")
        return
    if source.is_symlink() or not valid_record(source_record, source) or source.stat().st_size == 0:
        raise RunnerError("canonical_collision_or_ambiguous_state", f"staged source differs: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError as exc:
        if exc.errno != 18:  # EXDEV: control_root may reside on another filesystem.
            raise RunnerError("canonical_collision_or_ambiguous_state", f"cannot publish {destination}: {exc}") from exc
        copy_once(source, destination)
    if not valid_record({**source_record, "path": str(destination)}, destination):
        raise RunnerError("canonical_collision_or_ambiguous_state", f"published bytes differ: {destination}")


def reconcile_row(manifest: dict[str, Any], manifest_hash: str, row: dict[str, Any]) -> dict[str, Any]:
    candidate = candidate_attempt(manifest, manifest_hash, row, attempts(manifest_hash, row))
    if candidate is None:
        raise RunnerError("canonical_collision_or_ambiguous_state", "no validated attempt for reconciliation", row_id=row["row_id"])
    attempt, intent = candidate
    state, reason = publication_state(row, attempt, intent)
    if state not in {"complete_validated_staging_not_promoted", "promoted_incomplete", "promoted_complete_without_receipt"}:
        raise RunnerError(state, reason, row_id=row["row_id"])
    root = Path(row["output_root"])
    if state == "complete_validated_staging_not_promoted":
        try:
            root.mkdir()  # Exclusive creation; a pre-existing directory is a collision.
        except FileExistsError as exc:
            raise RunnerError("canonical_collision_or_ambiguous_state", f"canonical destination exists: {root}", row_id=row["row_id"]) from exc
        try:
            os.link(attempt / "intent.json", root / INTENT_MARKER)
        except OSError as exc:
            raise RunnerError("canonical_collision_or_ambiguous_state", f"cannot mark canonical destination: {exc}", row_id=row["row_id"]) from exc
    source_outputs, source_artifacts = staged_paths(row, attempt)
    for source, destination, source_record in zip(source_outputs, map(Path, row["expected_output_paths"]), intent["primary_outputs"]):
        publish_matching(source, destination, source_record)
    for key, name in (("selected_wcs_snapshot", "selectedWCs.txt"), ("scalings_snapshot", "scalings-preselect.json")):
        source = source_artifacts[key]
        publish_matching(source, root / name, record(source))
    for key, destination in canonical_artifacts(row).items():
        publish_matching(source_artifacts[key], destination, intent["artifacts"][key])
    state, reason = publication_state(row, attempt, intent)
    if state != "promoted_complete_without_receipt":
        raise RunnerError(state, reason, row_id=row["row_id"])
    runtime = manifest["runtime_contract"]
    receipt = {"schema": RECEIPT_SCHEMA, "manifest_sha256": manifest_hash, "row_id": row["row_id"], "attempt_id": row["attempt_id"], "physical_attempt_id": attempt.name, "resolved_argv": resolved_argv(manifest, row), "execution_argv": intent["execution_argv"], "start_timestamp": intent["start_timestamp"], "end_timestamp": intent["end_timestamp"], "command_return_code": 0, "runtime_contract_id": runtime["contract_id"], "python_executable": runtime["python_executable"], "make_cards_path": runtime["make_cards_path"], "runtime_fingerprints": runtime["fingerprints"], "runtime_contract_digest": runtime_digest(runtime), "primary_outputs": [record(Path(path)) for path in row["expected_output_paths"]], "artifacts": {key: record(path) for key, path in canonical_artifacts(row).items()}}
    valid, reason = validate_receipt(receipt, manifest, manifest_hash, row)
    if not valid:
        raise RunnerError("canonical_collision_or_ambiguous_state", reason, row_id=row["row_id"])
    final = receipt_path(manifest, row)
    atomic_json(receipt, final, False)
    valid, reason = validate_receipt(json.loads(final.read_text()), manifest, manifest_hash, row)
    if not valid:
        raise RunnerError("invalid_receipt", reason, row_id=row["row_id"])
    return {"row_id": row["row_id"], "attempt_id": row["attempt_id"], "physical_attempt_id": attempt.name, "action": "reconciled", "receipt_path": str(final)}


def execute_row(manifest: dict[str, Any], manifest_hash: str, row: dict[str, Any], owner_started_at: str, *, lease_fds: tuple[int, ...] = (), backend: str = "local", scheduler_id: str | None = None) -> dict[str, Any]:
    entries = attempts(manifest_hash, row)
    next_index = int(entries[-1].name[-6:]) + 1 if entries else 1
    if next_index > 999999:
        raise RunnerError("canonical_collision_or_ambiguous_state", "physical attempt index exhausted", row_id=row["row_id"])
    root = attempt_root(manifest_hash, row)
    root.mkdir(parents=True, exist_ok=True)
    attempt = root / f"attempt_{next_index:06d}"
    attempt.mkdir()
    log = attempt / "producer.log"
    atomic_json({**owner_payload(manifest, manifest_hash, owner_started_at, row, log), "lock_path": str(unit_lock_path(row)), "backend": backend, "scheduler_id": scheduler_id}, unit_owner_path(row), True)
    try:
        handle = log.open("xb")
    except FileExistsError as exc:
        raise RunnerError("canonical_collision_or_ambiguous_state", f"log exists: {log}", row_id=row["row_id"]) from exc
    argv, started = staged_argv(manifest, row, attempt), now()
    with handle:
        handle.write((json.dumps({"row_id": row["row_id"], "attempt_id": row["attempt_id"], "physical_attempt_id": attempt.name, "resolved_argv": resolved_argv(manifest, row), "execution_argv": argv, "start_timestamp": started}, sort_keys=True) + "\n").encode())
        handle.flush()
        completed = subprocess.run(argv, cwd=row["working_directory"], stdout=handle, stderr=subprocess.STDOUT, check=False, pass_fds=lease_fds)
        os.fsync(handle.fileno())
    if completed.returncode:
        raise RunnerError("row_command_failed", f"direct producer argv returned {completed.returncode}; no retry was attempted", row_id=row["row_id"])
    output_paths, staged_artifacts = staged_paths(row, attempt)
    if any(not path.is_file() or path.stat().st_size == 0 for path in output_paths):
        raise RunnerError("expected_output_check_failed", "expected output missing or empty", row_id=row["row_id"])
    stage_root, merge = attempt / "cards", attempt / "merge_report.json"
    sources = {"selected_wcs": stage_root / "selectedWCs.txt", "scalings": stage_root / "scalings-preselect.json", "merge_report": merge}
    destinations = {key: staged_artifacts[f"{key}_snapshot"] if key != "merge_report" else staged_artifacts["merge_report_snapshot"] for key in sources}
    for key, source in sources.items():
        copy_once(source, destinations[key])
    for path in [*output_paths, *sources.values(), *staged_artifacts.values()]:
        if path.is_symlink() or not path.is_file():
            raise RunnerError("expected_output_check_failed", f"staged artifact is not a regular file: {path}", row_id=row["row_id"])
        with path.open("rb") as source_handle:
            os.fsync(source_handle.fileno())
    intent = {"schema": INTENT_SCHEMA, "manifest_sha256": manifest_hash, "row_id": row["row_id"], "attempt_id": row["attempt_id"], "physical_attempt_id": attempt.name, "resolved_argv": resolved_argv(manifest, row), "execution_argv": argv, "runtime_contract_digest": runtime_digest(manifest["runtime_contract"]), "command_return_code": 0, "start_timestamp": started, "end_timestamp": now(), "primary_outputs": [record(path) for path in output_paths], "artifacts": {key: record(path) for key, path in staged_artifacts.items()}}
    atomic_json(intent, attempt / "intent.json", False)
    valid, reason, _ = valid_intent(manifest, manifest_hash, row, attempt)
    if not valid:
        raise RunnerError("canonical_collision_or_ambiguous_state", reason, row_id=row["row_id"])
    result = reconcile_row(manifest, manifest_hash, row)
    result["action"] = "executed"
    return result


def execute_unit(manifest: dict[str, Any], manifest_hash: str, row: dict[str, Any], *, backend: str = "local", scheduler_id: str | None = None) -> dict[str, Any]:
    """The sole mutating primitive: acquire ownership, reconcile, then execute."""
    with unit_lease(manifest, row) as lease_fds:
        try:
            state = classify(manifest, manifest_hash, row, False, unit_owner(row) or read_owner(manifest))
            if state["status"] == "complete":
                return {"row_id": row["row_id"], "attempt_id": row["attempt_id"], "action": "skipped_valid_receipt", "receipt_path": state["receipt_path"]}
            if state["status"] in {"complete_validated_staging_not_promoted", "promoted_incomplete", "promoted_complete_without_receipt"}:
                return reconcile_row(manifest, manifest_hash, row)
            if state["status"] not in {"not_started", "stale_owner_free_lock", "partial_staging_attempt"}:
                raise RunnerError(state["status"], state["reason"], row_id=row["row_id"])
            validate_unit_layout(manifest)
            validate_runtime(manifest["runtime_contract"])
            validate_row_inputs(row)
            fresh = classify(manifest, manifest_hash, row, False, unit_owner(row) or read_owner(manifest))
            if fresh["status"] not in {"not_started", "stale_owner_free_lock", "partial_staging_attempt"}:
                raise RunnerError(fresh["status"], fresh["reason"], row_id=row["row_id"])
            return execute_row(manifest, manifest_hash, row, now(), lease_fds=lease_fds, backend=backend, scheduler_id=scheduler_id)
        finally:
            unit_owner_path(row).unlink(missing_ok=True)


def execute(manifest: dict[str, Any], manifest_hash: str, *, backend: str = "local", scheduler_id: str | None = None) -> dict[str, Any]:
    """Sequential convenience orchestration over the canonical unit primitive."""
    return {"schema": "topeft_datacard_matrix_execution_result_v2", "manifest_sha256": manifest_hash,
            "rows": [execute_unit(manifest, manifest_hash, row, backend=backend, scheduler_id=scheduler_id) for row in manifest["rows"]]}


def overlay_scheduler(result: dict[str, Any], overlay: Any) -> None:
    """Attach supplied observations without deriving producer completion/retry."""
    overlay = exact_fields(overlay, {"schema", "parent_integrity", "observed_at", "units"}, "scheduler_status")
    if overlay["schema"] != "topeft_datacard_scheduler_status_v1" or overlay["parent_integrity"] != result["manifest_sha256"]:
        raise RunnerError("scheduler_status_error", "scheduler observation parent binding differs")
    text(overlay["observed_at"], "observed_at")
    if not isinstance(overlay["units"], list):
        raise RunnerError("scheduler_status_error", "units must be a list")
    states = {row["row_id"]: row for row in result["rows"]}
    seen = set()
    for item in overlay["units"]:
        exact_fields(item, {"row_id", "scheduler_id", "state"}, "scheduler_unit")
        row_id = text(item["row_id"], "row_id")
        if row_id not in states or row_id in seen:
            raise RunnerError("scheduler_status_error", "unknown or duplicate scheduler row")
        seen.add(row_id)
        for key in ("scheduler_id", "state"):
            text(item[key], key)
        states[row_id]["scheduler_metadata"] = {**item, "observed_at": overlay["observed_at"], "completion_authority": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a prequalified datacard matrix with byte-bound receipts.")
    modes = parser.add_mutually_exclusive_group(); modes.add_argument("--plan-only", action="store_true"); modes.add_argument("--status", action="store_true")
    parser.add_argument("manifest", type=Path, nargs="?")
    parser.add_argument("--unit", type=Path, help="Derived execution-unit descriptor")
    parser.add_argument("--row-id", help="Select one row from the original manifest")
    modes.add_argument("--derive-units", action="store_true", help="Print deterministic descriptors without writing state")
    parser.add_argument("--backend", choices=("local", "condor", "manual"), default="local")
    parser.add_argument("--scheduler-id", help="Observational scheduler identity")
    parser.add_argument("--unit-integrity", help="Dispatch guard for descriptor bytes")
    parser.add_argument("--scheduler-status", type=Path, help="Read-only operational metadata overlay")
    parser.add_argument("--runner-integrity", help="Dispatch guard for the worker runner bytes")
    args = parser.parse_args(argv)
    if bool(args.manifest) == bool(args.unit) or (args.unit and (args.row_id or args.derive_units)):
        parser.error("supply either MANIFEST [--row-id ROW] or --unit DESCRIPTOR")
    if args.row_id and args.derive_units:
        parser.error("--derive-units describes the whole workload; use --row-id for execution/status")
    if args.scheduler_status and not args.status:
        parser.error("--scheduler-status requires --status")
    if args.unit_integrity and not args.unit:
        parser.error("--unit-integrity requires --unit")
    try:
        if args.runner_integrity and hash_file(Path(__file__)) != args.runner_integrity:
            raise RunnerError("stale_dispatch_input", "worker runner bytes changed")
        if args.derive_units:
            print(json.dumps(derive_units(args.manifest), indent=2, sort_keys=True))
            return 0
        if args.unit:
            raw_unit = args.unit.read_bytes()
            if args.unit_integrity and hashlib.sha256(raw_unit).hexdigest() != args.unit_integrity:
                raise RunnerError("stale_dispatch_input", "execution-unit descriptor bytes changed")
            manifest, manifest_hash, row = resolve_unit(json.loads(raw_unit))
        else:
            manifest, manifest_hash = load_manifest(args.manifest)
            row = select_row(manifest, args.row_id) if args.row_id else None
        if args.plan_only or args.status:
            result = read_only("plan_only" if args.plan_only else "status", manifest, manifest_hash, row["row_id"] if row else None)
        elif row:
            result = {"schema": "topeft_datacard_matrix_execution_result_v2", "manifest_sha256": manifest_hash,
                      "rows": [execute_unit(manifest, manifest_hash, row, backend=args.backend, scheduler_id=args.scheduler_id)]}
        else:
            result = execute(manifest, manifest_hash, backend=args.backend, scheduler_id=args.scheduler_id)
        if args.scheduler_status:
            overlay_scheduler(result, json.loads(args.scheduler_status.read_text()))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2 if args.plan_only and not result["launch_ready"] else 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"schema": "topeft_datacard_matrix_error_v2", "status": "dispatch_read_error", "message": str(exc)}), file=sys.stderr)
        return 2
    except RunnerError as exc:
        error = {"schema": "topeft_datacard_matrix_error_v2", "status": exc.code, "message": str(exc)}
        if exc.row_id is not None: error["row_id"] = exc.row_id
        print(json.dumps(error, indent=2, sort_keys=True), file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
