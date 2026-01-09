"""Centralized metadata authority for Run 2 workflows."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Optional, Sequence, Tuple

import yaml

from analysis.topeft_run2 import metadata_loader


DEFAULT_METADATA_RELATIVE = Path("analysis/metadata/metadata.yml")
SCENARIOS_RELATIVE = Path("analysis/metadata/run2_scenarios.yaml")


@dataclass(frozen=True)
class ScenarioDefinition:
    """Immutable container describing a scenario definition."""

    name: str
    groups: Tuple[str, ...]
    description: Optional[str] = None


@dataclass(frozen=True)
class MetadataBundle:
    """Container describing a resolved metadata payload and scenario selection."""

    metadata_path: Path
    metadata: MutableMapping[str, Any]
    channels: Mapping[str, object]
    scenario: ScenarioDefinition
    scenarios: Mapping[str, ScenarioDefinition]
    provenance: Tuple[str, ...]


def get_repo_root() -> Path:
    """Return the repository root for the topeft checkout."""

    return Path(__file__).resolve().parents[2]


def resolve_metadata_path(path: str | Path | None) -> Path:
    """Return the absolute metadata path, anchored at the repo root."""

    if path is None:
        candidate = DEFAULT_METADATA_RELATIVE
    else:
        candidate = Path(path).expanduser()

    if not candidate.is_absolute():
        # Relative metadata paths resolve relative to the repo root.
        candidate = get_repo_root() / candidate

    try:
        return candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"Metadata file '{candidate}' could not be found."
        ) from exc


def _normalize_optional_string(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    candidate = str(value).strip()
    return candidate or None


def select_metadata_source(
    metadata_cli: Optional[str],
    metadata_options: Optional[str],
) -> Tuple[Optional[str], str]:
    """Return the preferred metadata path and its source label."""

    metadata_cli = _normalize_optional_string(metadata_cli)
    metadata_options = _normalize_optional_string(metadata_options)

    if metadata_cli:
        return metadata_cli, "cli"
    if metadata_options:
        return metadata_options, "options"
    return None, "default"


def golden_json_for_year(metadata: Mapping[str, object], year: str) -> str:
    """Return the golden JSON path for ``year`` from *metadata*."""

    golden_jsons = metadata.get("golden_jsons")
    if not isinstance(golden_jsons, Mapping):
        raise KeyError("metadata['golden_jsons'] is missing or not a mapping")
    try:
        entry = golden_jsons[str(year)]
    except KeyError as exc:
        raise KeyError(
            f"No golden JSON configured for year '{year}' in metadata."
        ) from exc
    candidate = Path(str(entry)).expanduser()
    if candidate.is_absolute():
        return str(candidate)
    try:
        from topcoffea.modules.paths import topcoffea_path
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise ImportError(
            "topcoffea.modules.paths is required to resolve golden JSON paths."
        ) from exc
    return topcoffea_path(str(candidate))


def load_metadata_bundle(
    metadata_path: str | Path | None,
    scenario: str | None,
    *,
    strict: bool = True,
    required_sections: Sequence[str] | None = ("channels",),
    metadata_source: Optional[str] = None,
) -> MetadataBundle:
    """Return the resolved metadata and scenario configuration."""

    scenario_name = _normalize_optional_string(scenario)
    if not scenario_name:
        raise ValueError("scenario must be provided to load metadata")

    scenarios = load_scenarios()
    try:
        scenario_def = scenarios[scenario_name]
    except KeyError as exc:
        known = ", ".join(sorted(scenarios)) or "<none>"
        raise ValueError(
            f"Unknown scenario '{scenario_name}'. Known scenarios: {known}"
        ) from exc

    resolved_metadata_path = resolve_metadata_path(metadata_path)
    bundle = metadata_loader.load_metadata(
        resolved_metadata_path,
        required_sections=required_sections,
    )
    metadata = bundle.payload

    channels = _select_channels_for_scenario(
        metadata,
        scenario_def,
        strict=strict,
        source_label=str(resolved_metadata_path),
    )

    source_label = metadata_source or ("default" if metadata_path is None else "explicit")
    provenance = (
        f"metadata_path={resolved_metadata_path}",
        f"metadata_source={source_label}",
        f"scenario={scenario_def.name}",
    )
    return MetadataBundle(
        metadata_path=resolved_metadata_path,
        metadata=metadata,
        channels=channels,
        scenario=scenario_def,
        scenarios=scenarios,
        provenance=provenance,
    )


def load_scenarios() -> Mapping[str, ScenarioDefinition]:
    """Return the scenario definitions from run2_scenarios.yaml."""

    return dict(_load_scenarios())


@lru_cache(maxsize=1)
def _load_scenarios() -> Mapping[str, ScenarioDefinition]:
    scenarios_path = get_repo_root() / SCENARIOS_RELATIVE
    payload = _read_yaml_mapping(scenarios_path)
    scenarios_section = payload.get("scenarios") or {}
    if not isinstance(scenarios_section, Mapping):
        raise TypeError(
            f"'scenarios' in {scenarios_path} must be a mapping of scenario definitions"
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
            groups=normalized_groups,
            description=definition.get("description"),
        )

    if not scenarios:
        raise ValueError(
            f"No scenarios are defined in {scenarios_path}."
        )

    return scenarios


def _read_yaml_mapping(path: Path) -> MutableMapping[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, MutableMapping):
        raise TypeError(f"{path} must contain a YAML mapping at the top level")
    return payload


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
) -> Mapping[str, Mapping[str, object]]:
    channels = payload.get("channels") or {}
    if not isinstance(channels, Mapping):
        raise TypeError(f"'channels' in {source} must be a mapping with 'groups'")
    available = channels.get("groups") or {}
    if not isinstance(available, Mapping):
        raise TypeError(
            f"'channels.groups' in {source} must be a mapping of group definitions"
        )
    groups: MutableMapping[str, Mapping[str, object]] = {}
    for group_name, metadata in available.items():
        if not isinstance(group_name, str):
            raise TypeError(f"Channel group names in {source} must be strings")
        if not isinstance(metadata, Mapping):
            raise TypeError(
                f"Channel group {group_name!r} in {source} must be a mapping"
            )
        groups[group_name] = metadata
    return groups


def _select_channels_for_scenario(
    metadata: Mapping[str, object],
    scenario: ScenarioDefinition,
    *,
    strict: bool,
    source_label: str,
) -> Mapping[str, object]:
    channels_payload = metadata.get("channels") or {}
    if not isinstance(channels_payload, Mapping):
        raise TypeError(f"'channels' in {source_label} must be a mapping with 'groups'")
    available_groups = _extract_groups_from_payload(metadata, source_label)
    if not available_groups:
        raise ValueError(
            f"No channel groups available for scenario '{scenario.name}' "
            f"(metadata source: {source_label})."
        )

    requested_groups = list(scenario.groups)
    missing_groups = [
        group_name for group_name in requested_groups if group_name not in available_groups
    ]

    if strict and missing_groups:
        raise KeyError(
            f"Scenario {scenario.name!r} references unknown group(s): {', '.join(missing_groups)} "
            f"(metadata source: {source_label})."
        )

    selected_groups = {
        group_name: available_groups[group_name]
        for group_name in requested_groups
        if group_name in available_groups
    }

    if not selected_groups:
        raise KeyError(
            f"No channel groups for scenario '{scenario.name}' found in metadata ({source_label}). "
            f"Requested groups: {', '.join(requested_groups) or '<none>'}. "
            f"Available groups: {', '.join(sorted(available_groups)) or '<none>'}."
        )

    if missing_groups and not strict:
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(
            "Scenario '%s': using subset of channel groups from metadata (%s). "
            "Requested: %s | Found: %s | Missing: %s",
            scenario.name,
            source_label,
            ", ".join(requested_groups),
            ", ".join(selected_groups),
            ", ".join(missing_groups),
        )

    scenario_groups = (
        tuple(selected_groups.keys()) if missing_groups and not strict else scenario.groups
    )
    channels_out = dict(channels_payload)
    channels_out["groups"] = selected_groups
    channels_out["scenarios"] = [
        {
            "name": scenario.name,
            "groups": scenario_groups,
        }
    ]
    return channels_out


__all__ = [
    "DEFAULT_METADATA_RELATIVE",
    "SCENARIOS_RELATIVE",
    "MetadataBundle",
    "ScenarioDefinition",
    "get_repo_root",
    "resolve_metadata_path",
    "select_metadata_source",
    "golden_json_for_year",
    "load_metadata_bundle",
    "load_scenarios",
]
