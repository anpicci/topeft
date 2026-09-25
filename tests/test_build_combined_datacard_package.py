"""Focused source-bound tests for the maintained combined package."""

import copy
import json
from pathlib import Path

import pytest

from analysis.topeft_run2 import build_combined_datacard_package as combined
from topeft.modules import datacard_packaging


def _write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _source(tmp_path, era, names):
    root = tmp_path / era
    cards = root / "cards"
    cards.mkdir(parents=True)
    mapping = datacard_packaging.build_per_era_mapping(names)
    records = []
    for row in mapping:
        name = row["physical_name"]
        stem = f"ttx_multileptons-{name}"
        (cards / f"{stem}.root").write_bytes(b"ROOT\x00" + era.encode() + name.encode())
        (cards / f"{stem}.txt").write_bytes(
            f"shapes *  * {stem}.root $PROCESS $PROCESS_$SYSTEMATIC\n"
            f"bin bin_{name}\nprocess ttH_sm\nrate 1.0\n".encode())
        records.append({"channel": row["per_era_chN"], "process": "ttH_sm",
                        "parameters": ["cSM[1]"], "scaling": [[1.0, 2.0]],
                        "extra": {"nested": [era, name]}})
    _write_json(root / "physical_to_chN.json", mapping)
    _write_json(root / "scalings.json", records)
    _write_json(root / "selectedWCs.txt", {"ttH_sm": ["cSM"]})
    _write_json(root / "package-provenance.json", {
        "schema": "TOP26006_v1", "artifact_type": "package_provenance", "analysis": "TOP-26-006",
        "era": era, "package_root": str(root), "packaged_txt_count": len(mapping),
        "packaged_root_count": len(mapping),
        "selected_wcs_sha256": datacard_packaging.sha256_file(root / "selectedWCs.txt"),
        "scalings_sha256": datacard_packaging.sha256_file(root / "scalings.json"),
        "physical_to_chN_sha256": datacard_packaging.sha256_file(root / "physical_to_chN.json"),
        "source_manifest_sha256s": [], "source_unit_count": 1,
        "builder_git_head": "a" * 40, "builder_source_sha256": "b" * 64,
        "builder_git_dirty": False,
    })
    return root


@pytest.fixture
def sources(tmp_path):
    return (_source(tmp_path, "run2", ["z", "a"]), _source(tmp_path, "run3", ["b"]))


def _build(tmp_path, sources):
    output = tmp_path / "combined"
    combined.build_combined_package(*sources, output, "TOP-26-006", "260925", "v1")
    return output


def _manifest(output):
    return json.loads((output / "combined_mapping_manifest.json").read_text())


def _refresh_hash(output, key, file_name):
    provenance_path = output / "package-provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance[key] = datacard_packaging.sha256_file(output / file_name)
    _write_json(provenance_path, provenance)


def test_build_and_public_certify(tmp_path, sources):
    output = _build(tmp_path, sources)
    result = combined.certify_combined_package(output, *sources)
    assert result["certified"] is True
    assert result["card_count"] == 3
    assert {path.name for path in output.iterdir()} == combined._output_names
    assert not (output / "selectedWCs.txt").exists()
    assert not (output / "combinedcard.txt").exists()
    assert not (tmp_path / ".combined.staging").exists()
    manifest = _manifest(output)
    rows = manifest["rows"]
    assert [(row["era"], row["physical_name"], row["per_era_chN"], row["combined_chN"])
            for row in rows] == [("run2", "z", "ch1", "ch1"),
                                 ("run2", "a", "ch2", "ch2"),
                                 ("run3", "b", "ch1", "ch3")]
    assert [row["destination_txt_name"] for row in rows] == [
        "Run2_ttx_multileptons-z.txt", "Run2_ttx_multileptons-a.txt", "Run3_ttx_multileptons-b.txt"]
    order = (output / "ordered_card_inputs.txt").read_text().splitlines()
    assert order == ["cards/" + row["destination_txt_name"] for row in rows]
    for row in rows:
        source = sources[0] if row["era"] == "run2" else sources[1]
        stem = f"ttx_multileptons-{row['physical_name']}"
        assert (output / "cards" / row["destination_root_name"]).read_bytes() == (
            source / "cards" / f"{stem}.root").read_bytes()
        source_bytes = (source / "cards" / f"{stem}.txt").read_bytes()
        destination_bytes = (output / "cards" / row["destination_txt_name"]).read_bytes()
        assert destination_bytes == source_bytes.replace(
            f"{stem}.root".encode(), row["destination_root_name"].encode(), 1)
        assert f"bin_{row['physical_name']}".encode() in destination_bytes
    scalings = json.loads((output / "scalings.json").read_text())
    assert [record["channel"] for record in scalings] == ["ch1", "ch2", "ch3"]
    assert [record["extra"]["nested"][0] for record in scalings] == ["run2", "run2", "run3"]
    provenance = json.loads((output / "package-provenance.json").read_text())
    assert provenance["package_root"] == manifest["package_root"] == str(output)
    assert str(tmp_path / ".combined.staging") not in (output / "README.md").read_text()
    readme = (output / "README.md").read_text()
    assert "mapfile -t cards < ordered_card_inputs.txt" in readme
    assert 'combineCards.py "${cards[@]}" > combinedcard.txt' in readme
    assert "wildcard/glob" in readme


