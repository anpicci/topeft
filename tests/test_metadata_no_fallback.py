from pathlib import Path

from analysis.topeft_run2 import metadata_authority
from analysis.topeft_run2 import scenario_registry
from topeft.modules import scenario_groups


def _write_minimal_metadata(tmp_path: Path) -> Path:
    metadata_file = tmp_path / "metadata.yml"
    metadata_file.write_text(
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
    return metadata_file


def test_no_fallback_when_metadata_is_explicit(tmp_path, monkeypatch) -> None:
    metadata_path = _write_minimal_metadata(tmp_path)

    def fail_registry(*args, **kwargs):
        raise AssertionError("Scenario registry should not be consulted")

    def fail_scenario_groups(*args, **kwargs):
        raise AssertionError("Scenario groups should not be consulted")

    monkeypatch.setattr(scenario_registry, "resolve_scenario_choice", fail_registry)
    monkeypatch.setattr(scenario_groups, "load_channels_for_scenario", fail_scenario_groups)

    bundle = metadata_authority.load_metadata_bundle(
        str(metadata_path),
        "TOP_22_006",
        strict=True,
        required_sections=("channels",),
        metadata_source="explicit",
    )

    assert bundle.metadata_path == metadata_path.resolve()


def test_single_metadata_file_load(tmp_path, monkeypatch) -> None:
    metadata_path = _write_minimal_metadata(tmp_path)
    open_calls: list[Path] = []
    original_open = Path.open

    def spy_open(self: Path, *args, **kwargs):
        if self.suffix in {".yml", ".yaml"}:
            open_calls.append(self)
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", spy_open)
    metadata_authority._load_scenarios.cache_clear()

    metadata_authority.load_metadata_bundle(
        str(metadata_path),
        "TOP_22_006",
        strict=True,
        required_sections=("channels",),
        metadata_source="explicit",
    )

    scenarios_path = metadata_authority.get_repo_root() / metadata_authority.SCENARIOS_RELATIVE
    metadata_path_resolved = metadata_path.resolve()
    metadata_opens = [path for path in open_calls if path == metadata_path_resolved]
    scenario_opens = [path for path in open_calls if path == scenarios_path]
    other_opens = [
        path
        for path in open_calls
        if path not in {metadata_path_resolved, scenarios_path}
    ]

    assert len(metadata_opens) == 1
    assert len(scenario_opens) == 1
    assert not other_opens
