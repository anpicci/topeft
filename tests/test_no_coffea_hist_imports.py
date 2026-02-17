from __future__ import annotations

import subprocess
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_TEXT_SUFFIXES = {".py", ".md", ".rst", ".txt", ".ipynb"}
_FORBIDDEN_TOKENS = (
    "coffea.hist",
    "from coffea import hist",
    "import coffea.hist",
)
_SELF_TEST_RELATIVE = Path("tests/test_no_coffea_hist_imports.py")


def _tracked_text_files() -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files"],
        cwd=_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    files: list[Path] = []
    for relpath in completed.stdout.splitlines():
        candidate = _ROOT / relpath
        if candidate.exists() and candidate.suffix in _TEXT_SUFFIXES:
            files.append(candidate)
    return files


def test_no_legacy_coffea_hist_imports() -> None:
    matches: list[str] = []
    for path in _tracked_text_files():
        relpath = path.relative_to(_ROOT)
        if relpath == _SELF_TEST_RELATIVE:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
            if any(token in line for token in _FORBIDDEN_TOKENS):
                matches.append(f"{relpath}:{lineno}:{line.strip()}")

    assert not matches, "Legacy coffea histogram references are forbidden:\n" + "\n".join(matches)
