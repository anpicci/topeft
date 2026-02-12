"""Plot comparison figures for flip application-region histograms.

Purpose:
Load tuple-keyed histogram output and produce per-variable comparison plots for
the ``ssz`` and ``osz`` channels used in the flip application workflow.

Inputs/outputs:
- Input: a pickle/gzip histogram artifact produced by the flip workflow.
- Output: PNG image files saved under ``--outpath``.

Side effects:
- Reads histogram files from disk.
- Creates output directories/files and writes plot images.

How to run:
- ``python analysis/flip_measurement/flip_ar_plotter.py histos/flipTopEFT.pkl.gz``
- ``python analysis/flip_measurement/flip_ar_plotter.py histos/flipTopEFT.pkl.gz --outpath plots/flip_ar``
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, MutableMapping

import argparse

import matplotlib.pyplot as plt
import hist

from .plot_utils import (
    TupleHistogramEntry,
    load_tuple_histogram_entries,
    summarise_by_variable,
)


def load_histograms(path: str) -> Iterable[TupleHistogramEntry]:
    return load_tuple_histogram_entries(path)


def group_by_variable(
    entries: Iterable[TupleHistogramEntry],
) -> MutableMapping[str, MutableMapping[str, MutableMapping[str, hist.Hist]]]:
    grouped = summarise_by_variable(entries, systematic="nominal", application=None)
    channel_grouped: MutableMapping[str, MutableMapping[str, MutableMapping[str, hist.Hist]]] = {}
    for variable, application_map in grouped.items():
        ordered_applications = sorted(application_map.keys(), key=lambda name: (name == ""))

        sample_histograms: MutableMapping[str, MutableMapping[str, hist.Hist]] = {}
        for application in ordered_applications:
            for sample, channel_map in application_map.get(application, {}).items():
                sample_label = f"{sample} ({application})" if application else sample
                merged_channels = sample_histograms.setdefault(sample_label, {})
                for channel, histogram in channel_map.items():
                    merged_channels.setdefault(channel, histogram)

        if sample_histograms:
            channel_grouped[variable] = sample_histograms
    return channel_grouped


def make_fig(
    histo1: hist.Hist,
    label1: str,
    histo2: hist.Hist | None = None,
    label2: str | None = None,
    hup: hist.Hist | None = None,
    hdo: hist.Hist | None = None,
) -> plt.Figure:
    fig, ax = plt.subplots(1, 1, figsize=(7, 7))

    if hup is not None and hdo is not None:
        hup.plot1d(ax=ax, stack=False, line_opts={"color": "lightgrey"})
        hdo.plot1d(ax=ax, stack=False, line_opts={"color": "lightgrey"})

    histo1.plot1d(ax=ax, stack=False, label=label1)
    if histo2 is not None:
        histo2.plot1d(ax=ax, stack=False, label=label2)

    ax.autoscale(axis="y")
    handles, labels = ax.get_legend_handles_labels()
    if labels:
        ax.legend(handles, labels)
    return fig


def build_channel_label(sample: str, channel: str) -> str:
    channel_label = channel.replace("_", " ") if channel else channel
    return f"{sample} ({channel_label})" if channel_label else sample


def main() -> None:
    from topeft.modules.logging_config import configure_topeft_logging
    configure_topeft_logging("INFO")

    parser = argparse.ArgumentParser(
        description="Plot ssz/osz comparisons from flip application-region histograms."
    )
    parser.add_argument(
        "filepath",
        default="histos/flipTopEFT.pkl.gz",
        help="Path to the histogram pickle produced by the flip workflow",
    )
    parser.add_argument("--outpath", "-o", default=".", help="Directory where plot images are written")
    args = parser.parse_args()

    tuple_histograms = load_histograms(args.filepath)
    grouped = group_by_variable(tuple_histograms)

    outpath = Path(args.outpath)
    outpath.mkdir(parents=True, exist_ok=True)

    for variable, sample_map in grouped.items():
        print(f"\nVariable: {variable}")
        for sample, channel_map in sample_map.items():
            ssz_hist = channel_map.get("ssz")
            osz_hist = channel_map.get("osz")
            if ssz_hist is None or osz_hist is None:
                print(f"  Missing channel histograms for sample {sample}, skipping")
                continue

            print(f"  sample_name {sample}")

            ssz_plot = ssz_hist.copy()
            osz_plot = osz_hist.copy()

            ssz_label = build_channel_label(sample, "ssz")
            osz_label = build_channel_label(sample, "osz")

            h_up = osz_plot.copy()
            h_up *= 1.3
            h_do = osz_plot.copy()
            h_do *= 0.7

            fig = make_fig(
                ssz_plot,
                ssz_label,
                histo2=osz_plot,
                label2=osz_label,
                hup=h_up,
                hdo=h_do,
            )
            savename = outpath / f"{sample}_{variable}.png"
            fig.savefig(savename)
            plt.close(fig)


if __name__ == "__main__":
    main()
