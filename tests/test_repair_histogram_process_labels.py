from __future__ import annotations

import json
from pathlib import Path

import hist
import numpy as np
import pytest

from analysis.topeft_run2.repair_histogram_process_labels import (
    RUN2_PROCESS_LABEL_REPAIRS,
    _repair_histograms,
    _repair_typed_metadata,
    repair_artifacts,
    repair_error,
)
from topcoffea.modules.histEFT import HistEFT
from topcoffea.modules.sparseHist import SparseHist
from topcoffea.modules.utils import get_hist_from_pkl
from topeft.modules.axes import info as axes_info
from topeft.modules.axes import info_2d as axes_info_2d
from topeft.modules.data_driven_products import (
    certify_data_driven_preflight,
    resolve_data_driven_products,
)
from topeft.modules.histogram_artifact import (
    histogram_artifact_error,
    metadata_sidecar_path,
    read_histogram_sidecar,
    validate_histogram_artifact,
    write_histogram_artifact,
)
from topeft.modules.nominal_schema import scalar_nominal_key, sumw2_key
from topeft.modules.production_sample_profile import (
    build_active_sample_universe,
    certify_production_sample_contract,
)
from topeft.modules.sumw2_policy import resolve_sumw2_storage_policy


OLD_LABELS = tuple(RUN2_PROCESS_LABEL_REPAIRS)
CANONICAL_LABELS = tuple(RUN2_PROCESS_LABEL_REPAIRS.values())
UNCHANGED_LABELS = (
    "WWW_4F_centralUL16",
    "WWZ_4F_centralUL18",
    "unrelated_centralUL17",
)
DATA_LABELS = ("dataUL16APV", "dataUL17")


def _axes(dense_name):
    return (
        hist.axis.StrCategory([], name="process", growth=True),
        hist.axis.StrCategory([], name="channel", growth=True),
        hist.axis.StrCategory([], name="systematic", growth=True),
        hist.axis.StrCategory([], name="appl", growth=True),
        hist.axis.Regular(2, 0.0, 2.0, name=dense_name),
    )


def _fill_sparse(dense_name, entries):
    output = SparseHist(*_axes(dense_name), storage="Double")
    for process, channel, weight in entries:
        output.fill(
            process=process,
            channel=channel,
            systematic="nominal",
            appl="isSR_3l",
            **{dense_name: np.asarray([0.5, 1.5])},
            weight=np.asarray([weight, weight + 0.25]),
        )
    return output


def _fill_eft(process):
    output = HistEFT(*_axes("njets"), wc_names=["ctG"], label="Events")
    output.fill(
        process=process,
        channel="3l",
        systematic="nominal",
        appl="isSR_3l",
        njets=np.asarray([0.5]),
        weight=np.asarray([2.0]),
        eft_coeff=np.asarray([[1.0, 2.0, 3.0]]),
    )
    return output


def _samples(include_collision=False):
    labels = (*OLD_LABELS, *UNCHANGED_LABELS)
    if include_collision:
        labels = (*labels, CANONICAL_LABELS[0])
    samples = {
        f"sample_{index}": {
            "histAxisName": label,
            "isData": False,
            "WCnames": [],
        }
        for index, label in enumerate(labels)
    }
    for index, label in enumerate(DATA_LABELS):
        samples[f"data_{index}"] = {
            "histAxisName": label,
            "isData": True,
            "WCnames": [],
        }
    return samples


