"""Build and source-certify a canonical Run2+Run3 datacard package."""

import argparse
import copy
import json
import re
import shutil
import subprocess
from pathlib import Path

from topeft.modules import datacard_packaging


_source_names = {"cards", "selectedWCs.txt", "scalings.json", "physical_to_chN.json", "package-provenance.json"}
_source_provenance_names = {
    "schema", "artifact_type", "analysis", "era", "package_root", "packaged_txt_count",
    "packaged_root_count", "selected_wcs_sha256", "scalings_sha256", "physical_to_chN_sha256",
    "source_manifest_sha256s", "source_unit_count", "builder_git_head", "builder_source_sha256",
    "builder_git_dirty",
}
_output_names = {"cards", "scalings.json", "ordered_card_inputs.txt", "combined_mapping_manifest.json", "package-provenance.json", "README.md"}
_provenance_names = {
    "schema", "artifact_type", "analysis", "package_version", "package_date", "package_root",
    "assembler_commit", "assembler_source_sha256", "manifest_sha256", "ordered_card_inputs_sha256",
    "scalings_sha256", "source_mapping_sha256", "source_scalings_sha256", "packaged_txt_count",
    "packaged_root_count",
}
_source_root_prefix = "ttx_multileptons-"
_channel_pattern = re.compile(r"ch[1-9][0-9]*\Z")
_writer_shapes = re.compile(rb"^([ \t]*shapes[ \t]+\S+[ \t]+\S+[ \t]+)(\S+)")
_verifier_shapes = re.compile(rb"^([ \t]*shapes[ \t]+\S+[ \t]+\S+[ \t]+)(\S+)(.*)\Z", re.DOTALL)
_sha_pattern = re.compile(r"[0-9a-f]{64}\Z")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _write_json(path, value):
    Path(path).write_bytes(_json_bytes(value))


def _plain_file(path):
    return path.is_file() and not path.is_symlink()


def _plain_directory(path):
    return path.is_dir() and not path.is_symlink()


def _source_package(root, era):
    root = Path(root)
    _require(root.is_absolute() and _plain_directory(root), f"{era} package root is invalid")
    _require({entry.name for entry in root.iterdir()} == _source_names, f"{era} package layout differs")
    cards = root / "cards"
    _require(_plain_directory(cards), f"{era} cards directory is invalid")
    for name in _source_names - {"cards"}:
        _require(_plain_file(root / name), f"{era} source metadata member missing: {name}")
    provenance = _read_json(root / "package-provenance.json")
    _require(isinstance(provenance, dict) and set(provenance) == _source_provenance_names
             and provenance.get("schema") == "TOP26006_v1"
             and provenance.get("artifact_type") == "package_provenance"
             and provenance.get("era") == era and provenance.get("package_root") == str(root)
             and isinstance(provenance.get("analysis"), str) and provenance["analysis"].strip(),
             f"{era} source provenance role differs")
    mapping = _read_json(root / "physical_to_chN.json")
    _require(isinstance(mapping, list) and mapping, f"{era} source mapping is invalid")
    datacard_packaging.verify_per_era_mapping(mapping, [row["physical_name"] for row in mapping])
    expected = {
        f"{_source_root_prefix}{row['physical_name']}.{suffix}"
        for row in mapping for suffix in ("txt", "root")
    }
    _require({entry.name for entry in cards.iterdir()} == expected, f"{era} cards inventory differs")
    _require(all(_plain_file(cards / name) for name in expected), f"{era} source card is not a regular file")
    _require(type(provenance["packaged_txt_count"]) is int
             and type(provenance["packaged_root_count"]) is int
             and provenance["packaged_txt_count"] == len(mapping)
             and provenance["packaged_root_count"] == len(mapping), f"{era} source counts differ")
    for key, name in (("selected_wcs_sha256", "selectedWCs.txt"),
                      ("scalings_sha256", "scalings.json"),
                      ("physical_to_chN_sha256", "physical_to_chN.json")):
        _require(provenance[key] == datacard_packaging.sha256_file(root / name),
                 f"{era} source provenance hash differs: {key}")
    scalings = _read_json(root / "scalings.json")
    _require(isinstance(scalings, list), f"{era} source scalings must be a list")
    return {"root": root, "cards": cards, "mapping": mapping, "scalings": scalings,
            "analysis": provenance["analysis"]}


