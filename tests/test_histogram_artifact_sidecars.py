from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path
import pickle

import hist
import numpy as np
import pytest

from analysis.topeft_run2 import make_cards, make_cr_and_sr_plots, run_data_driven
from topcoffea.modules.histEFT import HistEFT
from topcoffea.modules.sparseHist import SparseHist
from topcoffea.modules.utils import get_hist_from_pkl
from topeft.modules.axes import info as axes_info
from topeft.modules.axes import info_2d as axes_info_2d
from topeft.modules.datacard_tools import load_and_merge_histogram_pkls
from topeft.modules.dataDrivenEstimation import DataDrivenProducer
from topeft.modules.histogram_artifact import (
    histogram_artifact_error,
    lineage_input_from_sidecar,
    metadata_sidecar_path,
    read_histogram_sidecar,
    validate_histogram_artifact,
    write_histogram_artifact,
)
from topeft.modules import histogram_artifact
from topeft.modules.nominal_schema import (
    eft_nominal_key,
    evaluate_nominal_at_wc,
    materialize_legacy_histogram_dict,
    scalar_nominal_key,
)
from topeft.modules.sumw2_policy import resolve_sumw2_storage_policy


def _axes(dense_name):
    return (
        hist.axis.StrCategory([], name="process", growth=True),
        hist.axis.StrCategory([], name="channel", growth=True),
        hist.axis.StrCategory([], name="systematic", growth=True),
        hist.axis.StrCategory([], name="appl", growth=True),
        hist.axis.Regular(1, 0.0, 1.0, name=dense_name),
    )


def _fill_sparse(dense_name, entries):
    output = SparseHist(*_axes(dense_name), storage="Double")
    for process, appl, weight in entries:
        output.fill(
            process=process,
            channel="3l",
            systematic="nominal",
            appl=appl,
            **{dense_name: np.asarray([0.5])},
            weight=np.asarray([weight]),
        )
    return output


def _fill_eft(entries):
    output = HistEFT(*_axes("njets"), wc_names=["ctG"], label="Events")
    for process, appl, weight in entries:
        output.fill(
            process=process,
            channel="3l",
            systematic="nominal",
            appl=appl,
            njets=np.asarray([0.5]),
            weight=np.asarray([weight]),
            eft_coeff=np.asarray([[1.25, 2.0, 3.0]]),
        )
    return output


@pytest.fixture
def policy():
    return resolve_sumw2_storage_policy(
        {"mode": "full_diagnostics"},
        samples={
            "data_dataset": {
                "histAxisName": "dataUL18",
                "isData": True,
                "WCnames": [],
            },
            "prompt_dataset": {
                "histAxisName": "TTTo2L2Nu_centralUL18",
                "isData": False,
                "WCnames": [],
            },
            "signal_dataset": {
                "histAxisName": "signal_centralUL18",
                "isData": False,
                "WCnames": ["ctG"],
            },
        },
        runtime_families=("njets",),
        axes_info=axes_info,
        axes_info_2d=axes_info_2d,
        sumw2_storage_present=True,
    )


def _processor_payload():
    scalar_entries = (
        ("dataUL18", "isAR_3l", 10.0),
        ("TTTo2L2Nu_centralUL18", "isAR_3l", 3.0),
        ("dataUL18", "isAR_2lSS_OS", 4.0),
        ("TTTo2L2Nu_centralUL18", "isSR_3l", 2.0),
    )
    companion_entries = (
        ("dataUL18", "isAR_3l", 100.0),
        ("TTTo2L2Nu_centralUL18", "isAR_3l", 9.0),
        ("dataUL18", "isAR_2lSS_OS", 16.0),
        ("TTTo2L2Nu_centralUL18", "isSR_3l", 4.0),
        ("signal_centralUL18", "isAR_3l", 81.0),
        ("signal_centralUL18", "isSR_3l", 25.0),
    )
    return {
        scalar_nominal_key("njets"): _fill_sparse("njets", scalar_entries),
        eft_nominal_key("njets"): _fill_eft(
            (
                ("signal_centralUL18", "isAR_3l", 9.0),
                ("signal_centralUL18", "isSR_3l", 5.0),
            )
        ),
        "njets_sumw2": _fill_sparse("njets_sumw2", companion_entries),
    }


