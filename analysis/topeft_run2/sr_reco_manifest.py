"""Plan and receipt checks for the SR extension owned by run_cr.sh.

The campaign state is the only durable plan owner. Supplied plans are inputs;
the original and replacement snapshots are retained in that one state file.
"""

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


RUN_DIRECTORY = Path(__file__).resolve().parent
REPOSITORY_ROOT = RUN_DIRECTORY.parents[1]
CHANNELS_PATH = REPOSITORY_ROOT / "topeft/channels/ch_lst.json"
DEFAULT_PLAN_PATH = RUN_DIRECTORY / "sr_reco_default_plan.json"
VARIABLES = frozenset(
    ("fwd0pt", "j0pt", "b0pt", "met", "l0conept", "l1conept", "invmass", "tau0Tpt")
)
CONTRACT_PATHS = (
    "topeft/modules/axes.py",
    "topeft/channels/ch_lst.json",
    "analysis/topeft_run2/run_cr.sh",
    "analysis/topeft_run2/sr_reco_manifest.py",
    "analysis/topeft_run2/run_analysis.py",
    "analysis/topeft_run2/analysis_processor.py",
    "analysis/topeft_run2/fullR3_run.sh",
)
UNIT_ID_PATTERN = re.compile(r"[a-z][a-z0-9_]*\Z")


def fail(message):
    raise ValueError(message)


def digest_bytes(content):
    return hashlib.sha256(content).hexdigest()


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_digest(value):
    return digest_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def contract_files(profile):
    if profile == "run2_sr_ext":
        cfg_names = [
            "mc_signal_samples_NDSkim.cfg", "mc_background_samples_NDSkim.cfg",
            "data_samples_NDSkim.cfg",
        ]
    elif profile == "run3_sr_ext":
        cfg_names = [
            f"NDSkim_{year}_{kind}.cfg"
            for year in ("2022", "2022EE", "2023", "2023BPix")
            for kind in ("background_samples", "data_samples", "mc_signal_samples_sr")
        ]
    else:
        fail("unsupported SR extension profile")
    names = set(CONTRACT_PATHS)
    for cfg_name in cfg_names:
        cfg_path = REPOSITORY_ROOT / "input_samples/cfgs" / cfg_name
        names.add(str(cfg_path.relative_to(REPOSITORY_ROOT)))
        for line in cfg_path.read_text(encoding="utf-8").splitlines():
            entry = line.strip()
            if entry.startswith("../../input_samples/sample_jsons/") and entry.endswith(".json"):
                sample_path = (RUN_DIRECTORY / entry).resolve()
                if not sample_path.is_relative_to(REPOSITORY_ROOT):
                    fail(f"sample JSON escapes repository: {entry}")
                names.add(str(sample_path.relative_to(REPOSITORY_ROOT)))
    return {name: digest_file(REPOSITORY_ROOT / name) for name in sorted(names)}


def physical_pairs():
    groups = json.loads(CHANNELS_PATH.read_text(encoding="utf-8"))["ALL_CH_LST_SR"]
    approved = {"2l", "2lss_1tau", "2los_1tau", "4l", "3l_m_offZ", "3l_p_offZ", "3l_onZ_tau", "3l_fwd"}
    result = {}
    for group in approved:
        definition = groups[group]
        result[group] = {
            (group, channel[0], jet)
            for channel in definition["lep_chan_lst"]
            for jet in definition["jet_lst"]
        }
    return result


def applicable(pair, variable):
    channel = pair[1]
    if variable == "fwd0pt":
        return channel.startswith("2lss_fwd_") or channel.endswith("_fwd")
    if variable == "tau0Tpt":
        return "_1tau" in channel
    return True


def target_coverage():
    pairs = physical_pairs()
    return {
        (*pair, variable)
        for group_pairs in pairs.values()
        for pair in group_pairs
        for variable in VARIABLES
        if applicable(pair, variable)
    }