def _write_synthetic_artifact(path: Path, *, include_collision=False):
    samples = _samples(include_collision=include_collision)
    policy = resolve_sumw2_storage_policy(
        {"mode": "full_diagnostics"},
        samples=samples,
        runtime_families=("njets",),
        axes_info=axes_info,
        axes_info_2d=axes_info_2d,
        sumw2_storage_present=True,
    )
    products = resolve_data_driven_products(
        {
            "nonprompt": {
                "enabled": True,
                "source_contributors": {
                    "data": {"process_names": list(DATA_LABELS)},
                    "prompt_mc": {"process_names": list(OLD_LABELS)},
                },
            },
            "flips": {"enabled": False},
        },
        data_driven_products_present=True,
        legacy_do_np=False,
        samples=samples,
        runtime_families=("njets",),
        metadata_path="synthetic_options.yml",
    )
    requested, resolved = certify_data_driven_preflight(products, policy)
    entries = [
        (label, "3l", float(index + 1))
        for index, label in enumerate((*OLD_LABELS, *UNCHANGED_LABELS, *DATA_LABELS))
    ]
    if include_collision:
        entries.append((CANONICAL_LABELS[0], "3l", 100.0))
    payload = {
        scalar_nominal_key("njets"): _fill_sparse("njets", entries),
        sumw2_key("njets"): _fill_sparse(
            sumw2_key("njets"),
            [(process, channel, weight**2) for process, channel, weight in entries],
        ),
    }
    production_contract = certify_production_sample_contract(
        build_active_sample_universe(samples, wrapper_identity="pytest"),
        policy,
        products,
    )
    return write_histogram_artifact(
        path,
        histograms=payload,
        artifact_kind="processor_output",
        sumw2_storage_provenance=policy.to_provenance(),
        requested_data_driven_products=requested,
        resolved_data_driven_contract=resolved,
        production_sample_contract=production_contract,
    )


def _dense_content(histogram):
    return {
        tuple(key): np.asarray(value).copy()
        for key, value in histogram.view(flow=True).items()
    }


def _sidecar_contains_exact_label(value, labels):
    if isinstance(value, dict):
        return any(_sidecar_contains_exact_label(child, labels) for child in value.values())
    if isinstance(value, list):
        return any(_sidecar_contains_exact_label(child, labels) for child in value)
    return isinstance(value, str) and value in labels


def test_exact_repair_is_dry_run_first_and_write_is_copy_only(tmp_path):
    input_path = tmp_path / "input.pkl.gz"
    original_sidecar = _write_synthetic_artifact(input_path)
    input_identity = (input_path.read_bytes(), metadata_sidecar_path(input_path).read_bytes())
    output_dir = tmp_path / "corrected"

    dry_run = repair_artifacts([input_path], output_dir=output_dir)

    assert dry_run[0]["mapping_entries_found"] == RUN2_PROCESS_LABEL_REPAIRS
    assert dry_run[0]["mapping_entries_absent"] == []
    assert set(dry_run[0]["payload_histograms_affected"]) == {
        scalar_nominal_key("njets"),
        sumw2_key("njets"),
    }
    assert {
        "sumw2_storage_provenance",
        "sumw2_content_manifest",
        "resolved_data_driven_contract",
    } <= set(dry_run[0]["sidecar_surfaces_affected"])
    assert dry_run[0]["write_performed"] is False
    assert not output_dir.exists()
    assert input_identity == (
        input_path.read_bytes(),
        metadata_sidecar_path(input_path).read_bytes(),
    )

    written = repair_artifacts([input_path], output_dir=output_dir, write=True)
    output_path = output_dir / input_path.name
    output_sidecar_path = metadata_sidecar_path(output_path)

    assert written[0]["write_performed"] is True
    assert output_path.is_file()
    assert output_sidecar_path.is_file()
    assert input_identity == (
        input_path.read_bytes(),
        metadata_sidecar_path(input_path).read_bytes(),
    )
    output = get_hist_from_pkl(str(output_path))
    validated = validate_histogram_artifact(output_path, histograms=output)
    repaired_sidecar = read_histogram_sidecar(output_path)
    assert validated["metadata"] == repaired_sidecar
    assert not _sidecar_contains_exact_label(repaired_sidecar, set(OLD_LABELS))
    assert repaired_sidecar["production_sample_contract"] == original_sidecar[
        "production_sample_contract"
    ]
    for histogram in output.values():
        labels = {str(label) for label in histogram.axes["process"]}
        assert not labels & set(OLD_LABELS)
        assert set(CANONICAL_LABELS) <= labels
        assert set(UNCHANGED_LABELS) <= labels

    original = get_hist_from_pkl(str(input_path))
    for key in original:
        repaired_content = _dense_content(output[key])
        for categorical_key, dense_values in _dense_content(original[key]).items():
            categories = list(categorical_key)
            categories[0] = RUN2_PROCESS_LABEL_REPAIRS.get(categories[0], categories[0])
            np.testing.assert_array_equal(repaired_content[tuple(categories)], dense_values)

    with pytest.raises(repair_error, match="Refusing to overwrite"):
        repair_artifacts([input_path], output_dir=output_dir, write=True)


