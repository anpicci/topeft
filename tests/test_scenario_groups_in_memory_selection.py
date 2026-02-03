import logging

import pytest

from topeft.modules import scenario_groups


def _scenarios():
    return {
        "S1": scenario_groups.ScenarioDefinition(name="S1", groups=("G1", "G2")),
        "S2": scenario_groups.ScenarioDefinition(name="S2", groups=("G1", "MISSING")),
    }


def _channels_payload():
    return {
        "schema_version": 3,
        "group_aliases": {"SR": "G1"},
        "groups": {
            "G1": {"categories": []},
            "G2": {"categories": []},
        },
    }


def test_select_channels_preserves_extra_keys() -> None:
    selected = scenario_groups.select_channels_for_scenario(
        "S1",
        channels_payload=_channels_payload(),
        scenarios=_scenarios(),
        strict=True,
    )

    assert selected["schema_version"] == 3
    assert selected["group_aliases"] == {"SR": "G1"}
    assert set(selected["groups"].keys()) == {"G1", "G2"}
    assert selected["scenarios"] == [{"name": "S1", "groups": ("G1", "G2")}]


def test_select_channels_strict_missing_raises() -> None:
    with pytest.raises(KeyError, match="MISSING"):
        scenario_groups.select_channels_for_scenario(
            "S2",
            channels_payload=_channels_payload(),
            scenarios=_scenarios(),
            strict=True,
        )


def test_select_channels_non_strict_logs_warning(caplog) -> None:
    caplog.set_level(logging.WARNING)

    selected = scenario_groups.select_channels_for_scenario(
        "S2",
        channels_payload=_channels_payload(),
        scenarios=_scenarios(),
        strict=False,
    )

    assert set(selected["groups"].keys()) == {"G1"}
    assert any("Missing" in record.message or "missing" in record.message for record in caplog.records)
