from __future__ import annotations

import hist
import pytest

from analysis.topeft_run2 import make_cards
from topcoffea.modules.sparseHist import SparseHist
from topeft.modules import datacard_tools
from topeft.modules import histogram_artifact
from topeft.modules import nominal_schema
from topeft.modules.sumw2_policy import SUMW2_PROVENANCE_SCHEMA_VERSION


def _make_hist(processes, dense_name, nbins=1, dense_hi=None, channel="ch1"):
    if dense_hi is None:
        dense_hi = float(nbins)
    fill_value = float(dense_hi) / (2.0 * float(nbins))
    h = SparseHist(
        hist.axis.StrCategory([], name="process", growth=True),
        hist.axis.StrCategory([], name="channel", growth=True),
        hist.axis.Regular(nbins, 0.0, float(dense_hi), name=dense_name),
        storage="Double",
    )
    for proc in processes:
        h.fill(process=proc, channel=channel, **{dense_name: fill_value}, weight=1.0)
    return h


def _make_payload(
    key,
    processes,
    *,
    with_sumw2=True,
    nbins=1,
    dense_hi=None,
    channel="ch1",
):
    payload = {
        key: _make_hist(
            processes, key, nbins=nbins, dense_hi=dense_hi, channel=channel
        )
    }
    if with_sumw2:
        sumw2_key = f"{key}_sumw2"
        payload[sumw2_key] = _make_hist(
            processes,
            sumw2_key,
            nbins=nbins,
            dense_hi=dense_hi,
            channel=channel,
        )
    return payload


def _make_schema_payload(family, process, channel):
    return {
        nominal_schema.scalar_nominal_key(family): _make_hist(
            [process], family, channel=channel
        ),
        nominal_schema.sumw2_key(family): _make_hist(
            [process], nominal_schema.sumw2_key(family), channel=channel
        ),
    }


def _make_provenance(families, *, dataset, process, warning=""):
    return {
        "schema_version": SUMW2_PROVENANCE_SCHEMA_VERSION,
        "source": "explicit",
        "requested_mode": "full_diagnostics",
        "resolved_mode": "full_diagnostics",
        "signal_sample_profile": "unrestricted",
        "normalized_rules": [],
        "runtime_histogram_families": list(families),
        "resolved_datasets": [dataset],
        "resolved_processes": [process],
        "resolved_targets": [
            {"dataset": dataset, "process": process, "family": family}
            for family in families
        ],
        "warnings": [warning] if warning else [],
    }


