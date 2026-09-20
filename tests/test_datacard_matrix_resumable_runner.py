import json
from pathlib import Path
import subprocess
import time

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPOSITORY_ROOT / "analysis/topeft_run2/run_datacard_matrix_resumable.sh"
ENGINE = REPOSITORY_ROOT / "analysis/topeft_run2/datacard_matrix_runner.py"


FAKE_MAKE_CARDS = r'''
import json
from pathlib import Path
import sys
import time

argv = sys.argv[1:]

def one(option):
    return argv[argv.index(option) + 1]

def many(option):
    values = []
    for value in argv[argv.index(option) + 1:]:
        if value.startswith("--"):
            break
        values.append(value)
    return values

if "--counter" in argv:
    counter = Path(one("--counter"))
    current = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(current + 1))
if "--order-file" in argv:
    with Path(one("--order-file")).open("a") as output:
        output.write(one("--row-token") + "\n")
if "--assert-path-exists" in argv:
    assert Path(one("--assert-path-exists")).is_file()
if "--sleep-seconds" in argv:
    time.sleep(float(one("--sleep-seconds")))
if "--fail-before-output" in argv:
    raise SystemExit(7)

output_root = Path(one("--out-dir"))
output_root.mkdir(parents=True, exist_ok=True)
Path(one("--merge-report")).parent.mkdir(parents=True, exist_ok=True)
Path(one("--merge-report")).write_text(json.dumps({"fake": True}) + "\n")
(output_root / "selectedWCs.txt").write_text(json.dumps({"signal": ["ctW"]}) + "\n")
(output_root / "scalings-preselect.json").write_text(json.dumps([{"channel": "fake"}]) + "\n")
for output_name in many("--expected-output"):
    output = Path(output_name)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("synthetic\n")
'''


def row_paths(tmp_path, row_id, attempt_id):
    evidence = tmp_path / "evidence" / f"{row_id}_{attempt_id}"
    output_root = tmp_path / "cards"
    return {
        "output_root": output_root,
        "merge_report": evidence / "merge_report.json",
        "snapshot_directory": tmp_path / "control" / "snapshots" / f"{row_id}_{attempt_id}",
        "log": evidence / "row.log",
        "expected": [
            output_root / f"{row_id}_{attempt_id}.txt",
            output_root / f"{row_id}_{attempt_id}.root",
        ],
    }


def make_row(tmp_path, fake_script, row_id="row_01", attempt_id="attempt_01", extra=None):
    paths = row_paths(tmp_path, row_id, attempt_id)
    input_pkl = tmp_path / "input.pkl.gz"
    input_pkl.write_text("synthetic input\n")
    missing_parton = tmp_path / "missing_parton.root"
    missing_parton.write_text("synthetic payload\n")
    channels = ["channel_a", "channel_b"]
    years = ["2022", "2022EE"]
    producer_argv = [
        str(fake_script),
        str(input_pkl),
        "--out-dir",
        str(paths["output_root"]),
        "--var-lst",
        "lj0pt",
        "--ch-lst",
        *channels,
        "--binning",
        "fitting",
        "--year",
        *years,
        "--miss-parton-file",
        str(missing_parton),
        "--sr-registry",
        "ALL_CH_LST_SR",
        "--merge-report",
        str(paths["merge_report"]),
    ]
    producer_argv.extend(["--expected-output", *[str(path) for path in paths["expected"]]])
    producer_argv.extend(extra or [])
    return {
        "row_id": row_id,
        "attempt_id": attempt_id,
        "era": "run3",
        "working_directory": str(fake_script.parent),
        "input_pkl": str(input_pkl),
        "output_root": str(paths["output_root"]),
        "distribution": "lj0pt",
        "physical_channels": channels,
        "years": years,
        "missing_parton_path": str(missing_parton),
        "sr_registry": "ALL_CH_LST_SR",
        "merge_report_path": str(paths["merge_report"]),
        "snapshot_directory": str(paths["snapshot_directory"]),
        "log_path": str(paths["log"]),
        "expected_output_paths": [str(path) for path in paths["expected"]],
        "producer_argv": producer_argv,
    }


