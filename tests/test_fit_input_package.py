"""Focused synthetic checks for the portable fit input wrapper."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from analysis.topeft_run2 import build_fit_input_package as fit_input


def _write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path):
    repo = tmp_path / "repo"
    config = repo / "topeft" / "params" / "fits" / "TOP_26_006.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "analysis: TOP_26_006\nwc_population:\n  scientific: [ctW]\n"
        "  fixed_zero: [ctu1]\nwc_ranges:\n  ctW: [-3.0, 3.0]\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "topeft/params/fits/TOP_26_006.yml"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture",
                    "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"], check=True)
    package = tmp_path / "combined"
    cards = package / "cards"
    cards.mkdir(parents=True)
    (cards / "one.txt").write_bytes(b"shapes * * one.root $PROCESS\n")
    (cards / "one.root").write_bytes(b"synthetic-root-bytes\x00")
    (package / "ordered_card_inputs.txt").write_text("cards/one.txt\n", encoding="utf-8")
    _write_json(package / "scalings.json", [{"channel": "ch1"}])
    _write_json(package / "combined_mapping_manifest.json", {
        "schema": "TOP26006_v1", "artifact_type": "combined_mapping_manifest",
        "rows": [{"combined_order_index": 1, "destination_txt_name": "one.txt"}],
    })
    (package / "README.md").write_text("Synthetic combined package.\n", encoding="utf-8")
    _write_json(package / "package-provenance.json", {
        "schema": "TOP26006_v1", "artifact_type": "package_provenance", "analysis": "TOP-26-006",
        "scalings_sha256": _sha256(package / "scalings.json"),
        "ordered_card_inputs_sha256": _sha256(package / "ordered_card_inputs.txt"),
        "manifest_sha256": _sha256(package / "combined_mapping_manifest.json"),
    })
    return repo, config, package, tmp_path / "fit-input"


def test_valid_package_copies_bytes_and_binds_identity(tmp_path):
    repo, config, package, output = _fixture(tmp_path)
    expected = {path.relative_to(package).as_posix(): path.read_bytes()
                for path in package.rglob("*") if path.is_file()}
    result = fit_input.build_fit_input_package(package, repo, output)
    observed = json.loads((output / "fit-input-manifest.json").read_text())
    assert result == observed
    assert {path.relative_to(output / "datacards").as_posix(): path.read_bytes()
            for path in (output / "datacards").rglob("*") if path.is_file()} == expected
    assert (output / "config" / "TOP_26_006.yml").read_bytes() == config.read_bytes()
    assert observed["fit_config"]["sha256"] == _sha256(config)
    assert observed["fit_config"]["source_git_commit"] == subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
        stdout=subprocess.PIPE, text=True).stdout.strip()
    files = observed["datacards"]["files"]
    assert files == sorted(files, key=lambda row: row["path"])
    assert observed["datacards"]["content_sha256"] == hashlib.sha256(
        fit_input._json_bytes(files)).hexdigest()
    assert str(repo) not in (output / "fit-input-manifest.json").read_text()
    assert str(package) not in (output / "README.md").read_text()
    assert not (output / "selectedWCs.txt").exists()
    assert not (output / "datacards" / "selectedWCs.txt").exists()
    inventory_path = os.environ.get("FIT_INPUT_SYNTHETIC_INVENTORY_PATH")
    if inventory_path:
        Path(inventory_path).write_text(json.dumps({
            "fixture": "synthetic combined datacard package and synthetic Git config",
            "source_members": sorted(expected),
            "source_and_destination_bytes_equal": True,
            "config_bytes_equal": True,
            "datacards_content_sha256": observed["datacards"]["content_sha256"],
            "fit_config_sha256": observed["fit_config"]["sha256"],
            "source_git_commit": observed["fit_config"]["source_git_commit"],
            "wrapper_members": sorted(path.relative_to(output).as_posix()
                                      for path in output.rglob("*") if path.is_file()),
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@pytest.mark.parametrize("ordered", ["", "cards/one.txt\ncards/one.txt\n",
                                     "/tmp/one.txt\n", "cards/../one.txt\n",
                                     "../cards/one.txt\n", "cards/missing.txt\n"])
def test_ordered_card_inputs_fail_closed(tmp_path, ordered):
    repo, _, package, output = _fixture(tmp_path)
    (package / "ordered_card_inputs.txt").write_text(ordered, encoding="utf-8")
    with pytest.raises(fit_input.FitInputError):
        fit_input.build_fit_input_package(package, repo, output)
    assert not output.exists()


@pytest.mark.parametrize("member", ["cards/one.root", "README.md"])
def test_symlink_member_fails_closed(tmp_path, member):
    repo, _, package, output = _fixture(tmp_path)
    path = package / member
    path.unlink()
    path.symlink_to(package / "cards" / "one.txt")
    with pytest.raises(fit_input.FitInputError):
        fit_input.build_fit_input_package(package, repo, output)
    assert not output.exists()


@pytest.mark.parametrize("content", [None, "analysis: [bad\n", "analysis: wrong\n"])
def test_missing_or_malformed_config_has_no_fallback(tmp_path, content):
    repo, config, package, output = _fixture(tmp_path)
    if content is None:
        config.unlink()
    else:
        config.write_text(content, encoding="utf-8")
    with pytest.raises(fit_input.FitInputError):
        fit_input.build_fit_input_package(package, repo, output)
    assert not output.exists()


@pytest.mark.parametrize("kind", ["output", "staging", "source_inside_output", "output_inside_source"])
def test_existing_or_overlapping_paths_fail_closed(tmp_path, kind):
    repo, _, package, output = _fixture(tmp_path)
    if kind == "output":
        output.mkdir()
    elif kind == "staging":
        (tmp_path / ".fit-input.staging").mkdir()
    elif kind == "source_inside_output":
        output = tmp_path
    else:
        output = package / "nested-output"
    with pytest.raises(fit_input.FitInputError):
        fit_input.build_fit_input_package(package, repo, output)


@pytest.mark.parametrize("name", ["combinedcard.txt", "workspace.root", "higgsCombineTest.root",
                                     "fitDiagnostics.root", "selectedWCs.txt"])
def test_downstream_artifact_rejected(tmp_path, name):
    repo, _, package, output = _fixture(tmp_path)
    (package / "cards" / name).write_bytes(b"forbidden")
    with pytest.raises(fit_input.FitInputError, match="forbidden artifact"):
        fit_input.build_fit_input_package(package, repo, output)
    assert not output.exists()


def test_only_git_is_invoked_and_no_statistical_outputs_are_created(tmp_path, monkeypatch):
    repo, _, package, output = _fixture(tmp_path)
    calls = []
    original = fit_input.subprocess.run

    def capture(command, **kwargs):
        calls.append(command)
        return original(command, **kwargs)

    monkeypatch.setattr(fit_input.subprocess, "run", capture)
    fit_input.build_fit_input_package(package, repo, output)
    assert calls and all(command[0] == "git" for command in calls)
    assert {path.name for path in output.rglob("*") if path.is_file()} == {
        "one.txt", "one.root", "scalings.json", "ordered_card_inputs.txt",
        "combined_mapping_manifest.json", "package-provenance.json",
        "TOP_26_006.yml", "fit-input-manifest.json", "README.md",
    }


def test_cli_builds_synthetic_package(tmp_path, capsys):
    repo, _, package, output = _fixture(tmp_path)
    assert fit_input.main(["--combined-package", str(package), "--source-repo", str(repo),
                           "--output", str(output)]) == 0
    response = json.loads(capsys.readouterr().out)
    manifest = json.loads((output / "fit-input-manifest.json").read_text())
    assert response["datacards_content_sha256"] == manifest["datacards"]["content_sha256"]


def test_non_regular_card_member_fails_closed(tmp_path):
    repo, _, package, output = _fixture(tmp_path)
    fifo = package / "cards" / "named_pipe"
    os.mkfifo(fifo)
    with pytest.raises(fit_input.FitInputError, match="non-regular"):
        fit_input.build_fit_input_package(package, repo, output)
    assert not output.exists()


def test_config_must_match_recorded_git_commit(tmp_path):
    repo, config, package, output = _fixture(tmp_path)
    config.write_bytes(config.read_bytes() + b"\n")
    with pytest.raises(fit_input.FitInputError, match="differ from source Git commit"):
        fit_input.build_fit_input_package(package, repo, output)
    assert not output.exists()
