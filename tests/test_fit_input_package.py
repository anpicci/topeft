"""Focused synthetic checks for the portable fit-input projection."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from analysis.topeft_run2 import build_fit_input_package as fit_input


_mapping_fields = {
    "era", "physical_name", "per_era_chN", "combined_chN",
    "combined_order_index", "destination_txt_name", "destination_root_name",
}


def _write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _refresh_hashes(package):
    provenance_path = package / "package-provenance.json"
    provenance = json.loads(provenance_path.read_text())
    for name, field in (
        ("scalings.json", "scalings_sha256"),
        ("ordered_card_inputs.txt", "ordered_card_inputs_sha256"),
        ("combined_mapping_manifest.json", "manifest_sha256"),
    ):
        provenance[field] = _sha256(package / name)
    _write_json(provenance_path, provenance)


def _fixture(tmp_path):
    config = tmp_path / "plain-config.yml"
    config.write_text(
        "analysis: TOP_26_006\nwc_population:\n  scientific: [ctW]\n"
        "  fixed_zero: [ctu1]\nwc_ranges:\n  ctW: [-3.0, 3.0]\n",
        encoding="utf-8",
    )
    package = tmp_path / "combined"
    cards = package / "cards"
    cards.mkdir(parents=True)
    for name in ("one", "two"):
        (cards / f"{name}.txt").write_bytes(f"shapes * * {name}.root $PROCESS\n".encode())
        (cards / f"{name}.root").write_bytes(f"synthetic-{name}\x00".encode())
    (package / "ordered_card_inputs.txt").write_text(
        "cards/two.txt\ncards/one.txt\n", encoding="utf-8")
    _write_json(package / "scalings.json", [{"channel": "ch1"}, {"channel": "ch2"}])
    rows = []
    for index, name in enumerate(("two", "one"), start=1):
        rows.append({
            "era": "run2", "physical_name": name, "per_era_chN": f"ch{index}",
            "combined_chN": f"ch{index}", "combined_order_index": index,
            "destination_txt_name": f"{name}.txt",
            "destination_root_name": f"{name}.root",
            "source_txt_path": "/groups/historical/card.txt",
        })
    _write_json(package / "combined_mapping_manifest.json", {
        "schema": "TOP26006_v1", "artifact_type": "combined_mapping_manifest",
        "package_root": "/groups/historical/package", "rows": rows,
    })
    (package / "README.md").write_text(
        "Historical source at /groups/historical/package\n", encoding="utf-8")
    _write_json(package / "package-provenance.json", {
        "schema": "TOP26006_v1", "artifact_type": "package_provenance",
        "analysis": "TOP-26-006", "package_root": "/groups/historical/package",
        "package_version": "v1", "package_date": "260925",
        "assembler_commit": "a" * 40,
        "source_mapping_sha256": {"run2": "b" * 64},
    })
    _refresh_hashes(package)
    return config, package, tmp_path / "fit-input"


def test_valid_projection_copies_only_consumer_bytes(tmp_path):
    config, package, output = _fixture(tmp_path)
    source_bytes = {
        path.relative_to(package).as_posix(): path.read_bytes()
        for path in (package / "cards").rglob("*") if path.is_file()
    }
    source_bytes.update({name: (package / name).read_bytes()
                         for name in ("scalings.json", "ordered_card_inputs.txt")})
    result = fit_input.build_fit_input_package(
        package, config, output, package_build_topeft_commit="c" * 40,
        t0_topeft_commit="d" * 40, t0_topcoffea_commit="e" * 40)
    observed = json.loads((output / "fit-input-manifest.json").read_text())
    assert result == observed
    assert {path.relative_to(output / "datacards").as_posix(): path.read_bytes()
            for path in (output / "datacards").rglob("*") if path.is_file()} == source_bytes
    assert (output / "config" / "TOP_26_006.yml").read_bytes() == config.read_bytes()
    assert observed["fit_config"] == {
        "path": "config/TOP_26_006.yml", "sha256": _sha256(config)}
    assert observed["datacards"]["input_snapshot_sha256"] == hashlib.sha256(
        fit_input._json_bytes(observed["datacards"]["files"])).hexdigest()
    assert observed["datacards"]["files"] == sorted(
        observed["datacards"]["files"], key=lambda row: row["path"])
    rows = observed["datacards"]["channel_mapping"]["rows"]
    assert [set(row) for row in rows] == [_mapping_fields, _mapping_fields]
    assert [row["destination_txt_name"] for row in rows] == ["two.txt", "one.txt"]
    assert observed["provenance"]["package_build"]["topeft_commit"] == "c" * 40
    assert observed["provenance"]["upstream_t0"] == {
        "topeft_commit": "d" * 40, "topcoffea_commit": "e" * 40}
    assert observed["provenance"]["source_datacard_package"]["package_version"] == "v1"
    assert "/groups/historical" not in (output / "fit-input-manifest.json").read_text()
    readme = (output / "README.md").read_text()
    assert "/groups/historical" not in readme
    for phrase in ("sole card-order authority", "wildcard or glob", "scalings.json",
                   "cards/<name>.txt", "leading `cards/`", "writable cards directory",
                   'combineCards.py "${ordered_basenames[@]}" > combinedcard.txt',
                   "TOPEFT documents this command but does not execute it"):
        assert phrase in readme
    assert not (output / "combinedcard.txt").exists()
    assert not (output / "selectedWCs.txt").exists()
    inventory_path = os.environ.get("FIT_INPUT_SYNTHETIC_INVENTORY_PATH")
    if inventory_path:
        Path(inventory_path).write_text(json.dumps({
            "source_package": str(package), "source_config": str(config),
            "output_package": str(output),
        }, sort_keys=True) + "\n", encoding="utf-8")


@pytest.mark.parametrize("ordered", [
    "", "cards/two.txt\ncards/two.txt\n", "/tmp/two.txt\n",
    "cards/../two.txt\n", "../cards/two.txt\n", "cards/missing.txt\n",
    "cards/nested/two.txt\n", "cards/one.root\n",
])
def test_ordered_card_inputs_fail_closed(tmp_path, ordered):
    config, package, output = _fixture(tmp_path)
    (package / "ordered_card_inputs.txt").write_text(ordered, encoding="utf-8")
    _refresh_hashes(package)
    with pytest.raises(fit_input.FitInputError):
        fit_input.build_fit_input_package(package, config, output)
    assert not output.exists()


@pytest.mark.parametrize("member", ["cards/one.root", "scalings.json"])
def test_symlink_source_fails_closed(tmp_path, member):
    config, package, output = _fixture(tmp_path)
    path = package / member
    path.unlink()
    path.symlink_to(package / "cards" / "one.txt")
    with pytest.raises(fit_input.FitInputError):
        fit_input.build_fit_input_package(package, config, output)
    assert not output.exists()


@pytest.mark.parametrize("content", [None, "analysis: [bad\n", "analysis: wrong\n"])
def test_missing_or_malformed_config_has_no_fallback(tmp_path, content):
    config, package, output = _fixture(tmp_path)
    if content is None:
        config.unlink()
    else:
        config.write_text(content, encoding="utf-8")
    with pytest.raises(fit_input.FitInputError):
        fit_input.build_fit_input_package(package, config, output)
    assert not output.exists()


@pytest.mark.parametrize("kind", ["output", "staging", "source_inside_output", "output_inside_source"])
def test_existing_or_overlapping_paths_fail_closed(tmp_path, kind):
    config, package, output = _fixture(tmp_path)
    if kind == "output":
        output.mkdir()
    elif kind == "staging":
        (tmp_path / ".fit-input.staging").mkdir()
    elif kind == "source_inside_output":
        output = tmp_path
    else:
        output = package / "nested-output"
    with pytest.raises(fit_input.FitInputError):
        fit_input.build_fit_input_package(package, config, output)


@pytest.mark.parametrize("name", ["combinedcard.txt", "selectedWCs.txt"])
def test_downstream_owned_card_artifacts_rejected(tmp_path, name):
    config, package, output = _fixture(tmp_path)
    (package / "cards" / name).write_bytes(b"not an input")
    with pytest.raises(fit_input.FitInputError, match="downstream-owned"):
        fit_input.build_fit_input_package(package, config, output)
    assert not output.exists()


def test_arbitrary_card_name_is_not_statistical_ownership_proxy(tmp_path):
    config, package, output = _fixture(tmp_path)
    (package / "cards" / "impacts.root").write_bytes(b"opaque template")
    fit_input.build_fit_input_package(package, config, output)
    assert (output / "datacards" / "cards" / "impacts.root").read_bytes() == b"opaque template"


def test_provenance_variation_does_not_change_input_identities(tmp_path):
    config, package, first = _fixture(tmp_path)
    second = tmp_path / "second-fit-input"
    one = fit_input.build_fit_input_package(
        package, config, first, package_build_topeft_commit="a" * 40,
        t0_topeft_commit="b" * 40, t0_topcoffea_commit="c" * 40)
    two = fit_input.build_fit_input_package(
        package, config, second, package_build_topeft_commit="d" * 40,
        t0_topeft_commit="e" * 40, t0_topcoffea_commit="f" * 40)
    assert one["provenance"] != two["provenance"]
    assert one["datacards"]["input_snapshot_sha256"] == two["datacards"]["input_snapshot_sha256"]
    assert one["fit_config"]["sha256"] == two["fit_config"]["sha256"]


def test_source_location_disguised_as_provenance_is_omitted(tmp_path):
    config, package, output = _fixture(tmp_path)
    provenance_path = package / "package-provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["package_version"] = "/groups/historical/package"
    provenance["source_scalings_sha256"] = {"run2": "/groups/historical/scalings.json"}
    _write_json(provenance_path, provenance)
    manifest = fit_input.build_fit_input_package(package, config, output)
    source_fields = manifest["provenance"]["source_datacard_package"]
    assert "package_version" not in source_fields
    assert "source_scalings_sha256" not in source_fields
    assert "/groups/historical" not in (output / "fit-input-manifest.json").read_text()


def test_cli_uses_plain_config_file_without_git(tmp_path, capsys):
    config, package, output = _fixture(tmp_path)
    assert fit_input.main(["--combined-package", str(package), "--fit-config", str(config),
                           "--output", str(output)]) == 0
    response = json.loads(capsys.readouterr().out)
    manifest = json.loads((output / "fit-input-manifest.json").read_text())
    assert response["input_snapshot_sha256"] == manifest["datacards"]["input_snapshot_sha256"]


def test_non_regular_card_member_fails_closed(tmp_path):
    config, package, output = _fixture(tmp_path)
    os.mkfifo(package / "cards" / "named_pipe")
    with pytest.raises(fit_input.FitInputError, match="non-regular"):
        fit_input.build_fit_input_package(package, config, output)
    assert not output.exists()


def test_mapping_order_or_required_field_fails_closed(tmp_path):
    config, package, output = _fixture(tmp_path)
    path = package / "combined_mapping_manifest.json"
    mapping = json.loads(path.read_text())
    mapping["rows"][0]["destination_txt_name"] = "one.txt"
    _write_json(path, mapping)
    _refresh_hashes(package)
    with pytest.raises(fit_input.FitInputError, match="disagrees"):
        fit_input.build_fit_input_package(package, config, output)
    assert not output.exists()
