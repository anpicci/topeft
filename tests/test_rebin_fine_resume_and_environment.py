import hashlib
import importlib
import json
import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = REPOSITORY_ROOT / "analysis" / "topeft_run2"
RUN_CR = ANALYSIS_DIR / "run_cr.sh"
FULL_R3_RUN = ANALYSIS_DIR / "fullR3_run.sh"
STATE_FILENAME = ".rebin_fine_campaign_state.json"
CHANNEL_REGISTRY = REPOSITORY_ROOT / "topeft" / "channels" / "ch_lst.json"


def _run(*args):
    return subprocess.run(
        [str(RUN_CR), *args],
        cwd=ANALYSIS_DIR,
        check=False,
        capture_output=True,
        text=True,
    )


def _commit():
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT, text=True
    ).strip()


def _write_env(tmp_path, content=b"synthetic poncho archive"):
    path = tmp_path / "verified_env.tar.gz"
    path.write_bytes(content)
    return path


def _planned_blocks(output_dir, campaign_tag):
    rows = (
        ("run2_a", "2016APV 2016 2017 2018", "2lss_1tau 3l_m_offZ", "lj0pt ptll ptz_wtau"),
        ("run2_b", "2016APV 2016 2017 2018", "3l_p_offZ 3l_onZ_tau", "lj0pt ptz ptll"),
        ("run2_c", "2016APV 2016 2017 2018", "3l_fwd", "lt"),
        ("run3_a", "2022 2022EE 2023 2023BPix", "2lss_1tau 3l_m_offZ", "lj0pt ptll ptz_wtau"),
        ("run3_b", "2022 2022EE 2023 2023BPix", "3l_p_offZ 3l_onZ_tau", "lj0pt ptz ptll"),
        ("run3_c", "2022 2022EE 2023 2023BPix", "3l_fwd", "lt"),
    )
    blocks = []
    for block_id, years, categories, histograms in rows:
        output_tag = "{}_{}_{}".format(
            campaign_tag,
            categories.replace(" ", "-"),
            histograms.replace(" ", "-"),
        )
        output_name = "{}SRs_{}".format(years.replace(" ", "-"), output_tag)
        blocks.append(
            {
                "id": block_id,
                "years": years.split(),
                "category_groups": categories.split(),
                "histograms": histograms.split(),
                "output_tag": output_tag,
                "output_name": output_name,
                "expected_outputs": [
                    str(output_dir / f"{output_name}.pkl.gz"),
                    str(output_dir / f"{output_name}_np.pkl.gz"),
                ],
                "status": "planned",
                "exit_code": None,
                "last_transition_utc": "2026-01-01T00:00:00Z",
            }
        )
    return blocks


def _write_state(output_dir, campaign_tag, env_file, *, status="planned"):
    blocks = _planned_blocks(output_dir, campaign_tag)
    for block in blocks:
        block["status"] = status
    state = {
        "schema_version": 1,
        "production_profile": "rebin_fine",
        "campaign_tag": campaign_tag,
        "output_dir": str(output_dir),
        "topeft_git_commit": _commit(),
        "env_file": str(env_file.resolve()),
        "env_file_sha256": hashlib.sha256(env_file.read_bytes()).hexdigest(),
        "ttgamma_sample_role_policy": "split",
        "do_systs": True,
        "do_np": True,
        "created_at_utc": "2026-01-01T00:00:00Z",
        "updated_at_utc": "2026-01-01T00:00:00Z",
        "blocks": blocks,
    }
    state_path = output_dir / STATE_FILENAME
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return state_path, state


def _materialize_expected_outputs(state):
    for block in state["blocks"]:
        for output in block["expected_outputs"]:
            Path(output).write_bytes(b"synthetic completed output")


def test_rebin_fine_requires_verified_absolute_environment_archive(tmp_path):
    output_dir = tmp_path / "fresh"
    missing_env = tmp_path / "missing.tar.gz"

    no_env = _run(
        "--production-profile",
        "rebin_fine",
        "--dry-run",
        "--output-dir",
        str(output_dir),
    )
    assert no_env.returncode != 0
    assert "requires --env-file" in no_env.stderr

    relative = _run(
        "--production-profile",
        "rebin_fine",
        "--dry-run",
        "--output-dir",
        str(output_dir),
        "--env-file",
        "relative.tar.gz",
    )
    assert relative.returncode != 0
    assert "must be an absolute path" in relative.stderr

    missing = _run(
        "--production-profile",
        "rebin_fine",
        "--dry-run",
        "--output-dir",
        str(output_dir),
        "--env-file",
        str(missing_env),
    )
    assert missing.returncode != 0
    assert "readable, non-empty regular file" in missing.stderr

    empty_env = tmp_path / "empty.tar.gz"
    empty_env.touch()
    empty = _run(
        "--production-profile",
        "rebin_fine",
        "--dry-run",
        "--output-dir",
        str(output_dir),
        "--env-file",
        str(empty_env),
    )
    assert empty.returncode != 0
    assert "readable, non-empty regular file" in empty.stderr