def _scaling_identity(record):
    _require(isinstance(record, dict) and {"channel", "process", "parameters", "scaling"} <= set(record),
             "incomplete scaling record")
    channel = record["channel"]
    process = record["process"]
    _require(isinstance(channel, str) and _channel_pattern.fullmatch(channel) is not None
             and isinstance(process, str) and bool(process.strip()), "invalid scaling identity")
    _require(isinstance(record["parameters"], list) and isinstance(record["scaling"], list),
             "invalid scaling payload")
    return channel, process


def _combine_scalings(run2_records, run3_records, mapping):
    """Relabel source records without mutating or aliasing any source object."""
    labels = {(row["era"], row["per_era_chN"]): row["combined_chN"] for row in mapping}
    result = []
    seen = set()
    for era, records in (("run2", run2_records), ("run3", run3_records)):
        for record in records:
            source_channel, process = _scaling_identity(record)
            combined = labels.get((era, source_channel))
            _require(combined is not None, "unmapped source scaling channel")
            key = (combined, process)
            _require(key not in seen, "duplicate combined scaling identity")
            seen.add(key)
            transformed = copy.deepcopy(record)
            transformed["channel"] = combined
            result.append(transformed)
    return result


def _scalings_bytes(records):
    return ("[\n" + ",\n".join(json.dumps(record, separators=(",", ":"), allow_nan=False)
                             for record in records) + "\n]\n").encode("utf-8")


def _rewrite_card(source_bytes, source_root, destination_root):
    """Writer: replace only exact token four on well-formed shapes lines."""
    source_token = source_root.encode("ascii")
    destination_token = destination_root.encode("ascii")
    rewritten = []
    count = 0
    source_bytes.decode("utf-8")
    for line in source_bytes.splitlines(keepends=True):
        if re.match(rb"^[ \t]*shapes(?:[ \t]|$)", line):
            match = _writer_shapes.match(line)
            _require(match is not None and match.group(2) == source_token,
                     "ambiguous source template reference")
            line = line[:match.start(2)] + destination_token + line[match.end(2):]
            count += 1
        rewritten.append(line)
    _require(count > 0, "source card has no shapes template reference")
    return b"".join(rewritten)


def _verify_card(source_bytes, destination_bytes, source_root, destination_root):
    """Certifier: compare independent token spans and every other byte."""
    source_lines = source_bytes.splitlines(keepends=True)
    destination_lines = destination_bytes.splitlines(keepends=True)
    _require(len(source_lines) == len(destination_lines), "card line count differs")
    count = 0
    for source_line, destination_line in zip(source_lines, destination_lines):
        if re.match(rb"^[ \t]*shapes(?:[ \t]|$)", source_line):
            source_match = _verifier_shapes.fullmatch(source_line)
            destination_match = _verifier_shapes.fullmatch(destination_line)
            _require(source_match is not None and destination_match is not None,
                     "ambiguous packaged shapes line")
            _require(source_match.group(1) == destination_match.group(1)
                     and source_match.group(3) == destination_match.group(3)
                     and source_match.group(2) == source_root.encode("ascii")
                     and destination_match.group(2) == destination_root.encode("ascii"),
                     "card differs outside approved template token")
            count += 1
        else:
            _require(source_line == destination_line, "card differs outside approved shapes line")
    _require(count > 0, "card has no approved shapes reference")