def _write_processor(path, policy):
    return write_histogram_artifact(
        path,
        histograms=_processor_payload(),
        artifact_kind="processor_output",
        sumw2_storage_provenance=policy.to_provenance(),
    )


def _write_raw(path, payload):
    with gzip.open(path, "wb") as stream:
        pickle.dump(payload, stream, protocol=pickle.HIGHEST_PROTOCOL)


def _processes(histogram):
    return sorted(str(process) for process in histogram.axes["process"])


def test_metadata_sidecar_path_preserves_full_suffixes(tmp_path, monkeypatch):
    assert metadata_sidecar_path("output.pkl") == Path("output.pkl.metadata.json")
    assert metadata_sidecar_path("output.pkl.gz") == Path(
        "output.pkl.gz.metadata.json"
    )
    absolute = tmp_path / "nested" / "output.pkl.gz"
    assert metadata_sidecar_path(absolute) == Path(f"{absolute}.metadata.json")
    monkeypatch.chdir(tmp_path)
    assert metadata_sidecar_path(Path("relative.pkl")) == Path(
        "relative.pkl.metadata.json"
    )


def test_processor_artifact_is_automatic_self_describing_and_identity_bound(
    tmp_path, policy
):
    path = tmp_path / "processor.pkl.gz"
    sidecar = _write_processor(path, policy)
    assert path.is_file()
    assert metadata_sidecar_path(path).is_file()
    reopened = read_histogram_sidecar(path)
    assert reopened == sidecar
    assert sidecar["metadata_schema_version"] == 2
    assert sidecar["artifact"]["artifact_kind"] == "processor_output"
    assert sidecar["artifact"]["merged"] is False
    assert sidecar["artifact"]["pkl_basename"] == path.name
    assert sidecar["artifact"]["pkl_size_bytes"] == path.stat().st_size
    assert sidecar["lineage"] == {"inputs": []}
    family = sidecar["sumw2_content_manifest"]["families"]["njets"]
    assert family["scalar_nominal_processes"] == [
        "TTTo2L2Nu_centralUL18",
        "dataUL18",
    ]
    assert family["eft_nominal_processes"] == ["signal_centralUL18"]
    assert family["sumw2_processes"] == [
        "TTTo2L2Nu_centralUL18",
        "dataUL18",
        "signal_centralUL18",
    ]
    assert family["required_sumw2_processes"] == family["sumw2_processes"]
    assert validate_histogram_artifact(path)["metadata"] == sidecar


def test_atomic_pair_does_not_publish_pkl_when_sidecar_write_fails(
    tmp_path, policy, monkeypatch
):
    path = tmp_path / "failed.pkl.gz"

    def fail_sidecar_write(*_args, **_kwargs):
        raise OSError("synthetic metadata write failure")

    monkeypatch.setattr(histogram_artifact, "_write_json", fail_sidecar_write)
    with pytest.raises(OSError, match="metadata write failure"):
        write_histogram_artifact(
            path,
            histograms=_processor_payload(),
            artifact_kind="processor_output",
            sumw2_storage_provenance=policy.to_provenance(),
        )
    assert not path.exists()
    assert not metadata_sidecar_path(path).exists()


def test_schema_v2_missing_sidecar_error_is_actionable(tmp_path):
    path = tmp_path / "split.pkl.gz"
    _write_raw(path, _processor_payload())
    with pytest.raises(histogram_artifact_error) as error_info:
        validate_histogram_artifact(path)
    message = str(error_info.value)
    assert str(path) in message
    assert str(metadata_sidecar_path(path)) in message
    assert "detected_split_sibling_keys" in message
    assert "run_analysis" in message
    assert "run_data_driven" in message
    assert "merged-cache writer" in message
    assert "do not supply a sidecar path manually" in message


