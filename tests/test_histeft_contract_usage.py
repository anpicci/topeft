from pathlib import Path
import re
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ROOTS = ("analysis", "topeft/modules")
FORBIDDEN_PATTERNS = (
    re.compile(r"topcoffea\.modules\.HistEFT\.HistEFT"),
    re.compile(r"from\s+topcoffea\.modules\.HistEFT\b"),
    re.compile(r"topcoffea\.modules\.HistEFT\b"),
    re.compile(r"\bHistEFT_add\b"),
    re.compile(r"\btest_HistEFT\b"),
)


def _read(relpath: str) -> str:
    return (REPO_ROOT / relpath).read_text(encoding="utf-8")


def _iter_tracked_production_py_files():
    result = subprocess.run(
        ["git", "ls-files", *PRODUCTION_ROOTS],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    for relpath in result.stdout.splitlines():
        if not relpath.endswith(".py"):
            continue
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
        assert "from topcoffea.modules.histEFT import HistEFT" in source
        assert "topcoffea.modules.HistEFT.HistEFT" not in source


def test_no_legacy_histeft_references_in_production_roots():
    violations = []
    for path in _iter_tracked_production_py_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for pattern in FORBIDDEN_PATTERNS:
                if pattern.search(line):
                    violations.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert not violations, "Legacy HistEFT references found:\n" + "\n".join(violations)


def test_group_bins_uses_modern_sparsehist_group_signature():
    source = _read("analysis/topeft_run2/make_cr_and_sr_plots.py")
    assert "histo.group(axis_name, bin_map)" in source
    assert "def group(h: HistEFT" not in source
