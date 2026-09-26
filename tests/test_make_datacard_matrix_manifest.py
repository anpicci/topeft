"""Focused tests for standard datacard matrix manifest materialization."""

import json
import sys
from pathlib import Path

import pytest

from analysis.topeft_run2 import datacard_matrix_runner as runner
from analysis.topeft_run2 import make_datacard_matrix_manifest as generator


_expected_rows = {
    "mixed_01": ("lj0pt", 27), "mixed_02": ("lt", 8),
    "mixed_03": ("ptz", 1), "mixed_04": ("ptz_wtau", 8),
    "3l_offz_01": ("lj0pt", 16), "3l_offz_02": ("ptll", 32),
    "3l_onz_tau_01": ("lj0pt", 10), "3l_onz_tau_02": ("ptz", 6),
    "3l_fwd_01": ("lt", 21),
}


def _args(tmp_path, era):
    inputs = {}
    for group in ("mixed", "offz", "onz_tau", "fwd"):
        path = tmp_path / f"{group}.pkl.gz"
        path.write_bytes(b"synthetic input")
        inputs[group] = path
    missing = tmp_path / "missing.root"
    missing.write_bytes(b"synthetic payload")
    make_cards = tmp_path / "make_cards.py"
    make_cards.write_text("# synthetic producer\n")
    return [
        "--era", era, "--manifest-output", str(tmp_path / "matrix.json"),
        "--output-root", str(tmp_path / "cards"), "--control-root", str(tmp_path / "control"),
        "--mixed-pkl", str(inputs["mixed"]), "--offz-pkl", str(inputs["offz"]),
        "--onz-tau-pkl", str(inputs["onz_tau"]), "--fwd-pkl", str(inputs["fwd"]),
        "--python-executable", sys.executable, "--make-cards-path", str(make_cards),
        "--missing-parton-file", str(missing), "--runtime-contract-id", f"{era}-synthetic",
    ], inputs, make_cards


@pytest.mark.parametrize("era,years", [
    ("run2", ["UL16APV", "UL16", "UL17", "UL18"]),
    ("run3", ["2022", "2022EE", "2023", "2023BPix"]),
])
def test_standard_manifest_rows_and_runtime_inputs(tmp_path, era, years):
    args, inputs, make_cards = _args(tmp_path, era)
    assert generator.main(args) == 0
    path = tmp_path / "matrix.json"
    observed = json.loads(path.read_text())
    parsed, digest = runner.load_manifest(path)
    assert parsed == observed
    assert len(digest) == 64
    assert observed["schema"] == "topeft_datacard_matrix_v2"
    assert observed["runtime_contract"]["make_cards_path"] == str(make_cards)
    assert observed["runtime_contract"]["python_executable"] == sys.executable
    assert observed["runtime_contract"]["fingerprints"] == [
        {"path": str(make_cards), "sha256": runner.hash_file(make_cards)}]
    assert [(row["row_id"], row["distribution"], len(row["physical_channels"]))
            for row in observed["rows"]] == [
                (row_id, distribution, count)
                for row_id, (distribution, count) in _expected_rows.items()]
    assert sum(len(row["physical_channels"]) for row in observed["rows"]) == 129
    assert {row["input_pkl"] for row in observed["rows"]} == {str(path) for path in inputs.values()}
    assert all(row["years"] == years for row in observed["rows"])
    assert all(str(tmp_path) in row["output_root"] and str(tmp_path) in row["log_path"]
               for row in observed["rows"])
    assert "3l_m_offZ_high_1b_2j" in next(row for row in observed["rows"]
                                             if row["row_id"] == "3l_offz_02")["physical_channels"]
    assert "3l_m_offZ_1b_fwd_1j" in next(row for row in observed["rows"]
                                           if row["row_id"] == "3l_fwd_01")["physical_channels"]


def test_explicit_subset_needs_only_its_input_group_and_does_not_overwrite(tmp_path):
    args, inputs, _ = _args(tmp_path, "run2")
    for group in ("offz", "onz_tau", "fwd"):
        option = f"--{group.replace('_', '-')}-pkl"
        position = args.index(option)
        del args[position:position + 2]
    args.extend(["--physical-target", "2lss_p_4j_lj0pt"])
    assert generator.main(args) == 0
    path = tmp_path / "matrix.json"
    parsed, _ = runner.load_manifest(path)
    assert [(row["row_id"], row["physical_channels"], row["input_pkl"])
            for row in parsed["rows"]] == [("mixed_01", ["2lss_p_4j"], str(inputs["mixed"]))]
    previous = path.read_bytes()
    with pytest.raises(ValueError, match="be absent"):
        generator.main(args)
    assert path.read_bytes() == previous


def test_missing_input_and_unknown_target_leave_manifest_absent(tmp_path):
    args, _, _ = _args(tmp_path, "run3")
    position = args.index("--offz-pkl")
    del args[position:position + 2]
    with pytest.raises(ValueError, match="offz PKL is required"):
        generator.main(args)
    assert not (tmp_path / "matrix.json").exists()
    args.extend(["--physical-target", "unknown_lj0pt"])
    with pytest.raises(ValueError, match="outside the channel set"):
        generator.main(args)
    assert not (tmp_path / "matrix.json").exists()