def test_nonprompt_persisted_flow_reopens_and_preserves_lineage(tmp_path, policy):
    input_path = tmp_path / "processor.pkl.gz"
    output_path = tmp_path / "nonprompt.pkl.gz"
    input_sidecar = _write_processor(input_path, policy)
    run_data_driven.main(
        [
            "--input-pkl",
            str(input_path),
            "--output-pkl",
            str(output_path),
            "--quiet",
        ]
    )
    output_sidecar = read_histogram_sidecar(output_path)
    assert output_sidecar["artifact"]["artifact_kind"] == "nonprompt_output"
    assert output_sidecar["sumw2_storage_provenance"] == input_sidecar[
        "sumw2_storage_provenance"
    ]
    assert output_sidecar["lineage"]["inputs"] == [
        lineage_input_from_sidecar(input_sidecar)
    ]
    merged, report = load_and_merge_histogram_pkls([str(output_path)])
    assert report["artifact_kind"] == "nonprompt_output"
    scalar_processes = _processes(merged[scalar_nominal_key("njets")])
    assert scalar_processes == [
        "TTTo2L2Nu_centralUL18",
        "flipsUL18",
        "nonpromptUL18",
    ]
    assert _processes(merged[eft_nominal_key("njets")]) == [
        "signal_centralUL18"
    ]
    assert _processes(merged["njets_sumw2"]) == [
        "TTTo2L2Nu_centralUL18",
        "flipsUL18",
        "nonpromptUL18",
        "signal_centralUL18",
    ]
    scalar_view = evaluate_nominal_at_wc(merged, "njets", {})
    assert "nonpromptUL18" in scalar_view.axes["process"]
    datacard_view = materialize_legacy_histogram_dict(
        merged,
        runtime_families=("njets",),
        require_companions=("njets",),
    )
    assert tuple(datacard_view) == ("njets", "njets_sumw2")


def test_direct_data_driven_writer_discovers_and_writes_sidecars(tmp_path, policy):
    input_path = tmp_path / "processor.pkl.gz"
    output_path = tmp_path / "direct_nonprompt.pkl.gz"
    _write_processor(input_path, policy)
    producer = DataDrivenProducer(
        str(input_path),
        str(output_path),
        iterator_mode=True,
    )
    producer.dumpToPickle()
    sidecar = read_histogram_sidecar(output_path)
    assert sidecar["artifact"]["artifact_kind"] == "nonprompt_output"
    merged, report = load_and_merge_histogram_pkls([str(output_path)])
    assert report["artifact_kind"] == "nonprompt_output"
    assert "nonpromptUL18" in merged[scalar_nominal_key("njets")].axes["process"]


def test_flips_persisted_flow_has_separate_stage_contract(tmp_path, policy):
    input_path = tmp_path / "processor.pkl.gz"
    output_path = tmp_path / "flips.pkl.gz"
    _write_processor(input_path, policy)
    run_data_driven.main(
        [
            "--input-pkl",
            str(input_path),
            "--output-pkl",
            str(output_path),
            "--only-flips",
            "--quiet",
        ]
    )
    sidecar = read_histogram_sidecar(output_path)
    assert sidecar["artifact"]["artifact_kind"] == "flips_output"
    merged, report = load_and_merge_histogram_pkls([str(output_path)])
    assert report["artifact_kind"] == "flips_output"
    assert _processes(merged[scalar_nominal_key("njets")]) == ["flipsUL18"]
    assert _processes(merged["njets_sumw2"]) == ["flipsUL18"]
    assert _processes(merged[eft_nominal_key("njets")]) == [
        "signal_centralUL18"
    ]
    assert sum(
        float(np.asarray(values).sum())
        for values in merged[eft_nominal_key("njets")].eval({}).values()
    ) == pytest.approx(6.25)
    family = sidecar["sumw2_content_manifest"]["families"]["njets"]
    assert family["sumw2_processes"] == ["flipsUL18"]
    assert family["required_sumw2_processes"] == ["flipsUL18"]
    scalar_view = evaluate_nominal_at_wc(merged, "njets", {})
    assert sorted(str(process) for process in scalar_view.axes["process"]) == [
        "flipsUL18",
        "signal_centralUL18",
    ]
    datacard_view = materialize_legacy_histogram_dict(
        merged,
        runtime_families=("njets",),
        require_companions=("njets",),
    )
    assert tuple(datacard_view) == ("njets", "njets_sumw2")


