import hashlib
import json
from pathlib import Path

import pytest

from analysis.topeft_run2 import consolidate_datacard_metadata as consolidator


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def make_unit(tmp_path, unit_id, channel, records, selected_wcs):
    root = tmp_path / "sources" / unit_id
    receipt = root / "receipt.json"
    scalings = root / "scalings-preselect.json"
    selected = root / "selectedWCs.txt"
    write_json(receipt, {"accepted": True, "unit": unit_id})
    write_json(scalings, records)
    write_json(selected, selected_wcs)
    return {
        "era": "run3",
        "execution_unit_id": unit_id,
        "attempt_id": "attempt_01",
        "receipt_path": str(receipt),
        "receipt_sha256": sha256(receipt),
        "scalings_snapshot_path": str(scalings),
        "scalings_snapshot_sha256": sha256(scalings),
        "selectedWCs_snapshot_path": str(selected),
        "selectedWCs_snapshot_sha256": sha256(selected),
        "owned_scientific_target_identities": [
            {
                "era": "run3",
                "physical_channel": channel,
                "distribution": "x",
            }
        ],
    }


def record(channel, process):
    return {
        "channel": f"{channel}_x",
        "process": process,
        "parameters": ["cSM[1]"],
        "scaling": [[1.0]],
    }


def write_registry(tmp_path, units):
    path = tmp_path / "registry.json"
    write_json(
        path,
        {
            "schema": consolidator.REGISTRY_SCHEMA,
            "accepted": True,
            "source_registry_identity_sha256": "registry-identity",
            "units": units,
        },
    )
    return path


def read_outputs(output_dir):
    return (
        json.loads((output_dir / "scalings-preselect.json").read_text()),
        json.loads((output_dir / "selectedWCs.txt").read_text()),
    )


def test_disjoint_successful_fragments_merge_completely(tmp_path):
    units = [
        make_unit(tmp_path, "unit_a", "a", [record("a", "p")], {"p": ["c1"]}),
        make_unit(tmp_path, "unit_b", "b", [record("b", "q")], {"q": ["c2"]}),
    ]
    output = tmp_path / "output"

    summary = consolidator.consolidate_metadata(
        write_registry(tmp_path, units), "run3", output
    )

    scalings, selected = read_outputs(output)
    assert scalings == [record("a", "p"), record("b", "q")]
    assert selected == {"p": ["c1"], "q": ["c2"]}
    assert summary["source_unit_count"] == 2


def test_duplicate_scaling_identity_fails_closed(tmp_path):
    duplicate = record("a", "p")
    units = [
        make_unit(tmp_path, "unit_a", "a", [duplicate], {"p": ["c1"]}),
        make_unit(tmp_path, "unit_b", "a", [duplicate], {"p": ["c1"]}),
    ]

    with pytest.raises(ValueError, match="duplicate scaling identity"):
        consolidator.consolidate_metadata(
            write_registry(tmp_path, units), "run3", tmp_path / "output"
        )
    assert not (tmp_path / "output").exists()


def test_differing_selected_wcs_form_deterministic_union(tmp_path):
    units = [
        make_unit(
            tmp_path, "unit_a", "a", [record("a", "p")], {"p": ["c2", "c1"]}
        ),
        make_unit(
            tmp_path,
            "unit_b",
            "b",
            [record("b", "q")],
            {"p": ["c1", "c3"], "q": ["c4"]},
        ),
    ]
    output = tmp_path / "output"

    consolidator.consolidate_metadata(write_registry(tmp_path, units), "run3", output)

    assert read_outputs(output)[1] == {"p": ["c2", "c1", "c3"], "q": ["c4"]}


def test_unlisted_fragment_is_not_discovered(tmp_path):
    unit = make_unit(tmp_path, "listed", "a", [record("a", "p")], {"p": ["c1"]})
    write_json(
        tmp_path / "sources/unlisted/scalings-preselect.json",
        [record("unexpected", "bad")],
    )
    write_json(tmp_path / "sources/unlisted/selectedWCs.txt", {"bad": ["c9"]})
    output = tmp_path / "output"

    consolidator.consolidate_metadata(
        write_registry(tmp_path, [unit]), "run3", output
    )

    assert read_outputs(output) == ([record("a", "p")], {"p": ["c1"]})


def test_missing_declared_fragment_fails(tmp_path):
    unit = make_unit(tmp_path, "unit_a", "a", [record("a", "p")], {"p": ["c1"]})
    Path(unit["scalings_snapshot_path"]).unlink()

    with pytest.raises(ValueError, match="cannot read declared source"):
        consolidator.consolidate_metadata(
            write_registry(tmp_path, [unit]), "run3", tmp_path / "output"
        )


def test_identical_explicit_inputs_reproduce_identical_bytes(tmp_path):
    units = [
        make_unit(tmp_path, "unit_a", "a", [record("a", "p")], {"p": ["c2"]}),
        make_unit(tmp_path, "unit_b", "b", [record("b", "q")], {"p": ["c1"]}),
    ]
    registry = write_registry(tmp_path, units)
    first = tmp_path / "first"
    second = tmp_path / "second"

    consolidator.consolidate_metadata(registry, "run3", first)
    consolidator.consolidate_metadata(registry, "run3", second)

    assert (first / "scalings-preselect.json").read_bytes() == (
        second / "scalings-preselect.json"
    ).read_bytes()
    assert (first / "selectedWCs.txt").read_bytes() == (
        second / "selectedWCs.txt"
    ).read_bytes()
