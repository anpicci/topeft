import correctionlib
import numpy as np
import pytest
import awkward as ak

import topcoffea

from coffea.btag_tools import BTagScaleFactor

from topeft.modules.corrections import (
    ApplyJetCorrections,
    build_corrected_jets,
    build_corrected_met,
    clib_year_map,
    egm_tag_map,
    get_jerc_keys,
)
from topeft.modules.paths import topeft_path

topcoffea_path = topcoffea.modules.paths.topcoffea_path


@pytest.mark.parametrize("year", ["2018", "2023", "2023BPix"])
def test_apply_jet_corrections_factory_creation(year):
    """Ensure jet and MET correction factories can be instantiated for Run 2 and Run 3."""
    jet_factory = ApplyJetCorrections(year, "jet", isData=False, era=None, useclib=True)
    met_factory = ApplyJetCorrections(year, "met", isData=False, era=None, useclib=True)
    assert jet_factory is not None
    assert met_factory is not None


def test_apply_jet_corrections_build_with_allowed_variations():
    """Smoke-test that central corrections run even when all variations are gated off."""

    jets = ak.Array(
        [
            [
                {
                    "pt": np.float32(45.0),
                    "eta": np.float32(0.2),
                    "phi": np.float32(0.1),
                    "mass": np.float32(10.0),
                    "rawFactor": np.float32(0.1),
                    "area": np.float32(0.5),
                    "pt_gen": np.float32(44.0),
                    "pt_raw": np.float32(40.5),
                    "mass_raw": np.float32(9.0),
                    "rho": np.float32(0.5),
                }
            ]
        ]
    )
    met = ak.Array(
        [
            {
                "pt": np.float32(50.0),
                "phi": np.float32(0.0),
                "MetUnclustEnUpDeltaX": np.float32(0.0),
                "MetUnclustEnUpDeltaY": np.float32(0.0),
            }
        ]
    )

    allowed = {"jes": False, "jer": False, "ues": False}
    jet_factory = ApplyJetCorrections(
        "2018",
        "jet",
        isData=False,
        era=None,
        useclib=True,
        allowed_variations=allowed,
    )
    corrected_jets = build_corrected_jets(jet_factory, jets)
    jet_fields = set(ak.fields(corrected_jets))
    assert "pt" in jet_fields
    assert "jet_energy_correction" in jet_fields  # central correction applied
    assert "JER" not in jet_fields

    met_factory = ApplyJetCorrections(
        "2018",
        "met",
        isData=False,
        era=None,
        useclib=True,
        allowed_variations=allowed,
    )
    corrected_met = build_corrected_met(met_factory, met, corrected_jets)
    assert "MET_UnclusteredEnergy" not in ak.fields(corrected_met)


def test_apply_jet_corrections_builds_variation_branches_when_enabled():
    jets = ak.Array(
        [
            [
                {
                    "pt": np.float32(45.0),
                    "eta": np.float32(0.2),
                    "phi": np.float32(0.1),
                    "mass": np.float32(10.0),
                    "rawFactor": np.float32(0.1),
                    "area": np.float32(0.5),
                    "pt_gen": np.float32(44.0),
                    "pt_raw": np.float32(40.5),
                    "mass_raw": np.float32(9.0),
                    "rho": np.float32(0.5),
                }
            ]
        ]
    )
    met = ak.Array(
        [
            {
                "pt": np.float32(50.0),
                "phi": np.float32(0.0),
                "MetUnclustEnUpDeltaX": np.float32(0.0),
                "MetUnclustEnUpDeltaY": np.float32(0.0),
            }
        ]
    )

    allowed = {"jes": {"components": ["FlavorQCD"]}, "jer": True, "ues": True}
    jet_factory = ApplyJetCorrections(
        "2018",
        "jet",
        isData=False,
        era=None,
        useclib=True,
        allowed_variations=allowed,
    )
    corrected_jets = build_corrected_jets(jet_factory, jets)
    jet_fields = set(ak.fields(corrected_jets))
    assert "JER" in jet_fields
    assert any(field.startswith("JES_") for field in jet_fields)

    met_factory = ApplyJetCorrections(
        "2018",
        "met",
        isData=False,
        era=None,
        useclib=True,
        allowed_variations=allowed,
    )
    corrected_met = build_corrected_met(met_factory, met, corrected_jets)
    assert "MET_UnclusteredEnergy" in ak.fields(corrected_met)


@pytest.mark.parametrize("year", ["2018", "2023", "2023BPix"])
def test_jme_resources_available(year):
    """Verify that the correctionlib resources contain the expected JEC/JER entries."""
    clib_year = clib_year_map[year]
    cset = correctionlib.CorrectionSet.from_file(
        topcoffea_path(f"data/POG/JME/{clib_year}/jet_jerc.json.gz")
    )
    jet_algo, jec_tag, jec_levels, jer_tag, junc_types = get_jerc_keys(year, isdata=False)

    for level in jec_levels:
        assert f"{jec_tag}_{level}_{jet_algo}" in cset.keys()

    if jer_tag is not None:
        assert f"{jer_tag}_ScaleFactor_{jet_algo}" in cset.keys()
        assert f"{jer_tag}_PtResolution_{jet_algo}" in cset.keys()


@pytest.mark.parametrize("clib_year", sorted(egm_tag_map.keys()))
def test_electron_corrections_eval(clib_year):
    """Evaluate a representative electron scale factor to confirm category mapping."""
    egm_year = egm_tag_map[clib_year]
    cset = correctionlib.CorrectionSet.from_file(
        topcoffea_path(f"data/POG/EGM/{clib_year}/electron.json.gz")
    )

    corr_name = "Electron-ID-SF"
    working_point = "Reco20to75"
    eval_args = (egm_year, "sf", working_point, 0.1, 50.0)

    if clib_year.startswith("201"):
        corr_name = "UL-Electron-ID-SF"
        working_point = "RecoAbove20"
        eval_args = (egm_year, "sf", working_point, 0.1, 50.0)
    elif clib_year.startswith("2023"):
        eval_args = (egm_year, "sf", working_point, 0.1, 50.0, 0.1)

    value = cset[corr_name].evaluate(*eval_args)
    assert np.isfinite(value)


@pytest.mark.parametrize("clib_year", sorted(set(clib_year_map.values())))
def test_muon_corrections_eval(clib_year):
    """Evaluate a representative muon scale factor from the correctionlib payload."""
    cset = correctionlib.CorrectionSet.from_file(
        topcoffea_path(f"data/POG/MUO/{clib_year}/muon_Z.json.gz")
    )
    value = cset["NUM_LooseID_DEN_TrackerMuons"].evaluate(0.1, 30.0, "nominal")
    assert np.isfinite(value)


def test_btag_scale_factor_sample():
    """Ensure BTag CSV inputs load and evaluate for a representative point."""
    sf = BTagScaleFactor(
        topeft_path("data/btagSF/UL/wp_deepJet_106XUL18_v2.csv"),
        "MEDIUM",
    )
    value = sf.eval(
        "central", np.array([5]), np.array([0.3]), np.array([50.0])
    )[0]
    assert np.isfinite(value)
