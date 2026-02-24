from types import SimpleNamespace
import hist
import pytest

from analysis.topeft_run2 import make_cr_and_sr_plots


def _make_channel_hist(channels):
    histogram = hist.Hist(
        hist.axis.StrCategory(channels, name="channel"),
        hist.axis.Regular(1, 0.0, 1.0, name="observable"),
        storage=hist.storage.Double(),
    )
    for channel in channels:
        histogram.fill(channel=channel, observable=0.5, weight=1.0)
    return histogram


def test_global_channel_coverage_reports_variable_level_mismatch():
    histo = _make_channel_hist(["2lss_p_4j", "3l_p_offZ_1b_2j"])

    with pytest.raises(ValueError) as exc_info:
        make_cr_and_sr_plots.validate_variable_channel_coverage(
            [histo],
            {"2lss_p_4j"},
            [],
            region="SR",
            variable="lj0pt",
            region_dict_name="SR_CHAN_DICT",
        )

    msg = str(exc_info.value)
    assert "Global channel coverage mismatch" in msg
    assert "variable 'lj0pt'" in msg
    assert "3l_p_offZ_1b_2j" in msg
    assert "subgroup" not in msg.lower()


def test_subgroup_validation_ignores_unrelated_axis_channels_when_scoped():
    histo = _make_channel_hist(["2lss_4t_p_5j", "3l_p_offZ_1b_2j"])

    make_cr_and_sr_plots.validate_variable_channel_coverage(
        [histo],
        {"2lss_4t_p_5j", "3l_p_offZ_1b_2j"},
        [],
        region="SR",
        variable="lj0pt",
        region_dict_name="SR_CHAN_DICT",
    )

    # Subgroup validation receives subgroup-local channels only.
    make_cr_and_sr_plots.validate_channel_group(
        [histo],
        ["2lss_4t_p_5j"],
        [],
        region="SR",
        subgroup="2lss_4t_p_5j",
        variable="lj0pt",
        available_channels=["2lss_4t_p_5j"],
    )


def test_subgroup_validation_message_lists_only_subgroup_local_channels():
    histo = _make_channel_hist(["2lss_4t_p_5j", "3l_p_offZ_1b_2j"])

    with pytest.raises(ValueError) as exc_info:
        make_cr_and_sr_plots.validate_channel_group(
            [histo],
            ["2lss_4t_p_5j"],
            [],
            region="SR",
            subgroup="2lss_4t_p_5j",
            variable="lj0pt",
            available_channels=["2lss_4t_p_5j_alias"],
        )

    msg = str(exc_info.value)
    assert "Subgroup '2lss_4t_p_5j'" in msg
    assert "2lss_4t_p_5j_alias" in msg
    assert "3l_p_offZ_1b_2j" not in msg


def test_subgroup_validation_requires_explicit_available_channels():
    histo = _make_channel_hist(["2lss_4t_p_5j"])

    with pytest.raises(TypeError):
        make_cr_and_sr_plots.validate_channel_group(
            [histo],
            ["2lss_4t_p_5j"],
            [],
            region="SR",
            subgroup="2lss_4t_p_5j",
            variable="lj0pt",
        )


def test_global_validation_allows_sr_aggregated_channels_for_njets():
    histo = _make_channel_hist(["3l_p_offZ_1b", "3l_p_offZ_2b"])
    region_ctx = SimpleNamespace(name="SR")
    variable_payload = {
        "hist_mc": histo,
        "hist_data": None,
        "channel_transformations": ["njets"],
    }

    make_cr_and_sr_plots._ensure_variable_channel_coverage_validated(
        "njets", region_ctx, variable_payload
    )


def test_global_validation_remains_strict_for_non_njets_variables():
    histo = _make_channel_hist(["definitely_missing_channel_1j"])
    region_ctx = SimpleNamespace(name="SR")
    variable_payload = {
        "hist_mc": histo,
        "hist_data": None,
        "channel_transformations": [],
    }

    with pytest.raises(ValueError) as exc_info:
        make_cr_and_sr_plots._ensure_variable_channel_coverage_validated(
            "lj0pt", region_ctx, variable_payload
        )

    msg = str(exc_info.value)
    assert "variable 'lj0pt'" in msg
    assert "definitely_missing_channel_1j" in msg