def write_manifest(tmp_path, rows, name="manifest.json"):
    manifest = {
        "schema": "topeft_datacard_matrix_v1",
        "control_root": str(tmp_path / "control"),
        "lock_path": str(tmp_path / "control" / "runner.lock"),
        "rows": rows,
    }
    path = tmp_path / name
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return path, manifest


@pytest.fixture
def fake_script(tmp_path):
    script = tmp_path / "fake" / "make_cards.py"
    script.parent.mkdir()
    script.write_text(FAKE_MAKE_CARDS)
    return script


def run_runner(manifest, mode=None):
    command = [str(RUNNER)]
    if mode:
        command.append(mode)
    command.append(str(manifest))
    return subprocess.run(command, text=True, capture_output=True)


def final_json(stream):
    starts = [index for index in range(len(stream)) if stream.startswith("{", index)]
    for index in reversed(starts):
        try:
            return json.loads(stream[index:])
        except json.JSONDecodeError:
            continue
    raise AssertionError(f"no final JSON object in stream: {stream!r}")


def test_manifest_schema_rejection_happens_before_execution(tmp_path, fake_script):
    counter = tmp_path / "counter"
    row = make_row(tmp_path, fake_script, extra=["--counter", str(counter)])
    row.pop("era")
    manifest, _ = write_manifest(tmp_path, [row])
    completed = run_runner(manifest)
    assert completed.returncode != 0
    assert final_json(completed.stderr)["status"] == "manifest_schema_error"
    assert not counter.exists()


def test_duplicate_row_id_rejected(tmp_path, fake_script):
    first = make_row(tmp_path, fake_script, "same", "attempt_01")
    second = make_row(tmp_path, fake_script, "same", "attempt_02")
    manifest, _ = write_manifest(tmp_path, [first, second])
    completed = run_runner(manifest, "--plan-only")
    assert completed.returncode != 0
    assert "duplicate row_id" in completed.stderr


def test_plan_only_preserves_order_and_does_not_execute_or_mutate(tmp_path, fake_script):
    counter = tmp_path / "counter"
    rows = [
        make_row(tmp_path, fake_script, "row_02", extra=["--counter", str(counter)]),
        make_row(tmp_path, fake_script, "row_01", extra=["--counter", str(counter)]),
    ]
    manifest, manifest_data = write_manifest(tmp_path, rows)
    completed = run_runner(manifest, "--plan-only")
    result = final_json(completed.stdout)
    assert completed.returncode == 0
    assert [item["row_id"] for item in result["rows"]] == ["row_02", "row_01"]
    assert [item["action"] for item in result["rows"]] == ["execute", "execute"]
    assert result["mutated"] is False
    assert not counter.exists()
    assert not Path(manifest_data["control_root"]).exists()


def test_status_does_not_mutate(tmp_path, fake_script):
    row = make_row(tmp_path, fake_script)
    manifest, manifest_data = write_manifest(tmp_path, [row])
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    completed = run_runner(manifest, "--status")
    after = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    result = final_json(completed.stdout)
    assert completed.returncode == 0
    assert result["rows"][0]["status"] == "not_started"
    assert before == after
    assert not Path(manifest_data["control_root"]).exists()


def test_successful_synthetic_execution_and_receipt(tmp_path, fake_script):
    row = make_row(tmp_path, fake_script)
    manifest, _ = write_manifest(tmp_path, [row])
    completed = run_runner(manifest)
    assert completed.returncode == 0, completed.stderr
    receipt_path = tmp_path / "control/receipts/row_01__attempt_01.json"
    receipt = json.loads(receipt_path.read_text())
    assert receipt["command_return_code"] == 0
    assert all(item["nonzero"] for item in receipt["observed_expected_outputs"])
    assert Path(receipt["artifacts"]["selected_wcs_snapshot"]["path"]).is_file()
    assert Path(receipt["artifacts"]["scalings_snapshot"]["path"]).is_file()
    assert Path(receipt["artifacts"]["merge_report_snapshot"]["path"]).is_file()


