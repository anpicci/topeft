"""Focused synthetic contract tests for portable datacard references."""

import hashlib
import json
from pathlib import Path

import pytest

from tests.datacard_golden import compare_package, load_golden_fixture


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _combined(tmp_path, cards=False):
    package = tmp_path / "package"
    package.mkdir()
    payload_dir = package / "cards" if cards else package
    payload_dir.mkdir(exist_ok=True)
    txt = {"Run2_alpha.txt": b"card-a", "Run3_beta.txt": b"card-b"}
    root = {"Run2_alpha.root": b"root-a", "Run3_beta.root": b"root-b"}
    for name, value in (txt | root).items():
        (payload_dir / name).write_bytes(value)
    (package / "scalings.json").write_bytes(b"scalings")
    names = list(txt)
    lines = ["cards/" + name if cards else name for name in names]
    (package / "ordered_card_inputs.txt").write_text("\n".join(lines) + "\n")
    mapping = [
        {"era": era, "physical_name": physical, "per_era_chN": "ch1",
         "combined_chN": "ch" + str(index), "combined_order_index": index,
         "destination_txt_name": name, "destination_root_name": name[:-4] + ".root"}
        for index, (era, physical, name) in enumerate(
            (("run2", "alpha", names[0]), ("run3", "beta", names[1])), 1)
    ]
    _write_json(package / "combined_mapping_manifest.json", {"schema": "TOP26006_v1", "artifact_type": "combined_mapping_manifest", "rows": mapping})
    (package / "README.md").write_text('mapfile -t cards < ordered_card_inputs.txt\ncombineCards.py "${cards[@]}" > combinedcard.txt\nDo not use a wildcard/glob.\n')
    stable = {"schema": "TOP26006_v1", "artifact_type": "package_provenance", "analysis": "TOP-26-006",
              "packaged_txt_count": 2, "packaged_root_count": 2, "scalings_sha256": _sha(b"scalings"),
              "source_scalings_sha256": {"run2": "c" * 64, "run3": "d" * 64}}
    reference = {"assembler_commit": "e" * 40, "assembler_source_sha256": "f" * 64,
                 "manifest_sha256": _sha((package / "combined_mapping_manifest.json").read_bytes()),
                 "ordered_card_inputs_sha256": _sha("\n".join(names).encode() + b"\n"),
                 "package_date": "260923", "package_version": "v1",
                 "source_mapping_sha256": {"run2": "a" * 64, "run3": "b" * 64}}
    provenance = stable | reference | {"package_root": "historical-root"}
    if cards:
        provenance["ordered_card_inputs_sha256"] = _sha((package / "ordered_card_inputs.txt").read_bytes())
    _write_json(package / "package-provenance.json", provenance)
    fixture = {
        "fixture_schema": "top26006_datacard_golden_v1", "analysis": "TOP-26-006",
        "reference_role": "development_regression", "package_contract_schema": "TOP26006_v1",
        "payload": {"txt": {key: _sha(value) for key, value in txt.items()},
                    "root": {key: _sha(value) for key, value in root.items()}},
        "scalings_sha256": _sha(b"scalings"),
        "ordered_card_inputs": {"historical_source_sha256": reference["ordered_card_inputs_sha256"], "basenames": names},
        "combined_mapping": mapping,
        "readme_operational_contract": {"ordered_list_combine_cards_required": True, "direct_glob_forbidden": True},
        "provenance_comparison_contract": {
            "required_stable_semantic_values": stable, "reference_values": reference,
            "allowed_variable_keys": ["package_root", "package_date", "package_version", "created_at", "assembler_commit", "assembler_source_sha256"],
            "conditional_digest_deltas": {"manifest_sha256": "combined_mapping_semantics_equal", "ordered_card_inputs_sha256": "ordered_card_basenames_equal_with_cards_prefix", "source_mapping_sha256": "combined_mapping_semantics_equal"}},
        "target_layout_contract": {"payload_subdirectory": "cards"},
        "target_package_naming_contract": "top26006_combined_package_<date>_vN",
    }
    fixture_path = tmp_path / "golden.json"
    _write_json(fixture_path, fixture)
    return package, fixture_path


