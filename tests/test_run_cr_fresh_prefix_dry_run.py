"""Fresh-prefix previews use the real launcher without creating campaign state."""

import json
import shlex
from hashlib import sha256

import pytest

from test_campaign_profile_handoff import backend, launch, manifest, state_path


def source_commands(stdout):
    return [shlex.split(line) for line in stdout.splitlines()
            if line.lstrip().startswith("./fullR3_run.sh ")]


@pytest.fixture
def prepared_campaign(tmp_path):
    """Prepare native state in-process; no synthetic launcher execution needed."""
    profile = "run2_sr_ext"
    root = tmp_path / "output"
    root.mkdir()
    archive = tmp_path / "synthetic_environment.tar.gz"
    archive.write_bytes(b"synthetic archive for the validation backend only\n")
    units = manifest.default_units(profile, "-")
    specs = manifest.make_specs(units, profile, "synthetic", str(root),
                                manifest.make_revision(1, units))
    identity = dict(production_profile=profile, campaign_tag="synthetic", output_dir=str(root))
    provenance = dict(topeft_git_commit="fixture", environment_file=str(archive),
                      environment_file_sha256=sha256(archive.read_bytes()).hexdigest(),
                      environment_fingerprint=f"{9:064d}", environment_mode="explicit_snapshot",
                      topcoffea_git_commit=f"{8:040d}",
                      topcoffea_relevant_source_fingerprint=f"{7:064d}")
    state = manifest.new_state(specs, manifest.partition_coverage(units, profile), identity,
                               manifest.profile_contract(profile), provenance)
    unit = state["units"][0]
    command = ["./fullR3_run.sh", "-y", *unit["years"], "-t", unit["output_tag"],
               "-s", "25000", "--sr", "--hist-vars", *unit["histograms"],
               "--category-groups", *unit["category_groups"], "--do-systs", "--do-np",
               "--defer-np", "-p", str(root), "--all-analysis", "--env-file", str(archive),
               "--snapshot", "-x", "work_queue", "--ttgamma-sample-role-policy", "split"]
    manifest.transition(state, unit["id"], "source", "running", "none", "fixture", tuple(command))
    return state, unit, archive


@pytest.mark.parametrize("profile", ("run2_sr_ext", "run3_sr_ext"))
def test_fresh_prefix_preview_resolves_all_units_without_outputs(tmp_path, backend, profile):
    result = launch(tmp_path, backend, "--dry-run", "--wq-manager-prefix", "fresh-",
                    "--wq-port", "0", "--wq-staging-base", str(tmp_path / "staging"),
                    "--wq-free-warning-bytes", "30000000000",
                    "--wq-min-free-bytes", "10000000000", "--wq-poll-seconds", "30",
                    "--wq-treereduction", "20", "--wq-processing-cores", "1",
                    profile=profile)
    assert result.returncode == 0, result.stdout + result.stderr
    commands = source_commands(result.stdout)
    assert len(commands) == 12
    managers = [cmd[cmd.index("--wq-manager-name") + 1] for cmd in commands]
    assert len(set(managers)) == 12
    assert all(name.startswith(f"fresh-{profile}_") and name.endswith("-a1")
               for name in managers)
    assert result.stdout.count("Data-driven command (not executed in dry-run):") == 12
    assert result.stdout.count("python run_analysis.py ") == 12
    for cmd in commands:
        assert "--dry-run" in cmd
        assert cmd[cmd.index("--port") + 1] == "0"
        assert cmd[cmd.index("--wq-invocation-id") + 1].endswith("_source_attempt_1")
    assert "12 unit commands resolved" in result.stdout
    assert not (tmp_path / "output").exists()
    assert not (tmp_path / "staging").exists()
    assert not (tmp_path / "source_order.log").exists()
    assert not (tmp_path / "dd_argv.log").exists()


def test_resume_prefix_preview_uses_native_next_attempt_without_mutation(
        tmp_path, backend, prepared_campaign):
    state, unit, archive = prepared_campaign
    manifest.transition(state, unit["id"], "source", "failed", "23", "fixture")
    path = state_path(tmp_path, "run2_sr_ext")
    manifest.atomic_json(path, state)
    before = path.read_bytes()
    assert [a["number"] for a in state["units"][0]["stages"]["source"]["attempts"]] == [1]
    assert manifest.next_source_attempt(state, unit["id"]) == 2
    result = launch(tmp_path, backend, "--resume", "--dry-run",
                    "--selected-fragment", unit["id"], "--wq-manager-prefix", "resume-",
                    profile="run2_sr_ext", archive=archive)
    assert result.returncode == 0, result.stdout + result.stderr
    command, = source_commands(result.stdout)
    assert command[command.index("--wq-manager-name") + 1] == f"resume-{unit['id']}-a2"
    assert path.read_bytes() == before
    assert not (tmp_path / "source_order.log").exists()


@pytest.mark.parametrize("collision", ("directory", "state", "dangling_symlink"))
def test_fresh_prefix_preview_refuses_existing_campaign(tmp_path, backend, collision):
    output = tmp_path / "output"
    if collision == "dangling_symlink":
        output.symlink_to(tmp_path / "absent_campaign", target_is_directory=True)
    else:
        output.mkdir()
        if collision == "state":
            state_path(tmp_path).write_text('{"do_not_adopt": true}\n')
    result = launch(tmp_path, backend, "--dry-run", "--wq-manager-prefix", "fresh-")
    assert result.returncode != 0
    assert "refusing overwrite" in result.stderr
    assert not source_commands(result.stdout)
    if collision == "state":
        assert json.loads(state_path(tmp_path).read_text()) == {"do_not_adopt": True}