def _verify_scalings(observed, run2_records, run3_records, mapping):
    """Certifier: compare each observed record against its source payload."""
    _require(isinstance(observed, list), "combined scalings must be a list")
    sources = [("run2", record) for record in run2_records] + [("run3", record) for record in run3_records]
    _require(len(observed) == len(sources), "combined scaling count differs")
    labels = {(row["era"], row["per_era_chN"]): row["combined_chN"] for row in mapping}
    seen = set()
    for actual, (era, source) in zip(observed, sources):
        source_channel, process = _scaling_identity(source)
        actual_channel, actual_process = _scaling_identity(actual)
        _require(actual_channel == labels.get((era, source_channel)) and actual_process == process,
                 "combined scaling identity/order differs")
        key = (actual_channel, actual_process)
        _require(key not in seen, "duplicate combined scaling identity")
        seen.add(key)
        _require(set(actual) == set(source) and all(actual[name] == source[name] for name in source if name != "channel"),
                 "combined scaling payload differs")


def _readme(analysis, output):
    return (f"# {analysis} combined Run2+Run3 datacard package\n\n"
            f"Package path: `{output}`\n\n"
            "Packaged TXT and ROOT payloads live under `cards/`. "
            "`combined_mapping_manifest.json` records the mapping and order. "
            "`scalings.json` is the combined scaling payload. "
            "`ordered_card_inputs.txt` is the canonical consumer ordering authority.\n\n"
            "```bash\n"
            f"cd {output}\n"
            "mapfile -t cards < ordered_card_inputs.txt\n"
            'combineCards.py "${cards[@]}" > combinedcard.txt\n'
            "```\n\n"
            "Do not use wildcard/glob card discovery.\n")


def _builder_identity():
    source = Path(__file__).resolve()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=source.parents[2],
                          check=True, capture_output=True, text=True).stdout.strip()
    _require(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head) is not None,
             "builder commit is unobservable")
    return head, datacard_packaging.sha256_file(source)


def _manifest(mapping, output):
    return {"schema": "TOP26006_v1", "artifact_type": "combined_mapping_manifest",
            "package_root": str(output), "rows": mapping}


