"""No-submit adapter tests use synthetic producers and explicit fixture resources."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from analysis.topeft_run2 import datacard_matrix_condor as condor
from analysis.topeft_run2 import datacard_matrix_runner as runner
from analysis.topeft_run2 import make_cards
from test_datacard_matrix_resumable_runner import fake_script, make_row, manifest, sha


resources = dict(request_cpus=1, request_memory="1GB", request_disk="1GB")


def test_material_identity_worker_command_and_no_submit(tmp_path, fake_script, monkeypatch):
    rows = [make_row(tmp_path, fake_script, name) for name in ("a", "b")]
    path, data = manifest(tmp_path, fake_script, rows)
    destination = tmp_path / "dispatch"
    def forbidden(*args, **kwargs):
        pytest.fail("material preparation invoked a subprocess")
    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "run", forbidden)
        result = condor.prepare_material(path, destination, **resources, max_runtime=100)
    assert result["submitted"] is False
    units = [json.loads((destination / "units" / (row["row_id"] + ".json")).read_text()) for row in rows]
    assert units == runner.derive_units(path)
    items = (destination / "items.txt").read_text().splitlines()
    assert [item.split()[0] for item in items] == ["a", "b"]
    submit = (destination / "datacards.sub").read_text()
    assert "queue row_id, unit_integrity from " in submit
    assert '+MaxRuntime = 100' in submit and "should_transfer_files = NO" in submit
    assert "condor_submit" not in (destination / "worker.sh").read_text()
    assert not any(Path(row["output_root"]).exists() for row in rows)
    worker = subprocess.run([str(destination / "worker.sh"), *items[0].split(), "123.0"], text=True, capture_output=True)
    assert worker.returncode == 0, worker.stderr
    assert runner.validate_receipt(json.loads(runner.receipt_path(data, rows[0]).read_text()), data, sha(path), rows[0])[0]
    assert not Path(rows[1]["output_root"]).exists()
    with pytest.raises(runner.RunnerError, match="exists"):
        condor.prepare_material(path, destination, **resources)


@pytest.mark.parametrize("field,value", [("request_cpus", None), ("request_cpus", 0), ("request_memory", None), ("request_memory", "1GB\nqueue 9"), ("request_disk", ""), ("max_runtime", 0)])
def test_resources_are_explicit_and_fail_before_output(tmp_path, fake_script, field, value):
    path, _ = manifest(tmp_path, fake_script, [make_row(tmp_path, fake_script)])
    with pytest.raises(runner.RunnerError):
        condor.prepare_material(path, tmp_path / "dispatch", **{**resources, field: value})
    assert not (tmp_path / "dispatch").exists()


def test_frontend_bypasses_all_parent_producer_work(tmp_path, fake_script, monkeypatch, capsys):
    path, _ = manifest(tmp_path, fake_script, [make_row(tmp_path, fake_script)])
    def forbidden(*args, **kwargs):
        pytest.fail("Condor frontend entered parent producer work or submitted")
    monkeypatch.setattr(make_cards, "_resolve_pkl_paths", forbidden)
    monkeypatch.setattr(make_cards.datacard_tools, "load_and_merge_histogram_pkls", forbidden)
    monkeypatch.setattr(make_cards.datacard_tools, "DatacardMaker", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(sys, "argv", ["make_cards.py", "--condor", "--matrix-manifest", str(path), "--condor-output", str(tmp_path / "dispatch"), "--request-cpus", "1", "--request-memory", "1GB", "--request-disk", "1GB"])
    make_cards.main()
    assert json.loads(capsys.readouterr().out)["submitted"] is False


def test_worker_rejects_descriptor_mutation(tmp_path, fake_script):
    rows = [make_row(tmp_path, fake_script, name) for name in ("a", "b")]
    path, _ = manifest(tmp_path, fake_script, rows)
    destination = tmp_path / "dispatch"
    condor.prepare_material(path, destination, **resources)
    item = (destination / "items.txt").read_text().splitlines()[0].split()
    (destination / "units" / "a.json").write_text((destination / "units" / "b.json").read_text())
    result = subprocess.run([str(destination / "worker.sh"), *item, "123.0"], capture_output=True, text=True)
    assert result.returncode == 2 and "stale_dispatch_input" in result.stderr
    assert not any(Path(row["output_root"]).exists() for row in rows)


@pytest.mark.parametrize("policy", ["warn", "error", "off"])
@pytest.mark.parametrize("binning", ["fitting", "processing"])
@pytest.mark.parametrize("skip", [False, True])
def test_worker_preserves_canonical_producer_options(tmp_path, fake_script, policy, binning, skip):
    extras = ["--year-coverage-policy", policy, "--rate-syst-json", "custom/rates.json"]
    if skip:
        extras.append("--skip-missing-parton-rate-syst")
    row = make_row(tmp_path, fake_script, extra=extras)
    row["producer_args"][row["producer_args"].index("--binning") + 1] = binning
    path, data = manifest(tmp_path, fake_script, [row])
    destination = tmp_path / "dispatch"
    condor.prepare_material(path, destination, **resources)
    unit = json.loads((destination / "units" / (row["row_id"] + ".json")).read_text())
    parent, _, selected = runner.resolve_unit(unit)
    assert runner.resolved_argv(parent, selected) == runner.resolved_argv(data, row)
    assert selected["producer_args"] == row["producer_args"]
    assert "--sr-registry" not in selected["producer_args"]
    assert "--condor" not in selected["producer_args"]


def test_scheduler_overlay_has_no_completion_or_retry_authority(tmp_path, fake_script):
    row = make_row(tmp_path, fake_script)
    path, data = manifest(tmp_path, fake_script, [row])
    status = runner.read_only("status", data, sha(path))
    overlay = {"schema": "topeft_datacard_scheduler_status_v1", "parent_integrity": sha(path), "observed_at": "synthetic", "units": [{"row_id": row["row_id"], "scheduler_id": "123.0", "state": "completed_exit_0"}]}
    runner.overlay_scheduler(status, overlay)
    assert status["rows"][0]["status"] == "not_started"
    assert status["rows"][0]["scheduler_metadata"]["completion_authority"] is False
    runner.execute_unit(data, sha(path), row)
    status = runner.read_only("status", data, sha(path))
    overlay["units"][0]["state"] = "removed"
    runner.overlay_scheduler(status, overlay)
    assert status["rows"][0]["status"] == "complete"


def test_frontend_requires_manifest_and_rejects_producer_options(monkeypatch):
    for args in (["--condor"], ["--condor", "--matrix-manifest", "/manifest.json", "--condor-output", "/dispatch", "--year", "2022"], ["--condor", "--matrix-manifest", "/manifest.json", "--condor-output", "/dispatch", "--binning", "fitting"], ["--condor", "--matrix-manifest", "/manifest.json", "--condor-output", "/dispatch", "--year-coverage-policy", "warn"], ["--chunks", "2"], ["--request-cpus", "1"]):
        monkeypatch.setattr(sys, "argv", ["make_cards.py", *args])
        with pytest.raises(SystemExit) as error:
            make_cards.main()
        assert error.value.code == 2


def test_scheduler_overlay_rejects_wrong_parent_or_duplicate(tmp_path, fake_script):
    row = make_row(tmp_path, fake_script)
    path, data = manifest(tmp_path, fake_script, [row])
    observation = {"row_id": row["row_id"], "scheduler_id": "1.0", "state": "idle"}
    overlay = {"schema": "topeft_datacard_scheduler_status_v1", "parent_integrity": sha(path), "observed_at": "synthetic", "units": [observation, observation]}
    with pytest.raises(runner.RunnerError, match="duplicate"):
        runner.overlay_scheduler(runner.read_only("status", data, sha(path)), overlay)
    overlay.update(parent_integrity="0" * 64, units=[observation])
    with pytest.raises(runner.RunnerError, match="binding"):
        runner.overlay_scheduler(runner.read_only("status", data, sha(path)), overlay)