def _per_era(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    (package / "ttx_multileptons-alpha.txt").write_bytes(b"card")
    (package / "ttx_multileptons-alpha.root").write_bytes(b"root")
    (package / "ttx_multileptons-beta.txt").write_bytes(b"card-b")
    (package / "ttx_multileptons-beta.root").write_bytes(b"root-b")
    (package / "selectedWCs.txt").write_bytes(b"wc")
    (package / "scalings.json").write_bytes(b"scale")
    mapping = [{"physical_name": "alpha", "per_era_chN": "ch1"},
               {"physical_name": "beta", "per_era_chN": "ch2"}]
    fixture = {
        "fixture_schema": "top26006_datacard_golden_v1", "analysis": "TOP-26-006",
        "reference_role": "development_regression", "era": "run2",
        "payload": {"txt": {"ttx_multileptons-alpha.txt": _sha(b"card"), "ttx_multileptons-beta.txt": _sha(b"card-b")},
                    "root": {"ttx_multileptons-alpha.root": _sha(b"root"), "ttx_multileptons-beta.root": _sha(b"root-b")}},
        "selected_wcs_sha256": _sha(b"wc"), "scalings_sha256": _sha(b"scale"),
        "physical_to_chN": mapping, "target_layout_contract": {"payload_subdirectory": "cards"},
        "target_package_naming_contract": "top26006_run2_package_<date>_vN",
    }
    fixture_path = tmp_path / "golden.json"
    _write_json(fixture_path, fixture)
    return package, fixture_path, mapping


def _result(tmp_path, cards=False):
    package, fixture_path = _combined(tmp_path, cards=cards)
    return package, compare_package(load_golden_fixture(fixture_path), package)


def test_exact_logical_payload_match(tmp_path):
    _, result = _result(tmp_path)
    assert result["payload_mismatches"] == []
    assert result["semantic_contract_mismatches"] == []
    assert result["unexpected_provenance_deltas"] == []


def test_cards_layout_preserves_logical_identity_and_order(tmp_path):
    _, result = _result(tmp_path, cards=True)
    assert result["payload_mismatches"] == []
    assert result["semantic_contract_mismatches"] == []
    assert {row["artifact"] for row in result["intentional_layout_deltas"]} == {"payload", "ordered_card_inputs"}
    assert any(row["key"] == "ordered_card_inputs_sha256" for row in result["allowed_provenance_deltas"])


@pytest.mark.parametrize("suffix,kind", [(".txt", "txt"), (".root", "root")])
def test_payload_hash_mismatch(tmp_path, suffix, kind):
    package, fixture_path = _combined(tmp_path)
    target = next(package.glob("*" + suffix))
    target.write_bytes(b"changed")
    result = compare_package(load_golden_fixture(fixture_path), package)
    assert any(row["kind"] == kind and row["reason"] == "sha256" and row["basename"] == target.name for row in result["payload_mismatches"])


def test_missing_and_extra_payload_identity(tmp_path):
    package, fixture_path = _combined(tmp_path)
    (package / "Run2_alpha.txt").unlink()
    (package / "Run2_other.txt").write_bytes(b"card-a")
    result = compare_package(load_golden_fixture(fixture_path), package)
    assert {(row["basename"], row["reason"]) for row in result["payload_mismatches"]} >= {("Run2_alpha.txt", "missing"), ("Run2_other.txt", "extra")}


def test_ordered_card_swap_detected(tmp_path):
    package, fixture_path = _combined(tmp_path)
    path = package / "ordered_card_inputs.txt"
    path.write_text("Run3_beta.txt\nRun2_alpha.txt\n")
    result = compare_package(load_golden_fixture(fixture_path), package)
    assert any(row["artifact"] == "ordered_card_inputs" for row in result["semantic_contract_mismatches"])


def test_per_era_mapping_mismatch(tmp_path):
    package, fixture_path, mapping = _per_era(tmp_path)
    mapping[0]["per_era_chN"] = "ch2"
    result = compare_package(load_golden_fixture(fixture_path), package, mapping)
    assert any(row["artifact"] == "physical_to_chN" for row in result["semantic_contract_mismatches"])


@pytest.mark.parametrize("replacement,reason", [
    ({"physical_name": "alpha", "per_era_chN": "ch1"}, "duplicate_physical_name"),
    ({"physical_name": "alpha", "per_era_chN": "ch2"}, "duplicate_physical_name"),
    ({"physical_name": "beta", "per_era_chN": "ch1"}, "duplicate_per_era_chN"),
])
def test_per_era_duplicate_candidate_identity(tmp_path, replacement, reason):
    package, fixture_path, mapping = _per_era(tmp_path)
    mapping[1] = replacement
    result = compare_package(load_golden_fixture(fixture_path), package, mapping)
    assert any(row.get("reason") == reason and row.get("index") == 1
               for row in result["semantic_contract_mismatches"])


@pytest.mark.parametrize("candidate", [
    [{"physical_name": "alpha", "per_era_chN": "ch1"}],
    [{"physical_name": "alpha", "per_era_chN": "ch1"},
     {"physical_name": "beta", "per_era_chN": "ch2"},
     {"physical_name": "gamma", "per_era_chN": "ch3"}],
    [{"physical_name": "alpha", "per_era_chN": "ch1", "extra": "value"},
     {"physical_name": "beta", "per_era_chN": "ch2"}],
    {"alpha": "ch1"},
])
def test_per_era_mapping_shape_rejected(tmp_path, candidate):
    package, fixture_path, _ = _per_era(tmp_path)
    result = compare_package(load_golden_fixture(fixture_path), package, candidate)
    assert any(row.get("reason") in ("row_count", "not_list", "malformed_row")
               for row in result["semantic_contract_mismatches"])


@pytest.mark.parametrize("replacement", [
    {"physical_name": "alpha", "per_era_chN": "ch2"},
    {"physical_name": "beta", "per_era_chN": "ch1"},
])
def test_per_era_fixture_duplicate_identity_rejected(tmp_path, replacement):
    _, fixture_path, _ = _per_era(tmp_path)
    fixture = json.loads(fixture_path.read_text())
    fixture["physical_to_chN"][1] = replacement
    _write_json(fixture_path, fixture)
    with pytest.raises(ValueError, match="per-era mapping"):
        load_golden_fixture(fixture_path)


def test_readme_requires_ordered_input_load(tmp_path):
    package, fixture_path = _combined(tmp_path)
    (package / "README.md").write_text('combineCards.py "${cards[@]}" > combinedcard.txt\nDo not use a glob.\n')
    result = compare_package(load_golden_fixture(fixture_path), package)
    assert any(row["artifact"] == "README.md" for row in result["semantic_contract_mismatches"])


def test_readme_accepts_whitespace_variation(tmp_path):
    package, fixture_path = _combined(tmp_path)
    (package / "README.md").write_text('mapfile  -t  cards  < ordered_card_inputs.txt\n'
                                       'combineCards.py   "${cards[@]}"   >  combinedcard.txt\n'
                                       'Never build from a glob.\n')
    result = compare_package(load_golden_fixture(fixture_path), package)
    assert not any(row["artifact"] == "README.md" for row in result["semantic_contract_mismatches"])


def test_readme_rejects_reversed_command_order(tmp_path):
    package, fixture_path = _combined(tmp_path)
    (package / "README.md").write_text('combineCards.py "${cards[@]}" > combinedcard.txt\n'
                                       'mapfile -t cards < ordered_card_inputs.txt\nDo not use a glob.\n')
    result = compare_package(load_golden_fixture(fixture_path), package)
    assert any(row["artifact"] == "README.md" for row in result["semantic_contract_mismatches"])


def test_combined_mapping_mismatch(tmp_path):
    package, fixture_path = _combined(tmp_path)
    path = package / "combined_mapping_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["rows"][0]["combined_chN"] = "ch9"
    _write_json(path, manifest)
    result = compare_package(load_golden_fixture(fixture_path), package)
    assert any(row["artifact"] == "combined_mapping" for row in result["semantic_contract_mismatches"])


@pytest.mark.parametrize("file_name,kind", [("selectedWCs.txt", "selected_wcs"), ("scalings.json", "scalings.json")])
def test_per_era_auxiliary_hash_mismatch(tmp_path, file_name, kind):
    package, fixture_path, mapping = _per_era(tmp_path)
    (package / file_name).write_bytes(b"changed")
    result = compare_package(load_golden_fixture(fixture_path), package, mapping)
    assert any(row["kind"] == kind for row in result["payload_mismatches"])


def test_allowed_provenance_differences_are_reported(tmp_path):
    package, fixture_path = _combined(tmp_path)
    path = package / "package-provenance.json"
    provenance = json.loads(path.read_text())
    provenance.update({"package_root": "new-root", "package_date": "260924", "package_version": "v2",
                       "assembler_commit": "0" * 40, "assembler_source_sha256": "1" * 64,
                       "created_at": "2026-09-24T00:00:00Z"})
    _write_json(path, provenance)
    result = compare_package(load_golden_fixture(fixture_path), package)
    assert {row["key"] for row in result["allowed_provenance_deltas"]} >= {
        "package_root", "package_date", "package_version", "assembler_commit",
        "assembler_source_sha256", "created_at"}
    assert result["unexpected_provenance_deltas"] == []


def test_unexpected_provenance_key_detected(tmp_path):
    package, fixture_path = _combined(tmp_path)
    path = package / "package-provenance.json"
    provenance = json.loads(path.read_text())
    provenance["new_semantics"] = "changed"
    _write_json(path, provenance)
    result = compare_package(load_golden_fixture(fixture_path), package)
    assert any(row["key"] == "new_semantics" for row in result["unexpected_provenance_deltas"])


@pytest.mark.parametrize("mapping_equal", [True, False])
def test_source_mapping_digest_requires_equal_semantics(tmp_path, mapping_equal):
    package, fixture_path = _combined(tmp_path)
    provenance_path = package / "package-provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["source_mapping_sha256"] = {"run2": "0" * 64, "run3": "1" * 64}
    _write_json(provenance_path, provenance)
    if not mapping_equal:
        manifest_path = package / "combined_mapping_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["rows"][0]["per_era_chN"] = "ch9"
        _write_json(manifest_path, manifest)
    result = compare_package(load_golden_fixture(fixture_path), package)
    bucket = "allowed_provenance_deltas" if mapping_equal else "unexpected_provenance_deltas"
    assert any(row["key"] == "source_mapping_sha256" for row in result[bucket])
    other = "unexpected_provenance_deltas" if mapping_equal else "allowed_provenance_deltas"
    assert not any(row["key"] == "source_mapping_sha256" for row in result[other])


@pytest.mark.parametrize("mutation", ["allowed_variable_keys", "conditional_digest_deltas"])
def test_v1_provenance_fixture_contract_is_closed(tmp_path, mutation):
    _, fixture_path = _combined(tmp_path)
    fixture = json.loads(fixture_path.read_text())
    contract = fixture["provenance_comparison_contract"]
    if mutation == "allowed_variable_keys":
        contract[mutation].append("new_semantics")
    else:
        contract[mutation]["source_mapping_sha256"] = "weaker_basis"
    _write_json(fixture_path, fixture)
    with pytest.raises(ValueError, match="provenance key contract"):
        load_golden_fixture(fixture_path)


def test_missing_required_provenance_semantics_detected(tmp_path):
    package, fixture_path = _combined(tmp_path)
    path = package / "package-provenance.json"
    provenance = json.loads(path.read_text())
    del provenance["schema"]
    _write_json(path, provenance)
    result = compare_package(load_golden_fixture(fixture_path), package)
    assert any(row.get("key") == "schema" and row.get("reason") == "missing_required_key" for row in result["semantic_contract_mismatches"])


@pytest.mark.parametrize("mutation", ["internal_path", "round_label", "malformed"])
def test_fixture_validation_rejects_internal_or_malformed(tmp_path, mutation):
    _, fixture_path = _combined(tmp_path)
    fixture = json.loads(fixture_path.read_text())
    if mutation == "internal_path":
        fixture["source_path"] = "/groups/private/package"
    elif mutation == "round_label":
        fixture["source_label"] = "t0_datacards_004J"
    else:
        fixture["payload"]["txt"]["Run2_alpha.txt"] = "bad-hash"
    _write_json(fixture_path, fixture)
    with pytest.raises(ValueError):
        load_golden_fixture(fixture_path)
