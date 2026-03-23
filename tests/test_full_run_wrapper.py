"""Tests for the strict options-only full_run.sh wrapper."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _wrapper_path() -> tuple[Path, Path]:
    repo_root = Path(__file__).resolve().parent.parent
    analysis_dir = repo_root / "analysis" / "topeft_run2"
    return repo_root, analysis_dir / "full_run.sh"


def test_full_run_sh_help() -> None:
    _, script_path = _wrapper_path()
    completed = subprocess.run(
        [str(script_path), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Usage:" in completed.stdout
    assert "--options <path[:profile]>" in completed.stdout


def test_full_run_sh_requires_options() -> None:
    _, script_path = _wrapper_path()
    completed = subprocess.run(
        [str(script_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "--options is required" in completed.stderr


def test_full_run_sh_rejects_unknown_flags() -> None:
    _, script_path = _wrapper_path()
    completed = subprocess.run(
        [str(script_path), "--executor", "futures"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "unsupported argument" in completed.stderr


def test_full_run_sh_rejects_options_mixed_with_exit_knobs() -> None:
    _, script_path = _wrapper_path()
    completed = subprocess.run(
        [
            str(script_path),
            "--options",
            "configs/fullR2_run.yml:cr",
            "--exit-marker-path",
            "/tmp/marker.txt",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "--options cannot be mixed" in completed.stderr


def test_full_run_sh_runs_with_options_only(tmp_path: Path) -> None:
    repo_root, script_path = _wrapper_path()
    output_dir = tmp_path / "pretend_output"
    outname = "test_wrapper_pretend"
    options_file = tmp_path / "wrapper_options.yml"
    options_file.write_text(
        "\n".join(
            [
                "defaults:",
                "  executor: futures",
                "  pretend: true",
                "  summary_verbosity: none",
                f"  outpath: {output_dir.as_posix()}",
                f"  outname: {outname}",
                "  jsonFiles:",
                "    - ../../input_samples/sample_jsons/test_samples/UL17_private_ttH_for_CI.json",
                "profiles:",
                "  sr:",
                "    scenarios:",
                "      - TOP_22_006",
                "    skip_cr: true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [str(script_path), "--options", f"{options_file}:sr"],
        check=False,
        capture_output=True,
        text=True,
        cwd=repo_root / "analysis" / "topeft_run2",
    )

    assert completed.returncode == 0
    output_file = output_dir / f"{outname}.pkl.gz"
    assert not output_file.exists()
    if output_dir.exists():
        assert list(output_dir.iterdir()) == []

    combined_output = (completed.stdout + completed.stderr).lower()
    forbidden_markers = (
        "submitting histogram task",
        "starting histogram task",
        "completed histogram task",
        "launching coffeadynamicdatareduction",
        "saving output in",
        "finished writing",
    )
    for marker in forbidden_markers:
        assert marker not in combined_output
