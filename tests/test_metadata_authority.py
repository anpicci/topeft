from analysis.topeft_run2 import metadata_authority


def test_cli_metadata_wins_over_options() -> None:
    selected, source = metadata_authority.select_metadata_source(
        "cli.yml",
        "options.yml",
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
