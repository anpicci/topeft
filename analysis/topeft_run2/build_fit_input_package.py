#!/usr/bin/env python3
"""Wrap one combined datacard package with an exact TOP-26-006 fit config."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path, PurePosixPath

import yaml


_analysis = "TOP-26-006"
_schema = "TOP26006_fit_input_v1"
_config_relative_path = "topeft/params/fits/TOP_26_006.yml"
_top_level = {
    "cards", "scalings.json", "ordered_card_inputs.txt",
    "combined_mapping_manifest.json", "package-provenance.json", "README.md",
}
_metadata_hashes = {
    "scalings.json": "scalings_sha256",
    "ordered_card_inputs.txt": "ordered_card_inputs_sha256",
    "combined_mapping_manifest.json": "manifest_sha256",
}
_downstream_name = re.compile(
    r"^(?:combinedcard\.txt|workspace(?:[^/]*)\.root|higgsCombine.*\.root|"
    r"fitDiagnostics.*|multidimfit.*|combine(?:harvester|impact).*|"
    r"impacts?.*|toys?.*|gof.*|goodness.*|wilks.*|coverage.*|"
    r"selectedWCs\.txt|ModelConfig.*|autoMCStats.*)$", re.IGNORECASE,
)


class FitInputError(ValueError):
    """A source or destination violates the portable package contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FitInputError(message)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def _plain_dir(path: Path) -> bool:
    try:
        return stat.S_ISDIR(path.lstat().st_mode)
    except OSError:
        return False


def _overlap(first: Path, second: Path) -> bool:
    first, second = first.resolve(), second.resolve()
    return first == second or first in second.parents or second in first.parents


def _source_members(package: Path) -> list[str]:
    _require(_plain_dir(package), "combined package must be a plain directory")
    top = {entry.name for entry in package.iterdir()}
    _require(top == _top_level, "combined package top-level structure is invalid")
    _require(_plain_dir(package / "cards"), "cards must be a plain directory")
    members = []
    for root, dirs, files in os.walk(package, followlinks=False):
        for name in sorted(dirs):
            path = Path(root) / name
            _require(_plain_dir(path), f"non-regular directory: {path}")
            _require(not _downstream_name.fullmatch(name), f"forbidden artifact: {name}")
        for name in sorted(files):
            path = Path(root) / name
            _require(_regular_file(path), f"non-regular or symlink member: {path}")
            _require(not _downstream_name.fullmatch(name), f"forbidden artifact: {name}")
            members.append(path.relative_to(package).as_posix())
    members.sort()
    _require(any(name.startswith("cards/") for name in members), "cards is empty")
    return members


def _read_metadata(package: Path, members: list[str]) -> None:
    member_set = set(members)
    try:
        provenance = json.loads((package / "package-provenance.json").read_text(encoding="utf-8"))
        mapping = json.loads((package / "combined_mapping_manifest.json").read_text(encoding="utf-8"))
        json.loads((package / "scalings.json").read_text(encoding="utf-8"))
        ordered = (package / "ordered_card_inputs.txt").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FitInputError(f"invalid combined package metadata: {error}") from error
    _require(isinstance(provenance, dict) and provenance.get("schema") == "TOP26006_v1"
             and provenance.get("artifact_type") == "package_provenance"
             and provenance.get("analysis") == _analysis, "combined provenance identity is invalid")
    _require(isinstance(mapping, dict) and mapping.get("schema") == "TOP26006_v1"
             and mapping.get("artifact_type") == "combined_mapping_manifest"
             and isinstance(mapping.get("rows"), list) and bool(mapping["rows"]),
             "combined mapping metadata is invalid")
    _require(bool(ordered) and len(ordered) == len(set(ordered)), "ordered card inputs missing or duplicate")
    for entry in ordered:
        path = PurePosixPath(entry)
        _require(entry and "\\" not in entry and not path.is_absolute()
                 and path.parts[0] == "cards" and len(path.parts) > 1
                 and all(part not in {".", ".."} for part in entry.split("/"))
                 and entry in member_set and entry.endswith(".txt"),
                 f"invalid ordered card entry: {entry}")
    for name, field in _metadata_hashes.items():
        expected = provenance.get(field)
        _require(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected),
                 f"missing declared metadata hash: {field}")
        _require(_sha256_bytes((package / name).read_bytes()) == expected,
                 f"declared metadata hash mismatch: {name}")


