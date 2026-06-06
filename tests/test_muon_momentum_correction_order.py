from pathlib import Path

import awkward as ak
import numpy as np
import pytest

from topeft.modules import corrections

_RUN3_VARIATIONS = [
    "MuonScaleUp",
    "MuonScaleDown",
    "MuonResolutionUp",
    "MuonResolutionDown",
]


class _ThresholdSelection:
    def coneptMuon(self, muons):
        return muons.pt

    def isPresMuon(self, muons):
        return muons.pt > 10.0


def _muons(pt=9.5):
    return ak.Array(
        [
            [
                {
                    "pt": pt,
                    "eta": 0.2,
                    "phi": 0.1,
                    "charge": 1,
                    "nTrackerLayers": 12,
                }
            ]
        ]
    )


def _run3_muons():
    return ak.Array(
        [
            [
                {
                    "pt": 30.0,
                    "eta": 0.2,
                    "phi": 0.1,
                    "charge": 1,
                    "nTrackerLayers": 12,
                },
                {
                    "pt": 45.0,
                    "eta": -1.1,
                    "phi": -0.4,
                    "charge": -1,
                    "nTrackerLayers": 14,
                },
            ],
            [],
            [
                {
                    "pt": 60.0,
                    "eta": 1.3,
                    "phi": 2.0,
                    "charge": 1,
                    "nTrackerLayers": 10,
                }
            ],
        ]
    )


def _assert_finite_run3_shape(corrected):
    assert ak.to_list(ak.num(corrected)) == [2, 0, 1]
    assert np.all(np.isfinite(ak.to_numpy(ak.flatten(corrected))))


def _processor_source(name):
    repo = Path(__file__).resolve().parents[1]
    return (repo / "analysis" / "topeft_run2" / name).read_text()


def test_corrected_pt_is_used_for_conept_and_selection_threshold():
    muons = _muons()
    prepared = ak.with_field(muons, muons.pt, "pt_raw")
    prepared = ak.with_field(prepared, muons.pt + 1.0, "pt")
    prepared = ak.with_field(
        prepared, _ThresholdSelection().coneptMuon(prepared), "conept"
    )

    assert ak.to_list(prepared.pt_raw) == [[9.5]]
    assert ak.to_list(prepared.pt) == [[10.5]]
    assert ak.to_list(prepared.conept) == [[10.5]]
    assert ak.to_list(_ThresholdSelection().isPresMuon(prepared)) == [[True]]


@pytest.mark.parametrize("year", ["2016APV", "2016", "2017", "2018"])
def test_run2_dispatch_preserves_rochester_path(monkeypatch, year):
    calls = []

    def _fake_rochester(year, muons, is_data):
        calls.append((year, is_data))
        return muons.pt + 0.5

    monkeypatch.setattr(
        corrections, "ApplyRochesterCorrections", _fake_rochester
    )

    corrected = corrections.apply_muon_momentum_corrections(
        year, _muons(), False
    )

    assert calls == [(year, False)]
    assert ak.to_list(corrected) == [[10.0]]


@pytest.mark.parametrize("year", ["2022", "2022EE", "2023", "2023BPix"])
def test_run3_nominal_data_uses_default_backend_and_payload(year):
    corrected = corrections.apply_muon_momentum_corrections(
        year,
        _run3_muons(),
        True,
    )

    _assert_finite_run3_shape(corrected)


@pytest.mark.parametrize("year", ["2022", "2022EE", "2023", "2023BPix"])
def test_run3_nominal_mc_uses_default_backend_and_payload(year):
    muons = _run3_muons()
    data_corrected = corrections.apply_muon_momentum_corrections(
        year,
        muons,
        True,
    )
    corrected = corrections.apply_muon_momentum_corrections(
        year,
        muons,
        False,
        event_numbers=ak.Array([1001, 1002, 1003]),
        luminosity_blocks=ak.Array([11, 12, 13]),
    )

    _assert_finite_run3_shape(corrected)
    assert not np.allclose(
        ak.to_numpy(ak.flatten(data_corrected)),
        ak.to_numpy(ak.flatten(corrected)),
    )


@pytest.mark.parametrize("variation", _RUN3_VARIATIONS)
def test_run3_mc_variations_use_default_backend_and_payload(variation):
    corrected = corrections.apply_muon_momentum_corrections(
        "2022",
        _run3_muons(),
        False,
        event_numbers=ak.Array([1001, 1002, 1003]),
        luminosity_blocks=ak.Array([11, 12, 13]),
        variation=variation,
    )

    _assert_finite_run3_shape(corrected)


@pytest.mark.parametrize("variation", _RUN3_VARIATIONS)
def test_run3_data_rejects_muon_momentum_variations(variation):
    with pytest.raises(ValueError, match="not applicable to data"):
        corrections.apply_muon_momentum_corrections(
            "2022",
            _run3_muons(),
            True,
            variation=variation,
        )


