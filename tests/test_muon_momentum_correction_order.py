from pathlib import Path

import awkward as ak
import pytest

from topeft.modules import corrections


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


def test_run2_dispatch_preserves_rochester_path(monkeypatch):
    calls = []

    def _fake_rochester(year, muons, is_data):
        calls.append((year, is_data))
        return muons.pt + 0.5

    monkeypatch.setattr(
        corrections, "ApplyRochesterCorrections", _fake_rochester
    )

    corrected = corrections.apply_muon_momentum_corrections(
        "2018", _muons(), False
    )

    assert calls == [("2018", False)]
    assert ak.to_list(corrected) == [[10.0]]


def test_run3_does_not_silently_return_identity_without_payload():
    with pytest.raises(RuntimeError, match="correction_set or payload_directory"):
        corrections.apply_muon_momentum_corrections(
            "2022",
            _muons(),
            False,
            event_numbers=ak.Array([1]),
            luminosity_blocks=ak.Array([2]),
        )


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
def test_muon_object_systematics_are_not_activated_without_rebuild(
    processor_name,
):
    source = _processor_source(processor_name)

    assert "MuonScaleUp" not in source
    assert "MuonScaleDown" not in source
    assert "MuonResolutionUp" not in source
    assert "MuonResolutionDown" not in source
