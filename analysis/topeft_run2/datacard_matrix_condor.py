"""Prepare shared-filesystem HTCondor dispatch material; never submit jobs.

The matrix runner owns topology, leases, reconciliation and completion. This
module only serializes an explicit common resource request and unit dispatch.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shlex

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
        items.append(f"{unit['row_id']} {runner.hash_file(unit_path)}")
    (destination / "items.txt").write_text("\n".join(items) + "\n")
    worker = destination / "worker.sh"
    command = " ".join(shlex.quote(value) for value in (python, str(engine)))
    worker.write_text(
        '#!/bin/sh\nset -eu\n'
        + f'exec {command} --unit {shlex.quote(str(destination / "units"))}/"$1".json '
        + '--unit-integrity "$2" --backend condor --scheduler-id "$3" '
        + f'--runner-integrity {runner.hash_file(engine)}\n'
    )
    worker.chmod(0o755)
    lines = [
        "universe = vanilla", f"executable = {worker}",
        'arguments = "$(row_id) $(unit_integrity) $(Cluster).$(Process)"',
        f"initialdir = {destination}", "should_transfer_files = NO",
        "getenv = true", f"request_cpus = {request_cpus}",
        f"request_memory = {request_memory}", f"request_disk = {request_disk}",
        f"output = {destination}/logs/$(Cluster).$(Process).out",
        f"error = {destination}/logs/$(Cluster).$(Process).err",
        f"log = {destination}/logs/events.log",
        '+DatacardUnit = "$(row_id)"',
        '+DatacardParentIntegrity = "' + units[0]["parent_integrity"] + '"',
        "on_exit_hold = (ExitBySignal == True) || (ExitCode != 0)",
    ]
    if max_runtime is not None:
        lines.append(f"+MaxRuntime = {max_runtime}")
    lines.append(f"queue row_id, unit_integrity from {destination}/items.txt")
    # Publish the submit description last; failed preparation leaves no ready job.
    pending = destination / ".datacards.sub.pending"
    with pending.open("x") as handle:
        handle.write("\n".join(lines) + "\n")
    runner.copy_once(pending, destination / "datacards.sub")
    pending.unlink()
    return {"submitted": False, "submit_file": str(destination / "datacards.sub"),
            "unit_ids": [unit["row_id"] for unit in units],
            "storage_model": "shared_filesystem", "receipt_authority": "matrix_runner"}