def test_two_rows_execute_sequentially_in_manifest_order(tmp_path, fake_script):
    order = tmp_path / "order.txt"
    first = make_row(
        tmp_path,
        fake_script,
        "row_a",
        extra=["--order-file", str(order), "--row-token", "row_a"],
    )
    second = make_row(
        tmp_path,
        fake_script,
        "row_b",
        extra=["--order-file", str(order), "--row-token", "row_b"],
    )
    manifest, _ = write_manifest(tmp_path, [first, second])
    completed = run_runner(manifest)
    assert completed.returncode == 0, completed.stderr
    assert order.read_text().splitlines() == ["row_a", "row_b"]


def test_second_row_not_launched_and_no_retry_after_first_failure(tmp_path, fake_script):
    order = tmp_path / "order.txt"
    counter = tmp_path / "counter"
    first = make_row(
        tmp_path,
        fake_script,
        "row_a",
        extra=[
            "--order-file",
            str(order),
            "--row-token",
            "row_a",
            "--counter",
            str(counter),
            "--fail-before-output",
        ],
    )
    second = make_row(
        tmp_path,
        fake_script,
        "row_b",
        extra=["--order-file", str(order), "--row-token", "row_b"],
    )
    manifest, _ = write_manifest(tmp_path, [first, second])
    completed = run_runner(manifest)
    assert completed.returncode != 0
    assert final_json(completed.stderr)["status"] == "row_command_failed"
    assert order.read_text().splitlines() == ["row_a"]
    assert counter.read_text() == "1"


def test_valid_receipt_skips_row_on_resume(tmp_path, fake_script):
    counter = tmp_path / "counter"
    row = make_row(tmp_path, fake_script, extra=["--counter", str(counter)])
    manifest, _ = write_manifest(tmp_path, [row])
    assert run_runner(manifest).returncode == 0
    resumed = run_runner(manifest)
    assert resumed.returncode == 0, resumed.stderr
    assert counter.read_text() == "1"
    assert final_json(resumed.stdout)["rows"][0]["action"] == "skipped_valid_receipt"


def test_existing_output_without_receipt_blocks(tmp_path, fake_script):
    row = make_row(tmp_path, fake_script)
    output = Path(row["expected_output_paths"][0])
    output.parent.mkdir(parents=True)
    output.write_text("preexisting\n")
    manifest, _ = write_manifest(tmp_path, [row])
    completed = run_runner(manifest)
    assert completed.returncode != 0
    assert final_json(completed.stderr)["status"] == "preexisting_unreceipted_output"


def test_stale_receipt_blocks(tmp_path, fake_script):
    row = make_row(tmp_path, fake_script)
    manifest, _ = write_manifest(tmp_path, [row])
    assert run_runner(manifest).returncode == 0
    snapshot = Path(row["snapshot_directory"]) / "selectedWCs.txt"
    snapshot.write_text("tampered\n")
    completed = run_runner(manifest)
    assert completed.returncode != 0
    assert final_json(completed.stderr)["status"] == "stale_or_invalid_execution_receipt"


def test_interrupted_log_without_receipt_blocks(tmp_path, fake_script):
    row = make_row(tmp_path, fake_script)
    log = Path(row["log_path"])
    log.parent.mkdir(parents=True)
    log.write_text("interrupted\n")
    manifest, _ = write_manifest(tmp_path, [row])
    status = final_json(run_runner(manifest, "--status").stdout)
    assert status["rows"][0]["status"] == "unreceipted_output"
    completed = run_runner(manifest)
    assert final_json(completed.stderr)["status"] == "interrupted_row_requires_external_reconciliation"


@pytest.mark.parametrize("artifact", ["merge_report", "snapshot"])
def test_attempt_evidence_without_receipt_blocks_as_interrupted(
    tmp_path, fake_script, artifact
):
    row = make_row(tmp_path, fake_script)
    if artifact == "merge_report":
        collision = Path(row["merge_report_path"])
    else:
        collision = Path(row["snapshot_directory"]) / "selectedWCs.txt"
    collision.parent.mkdir(parents=True)
    collision.write_text("preexisting\n")
    manifest, _ = write_manifest(tmp_path, [row])
    completed = run_runner(manifest)
    assert completed.returncode != 0
    assert (
        final_json(completed.stderr)["status"]
        == "interrupted_row_requires_external_reconciliation"
    )


