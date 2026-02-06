import pytest

from analysis.topeft_run2 import metadata_authority


def test_unknown_scenario_raises(tmp_path) -> None:
    metadata_path = tmp_path / "metadata.yml"
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

    with pytest.raises(ValueError, match="Unknown scenario 'NOT_REAL'"):
        metadata_authority.load_metadata_bundle(
            str(metadata_path),
            "NOT_REAL",
            strict=True,
            required_sections=("channels",),
            metadata_source="explicit",
        )
