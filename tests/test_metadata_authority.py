from pathlib import Path

import pytest

from analysis.topeft_run2.metadata_authority import resolve_effective_metadata_path


def _write_metadata(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_text("variables: {}\n")
    return path


def test_options_metadata_wins_over_registry(tmp_path: Path) -> None:
    metadata_path = _write_metadata(tmp_path, "options.yml")
    resolved_path, provenance = resolve_effective_metadata_path(
        scenario_name="TOP_22_006",
        metadata_cli=None,
        metadata_options=str(metadata_path),
    )

    assert Path(resolved_path) == metadata_path.resolve()
    assert provenance == "options"


def test_cli_metadata_wins_over_registry(tmp_path: Path) -> None:
    cli_path = _write_metadata(tmp_path, "cli.yml")
    resolved_path, provenance = resolve_effective_metadata_path(
        scenario_name="TOP_22_006",
        metadata_cli=str(cli_path),
        metadata_options=None,
    )

    assert Path(resolved_path) == cli_path.resolve()
    assert provenance == "cli"


def test_cli_and_options_metadata_are_mutually_exclusive(tmp_path: Path) -> None:
    cli_path = _write_metadata(tmp_path, "cli.yml")
    options_path = _write_metadata(tmp_path, "options.yml")
    with pytest.raises(ValueError, match="mutually exclusive"):
        resolve_effective_metadata_path(
            scenario_name="TOP_22_006",
            metadata_cli=str(cli_path),
            metadata_options=str(options_path),
        )
