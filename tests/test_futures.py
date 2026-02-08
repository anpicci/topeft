import os
from pathlib import Path
import subprocess
import sys

import pytest

import topeft.modules.dataDrivenEstimation as dataDrivenEstimation
from topeft.modules.comp_datacard import comp_datacard


_HIST_DIR = Path("analysis/topeft_run2/histos")
_YIELDS_PKL = _HIST_DIR / "output_check_yields.pkl.gz"
_NONPROMPT_PKL = _HIST_DIR / "output_check_yields_nonprompt.pkl.gz"


def _require_integration_opt_in() -> None:
    if os.environ.get("TOPEFT_RUN_ARTIFACT_INTEGRATION") == "1":
        return
    pytest.skip(
        "Artifact integration tests are disabled by default. "
        "Set TOPEFT_RUN_ARTIFACT_INTEGRATION=1 to enable."
    )


def _require_artifact(path: Path, *, producer_cmd: str) -> None:
    if path.exists():
        return
    pytest.skip(
        f"Missing required artifact '{path}'. Produce it with: {producer_cmd}"
    )


def test_topcoffea():
    _require_integration_opt_in()

    args = [
        "time",
        sys.executable,
        "run_analysis.py",
        "-x",
        "futures",
        "../../input_samples/sample_jsons/test_samples/UL17_private_ttH_for_CI.json",
        "-o",
        "output_check_yields",
        "-p",
        "histos/"
    ]

    # Run TopCoffea
    subprocess.run(args, check=True, cwd="analysis/topeft_run2")

    assert _YIELDS_PKL.exists()


def test_nonprompt():
    _require_artifact(
        _YIELDS_PKL,
        producer_cmd=(
            "TOPEFT_RUN_ARTIFACT_INTEGRATION=1 "
            f"{sys.executable} analysis/topeft_run2/run_analysis.py -x futures "
            "input_samples/sample_jsons/test_samples/UL17_private_ttH_for_CI.json "
            "-o output_check_yields -p analysis/topeft_run2/histos/"
        ),
    )

    a=dataDrivenEstimation.DataDrivenProducer(str(_YIELDS_PKL), str(_HIST_DIR / "output_check_yields_nonprompt"))
    a.dumpToPickle() # Do we want to write this file when testing in CI? Maybe if we ever save the CI artifacts

    assert _NONPROMPT_PKL.exists()

def test_datacardmaker():
    _require_artifact(
        _NONPROMPT_PKL,
        producer_cmd=(
            f"{sys.executable} -m pytest -q tests/test_futures.py::test_nonprompt -q"
        ),
    )

    args = [
        "time",
        sys.executable,
        "analysis/topeft_run2/make_cards.py",
        str(_NONPROMPT_PKL),
        "-d",
        "histos",
        "--var-lst",
        "lj0pt",
        "--do-nuisance",
        "--ch-lst",
        "2lss_p_4j",
        "--skip-selected-wcs-check"
    ]

    # Run datacard maker
    subprocess.run(args, check=True)

    assert (comp_datacard('histos/ttx_multileptons-2lss_p_4j_lj0pt.txt','analysis/topeft_run2/test/ttx_multileptons-2lss_p_4j_lj0pt.txt'))
