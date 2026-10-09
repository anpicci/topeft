import copy
import csv
import fcntl
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from analysis.topeft_run2 import sr_reco_manifest as manifest
from test_run2_srplot009_manual_handoff import (
    RUN_CR,
    RUN_DIRECTORY,
    _campaign_state,
    _clean_environment,
    _run,
    _write_backend,
)


def _backend_environment(validation_root):
    environment = _clean_environment()
    environment.update({
        "SRPLOT009_VALIDATION_BACKEND": str(validation_root / "backend.sh"),
        "SRPLOT009_VALIDATION_ROOT": str(validation_root),
        "SRPLOT009_VALIDATION_SCENARIO": "success",
    })
    return environment


def _replacement_units():
    initial = manifest.load_plan(manifest.DEFAULT_PLAN_PATH)
    pending = copy.deepcopy(initial[2:])
    b_1 = next(unit for unit in pending if unit["id"] == "b_1")
    b_2 = next(unit for unit in pending if unit["id"] == "b_2")
    merged = {
        "id": "v2_b_all",
        "category_groups": b_1["category_groups"],
        "histograms": b_1["histograms"] + b_2["histograms"],
    }
    return [
        {**unit, "id": f"v2_{unit['id']}"}
        for unit in pending if unit["id"] not in {"b_1", "b_2"}
    ] + [merged]


@pytest.mark.parametrize("profile", ("run2_sr_ext", "run3_sr_ext"))
def test_two_completed_units_replan_in_same_native_campaign(tmp_path, profile):
    validation_root = tmp_path / profile
    validation_root.mkdir()
    _write_backend(validation_root / "backend.sh")
    environment = _backend_environment(validation_root)
    output_root = validation_root / "output"
    tag = f"synthetic-{profile}"
    old_ids = [f"{profile}_a_1", f"{profile}_a_2"]
    for index, block_id in enumerate(old_ids):
        result = _run(
            profile, output_root, tag, dry_run=False, resume=index > 0,
            environment=environment, extra_args=("--selected-fragment", block_id),
        )
        assert result.returncode == 0, result.stdout
    state = _campaign_state(output_root, profile)
    assert len(state["sr_reco_plan_revisions"][0]["blocks"]) == 12
    first_revision = state["active_sr_reco_revision"]
    assert [block["status"] for block in state["blocks"][:2]] == ["success", "success"]
    preserved = {
        path: Path(path).read_bytes()
        for block in state["blocks"][:2]
        for output in block["expected_outputs"]
        for path in (output, f"{output}.metadata.json")
    }
    preserved_receipts = copy.deepcopy([
        (block["source_receipt"], block["nonprompt_receipt"])
        for block in state["blocks"][:2]
    ])
    calls_before = (validation_root / "block_calls.tsv").read_text()

    replacement = {"units": _replacement_units()}
    plan_path = validation_root / "pending.json"
    plan_path.write_text(json.dumps(replacement), encoding="utf-8")
    activation = _run(
        profile, output_root, tag, dry_run=False, resume=True,
        environment=environment, supply_env_file=False,
        extra_args=(
            "--activate-pending-plan", str(plan_path),
            "--expected-plan-revision", first_revision,
        ),
    )
    assert activation.returncode == 0, activation.stdout
    revised = _campaign_state(output_root, profile)
    assert revised["output_dir"] == str(output_root)
    assert len(revised["sr_reco_plan_revisions"]) == 2
    assert len(revised["blocks"]) == 11
    assert revised["active_sr_reco_revision"] != first_revision
    assert [block["plan_revision"] for block in revised["blocks"][:2]] == [first_revision] * 2
    assert [(block["source_receipt"], block["nonprompt_receipt"]) for block in revised["blocks"][:2]] == preserved_receipts
    assert all(Path(path).read_bytes() == data for path, data in preserved.items())
    assert (validation_root / "block_calls.tsv").read_text() == calls_before
    assert len(manifest.check_state(revised)) == 11

    resumed = _run(
        profile, output_root, tag, dry_run=False, resume=True,
        environment=environment,
    )
    assert resumed.returncode == 0, resumed.stdout
    final = _campaign_state(output_root, profile)
    summary = subprocess.run(
        ["python", str(RUN_DIRECTORY / "sr_reco_manifest.py"), "consumer-summary", str(output_root / f".{profile}_campaign_state.json")],
        cwd=RUN_DIRECTORY, text=True, capture_output=True, check=True,
    )
    consumed = json.loads(summary.stdout)
    with (output_root / "campaign_summary.tsv").open(encoding="utf-8", newline="") as handle:
        report_rows = list(csv.DictReader(handle, delimiter="\t"))
    assert consumed["complete"] is True
    assert consumed["target_coverage_count"] == len(manifest.target_coverage())
    assert Counter(item["revision"] for item in consumed["units"]) == {
        first_revision: 2, final["active_sr_reco_revision"]: 9,
    }
    assert len({block["expected_nominal_path"] for block in final["blocks"]}) == 11
    assert {row["block_id"]: row["plan_revision"] for row in report_rows} == {
        block["id"]: block["plan_revision"] for block in final["blocks"]
    }
    assert all(Path(path).read_bytes() == data for path, data in preserved.items())
    calls_after = (validation_root / "block_calls.tsv").read_text()
    for block_id in old_ids:
        assert calls_after.count(f"{block_id}\t") == calls_before.count(f"{block_id}\t")
    for block in final["blocks"][2:]:
        assert calls_after.count(f"{block['id']}\t") == 1
    if profile == "run3_sr_ext":
        nonprompt_calls = (validation_root / "nonprompt_calls.tsv").read_text().splitlines()
        assert Counter(nonprompt_calls) == {block["id"]: 1 for block in final["blocks"]}


