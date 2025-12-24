from pathlib import Path

import pytest

from analysis.topeft_run2 import metadata_authority


def _write_metadata(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_text("variables: {}\n")
    return path


def test_options_metadata_bypasses_registry(tmp_path: Path, monkeypatch) -> None:
    metadata_path = _write_metadata(tmp_path, "options.yml")

    def fail_registry(*args, **kwargs):
        raise AssertionError("Scenario registry should not be consulted for options metadata")

    monkeypatch.setattr(metadata_authority, "resolve_scenario_choice", fail_registry)

    resolved_path, provenance = metadata_authority.resolve_effective_metadata_path(
        scenario_name="TOP_22_006",
        metadata_cli=None,
        metadata_options=str(metadata_path),
    )

    assert Path(resolved_path) == metadata_path.resolve()
    assert provenance == "options"


def test_cli_metadata_bypasses_registry(tmp_path: Path, monkeypatch) -> None:
    cli_path = _write_metadata(tmp_path, "cli.yml")

    def fail_registry(*args, **kwargs):
        raise AssertionError("Scenario registry should not be consulted for CLI metadata")

    monkeypatch.setattr(metadata_authority, "resolve_scenario_choice", fail_registry)

    resolved_path, provenance = metadata_authority.resolve_effective_metadata_path(
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
        metadata_authority.resolve_effective_metadata_path(
            scenario_name="TOP_22_006",
            metadata_cli=str(cli_path),
            metadata_options=str(options_path),
        )


def test_registry_fallback_when_no_metadata() -> None:
    resolved_path, provenance = metadata_authority.resolve_effective_metadata_path(
        scenario_name="TOP_22_006",
        metadata_cli=None,
        metadata_options=None,
    )

    assert Path(resolved_path).exists()
    assert provenance == "scenario_registry"