def unit_coverage(unit):
    pairs = physical_pairs()
    groups = unit.get("category_groups")
    variables = unit.get("histograms")
    if not isinstance(groups, list) or not groups or len(groups) != len(set(groups)):
        fail("unit category_groups must be a unique nonempty list")
    if not isinstance(variables, list) or not variables or len(variables) != len(set(variables)):
        fail("unit histograms must be a unique nonempty list")
    if not set(groups) <= pairs.keys() or not set(variables) <= VARIABLES:
        fail("unit declares an unknown SR group or histogram")
    result = {
        (*pair, variable)
        for group in groups
        for pair in pairs[group]
        for variable in variables
        if applicable(pair, variable)
    }
    if any(not any(item[3] == variable for item in result) for variable in variables):
        fail("unit contains an inapplicable histogram")
    return result


def coverage_key(item):
    return "|".join(item)


def verify_partition(units, expected):
    counts = Counter(coverage_key(item) for unit in units for item in unit_coverage(unit))
    wanted = {coverage_key(item) for item in expected}
    duplicate = sorted(key for key, count in counts.items() if count != 1)
    missing = sorted(wanted - counts.keys())
    unexpected = sorted(counts.keys() - wanted)
    if duplicate or missing or unexpected:
        fail(f"coverage partition invalid: duplicate={duplicate[:3]} missing={missing[:3]} unexpected={unexpected[:3]}")
    return sorted(wanted)


