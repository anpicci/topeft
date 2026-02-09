from __future__ import annotations

from pathlib import Path
import re
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_HISTEFT_IMPORT = "from topcoffea.modules.histEFT import HistEFT"
LEGACY_MODULE_TOKEN = "Hist" + "EFT"
LEGACY_CLASS_PATH = "topcoffea.modules." + "HistEFT.HistEFT"
TRACKED_TEXT_SUFFIXES = {".py", ".md", ".rst", ".txt", ".ipynb"}
TRACKED_SOURCE_ROOTS = ("analysis", "topeft/modules")

FORBIDDEN_PATTERNS = (
    re.compile(r"topcoffea\.modules\." + LEGACY_MODULE_TOKEN + r"(?:\." + LEGACY_MODULE_TOKEN + r")?"),
    re.compile(r"from\s+topcoffea\.modules\." + LEGACY_MODULE_TOKEN + r"\b"),
    re.compile(r"\b" + ("Hist" + "EFT_add") + r"\b"),
    re.compile(r"\btest_" + ("Hist" + "EFT") + r"(?:_add)?\b"),
)


def _read(relpath: str) -> str:
    return (REPO_ROOT / relpath).read_text(encoding="utf-8")


def _iter_tracked_files():
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    for relpath in result.stdout.splitlines():
        yield REPO_ROOT / relpath


def _iter_tracked_text_files():
    for path in _iter_tracked_files():
        if path.suffix.lower() in TRACKED_TEXT_SUFFIXES:
            yield path


def _iter_tracked_source_py_files():
    result = subprocess.run(
        ["git", "ls-files", *TRACKED_SOURCE_ROOTS],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    for relpath in result.stdout.splitlines():
        if relpath.endswith(".py"):
            yield REPO_ROOT / relpath


def test_production_modules_import_canonical_histeft_path():
    for relpath in [
        "analysis/topeft_run2/analysis_processor.py",
        "analysis/topeft_run2/sow_processor.py",
        "analysis/topeft_run2/make_cr_and_sr_plots.py",
        "analysis/training/simple_processor.py",
        "analysis/training/simple_run.py",
        "analysis/mc_validation/mc_validation_gen_processor.py",
        "topeft/modules/yield_tools.py",
    ]:
        source = _read(relpath)
        assert CANONICAL_HISTEFT_IMPORT in source
        assert LEGACY_CLASS_PATH not in source


def test_no_legacy_histeft_references_in_tracked_repo_files():
    violations = []
    for path in _iter_tracked_text_files():
        relpath = path.relative_to(REPO_ROOT)
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for pattern in FORBIDDEN_PATTERNS:
                if pattern.search(line):
                    violations.append(f"{relpath}:{lineno}: {line.strip()}")
    assert not violations, "Legacy HistEFT references found:\n" + "\n".join(violations)


def test_no_legacy_histeft_references_in_source_python_files():
    """Production sources should remain clear even if docs are edited separately."""

    violations = []
    for path in _iter_tracked_source_py_files():
        relpath = path.relative_to(REPO_ROOT)
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for pattern in FORBIDDEN_PATTERNS:
                if pattern.search(line):
                    violations.append(f"{relpath}:{lineno}: {line.strip()}")
    assert not violations, "Legacy HistEFT references found in source roots:\n" + "\n".join(violations)


def test_group_bins_uses_modern_sparsehist_group_signature():
    source = _read("analysis/topeft_run2/make_cr_and_sr_plots.py")
    assert "histo.group(axis_name, bin_map)" in source
    assert "def group(h: HistEFT" not in source
