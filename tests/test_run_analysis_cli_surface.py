"""CLI surface checks for run_analysis.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run_analysis_path() -> Path:
    repo_root = Path(__file__).resolve().parent.parent
    return repo_root / "analysis" / "topeft_run2" / "run_analysis.py"


def test_run_analysis_help_omits_futures_workers() -> None:
    script_path = _run_analysis_path()
    completed = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--futures-workers" not in completed.stdout