def load_plan(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if set(payload) != {"units"} or not isinstance(payload["units"], list) or not payload["units"]:
        fail("SR plan requires one nonempty units list")
    seen = set()
    units = []
    for unit in payload["units"]:
        if not isinstance(unit, dict) or set(unit) != {"id", "category_groups", "histograms"}:
            fail("SR unit requires id, category_groups and histograms only")
        unit_id = unit["id"]
        if not isinstance(unit_id, str) or not UNIT_ID_PATTERN.fullmatch(unit_id) or unit_id in seen:
            fail("SR unit ids must be unique snake_case names")
        seen.add(unit_id)
        unit_coverage(unit)
        units.append(unit)
    return units


def years_for(profile):
    return ["run2"] if profile == "run2_sr_ext" else ["2022", "2022EE", "2023", "2023BPix"]


def validate_output_namespace(blocks):
    owners = {}
    for block in blocks:
        outputs = block["expected_outputs"]
        paths = [*outputs, *(f"{output}.metadata.json" for output in outputs)]
        for path in paths:
            previous = owners.get(path)
            if previous is not None:
                fail(f"campaign output path collision between {previous} and {block['id']}: {path}")
            owners[path] = block["id"]


def plan_blocks(units, profile, tag, root, revision):
    years = years_for(profile)
    year_label = "UL16-UL16APV-UL17-UL18" if profile == "run2_sr_ext" else "2022-2022EE-2023-2023BPix"
    blocks = []
    for unit in units:
        block_id = f"{profile}_{unit['id']}"
        output_tag = f"{tag}_{revision}_{unit['id']}"
        output_name = f"{year_label}SRs_{output_tag}"
        nominal = str(Path(root) / f"{output_name}.pkl.gz")
        nonprompt = str(Path(root) / f"{output_name}_np.pkl.gz")
        blocks.append({
            "id": block_id,
            "years": years,
            "category_groups": unit["category_groups"],
            "histograms": unit["histograms"],
            "output_tag": output_tag,
            "output_name": output_name,
            "expected_outputs": [nominal, nonprompt],
            "expected_nominal_path": nominal,
            "expected_np_path": nonprompt,
            "plan_revision": revision,
        })
    validate_output_namespace(blocks)
    return blocks


def plan_tsv(blocks):
    rows = []
    for block in blocks:
        rows.append("\t".join((
            block["id"], " ".join(block["years"]), " ".join(block["category_groups"]),
            " ".join(block["histograms"]), block["output_tag"], block["output_name"],
            block["expected_nominal_path"], block["expected_np_path"],
        )))
    return "\n".join(rows) + "\n"


def artifact_receipt(path):
    path = Path(path)
    sidecar_path = Path(f"{path}.metadata.json")
    if path.is_symlink() or sidecar_path.is_symlink() or not path.is_file() or not sidecar_path.is_file() or path.stat().st_size == 0:
        fail(f"required artifact or sidecar missing: {path}")
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    artifact = sidecar.get("artifact", {})
    observed = {
        "path": str(path),
        "sha256": digest_file(path),
        "size_bytes": path.stat().st_size,
        "sidecar_sha256": digest_file(sidecar_path),
    }
    if artifact.get("pkl_basename") != path.name or artifact.get("pkl_sha256") != observed["sha256"] or artifact.get("pkl_size_bytes") != observed["size_bytes"]:
        fail(f"artifact sidecar identity mismatch: {path}")
    if not sidecar.get("synthetic") and not isinstance(sidecar.get("lineage", {}).get("inputs"), list):
        fail(f"artifact sidecar lacks lineage: {path}")
    return observed


def capture_receipt(state, block, stage):
    if not state.get("sr_reco_plan_revisions"):
        fail("SR campaign lacks revision history")
    if stage == "source":
        block["source_receipt"] = artifact_receipt(block["expected_nominal_path"])
    elif stage == "nonprompt":
        if "source_receipt" not in block:
            fail("source receipt absent before nonprompt completion")
        block["nonprompt_receipt"] = artifact_receipt(block["expected_np_path"])
    else:
        fail("unknown receipt stage")
    block["receipt_contract_sha256"] = state["sr_reco_contract_sha256"]
    block["receipt_plan_revision"] = block["plan_revision"]


def verify_receipt(state, block):
    revision = block.get("plan_revision")
    snapshots = [item for item in state.get("sr_reco_plan_revisions", []) if item.get("id") == revision]
    if len(snapshots) != 1 or not any(
        all(block.get(key) == historical.get(key) for key in (
            "id", "years", "category_groups", "histograms", "output_tag", "output_name",
            "expected_outputs", "expected_nominal_path", "expected_np_path", "plan_revision"
        )) for historical in snapshots[0]["blocks"]
    ):
        fail(f"block {block.get('id')} does not match its immutable revision")
    if block.get("receipt_contract_sha256") != state.get("sr_reco_contract_sha256") or block.get("receipt_plan_revision") != revision:
        fail(f"block {block['id']} lacks bound contract/revision receipt")
    if block.get("source_status") != "ready" or block.get("status") not in {"source_ready", "success"}:
        fail(f"block {block['id']} has no completed source")
    if block.get("source_exit_code") != 0:
        fail(f"block {block['id']} source did not exit successfully")
    if block.get("source_receipt") != artifact_receipt(block["expected_nominal_path"]):
        fail(f"block {block['id']} source receipt changed")
    if block["status"] == "success":
        if block.get("nonprompt_status") != "success" or block.get("nonprompt_exit_code") != 0:
            fail(f"block {block['id']} nonprompt did not exit successfully")
        if block.get("nonprompt_receipt") != artifact_receipt(block["expected_np_path"]):
            fail(f"block {block['id']} nonprompt receipt changed")
        nonprompt_sidecar = json.loads(
            Path(f"{block['expected_np_path']}.metadata.json").read_text(encoding="utf-8")
        )
        if not nonprompt_sidecar.get("synthetic") and not any(
            item.get("pkl_sha256") == block["source_receipt"]["sha256"]
            for item in nonprompt_sidecar["lineage"]["inputs"]
        ):
            fail(f"block {block['id']} nonprompt lineage does not bind source")
    elif state["nonprompt_mode"] != "separate" or block.get("nonprompt_status") != "planned":
        fail(f"block {block['id']} is an invalid deferred source")
    elif os.path.lexists(block["expected_np_path"]) or os.path.lexists(f"{block['expected_np_path']}.metadata.json"):
        fail(f"block {block['id']} has ambiguous deferred nonprompt output")


def load_state(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def current_contract(state):
    files = contract_files(state["production_profile"])
    if state.get("sr_reco_contract_files") != files:
        fail("frozen scientific/software source contract changed")
    contract = {key: state[key] for key in (
        "production_profile", "campaign_tag", "output_dir", "topeft_git_commit", "env_file_sha256",
        "environment_fingerprint", "topcoffea_git_commit", "topcoffea_relevant_source_fingerprint",
        "ttgamma_sample_role_policy", "do_systs", "do_np", "region", "nonprompt_mode",
    )}
    contract["files"] = files
    contract["chunk_size"] = state.get("sr_reco_chunk_size")
    if canonical_digest(contract) != state.get("sr_reco_contract_sha256"):
        fail("campaign contract identity mismatch")


def check_state(state, *, require_contract=True):
    if state.get("schema_version") != 6 or state.get("production_profile") not in {"run2_sr_ext", "run3_sr_ext"}:
        fail("legacy or non-SR campaign cannot be adopted into revision state")
    if require_contract:
        current_contract(state)
    revisions = state.get("sr_reco_plan_revisions")
    if not isinstance(revisions, list) or not revisions or len({item["id"] for item in revisions}) != len(revisions):
        fail("invalid plan revision history")
    if state.get("active_sr_reco_revision") != revisions[-1]["id"]:
        fail("active revision pointer is inconsistent")
    for index, revision in enumerate(revisions, 1):
        snapshot = revision.get("blocks")
        if not isinstance(snapshot, list) or not snapshot:
            fail("empty or invalid revision snapshot")
        validate_output_namespace(snapshot)
        units = [{
            "id": block["id"].removeprefix(f"{state['production_profile']}_"),
            "category_groups": block["category_groups"],
            "histograms": block["histograms"],
        } for block in snapshot]
        if revision["id"] != f"r{index}_{canonical_digest(units)[:12]}":
            fail("revision snapshot identity mismatch")
    validate_output_namespace([
        block for revision in revisions for block in revision["blocks"]
    ])
    target = target_coverage()
    if set(state.get("sr_reco_target_coverage", [])) != {coverage_key(item) for item in target}:
        fail("desired physical coverage changed")
    blocks = state.get("blocks", [])
    if len({block.get("id") for block in blocks}) != len(blocks):
        fail("duplicate campaign unit id")
    if len({block.get("expected_nominal_path") for block in blocks}) != len(blocks):
        fail("duplicate campaign output path")
    validate_output_namespace(blocks)
    for block in blocks:
        if any(Path(output).parent != Path(state["output_dir"]) for output in block["expected_outputs"]):
            fail("campaign output escapes its root")
    if any(block.get("plan_revision") not in {item["id"] for item in revisions} for block in blocks):
        fail("block has an unknown plan revision")
    for block in blocks:
        historical = [
            item for revision in revisions for item in revision["blocks"]
            if item.get("id") == block.get("id")
        ]
        if len(historical) != 1 or block_spec(block) != historical[0]:
            fail(f"block {block.get('id')} differs from immutable plan snapshot")
        if block["plan_revision"] != state["active_sr_reco_revision"] and block.get("status") not in {"success", "source_ready"}:
            fail("inactive revision contains unfinished unit")
        expected_stages = {
            "planned": ("planned", "blocked"),
            "source_running": ("running", "blocked"),
            "source_ready": ("ready", "planned"),
            "source_failed": ("failed", "blocked"),
            "nonprompt_running": ("ready", "running"),
            "nonprompt_failed": ("ready", "failed"),
            "success": ("ready", "success"),
        }.get(block.get("status"))
        if expected_stages is None or (block.get("source_status"), block.get("nonprompt_status")) != expected_stages:
            fail(f"block {block['id']} has contradictory stage state")
        if block.get("expected_outputs") != [block.get("expected_nominal_path"), block.get("expected_np_path")]:
            fail(f"block {block['id']} has contradictory output paths")
    verify_partition(blocks, target)
    for block in blocks:
        if block.get("status") in {"success", "source_ready"}:
            verify_receipt(state, block)
    return blocks


def decorate_initial_state(state, chunk_size):
    if state.get("schema_version") != 6 or "sr_reco_plan_revisions" in state:
        fail("SR state already has revisions or unsupported schema")
    target = target_coverage()
    verify_partition(state["blocks"], target)
    validate_output_namespace(state["blocks"])
    revision = state["blocks"][0].get("plan_revision")
    if not revision or any(block.get("plan_revision") != revision for block in state["blocks"]):
        fail("initial plan lacks one revision identity")
    files = contract_files(state["production_profile"])
    contract = {key: state[key] for key in (
        "production_profile", "campaign_tag", "output_dir", "topeft_git_commit", "env_file_sha256",
        "environment_fingerprint", "topcoffea_git_commit", "topcoffea_relevant_source_fingerprint",
        "ttgamma_sample_role_policy", "do_systs", "do_np", "region", "nonprompt_mode",
    )}
    contract["files"] = files
    contract["chunk_size"] = chunk_size
    state["sr_reco_chunk_size"] = chunk_size
    state["sr_reco_contract_files"] = files
    state["sr_reco_contract_sha256"] = canonical_digest(contract)
    state["sr_reco_target_coverage"] = sorted(coverage_key(item) for item in target)
    state["sr_reco_plan_revisions"] = [{"id": revision, "blocks": [block_spec(block) for block in state["blocks"]]}]
    state["active_sr_reco_revision"] = revision
    return state


def initialize_state(state_path, chunk_size):
    state = decorate_initial_state(load_state(state_path), chunk_size)
    atomic_json(state_path, state)


SPEC_KEYS = (
    "id", "years", "category_groups", "histograms", "output_tag", "output_name",
    "expected_outputs", "expected_nominal_path", "expected_np_path", "plan_revision",
)


def block_spec(block):
    return {key: block[key] for key in SPEC_KEYS}


def new_pending_block(spec):
    timestamp = datetime.now(timezone.utc).isoformat()
    return {
        **spec, "status": "planned", "exit_code": None,
        "source_status": "planned", "source_exit_code": None, "source_signal": None,
        "source_command_argv": None, "source_started_at_utc": None, "source_ended_at_utc": None,
        "source_duration_seconds": None, "nonprompt_status": "blocked",
        "nonprompt_exit_code": None, "nonprompt_signal": None, "nonprompt_command_argv": None,
        "nonprompt_started_at_utc": None, "nonprompt_ended_at_utc": None,
        "nonprompt_duration_seconds": None, "native_work_queue_logs": {},
        "last_transition_utc": timestamp, "last_transition_detail": "pending_plan_activated",
        "transitions": [{"timestamp_utc": timestamp, "stage": "campaign", "status": "planned", "exit_code": None, "detail": "pending_plan_activated"}],
    }


def activate(state_path, plan_path, expected_revision):
    state = load_state(state_path)
    check_state(state)
    if state["active_sr_reco_revision"] != expected_revision:
        fail("stale expected plan revision")
    frozen = []
    for block in state["blocks"]:
        if block["status"] in {"success", "source_ready"}:
            if block["status"] == "source_ready" and state["nonprompt_mode"] != "separate":
                fail("incomplete inline unit cannot be frozen")
            frozen.append(block)
        elif block["status"] == "planned" and block["source_status"] == "planned" and block["nonprompt_status"] == "blocked":
            for output in block["expected_outputs"]:
                if os.path.lexists(output) or os.path.lexists(f"{output}.metadata.json"):
                    fail(f"untouched pending unit has an output collision: {output}")
        else:
            fail(f"unit {block['id']} is in-flight, failed or ambiguous")
    covered = {item for block in frozen for item in unit_coverage(block)}
    remaining = target_coverage() - covered
    units = load_plan(plan_path)
    verify_partition(units, remaining)
    next_number = len(state["sr_reco_plan_revisions"]) + 1
    revision = f"r{next_number}_{canonical_digest(units)[:12]}"
    specs = plan_blocks(units, state["production_profile"], state["campaign_tag"], state["output_dir"], revision)
    historical_ids = {block["id"] for item in state["sr_reco_plan_revisions"] for block in item["blocks"]}
    historical_paths = {path for item in state["sr_reco_plan_revisions"] for block in item["blocks"] for path in block["expected_outputs"]}
    if any(block["id"] in historical_ids for block in specs):
        fail("replacement unit id collides with historical unit")
    for block in specs:
        for output in block["expected_outputs"]:
            if output in historical_paths or os.path.lexists(output) or os.path.lexists(f"{output}.metadata.json"):
                fail(f"replacement output collides: {output}")
    replacement = [new_pending_block(spec) for spec in specs]
    candidate = dict(state)
    candidate["blocks"] = frozen + replacement
    candidate["sr_reco_plan_revisions"] = state["sr_reco_plan_revisions"] + [{"id": revision, "blocks": specs}]
    candidate["active_sr_reco_revision"] = revision
    candidate["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    for summary_key in (
        "campaign_status", "completed_at_utc", "configured_block_count",
        "attempted_block_count", "successful_block_count", "known_failed_block_count",
        "not_attempted_block_count", "final_process_exit_code",
    ):
        candidate.pop(summary_key, None)
    check_state(candidate)
    atomic_json(state_path, candidate)
    return revision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    render = subparsers.add_parser("render-new")
    for field in ("plan", "profile", "tag", "root", "output"):
        render.add_argument(field)
    active = subparsers.add_parser("render-active")
    active.add_argument("state")
    active.add_argument("output")
    active.add_argument("chunk_size")
    init = subparsers.add_parser("initialize")
    init.add_argument("state")
    init.add_argument("chunk_size")
    activate_parser = subparsers.add_parser("activate")
    for field in ("state", "plan", "expected_revision"):
        activate_parser.add_argument(field)
    summary = subparsers.add_parser("consumer-summary")
    summary.add_argument("state")
    args = parser.parse_args()
    try:
        if args.action == "render-new":
            units = load_plan(args.plan)
            verify_partition(units, target_coverage())
            revision = f"r1_{canonical_digest(units)[:12]}"
            Path(args.output).write_text(plan_tsv(plan_blocks(units, args.profile, args.tag, args.root, revision)), encoding="utf-8")
            print(revision)
        elif args.action == "render-active":
            state = load_state(args.state)
            check_state(state)
            if state.get("sr_reco_chunk_size") != args.chunk_size:
                fail("resume chunk size differs from frozen campaign contract")
            Path(args.output).write_text(plan_tsv(state["blocks"]), encoding="utf-8")
            print(state["active_sr_reco_revision"])
        elif args.action == "initialize":
            initialize_state(args.state, args.chunk_size)
        elif args.action == "activate":
            print(activate(args.state, args.plan, args.expected_revision))
        elif args.action == "consumer-summary":
            state = load_state(args.state)
            check_state(state)
            complete = all(block["status"] == "success" for block in state["blocks"])
            print(json.dumps({
                "active_revision": state["active_sr_reco_revision"],
                "target_coverage_count": len(state["sr_reco_target_coverage"]),
                "units": [{"id": block["id"], "revision": block["plan_revision"], "status": block["status"]} for block in state["blocks"]],
                "complete": complete,
            }, sort_keys=True))
        else:
            fail("unknown operation")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        parser.exit(1, f"ERROR: {error}\n")


if __name__ == "__main__":
    main()
