"""Helpers for selecting scenario channel groups from in-memory metadata."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Mapping, MutableMapping, Sequence, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScenarioDefinition:
    """Immutable container describing a scenario definition."""

    name: str
    group_names: Tuple[str, ...]

    @property
    def groups(self) -> Tuple[str, ...]:
        """Return the ordered group names for this scenario."""

        return self.group_names


def load_scenarios(payload: Mapping[str, object]) -> Dict[str, ScenarioDefinition]:
    """Return the scenarios enumerated in the provided payload keyed by name."""

    return dict(_load_scenarios(payload))


def resolve_scenario_groups(
    name: str, scenarios: Mapping[str, ScenarioDefinition]
) -> ScenarioDefinition:
    """Return the :class:`ScenarioDefinition` matching ``name``."""

    try:
        return scenarios[name]
    except KeyError as exc:
        known = ", ".join(sorted(scenarios))
        raise KeyError(
            f"Scenario {name!r} not found in scenario definitions. "
            f"Available scenarios: {known or '<none>'}."
        ) from exc


def known_scenarios(scenarios: Mapping[str, ScenarioDefinition]) -> Tuple[str, ...]:
    """Return the scenario names enumerated in the provided definitions."""

    return tuple(scenarios.keys())


def is_scenario(
    name: str, scenarios: Mapping[str, ScenarioDefinition]
) -> bool:
    """Return ``True`` when ``name`` is defined in the scenario definitions."""

    if not name:
        return False
    return name in scenarios


def load_channels_for_scenario(
    name: str,
    *,
    metadata: Mapping[str, object],
    scenarios: Mapping[str, ScenarioDefinition],
    strict: bool = True,
    metadata_label: str = "<in-memory metadata>",
) -> Mapping[str, object]:
    """Return scenario-scoped channel metadata for ``name`` from *metadata*."""

    scenario = resolve_scenario_groups(name, scenarios)
    available_groups = _extract_groups_from_payload(metadata, metadata_label)

    if not available_groups:
        raise ValueError(
            f"No channel groups available for scenario '{name}' (metadata source: {metadata_label})."
        )

    requested_groups = list(scenario.groups)
    missing_groups = [
        group_name for group_name in requested_groups if group_name not in available_groups
    ]

    if strict and missing_groups:
        raise KeyError(
            f"Scenario {scenario.name!r} references unknown group(s): {', '.join(missing_groups)} "
            f"(metadata source: {metadata_label})."
        )

    selected_groups = {
        group_name: available_groups[group_name]
        for group_name in requested_groups
        if group_name in available_groups
    }

    if not selected_groups:
        raise KeyError(
            f"No channel groups for scenario '{scenario.name}' found in metadata ({metadata_label}). "
            f"Requested groups: {', '.join(requested_groups) or '<none>'}. "
            f"Available groups: {', '.join(sorted(available_groups)) or '<none>'}."
        )

    if missing_groups and not strict:
        logger.warning(
            "Scenario '%s': using subset of channel groups from metadata (%s). "
            "Requested: %s | Found: %s | Missing: %s",
            scenario.name,
            metadata_label,
            ", ".join(requested_groups),
            ", ".join(selected_groups),
            ", ".join(missing_groups),
        )

    scenario_groups = (
        tuple(selected_groups.keys()) if missing_groups and not strict else scenario.groups
    )
    return {
        "groups": selected_groups,
        "scenarios": [
            {
                "name": scenario.name,
                "groups": scenario_groups,
            }
        ],
    }


def _load_scenarios(
    payload: Mapping[str, object],
) -> Mapping[str, ScenarioDefinition]:
    scenarios_section = payload.get("scenarios") or {}
    if not isinstance(scenarios_section, Mapping):
        raise TypeError(
            "'scenarios' must be a mapping of scenario definitions"
        )

    scenarios: MutableMapping[str, ScenarioDefinition] = {}
    for scenario_name, definition in scenarios_section.items():
        if not isinstance(scenario_name, str):
            raise TypeError("Scenario names must be strings")
        if not isinstance(definition, Mapping):
            raise TypeError(
                f"Scenario definition for {scenario_name!r} must be a mapping"
            )
        raw_groups = definition.get("groups", [])
        if raw_groups is None:
            raw_groups = []
        if isinstance(raw_groups, str):
            raw_groups = [raw_groups]
        if not isinstance(raw_groups, (list, tuple)):
            raise TypeError(
                f"Scenario {scenario_name!r} groups must be a sequence of group names"
            )

        normalized_groups = _normalize_group_names(raw_groups)
        scenarios[scenario_name] = ScenarioDefinition(
            name=scenario_name,
            group_names=normalized_groups,
        )

    return scenarios


def _normalize_group_names(group_names: Sequence[object]) -> Tuple[str, ...]:
    seen = set()
    ordered = []
    for name in group_names:
        if not isinstance(name, str):
            raise TypeError("Scenario group names must be strings")
        stripped = name.strip()
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        ordered.append(stripped)
    return tuple(ordered)


def _extract_groups_from_payload(
    payload: Mapping[str, object], source: str
) -> Dict[str, Mapping[str, object]]:
    channels = payload.get("channels") or {}
    if not isinstance(channels, Mapping):
        raise TypeError(f"'channels' in {source} must be a mapping with 'groups'")
    available = channels.get("groups") or {}
    if not isinstance(available, Mapping):
        raise TypeError(
            f"'channels.groups' in {source} must be a mapping of group definitions"
        )
    groups: Dict[str, Mapping[str, object]] = {}
    for group_name, metadata in available.items():
        if not isinstance(group_name, str):
            raise TypeError(f"Channel group names in {source} must be strings")
        if not isinstance(metadata, Mapping):
            raise TypeError(
                f"Channel group {group_name!r} in {source} must be a mapping"
            )
        groups[group_name] = metadata
    return groups


__all__ = [
    "ScenarioDefinition",
    "load_scenarios",
    "resolve_scenario_groups",
    "known_scenarios",
    "is_scenario",
    "load_channels_for_scenario",
]