def test_cli_surface():
    with pytest.raises(SystemExit) as exc:
        combined.main(["build", "--help"])
    assert exc.value.code == 0
    with pytest.raises(SystemExit):
        combined.main(["build", "--legacy-certificate", "x"])
    with pytest.raises(SystemExit):
        combined.main(["build", "--dry-run"])
    with pytest.raises(SystemExit):
        combined.main(["certify", "--package-root", "/tmp/missing"])


@pytest.mark.parametrize("change", ["role", "flat", "missing_mapping", "missing_scalings", "missing_card", "bad_mapping"])
def test_source_boundary_rejects_invalid_package(tmp_path, sources, change):
    run2, run3 = sources
    if change == "role":
        with pytest.raises(ValueError):
            combined.build_combined_package(run3, run2, tmp_path / "combined", "TOP-26-006", "260925", "v1")
        return
    if change == "flat":
        (run2 / "flat.txt").write_text("x")
    elif change == "missing_mapping":
        (run2 / "physical_to_chN.json").unlink()
    elif change == "missing_scalings":
        (run2 / "scalings.json").unlink()
    elif change == "missing_card":
        (run2 / "cards" / "ttx_multileptons-z.root").unlink()
    else:
        mapping = json.loads((run2 / "physical_to_chN.json").read_text())
        mapping[1]["per_era_chN"] = "ch1"
        _write_json(run2 / "physical_to_chN.json", mapping)
    with pytest.raises((ValueError, FileNotFoundError)):
        _build(tmp_path, sources)
    assert not (tmp_path / "combined").exists()


@pytest.mark.parametrize("target", ["output", "staging"])
def test_existing_destination_blocks_before_mutation(tmp_path, sources, target):
    path = tmp_path / ("combined" if target == "output" else ".combined.staging")
    path.mkdir()
    with pytest.raises(ValueError):
        _build(tmp_path, sources)
    assert list(path.iterdir()) == []


def test_ambiguous_source_template_preserves_staging(tmp_path, sources):
    card = sources[0] / "cards" / "ttx_multileptons-z.txt"
    card.write_bytes(card.read_bytes().replace(b"ttx_multileptons-z.root", b"different.root"))
    with pytest.raises(ValueError, match="ambiguous"):
        _build(tmp_path, sources)
    assert not (tmp_path / "combined").exists()
    assert (tmp_path / ".combined.staging").is_dir()


@pytest.mark.parametrize("target", ["root", "txt", "scalings", "order", "mapping"])
def test_certifier_rejects_corrupted_output_even_with_updated_metadata(tmp_path, sources, target):
    output = _build(tmp_path, sources)
    row = _manifest(output)["rows"][0]
    if target == "root":
        (output / "cards" / row["destination_root_name"]).write_bytes(b"bad")
    elif target == "txt":
        card = output / "cards" / row["destination_txt_name"]
        card.write_bytes(card.read_bytes().replace(b"rate 1.0", b"rate 2.0"))
    elif target == "scalings":
        records = json.loads((output / "scalings.json").read_text())
        records[0]["extra"]["nested"][0] = "bad"
        (output / "scalings.json").write_bytes(combined._scalings_bytes(records))
        _refresh_hash(output, "scalings_sha256", "scalings.json")
    elif target == "order":
        path = output / "ordered_card_inputs.txt"
        lines = path.read_text().splitlines()
        path.write_text("\n".join(reversed(lines)) + "\n")
        _refresh_hash(output, "ordered_card_inputs_sha256", "ordered_card_inputs.txt")
    else:
        manifest = _manifest(output)
        manifest["rows"][0]["combined_chN"] = "ch99"
        _write_json(output / "combined_mapping_manifest.json", manifest)
        _refresh_hash(output, "manifest_sha256", "combined_mapping_manifest.json")
    with pytest.raises(ValueError):
        combined.certify_combined_package(output, *sources)


