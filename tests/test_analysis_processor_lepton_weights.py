import importlib
import sys
import types
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture(name="analysis_module")
def fixture_analysis_module(monkeypatch):
    from tests import test_flavor_split_histograms as flavor_split

    flavor_split._install_test_stubs(monkeypatch)
    return importlib.import_module("analysis.topeft_run2.analysis_processor")


@pytest.mark.parametrize(
    "channel_prefix,tau_enabled,expected",
    [
        (
            "1l",
            True,
            [
                ("lepSF_muon", "sf_1l_muon", "sf_1l_hi_muon", "sf_1l_lo_muon", True),
                ("lepSF_elec", "sf_1l_elec", "sf_1l_hi_elec", "sf_1l_lo_elec", False),
                (
                    "lepSF_taus_real",
                    "sf_2l_taus_real",
                    "sf_2l_taus_real_hi",
                    "sf_2l_taus_real_lo",
                    True,
                ),
                (
                    "lepSF_taus_fake",
                    "sf_2l_taus_fake",
                    "sf_2l_taus_fake_hi",
                    "sf_2l_taus_fake_lo",
                    False,
                ),
            ],
        ),
        (
            "2l",
            True,
            [
                ("lepSF_muon", "sf_2l_muon", "sf_2l_hi_muon", "sf_2l_lo_muon", True),
                ("lepSF_elec", "sf_2l_elec", "sf_2l_hi_elec", "sf_2l_lo_elec", False),
                (
                    "lepSF_taus_real",
                    "sf_2l_taus_real",
                    "sf_2l_taus_real_hi",
                    "sf_2l_taus_real_lo",
                    True,
                ),
                (
                    "lepSF_taus_fake",
                    "sf_2l_taus_fake",
                    "sf_2l_taus_fake_hi",
                    "sf_2l_taus_fake_lo",
                    False,
                ),
            ],
        ),
        (
            "3l",
            True,
            [
                ("lepSF_muon", "sf_3l_muon", "sf_3l_hi_muon", "sf_3l_lo_muon", True),
                ("lepSF_elec", "sf_3l_elec", "sf_3l_hi_elec", "sf_3l_lo_elec", False),
                (
                    "lepSF_taus_real",
                    "sf_2l_taus_real",
                    "sf_2l_taus_real_hi",
                    "sf_2l_taus_real_lo",
                    True,
                ),
                (
                    "lepSF_taus_fake",
                    "sf_2l_taus_fake",
                    "sf_2l_taus_fake_hi",
                    "sf_2l_taus_fake_lo",
                    False,
                ),
            ],
        ),
        (
            "4l",
            True,
            [
                ("lepSF_muon", "sf_4l_muon", "sf_4l_hi_muon", "sf_4l_lo_muon", True),
                ("lepSF_elec", "sf_4l_elec", "sf_4l_hi_elec", "sf_4l_lo_elec", False),
            ],
        ),
        (
            "1l",
            False,
            [
                ("lepSF_muon", "sf_1l_muon", "sf_1l_hi_muon", "sf_1l_lo_muon", True),
                ("lepSF_elec", "sf_1l_elec", "sf_1l_hi_elec", "sf_1l_lo_elec", False),
            ],
        ),
    ],
)
def test_register_channel_lepton_sf_weights(
    analysis_module, monkeypatch, channel_prefix, tau_enabled, expected
):
    calls = []

    def _fake_register(
        weights_object,
        events,
        label,
        central_attr,
        up_attr,
        down_attr,
        include_variations,
        *,
        variation_name,
        logger_obj,
    ):
        calls.append((label, central_attr, up_attr, down_attr, include_variations))

    monkeypatch.setattr(analysis_module, "register_lepton_sf_weight", _fake_register)

    processor = object.__new__(analysis_module.AnalysisProcessor)
    processor.tau_h_analysis = tau_enabled

    processor._register_channel_lepton_sf_weights(
        channel_prefix=channel_prefix,
        nlep_cat=f"{channel_prefix}_category",
        weights_object=types.SimpleNamespace(),
        events=types.SimpleNamespace(),
        include_muon_sf_variations=True,
        include_elec_sf_variations=False,
        include_tau_real_sf_variations=True,
        include_tau_fake_sf_variations=False,
        variation_name="nominal",
        logger_obj=types.SimpleNamespace(),
    )

    assert calls == expected



def test_register_channel_lepton_sf_weights_unknown_channel(
    analysis_module, monkeypatch
):
    monkeypatch.setattr(
        analysis_module, "register_lepton_sf_weight", lambda *args, **kwargs: None
    )

    processor = object.__new__(analysis_module.AnalysisProcessor)
    processor.tau_h_analysis = True

    with pytest.raises(Exception, match="Unknown channel name: 5l_category"):
        processor._register_channel_lepton_sf_weights(
            channel_prefix="5l",
            nlep_cat="5l_category",
            weights_object=types.SimpleNamespace(),
            events=types.SimpleNamespace(),
            include_muon_sf_variations=True,
            include_elec_sf_variations=False,
            include_tau_real_sf_variations=True,
            include_tau_fake_sf_variations=False,
            variation_name="nominal",
            logger_obj=types.SimpleNamespace(),
        )

