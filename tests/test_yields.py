from pathlib import Path
import subprocess
import sys

import pytest


_YIELDS_PKL = Path("analysis/topeft_run2/histos/output_check_yields.pkl.gz")
_YIELDS_JSON = Path("analysis/topeft_run2/output_check_yields.json")


def _require_artifact(path: Path, *, producer_cmd: str) -> None:
    if path.exists():
        return
    pytest.skip(
        f"Missing required artifact '{path}'. Produce it with: {producer_cmd}"
    )

def test_make_yields_after_processor():
    _require_artifact(
        _YIELDS_PKL,
        producer_cmd=(
            "python analysis/topeft_run2/run_analysis.py -x futures "
            "input_samples/sample_jsons/test_samples/UL17_private_ttH_for_CI.json "
            "-o output_check_yields -p analysis/topeft_run2/histos/"
        ),
    )

    args = [
        sys.executable,
        "analysis/topeft_run2/get_yield_json.py",
        "-f",
        "analysis/topeft_run2/histos/output_check_yields.pkl.gz",
        "-n",
        "analysis/topeft_run2/output_check_yields"
    ]

    # Produce json
    out = subprocess.run(args, check=True)
    assert (out.returncode == 0) # Returns 0 if all pass
    assert _YIELDS_JSON.exists()

def test_compare_yields_after_processor():
    _require_artifact(
        _YIELDS_JSON,
        producer_cmd=(
            f"{sys.executable} analysis/topeft_run2/get_yield_json.py -f "
            "analysis/topeft_run2/histos/output_check_yields.pkl.gz "
            "-n analysis/topeft_run2/output_check_yields"
        ),
    )

    args = [
        sys.executable,
        "analysis/topeft_run2/comp_yields.py",
        "analysis/topeft_run2/output_check_yields.json",
        "analysis/topeft_run2/test/UL17_private_ttH_for_CI_yields.json",
        "-t1",
        "New yields",
        "-t2",
        "Ref yields"
    ]

    # Run comparison
    out = subprocess.run(args, stdout=True)
    assert (out.returncode == 0) # Returns 0 if all pass
