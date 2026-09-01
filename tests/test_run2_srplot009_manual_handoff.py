import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RUN_DIRECTORY = REPOSITORY_ROOT / "analysis" / "topeft_run2"
RUN_CR = RUN_DIRECTORY / "run_cr.sh"
FROZEN_ENV = RUN_DIRECTORY / "topeft-envs" / "env_spec_9d72aad444117c28.tar.gz"
FROZEN_SHA256 = "8245afe4b3c28f4948039d383ad2176f1ee3ebb5e61bcdf1b49289452b025332"
PUBLIC_PROFILES = {
    "run2_full", "run3_full", "run2_run3_full",
    "run2_full_CR", "run3_full_CR", "run2_run3_full_CR",
}
MATRIX_EARLY_PROFILES = (
    "run2_full",
    "run2_full_CR",
    "run3_full_CR",
    "run2_run3_full",
    "run2_run3_full_CR",
)
RUN2_SR_BLOCKS = [
    (("UL16", "UL16APV", "UL17", "UL18"), ("2l", "2lss_1tau", "2los_1tau", "4l"), ("njets", "lj0pt", "ptz", "ptz_wtau", "lt")),
    (("UL16", "UL16APV", "UL17", "UL18"), ("3l_m_offZ",), ("njets", "lj0pt", "ptll", "lt")),
    (("UL16", "UL16APV", "UL17", "UL18"), ("3l_p_offZ",), ("njets", "lj0pt", "ptll", "lt")),
    (("UL16", "UL16APV", "UL17", "UL18"), ("3l_onZ_tau",), ("njets", "lj0pt", "ptz", "lt")),
    (("UL16", "UL16APV", "UL17", "UL18"), ("3l_fwd",), ("njets", "lj0pt", "ptz", "lt")),
]
RUN3_SR_BLOCKS = [
    (("2022", "2022EE", "2023", "2023BPix"), categories, histograms)
    for _, categories, histograms in RUN2_SR_BLOCKS
]


def _option_values(argv, option, count=None):
    start = argv.index(option) + 1
    if count is not None:
        return argv[start : start + count]
    values = []
    for item in argv[start:]:
        if item.startswith("-"):
            break
        values.append(item)
    return values


def _commands(stdout):
    return [
        shlex.split(text)
        for text in re.findall(r"Running the following command:\n([^\n]+)", stdout)
    ]


def _scientific_signature(argv):
    return (
        tuple(_option_values(argv, "--years")),
        tuple(_option_values(argv, "--category-groups")),
        tuple(_option_values(argv, "--hist-list")),
        "--skip-cr" in argv,
        "--skip-sr" in argv,
        "--do-systs" in argv,
        "--do-np" in argv,
        "--np-postprocess=inline" in argv,
        "--np-postprocess=defer" in argv,
        tuple(_option_values(argv, "-x", 1)),
        tuple(_option_values(argv, "-s", 1)),
        tuple(_option_values(argv, "--env-file", 1)),
        "--snapshot" in argv,
    )


def _clean_environment():
    environment = os.environ.copy()
    for name in (
        "SRPLOT009_VALIDATION_BACKEND",
        "SRPLOT009_VALIDATION_ROOT",
        "SRPLOT009_VALIDATION_SCENARIO",
    ):
        environment.pop(name, None)
    return environment


