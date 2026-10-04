"""Focused read-only behavior checks for the manifest-driven dashboard."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest


dashboard_source = Path(__file__).resolve().parents[1] / "analysis/topeft_run2/monitoring/datacard_matrix_dashboard.sh"


def dashboard_case(tmp_path):
    script_dir = tmp_path / "analysis/topeft_run2/monitoring"
    script_dir.mkdir(parents=True)
    dashboard = script_dir / "datacard_matrix_dashboard.sh"
    shutil.copy2(dashboard_source, dashboard)
    runner = script_dir.parent / "run_datacard_matrix_resumable.sh"
    runner.write_text('#!/bin/sh\n[ "$1" = "--status" ] || exit 90\ncat "' + str(tmp_path / "status.json") + '"\n')
    runner.chmod(0o755)

    control_root = tmp_path / "control"
    control_root.mkdir()
    rows = [
        {
            "row_id": f"unit_{index}",
            "logical_row_id": "logical_a" if index < 3 else "logical_b",
            "attempt_id": "attempt_01",
            "physical_channels": [f"channel_{index}_{part}" for part in range(index)],
            "output_root": str(tmp_path / "cards" / f"unit_{index}"),
            "log_path": str(control_root / f"unit_{index}.log"),
        }
        for index in (1, 2, 3)
    ]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema": "topeft_datacard_matrix_v3", "control_root": str(control_root), "rows": rows}))
    status = {
        "schema": "topeft_datacard_matrix_read_only_result_v2",
        "mode": "status",
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "mutated": False,
        "lock_held": True,
        "owner_metadata": {
            "current_row_id": "unit_2",
            "current_attempt_id": "attempt_01",
            "current_row_started_at": "2026-01-01T00:00:00Z",
        },
        "rows": [
            {"row_id": row["row_id"], "attempt_id": row["attempt_id"], "status": state}
            for row, state in zip(rows, ("complete", "active", "not_started"))
        ],
    }
    status_path = tmp_path / "status.json"
    status_path.write_text(json.dumps(status))
    return dashboard, manifest, status_path, control_root


def run_once(dashboard, manifest):
    return subprocess.run([str(dashboard), "--once", "--log-lines", "1", str(manifest)],
                          capture_output=True, text=True, check=False)


def test_dashboard_counts_targets_and_reads_only_current_log(tmp_path):
    dashboard, manifest, _, control_root = dashboard_case(tmp_path)
    current_log = control_root / "unit_2.log"
    current_log.write_text("older\nlatest\n")
    before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in control_root.iterdir()}

    result = run_once(dashboard, manifest)

    assert result.returncode == 0, result.stderr
    assert "Execution units: 1 / 3" in result.stdout
    assert "Physical targets: 1 / 6" in result.stdout
    assert "Active units   : 1 (2 targets)  Pending: 1  Problems: 0" in result.stdout
    assert "logical_a, logical_b" in result.stdout
    assert "channel_3_0,channel_3_1,channel_3_2" in result.stdout
    assert "2026-01-01T00:00:00Z" in result.stdout
    assert "latest" in result.stdout
    assert "older" not in result.stdout
    assert before == {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in control_root.iterdir()}


def test_dashboard_waits_for_absent_active_log(tmp_path):
    dashboard, manifest, _, control_root = dashboard_case(tmp_path)
    result = run_once(dashboard, manifest)
    assert result.returncode == 0, result.stderr
    assert f"[waiting for log] {control_root / 'unit_2.log'}" in result.stdout
    assert list(control_root.iterdir()) == []


@pytest.mark.parametrize("change", ["wrong_schema", "row_mismatch", "unknown_state", "mutated"])
def test_dashboard_rejects_inconsistent_status(tmp_path, change):
    dashboard, manifest, status_path, _ = dashboard_case(tmp_path)
    status = json.loads(status_path.read_text())
    if change == "wrong_schema":
        status["schema"] = "wrong"
    elif change == "row_mismatch":
        status["rows"][0]["row_id"] = "other"
    elif change == "unknown_state":
        status["rows"][0]["status"] = "mystery"
    else:
        status["mutated"] = True
    status_path.write_text(json.dumps(status))
    result = run_once(dashboard, manifest)
    assert result.returncode == 2
    assert "invalid JSON, unknown state, or rows inconsistent" in result.stderr


def test_dashboard_rejects_wrong_manifest_schema(tmp_path):
    dashboard, manifest, _, _ = dashboard_case(tmp_path)
    content = json.loads(manifest.read_text())
    content["schema"] = "topeft_datacard_matrix_v2"
    manifest.write_text(json.dumps(content))
    result = run_once(dashboard, manifest)
    assert result.returncode == 2
    assert "not readable v3 JSON" in result.stderr


def test_dashboard_rejects_invalid_status_json(tmp_path):
    dashboard, manifest, status_path, _ = dashboard_case(tmp_path)
    status_path.write_text("not JSON")
    result = run_once(dashboard, manifest)
    assert result.returncode == 2
    assert "invalid JSON" in result.stderr


def test_dashboard_reports_missing_runner(tmp_path):
    dashboard, manifest, _, _ = dashboard_case(tmp_path)
    (dashboard.parent.parent / "run_datacard_matrix_resumable.sh").unlink()
    result = run_once(dashboard, manifest)
    assert result.returncode == 2
    assert "runner is missing or not executable" in result.stderr
