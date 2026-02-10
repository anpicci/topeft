#!/usr/bin/env python
# coding: utf-8

"""Intro to modern histogram usage with ``hist`` and ``mplhep``.

This training script replaces the legacy Coffea histogram tutorial and focuses
on the APIs used by the current topeft/topcoffea stack.
"""

from __future__ import annotations

import gzip
import os
import pickle

import hist
import matplotlib.pyplot as plt
import mplhep as hep
import numpy as np


def demo_histograms() -> None:
    # 1D categorical + dense axis histogram
    hist_1d = hist.Hist(
        hist.axis.StrCategory([], name="soda", growth=True),
        hist.axis.Regular(20, -5, 5, name="x", label="x coordinate [m]"),
        storage=hist.storage.Double(),
    )
    hist_1d.fill(soda="cocacola", x=np.random.normal(size=10))
    hist_1d.fill(soda="pepsi", x=np.random.normal(size=10), weight=np.ones(10) * 5)

    fig, ax = plt.subplots(1, 1, figsize=(7, 5))
    hep.histplot(hist_1d, stack=True, ax=ax)
    ax.set_title("1D stacked example")
    fig.tight_layout()

    # 2D histogram and explicit 2D plotting
    hist_2d = hist.Hist(
        hist.axis.StrCategory([], name="species", growth=True),
        hist.axis.Regular(10, -5, 5, name="x", label="x coordinate [m]"),
        hist.axis.Regular(10, -5, 5, name="y", label="y coordinate [m]"),
        storage=hist.storage.Double(),
    )
    hist_2d.fill(
        species="ducks",
        x=np.random.normal(size=10),
        y=np.random.normal(size=10),
        weight=np.ones(10) * 3,
    )
    hist_2d.fill(
        species="phoenix",
        x=np.random.normal(size=8),
        y=np.random.normal(size=8),
        weight=np.ones(8) * 9,
    )

    fig2, ax2 = plt.subplots(1, 1, figsize=(7, 5))
    hep.hist2dplot(hist_2d[{"species": sum}], xaxis="x", ax=ax2)
    ax2.set_title("2D example")
    fig2.tight_layout()


def demo_loading_pickle(path: str) -> None:
    if not os.path.exists(path):
        print(f"Skipping pickle demo; file not found: {path}")
        return
    with gzip.open(path, "rb") as fin:
        payload = pickle.load(fin)
    print(f"Loaded {len(payload)} histogram entries from {path}")


if __name__ == "__main__":
    demo_histograms()
    demo_loading_pickle("tutorialpkldir/all2017mcsigsamples_skipSR_2022sept13_topcoffeatutorial.pkl.gz")
