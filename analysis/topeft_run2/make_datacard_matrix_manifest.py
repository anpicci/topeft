"""Materialize a standard Run 2 or Run 3 datacard matrix manifest."""

import argparse
import json
import os
from pathlib import Path

from analysis.topeft_run2 import build_per_era_datacard_package as per_era
from analysis.topeft_run2 import datacard_matrix_runner as runner


_years = {
    "run2": ["UL16APV", "UL16", "UL17", "UL18"],
    "run3": ["2022", "2022EE", "2023", "2023BPix"],
}
_row_order = [
    ("mixed_01", "mixed", "lj0pt"),
    ("mixed_02", "mixed", "lt"),
    ("mixed_03", "mixed", "ptz"),
    ("mixed_04", "mixed", "ptz_wtau"),
    ("3l_offz_01", "offz", "lj0pt"),
    ("3l_offz_02", "offz", "ptll"),
    ("3l_onz_tau_01", "onz_tau", "lj0pt"),
    ("3l_onz_tau_02", "onz_tau", "ptz"),
    ("3l_fwd_01", "fwd", "lt"),
]
_card_prefix = "ttx_multileptons-"
_repository_root = Path(__file__).resolve().parents[2]
_registry = _repository_root / "topeft/channels/ch_lst.json"


def _physical_row(physical_name):
    for distribution in ("ptz_wtau", "lj0pt", "ptll", "ptz", "lt"):
        suffix = "_" + distribution
        if physical_name.endswith(suffix):
            channel = physical_name[:-len(suffix)]
            if channel.startswith("3l_") and "fwd" in channel:
                return "fwd", distribution, channel
            if distribution == "ptll" or channel.startswith(("3l_m_offZ_", "3l_p_offZ_")):
                return "offz", distribution, channel
            if channel.startswith(("3l_onZ_", "3l_1tau_")):
                return "onz_tau", distribution, channel
            return "mixed", distribution, channel
    raise ValueError(f"unsupported physical target distribution: {physical_name}")


def _runtime_path(value, label, *, executable=False):
    path = runner.absolute(str(value), label)
    if not path.is_file() or (executable and not os.access(path, os.X_OK)):
        raise ValueError(f"{label} must be an existing regular file: {path}")
    return path


def make_manifest(args):
    manifest_output = runner.absolute(str(args.manifest_output), "manifest_output")
    output_root = runner.absolute(str(args.output_root), "output_root")
    control_root = runner.absolute(str(args.control_root), "control_root")
    working_directory = runner.absolute(str(args.working_directory), "working_directory")
    if not working_directory.is_dir():
        raise ValueError(f"working_directory must exist: {working_directory}")
    if not manifest_output.parent.is_dir() or manifest_output.exists():
        raise ValueError(f"manifest output must have an existing parent and be absent: {manifest_output}")
    if not runner.IDENTIFIER_RE.fullmatch(args.attempt_id):
        raise ValueError("attempt_id must be a portable identifier")
    python = _runtime_path(args.python_executable, "python_executable", executable=True)
    make_cards = _runtime_path(args.make_cards_path, "make_cards_path")
    missing_parton = _runtime_path(args.missing_parton_file, "missing_parton_file")
    fingerprints = []
    seen_runtime = set()
    for value in [make_cards, *args.runtime_file]:
        path = _runtime_path(value, "runtime_file")
        if path in seen_runtime:
            continue
        seen_runtime.add(path)
        fingerprints.append({"path": str(path), "sha256": runner.hash_file(path)})
    runtime = {
        "contract_id": args.runtime_contract_id,
        "python_executable": str(python),
        "make_cards_path": str(make_cards),
        "fingerprints": fingerprints,
    }
    runner.validate_runtime(runtime)
    physical_names = per_era._selected_physical_names(_registry, "ALL_CH_LST_SR", args.physical_target)
    grouped = {(group, distribution): [] for _, group, distribution in _row_order}
    for name in physical_names:
        group, distribution, channel = _physical_row(name)
        if (group, distribution) not in grouped:
            raise ValueError(f"physical target has no standard matrix row: {name}")
        grouped[group, distribution].append(channel)
    inputs = {"mixed": args.mixed_pkl, "offz": args.offz_pkl,
              "onz_tau": args.onz_tau_pkl, "fwd": args.fwd_pkl}
    rows = []
    for row_id, group, distribution in _row_order:
        channels = grouped[group, distribution]
        if not channels:
            continue
        input_value = inputs[group]
        if input_value is None:
            raise ValueError(f"{group} PKL is required for row {row_id}")
        input_pkl = _runtime_path(input_value, f"{group}_pkl")
        row_output = output_root / row_id
        merge_report = control_root / "merge_reports" / f"{row_id}__{args.attempt_id}.json"
        snapshot = control_root / "snapshots" / f"{row_id}__{args.attempt_id}"
        log = control_root / "logs" / f"{row_id}__{args.attempt_id}.log"
        expected_outputs = [str(row_output / f"{_card_prefix}{channel}_{distribution}.{suffix}")
                            for channel in channels for suffix in ("txt", "root")]
        producer_args = [
            "--out-dir", str(row_output), "--var-lst", distribution,
            "--ch-lst", *channels,
            "--do-nuisance", "--do-mc-stat", "--skip-selected-wcs-check",
            "--year-coverage-policy", "warn", "--year", *_years[args.era],
            "--miss-parton-file", str(missing_parton), "--sr-registry", "ALL_CH_LST_SR",
            "--merge-report", str(merge_report),
        ]
        rows.append({
            "row_id": row_id, "attempt_id": args.attempt_id, "era": args.era,
            "working_directory": str(working_directory), "input_pkl": str(input_pkl),
            "output_root": str(row_output), "distribution": distribution,
            "physical_channels": channels, "years": _years[args.era],
            "missing_parton_path": str(missing_parton), "sr_registry": "ALL_CH_LST_SR",
            "merge_report_path": str(merge_report), "snapshot_directory": str(snapshot),
            "log_path": str(log), "expected_output_paths": expected_outputs,
            "producer_args": producer_args,
        })
    manifest = {
        "schema": runner.MANIFEST_SCHEMA, "control_root": str(control_root),
        "lock_path": str(control_root / "runner.lock"),
        "runtime_contract": runtime, "rows": rows,
    }
    runner.validate_runtime(runtime, verify_files=False)
    for index, row in enumerate(rows):
        runner.validate_row(row, index, control_root)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--era", choices=tuple(_years), required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--control-root", type=Path, required=True)
    parser.add_argument("--mixed-pkl", type=Path)
    parser.add_argument("--offz-pkl", type=Path)
    parser.add_argument("--onz-tau-pkl", type=Path)
    parser.add_argument("--fwd-pkl", type=Path)
    parser.add_argument("--python-executable", type=Path, required=True)
    parser.add_argument("--make-cards-path", type=Path,
                        default=_repository_root / "analysis/topeft_run2/make_cards.py")
    parser.add_argument("--missing-parton-file", type=Path, required=True)
    parser.add_argument("--runtime-contract-id", required=True)
    parser.add_argument("--runtime-file", type=Path, action="append", default=[])
    parser.add_argument("--physical-target", action="append", default=[],
                        help="Repeat for a restricted physical <channel>_<distribution> set")
    parser.add_argument("--attempt-id", default="attempt_01")
    parser.add_argument("--working-directory", type=Path, default=_repository_root)
    args = parser.parse_args(argv)
    manifest = make_manifest(args)
    with args.manifest_output.open("x", encoding="utf-8") as output:
        json.dump(manifest, output, indent=2)
        output.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