def _run(profile, output_dir, campaign_tag, *, dry_run=True, environment=None):
    command = [
        str(RUN_CR), "--production-profile", profile,
        "--output-dir", str(output_dir),
        "--campaign-tag", campaign_tag,
        "--env-file", str(FROZEN_ENV),
    ]
    if dry_run:
        command.append("--dry-run")
    return subprocess.run(
        command,
        cwd=RUN_DIRECTORY,
        env=environment or _clean_environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _assert_common(argv):
    assert argv[:2] == ["python", "run_analysis.py"]
    assert "--snapshot" in argv
    assert _option_values(argv, "--env-file", 1) == [str(FROZEN_ENV)]
    assert _option_values(argv, "-s", 1) == ["100000"]
    assert _option_values(argv, "-x", 1) == ["work_queue"]
    assert "--workers" not in argv
    assert "--nworkers" not in argv
    assert "--do-systs" in argv
    assert "--do-np" in argv
    assert "--options" in argv


def _write_backend(path):
    path.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
action="$1"
scenario="$2"
shift 2
printf '%s\\t%s\\n' "$action" "$scenario" >> "${{SRPLOT009_VALIDATION_ROOT}}/backend_actions.tsv"
case "$action" in
  validate_environment)
    archive="$1"
    [[ "$scenario" != validation_failure ]] || exit 18
    printf 'env_file: %s\\n' "$archive"
    printf 'env_file_sha256: {FROZEN_SHA256}\\n'
    printf 'env_manifest: %s.manifest.json\\n' "$archive"
    printf 'environment_fingerprint: %064d\\n' 9
    printf 'environment_validation_status: valid\\n'
    printf 'topcoffea_git_commit: %040d\\n' 8
    printf 'topcoffea_relevant_source_fingerprint: %064d\\n' 7
    ;;
  run_block)
    block_id="$1"
    env_file="$2"
    shift 2
    printf '%s\\t%s\\t%s\\n' "$block_id" "$env_file" "$*" >> "${{SRPLOT009_VALIDATION_ROOT}}/block_calls.tsv"
    : > "${{SRPLOT009_VALIDATION_ROOT}}/${{block_id}}.started"
    [[ "$scenario" != block_failure_3 || "$block_id" != block3 ]] || exit 23
    : > "${{SRPLOT009_VALIDATION_ROOT}}/${{block_id}}.finished"
    ;;
  *) exit 90 ;;