@pytest.mark.parametrize("target", ["root", "txt", "scalings", "role"])
def test_certifier_is_bound_to_supplied_sources(tmp_path, sources, target):
    output = _build(tmp_path, sources)
    if target == "role":
        with pytest.raises(ValueError):
            combined.certify_combined_package(output, sources[1], sources[0])
        return
    if target == "root":
        path = sources[0] / "cards" / "ttx_multileptons-z.root"
        path.write_bytes(b"changed")
    elif target == "txt":
        path = sources[0] / "cards" / "ttx_multileptons-z.txt"
        path.write_bytes(path.read_bytes().replace(b"rate 1.0", b"rate 2.0"))
    else:
        path = sources[0] / "scalings.json"
        records = json.loads(path.read_text())
        records[0]["extra"]["nested"].append("changed")
        _write_json(path, records)
        provenance_path = sources[0] / "package-provenance.json"
        provenance = json.loads(provenance_path.read_text())
        provenance["scalings_sha256"] = datacard_packaging.sha256_file(path)
        _write_json(provenance_path, provenance)
    with pytest.raises(ValueError):
        combined.certify_combined_package(output, *sources)


def test_scaling_writer_keeps_independent_records_and_rejects_duplicates(sources):
    run2 = json.loads((sources[0] / "scalings.json").read_text())
    run3 = json.loads((sources[1] / "scalings.json").read_text())
    mapping = datacard_packaging.build_combined_mapping(
        json.loads((sources[0] / "physical_to_chN.json").read_text()),
        json.loads((sources[1] / "physical_to_chN.json").read_text()))
    result = combined._combine_scalings(run2, run3, mapping)
    result[0]["extra"]["nested"].append("writer mutation")
    assert run2[0]["extra"]["nested"] == ["run2", "z"]
    duplicate = copy.deepcopy(run2[0])
    with pytest.raises(ValueError, match="duplicate"):
        combined._combine_scalings(run2 + [duplicate], run3, mapping)


def test_writer_corruption_is_caught_by_independent_certifier(tmp_path, sources, monkeypatch):
    original = datacard_packaging.build_combined_mapping

    def corrupt_mapping(*args):
        rows = original(*args)
        rows[0]["destination_txt_name"] = "wrong.txt"
        return rows

    monkeypatch.setattr(datacard_packaging, "build_combined_mapping", corrupt_mapping)
    with pytest.raises(ValueError):
        _build(tmp_path, sources)
    assert not (tmp_path / "combined").exists()
    assert (tmp_path / ".combined.staging").is_dir()


def test_order_writer_corruption_is_caught_by_independent_certifier(tmp_path, sources, monkeypatch):
    original = datacard_packaging.build_ordered_card_inputs
    monkeypatch.setattr(datacard_packaging, "build_ordered_card_inputs", lambda rows: list(reversed(original(rows))))
    with pytest.raises(ValueError):
        _build(tmp_path, sources)
    assert not (tmp_path / "combined").exists()


def test_scaling_writer_corruption_is_caught_by_independent_certifier(tmp_path, sources, monkeypatch):
    original = combined._combine_scalings

    def corrupt_scalings(*args):
        records = original(*args)
        records[0]["scaling"][0][0] += 1
        return records

    monkeypatch.setattr(combined, "_combine_scalings", corrupt_scalings)
    with pytest.raises(ValueError):
        _build(tmp_path, sources)
    assert not (tmp_path / "combined").exists()


def test_txt_writer_corruption_is_caught_by_independent_certifier(tmp_path, sources, monkeypatch):
    original = combined._rewrite_card

    def corrupt_card(*args):
        return original(*args).replace(b"rate 1.0", b"rate 2.0")

    monkeypatch.setattr(combined, "_rewrite_card", corrupt_card)
    with pytest.raises(ValueError):
        _build(tmp_path, sources)
    assert not (tmp_path / "combined").exists()
