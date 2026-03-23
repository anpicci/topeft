from pathlib import Path

import pytest

from analysis.topeft_run2 import metadata_authority


def test_cli_metadata_selected_when_no_options() -> None:
    selected, source = metadata_authority.select_metadata_source(
        "cli.yml",
        None,
        metadata_authority.DEFAULT_METADATA_RELATIVE,
    )

    assert selected == metadata_authority.get_repo_root() / "cli.yml"
    assert source == "cli"


def test_options_metadata_selected_when_cli_missing() -> None:
    selected, source = metadata_authority.select_metadata_source(
        None,
        "options.yml",
        metadata_authority.DEFAULT_METADATA_RELATIVE,
    )

    assert selected == metadata_authority.get_repo_root() / "options.yml"
    assert source == "options"


def test_default_metadata_selected_when_none_provided() -> None:
    selected, source = metadata_authority.select_metadata_source(
        None,
        None,
        metadata_authority.DEFAULT_METADATA_RELATIVE,
    )

    assert selected == metadata_authority.get_repo_root() / metadata_authority.DEFAULT_METADATA_RELATIVE
    assert source == "default"


def test_relative_metadata_paths_cannot_escape_repo_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.setattr(metadata_authority, "get_repo_root", lambda: repo_root)

    with pytest.raises(ValueError, match="analysis/metadata/metadata.yml"):
        metadata_authority.select_metadata_source(
            "../outside.yml",
            None,
            metadata_authority.DEFAULT_METADATA_RELATIVE,
        )


def test_absolute_metadata_paths_outside_repo_root_are_allowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata_path = tmp_path / "outside.yml"
    metadata_path.write_text("channels: {}\nvariables: {}\n", encoding="utf-8")
    monkeypatch.setattr(metadata_authority, "get_repo_root", lambda: repo_root)

    resolved = metadata_authority.resolve_metadata_path(metadata_path)

    assert resolved == metadata_path.resolve()
