"""Helpers for loading scenario definitions and channel groups from metadata."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Mapping, MutableMapping, Sequence, Tuple, Union

import yaml

from topeft.modules.paths import topeft_path

logger = logging.getLogger(__name__)

SCENARIO_DEFINITIONS_PATH = Path(
    topeft_path("../analysis/metadata/run2_scenarios.yaml")
)
GROUP_METADATA_PATHS = (
    # Canonical metadata bundle with the full systematics catalog and channel groups.
    Path(topeft_path("../analysis/metadata/metadata.yml")),
)


@dataclass(frozen=True)
class ScenarioDefinition:
    """Immutable container describing a scenario definition."""

    name: str
    group_names: Tuple[str, ...]

    @property
    def groups(self) -> Tuple[str, ...]:
        """Return the ordered group names for this scenario."""

        return self.group_names


def load_scenarios() -> Dict[str, ScenarioDefinition]:
    """Return the scenarios enumerated in the scenario definition YAML keyed by name."""

    return dict(_load_scenarios())


def resolve_scenario_groups(name: str) -> ScenarioDefinition:
    """Return the :class:`ScenarioDefinition` matching ``name``."""

    scenarios = load_scenarios()
    try:
        return scenarios[name]
    except KeyError as exc:
        known = ", ".join(sorted(scenarios))
        raise KeyError(
            f"Scenario {name!r} not found in analysis/metadata/run2_scenarios.yaml. "
            f"Available scenarios: {known or '<none>'}."
        ) from exc


def known_scenarios() -> Tuple[str, ...]:
    """Return the scenario names enumerated in the scenario definition YAML."""

    return tuple(_load_scenarios().keys())


def is_scenario(name: str) -> bool:
    """Return ``True`` when ``name`` is defined in the scenario definition YAML."""

    if not name:
        return False
    return name in _load_scenarios()


def load_channels_for_scenario(
    name: str,
    *,
    metadata: Mapping[str, object] | None = None,
    metadata_path: Union[str, Path, None] = None,
    strict: bool = True,
) -> Mapping[str, object]:
    """Return metadata suitable for :class:`ChannelMetadataHelper`.

    The returned mapping follows the ``metadata['channels']`` structure and
    contains only the groups requested by ``name``.  Scenario information is
    included so callers can still rely on ``ChannelMetadataHelper`` helpers that
    need the scenario → group map. Callers should pass either the already-loaded
    metadata mapping or a metadata path; when neither is provided the canonical
    canonical bundle is used as a fallback. This ensures that custom runs which
    inject metadata remain consistent—only users who omit both inputs pay the
    price of the legacy fallback to the bundled metadata.
    """

    scenario = resolve_scenario_groups(name)
    metadata_supplied = metadata is not None or metadata_path is not None

    if metadata is not None:
        available_groups = _extract_groups_from_payload(
            metadata, "<in-memory metadata>"
        )
        source_label = metadata_path or "provided metadata payload"
    elif metadata_path is not None:
        candidate = Path(metadata_path).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        resolved = candidate.resolve()
        payload = _read_yaml_mapping(resolved)
        available_groups = _extract_groups_from_payload(payload, str(resolved))
        source_label = str(resolved)
    else:
        logger.warning(
            "No metadata supplied when resolving scenario '%s'. Falling back to canonical %s; "
            "custom runs may diverge if metadata differs.",
            name,
            ", ".join(str(path) for path in GROUP_METADATA_PATHS),
        )
        available_groups = _load_group_metadata()
        source_label = "canonical metadata"

    if not available_groups:
        raise ValueError(
            f"No channel groups available for scenario '{name}' (metadata source: {source_label})."
        )

    requested_groups = list(scenario.groups)

    if strict:
        missing_groups = [name for name in requested_groups if name not in available_groups]
        if missing_groups:
            raise KeyError(
                f"Scenario {scenario.name!r} references unknown group(s): {', '.join(missing_groups)} "
                f"(metadata source: {source_label})."
            )
        selected_groups: Dict[str, Mapping[str, object]] = {
            group_name: available_groups[group_name]
            for group_name in requested_groups
        }
    else:
        selected_groups = {}
        missing_groups = []
        for group_name in requested_groups:
            metadata_entry = available_groups.get(group_name)
            if metadata_entry is None:
                missing_groups.append(group_name)
                continue
            if group_name not in selected_groups:
                selected_groups[group_name] = metadata_entry

    if not selected_groups:
        raise KeyError(
            f"No channel groups for scenario '{scenario.name}' found in metadata ({source_label}). "
            f"Requested groups: {', '.join(requested_groups) or '<none>'}. "
            f"Available groups: {', '.join(sorted(available_groups)) or '<none>'}."
        )

    if not strict and missing_groups and metadata_supplied:
        logger.warning(
            "Scenario '%s': using subset of channel groups from metadata (%s). "
            "Requested: %s | Found: %s | Missing: %s",
            scenario.name,
            source_label,
            ", ".join(requested_groups),
            ", ".join(selected_groups),
            ", ".join(missing_groups),
        )

    return {
        "groups": selected_groups,
        "scenarios": [
            {
                "name": scenario.name,
                "groups": scenario.groups,
            }
        ],
    }


@lru_cache(maxsize=1)
def _load_scenarios() -> Mapping[str, ScenarioDefinition]:
    payload = _read_yaml_mapping(SCENARIO_DEFINITIONS_PATH)
    scenarios_section = payload.get("scenarios") or {}
    if not isinstance(scenarios_section, Mapping):
        raise TypeError(
            f"'scenarios' in {SCENARIO_DEFINITIONS_PATH} must be a mapping of scenario definitions"
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


@lru_cache(maxsize=1)
def _load_group_metadata() -> Dict[str, Mapping[str, object]]:
    """Return the canonical channel-group metadata keyed by group name."""

    groups: Dict[str, Mapping[str, object]] = {}
    for metadata_path in GROUP_METADATA_PATHS:
        payload = _read_yaml_mapping(metadata_path)
        for group_name, metadata in _extract_groups_from_payload(
            payload, str(metadata_path)
        ).items():
            groups.setdefault(group_name, metadata)
    return groups


def _read_yaml_mapping(path: Path) -> Mapping[str, object]:
    """Return ``yaml.safe_load`` output ensuring it is a mapping."""

    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, Mapping):
        raise TypeError(f"{path} must contain a YAML mapping at the top level")
    return payload


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
