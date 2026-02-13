import subprocess
import sys
from pathlib import Path

import pytest

from analysis.topeft_run2 import analysis_processor


def _make_processor(**mode_kwargs):
    return analysis_processor.AnalysisProcessor(
        samples={},
        wc_names_lst=[],
        hist_lst=["njets"],
        fill_sumw2_hist=False,
        **mode_kwargs,
    )


def test_mode_flags_are_mutually_exclusive():
    with pytest.raises(ValueError, match="mutually exclusive"):
        _make_processor(offZ_split=True, tau_h_analysis=True)


@pytest.mark.parametrize(
    "mode_kwargs, expected",
    [
        ({}, ("default", False, False, False)),
        ({"offZ_split": True}, ("offz", True, False, False)),
        ({"tau_h_analysis": True}, ("tau", False, True, False)),
        ({"fwd_analysis": True}, ("fwd", False, False, True)),
        ({"all_analysis": True}, ("all", True, True, True)),
    ],
)
def test_mode_toggles_follow_truth_table(mode_kwargs, expected):
    proc = _make_processor(**mode_kwargs)
    mode_name, enable_offz, enable_tau, enable_fwd = expected
    assert proc._analysis_mode == mode_name
    assert proc.enable_offz_blocks is enable_offz
    assert proc.enable_tau_blocks is enable_tau
    assert proc.enable_fwd_blocks is enable_fwd


def test_all_mode_keeps_offz_split_ptz_histograms():
    proc = _make_processor(all_analysis=True)
    should_skip = proc._should_skip_histogram_fill(
        dense_axis_name="ptz",
        ch_name="3l_channel",
        lep_chan="3l_m_offZ_low_1b",
    )
    assert should_skip is False


def test_tau_mode_ptz_wtau_gating_is_strict():
    proc = _make_processor(tau_h_analysis=True)
    assert proc._should_skip_histogram_fill("ptz_wtau", "2l_channel", "2lss_p_1tau_onZ") is False
    assert proc._should_skip_histogram_fill("ptz_wtau", "2l_channel", "2lss_p_1tau_offZ") is True


def test_run_analysis_help_shows_canonical_mode_flags_only():
    script_path = (
        Path(__file__).resolve().parents[1] / "analysis" / "topeft_run2" / "run_analysis.py"
    )
    result = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    help_text = result.stdout

    assert "--offZ-3l-split" in help_text
    assert "--tau-h-analysis" in help_text
    assert "--offZ-split" not in help_text
    assert "--tau_h_analysis" not in help_text