def certify_combined_package(package_root, run2_package, run3_package, *, expected_output=None):
    """Certify an existing package against both supplied canonical sources."""
    package_root = Path(package_root)
    output = Path(expected_output) if expected_output is not None else package_root
    _require(package_root.is_absolute() and _plain_directory(package_root), "combined package root is invalid")
    _require(output.is_absolute(), "expected package path must be absolute")
    run2 = _source_package(run2_package, "run2")
    run3 = _source_package(run3_package, "run3")
    _require(run2["analysis"] == run3["analysis"], "source analyses differ")
    _require({entry.name for entry in package_root.iterdir()} == _output_names,
             "combined package top-level inventory differs")
    cards = package_root / "cards"
    _require(_plain_directory(cards), "combined cards directory is invalid")
    for name in _output_names - {"cards"}:
        _require(_plain_file(package_root / name), f"combined metadata member missing: {name}")
    manifest = _read_json(package_root / "combined_mapping_manifest.json")
    _require(isinstance(manifest, dict) and set(manifest) == {"schema", "artifact_type", "package_root", "rows"}
             and manifest["schema"] == "TOP26006_v1"
             and manifest["artifact_type"] == "combined_mapping_manifest"
             and manifest["package_root"] == str(output), "combined manifest wrapper differs")
    mapping = manifest["rows"]
    datacard_packaging.verify_combined_mapping(mapping, run2["mapping"], run3["mapping"])
    expected_names = {row[name] for row in mapping for name in ("destination_txt_name", "destination_root_name")}
    _require({entry.name for entry in cards.iterdir()} == expected_names,
             "combined cards inventory differs")
    _require(all(_plain_file(cards / name) for name in expected_names), "combined card member is not a regular file")
    for row in mapping:
        source = run2 if row["era"] == "run2" else run3
        stem = f"{_source_root_prefix}{row['physical_name']}"
        source_root = source["cards"] / (stem + ".root")
        source_txt = source["cards"] / (stem + ".txt")
        destination_root = cards / row["destination_root_name"]
        destination_txt = cards / row["destination_txt_name"]
        _require(datacard_packaging.sha256_file(source_root) == datacard_packaging.sha256_file(destination_root),
                 "packaged ROOT bytes differ from source")
        destination_bytes = destination_txt.read_bytes()
        _verify_card(source_txt.read_bytes(), destination_bytes, source_root.name, destination_root.name)
        _require(str(run2["root"]).encode() not in destination_bytes
                 and str(run3["root"]).encode() not in destination_bytes
                 and str(package_root).encode() not in destination_bytes,
                 "packaged TXT leaks a source or staging path")
    scaling_bytes = (package_root / "scalings.json").read_bytes()
    _require(str(package_root).encode() not in scaling_bytes if package_root != output else True,
             "combined scalings leak staging path")
    observed_scalings = json.loads(scaling_bytes)
    _verify_scalings(observed_scalings, run2["scalings"], run3["scalings"], mapping)
    order_bytes = (package_root / "ordered_card_inputs.txt").read_bytes()
    order = order_bytes.decode("utf-8")
    datacard_packaging.verify_ordered_card_inputs(order, mapping)
    _require(order.endswith("\n") and all((package_root / line).is_file() for line in order.splitlines()),
             "ordered card path is missing")
    provenance = _read_json(package_root / "package-provenance.json")
    _require(isinstance(provenance, dict) and set(provenance) == _provenance_names
             and provenance["schema"] == "TOP26006_v1"
             and provenance["artifact_type"] == "package_provenance"
             and provenance["analysis"] == run2["analysis"]
             and provenance["package_root"] == str(output)
             and isinstance(provenance["package_date"], str) and bool(provenance["package_date"])
             and isinstance(provenance["package_version"], str) and bool(provenance["package_version"])
             and isinstance(provenance["assembler_commit"], str) and bool(provenance["assembler_commit"])
             and isinstance(provenance["assembler_source_sha256"], str)
             and _sha_pattern.fullmatch(provenance["assembler_source_sha256"]) is not None,
             "combined provenance identity differs")
    expected_hashes = {
        "manifest_sha256": "combined_mapping_manifest.json",
        "ordered_card_inputs_sha256": "ordered_card_inputs.txt",
        "scalings_sha256": "scalings.json",
    }
    for key, name in expected_hashes.items():
        _require(provenance[key] == datacard_packaging.sha256_file(package_root / name),
                 f"combined provenance hash differs: {key}")
    for key, name in (("source_mapping_sha256", "physical_to_chN.json"),
                      ("source_scalings_sha256", "scalings.json")):
        _require(provenance[key] == {
            "run2": datacard_packaging.sha256_file(run2["root"] / name),
            "run3": datacard_packaging.sha256_file(run3["root"] / name),
        }, f"combined source hash differs: {key}")
    _require(type(provenance["packaged_txt_count"]) is int
             and type(provenance["packaged_root_count"]) is int
             and provenance["packaged_txt_count"] == len(mapping)
             and provenance["packaged_root_count"] == len(mapping), "packaged counts differ")
    readme = (package_root / "README.md").read_text(encoding="utf-8")
    for clause in ("cards/", "ordered_card_inputs.txt", "combined_mapping_manifest.json", "scalings.json",
                   f"cd {output}", "mapfile -t cards < ordered_card_inputs.txt",
                   'combineCards.py "${cards[@]}" > combinedcard.txt', "wildcard/glob"):
        _require(clause in readme, f"README omits consumer contract: {clause}")
    for name in _output_names - {"cards", "scalings.json"}:
        raw = (package_root / name).read_bytes()
        _require(str(package_root).encode() not in raw if package_root != output else True,
                 "consumer metadata leaks staging path")
    return {"schema": "topeft_combined_source_certification_v1", "package_root": str(output),
            "source_packages": {"run2": str(run2["root"]), "run3": str(run3["root"])},
            "card_count": len(mapping), "scaling_record_count": len(observed_scalings), "certified": True}


