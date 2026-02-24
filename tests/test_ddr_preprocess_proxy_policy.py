from __future__ import annotations

from pathlib import Path

import pytest

from analysis.topeft_run2.run_analysis_helpers import RunConfig
from analysis.topeft_run2.workflow import (
    _resolve_ddr_preprocess_paths,
    flatten_ddr_result_payload,
    stage_ddr_proxy,
)


def test_stage_ddr_proxy_copies_to_proxy_pem(tmp_path: Path) -> None:
    source_proxy = tmp_path / "user_proxy.pem"
    source_proxy.write_text("proxy-data", encoding="utf-8")
    staging_dir = tmp_path / "staging"

    staged_proxy = stage_ddr_proxy(str(source_proxy), staging_dir=staging_dir)

    assert staged_proxy == staging_dir / "proxy.pem"
    assert staged_proxy.exists()
    assert staged_proxy.read_text(encoding="utf-8") == "proxy-data"


def test_stage_ddr_proxy_missing_path_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        stage_ddr_proxy(str(tmp_path / "missing_proxy.pem"), staging_dir=tmp_path / "staging")


def test_preprocess_paths_auto_save_defaults_to_results_dir(tmp_path: Path) -> None:
    config = RunConfig(executor="taskvine")
    preprocessed_data_path, save_path = _resolve_ddr_preprocess_paths(
        config,
        results_dir=tmp_path,
    )

    assert preprocessed_data_path is None
    assert save_path == str((tmp_path / "ddr_preprocessed_data.json").resolve())


def test_preprocess_paths_explicit_save_overrides_auto(tmp_path: Path) -> None:
    explicit_save = tmp_path / "custom-preprocessed.json"
    config = RunConfig(
        executor="taskvine",
        ddr_save_preprocess=str(explicit_save),
    )
    _, save_path = _resolve_ddr_preprocess_paths(
        config,
        results_dir=tmp_path,
    )

    assert save_path == str(explicit_save)


def test_preprocess_paths_reuse_mode_disables_auto_save(tmp_path: Path) -> None:
    config = RunConfig(
        executor="taskvine",
        ddr_preprocessed_data=str(tmp_path / "existing-preprocessed.json"),
        ddr_auto_save_preprocess=True,
    )
    preprocessed_data_path, save_path = _resolve_ddr_preprocess_paths(
        config,
        results_dir=tmp_path,
    )

    assert preprocessed_data_path == str(tmp_path / "existing-preprocessed.json")
    assert save_path is None


def test_preprocess_paths_reuse_mode_keeps_explicit_save(tmp_path: Path) -> None:
    explicit_save = tmp_path / "explicit-save.json"
    config = RunConfig(
        executor="taskvine",
        ddr_preprocessed_data=str(tmp_path / "existing-preprocessed.json"),
        ddr_save_preprocess=str(explicit_save),
    )
    _, save_path = _resolve_ddr_preprocess_paths(
        config,
        results_dir=tmp_path,
    )

    assert save_path == str(explicit_save)


def test_flatten_ddr_result_payload_uses_canonical_key_order() -> None:
    payload = {
        "proc_a": {
            "dataset_a": {
                ("ptbl", "2lss", "isSR_2l", "TTW", "nominal"): 1,
                ("ptbl", "2lss", "isSR_2l", "TTW", ("JES", "Up")): 2,
                "region_yields": {"ignored": True},
            }
        }
    }

    flattened = flatten_ddr_result_payload(payload)

    assert list(flattened.keys()) == [
        ("TTW", "2lss", "ptbl", "isSR_2l", "JES:Up"),
        ("TTW", "2lss", "ptbl", "isSR_2l", "nominal"),
    ]
    assert flattened[("TTW", "2lss", "ptbl", "isSR_2l", "nominal")] == 1
    assert flattened[("TTW", "2lss", "ptbl", "isSR_2l", "JES:Up")] == 2


def test_flatten_ddr_result_payload_merges_duplicates() -> None:
    payload = {
        "proc_a": {"dataset": {("ptbl", "2lss", "isSR_2l", "TTW", "nominal"): 1}},
        "proc_b": {"dataset": {("ptbl", "2lss", "isSR_2l", "TTW", "nominal"): 2}},
    }

    flattened = flatten_ddr_result_payload(payload)

    assert flattened[("TTW", "2lss", "ptbl", "isSR_2l", "nominal")] == 3
