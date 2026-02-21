from __future__ import annotations

import hist
import pytest

from analysis.topeft_run2 import make_cards
from topcoffea.modules.sparseHist import SparseHist
from topeft.modules import datacard_tools


def _make_hist(processes, dense_name, nbins=1):
    h = SparseHist(
        hist.axis.StrCategory([], name="process", growth=True),
        hist.axis.StrCategory([], name="channel", growth=True),
        hist.axis.Regular(nbins, 0.0, float(nbins), name=dense_name),
        storage="Double",
    )
    for proc in processes:
        h.fill(process=proc, channel="ch1", **{dense_name: 0.5}, weight=1.0)
    return h


def _make_payload(key, processes, *, with_sumw2=True, nbins=1):
    payload = {key: _make_hist(processes, key, nbins=nbins)}
    if with_sumw2:
        sumw2_key = f"{key}_sumw2"
        payload[sumw2_key] = _make_hist(processes, sumw2_key, nbins=nbins)
    return payload


def test_merge_histogram_pkls_succeeds_for_disjoint_processes(monkeypatch):
    payloads = {
        "a.pkl.gz": _make_payload("met", ["proc_a"]),
        "b.pkl.gz": _make_payload("met", ["proc_b"]),
    }

    def fake_loader(path, allow_empty=False):
        assert allow_empty is False
        return payloads[path]

    monkeypatch.setattr(datacard_tools, "get_hist_from_pkl", fake_loader)

    merged, report = datacard_tools.load_and_merge_histogram_pkls(
        ["a.pkl.gz", "b.pkl.gz"],
        on_process_collision="error",
    )

    assert set(merged["met"].axes["process"]) == {"proc_a", "proc_b"}
    assert report["num_process_collisions"] == 0


def test_merge_histogram_pkls_fails_when_sumw2_missing(monkeypatch):
    payloads = {
        "broken.pkl.gz": _make_payload("met", ["proc_a"], with_sumw2=False),
    }

    monkeypatch.setattr(datacard_tools, "get_hist_from_pkl", lambda path, allow_empty=False: payloads[path])

    with pytest.raises(RuntimeError, match="missing required \\*_sumw2 companions"):
        datacard_tools.load_and_merge_histogram_pkls(["broken.pkl.gz"])


def test_merge_histogram_pkls_process_overlap_policy(monkeypatch):
    payloads = {
        "a.pkl.gz": _make_payload("met", ["shared_proc"]),
        "b.pkl.gz": _make_payload("met", ["shared_proc"]),
    }

    monkeypatch.setattr(datacard_tools, "get_hist_from_pkl", lambda path, allow_empty=False: payloads[path])

    with pytest.raises(RuntimeError, match="Process-label overlap detected"):
        datacard_tools.load_and_merge_histogram_pkls(
            ["a.pkl.gz", "b.pkl.gz"],
            on_process_collision="error",
        )

    merged, report = datacard_tools.load_and_merge_histogram_pkls(
        ["a.pkl.gz", "b.pkl.gz"],
        on_process_collision="allow",
    )
    assert "met" in merged
    assert report["num_process_collisions"] >= 1


def test_make_cards_parser_accepts_multiple_pkls():
    parser = make_cards.build_arg_parser()
    args = parser.parse_args(
        [
            "a.pkl.gz",
            "b.pkl.gz",
            "--on-process-collision",
            "warn",
            "--merge-only",
        ]
    )

    assert args.pkl_file == ["a.pkl.gz", "b.pkl.gz"]
    assert args.on_process_collision == "warn"
    assert args.merge_only is True


def test_resolve_pkl_paths_from_file(tmp_path):
    pkl_list = tmp_path / "pkls.txt"
    pkl_list.write_text(
        "\n".join(
            [
                "# comment line",
                "",
                "/tmp/a.pkl.gz",
                "/tmp/b.pkl.gz",
            ]
        )
        + "\n"
    )

    parser = make_cards.build_arg_parser()
    args = parser.parse_args(["--pkl-list-file", str(pkl_list)])
    resolved = make_cards._resolve_pkl_paths(args, parser)

    assert resolved == ["/tmp/a.pkl.gz", "/tmp/b.pkl.gz"]