def _transformed_payload(artifact_kind):
    process = "flipsUL18" if artifact_kind == "flips_output" else "nonpromptUL18"
    return {
        scalar_nominal_key("njets"): _fill_sparse(
            "njets", ((process, "isSR_3l", 2.0),)
        ),
        "njets_sumw2": _fill_sparse(
            "njets_sumw2", ((process, "isSR_3l", 4.0),)
        ),
    }


@pytest.mark.parametrize(
    "artifact_kind",
    ["processor_output", "nonprompt_output", "flips_output"],
)
def test_compatible_stage_merges_regenerate_deterministic_sidecar(
    tmp_path, policy, artifact_kind
):
    source_path = tmp_path / f"{artifact_kind}_source.pkl.gz"
    source_sidecar = _write_processor(source_path, policy)
    paths = []
    for index in range(2):
        path = tmp_path / f"{artifact_kind}_{index}.pkl.gz"
        if artifact_kind == "processor_output":
            _write_processor(path, policy)
        else:
            write_histogram_artifact(
                path,
                histograms=_transformed_payload(artifact_kind),
                artifact_kind=artifact_kind,
                sumw2_storage_provenance=policy.to_provenance(),
                lineage_inputs=[lineage_input_from_sidecar(source_sidecar)],
            )
        paths.append(str(path))
    merged, report = load_and_merge_histogram_pkls(
        paths, on_process_collision="allow"
    )
    cached_path = make_cards._cache_merged_histograms(
        merged,
        f"merged_{artifact_kind}",
        str(tmp_path),
        report,
    )
    merged_sidecar = read_histogram_sidecar(cached_path)
    assert merged_sidecar["artifact"]["artifact_kind"] == artifact_kind
    assert merged_sidecar["artifact"]["merged"] is True
    assert len(merged_sidecar["lineage"]["inputs"]) == 2
    reopened, reopened_report = load_and_merge_histogram_pkls([cached_path])
    assert tuple(reopened) == tuple(merged)
    assert reopened_report["artifact_kind"] == artifact_kind


def test_plotting_merged_cache_writer_preserves_artifact_stage(tmp_path, policy):
    paths = []
    for index in range(2):
        path = tmp_path / f"plot_input_{index}.pkl.gz"
        _write_processor(path, policy)
        paths.append(str(path))
    merged, report = load_and_merge_histogram_pkls(
        paths, on_process_collision="allow"
    )
    cached_path = make_cr_and_sr_plots._cache_merged_histograms(
        merged,
        "plot_cache",
        str(tmp_path),
        report,
    )
    sidecar = read_histogram_sidecar(cached_path)
    assert sidecar["artifact"]["artifact_kind"] == "processor_output"
    assert sidecar["artifact"]["merged"] is True
    assert len(sidecar["lineage"]["inputs"]) == 2


def test_incompatible_artifact_stage_merges_are_rejected(tmp_path, policy):
    processor_path = tmp_path / "processor.pkl.gz"
    processor_sidecar = _write_processor(processor_path, policy)
    nonprompt_path = tmp_path / "nonprompt.pkl.gz"
    flips_path = tmp_path / "flips.pkl.gz"
    for path, artifact_kind in (
        (nonprompt_path, "nonprompt_output"),
        (flips_path, "flips_output"),
    ):
        write_histogram_artifact(
            path,
            histograms=_transformed_payload(artifact_kind),
            artifact_kind=artifact_kind,
            sumw2_storage_provenance=policy.to_provenance(),
            lineage_inputs=[lineage_input_from_sidecar(processor_sidecar)],
        )
    with pytest.raises(RuntimeError, match="incompatible histogram artifact kinds"):
        load_and_merge_histogram_pkls(
            [str(processor_path), str(nonprompt_path)],
            on_process_collision="allow",
        )
    with pytest.raises(RuntimeError, match="incompatible histogram artifact kinds"):
        load_and_merge_histogram_pkls(
            [str(nonprompt_path), str(flips_path)],
            on_process_collision="allow",
        )


