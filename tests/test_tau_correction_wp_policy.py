from pathlib import Path
from types import SimpleNamespace

import awkward as ak
import numpy as np
import pytest

import topeft.modules.corrections as corrections


class _RecordingCorrection:
    def __init__(self, name):
        self.name = name
        self.calls = []

    def evaluate(self, *args):
        self.calls.append(args)
        return np.ones(len(args[0]), dtype=np.float32)


class _RecordingEvaluator:
    def __init__(self):
        self.keys = []

    def __getitem__(self, key):
        self.keys.append(key)

        def evaluate(first, *args):
            return ak.ones_like(first, dtype=np.float32)

        return evaluate


def _tau_record(year, gen_part_flav):
    if year.startswith("201"):
        discriminator_fields = {
            "idDeepTau2017v2p1VSjet": 16,
            "idDeepTau2017v2p1VSe": 2,
            "idDeepTau2017v2p1VSmu": 8,
        }
    else:
        discriminator_fields = {
            "idDeepTau2018v2p5VSjet": 5,
            "idDeepTau2018v2p5VSe": 2,
            "idDeepTau2018v2p5VSmu": 4,
        }

    return ak.Array(
        [[
            {
                "pt": 35.0,
                "mass": 1.2,
                "eta": 0.5,
                "decayMode": 0,
                "genPartFlav": gen_part_flav,
                "isLoose": 1,
                "isMedium": 1,
                "iseTight": 1,
                "ismTight": 1,
                **discriminator_fields,
            }
        ]]
    )


@pytest.mark.parametrize(
    ("year", "vsjet_correction_name", "fake_sf_key"),
    [
        ("2018", "DeepTau2017v2p1VSjet", "TauFakeSF"),
        ("2022", "DeepTau2018v2p5VSjet", "TauFakeSF_Run3"),
    ],
)
def test_tau_pog_vsjet_payload_uses_aligned_medium_wp_and_fake_sf_stays_separate(
    monkeypatch,
    year,
    vsjet_correction_name,
    fake_sf_key,
):
    recording_corrections = {
        vsjet_correction_name: _RecordingCorrection(vsjet_correction_name),
        "DeepTau2018v2p5VSe": _RecordingCorrection("DeepTau2018v2p5VSe"),
    }
    monkeypatch.setattr(
        corrections.correctionlib,
        "CorrectionSet",
        SimpleNamespace(from_file=lambda path: recording_corrections),
    )
    recording_evaluator = _RecordingEvaluator()
    monkeypatch.setattr(corrections, "SFevaluator", recording_evaluator)

    corrections.AttachTauSF(
        {},
        _tau_record(year, gen_part_flav=5),
        year,
        vsJetWP=corrections.TAU_POG_VSJET_WP,
    )

    vsjet_calls = recording_corrections[vsjet_correction_name].calls
    assert vsjet_calls
    assert all(call[3] == "Medium" for call in vsjet_calls)
    assert fake_sf_key in recording_evaluator.keys


@pytest.mark.parametrize(
    ("year", "vsjet_correction_name", "fake_sf_key"),
    [
        ("2018", "DeepTau2017v2p1VSjet", "TauFakeSF"),
        ("2022", "DeepTau2018v2p5VSjet", "TauFakeSF_Run3"),
    ],
)
def test_jet_faking_tau_sf_keeps_its_dedicated_non_pog_payload(
    monkeypatch,
    year,
    vsjet_correction_name,
    fake_sf_key,
):
    recording_corrections = {
        vsjet_correction_name: _RecordingCorrection(vsjet_correction_name),
        "DeepTau2018v2p5VSe": _RecordingCorrection("DeepTau2018v2p5VSe"),
    }
    monkeypatch.setattr(
        corrections.correctionlib,
        "CorrectionSet",
        SimpleNamespace(from_file=lambda path: recording_corrections),
    )
    recording_evaluator = _RecordingEvaluator()
    monkeypatch.setattr(corrections, "SFevaluator", recording_evaluator)

    corrections.AttachTauSF(
        {},
        _tau_record(year, gen_part_flav=0),
        year,
        vsJetWP=corrections.TAU_POG_VSJET_WP,
    )

    assert fake_sf_key in recording_evaluator.keys


def test_processor_uses_one_aligned_tau_wp_for_run2_and_run3():
    processor_source = (
        Path(__file__).resolve().parents[1]
        / "analysis"
        / "topeft_run2"
        / "analysis_processor.py"
    ).read_text()

    assert corrections.TAU_POG_VSJET_WP == "Medium"
    assert "tau_T_tag = TAU_POG_VSJET_WP" in processor_source
    assert 'tau_T_tag = "Loose" if is_run2 else "Medium"' not in processor_source
