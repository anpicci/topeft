from pathlib import Path

from analysis.topeft_run2 import metadata_authority


def _write_metadata_with_extra_channels(tmp_path: Path) -> Path:
    metadata_file = tmp_path / "metadata.yml"
    metadata_file.write_text(
        "\n".join(
            [
                "channels:",
                "  schema_version: 3",
                "  group_aliases:",
                "    SR: TOP22_006_CH_LST_SR",
                "  groups:",
                "    TOP22_006_CH_LST_SR: {}",
                "    CH_LST_CR: {}",
            ]
        ),
        encoding="utf-8",
    )
    return metadata_file


def test_preserve_extra_channels_keys(tmp_path) -> None:
    metadata_path = _write_metadata_with_extra_channels(tmp_path)

    bundle = metadata_authority.load_metadata_bundle(
        str(metadata_path),
        "TOP_22_006",
        strict=True,
        required_sections=("channels",),
        metadata_source="explicit",
    )

    assert set(bundle.channels["groups"]) == {"TOP22_006_CH_LST_SR", "CH_LST_CR"}
    assert tuple(bundle.channels["scenarios"][0]["groups"]) == (
        "TOP22_006_CH_LST_SR",
        "CH_LST_CR",
    )
    assert bundle.channels["schema_version"] == 3
    assert bundle.channels["group_aliases"] == {"SR": "TOP22_006_CH_LST_SR"}