def test_histogram_repair_handles_eft_and_preserves_coefficients():
    original = _fill_eft(OLD_LABELS[1])
    repaired, affected = _repair_histograms({"njets__eft_nominal": original})

    assert affected == {"njets__eft_nominal": [OLD_LABELS[1]]}
    assert {str(label) for label in repaired["njets__eft_nominal"].axes["process"]} == {
        CANONICAL_LABELS[1]
    }
    np.testing.assert_array_equal(
        next(iter(original.view(flow=True).values())),
        next(iter(repaired["njets__eft_nominal"].view(flow=True).values())),
    )


def test_histogram_repair_preserves_weight_storage_values_and_variances():
    original = SparseHist(*_axes("njets"), storage="Weight")
    original.fill(
        process=OLD_LABELS[2],
        channel="3l",
        systematic="nominal",
        appl="isSR_3l",
        njets=np.asarray([0.5, 1.5]),
        weight=np.asarray([2.0, 3.0]),
    )

    repaired, _ = _repair_histograms({"weighted": original})
    original_values = next(iter(original.view(flow=True).values()))
    repaired_values = next(iter(repaired["weighted"].view(flow=True).values()))

    np.testing.assert_array_equal(repaired_values.value, original_values.value)
    np.testing.assert_array_equal(repaired_values.variance, original_values.variance)


def test_process_collision_is_refused(tmp_path):
    input_path = tmp_path / "collision.pkl.gz"
    _write_synthetic_artifact(input_path, include_collision=True)

    with pytest.raises(repair_error, match="merge existing categorical support"):
        repair_artifacts([input_path])


def test_transformation_contract_process_fields_are_repaired_by_type():
    metadata = {
        "transformation_contract": {
            "families": {
                "njets": {
                    "source_scalar_processes": [OLD_LABELS[0], "other"],
                    "retained_scalar_processes": [OLD_LABELS[2]],
                    "generated_nonprompt_processes": ["nonpromptUL17"],
                }
            }
        }
    }

    repaired = _repair_typed_metadata(metadata)

    family = repaired["transformation_contract"]["families"]["njets"]
    assert family["source_scalar_processes"] == [CANONICAL_LABELS[0], "other"]
    assert family["retained_scalar_processes"] == [CANONICAL_LABELS[2]]
    assert family["generated_nonprompt_processes"] == ["nonpromptUL17"]


def test_unsupported_or_malformed_sidecar_fails_closed(tmp_path):
    input_path = tmp_path / "malformed.pkl.gz"
    _write_synthetic_artifact(input_path)
    sidecar_path = metadata_sidecar_path(input_path)
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    sidecar["unsupported_identity"] = OLD_LABELS[0]
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")

    with pytest.raises(histogram_artifact_error):
        repair_artifacts([input_path])


def test_write_mode_requires_explicit_separate_output_directory(tmp_path):
    input_path = tmp_path / "input.pkl.gz"
    _write_synthetic_artifact(input_path)

    with pytest.raises(repair_error, match="explicit --output-dir"):
        repair_artifacts([input_path], write=True)
    with pytest.raises(repair_error, match="in-place repair is forbidden"):
        repair_artifacts([input_path], output_dir=tmp_path)