def test_new_attempt_with_unique_paths_can_execute_after_failed_attempt(tmp_path, fake_script):
    first = make_row(
        tmp_path,
        fake_script,
        attempt_id="attempt_01",
        extra=["--fail-before-output"],
    )
    first_manifest, _ = write_manifest(tmp_path, [first], "first.json")
    assert run_runner(first_manifest).returncode != 0
    second = make_row(tmp_path, fake_script, attempt_id="attempt_02")
    second_manifest, _ = write_manifest(tmp_path, [second], "second.json")
    completed = run_runner(second_manifest)
    assert completed.returncode == 0, completed.stderr
    assert Path(first["log_path"]).is_file()
    assert (tmp_path / "control/receipts/row_01__attempt_02.json").is_file()


def test_snapshot_is_created_before_next_row(tmp_path, fake_script):
    first = make_row(tmp_path, fake_script, "row_a")
    first_snapshot = Path(first["snapshot_directory"]) / "selectedWCs.txt"
    second = make_row(
        tmp_path,
        fake_script,
        "row_b",
        extra=["--assert-path-exists", str(first_snapshot)],
    )
    manifest, _ = write_manifest(tmp_path, [first, second])
    completed = run_runner(manifest)
    assert completed.returncode == 0, completed.stderr


def test_lock_prevents_second_runner(tmp_path, fake_script):
    row = make_row(tmp_path, fake_script, extra=["--sleep-seconds", "2"])
    manifest, _ = write_manifest(tmp_path, [row])
    first = subprocess.Popen([str(RUNNER), str(manifest)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    log = Path(row["log_path"])
    deadline = time.monotonic() + 10
    while not log.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert log.exists()
    second = run_runner(manifest)
    assert second.returncode != 0
    assert final_json(second.stderr)["status"] == "execution_lock_held"
    first_stdout, first_stderr = first.communicate(timeout=15)
    assert first.returncode == 0, first_stderr + first_stdout


def test_receipt_records_exact_wrapper_and_resolved_argv(tmp_path, fake_script):
    row = make_row(tmp_path, fake_script)
    manifest, _ = write_manifest(tmp_path, [row])
    assert run_runner(manifest).returncode == 0
    receipt = json.loads(
        (tmp_path / "control/receipts/row_01__attempt_01.json").read_text()
    )
    invocation = receipt["wrapper_invocation"]
    assert invocation[:5] == [
        "/users/apiccine/work/correction-lib/codex-run.sh",
        "/bin/bash",
        "--noprofile",
        "--norc",
        "-c",
    ]
    assert receipt["exact_resolved_argv"][0] == "/users/apiccine/work/miniconda3/envs/clib-env/bin/python"
    assert receipt["exact_resolved_argv"][1] == str(fake_script)


def test_physical_channels_remain_shell_safe_literal_argv(tmp_path, fake_script):
    injected = tmp_path / "must_not_exist"
    channel = f"channel;touch {injected}"
    row = make_row(tmp_path, fake_script)
    row["physical_channels"] = [channel]
    start = row["producer_argv"].index("--ch-lst") + 1
    end = row["producer_argv"].index("--binning")
    row["producer_argv"][start:end] = [channel]
    manifest, _ = write_manifest(tmp_path, [row])
    completed = run_runner(manifest)
    assert completed.returncode == 0, completed.stderr
    assert not injected.exists()
    receipt = json.loads(
        (tmp_path / "control/receipts/row_01__attempt_01.json").read_text()
    )
    argv = receipt["exact_resolved_argv"]
    assert argv[argv.index("--ch-lst") + 1] == channel


def test_engine_has_no_finalizer_or_consolidation_behavior():
    source = ENGINE.read_text()
    assert "datacards_post_processing" not in source
    assert '"scalings.json"' not in source
