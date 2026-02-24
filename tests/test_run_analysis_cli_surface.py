"""CLI surface checks for run_analysis.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run_analysis_path() -> Path:
    repo_root = Path(__file__).resolve().parent.parent
    return repo_root / "analysis" / "topeft_run2" / "run_analysis.py"


def _run_sow_path() -> Path:
    repo_root = Path(__file__).resolve().parent.parent
    return repo_root / "analysis" / "topeft_run2" / "run_sow.py"


def test_run_analysis_help_omits_legacy_worker_flag() -> None:
    script_path = _run_analysis_path()
    completed = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    forbidden = "--" + "futures" + "-" + "workers"
    assert forbidden not in completed.stdout


def test_run_sow_help_includes_central_nworkers_flag() -> None:
    script_path = _run_sow_path()
    completed = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--nworkers" in completed.stdout
