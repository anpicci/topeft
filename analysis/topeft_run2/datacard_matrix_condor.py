"""Prepare shared-filesystem HTCondor dispatch material; never submit jobs.

The matrix runner owns topology, leases, reconciliation and completion. This
module only serializes an explicit common resource request and unit dispatch.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shlex
import shutil

try:
    from . import datacard_matrix_runner as runner
except ImportError:  # Direct make_cards.py entrypoint.
    import datacard_matrix_runner as runner


_safe_path = re.compile(r"^/[A-Za-z0-9_./+-]+$")
_resource = re.compile(r"^[1-9][0-9]*(?:[KMGTP]B?|B)?$", re.IGNORECASE)


def submit_path(path: Path) -> str:
    value = str(path.resolve())
    if not _safe_path.fullmatch(value):
        raise runner.RunnerError("condor_configuration_error", "submit paths must be absolute and contain only letters, digits, _ . / + -")
    return value


def prepare_material(manifest_path: Path, destination: Path, *, request_cpus: int,
                     request_memory: str, request_disk: str,
                     max_retries: int, max_starts: int, schedd: str, pool: str,
                     query_executable: str | None = None,
                     max_runtime: int | None = None) -> dict:
    """Write fresh dispatch material with one item per canonical unit.

    Paths and runtime must be visible at the same absolute locations on workers.
    Memory/disk values use HTCondor submit units (or explicit unit suffixes).
    No resource values, concurrency cap, transfer model or retries are guessed.
    """
    if type(request_cpus) is not int or request_cpus <= 0:
        raise runner.RunnerError("condor_configuration_error", "request_cpus must be an explicit positive integer")
    if any(not isinstance(value, str) or not _resource.fullmatch(value) for value in (request_memory, request_disk)):
        raise runner.RunnerError("condor_configuration_error", "request_memory and request_disk require explicit positive quantities")
    if max_runtime is not None and (type(max_runtime) is not int or max_runtime <= 0):
        raise runner.RunnerError("condor_configuration_error", "max_runtime must be positive seconds when supplied")
    if type(max_retries) is not int or max_retries < 0 or type(max_starts) is not int or max_starts <= 0:
        raise runner.RunnerError("condor_configuration_error", "explicit max_retries >= 0 and max_starts > 0 are required")
    if any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:@+-]*", value) for value in (schedd, pool)):
        raise runner.RunnerError("condor_configuration_error", "explicit schedd and pool endpoints are required")
    query_executable = query_executable or shutil.which("condor_q")
    if (not query_executable or not Path(query_executable).is_absolute()
            or not Path(query_executable).is_file() or not os.access(query_executable, os.X_OK)):
        raise runner.RunnerError("condor_configuration_error", "an absolute maintained condor_q executable is required")
    scheduler = {"schedd": schedd, "pool": pool, "query_executable": submit_path(Path(query_executable))}
    units = runner.derive_units(manifest_path)
    manifest, _, _ = runner.resolve_unit(units[0])
    destination = Path(submit_path(destination))
    engine = Path(runner.__file__).resolve()
    python = manifest["runtime_contract"]["python_executable"]
    submit_path(engine)
    submit_path(Path(python))
    # Validate before creating output; exclusive mkdir provides no-overwrite.
    try:
        destination.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise runner.RunnerError("condor_output_exists", f"dispatch destination exists: {destination}") from exc
    (destination / "units").mkdir()
    (destination / "logs").mkdir()
    items = []
    for unit in units:
        unit_path = destination / "units" / (unit["row_id"] + ".json")
        runner.atomic_json(unit, unit_path, False)
        items.append(f"{unit['row_id']} {runner.hash_file(unit_path)} unreserved")
    (destination / "items.txt").write_text("\n".join(items) + "\n")
    worker = destination / "worker.sh"
    command = " ".join(shlex.quote(value) for value in (python, str(engine)))
    worker.write_text(
        '#!/bin/sh\nset -eu\n'
        + f'exec {command} --unit {shlex.quote(str(destination / "units"))}/"$1".json '
        + '--unit-integrity "$2" --backend condor --scheduler-id "$3" '
        + '--reservation-token "$4" '
        + f'--runner-integrity {runner.hash_file(engine)}\n'
    )
    worker.chmod(0o755)
    lines = [
        "universe = vanilla", f"executable = {worker}",
        'arguments = "$(row_id) $(unit_integrity) $(Cluster).$(Process) $(reservation_token)"',
        f"initialdir = {destination}", "should_transfer_files = NO",
        "getenv = false", f"request_cpus = {request_cpus}",
        f"request_memory = {request_memory}", f"request_disk = {request_disk}",
        f"output = {destination}/logs/$(row_id)__$(Cluster).$(Process).out",
        f"error = {destination}/logs/$(row_id)__$(Cluster).$(Process).err",
        f"log = {destination}/logs/$(row_id)__$(Cluster).$(Process).events.log",
        '+DatacardUnit = "$(row_id)"',
        '+DatacardParentIntegrity = "' + units[0]["parent_integrity"] + '"',
        '+DatacardReservation = "$(reservation_token)"',
        f"max_retries = {max_retries}", "success_exit_code = 0",
        f"requirements = MY.NumJobStarts < {max_starts}",
        f"on_exit_remove = NumJobStarts >= {max_starts}",
        f"periodic_remove = (JobStatus == 5) || (JobStatus == 1 && NumJobStarts >= {max_starts})",
    ]
    if max_runtime is not None:
        lines.append(f"allowed_execute_duration = {max_runtime}")
    lines.append(f"queue row_id, unit_integrity, reservation_token from {destination}/items.txt")
    # Publish the submit description last; failed preparation leaves no ready job.
    pending = destination / ".datacards.sub.pending"
    with pending.open("x") as handle:
        handle.write("\n".join(lines) + "\n")
    runner.copy_once(pending, destination / "datacards.sub")
    pending.unlink()
    return {"submitted": False, "submit_file": str(destination / "datacards.sub"),
            "unit_ids": [unit["row_id"] for unit in units],
            "reservation_state": "unreserved_material_only",
            "scheduler": scheduler,
            "storage_model": "shared_filesystem", "receipt_authority": "matrix_runner"}


@contextmanager
def submission_transaction(manifest_path: Path, destination: Path, scheduler: dict):
    """Bind prepared itemdata inside a reservation transaction; never submit.

    A future submit caller must mark_submission_started immediately before any
    possible scheduler side effect, inherit transaction.lease_fds into the
    submit subprocess, and wait for it to terminate before exiting. Exceptions,
    timeout and nonzero exit after that marker preserve all reservations.
    """
    units = runner.derive_units(manifest_path)
    manifest, manifest_hash, _ = runner.resolve_unit(units[0])
    items = []
    for unit in units:
        unit_path = destination / "units" / (unit["row_id"] + ".json")
        if json.loads(unit_path.read_text()) != unit:
            raise runner.RunnerError("stale_dispatch_input", "prepared descriptor differs from canonical unit")
        items.append((unit["row_id"], runner.hash_file(unit_path)))
    with runner.reserve_condor(manifest, manifest_hash, manifest["rows"], scheduler) as transaction:
        tokens = {item["row_id"]: item["owner_id"] for item in transaction.reservations}
        (destination / "items.txt").write_text("".join(
            f"{row_id} {integrity} {tokens[row_id]}\n" for row_id, integrity in items))
        yield transaction
