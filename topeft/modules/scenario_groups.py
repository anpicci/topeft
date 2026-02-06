"""In-memory helpers for selecting scenario channel groups.

This module is intentionally pure and side-effect free. Callers must provide
scenario definitions and channel payloads explicitly; no file I/O or environment
variables are consulted here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Mapping, MutableMapping, Sequence, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScenarioDefinition:
    """Immutable container describing a scenario definition."""

    name: str
    groups: Tuple[str, ...]
    description: str | None = None


def is_scenario(name: str, *, scenarios: Mapping[str, ScenarioDefinition]) -> bool:
    """Return ``True`` when ``name`` is defined in ``scenarios``."""

    if not name:
        return False
    _require_scenarios(scenarios)
    return name in scenarios


def known_scenarios(*, scenarios: Mapping[str, ScenarioDefinition]) -> Tuple[str, ...]:
    """Return the scenario names enumerated in ``scenarios``."""

    _require_scenarios(scenarios)
    return tuple(scenarios.keys())


def resolve_scenario_groups(
    name: str,
    *,
    scenarios: Mapping[str, ScenarioDefinition],
) -> ScenarioDefinition:
    """Return the :class:`ScenarioDefinition` matching ``name``."""

    _require_scenarios(scenarios)
    try:
        return scenarios[name]
    except KeyError as exc:
        known = ", ".join(sorted(scenarios)) or "<none>"
        raise KeyError(
            f"Scenario {name!r} not found in scenario definitions. "
            f"Available scenarios: {known}."
        ) from exc


def select_channels_for_scenario(
    name: str,
    *,
    channels_payload: Mapping[str, object],
    scenarios: Mapping[str, ScenarioDefinition],
    strict: bool = True,
) -> Mapping[str, object]:
    """Return scenario-scoped channel metadata for ``name``.

    The returned mapping mirrors the input ``channels_payload`` but replaces the
    ``groups`` field with the selected subset and injects a single-entry
    ``scenarios`` list describing the selection.
    """

    scenario = resolve_scenario_groups(name, scenarios=scenarios)
    available_groups = _extract_groups_from_payload(channels_payload, "channels_payload")
    if not available_groups:
        raise ValueError(
            f"No channel groups available for scenario '{scenario.name}' "
            "(metadata source: channels_payload)."
        )

    requested_groups = list(scenario.groups)
    missing_groups = [group_name for group_name in requested_groups if group_name not in available_groups]

    if strict and missing_groups:
        raise KeyError(
            f"Scenario {scenario.name!r} references unknown group(s): {', '.join(missing_groups)} "
            "(metadata source: channels_payload)."
        )

    selected_groups = {
        group_name: available_groups[group_name]
        for group_name in requested_groups
        if group_name in available_groups
    }

    if not selected_groups:
        raise KeyError(
            f"No channel groups for scenario '{scenario.name}' found in metadata (channels_payload). "
            f"Requested groups: {', '.join(requested_groups) or '<none>'}. "
            f"Available groups: {', '.join(sorted(available_groups)) or '<none>'}."
        )

    if missing_groups and not strict:
        logger.warning(
            "Scenario '%s': using subset of channel groups from metadata (channels_payload). "
            "Requested: %s | Found: %s | Missing: %s",
            scenario.name,
            ", ".join(requested_groups) or "<none>",
            ", ".join(selected_groups) or "<none>",
            ", ".join(missing_groups) or "<none>",
        )

    scenario_groups = tuple(selected_groups.keys()) if (missing_groups and not strict) else scenario.groups

    channels_out: MutableMapping[str, object] = dict(channels_payload)
    channels_out["groups"] = selected_groups
    channels_out["scenarios"] = [
        {
            "name": scenario.name,
            "groups": scenario_groups,
        }
    ]
    return channels_out


def _require_scenarios(scenarios: Mapping[str, ScenarioDefinition]) -> None:
    if scenarios is None or not isinstance(scenarios, Mapping):
        raise TypeError("scenarios must be a mapping of ScenarioDefinition objects")


def _extract_groups_from_payload(
    payload: Mapping[str, object],
    source: str,
) -> Mapping[str, Mapping[str, object]]:
    channels = payload.get("groups") if isinstance(payload, Mapping) else None
    if not isinstance(channels, Mapping):
        raise TypeError(f"'groups' in {source} must be a mapping of group definitions")

    groups: MutableMapping[str, Mapping[str, object]] = {}
    for group_name, metadata in channels.items():
        if not isinstance(group_name, str):
            raise TypeError(f"Channel group names in {source} must be strings")
        if not isinstance(metadata, Mapping):
            raise TypeError(f"Channel group {group_name!r} in {source} must be a mapping")
        groups[group_name] = metadata
    return groups


__all__ = [
    "ScenarioDefinition",
    "is_scenario",
    "known_scenarios",
    "resolve_scenario_groups",
    "select_channels_for_scenario",
]
