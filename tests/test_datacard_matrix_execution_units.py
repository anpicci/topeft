"""Synthetic execution-unit tests; no real producer or scheduler is invoked."""
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from analysis.topeft_run2 import datacard_matrix_runner as runner
from test_datacard_matrix_resumable_runner import (
    fake_script, make_row, manifest, sha, wait_for_owner, ENGINE,
)


def test_descriptors_preserve_parent_identity_and_detect_drift(tmp_path, fake_script):
    rows = [make_row(tmp_path, fake_script, name) for name in ("a", "b")]
    path, original = manifest(tmp_path, fake_script, rows)
    units = runner.derive_units(path)
    assert units == runner.derive_units(path)
    assert [unit["row_id"] for unit in units] == ["a", "b"]
    parent, digest, row = runner.resolve_unit(units[0])
    assert parent == original and digest == sha(path) and row == rows[0]
    path.write_text(path.read_text() + "\n")
    with pytest.raises(runner.RunnerError, match="bytes changed"):
        runner.resolve_unit(units[0])


def test_unit_executes_only_selected_row_and_switches_backend(tmp_path, fake_script):
    rows = [make_row(tmp_path, fake_script, name) for name in ("a", "b")]
    path, data = manifest(tmp_path, fake_script, rows)
    parent, digest, row = runner.resolve_unit(runner.derive_units(path)[0])
    assert runner.execute_unit(parent, digest, row)["action"] == "executed"
    assert not Path(rows[1]["output_root"]).exists()
    before = runner.receipt_path(data, row).read_bytes()
    assert runner.execute_unit(parent, digest, row, backend="condor")["action"] == "skipped_valid_receipt"
    assert runner.receipt_path(data, row).read_bytes() == before


def test_independent_leases_coexist_and_alias_manifest_blocks(tmp_path, fake_script):
    rows = [make_row(tmp_path, fake_script, name) for name in ("a", "b")]
    _, data = manifest(tmp_path, fake_script, rows)
    with runner.unit_lease(data, rows[0]), runner.unit_lease(data, rows[1]):
        with pytest.raises(runner.RunnerError) as error:
            runner.execute_unit(data, "other_manifest", {**rows[0], "row_id": "alias"}, backend="condor")
        assert error.value.code == "execution_lock_held"


def test_two_active_units_status_and_parent_kill_exclusion(tmp_path, fake_script):
    rows = [make_row(tmp_path, fake_script, name, extra=["--wait-for", str(tmp_path / "release"), "--counter", str(tmp_path / (name + "_started"))]) for name in ("a", "b")]
    path, data = manifest(tmp_path, fake_script, rows)
    processes = [subprocess.Popen([sys.executable, str(ENGINE), str(path), "--row-id", row["row_id"], "--backend", "condor", "--scheduler-id", "synthetic.0"], stdout=subprocess.PIPE, stderr=subprocess.PIPE) for row in rows]
    try:
        for row in rows:
            wait_for_owner(runner.unit_owner_path(row), row["row_id"])
        deadline = time.monotonic() + 10
        while not all((tmp_path / (name + "_started")).exists() for name in ("a", "b")) and time.monotonic() < deadline:
            time.sleep(.01)
        assert all((tmp_path / (name + "_started")).exists() for name in ("a", "b"))
        status = runner.read_only("status", data, sha(path))
        assert [state["status"] for state in status["rows"]] == ["active", "active"]
        assert all(state["owner_metadata"]["backend"] == "condor" for state in status["rows"])
        processes[0].kill()
        processes[0].wait()
        with pytest.raises(runner.RunnerError) as error:
            runner.execute_unit(data, sha(path), rows[0], backend="local")
        assert error.value.code == "execution_lock_held"
        assert not runner.receipt_path(data, rows[0]).exists()
        (tmp_path / "release").touch()
        processes[1].communicate(timeout=10)
        assert processes[1].returncode == 0
        deadline = time.monotonic() + 10
        while runner.probe_lock(runner.unit_lock_path(rows[0]))[0] and time.monotonic() < deadline:
            time.sleep(.02)
        assert runner.classify(data, sha(path), rows[0])["status"] == "partial_staging_attempt"
        assert not runner.receipt_path(data, rows[0]).exists()
    finally:
        (tmp_path / "release").touch()
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)


def test_whole_workload_composes_unit_executor(tmp_path, fake_script, monkeypatch):
    rows = [make_row(tmp_path, fake_script, name) for name in ("a", "b")]
    path, data = manifest(tmp_path, fake_script, rows)
    seen = []
    def execute_unit(parent, digest, row, **metadata):
        assert parent is data and digest == sha(path)
        seen.append(row["row_id"])
        return {"row_id": row["row_id"]}
    monkeypatch.setattr(runner, "execute_unit", execute_unit)
    assert runner.execute(data, sha(path))["rows"] == [{"row_id": "a"}, {"row_id": "b"}]
    assert seen == ["a", "b"]


def test_descriptor_cli_and_worker_integrity(tmp_path, fake_script):
    row = make_row(tmp_path, fake_script)
    path, data = manifest(tmp_path, fake_script, [row])
    unit_path = tmp_path / "unit.json"
    unit_path.write_text(json.dumps(runner.derive_units(path)[0]))
    command = [sys.executable, str(ENGINE), "--unit", str(unit_path), "--runner-integrity"]
    bad = subprocess.run([*command, "0" * 64], capture_output=True, text=True)
    assert bad.returncode == 2 and "stale_dispatch_input" in bad.stderr
    assert not Path(row["output_root"]).exists()
    good = subprocess.run([*command, sha(ENGINE)], capture_output=True, text=True)
    assert good.returncode == 0, good.stderr
    assert runner.validate_receipt(json.loads(runner.receipt_path(data, row).read_text()), data, sha(path), row)[0]


def test_nested_cross_manifest_domains_fail_closed(tmp_path, fake_script):
    outer = make_row(tmp_path, fake_script, "outer")
    path, data = manifest(tmp_path, fake_script, [outer])
    inner = {**outer, "output_root": str(Path(outer["output_root"]) / "inner")}
    with runner.unit_lease(data, outer):
        with pytest.raises(runner.RunnerError, match="nested"):
            with runner.unit_lease(data, inner):
                pytest.fail("nested domain acquired")
        assert not Path(outer["output_root"]).exists()
    assert not runner.receipt_path(data, outer).exists()


def test_legacy_manifest_layout_still_loads(tmp_path, fake_script):
    rows = [make_row(tmp_path, fake_script, name) for name in ("a", "b")]
    # Historically valid distinct targets can share an output root.
    rows[1]["output_root"] = rows[0]["output_root"]
    args = rows[1]["producer_args"]
    args[args.index("--out-dir") + 1] = rows[0]["output_root"]
    rows[1]["expected_output_paths"] = [str(Path(rows[0]["output_root"]) / "other.txt")]
    path, data = manifest(tmp_path, fake_script, rows)
    assert runner.load_manifest(path)[0] == data
    with pytest.raises(runner.RunnerError, match="disjoint"):
        runner.derive_units(path)
