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

    fitting = DatacardMaker.fitting_view(
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


def test_wc_selection_uses_fitting_bins_instead_of_fine_processing_bins():
    source = _signal_histogram()
    source.fill(
        process="ttH",
        channel=CHANNEL,
        systematic="nominal",
        lj0pt=np.array([25.0, 75.0]),
        eft_coeff=np.array([[1.0, 10.0, 0.0], [1.0, -10.0, 0.0]]),
    )
    maker = DatacardMaker.__new__(DatacardMaker)
    maker.hists = {"lj0pt": source}
    maker.coeffs = []
    maker.tolerance = 1.0e-4
    maker.verbose = False

    selected = maker.get_selected_wcs("lj0pt", [CHANNEL])

    # Either 50-GeV source bin alone would select ctG. Their exact fitting-bin
    # sum cancels, proving the decision observes the card-facing view.
    assert selected["ttH"] == set()