def test_rejected_replans_preserve_authoritative_state(tmp_path, monkeypatch):
    profile = "run2_sr_ext"
    validation_root = tmp_path / "rejected"
    validation_root.mkdir()
    _write_backend(validation_root / "backend.sh")
    output_root = validation_root / "output"
    tag = "synthetic-rejected"
    result = _run(
        profile, output_root, tag, dry_run=False,
        environment=_backend_environment(validation_root),
        extra_args=("--selected-fragment", f"{profile}_a_1"),
    )
    assert result.returncode == 0, result.stdout
    state_path = output_root / f".{profile}_campaign_state.json"
    original = state_path.read_bytes()
    state = json.loads(original)
    overlapping_state = copy.deepcopy(state)
    overlapping_state["blocks"][1]["expected_outputs"][0] = state["blocks"][0]["expected_np_path"]
    with pytest.raises(ValueError, match="output path collision"):
        manifest.check_state(overlapping_state, require_contract=False)
    valid = _replacement_units()
    # The second original unit is still pending here, so this candidate has a gap.
    with pytest.raises(ValueError, match="missing"):
        manifest.activate(state_path, _write_plan(validation_root, valid), state["active_sr_reco_revision"])
    assert state_path.read_bytes() == original
    with pytest.raises(ValueError, match="stale"):
        manifest.activate(state_path, _write_plan(validation_root, manifest.load_plan(manifest.DEFAULT_PLAN_PATH)[1:]), "r0_stale")
    assert state_path.read_bytes() == original
    complete_pending = [
        {**unit, "id": f"v2_{unit['id']}"}
        for unit in manifest.load_plan(manifest.DEFAULT_PLAN_PATH)[1:]
    ]
    complete_plan = _write_plan(validation_root, complete_pending)
    with monkeypatch.context() as patcher:
        patcher.setattr(manifest, "contract_files", lambda profile: {"changed": "contract"})
        with pytest.raises(ValueError, match="contract"):
            manifest.activate(state_path, complete_plan, state["active_sr_reco_revision"])
    assert state_path.read_bytes() == original
    with monkeypatch.context() as patcher:
        patcher.setattr(manifest, "atomic_json", lambda path, value: (_ for _ in ()).throw(OSError("injected before replace")))
        with pytest.raises(OSError, match="injected"):
            manifest.activate(state_path, complete_plan, state["active_sr_reco_revision"])
    assert state_path.read_bytes() == original
    next_revision = f"r2_{manifest.canonical_digest(complete_pending)[:12]}"
    collision = manifest.plan_blocks(
        complete_pending, profile, tag, output_root, next_revision,
    )[0]["expected_nominal_path"]
    Path(collision).write_bytes(b"collision")
    with pytest.raises(ValueError, match="replacement output collides"):
        manifest.activate(state_path, complete_plan, state["active_sr_reco_revision"])
    assert state_path.read_bytes() == original
    Path(collision).unlink()
    for occupied_path in (collision, f"{collision}.metadata.json"):
        Path(occupied_path).symlink_to(validation_root / "missing-target")
        with pytest.raises(ValueError, match="replacement output collides"):
            manifest.activate(state_path, complete_plan, state["active_sr_reco_revision"])
        assert state_path.read_bytes() == original
        Path(occupied_path).unlink()
    lock_path = output_root / f".{profile}_campaign.lock"
    lock_bytes = b"existing lock contents must survive\n"
    lock_path.write_bytes(lock_bytes)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        blocked = _run(
            profile, output_root, tag, dry_run=False, resume=True,
            environment=_backend_environment(validation_root), supply_env_file=False,
            extra_args=(
                "--activate-pending-plan", str(complete_plan),
                "--expected-plan-revision", state["active_sr_reco_revision"],
            ),
        )
        assert blocked.returncode != 0
        assert "writer lock is held" in blocked.stdout
    assert lock_path.read_bytes() == lock_bytes
    lock_path.unlink()
    lock_target = validation_root / "lock-target"
    lock_target.write_bytes(b"lock target remains unchanged\n")
    lock_path.symlink_to(lock_target)
    blocked_symlink = _run(
        profile, output_root, tag, dry_run=False, resume=True,
        environment=_backend_environment(validation_root), supply_env_file=False,
        extra_args=(
            "--activate-pending-plan", str(complete_plan),
            "--expected-plan-revision", state["active_sr_reco_revision"],
        ),
    )
    assert blocked_symlink.returncode != 0
    assert "lock path must not be a symbolic link" in blocked_symlink.stdout
    assert lock_path.is_symlink()
    assert lock_target.read_bytes() == b"lock target remains unchanged\n"
    assert state_path.read_bytes() == original
    overlap = copy.deepcopy(manifest.load_plan(manifest.DEFAULT_PLAN_PATH))
    overlap[1]["histograms"].append("invmass")
    with pytest.raises(ValueError, match="coverage partition"):
        manifest.verify_partition(overlap, manifest.target_coverage())
    corrupted = state["blocks"][0]["expected_nominal_path"]
    Path(corrupted).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="identity mismatch"):
        manifest.activate(state_path, complete_plan, state["active_sr_reco_revision"])
    assert state_path.read_bytes() == original
    Path(corrupted).write_bytes(b"synthetic source\n")
    original_atomic_json = manifest.atomic_json

    def committed_then_interrupted(path, value):
        original_atomic_json(path, value)
        raise OSError("injected after replace")

    with monkeypatch.context() as patcher:
        patcher.setattr(manifest, "atomic_json", committed_then_interrupted)
        with pytest.raises(OSError, match="after replace"):
            manifest.activate(state_path, complete_plan, state["active_sr_reco_revision"])
    published = manifest.load_state(state_path)
    assert published["active_sr_reco_revision"] != state["active_sr_reco_revision"]
    assert manifest.check_state(published)


