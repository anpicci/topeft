import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "analysis/topeft_run2/run_datacard_matrix_resumable.sh"
ENGINE = ROOT / "analysis/topeft_run2/datacard_matrix_runner.py"

FAKE = r'''
from pathlib import Path
import json, sys, time
args = sys.argv[1:]
input_pkl = args[0]
def one(name): return args[args.index(name) + 1]
def many(name):
    result = []
    for item in args[args.index(name) + 1:]:
        if item.startswith("--"): break
        result.append(item)
    return result
if "--record-argv" in args: Path(one("--record-argv")).write_text(json.dumps(args))
if "--counter" in args:
    p = Path(one("--counter")); p.write_text(str(int(p.read_text()) + 1 if p.exists() else 1))
if "--order" in args:
    with Path(one("--order")).open("a") as h: h.write(one("--token") + "\n")
if "--write-path" in args:
    p = Path(one("--write-path")); p.parent.mkdir(parents=True, exist_ok=True); p.write_text("external\n")
if "--mutate-path" in args: Path(one("--mutate-path")).write_text("runtime drift\n")
if "--sleep" in args: time.sleep(float(one("--sleep")))
if "--fail" in args: raise SystemExit(7)
root = Path(one("--out-dir")); root.mkdir(parents=True, exist_ok=True)
report = Path(one("--merge-report")); report.parent.mkdir(parents=True, exist_ok=True); report.write_text("{}\n")
(root / "selectedWCs.txt").write_text("selected\n")
(root / "scalings-preselect.json").write_text("scalings\n")
for name in many("--expected-output"):
    p = Path(name); p.parent.mkdir(parents=True, exist_ok=True); p.write_text("synthetic " + input_pkl + "\n")
'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def fake_script(tmp_path):
    script = tmp_path / "runtime" / "make_cards.py"
    script.parent.mkdir()
    script.write_text(FAKE)
    return script


def make_row(tmp_path, fake, row_id="row_01", attempt="attempt_01", extra=None):
    root = tmp_path / "cards" / f"{row_id}_{attempt}"
    evidence = tmp_path / "evidence" / f"{row_id}_{attempt}"
    input_pkl = tmp_path / "inputs" / f"{row_id}_{attempt}.pkl.gz"
    input_pkl.parent.mkdir(exist_ok=True); input_pkl.write_text("input\n")
    missing = tmp_path / "missing.root"; missing.write_text("missing\n")
    outputs = [root / "card.txt", root / "card.root"]
    args = ["--out-dir", str(root), "--var-lst", "lj0pt", "--ch-lst", "channel_a", "channel_b", "--binning", "fitting", "--year", "2022", "2022EE", "--miss-parton-file", str(missing), "--sr-registry", "ALL_CH_LST_SR", "--merge-report", str(evidence / "merge.json"), "--expected-output", *map(str, outputs), *(extra or [])]
    return {"row_id": row_id, "attempt_id": attempt, "era": "run3", "working_directory": str(fake.parent), "input_pkl": str(input_pkl), "output_root": str(root), "distribution": "lj0pt", "physical_channels": ["channel_a", "channel_b"], "years": ["2022", "2022EE"], "missing_parton_path": str(missing), "sr_registry": "ALL_CH_LST_SR", "merge_report_path": str(evidence / "merge.json"), "snapshot_directory": str(tmp_path / "control" / "snapshots" / f"{row_id}_{attempt}"), "log_path": str(evidence / "row.log"), "expected_output_paths": list(map(str, outputs)), "producer_args": args}


def manifest(tmp_path, fake, rows, name="manifest.json"):
    data = {"schema": "topeft_datacard_matrix_v2", "control_root": str(tmp_path / "control"), "lock_path": str(tmp_path / "control" / "runner.lock"), "runtime_contract": {"contract_id": "synthetic-runtime", "python_executable": sys.executable, "make_cards_path": str(fake), "fingerprints": [{"path": str(fake), "sha256": sha(fake)}]}, "rows": rows}
    path = tmp_path / name; path.write_text(json.dumps(data, indent=2) + "\n")
    return path, data


def invoke(path, mode=None):
    return subprocess.run([str(RUNNER), *( [mode] if mode else []), str(path)], text=True, capture_output=True)


def result(stream):
    for start in reversed([i for i, char in enumerate(stream) if char == "{"]):
        try: return json.loads(stream[start:])
        except json.JSONDecodeError: pass
    raise AssertionError(stream)


def receipt(tmp_path, row):
    return json.loads((tmp_path / "control" / "receipts" / f"{row['row_id']}__{row['attempt_id']}.json").read_text())


def test_schema_and_identity_rejections(tmp_path, fake_script):
    row = make_row(tmp_path, fake_script); row.pop("era")
    path, _ = manifest(tmp_path, fake_script, [row]); assert result(invoke(path).stderr)["status"] == "manifest_schema_error"
    first, second = make_row(tmp_path, fake_script), make_row(tmp_path, fake_script)
    path, _ = manifest(tmp_path, fake_script, [first, second], "duplicate.json"); assert result(invoke(path, "--plan-only").stderr)["status"] == "manifest_schema_error"


def test_plan_and_status_are_nonmutating(tmp_path, fake_script):
    row = make_row(tmp_path, fake_script, extra=["--counter", str(tmp_path / "counter")]); path, data = manifest(tmp_path, fake_script, [row])
    assert result(invoke(path, "--plan-only").stdout)["rows"][0]["action"] == "execute"
    assert result(invoke(path, "--status").stdout)["rows"][0]["status"] == "not_started"
    assert not Path(data["control_root"]).exists() and not (tmp_path / "counter").exists()


def test_active_interrupted_and_stale_owner_statuses(tmp_path, fake_script):
    row = make_row(tmp_path, fake_script, extra=["--sleep", "1.2"]); path, data = manifest(tmp_path, fake_script, [row])
    first = subprocess.Popen([str(RUNNER), str(path)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.monotonic() + 10
    while not Path(row["log_path"]).exists() and time.monotonic() < deadline: time.sleep(.02)
    active = result(invoke(path, "--status").stdout); assert active["lock_held"] and active["rows"][0]["status"] == "active"
    out, err = first.communicate(timeout=10); assert first.returncode == 0, out + err
    Path(row["log_path"]).unlink(); (tmp_path / "control" / "receipts" / "row_01__attempt_01.json").unlink()
    Path(row["expected_output_paths"][0]).write_text("interrupted\n")
    assert result(invoke(path, "--status").stdout)["rows"][0]["status"] == "interrupted_requires_external_reconciliation"
    owner = {"schema_version": "topeft_datacard_runner_owner_v1", "manifest_sha256": sha(path), "current_row_id": row["row_id"], "current_attempt_id": row["attempt_id"]}
    (tmp_path / "control" / "runner_owner.json").write_text(json.dumps(owner))
    assert result(invoke(path, "--status").stdout)["rows"][0]["status"] == "interrupted_requires_external_reconciliation"


def test_receipt_byte_binds_outputs_and_control_artifacts(tmp_path, fake_script):
    row = make_row(tmp_path, fake_script); path, _ = manifest(tmp_path, fake_script, [row]); assert invoke(path).returncode == 0
    data = receipt(tmp_path, row); assert all(set(item) == {"path", "size_bytes", "sha256"} for item in data["primary_outputs"])
    for path_to_mutate in [row["expected_output_paths"][0], row["expected_output_paths"][1], data["artifacts"]["selected_wcs_snapshot"]["path"], data["artifacts"]["scalings_snapshot"]["path"]]:
        Path(path_to_mutate).write_text("tampered\n")
        assert result(invoke(path, "--status").stdout)["rows"][0]["status"] == "invalid_receipt"
        Path(path_to_mutate).write_text("synthetic " + row["input_pkl"] + "\n" if str(path_to_mutate).endswith((".txt", ".root")) and "snapshots" not in str(path_to_mutate) else "selected\n" if str(path_to_mutate).endswith("selectedWCs.txt") else "scalings\n")
    Path(row["expected_output_paths"][0]).unlink()
    assert result(invoke(path, "--status").stdout)["rows"][0]["status"] == "invalid_receipt"


def test_resume_failures_and_new_attempt(tmp_path, fake_script):
    counter = tmp_path / "counter"; row = make_row(tmp_path, fake_script, extra=["--counter", str(counter)]); path, _ = manifest(tmp_path, fake_script, [row])
    assert invoke(path).returncode == 0 and invoke(path).returncode == 0 and counter.read_text() == "1"
    bad = make_row(tmp_path, fake_script, "bad", extra=["--fail"]); later = make_row(tmp_path, fake_script, "later", extra=["--counter", str(tmp_path / "later")]); bad_path, _ = manifest(tmp_path, fake_script, [bad, later], "bad.json")
    assert result(invoke(bad_path).stderr)["status"] == "row_command_failed" and not (tmp_path / "later").exists()
    retry = make_row(tmp_path, fake_script, "bad", "attempt_02"); retry_path, _ = manifest(tmp_path, fake_script, [retry], "retry.json"); assert invoke(retry_path).returncode == 0
    orphan = make_row(tmp_path, fake_script, "orphan"); Path(orphan["expected_output_paths"][0]).parent.mkdir(parents=True); Path(orphan["expected_output_paths"][0]).write_text("orphan\n"); orphan_path, _ = manifest(tmp_path, fake_script, [orphan], "orphan.json")
    assert result(invoke(orphan_path).stderr)["status"] == "interrupted_requires_external_reconciliation"


def test_runtime_contract_blocks_before_and_between_rows(tmp_path, fake_script):
    row = make_row(tmp_path, fake_script); path, data = manifest(tmp_path, fake_script, [row]); fake_script.write_text("changed\n")
    assert result(invoke(path).stderr)["status"] == "runtime_contract_mismatch" and not Path(row["log_path"]).exists()
    fake_script.write_text(FAKE); first = make_row(tmp_path, fake_script, "first", extra=["--mutate-path", str(fake_script)]); second = make_row(tmp_path, fake_script, "second", extra=["--counter", str(tmp_path / "second")]); path, _ = manifest(tmp_path, fake_script, [first, second], "drift.json")
    assert result(invoke(path).stderr)["status"] == "runtime_contract_mismatch" and not (tmp_path / "second").exists()


def test_fresh_classification_blocks_future_external_output(tmp_path, fake_script):
    future = make_row(tmp_path, fake_script, "future", extra=["--counter", str(tmp_path / "future")])
    first = make_row(tmp_path, fake_script, "first", extra=["--write-path", future["expected_output_paths"][0]])
    path, _ = manifest(tmp_path, fake_script, [first, future])
    assert result(invoke(path).stderr)["status"] == "interrupted_requires_external_reconciliation" and not (tmp_path / "future").exists()


def test_input_binding_literal_argv_and_direct_execution(tmp_path, fake_script):
    record_argv = tmp_path / "argv.json"; channel = "channel;touch should_not_exist"
    row = make_row(tmp_path, fake_script, extra=["--record-argv", str(record_argv)])
    row["physical_channels"] = [channel]; start = row["producer_args"].index("--ch-lst") + 1; end = row["producer_args"].index("--binning"); row["producer_args"][start:end] = [channel]
    path, _ = manifest(tmp_path, fake_script, [row]); assert invoke(path).returncode == 0
    argv = json.loads(record_argv.read_text()); assert argv[0] == row["input_pkl"] and argv[argv.index("--ch-lst") + 1] == channel
    source = ENGINE.read_text(); assert "subprocess.run(" in source and "shell=True" not in source and "codex-run.sh" not in source
    assert "codex-run.sh" not in RUNNER.read_text() and "/bin/bash --noprofile" not in RUNNER.read_text()
    row = make_row(tmp_path, fake_script, "negative"); original = row["input_pkl"]; row["input_pkl"] = str(tmp_path / "missing-input.pkl"); row["producer_args"].extend(["--unrelated", original]); path, _ = manifest(tmp_path, fake_script, [row], "negative.json")
    assert result(invoke(path).stderr)["status"] == "runtime_preflight_error"


def test_lock_blocks_second_owner_and_no_finalizer_behavior(tmp_path, fake_script):
    row = make_row(tmp_path, fake_script, extra=["--sleep", "1"]); path, _ = manifest(tmp_path, fake_script, [row]); first = subprocess.Popen([str(RUNNER), str(path)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.monotonic() + 10
    while not Path(row["log_path"]).exists() and time.monotonic() < deadline: time.sleep(.02)
    assert result(invoke(path).stderr)["status"] == "execution_lock_held"
    first.communicate(timeout=10); assert first.returncode == 0
    source = ENGINE.read_text(); assert "datacards_post_processing" not in source and '"scalings.json"' not in source