esac
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def test_public_profile_inventory_and_default_alias():
    source = RUN_CR.read_text(encoding="utf-8")
    for profile in PUBLIC_PROFILES:
        assert profile in source
    assert "rebin_fine" in source
    result = subprocess.run(
        [str(RUN_CR), "--dry-run"],
        cwd=RUN_DIRECTORY,
        env=_clean_environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    assert [signature[:3] for signature in map(_scientific_signature, _commands(result.stdout))] == RUN2_SR_BLOCKS


def test_four_component_profiles_resolve_authoritative_contracts(tmp_path):
    observed = {}
    for profile in ("run2_full", "run3_full", "run2_full_CR", "run3_full_CR"):
        result = _run(profile, tmp_path / profile, f"test-{profile}")
        assert result.returncode == 0, result.stdout
        commands = _commands(result.stdout)
        observed[profile] = commands
        assert commands
        for argv in commands:
            _assert_common(argv)
        assert result.stdout.count("sumw2_storage_mode: full_diagnostics") == 1
        assert not (tmp_path / profile).exists()

    assert [signature[:3] for signature in map(_scientific_signature, observed["run2_full"])] == RUN2_SR_BLOCKS
    assert [signature[:3] for signature in map(_scientific_signature, observed["run3_full"])] == RUN3_SR_BLOCKS
    assert len(observed["run2_full_CR"]) == 6
    assert len(observed["run3_full_CR"]) == 12
    assert {tuple(_option_values(a, "--years")) for a in observed["run2_full_CR"]} == {("2016APV", "2016", "2017", "2018")}
    assert {tuple(_option_values(a, "--years")) for a in observed["run3_full_CR"]} == {("2022", "2022EE"), ("2023", "2023BPix")}
    assert all("--skip-cr" in a for a in observed["run2_full"] + observed["run3_full"])
    assert all("--skip-sr" in a for a in observed["run2_full_CR"] + observed["run3_full_CR"])


def test_combined_profiles_reuse_components_and_separate_namespaces(tmp_path):
    for combined, first, second, suffix in (
        ("run2_run3_full", "run2_full", "run3_full", ""),
        ("run2_run3_full_CR", "run2_full_CR", "run3_full_CR", "_CR"),
    ):
        run2 = _run(first, tmp_path / f"single2{suffix}", f"matrix_run2{suffix}")
        run3 = _run(second, tmp_path / f"single3{suffix}", f"matrix_run3{suffix}")
        combined_root = tmp_path / combined
        result = _run(combined, combined_root, "matrix")
        assert run2.returncode == run3.returncode == result.returncode == 0
        expected = list(map(_scientific_signature, _commands(run2.stdout) + _commands(run3.stdout)))
        assert list(map(_scientific_signature, _commands(result.stdout))) == expected
        assert f"{combined_root}/run2{suffix}" in result.stdout
        assert f"{combined_root}/run3{suffix}" in result.stdout
        assert not combined_root.exists()


def test_stubbed_failure_stops_later_blocks_and_combined_run3(tmp_path):
    backend = tmp_path / "backend.sh"
    _write_backend(backend)
    environment = _clean_environment()
    environment.update(
        {
            "SRPLOT009_VALIDATION_BACKEND": str(backend),
            "SRPLOT009_VALIDATION_ROOT": str(tmp_path),
            "SRPLOT009_VALIDATION_SCENARIO": "block_failure_3",
        }
    )
    output_root = tmp_path / "combined"
    result = _run("run2_run3_full", output_root, "failure-test", dry_run=False, environment=environment)
    assert result.returncode == 23, result.stdout
    assert (output_root / "run2").is_dir()
    assert not (output_root / "run3").exists()
    assert (tmp_path / "block3.started").exists()
    assert not (tmp_path / "block4.started").exists()
    assert "later blocks were not started" in result.stdout


def test_collision_and_frozen_archive_override_fail_closed(tmp_path):
    collision = tmp_path / "collision"
    collision.mkdir()
    result = _run("run2_full_CR", collision, "collision")
    assert result.returncode != 0
    assert "refusing overwrite" in result.stdout

    result = subprocess.run(
        [
            str(RUN_CR), "--production-profile", "run2_full", "--dry-run",
            "--output-dir", str(tmp_path / "other"), "--campaign-tag", "other",
            "--env-file", str(tmp_path / "wrong.tar.gz"),
        ],
        cwd=RUN_DIRECTORY,
        env=_clean_environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert result.returncode != 0
    assert "pinned to the maintained frozen snapshot archive" in result.stdout


@pytest.mark.parametrize("profile", MATRIX_EARLY_PROFILES)
def test_every_matrix_owned_profile_rejects_unknown_tokens_before_side_effects(
    tmp_path, profile
):
    output_root = tmp_path / profile
    result = subprocess.run(
        [
            str(RUN_CR),
            "--production-profile",
            profile,
            "--dry-rnu",
            "--output-dir",
            str(output_root),
            "--campaign-tag",
            f"unknown-{profile}",
        ],
        cwd=RUN_DIRECTORY,
        env=_clean_environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert result.returncode != 0
    assert "unsupported run_cr.sh option '--dry-rnu'" in result.stdout
    assert not output_root.exists()


def test_matrix_owned_missing_env_value_fails_before_side_effects(tmp_path):
    output_root = tmp_path / "missing-env-value"
    result = subprocess.run(
        [
            str(RUN_CR),
            "--production-profile",
            "run2_full",
            "--dry-run",
            "--output-dir",
            str(output_root),
            "--campaign-tag",
            "missing-env-value",
            "--env-file",
        ],
        cwd=RUN_DIRECTORY,
        env=_clean_environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert result.returncode != 0
    assert "--env-file requires a value" in result.stdout
    assert not output_root.exists()


@pytest.mark.parametrize(
    "value_option",
    ("--production-profile", "--output-dir", "--campaign-tag", "--env-file"),
)
def test_matrix_value_options_reject_another_option_as_value_before_side_effects(
    tmp_path, value_option
):
    output_root = tmp_path / value_option.removeprefix("--")
    command = [
        str(RUN_CR),
        "--production-profile",
        "run2_full",
        "--output-dir",
        str(output_root),
        "--campaign-tag",
        "malformed-value",
        "--env-file",
        str(FROZEN_ENV),
    ]
    if value_option == "--campaign-tag":
        del command[5:7]
    elif value_option == "--env-file":
        del command[7:9]
    command.extend((value_option, "--dry-run"))

    result = subprocess.run(
        command,
        cwd=RUN_DIRECTORY,
        env=_clean_environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode != 0
    assert f"{value_option} requires a value" in result.stdout
    assert not output_root.exists()
