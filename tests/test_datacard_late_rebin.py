import hist
import numpy as np
import pytest

from topcoffea.modules.histEFT import HistEFT
from topeft.modules.axis_binning import (
    histogram_dense_edges,
    validate_matching_histogram_edges,
)
from topeft.modules.datacard_tools import DatacardMaker


CHANNEL = "3l_1tau_1b_2j"


def _signal_histogram(*, dense_axis=None):
    if dense_axis is None:
        dense_axis = hist.axis.Regular(12, 0, 600, name="lj0pt")
    return HistEFT(
        hist.axis.StrCategory([], name="process", growth=True),
        hist.axis.StrCategory([], name="channel", growth=True),
        hist.axis.StrCategory([], name="systematic", growth=True),
        dense_axis,
        wc_names=["ctG"],
        label="Events",
    )


def _maker_for_mode(mode, source):
    maker = DatacardMaker.__new__(DatacardMaker)
    maker.binning_mode = mode
    maker.hists = {"lj0pt": source}
    maker.coeffs = []
    maker.tolerance = 1.0e-4
    maker.verbose = False
    return maker


def test_datacard_fitting_view_preserves_eft_scaling_bin_correspondence():
    source = _signal_histogram()
    source.fill(
        process="ttH",
        channel=CHANNEL,
        systematic="nominal",
        lj0pt=np.array([25.0, 175.0, 275.0, 375.0]),
        eft_coeff=np.array(
            [
                [2.0, 1.0, 0.5],
                [3.0, -1.0, 1.0],
                [4.0, 2.0, 1.5],
                [5.0, -2.0, 2.0],
            ]
        ),
    )

    fitting = _maker_for_mode("fitting", source).binning_view(
        source.integrate("channel", [CHANNEL]), "lj0pt", CHANNEL
    )
    template = fitting.integrate("process", ["ttH"])
    scaling_hist = template.integrate("systematic", ["nominal"])

    validate_matching_histogram_edges(
        template, scaling_hist, context="synthetic datacard template/scaling"
    )
    assert np.array_equal(histogram_dense_edges(template), [0, 150, 250, 350])
    scalings = scaling_hist.make_scaling()
    # Four fitting bins are serialized after the underflow is removed: three
    # finite intervals plus the physical overflow bin.
    assert scalings.shape[-2] - 1 == 4


def test_physical_edges_reject_same_length_scaling_mismatch():
    template = _signal_histogram(
        dense_axis=hist.axis.Variable([0, 150, 250, 350], name="lj0pt")
    )
    scaling = _signal_histogram(
        dense_axis=hist.axis.Variable([0, 150, 300, 350], name="lj0pt")
    )
    with pytest.raises(ValueError, match="Physical dense-axis mismatch"):
        validate_matching_histogram_edges(
            template, scaling, context="same-length different-edge regression"
        )


@pytest.mark.parametrize(
    ("mode", "expected_selected"),
    (("processing", {"ctG"}), ("fitting", set())),
)
def test_wc_selection_uses_the_selected_card_view(mode, expected_selected):
    source = _signal_histogram()
    source.fill(
        process="ttH",
        channel=CHANNEL,
        systematic="nominal",
        lj0pt=np.array([25.0, 75.0]),
        eft_coeff=np.array([[1.0, 10.0, 0.0], [1.0, -10.0, 0.0]]),
    )
    maker = _maker_for_mode(mode, source)

    selected = maker.get_selected_wcs("lj0pt", [CHANNEL])

    # Either 50-GeV source bin alone selects ctG, while their fitting-bin sum
    # cancels. The decision must track the card-facing view in both modes.
    assert selected["ttH"] == expected_selected


def test_processing_view_uses_old_coarse_stored_axis_without_resolving_fitting():
    source = _signal_histogram(
        dense_axis=hist.axis.Variable([0, 150, 250, 500], name="lj0pt")
    )
    source.fill(
        process="ttH",
        channel=CHANNEL,
        systematic="nominal",
        lj0pt=np.array([25.0]),
        eft_coeff=np.array([[1.0, 0.0, 0.0]]),
    )
    channel_hist = source.integrate("channel", [CHANNEL])
    processing = _maker_for_mode("processing", source).binning_view(
        channel_hist, "lj0pt", CHANNEL
    )

    assert processing is channel_hist
    assert np.array_equal(histogram_dense_edges(processing), [0, 150, 250, 500])
    with pytest.raises(ValueError, match="not exactly representable"):
        _maker_for_mode("fitting", source).binning_view(
            channel_hist, "lj0pt", CHANNEL
        )


def test_selected_views_keep_sumw2_eft_and_scaling_payloads_aligned():
    source = _signal_histogram()
    sumw2 = _signal_histogram()
    source.fill(
        process="ttH",
        channel=CHANNEL,
        systematic="nominal",
        lj0pt=np.array([25.0, 75.0, 175.0]),
        eft_coeff=np.array([[2.0, 1.0, 0.5], [3.0, -1.0, 1.0], [4.0, 2.0, 1.5]]),
    )
    sumw2.fill(
        process="ttH",
        channel=CHANNEL,
        systematic="nominal",
        lj0pt=np.array([25.0, 75.0, 175.0]),
        eft_coeff=np.array([[5.0, 0.0, 0.0], [7.0, 0.0, 0.0], [11.0, 0.0, 0.0]]),
    )

    for mode, expected_edges, expected_scaling_bins in (
        ("processing", np.arange(0, 650, 50), 13),
        ("fitting", np.array([0, 150, 250, 350]), 4),
    ):
        maker = _maker_for_mode(mode, source)
        selected = maker.binning_view(
            source.integrate("channel", [CHANNEL]), "lj0pt", CHANNEL
        )
        selected_sumw2 = maker.binning_view(
            sumw2.integrate("channel", [CHANNEL]), "lj0pt", CHANNEL
        )
        validate_matching_histogram_edges(
            selected,
            selected_sumw2,
            context=f"synthetic {mode} nominal/sumw2",
        )
        assert np.array_equal(histogram_dense_edges(selected), expected_edges)
        payload = next(iter(selected.view(flow=True).values()))
        assert np.allclose(np.sum(payload, axis=0)[1:-1], [9.0, 2.0, 3.0])
        scalings = selected.integrate("process", ["ttH"]).integrate(
            "systematic", ["nominal"]
        ).make_scaling()
        assert scalings.shape[-2] - 1 == expected_scaling_bins
