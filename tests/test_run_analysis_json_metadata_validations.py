import importlib.util
import json
import runpy
import sys
from pathlib import Path
from unittest import mock

import pytest


_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "analysis/topeft_run2/run_analysis.py"


def _load_run_analysis_module():
    spec = importlib.util.spec_from_file_location("run_analysis_json_validation_test", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    original_sys_path = list(sys.path)
    sys.path.insert(0, str(_SCRIPT_PATH.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path = original_sys_path
    return module


def _write_payload(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fout:
        json.dump(payload, fout)


def _base_payload(*, hist_axis_name, year, files=None):
    return {
        "files": files if files is not None else ["/store/test/file.root"],
        "year": year,
        "xsec": 1.0,
        "nEvents": 10,
        "nGenEvents": 10,
        "nSumOfWeights": 10.0,
        "isData": False,
        "histAxisName": hist_axis_name,
        "treeName": "Events",
        "options": "",
    }


def _run_cli_with_args(args):
    original_sys_path = list(sys.path)
    sys.path.insert(0, str(_SCRIPT_PATH.parent))
    try:
        with mock.patch.object(sys, "argv", args):
            runpy.run_path(str(_SCRIPT_PATH), run_name="__main__")
    finally:
        sys.path = original_sys_path


def test_case_a_same_basename_different_histaxis_raises(tmp_path):
    json_a = tmp_path / "a" / "sample.json"
    json_b = tmp_path / "b" / "sample.json"
    _write_payload(json_a, _base_payload(hist_axis_name="histA", year="2022"))
    _write_payload(json_b, _base_payload(hist_axis_name="histB", year="2022"))

    args = [
        "run_analysis.py",
        f"{json_a},{json_b}",
        "--pretend",
        "--skip-topcoffea-data-check",
    ]
    with pytest.raises(RuntimeError) as excinfo:
        _run_cli_with_args(args)

    message = str(excinfo.value)
    assert 'Colliding sample basename key "sample"' in message
    assert str(json_a.resolve()) in message
    assert str(json_b.resolve()) in message
    assert "histA" in message
    assert "histB" in message


def test_case_c_missing_json_reference_from_cfg_raises(tmp_path):
    cfg_path = tmp_path / "missing.cfg"
    missing_json = tmp_path / "does_not_exist.json"
    cfg_path.write_text(f"root://test/\n{missing_json}\n", encoding="utf-8")

    args = [
        "run_analysis.py",
        str(cfg_path),
        "--pretend",
        "--skip-topcoffea-data-check",
    ]
    with pytest.raises(SystemExit) as excinfo:
        _run_cli_with_args(args)

    message = str(excinfo.value)
    assert str(cfg_path) in message
    assert str(missing_json) in message
    assert "Missing referenced JSON file(s)" in message


def test_case_d_year_mismatch_detected_from_internal_tokens(tmp_path):
    json_path = tmp_path / "mismatch.json"
    payload = _base_payload(
        hist_axis_name="ttH_private",
        year="2022EE",
        files=["/store/user/foo/ND_skim2023BPix/output.root"],
    )
    _write_payload(json_path, payload)

    args = [
        "run_analysis.py",
        str(json_path),
        "--pretend",
        "--skip-topcoffea-data-check",
    ]
    with pytest.raises(RuntimeError) as excinfo:
        _run_cli_with_args(args)

    message = str(excinfo.value)
    assert str(json_path.resolve()) in message
    assert "payload year: 2022EE" in message
    assert "detected year from internal JSON content: 2023BPix" in message
    assert "2023BPix" in message


def test_case_e_run2_synonyms_behavior():
    run_analysis = _load_run_analysis_module()

    ok_payload = _base_payload(hist_axis_name="h", year="2016")
    ok_payload["notes"] = "UL16 campaign"
    # Should not raise: UL16 canonicalizes to 2016.
    assert run_analysis._validate_payload_year_tokens(ok_payload, "/tmp/ok.json") is None

    bad_payload = _base_payload(hist_axis_name="h", year="2016")
    bad_payload["notes"] = "UL17 campaign"
    with pytest.raises(RuntimeError) as excinfo:
        run_analysis._validate_payload_year_tokens(bad_payload, "/tmp/bad.json")

    message = str(excinfo.value)
    assert "payload year: 2016" in message
    assert "detected year from internal JSON content: 2017" in message
    assert "UL17" in message


def test_case_f_duplicate_file_reuse_warns_only(capsys):
    run_analysis = _load_run_analysis_module()

    samplesdict = {
        "sampleA": {"redirector": "root://x/", "files": ["/store/a.root"]},
        "sampleB": {"redirector": "root://x/", "files": ["/store/a.root"]},
        "sampleC": {"redirector": "root://x/", "files": ["/store/unique.root"]},
    }

    run_analysis._warn_duplicate_input_files(samplesdict, max_examples=10)
    captured = capsys.readouterr()

    assert "[WARNING] Found 1 input file path(s) reused across multiple samples" in captured.out
    assert "root://x//store/a.root" in captured.out
    assert "sampleA, sampleB" in captured.out
