"""Smoke test for ApplyJetCorrections using the CLib path with savecorr enabled."""

import gzip
from pathlib import Path

import awkward as ak
import correctionlib.schemav2 as cs
import numpy as np

from topeft.modules.corrections import ApplyJetCorrections, clib_year_map, get_jerc_keys
from topcoffea.modules.paths import topcoffea_path


def _write_minimal_jerc(year: str = "2018", era: str = "A") -> Path:
    """Create a minimal correction set so CLib JEC loading succeeds during tests."""

    jme_year = clib_year_map[year]
    jet_algo, jec_tag, jec_levels, _, _ = get_jerc_keys(year, True, era)

    target_dir = Path(topcoffea_path(f"data/POG/JME/{jme_year}"))
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / "jet_jerc.json.gz"

    corrections = []
    jet_pt = cs.Variable(name="JetPt", type="real", description="jet pt")
    output = cs.Variable(name="weight", type="real")
    binning = cs.Binning(
        input="JetPt",
        edges=[0, 1e6],
        content=[1.0],
        flow="clamp",
        nodetype="binning",
    )

    for level in jec_levels:
        corrections.append(
            cs.Correction(
                name=f"{jec_tag}_{level}_{jet_algo}",
                inputs=[jet_pt],
                output=output,
                version=1,
                data=binning,
            )
        )

    cset = cs.CorrectionSet(schema_version=2, corrections=corrections)
    with gzip.open(target_path, "wt") as fout:
        fout.write(cset.model_dump_json(exclude_none=True))

    return target_path


def test_apply_jet_corrections_clib_savecorr(tmp_path):
    """Ensure CLib JEC application runs and preserves per-level outputs when requested."""

    _write_minimal_jerc()

    jets = ak.Array(
        {
            "pt": [[50.0, 30.0]],
            "eta": [[0.1, -1.5]],
            "phi": [[0.2, -0.5]],
            "mass": [[10.0, 5.0]],
            "area": [[0.5, 0.4]],
            "pt_raw": [[45.0, 28.0]],
            "mass_raw": [[8.0, 4.0]],
            "rho": [[20.0, 20.0]],
        }
    )

    factory = ApplyJetCorrections(
        year="2018", corr_type="jets", isData=True, era="A", useclib=True, savelevels=True
    )

    assert factory.jec_stack.use_clib is True
    assert getattr(factory.jec_stack, "savecorr", False) is True

    corrected = factory.build(jets, lazy_cache={})

    np.testing.assert_allclose(
        np.asarray(ak.flatten(corrected.pt, axis=None)),
        np.asarray(ak.flatten(jets.pt_raw, axis=None)),
    )
    assert "jet_energy_correction" in corrected.fields
