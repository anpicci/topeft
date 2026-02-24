"""Token-level hygiene checks for legacy worker-flag spellings."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def test_no_legacy_worker_flag_tokens_in_tracked_files() -> None:
    head = "futures"
    tail = "workers"
    dash = "-"
    under = "_"
    pattern = f"{head}{dash}{tail}|{head}{under}{tail}|--{head}{dash}{tail}"

    completed = subprocess.run(
        ["git", "grep", "-n", "-E", pattern],
        cwd=_repo_root(),
        check=False,
        capture_output=True,
        text=True,
    )

    # git grep returns 1 when there are no matches.
    assert completed.returncode == 1, completed.stdout + completed.stderr
