from analysis.topeft_run2 import metadata_authority


def test_relative_metadata_paths_resolve_from_repo_root(tmp_path, monkeypatch) -> None:
    metadata_path = tmp_path / "relative_meta.yml"
    metadata_path.write_text(
        "\n".join(
            [
                "channels:",
                "  groups:",
                "    TOP22_006_CH_LST_SR: {}",
                "    CH_LST_CR: {}",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(metadata_authority, "get_repo_root", lambda: tmp_path)
    other_dir = tmp_path / "elsewhere"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)

    resolved = metadata_authority.resolve_metadata_path("relative_meta.yml")

    assert resolved == metadata_path.resolve()
