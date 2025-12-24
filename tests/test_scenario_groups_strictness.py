from pathlib import Path

import pytest

from topeft.modules import scenario_groups


def _fixture_path(name: str) -> Path:
    return Path(__file__).resolve().parent / "data" / name


def test_strict_missing_group_raises(monkeypatch) -> None:
    def fail_fallback():
        raise AssertionError("Canonical metadata fallback should not be used")

    monkeypatch.setattr(scenario_groups, "_load_group_metadata", fail_fallback)

    metadata_path = _fixture_path("metadata_minimal.yml")
    with pytest.raises(KeyError, match="unknown group") as excinfo:
        scenario_groups.load_channels_for_scenario(
            "TOP_22_006",
            metadata_path=metadata_path,
            strict=True,
        )

    assert "CH_LST_CR" in str(excinfo.value)


def test_allow_partial_requires_flag(monkeypatch) -> None:
    def fail_fallback():
        raise AssertionError("Canonical metadata fallback should not be used")

    monkeypatch.setattr(scenario_groups, "_load_group_metadata", fail_fallback)

    metadata_path = _fixture_path("metadata_minimal.yml")
    result = scenario_groups.load_channels_for_scenario(
        "TOP_22_006",
        metadata_path=metadata_path,
        strict=False,
    )

    groups = result.get("groups") or {}
    assert "TOP22_006_CH_LST_SR" in groups
    assert "CH_LST_CR" not in groups


def test_missing_group_payload_does_not_fallback(monkeypatch, tmp_path) -> None:
    def fail_fallback():
        raise AssertionError("Canonical metadata fallback should not be used")

    monkeypatch.setattr(scenario_groups, "_load_group_metadata", fail_fallback)

    metadata_path = tmp_path / "missing_groups.yml"
    metadata_path.write_text("channels: {}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="No channel groups available"):
        scenario_groups.load_channels_for_scenario(
            "TOP_22_006",
            metadata_path=metadata_path,
            strict=True,
        )