def _synthetic_sidecar(path):
    path = Path(path)
    path.write_bytes(f"synthetic {path.name}".encode())
    sidecar = {
        "artifact": {
            "pkl_basename": path.name,
            "pkl_size_bytes": path.stat().st_size,
            "pkl_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        },
        "synthetic": True,
    }
    Path(f"{path}.metadata.json").write_text(json.dumps(sidecar), encoding="utf-8")


def test_run3_verified_source_can_remain_deferred_through_replan(tmp_path):
    profile = "run3_sr_ext"
    plan = manifest.load_plan(manifest.DEFAULT_PLAN_PATH)
    first_revision = f"r1_{manifest.canonical_digest(plan)[:12]}"
    specs = manifest.plan_blocks(plan, profile, "deferred", tmp_path, first_revision)
    state = {
        "schema_version": 6, "production_profile": profile,
        "campaign_tag": "deferred", "output_dir": str(tmp_path),
        "topeft_git_commit": "a" * 40, "env_file": str(tmp_path / "archive"),
        "env_file_sha256": "b" * 64, "environment_fingerprint": "c" * 64,
        "environment_mode": "explicit_snapshot",
        "topcoffea_git_commit": "d" * 40,
        "topcoffea_relevant_source_fingerprint": "e" * 64,
        "ttgamma_sample_role_policy": "split", "do_systs": True,
        "do_np": True, "region": "SR", "nonprompt_mode": "separate",
        "blocks": [manifest.new_pending_block(spec) for spec in specs],
    }
    state_path = tmp_path / ".run3_sr_ext_campaign_state.json"
    manifest.atomic_json(state_path, state)
    manifest.initialize_state(state_path, "100000")
    state = manifest.load_state(state_path)
    for block in state["blocks"][:2]:
        _synthetic_sidecar(block["expected_nominal_path"])
        block["status"] = "source_ready"
        block["source_status"] = "ready"
        block["source_exit_code"] = 0
        block["nonprompt_status"] = "planned"
        block["transitions"].append({
            "stage": "source", "status": "ready", "exit_code": 0,
            "detail": "source_child_exit_zero_expected_source_present",
        })
        manifest.capture_receipt(state, block, "source")
    manifest.atomic_json(state_path, state)
    pending = _replacement_units()
    revision = manifest.activate(
        state_path, _write_plan(tmp_path, pending), first_revision,
    )
    revised = manifest.load_state(state_path)
    assert revised["active_sr_reco_revision"] == revision
    assert [block["status"] for block in revised["blocks"][:2]] == ["source_ready", "source_ready"]
    assert not any(Path(block["expected_np_path"]).exists() for block in revised["blocks"][:2])
    assert manifest.check_state(revised)
    old = copy.deepcopy(revised)
    old.pop("sr_reco_plan_revisions")
    with pytest.raises(ValueError, match="revision history"):
        manifest.check_state(old)
    changed_target = copy.deepcopy(revised)
    changed_target["sr_reco_target_coverage"].pop()
    with pytest.raises(ValueError, match="desired physical coverage"):
        manifest.check_state(changed_target)
    for status, source_status, nonprompt_status in (
        ("source_running", "running", "blocked"),
        ("source_failed", "failed", "blocked"),
        ("nonprompt_running", "ready", "running"),
    ):
        ambiguous = copy.deepcopy(revised)
        pending_block = ambiguous["blocks"][-1]
        pending_block["status"] = status
        pending_block["source_status"] = source_status
        pending_block["nonprompt_status"] = nonprompt_status
        blocked_path = tmp_path / f"{status}.json"
        manifest.atomic_json(blocked_path, ambiguous)
        old_bytes = blocked_path.read_bytes()
        with pytest.raises(ValueError, match="in-flight, failed or ambiguous"):
            manifest.activate(blocked_path, _write_plan(tmp_path, pending), revision)
        assert blocked_path.read_bytes() == old_bytes


def test_plan_rejects_invalid_units_and_pair_sets(tmp_path):
    plan = manifest.load_plan(manifest.DEFAULT_PLAN_PATH)
    duplicate_id = copy.deepcopy(plan)
    duplicate_id[1]["id"] = duplicate_id[0]["id"]
    with pytest.raises(ValueError, match="unique"):
        manifest.load_plan(_write_plan(tmp_path, duplicate_id))
    unknown_axis = copy.deepcopy(plan)
    unknown_axis[0]["histograms"] = ["bjetpt0"]
    with pytest.raises(ValueError, match="unknown"):
        manifest.load_plan(_write_plan(tmp_path, unknown_axis))
    unknown_group = copy.deepcopy(plan)
    unknown_group[0]["category_groups"] = ["invented_sr"]
    with pytest.raises(ValueError, match="unknown"):
        manifest.load_plan(_write_plan(tmp_path, unknown_group))
    inapplicable = copy.deepcopy(plan)
    inapplicable[4]["histograms"] = ["fwd0pt"]
    with pytest.raises(ValueError, match="inapplicable"):
        manifest.load_plan(_write_plan(tmp_path, inapplicable))
    missing = copy.deepcopy(plan[:-1])
    with pytest.raises(ValueError, match="missing"):
        manifest.verify_partition(missing, manifest.target_coverage())
    overlapping = copy.deepcopy(plan)
    overlapping.append({**copy.deepcopy(plan[0]), "id": "another_a_1"})
    with pytest.raises(ValueError, match="duplicate"):
        manifest.verify_partition(overlapping, manifest.target_coverage())


def test_plan_blocks_rejects_overlapping_source_and_nonprompt_paths(tmp_path):
    units = copy.deepcopy(manifest.load_plan(manifest.DEFAULT_PLAN_PATH)[:2])
    units[0]["id"] = "x"
    units[1]["id"] = "x_np"
    with pytest.raises(ValueError, match="output path collision"):
        manifest.plan_blocks(units, "run2_sr_ext", "collision", tmp_path, "r1_test")


def test_run_cr_preoutput_rejects_dangling_output_symlink(tmp_path):
    profile = "run2_sr_ext"
    validation_root = tmp_path / "preoutput-symlink"
    validation_root.mkdir()
    _write_backend(validation_root / "backend.sh")
    output_root = validation_root / "output"
    tag = "synthetic-preoutput-symlink"
    initial = _run(
        profile, output_root, tag, dry_run=False,
        environment=_backend_environment(validation_root),
        extra_args=("--selected-fragment", f"{profile}_a_1"),
    )
    assert initial.returncode == 0, initial.stdout
    state_path = output_root / f".{profile}_campaign_state.json"
    state = manifest.load_state(state_path)
    pending = next(block for block in state["blocks"] if block["status"] == "planned")
    Path(pending["expected_nominal_path"]).symlink_to(validation_root / "missing-pkl")
    lock_path = output_root / f".{profile}_campaign.lock"
    lock_bytes = b"second lock acquisition must preserve bytes\n"
    lock_path.write_bytes(lock_bytes)
    result = _run(
        profile, output_root, tag, dry_run=False, resume=True,
        environment=_backend_environment(validation_root), supply_env_file=False,
        extra_args=("--selected-fragment", pending["id"]),
    )
    assert result.returncode != 0
    assert "expected output path already exists" in result.stdout
    assert lock_path.read_bytes() == lock_bytes


def _write_plan(directory, units):
    path = directory / "candidate.json"
    path.write_text(json.dumps({"units": units}), encoding="utf-8")
    return path


def test_axis_and_locality_contract():
    from topeft.modules.axes import info

    target = manifest.target_coverage()
    assert len(target) == len({manifest.coverage_key(item) for item in target})
    assert len(target) == 849  # observed current channel expansion, not a runtime constant
    assert all(manifest.applicable(item[:3], item[3]) for item in target)
    assert set(item[3] for item in target) == manifest.VARIABLES
    assert manifest.verify_partition(manifest.load_plan(manifest.DEFAULT_PLAN_PATH), target)
    assert info["j0pt"]["processing"] == info["b0pt"]["processing"]
    assert info["j0pt"]["label"] != info["b0pt"]["label"]
    default = manifest.load_plan(manifest.DEFAULT_PLAN_PATH)
    eleven = copy.deepcopy(default)
    eleven[1]["histograms"] += eleven[2]["histograms"]
    eleven.pop(2)
    assert manifest.verify_partition(eleven, target)

    def bin_proxy(unit):
        total = 0
        for pair in manifest.unit_coverage(unit):
            processing = info[pair[3]]["processing"]
            total += processing.get("bins", len(processing.get("edges", [])) - 1) + 2
        return total

    assert max(map(bin_proxy, default)) < max(map(bin_proxy, eleven))


def test_user_supplied_full_plan_selects_one_unit_without_output(tmp_path):
    profile = "run2_sr_ext"
    units = manifest.load_plan(manifest.DEFAULT_PLAN_PATH)
    units[1]["histograms"] += units[2]["histograms"]
    units.pop(2)
    plan_path = _write_plan(tmp_path, units)
    validation_root = tmp_path / "custom"
    validation_root.mkdir()
    _write_backend(validation_root / "backend.sh")
    output_root = validation_root / "output"
    result = _run(
        profile, output_root, "custom", dry_run=True,
        environment=_backend_environment(validation_root),
        extra_args=(
            "--sr-plan", str(plan_path),
            "--selected-fragment", f"{profile}_a_2",
        ),
    )
    assert result.returncode == 0, result.stdout
    assert result.stdout.count("production_block_id:") == 1
    assert "Variables: l0conept j0pt b0pt" in result.stdout
    assert not output_root.exists()
