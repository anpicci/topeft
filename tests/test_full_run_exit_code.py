"""Regression tests for full_run.sh exit-code propagation and marker behavior."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _full_run_script() -> Path:
    repo_root = Path(__file__).resolve().parent.parent
    return repo_root / "analysis" / "topeft_run2" / "full_run.sh"


def test_full_run_self_test_exit_zero_writes_marker(tmp_path: Path) -> None:
    script_path = _full_run_script()
    marker_path = tmp_path / "exit_zero.txt"

    env = os.environ.copy()
    env["TOPEFT_EXIT_MARKER"] = str(marker_path)
    env["TOPEFT_EXIT_DEBUG"] = "1"

    completed = subprocess.run(
        [str(script_path), "--self-test-exit-propagation", "0"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 0
    assert marker_path.read_text(encoding="utf-8").strip() == "0"
    assert "driver_status=0" in completed.stderr


def test_full_run_self_test_exit_nonzero_with_tee_and_marker(tmp_path: Path) -> None:
    script_path = _full_run_script()
    marker_path = tmp_path / "exit_nonzero.txt"
    log_path = tmp_path / "driver.log"

    env = os.environ.copy()
    env["TOPEFT_EXIT_MARKER"] = str(marker_path)
    env["TOPEFT_DRIVER_LOG"] = str(log_path)
    env["TOPEFT_EXIT_DEBUG"] = "1"

    completed = subprocess.run(
        [str(script_path), "--self-test-exit-propagation", "17"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 17
    assert marker_path.read_text(encoding="utf-8").strip() == "17"
    assert log_path.exists()
    log_text = log_path.read_text(encoding="utf-8")
    assert "full_run self-test stdout" in log_text
    assert "full_run self-test stderr" in log_text
    assert "driver_status=17" in completed.stderr
    assert "pipestatus=[" in completed.stderr