@pytest.mark.parametrize("variation", _RUN3_VARIATIONS)
def test_run2_variation_requests_remain_unsupported(variation):
    with pytest.raises(ValueError, match="Run 2 Rochester.*does not support"):
        corrections.apply_muon_momentum_corrections(
            "2018",
            _muons(),
            False,
            variation=variation,
        )


def test_run3_mc_requires_event_and_lumi_inputs():
    with pytest.raises(ValueError, match="event_numbers and luminosity_blocks"):
        corrections.apply_muon_momentum_corrections(
            "2022",
            _run3_muons(),
            False,
        )


def test_unsupported_year_fails_loudly():
    with pytest.raises(ValueError, match="Unsupported Run 3.*2024"):
        corrections.apply_muon_momentum_corrections(
            "2024",
            _run3_muons(),
            True,
        )


def test_muon_momentum_systematic_list_is_run3_mc_only():
    assert corrections.RUN3_MUON_MOMENTUM_SYSTEMATICS == tuple(_RUN3_VARIATIONS)
    assert (
        corrections.get_supported_muon_momentum_systematics("2022", isData=False)
        == _RUN3_VARIATIONS
    )
    assert corrections.get_supported_muon_momentum_systematics("2022", isData=True) == []
    assert corrections.get_supported_muon_momentum_systematics("2018", isData=False) == []


@pytest.mark.parametrize(
    "processor_name",
    ["analysis_processor.py", "analysis_processor_diboson.py"],
)
def test_processors_prepare_corrected_muons_before_selection(processor_name):
    source = _processor_source(processor_name)

    correction = source.index(
        "corrected_muon_pt = apply_muon_momentum_corrections"
    )
    preserve_raw = source.index('mu["pt_raw"] = mu.pt')
    install_corrected_pt = source.index('mu["pt"] = corrected_muon_pt')
    compute_conept = source.index(
        'mu["conept"] = leptonSelection.coneptMuon(mu)'
    )
    selection = source.index('mu["isPres"] = leptonSelection.isPresMuon(mu)')

    assert correction < preserve_raw < install_corrected_pt
    assert install_corrected_pt < compute_conept < selection
    removed_helper = "prepare_" + "muons_for_selection"
    assert removed_helper not in source


@pytest.mark.parametrize(
    "processor_name",
    ["analysis_processor.py", "analysis_processor_diboson.py"],
)
def test_processors_rebuild_muon_objects_for_muon_systematics(processor_name):
    source = _processor_source(processor_name)

    activation = source.index("get_supported_muon_momentum_systematics")
    syst_loop = source.index("for syst_var in syst_var_list:")
    rebuild = source.index("if is_muon_momentum_systematic(syst_var):")
    jet_cleaning = source.index("tmp = ak.cartesian", rebuild)
    event_leptons = source.index(
        'events["l_fo_conept_sorted"] = l_fo_conept_sorted_for_syst',
        rebuild,
    )
    event_selection = source.index("te_es.add", event_leptons)

    assert activation < syst_loop < rebuild < jet_cleaning < event_leptons
    assert event_leptons < event_selection

    for snippet in [
        'varied_mu = ak.with_field(mu, mu.pt_raw, "pt")',
        "varied_corrected_muon_pt = apply_muon_momentum_corrections",
        "variation=syst_var",
        'varied_mu["pt_raw"] = varied_mu.pt',
        'varied_mu["pt"] = varied_corrected_muon_pt',
        'varied_mu["conept"] = leptonSelection.coneptMuon(varied_mu)',
        'varied_mu["isPres"] = leptonSelection.isPresMuon(varied_mu)',
        'varied_mu["isLooseM"] = leptonSelection.isLooseMuon(varied_mu)',
        'varied_mu["isFO"] = leptonSelection.isFOMuon(varied_mu, year)',
        'varied_mu["isTightLep"]= leptonSelection.tightSelMuon(varied_mu)',
        "m_loose_for_syst = varied_mu",
        "l_loose_for_syst = ak.with_name",
        "min_mll_afas_for_syst = ak.min",
        "m_fo_for_syst = varied_mu",
        "AttachMuonSF(m_fo_for_syst",
        "AttachPerLeptonFR(m_fo_for_syst",
        "l_fo_for_syst = ak.with_name",
        "l_fo_conept_sorted_for_syst =",
    ]:
        assert source.index(snippet, rebuild) < event_selection

    local_leptons = source.index(
        "l_fo_conept_sorted_padded = ak.pad_none(l_fo_conept_sorted_for_syst",
        event_leptons,
    )
    assert event_leptons < local_leptons

    rebuild_block = source[rebuild:jet_cleaning]
    assert "ApplyMETSystematics" not in rebuild_block
    assert "get_selected_met" not in rebuild_block
