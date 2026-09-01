import os
import re
import shlex
import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RUN_DIRECTORY = REPOSITORY_ROOT / "analysis" / "topeft_run2"
RUN_CR = RUN_DIRECTORY / "run_cr.sh"
OUTPUT_ROOT = "/groups/klannon/apiccine/run2_srplot009_current_branch"
FUTURE_ENV_FILE = (
    "/groups/klannon/apiccine/run2_srplot009_current_branch_environment/"
    "topeft-envs/env_spec_FUTURE_LAUNCH.tar.gz"
)
CFG_BUNDLE = [
    "../../input_samples/cfgs/mc_signal_samples_NDSkim.cfg",
    "../../input_samples/cfgs/mc_background_samples_NDSkim.cfg",
    "../../input_samples/cfgs/data_samples_NDSkim.cfg",
]
EXPECTED_BLOCKS = [
    {
        "id": "block1",
        "tag": "current-branch-srplot009-block1",
        "histograms": ["njets", "lj0pt", "ptz", "ptz_wtau", "lt"],
        "categories": ["2l", "2lss_1tau", "2los_1tau", "4l"],
    },
    {
        "id": "block2",
        "tag": "current-branch-srplot009-block2",
        "histograms": ["njets", "lj0pt", "ptll", "lt"],
        "categories": ["3l_m_offZ"],
    },
    {
        "id": "block3",
        "tag": "current-branch-srplot009-block3",
        "histograms": ["njets", "lj0pt", "ptll", "lt"],
        "categories": ["3l_p_offZ"],
    },
    {
        "id": "block4",
        "tag": "current-branch-srplot009-block4",
        "histograms": ["njets", "lj0pt", "ptz", "lt"],
        "categories": ["3l_onZ_tau"],
    },
    {
        "id": "block5",
        "tag": "current-branch-srplot009-block5",
        "histograms": ["njets", "lj0pt", "ptz", "lt"],
        "categories": ["3l_fwd"],
    },
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


def _clean_validation_environment():
    environment = os.environ.copy()
    for name in (
        "SRPLOT009_VALIDATION_BACKEND",
        "SRPLOT009_VALIDATION_ROOT",
        "SRPLOT009_VALIDATION_SCENARIO",
    ):
        environment.pop(name, None)
    return environment


def _write_stub_backend(path):
    path.write_text(
        """#!/usr/bin/env bash
set -euo pipefail

action="$1"
scenario="$2"
shift 2
printf '%s\\t%s\\n' "$action" "$scenario" >> "${SRPLOT009_VALIDATION_ROOT}/backend_actions.tsv"

emit_identity() {
  local archive="$1"
  local digest
  digest=$(sha256sum "$archive")
  digest="${digest%% *}"
  printf 'env_file: %s\\n' "$archive"
  printf 'env_file_sha256: %s\\n' "$digest"
  printf 'env_manifest: %s.manifest.json\\n' "$archive"
  printf 'environment_fingerprint: %064d\\n' 9
  printf 'environment_validation_status: valid\\n'
  printf 'topcoffea_git_commit: %040d\\n' 8
  printf 'topcoffea_relevant_source_fingerprint: %064d\\n' 7
}

case "$action" in
  build_environment)
    namespace="$1"
    if [[ "$scenario" == "build_failure" ]]; then
      exit 17
    fi
    mkdir -p "$namespace/topeft-envs"
    archive="$namespace/topeft-envs/env_spec_9999999999999999.tar.gz"
    printf 'inert synthetic archive\\n' > "$archive"
    printf '{"synthetic": true}\\n' > "$archive.manifest.json"
    emit_identity "$archive"
    ;;
  validate_environment)
    namespace="$1"
    archive="$2"
    if [[ "$scenario" == "validation_failure" ]]; then
      exit 18
    fi
    emit_identity "$archive"
    ;;
  run_block)
    block_id="$1"
    env_file="$2"
    shift 2
    printf '%s\\t%s' "$block_id" "$env_file" >> "${SRPLOT009_VALIDATION_ROOT}/block_calls.tsv"
    printf '\\t%q' "$@" >> "${SRPLOT009_VALIDATION_ROOT}/block_calls.tsv"
    printf '\\n' >> "${SRPLOT009_VALIDATION_ROOT}/block_calls.tsv"
    : > "${SRPLOT009_VALIDATION_ROOT}/${block_id}.started"
    if [[ "$scenario" == "block_failure_3" && "$block_id" == "block3" ]]; then
      exit 23
    fi
    : > "${SRPLOT009_VALIDATION_ROOT}/${block_id}.finished"
    ;;
  *)
    exit 90
    ;;
esac
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _run_stub(tmp_path, scenario):
    backend = tmp_path / "stub_backend.sh"
    _write_stub_backend(backend)
    environment = _clean_validation_environment()
    environment.update(
        {
            "SRPLOT009_VALIDATION_BACKEND": str(backend),
            "SRPLOT009_VALIDATION_ROOT": str(tmp_path),
            "SRPLOT009_VALIDATION_SCENARIO": scenario,
        }
    )
    return subprocess.run(
        [str(RUN_CR)],
        cwd=RUN_DIRECTORY,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def test_dry_run_resolves_the_independent_five_block_oracle():
    assert not Path(OUTPUT_ROOT).exists()
    result = subprocess.run(
        [str(RUN_CR), "--dry-run"],
        cwd=RUN_DIRECTORY,
        env=_clean_validation_environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    commands = re.findall(r"Running the following command:\n([^\n]+)", result.stdout)
    assert len(commands) == len(EXPECTED_BLOCKS)

    seen_env_files = set()
    for command_text, expected in zip(commands, EXPECTED_BLOCKS):
        argv = shlex.split(command_text)
        assert argv[:2] == ["python", "run_analysis.py"]
        assert argv[2].split(",") == CFG_BUNDLE
        assert _option_values(argv, "--years") == ["UL16", "UL16APV", "UL17", "UL18"]
        assert _option_values(argv, "--hist-list") == expected["histograms"]
        assert _option_values(argv, "--category-groups") == expected["categories"]
        assert _option_values(argv, "-o", 1) == [
            f"UL16-UL16APV-UL17-UL18SRs_{expected['tag']}"
        ]
        assert _option_values(argv, "-p", 1) == [OUTPUT_ROOT]
        assert _option_values(argv, "-x", 1) == ["work_queue"]
        assert _option_values(argv, "--nworkers", 1) == ["8"]
        assert _option_values(argv, "-s", 1) == ["100000"]
        assert _option_values(argv, "--sample-universe-wrapper", 1) == ["fullR3_run.sh"]
        assert _option_values(argv, "--ttgamma-sample-role-policy", 1) == ["split"]
        assert "--skip-cr" in argv
        assert "--skip-sr" not in argv
        assert "--all-analysis" in argv
        assert "--do-systs" in argv
        assert "--do-np" in argv
        assert "--np-postprocess=inline" in argv
        assert "--defer-np" not in argv
        assert "--snapshot" not in argv
        env_file = _option_values(argv, "--env-file", 1)[0]
        seen_env_files.add(env_file)

    assert seen_env_files == {FUTURE_ENV_FILE}
    assert result.stdout.count("SRPLOT009_BLOCK_COMMAND\t") == 5
    assert "dry_run_complete:" in result.stdout
    assert not Path(OUTPUT_ROOT).exists()


def test_stub_success_builds_and_validates_one_archive_then_reuses_it(tmp_path):
    result = _run_stub(tmp_path, "success")
    assert result.returncode == 0, result.stdout

    archives = list((tmp_path / "environment" / "topeft-envs").glob("env_spec_*.tar.gz"))
    assert len(archives) == 1
    identity = (tmp_path / "environment" / "environment_identity.tsv").read_text(
        encoding="utf-8"
    )
    assert "fresh_namespace_absent_before_build\ttrue" in identity
    assert "fresh_archive_created_for_this_launch\ttrue" in identity
    assert "environment_validation_status\tvalid" in identity
    assert "same_explicit_archive_required_for_all_blocks\ttrue" in identity
    campaign_log = (tmp_path / "environment" / "campaign.log").read_text(encoding="utf-8")
    assert "campaign_command: ./run_cr.sh" in campaign_log
    assert "campaign_start_time_utc:" in campaign_log
    assert "campaign_end_time_utc:" in campaign_log
    assert "campaign_exit_code: 0" in campaign_log

    actions = (tmp_path / "backend_actions.tsv").read_text(encoding="utf-8").splitlines()
    assert [line.split("\t", 1)[0] for line in actions] == [
        "build_environment",
        "validate_environment",
        "run_block",
        "run_block",
        "run_block",
        "run_block",
        "run_block",
    ]
    block_calls = (tmp_path / "block_calls.tsv").read_text(encoding="utf-8").splitlines()
    assert len(block_calls) == 5
    assert {line.split("\t", 2)[1] for line in block_calls} == {str(archives[0])}
    for index, line in enumerate(block_calls, start=1):
        assert line.split("\t", 1)[0] == f"block{index}"
        assert "--env-file" in line
        assert str(archives[0]) in line
        assert "--np-postprocess=inline" in line

    events = (tmp_path / "output" / "srplot009_campaign_events.tsv").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(events) == 11
    assert sum("\tstarted\t" in row for row in events[1:]) == 5
    assert sum("\tfinished\t0" in row for row in events[1:]) == 5


def test_stub_build_or_validation_failure_starts_no_block(tmp_path):
    for scenario in ("build_failure", "validation_failure"):
        scenario_root = tmp_path / scenario
        scenario_root.mkdir()
        result = _run_stub(scenario_root, scenario)
        assert result.returncode != 0
        assert not (scenario_root / "output").exists()
        assert not (scenario_root / "block_calls.tsv").exists()
        assert "all five blocks remain not_started" in result.stdout


def test_stub_block_failure_stops_later_blocks_and_preserves_state(tmp_path):
    result = _run_stub(tmp_path, "block_failure_3")
    assert result.returncode == 23, result.stdout
    assert (tmp_path / "block1.finished").exists()
    assert (tmp_path / "block2.finished").exists()
    assert (tmp_path / "block3.started").exists()
    assert not (tmp_path / "block3.finished").exists()
    assert not (tmp_path / "block4.started").exists()
    assert not (tmp_path / "block5.started").exists()
    assert (tmp_path / "output").is_dir()
    assert (tmp_path / "environment" / "environment_identity.tsv").is_file()
    campaign_log = (tmp_path / "environment" / "campaign.log").read_text(encoding="utf-8")
    assert "campaign_exit_code: 23" in campaign_log
    assert "later blocks were not started" in result.stdout


def test_preexisting_environment_namespace_cannot_masquerade_as_fresh(tmp_path):
    (tmp_path / "environment").mkdir()
    backend = tmp_path / "stub_backend.sh"
    _write_stub_backend(backend)
    environment = _clean_validation_environment()
    environment.update(
        {
            "SRPLOT009_VALIDATION_BACKEND": str(backend),
            "SRPLOT009_VALIDATION_ROOT": str(tmp_path),
            "SRPLOT009_VALIDATION_SCENARIO": "success",
        }
    )
    result = subprocess.run(
        [str(RUN_CR)],
        cwd=RUN_DIRECTORY,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert result.returncode != 0
    assert "cannot prove a fresh campaign archive" in result.stdout
    assert not (tmp_path / "backend_actions.tsv").exists()
    assert not (tmp_path / "output").exists()


def test_preexisting_output_root_blocks_before_environment_build(tmp_path):
    (tmp_path / "output").mkdir()
    backend = tmp_path / "stub_backend.sh"
    _write_stub_backend(backend)
    environment = _clean_validation_environment()
    environment.update(
        {
            "SRPLOT009_VALIDATION_BACKEND": str(backend),
            "SRPLOT009_VALIDATION_ROOT": str(tmp_path),
            "SRPLOT009_VALIDATION_SCENARIO": "success",
        }
    )
    result = subprocess.run(
        [str(RUN_CR)],
        cwd=RUN_DIRECTORY,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert result.returncode != 0
    assert "refusing overwrite, merge, or resume" in result.stdout
    assert not (tmp_path / "backend_actions.tsv").exists()
    assert not (tmp_path / "environment").exists()
