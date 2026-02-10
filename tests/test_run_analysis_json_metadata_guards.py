import importlib.util
import json
import sys
from pathlib import Path

import pytest


_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "analysis/topeft_run2/run_analysis.py"


def _load_run_analysis_module():
    module_name = "run_analysis_json_metadata_guards_test"
    spec = importlib.util.spec_from_file_location(module_name, _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    original_sys_path = list(sys.path)
    sys.path.insert(0, str(_SCRIPT_PATH.parent.resolve()))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path = original_sys_path
    return module


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fout:
        json.dump(payload, fout)


def test_hist_axis_mismatch_for_same_basename_raises(tmp_path):
    run_analysis = _load_run_analysis_module()

    json_a = tmp_path / "input_samples/sample_jsons/background_samples/ND_skim2022/TTto2L2Nu_NDSkim.json"
    json_b = tmp_path / "input_samples/sample_jsons/background_samples/ND_skim2023/TTto2L2Nu_NDSkim.json"

    payload_a = {"histAxisName": "TTto2L2Nu_central2022", "year": "2022"}
    payload_b = {"histAxisName": "TTto2L2Nu_central2023", "year": "2023"}
    _write_json(json_a, payload_a)
    _write_json(json_b, payload_b)

    entries = [
        run_analysis._build_json_metadata_entry(
            "TTto2L2Nu_NDSkim", str(json_a), payload_a, "root://first"
        ),
        run_analysis._build_json_metadata_entry(
            "TTto2L2Nu_NDSkim", str(json_b), payload_b, "root://second"
        ),
    ]

    with pytest.raises(RuntimeError) as excinfo:
        run_analysis._validate_json_metadata_entries(entries)

    message = str(excinfo.value)
    assert 'Basename: "TTto2L2Nu_NDSkim"' in message
    assert str(json_a.resolve()) in message
    assert str(json_b.resolve()) in message
    assert "TTto2L2Nu_central2022" in message
    assert "TTto2L2Nu_central2023" in message
    assert "inferred dir-year: 2022" in message
    assert "inferred dir-year: 2023" in message


def test_directory_year_payload_year_mismatch_raises(tmp_path):
    run_analysis = _load_run_analysis_module()

    json_path = tmp_path / "input_samples/sample_jsons/signal_samples/ND_skim2023BPix/ttH.json"
    payload = {"histAxisName": "ttH_private2023BPix", "year": "2022EE"}
    _write_json(json_path, payload)

    entry = run_analysis._build_json_metadata_entry(
        "ttH", str(json_path), payload, "root://test"
    )
    assert run_analysis._infer_directory_year(str(json_path)) == "2023BPix"

    with pytest.raises(RuntimeError) as excinfo:
        run_analysis._validate_json_metadata_entries([entry])

    message = str(excinfo.value)
    assert str(json_path.resolve()) in message
    assert "payload year: 2022EE" in message
    assert "inferred dir-year: 2023BPix" in message
    assert 'set payload "year" to "2023BPix"' in message