@pytest.mark.parametrize("artifact_kind", ["nonprompt_output", "flips_output"])
def test_transformed_missing_and_unexpected_companions_are_actionable(
    tmp_path, policy, artifact_kind
):
    source_path = tmp_path / "processor.pkl.gz"
    source_sidecar = _write_processor(source_path, policy)
    path = tmp_path / f"{artifact_kind}.pkl.gz"
    payload = _transformed_payload(artifact_kind)
    expected_process = (
        "flipsUL18" if artifact_kind == "flips_output" else "nonpromptUL18"
    )
    write_histogram_artifact(
        path,
        histograms=payload,
        artifact_kind=artifact_kind,
        sumw2_storage_provenance=policy.to_provenance(),
        lineage_inputs=[lineage_input_from_sidecar(source_sidecar)],
    )

    missing_payload = {scalar_nominal_key("njets"): payload[scalar_nominal_key("njets")]}
    _write_raw(path, missing_payload)
    with pytest.raises(histogram_artifact_error) as missing_error:
        validate_histogram_artifact(path)
    missing_message = str(missing_error.value)
    assert "pkl_path=" in missing_message
    assert "sidecar_path=" in missing_message
    assert f"artifact_kind={artifact_kind}" in missing_message
    assert "family=njets" in missing_message
    assert f"missing_required_companions=['{expected_process}']" in missing_message
    assert "run_data_driven" in missing_message

    write_histogram_artifact(
        path,
        histograms=payload,
        artifact_kind=artifact_kind,
        sumw2_storage_provenance=policy.to_provenance(),
        lineage_inputs=[lineage_input_from_sidecar(source_sidecar)],
    )
    unexpected_payload = copy.deepcopy(payload)
    unexpected_payload["njets_sumw2"].fill(
        process="unexpectedUL18",
        channel="3l",
        systematic="nominal",
        appl="isSR_3l",
        njets_sumw2=np.asarray([0.5]),
        weight=np.asarray([1.0]),
    )
    _write_raw(path, unexpected_payload)
    with pytest.raises(histogram_artifact_error) as unexpected_error:
        validate_histogram_artifact(path)
    unexpected_message = str(unexpected_error.value)
    assert "unexpected_companions=['unexpectedUL18']" in unexpected_message
    assert "family=njets" in unexpected_message

    producer_path = tmp_path / f"producer_rejects_{artifact_kind}.pkl.gz"
    with pytest.raises(
        histogram_artifact_error,
        match="unexpected transformed companions.*unexpectedUL18",
    ):
        write_histogram_artifact(
            producer_path,
            histograms=unexpected_payload,
            artifact_kind=artifact_kind,
            sumw2_storage_provenance=policy.to_provenance(),
            lineage_inputs=[lineage_input_from_sidecar(source_sidecar)],
        )
    assert not producer_path.exists()
    assert not metadata_sidecar_path(producer_path).exists()


@pytest.mark.parametrize(
    "tamper",
    [
        "basename",
        "size",
        "checksum",
        "unknown_kind",
        "nominal_schema",
        "nominal_layout",
        "missing_artifact_field",
        "partial_manifest",
        "wrong_processes",
        "malformed_lineage",
    ],
)
def test_metadata_tampering_is_rejected(tmp_path, policy, tamper):
    path = tmp_path / f"tamper_{tamper}.pkl.gz"
    _write_processor(path, policy)
    sidecar_path = metadata_sidecar_path(path)
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    if tamper == "basename":
        sidecar["artifact"]["pkl_basename"] = "wrong.pkl.gz"
    elif tamper == "size":
        sidecar["artifact"]["pkl_size_bytes"] += 1
    elif tamper == "checksum":
        sidecar["artifact"]["pkl_sha256"] = "0" * 64
    elif tamper == "unknown_kind":
        sidecar["artifact"]["artifact_kind"] = "unknown"
    elif tamper == "nominal_schema":
        sidecar["artifact"]["nominal_container_schema_version"] = 999
    elif tamper == "nominal_layout":
        sidecar["artifact"]["nominal_container_layout"] = "wrong_layout"
    elif tamper == "missing_artifact_field":
        sidecar["artifact"].pop("merged")
    elif tamper == "partial_manifest":
        sidecar["sumw2_content_manifest"]["families"]["njets"].pop(
            "sumw2_processes"
        )
    elif tamper == "wrong_processes":
        sidecar["sumw2_content_manifest"]["families"]["njets"][
            "scalar_nominal_processes"
        ].append("wrongUL18")
    else:
        sidecar["lineage"] = {"inputs": [{"pkl_basename": "missing-fields"}]}
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
    with pytest.raises(histogram_artifact_error):
        validate_histogram_artifact(path)


