from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relpath: str) -> str:
    return (REPO_ROOT / relpath).read_text(encoding="utf-8")


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


def test_group_bins_uses_modern_sparsehist_group_signature():
    source = _read("analysis/topeft_run2/make_cr_and_sr_plots.py")
    assert "histo.group(axis_name, bin_map)" in source
    assert "def group(h: HistEFT" not in source