def _config_identity(source_repo: Path, config: Path) -> tuple[bytes, str]:
    _require(_plain_dir(source_repo / ".git"), "source repository Git directory is missing")
    _require(config.resolve() == (source_repo / _config_relative_path).resolve(),
             "fit config must be the declared source repository path")
    _require(_regular_file(config), "fit config is missing or not a regular file")
    content = config.read_bytes()
    try:
        parsed = yaml.safe_load(content)
    except (yaml.YAMLError, UnicodeError) as error:
        raise FitInputError(f"malformed fit config: {error}") from error
    _require(isinstance(parsed, dict) and parsed.get("analysis") == "TOP_26_006"
             and isinstance(parsed.get("wc_population"), dict)
             and isinstance(parsed["wc_population"].get("scientific"), list)
             and bool(parsed["wc_population"]["scientific"])
             and isinstance(parsed.get("wc_ranges"), dict) and bool(parsed["wc_ranges"]),
             "fit config lacks required analysis, WC population, or ranges")
    try:
        commit = subprocess.run(
            ["git", "-C", str(source_repo), "rev-parse", "HEAD"],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ).stdout.decode("ascii").strip()
        committed = subprocess.run(
            ["git", "-C", str(source_repo), "show", f"{commit}:{_config_relative_path}"],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ).stdout
    except (OSError, subprocess.CalledProcessError, UnicodeError) as error:
        raise FitInputError("cannot verify fit config source Git commit") from error
    _require(committed == content, "fit config bytes differ from source Git commit")
    return content, commit


def _copy_and_hash(source: Path, destination: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    size = 0
    source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(source_fd, "rb") as input_stream, destination.open("xb") as output_stream:
        _require(stat.S_ISREG(os.fstat(input_stream.fileno()).st_mode),
                 f"source member changed type: {source}")
        for block in iter(lambda: input_stream.read(1024 * 1024), b""):
            output_stream.write(block)
            digest.update(block)
            size += len(block)
    return {"size_bytes": size, "sha256": digest.hexdigest()}


def _hash_file(path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return {"size_bytes": size, "sha256": digest.hexdigest()}


def build_fit_input_package(package: Path, source_repo: Path, output: Path) -> dict[str, object]:
    package, source_repo, output = Path(package), Path(source_repo), Path(output)
    config = source_repo / _config_relative_path
    staging = output.parent / f".{output.name}.staging"
    _require(output.is_absolute() and output.name not in {"", ".", ".."}, "output must be absolute")
    _require(_plain_dir(output.parent), "output parent must be a plain existing directory")
    _require(not output.exists() and not output.is_symlink(), "output already exists")
    _require(not staging.exists() and not staging.is_symlink(), "staging already exists")
    for first, second in ((package, config), (package, output), (package, staging),
                          (config, output), (config, staging), (staging, output)):
        _require(not _overlap(first, second), "source, config, staging, and output must not overlap")
    members = _source_members(package)
    _read_metadata(package, members)
    config_bytes, commit = _config_identity(source_repo, config)
    staging.mkdir()
    try:
        datacards = staging / "datacards"
        datacards.mkdir()
        source_inventory = []
        for relative in members:
            destination = datacards / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            source_inventory.append({"path": relative, **_copy_and_hash(package / relative, destination)})
        config_destination = staging / "config" / "TOP_26_006.yml"
        config_destination.parent.mkdir()
        config_destination.write_bytes(config_bytes)
        destination_inventory = [
            {"path": relative, **_hash_file(datacards / relative)} for relative in members
        ]
        _require(source_inventory == destination_inventory, "datacard copy identity mismatch")
        _read_metadata(datacards, members)
        _require(_sha256_bytes(config_bytes) == _hash_file(config_destination)["sha256"],
                 "fit config copy identity mismatch")
        content_sha256 = _sha256_bytes(_json_bytes(source_inventory))
        manifest = {
            "schema": _schema, "artifact_type": "fit_input_manifest", "analysis": _analysis,
            "datacards": {"path": "datacards", "content_sha256": content_sha256,
                          "files": source_inventory},
            "fit_config": {"path": "config/TOP_26_006.yml",
                           "sha256": _sha256_bytes(config_bytes),
                           "source_repository": "topeft",
                           "source_repo_relative_path": _config_relative_path,
                           "source_git_commit": commit},
        }
        (staging / "fit-input-manifest.json").write_bytes(_json_bytes(manifest))
        (staging / "README.md").write_text(
            "# TOP-26-006 fit input package\n\n"
            "Use `datacards/ordered_card_inputs.txt` as the ordered card entry point. "
            "Resolve its entries relative to `datacards/`. `config/TOP_26_006.yml` "
            "is the scientific WC authority. The manifest binds both inputs by content. "
            "Source repository and historical package paths in provenance are archival, "
            "not runtime locators.\n\n"
            "EFTFit owns all Combine and CombineHarvester products, including combined "
            "cards, workspaces, inventories, fits, impacts, toys, GOF, Wilks, and coverage. "
            "Derive any selectedWCs.txt downstream from this package-local config.\n",
            encoding="utf-8",
        )
        _require(not output.exists() and not output.is_symlink(), "output appeared before publication")
        staging.rename(output)
        return manifest
    except BaseException:
        shutil.rmtree(staging)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--combined-package", type=Path, required=True)
    parser.add_argument("--source-repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = build_fit_input_package(args.combined_package, args.source_repo, args.output)
    print(json.dumps({"output": str(args.output), "datacards_content_sha256":
                      manifest["datacards"]["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