def test_legacy_uniform_without_sidecar_remains_usable(tmp_path):
    path = tmp_path / "legacy.pkl.gz"
    nominal = HistEFT(*_axes("njets"), wc_names=["ctG"], label="Events")
    nominal.fill(
        process="signalUL18",
        channel="3l",
        systematic="nominal",
        appl="isSR_3l",
        njets=np.asarray([0.5]),
        weight=np.asarray([2.0]),
        eft_coeff=np.asarray([[1.5, 2.0, 3.0]]),
    )
    companion = HistEFT(*_axes("njets_sumw2"), wc_names=["ctG"], label="Events")
    companion.fill(
        process="signalUL18",
        channel="3l",
        systematic="nominal",
        appl="isSR_3l",
        njets_sumw2=np.asarray([0.5]),
        weight=np.asarray([3.0]),
        eft_coeff=np.asarray([[1.0, 0.0, 0.0]]),
    )
    _write_raw(path, {"njets": nominal, "njets_sumw2": companion})
    with pytest.warns(UserWarning, match="legacy uniform") as warning_records:
        merged, report = load_and_merge_histogram_pkls([str(path)])
    assert len(warning_records) == 1
    assert report["schema"] == "legacy_uniform"
    scalar = evaluate_nominal_at_wc(merged, "njets", {}, schema_version=None)
    assert _processes(scalar) == ["signalUL18"]
    datacard_view = materialize_legacy_histogram_dict(
        merged,
        schema_version=None,
        require_companions=("njets",),
    )
    assert tuple(datacard_view) == ("njets", "njets_sumw2")
    assert not metadata_sidecar_path(path).exists()


def test_recognized_legacy_metadata_does_not_create_schema_v2_sidecar(
    tmp_path, policy
):
    path = tmp_path / "legacy_with_metadata.pkl.gz"
    nominal = _fill_eft((("signalUL18", "isSR_3l", 2.0),))
    companion = _fill_eft((("signalUL18", "isSR_3l", 3.0),))
    _write_raw(path, {"njets": nominal, "njets_sumw2": companion})
    legacy_metadata = {
        "metadata_version": 1,
        "input_histogram": str(path),
        "sumw2_storage_provenance": policy.to_provenance(),
        "nominal_container_schema_version": 2,
        "nominal_container_layout": "split_sibling_v1",
    }
    metadata_sidecar_path(path).write_text(
        json.dumps(legacy_metadata), encoding="utf-8"
    )
    with pytest.warns(UserWarning, match="legacy uniform"):
        merged, report = load_and_merge_histogram_pkls([str(path)])
    assert report["schema"] == "legacy_uniform"
    assert tuple(merged) == ("njets", "njets_sumw2")
    assert json.loads(metadata_sidecar_path(path).read_text(encoding="utf-8")) == (
        legacy_metadata
    )


def test_no_user_facing_sidecar_cli_option_and_shared_discovery_source():
    parser_help = run_data_driven._build_argument_parser().format_help()
    assert "--metadata-json" not in parser_help
    assert "--metadata-sidecar" not in parser_help
    assert "--sidecar" not in parser_help
    repository_root = Path(__file__).resolve().parents[1]
    consumer_sources = [
        repository_root / "analysis/topeft_run2/run_analysis.py",
        repository_root / "analysis/topeft_run2/run_data_driven.py",
        repository_root / "analysis/topeft_run2/make_cards.py",
        repository_root / "analysis/topeft_run2/make_cr_and_sr_plots.py",
        repository_root / "analysis/topeft_run2/faketau_sf_fitter.py",
        repository_root / "analysis/topeft_run2/tauFitter.py",
        repository_root / "topeft/modules/datacard_tools.py",
    ]
    for source_path in consumer_sources:
        source = source_path.read_text(encoding="utf-8")
        assert "--metadata-sidecar" not in source
        assert "--sidecar" not in source
        assert "--metadata-json" not in source
    assert "metadata_sidecar_path" in (
        repository_root / "topeft/modules/histogram_artifact.py"
    ).read_text(encoding="utf-8")