def test_rebin_fine_dry_run_reuses_one_env_without_output_side_effects(tmp_path):
    output_dir = tmp_path / "fresh_dry_run"
    env_file = _write_env(tmp_path)
    env_sha256 = hashlib.sha256(env_file.read_bytes()).hexdigest()

    result = _run(
        "--production-profile",
        "rebin_fine",
        "--dry-run",
        "--output-dir",
        str(output_dir),
        "--campaign-tag",
        "fine_test",
        "--env-file",
        str(env_file),
    )

    assert result.returncode == 0, result.stderr
    assert f"env_file: {env_file.resolve()}" in result.stdout
    assert f"env_file_sha256: {env_sha256}" in result.stdout
    assert "environment_policy: explicit_single_archive" in result.stdout
    assert result.stdout.count("rebin_fine dry-run resolved") == 6
    assert result.stdout.count(f"--env-file {env_file.resolve()}") >= 6
    assert "poncho_package_create" not in result.stdout
    assert env_file.read_bytes() == b"synthetic poncho archive"
    assert not output_dir.exists()
    assert not (output_dir / STATE_FILENAME).exists()


def test_fullr3_forwards_env_file_to_run_analysis_dry_run(tmp_path):
    env_file = _write_env(tmp_path)
    result = subprocess.run(
        [
            str(FULL_R3_RUN),
            "-y",
            "2022",
            "-t",
            "env_forward",
            "--sr",
            "--dry-run",
            "--env-file",
            str(env_file.resolve()),
        ],
        cwd=ANALYSIS_DIR,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert f"--env-file {env_file.resolve()}" in result.stdout


def test_env_override_bypasses_automatic_poncho_packaging(tmp_path, monkeypatch):
    env_file = _write_env(tmp_path)
    monkeypatch.syspath_prepend(str(ANALYSIS_DIR))
    run_analysis = importlib.import_module("run_analysis")

    def unexpected_packaging(**_kwargs):
        raise AssertionError("automatic environment packaging was called")

    monkeypatch.setattr(run_analysis.remote_environment, "get_environment", unexpected_packaging)
    assert run_analysis._resolve_environment_file(str(env_file), True) == str(
        env_file.resolve()
    )


def test_rebin_fine_does_not_run_legacy_environment_cache_cleanup():
    source = RUN_CR.read_text(encoding="utf-8")
    assert (
        'if [[ "${dry_run}" == "false" && "${production_profile}" != "rebin_fine" ]]; then\n'
        "    clean_env_cache"
    ) in source


def test_rebin_fine_preserves_the_frozen_six_block_physics_packing():
    registry = json.loads(CHANNEL_REGISTRY.read_text(encoding="utf-8"))[
        "ALL_CH_LST_SR"
    ]
    expected = {
        "2lss_1tau": 16,
        "3l_m_offZ": 24,
        "3l_p_offZ": 24,
        "3l_onZ_tau": 16,
        "3l_fwd": 24,
    }
    observed = {
        group: len(config["lep_chan_lst"]) * len(config["jet_lst"])
        for group, config in registry.items()
        if group in expected
    }
    assert observed == expected
    blocks = _planned_blocks(Path("/tmp/rebin_fine_contract"), "fine_contract")
    assert [block["histograms"] for block in blocks] == [
        ["lj0pt", "ptll", "ptz_wtau"],
        ["lj0pt", "ptz", "ptll"],
        ["lt"],
        ["lj0pt", "ptll", "ptz_wtau"],
        ["lj0pt", "ptz", "ptll"],
        ["lt"],
    ]
    assert all("njets" not in block["histograms"] for block in blocks)


def test_fresh_rebin_fine_rejects_existing_namespace(tmp_path):
    output_dir = tmp_path / "existing"
    output_dir.mkdir()
    env_file = _write_env(tmp_path)
    result = _run(
        "--production-profile",
        "rebin_fine",
        "--output-dir",
        str(output_dir),
        "--campaign-tag",
        "fine_test",
        "--env-file",
        str(env_file),
    )

    assert result.returncode != 0
    assert "output directory already exists" in result.stderr


def test_resume_skips_only_successful_blocks_with_present_outputs(tmp_path):
    output_dir = tmp_path / "resume_success"
    output_dir.mkdir()
    env_file = _write_env(tmp_path)
    state_path, state = _write_state(output_dir, "fine_resume", env_file, status="success")
    _materialize_expected_outputs(state)

    result = _run(
        "--production-profile",
        "rebin_fine",
        "--resume",
        "--output-dir",
        str(output_dir),
        "--campaign-tag",
        "fine_resume",
        "--env-file",
        str(env_file),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.count("Skipping validated rebin_fine block") == 6
    assert "Running the following command:" not in result.stdout
    assert json.loads(state_path.read_text())["blocks"][0]["status"] == "success"


def test_resume_rejects_state_drift_and_ambiguous_outputs(tmp_path):
    output_dir = tmp_path / "resume_drift"
    output_dir.mkdir()
    env_file = _write_env(tmp_path)
    state_path, state = _write_state(output_dir, "fine_resume", env_file)

    tag_mismatch = _run(
        "--production-profile",
        "rebin_fine",
        "--resume",
        "--output-dir",
        str(output_dir),
        "--campaign-tag",
        "different_tag",
        "--env-file",
        str(env_file),
    )
    assert tag_mismatch.returncode != 0
    assert "mismatch for campaign_tag" in tag_mismatch.stderr

    state["topeft_git_commit"] = "different_commit"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    commit_mismatch = _run(
        "--production-profile",
        "rebin_fine",
        "--resume",
        "--output-dir",
        str(output_dir),
        "--campaign-tag",
        "fine_resume",
        "--env-file",
        str(env_file),
    )
    assert commit_mismatch.returncode != 0
    assert "mismatch for topeft_git_commit" in commit_mismatch.stderr

    state["topeft_git_commit"] = _commit()
    state["blocks"][0]["expected_outputs"][0]
    Path(state["blocks"][0]["expected_outputs"][0]).write_bytes(b"partial")
    state_path.write_text(json.dumps(state), encoding="utf-8")
    collision = _run(
        "--production-profile",
        "rebin_fine",
        "--resume",
        "--output-dir",
        str(output_dir),
        "--campaign-tag",
        "fine_resume",
        "--env-file",
        str(env_file),
    )
    assert collision.returncode != 0
    assert "Refusing ambiguous overwrite" in collision.stderr


def test_resume_marks_missing_success_output_incomplete_and_dry_runs_failed_block(tmp_path):
    output_dir = tmp_path / "resume_incomplete"
    output_dir.mkdir()
    env_file = _write_env(tmp_path)
    state_path, state = _write_state(output_dir, "fine_resume", env_file, status="success")
    _materialize_expected_outputs(state)
    Path(state["blocks"][0]["expected_outputs"][1]).unlink()

    missing_success = _run(
        "--production-profile",
        "rebin_fine",
        "--resume",
        "--output-dir",
        str(output_dir),
        "--campaign-tag",
        "fine_resume",
        "--env-file",
        str(env_file),
    )
    assert missing_success.returncode != 0
    assert "marks run2_a successful" in missing_success.stderr
    updated = json.loads(state_path.read_text())
    assert updated["blocks"][0]["status"] == "failed_or_incomplete"

    for output in state["blocks"][0]["expected_outputs"]:
        Path(output).unlink(missing_ok=True)
    dry_resume = _run(
        "--production-profile",
        "rebin_fine",
        "--resume",
        "--dry-run",
        "--output-dir",
        str(output_dir),
        "--campaign-tag",
        "fine_resume",
        "--env-file",
        str(env_file),
    )
    assert dry_resume.returncode == 0, dry_resume.stderr
    assert dry_resume.stdout.count("Skipping validated rebin_fine block") == 5
    assert dry_resume.stdout.count("rebin_fine dry-run resolved") == 1
    assert json.loads(state_path.read_text())["blocks"][0]["status"] == "failed_or_incomplete"


def test_resume_rejects_environment_sha_drift(tmp_path):
    output_dir = tmp_path / "resume_env_sha"
    output_dir.mkdir()
    env_file = _write_env(tmp_path)
    _write_state(output_dir, "fine_resume", env_file)
    env_file.write_bytes(b"different synthetic poncho archive")

    result = _run(
        "--production-profile",
        "rebin_fine",
        "--resume",
        "--output-dir",
        str(output_dir),
        "--campaign-tag",
        "fine_resume",
        "--env-file",
        str(env_file),
    )

    assert result.returncode != 0
    assert "mismatch for env_file_sha256" in result.stderr