def test_merge_histogram_pkls_succeeds_for_disjoint_processes(monkeypatch):
    payloads = {
        "a.pkl.gz": _make_payload("met", ["proc_a"], channel="channel_a"),
        "b.pkl.gz": _make_payload("met", ["proc_b"], channel="channel_b"),
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


def test_merge_histogram_pkls_fails_on_dense_axis_edges_mismatch(monkeypatch):
    payloads = {
        "a.pkl.gz": _make_payload(
            "met", ["proc_a"], dense_hi=1.0, channel="channel_a"
        ),
        "b.pkl.gz": _make_payload(
            "met", ["proc_b"], dense_hi=2.0, channel="channel_b"
        ),
    }

    monkeypatch.setattr(datacard_tools, "get_hist_from_pkl", lambda path, allow_empty=False: payloads[path])

    with pytest.raises(ValueError, match="Dense-axis edges mismatch"):
        datacard_tools.load_and_merge_histogram_pkls(
            ["a.pkl.gz", "b.pkl.gz"],
            on_process_collision="allow",
        )


def test_merge_histogram_pkls_process_overlap_policy(monkeypatch):
    payloads = {
        "a.pkl.gz": _make_payload(
            "met", ["shared_proc"], channel="channel_a"
        ),
        "b.pkl.gz": _make_payload(
            "met", ["shared_proc"], channel="channel_b"
        ),
    }

    monkeypatch.setattr(datacard_tools, "get_hist_from_pkl", lambda path, allow_empty=False: payloads[path])

    with pytest.raises(RuntimeError) as exc_info:
        datacard_tools.load_and_merge_histogram_pkls(
            ["a.pkl.gz", "b.pkl.gz"],
            on_process_collision="error",
        )
    msg = str(exc_info.value)
    assert "Process-label overlap detected" in msg
    assert "--on-process-collision allow" in msg
    assert "--merge-only --on-process-collision warn" in msg

    merged, report = datacard_tools.load_and_merge_histogram_pkls(
        ["a.pkl.gz", "b.pkl.gz"],
        on_process_collision="allow",
    )
    assert "met" in merged
    assert report["num_process_collisions"] >= 1


def test_process_collision_allow_preserves_disjoint_channel_content(monkeypatch):
    payloads = {
        "a.pkl.gz": {
            "met": _make_hist(["shared_proc"], "met", channel="channel_a"),
            "met_sumw2": _make_hist(
                ["shared_proc"], "met_sumw2", channel="channel_a"
            ),
        },
        "b.pkl.gz": {
            "met": _make_hist(["shared_proc"], "met", channel="channel_b"),
            "met_sumw2": _make_hist(
                ["shared_proc"], "met_sumw2", channel="channel_b"
            ),
        },
    }
    monkeypatch.setattr(
        datacard_tools,
        "get_hist_from_pkl",
        lambda path, allow_empty=False: payloads[path],
    )

    merged, _report = datacard_tools.load_and_merge_histogram_pkls(
        ["a.pkl.gz", "b.pkl.gz"], on_process_collision="allow"
    )

    assert set(merged["met"].axes["channel"]) == {"channel_a", "channel_b"}


def test_duplicate_final_category_is_rejected_before_histogram_addition(monkeypatch):
    payloads = {
        "a.pkl.gz": _make_payload("met", ["proc_a"], channel="3l_onZ_2b_4j"),
        "b.pkl.gz": _make_payload("met", ["proc_b"], channel="3l_onZ_2b_4j"),
    }
    monkeypatch.setattr(
        datacard_tools,
        "get_hist_from_pkl",
        lambda path, allow_empty=False: payloads[path],
    )

    with pytest.raises(RuntimeError, match="Duplicate final jet-resolved category"):
        datacard_tools.load_and_merge_histogram_pkls(
            ["a.pkl.gz", "b.pkl.gz"], on_process_collision="allow"
        )


def test_legacy_cross_run_histogram_composition_is_rejected(monkeypatch):
    payloads = {
        "run2.pkl.gz": _make_payload(
            "met", ["backgroundUL18"], channel="2lss_m_4j"
        ),
        "run3.pkl.gz": _make_payload(
            "met", ["background2022"], channel="3l_onZ_2b_4j"
        ),
    }
    monkeypatch.setattr(
        datacard_tools,
        "get_hist_from_pkl",
        lambda path, allow_empty=False: payloads[path],
    )

    with pytest.raises(
        RuntimeError, match=r"Run 2 \+ Run 3 composition is unsupported"
    ):
        datacard_tools.load_and_merge_histogram_pkls(
            ["run2.pkl.gz", "run3.pkl.gz"], on_process_collision="allow"
        )


def test_split_family_provenance_composes_first_occurrence_ordered_union():
    mixed = ("njets", "lj0pt", "ptz", "ptz_wtau", "lt")
    sibling = ("njets", "lj0pt", "ptz", "lt")
    composed = histogram_artifact._compose_sumw2_storage_provenance(
        (
            _make_provenance(mixed, dataset="shared_dataset", process="shared_proc"),
            _make_provenance(
                sibling, dataset="shared_dataset", process="shared_proc"
            ),
        )
    )

    assert composed["runtime_histogram_families"] == list(mixed)
    assert [target["family"] for target in composed["resolved_targets"]] == [
        "njets",
        "lj0pt",
        "ptz",
        "ptz_wtau",
        "lt",
    ]
    assert histogram_artifact._ordered_family_union((mixed, sibling, mixed)) == list(mixed)


def test_split_family_provenance_preserves_policy_and_allocation_guards():
    first = _make_provenance(("njets",), dataset="dataset_a", process="process_a")
    incompatible = _make_provenance(
        ("njets",), dataset="dataset_b", process="process_b", warning="changed"
    )
    with pytest.raises(RuntimeError, match="policy-control field 'warnings'"):
        histogram_artifact._compose_sumw2_storage_provenance((first, incompatible))

    different_dataset = _make_provenance(
        ("njets",), dataset="dataset_b", process="process_a"
    )
    with pytest.raises(RuntimeError, match="identical source-level resolved_datasets"):
        histogram_artifact._compose_sumw2_storage_provenance(
            (first, different_dataset)
        )

    different_process = _make_provenance(
        ("njets",), dataset="dataset_a", process="process_b"
    )
    with pytest.raises(RuntimeError, match="identical source-level resolved_processes"):
        histogram_artifact._compose_sumw2_storage_provenance(
            (first, different_process)
        )


def test_sidecar_merge_composes_partial_content_manifests(monkeypatch):
    mixed = ("njets", "ptz_wtau")
    sibling = ("njets",)
    first_provenance = _make_provenance(
        mixed, dataset="shared_dataset", process="shared_proc"
    )
    second_provenance = _make_provenance(
        sibling, dataset="shared_dataset", process="shared_proc"
    )
    composed = histogram_artifact._compose_sumw2_storage_provenance(
        (first_provenance, second_provenance)
    )

    def sidecar(provenance):
        return {
            "artifact": {
                "artifact_kind": "processor_output",
                "nominal_container_schema_version": 2,
                "nominal_container_layout": "split_sibling_v1",
                "pkl_basename": f"{provenance['resolved_datasets'][0]}.pkl.gz",
                "pkl_sha256": provenance["resolved_datasets"][0],
            },
            "sumw2_storage_provenance": provenance,
            "sumw2_content_manifest": {
                "families": {
                    family: {
                        "dimensionality": 1,
                        "required_sumw2_processes": [provenance["resolved_processes"][0]],
                    }
                    for family in provenance["runtime_histogram_families"]
                }
            },
        }

    monkeypatch.setattr(
        histogram_artifact,
        "_compose_merged_contract_set",
        lambda sidecars: (composed, None, None, None),
    )
    report = histogram_artifact.merge_histogram_sidecars(
        (sidecar(first_provenance), sidecar(second_provenance))
    )

    assert report["sumw2_storage_provenance"]["runtime_histogram_families"] == list(
        mixed
    )
    assert sorted(report["required_sumw2_processes"]) == list(mixed)


def test_merge_nominal_mappings_validates_partial_inputs_and_complete_output():
    families = ("njets", "ptz_wtau")
    first = _make_schema_payload("njets", "shared_proc", "channel_a")
    second = _make_schema_payload("ptz_wtau", "shared_proc", "channel_b")

    merged = nominal_schema.merge_nominal_mappings(
        (first, second), runtime_families=families
    )

    assert tuple(merged) == (
        nominal_schema.scalar_nominal_key("njets"),
        nominal_schema.sumw2_key("njets"),
        nominal_schema.scalar_nominal_key("ptz_wtau"),
        nominal_schema.sumw2_key("ptz_wtau"),
    )
    nominal_schema.validate_nominal_mapping(
        merged, runtime_families=families
    )


def test_partial_input_validation_rejects_claimed_missing_or_malformed_family():
    missing_nominal = {
        nominal_schema.sumw2_key("njets"): _make_hist(
            ["proc"], nominal_schema.sumw2_key("njets")
        )
    }
    with pytest.raises(ValueError, match="orphan statistical companion"):
        nominal_schema.merge_nominal_mappings(
            (missing_nominal,), runtime_families=("njets", "ptz_wtau")
        )

    malformed = {
        nominal_schema.scalar_nominal_key("njets"): object(),
    }
    with pytest.raises(TypeError, match="must be an exact SparseHist"):
        nominal_schema.merge_nominal_mappings(
            (malformed,), runtime_families=("njets", "ptz_wtau")
        )


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


def test_make_cards_parser_default_process_collision_policy_is_error():
    parser = make_cards.build_arg_parser()
    args = parser.parse_args(["a.pkl.gz"])

    assert args.on_process_collision == "error"


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
