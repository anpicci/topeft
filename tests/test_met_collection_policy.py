from pathlib import Path
from types import SimpleNamespace

import pytest

from topeft.modules.corrections import (
    ApplyMETSystematics,
    get_corr_t1_met_jets,
    get_selected_met,
    get_selected_raw_met,
    get_supported_met_systematics,
    is_met_unclustered_systematic,
    use_run3_type1_met,
)


def test_run2_selected_met_uses_legacy_met():
    events = SimpleNamespace(MET=object(), PuppiMET=object())

    assert get_selected_met(events, "2018") is events.MET


def test_run3_selected_met_uses_puppimet():
    events = SimpleNamespace(MET=object(), PuppiMET=object())

    assert get_selected_met(events, "2022") is events.PuppiMET


def test_run3_selected_met_missing_puppimet_fails_clearly():
    events = SimpleNamespace(MET=object())

    with pytest.raises(RuntimeError, match="requires events.PuppiMET"):
        get_selected_met(events, "2022")


def test_run3_type1_raw_met_policy_uses_raw_puppimet():
    events = SimpleNamespace(MET=object(), PuppiMET=object(), RawPuppiMET=object())

    assert use_run3_type1_met("2022")
    assert get_selected_met(events, "2022") is events.PuppiMET
    assert get_selected_raw_met(events, "2022") is events.RawPuppiMET


def test_run2_type1_policy_is_disabled_and_legacy_met_is_unchanged():
    events = SimpleNamespace(MET=object(), RawPuppiMET=object(), PuppiMET=object())

    assert not use_run3_type1_met("2018")
    assert get_selected_met(events, "2018") is events.MET
    assert get_selected_raw_met(events, "2018") is events.MET


def test_run3_type1_requires_corr_t1_met_jet_collection():
    corr_t1 = object()
    events = SimpleNamespace(CorrT1METJet=corr_t1)

    assert get_corr_t1_met_jets(events, "2022") is corr_t1
    assert get_corr_t1_met_jets(events, "2018") is None

    with pytest.raises(RuntimeError, match="requires events.CorrT1METJet"):
        get_corr_t1_met_jets(SimpleNamespace(), "2022")


def test_met_unclustered_systematics_are_public_generic_labels():
    assert get_supported_met_systematics("2022", isData=False) == [
        "MET_UnclusteredEnergyUp",
        "MET_UnclusteredEnergyDown",
    ]
    assert get_supported_met_systematics("2022", isData=True) == []
    assert is_met_unclustered_systematic("MET_UnclusteredEnergyUp")
    assert is_met_unclustered_systematic("MET_UnclusteredEnergyDown")
    assert not is_met_unclustered_systematic("JER_2022Up")


def test_apply_met_systematics_selects_unclustered_shift_only():
    nominal = object()
    up = object()
    down = object()
    met = SimpleNamespace(
        MET_UnclusteredEnergy=SimpleNamespace(up=up, down=down)
    )

    assert ApplyMETSystematics(met, "nominal") is met
    assert ApplyMETSystematics(met, "MET_UnclusteredEnergyUp") is up
    assert ApplyMETSystematics(met, "MET_UnclusteredEnergyDown") is down
    assert ApplyMETSystematics(nominal, "JER_2022Up") is nominal


def test_apply_met_systematics_selects_type1_jet_variations_when_present():
    nominal = object()
    jer_up = object()
    jer_down = object()
    jes_up = object()
    jes_down = object()
    met = SimpleNamespace(
        JER=SimpleNamespace(up=jer_up, down=jer_down),
        JES_Total=SimpleNamespace(up=jes_up, down=jes_down),
    )

    assert ApplyMETSystematics(met, "nominal") is met
    assert ApplyMETSystematics(met, "JER_2022Up") is jer_up
    assert ApplyMETSystematics(met, "JER_2022Down") is jer_down
    assert ApplyMETSystematics(met, "JES_TotalUp") is jes_up
    assert ApplyMETSystematics(met, "JES_TotalDown") is jes_down
    assert ApplyMETSystematics(nominal, "JES_TotalUp") is nominal


def test_processor_keeps_public_met_and_lt_semantics():
    processor_source = (
        Path(__file__).parents[1]
        / "analysis"
        / "topeft_run2"
        / "analysis_processor.py"
    ).read_text()

    assert "type1_met = ApplyJetCorrections(" in processor_source
    assert "corr_type='type1_met'" in processor_source
    assert "met = ApplyMETSystematics(type1_met, syst_var)" in processor_source
    assert "lt = ak.sum(l_fo_conept_sorted_padded.pt, axis=-1) + met.pt" in processor_source
    assert 'varnames["met"]     = met.pt' in processor_source