def build_combined_package(run2_package, run3_package, output, analysis, package_date, package_version):
    output = Path(output)
    _require(output.is_absolute() and output.name not in {"", ".", ".."}, "output must be absolute")
    _require(_plain_directory(output.parent), "output parent does not exist")
    staging = output.parent / f".{output.name}.staging"
    _require(not output.exists() and not output.is_symlink(), "final output already exists")
    _require(not staging.exists() and not staging.is_symlink(), "private staging already exists")
    _require(isinstance(analysis, str) and bool(analysis.strip())
             and isinstance(package_date, str) and bool(re.fullmatch(r"[0-9]{6}", package_date))
             and isinstance(package_version, str) and bool(re.fullmatch(r"v[1-9][0-9]*", package_version)),
             "invalid package metadata")
    run2 = _source_package(run2_package, "run2")
    run3 = _source_package(run3_package, "run3")
    _require(run2["analysis"] == run3["analysis"] == analysis, "source analysis differs")
    mapping = datacard_packaging.build_combined_mapping(run2["mapping"], run3["mapping"])
    combined_scalings = _combine_scalings(run2["scalings"], run3["scalings"], mapping)
    ordered_inputs = datacard_packaging.build_ordered_card_inputs(mapping)
    head, source_hash = _builder_identity()
    staging.mkdir()
    cards = staging / "cards"
    cards.mkdir()
    for row in mapping:
        source = run2 if row["era"] == "run2" else run3
        stem = f"{_source_root_prefix}{row['physical_name']}"
        source_root = source["cards"] / (stem + ".root")
        source_txt = source["cards"] / (stem + ".txt")
        shutil.copyfile(source_root, cards / row["destination_root_name"])
        (cards / row["destination_txt_name"]).write_bytes(
            _rewrite_card(source_txt.read_bytes(), source_root.name, row["destination_root_name"]))
    _write_json(staging / "combined_mapping_manifest.json", _manifest(mapping, output))
    (staging / "scalings.json").write_bytes(_scalings_bytes(combined_scalings))
    (staging / "ordered_card_inputs.txt").write_text("\n".join(ordered_inputs) + "\n", encoding="utf-8")
    (staging / "README.md").write_text(_readme(analysis, output), encoding="utf-8")
    provenance = {
        "schema": "TOP26006_v1", "artifact_type": "package_provenance", "analysis": analysis,
        "package_date": package_date, "package_version": package_version, "package_root": str(output),
        "assembler_commit": head, "assembler_source_sha256": source_hash,
        "manifest_sha256": datacard_packaging.sha256_file(staging / "combined_mapping_manifest.json"),
        "scalings_sha256": datacard_packaging.sha256_file(staging / "scalings.json"),
        "ordered_card_inputs_sha256": datacard_packaging.sha256_file(staging / "ordered_card_inputs.txt"),
        "source_mapping_sha256": {era: datacard_packaging.sha256_file(source["root"] / "physical_to_chN.json")
                                  for era, source in (("run2", run2), ("run3", run3))},
        "source_scalings_sha256": {era: datacard_packaging.sha256_file(source["root"] / "scalings.json")
                                   for era, source in (("run2", run2), ("run3", run3))},
        "packaged_txt_count": len(mapping), "packaged_root_count": len(mapping),
    }
    _write_json(staging / "package-provenance.json", provenance)
    certify_combined_package(staging, run2["root"], run3["root"], expected_output=output)
    _require(not output.exists() and not output.is_symlink(), "final output appeared before publication")
    staging.rename(output)
    _require(_plain_directory(output) and not staging.exists()
             and _read_json(output / "combined_mapping_manifest.json")["package_root"] == str(output),
             "publication readback differs")
    return provenance


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--run2-package", type=Path, required=True)
    build.add_argument("--run3-package", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--analysis", required=True)
    build.add_argument("--package-date", required=True)
    build.add_argument("--package-version", required=True)
    certify = commands.add_parser("certify")
    certify.add_argument("--package-root", type=Path, required=True)
    certify.add_argument("--run2-package", type=Path, required=True)
    certify.add_argument("--run3-package", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "build":
        build_combined_package(args.run2_package, args.run3_package, args.output,
                               args.analysis, args.package_date, args.package_version)
    else:
        print(json.dumps(certify_combined_package(args.package_root, args.run2_package, args.run3_package),
                         sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
