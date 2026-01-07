from pathlib import Path

import pytest

from analysis.topeft_run2 import metadata_authority


def _fixture_path(name: str) -> Path:
    return Path(__file__).resolve().parent / "data" / name


def test_strict_missing_group_raises(monkeypatch) -> None:
    metadata_path = _fixture_path("metadata_minimal.yml")
    with pytest.raises(KeyError, match="unknown group") as excinfo:
        metadata_authority.load_metadata_bundle(
            str(metadata_path),
            "TOP_22_006",
            strict=True,
            required_sections=("channels",),
            metadata_source="explicit",
        )

    assert "CH_LST_CR" in str(excinfo.value)


def test_allow_partial_requires_flag(monkeypatch) -> None:
    metadata_path = _fixture_path("metadata_minimal.yml")
    result = metadata_authority.load_metadata_bundle(
        str(metadata_path),
        "TOP_22_006",
        strict=False,
        required_sections=("channels",),
        metadata_source="explicit",
    )

    groups = result.channels.get("groups") or {}
    assert "TOP22_006_CH_LST_SR" in groups
    assert "CH_LST_CR" not in groups


def test_missing_group_payload_does_not_fallback(monkeypatch, tmp_path) -> None:
    metadata_path = tmp_path / "missing_groups.yml"
    metadata_path.write_text("channels: {}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="No channel groups available"):
        metadata_authority.load_metadata_bundle(
            str(metadata_path),
            "TOP_22_006",
            strict=True,
            required_sections=("channels",),
            metadata_source="explicit",
        )
