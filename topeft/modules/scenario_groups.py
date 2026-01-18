"""Helpers for selecting scenario channel groups from metadata.

This module serves two closely-related purposes:

1) Define and expose *scenario → group list* mappings ("scenario definitions").
2) Given a scenario name and a channels payload, return a channels mapping that
   contains *only* the channel groups required by that scenario.

Rationale (matching the other revised scripts):
- Scenario *definitions* are treated as canonical (shipped/bundled with the code),
  so users can reliably ask for a known scenario name.
- Channel *groups* may come from a custom metadata payload (e.g. a user-provided
  YAML), while still selecting groups using the canonical scenario definition.
- When callers provide neither an in-memory metadata mapping nor a metadata path,
  we fall back to the bundled/canonical metadata on disk (with a warning).

Environment overrides:
- TOPEFT_SCENARIO_METADATA_PATHS: colon-separated list of YAML/JSON files to use
  as canonical metadata sources (first existing file wins, later ones merge).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, MutableMapping, Optional, Sequence, Tuple, Union

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------


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
    name: str, scenarios: Optional[Mapping[str, ScenarioDefinition]] = None
) -> ScenarioDefinition:
    """Return the :class:`ScenarioDefinition` matching ``name``."""
    scenarios = _ensure_scenarios(scenarios)
    try:
        return scenarios[name]
    except KeyError as exc:
        known = ", ".join(sorted(scenarios))
        raise KeyError(
            f"Scenario {name!r} not found in scenario definitions. "
            f"Available scenarios: {known or '<none>'}."
        ) from exc


def known_scenarios(scenarios: Optional[Mapping[str, ScenarioDefinition]] = None) -> Tuple[str, ...]:
    """Return the scenario names enumerated in the provided (or canonical) definitions."""
    scenarios = _ensure_scenarios(scenarios)
    return tuple(scenarios.keys())


def is_scenario(name: str, scenarios: Optional[Mapping[str, ScenarioDefinition]] = None) -> bool:
    """Return ``True`` when ``name`` is defined in the provided (or canonical) definitions."""
    if not name:
        return False
    scenarios = _ensure_scenarios(scenarios)
    return name in scenarios


# ---------------------------------------------------------------------------
# Channel group selection
# ---------------------------------------------------------------------------


def load_channels_for_scenario(
    name: str,
    *,
    metadata: Mapping[str, object] | None = None,
    metadata_path: Union[str, Path, None] = None,
    scenarios: Mapping[str, ScenarioDefinition] | None = None,
    strict: bool = True,
) -> Mapping[str, object]:
    """Return scenario-scoped channel metadata for ``name``.

    The returned mapping follows the ``metadata['channels']`` structure and
    contains only the groups requested by ``name``. Scenario information is
    included so callers can still rely on helpers that need the scenario → group
    map.

    Callers should pass either the already-loaded metadata mapping or a metadata
    path. When neither is provided, the canonical/bundled metadata is used as a
    fallback (with a warning).

    Parameters
    ----------
    name:
        Scenario name, resolved against scenario definitions.
    metadata:
        In-memory metadata payload (already parsed from YAML/JSON).
    metadata_path:
        Path to a YAML/JSON file containing metadata.
    scenarios:
        Optional explicit scenario definitions mapping. If omitted, canonical
        scenario definitions are used.
    strict:
        If True, missing groups referenced by the scenario raise immediately.
        If False, missing groups are tolerated and only the intersection is used
        (with a warning when metadata was explicitly supplied).
    """
    scenario = resolve_scenario_groups(name, scenarios=scenarios)
    metadata_supplied = metadata is not None or metadata_path is not None

    # 1) Decide where channel groups come from.
    if metadata is not None:
        available_groups = _extract_groups_from_payload(metadata, "<in-memory metadata>")
        source_label = str(metadata_path) if metadata_path is not None else "provided metadata payload"
    elif metadata_path is not None:
        resolved = _resolve_metadata_path(metadata_path)
        payload = _read_mapping(resolved)
        available_groups = _extract_groups_from_payload(payload, str(resolved))
        source_label = str(resolved)
    else:
        logger.warning(
            "No metadata supplied when resolving scenario '%s'. Falling back to canonical metadata; "
            "custom runs may diverge if metadata differs.",
            name,
        )
        payload = _load_canonical_payload()
        available_groups = _extract_groups_from_payload(payload, "canonical metadata")
        source_label = "canonical metadata"

    if not available_groups:
        raise ValueError(
            f"No channel groups available for scenario '{scenario.name}' (metadata source: {source_label})."
        )

    requested_groups = list(scenario.groups)

    # 2) Select and validate group membership.
    if strict:
        missing_groups = [g for g in requested_groups if g not in available_groups]
        if missing_groups:
            raise KeyError(
                f"Scenario {scenario.name!r} references unknown group(s): {', '.join(missing_groups)} "
                f"(metadata source: {source_label})."
            )
        selected_groups: Dict[str, Mapping[str, object]] = {
            group_name: available_groups[group_name] for group_name in requested_groups
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
            ", ".join(requested_groups) or "<none>",
            ", ".join(selected_groups) or "<none>",
            ", ".join(missing_groups) or "<none>",
        )

    scenario_groups = tuple(selected_groups.keys()) if (missing_groups and not strict) else scenario.groups

    return {
        "groups": selected_groups,
        "scenarios": [
            {
                "name": scenario.name,
                "groups": scenario_groups,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Canonical metadata discovery / loading (for scenario definitions and fallback)
# ---------------------------------------------------------------------------


def _ensure_scenarios(
    scenarios: Optional[Mapping[str, ScenarioDefinition]],
) -> Mapping[str, ScenarioDefinition]:
    if scenarios is not None:
        return scenarios
    return _canonical_scenarios()


_CANONICAL_PAYLOAD_CACHE: Optional[Mapping[str, object]] = None
_CANONICAL_SCENARIOS_CACHE: Optional[Mapping[str, ScenarioDefinition]] = None


def _canonical_scenarios() -> Mapping[str, ScenarioDefinition]:
    global _CANONICAL_SCENARIOS_CACHE
    if _CANONICAL_SCENARIOS_CACHE is not None:
        return _CANONICAL_SCENARIOS_CACHE

    payload = _load_canonical_payload()
    scenarios = load_scenarios(payload)
    _CANONICAL_SCENARIOS_CACHE = scenarios
    return scenarios


def _load_canonical_payload() -> Mapping[str, object]:
    global _CANONICAL_PAYLOAD_CACHE
    if _CANONICAL_PAYLOAD_CACHE is not None:
        return _CANONICAL_PAYLOAD_CACHE

    paths = _canonical_metadata_paths()
    if not paths:
        raise RuntimeError(
            "No canonical scenario metadata paths could be resolved. "
            "Set TOPEFT_SCENARIO_METADATA_PATHS to point at a YAML/JSON metadata file."
        )

    merged: Dict[str, object] = {}
    loaded_any = False
    for path in paths:
        if not path.exists():
            continue
        payload = _read_mapping(path)
        merged = _deep_merge(merged, dict(payload))
        loaded_any = True

    if not loaded_any:
        raise RuntimeError(
            "Canonical scenario metadata paths were resolved, but none exist on disk. "
            "Set TOPEFT_SCENARIO_METADATA_PATHS to point at a YAML/JSON metadata file."
        )

    _CANONICAL_PAYLOAD_CACHE = merged
    return merged


def _canonical_metadata_paths() -> Tuple[Path, ...]:
    """Return the list of candidate canonical metadata files to load/merge."""
    env = os.environ.get("TOPEFT_SCENARIO_METADATA_PATHS", "").strip()
    if env:
        parts = [p for p in env.split(":") if p.strip()]
        resolved = tuple(_resolve_metadata_path(p) for p in parts)
        return resolved

    here = Path(__file__).resolve()
    candidates = [
        # Common "data/" layout next to modules
        here.parent / "data" / "scenario_groups.yaml",
        here.parent / "data" / "scenario_groups.yml",
        here.parent / "data" / "scenarios.yaml",
        here.parent / "data" / "scenarios.yml",
        here.parent / "data" / "metadata.yaml",
        here.parent / "data" / "metadata.yml",
        # One level up (repo-specific packaging)
        here.parent.parent / "data" / "scenario_groups.yaml",
        here.parent.parent / "data" / "scenario_groups.yml",
        here.parent.parent / "data" / "scenarios.yaml",
        here.parent.parent / "data" / "scenarios.yml",
        here.parent.parent / "data" / "metadata.yaml",
        here.parent.parent / "data" / "metadata.yml",
    ]
    # Keep ordering (first existing file wins; later ones merge)
    return tuple(Path(p) for p in candidates)


def _resolve_metadata_path(path: Union[str, Path]) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate.resolve()


def _read_mapping(path: Path) -> Mapping[str, object]:
    """Read YAML/JSON file into a mapping."""
    if not path.exists():
        raise FileNotFoundError(str(path))
    text = path.read_text(encoding="utf-8")

    # Prefer YAML if available (metadata files are typically YAML).
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                f"PyYAML is required to read '{path}'. Install pyyaml or provide JSON."
            ) from exc
        payload = yaml.safe_load(text) or {}
    else:
        payload = json.loads(text) if text.strip() else {}

    if not isinstance(payload, Mapping):
        raise TypeError(f"Metadata in {path} must be a mapping at the top level")
    return payload


def _deep_merge(base: Dict[str, object], incoming: Dict[str, object]) -> Dict[str, object]:
    """Recursively merge mapping-like values (incoming wins for scalars/lists)."""
    merged: Dict[str, object] = dict(base)
    for key, value in incoming.items():
        if key not in merged:
            merged[key] = value
            continue
        left = merged[key]
        if isinstance(left, Mapping) and isinstance(value, Mapping):
            merged[key] = _deep_merge(dict(left), dict(value))
        else:
            merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# Parsing helpers (unchanged core logic, just made stricter & typed)
# ---------------------------------------------------------------------------


def _load_scenarios(payload: Mapping[str, object]) -> Mapping[str, ScenarioDefinition]:
    scenarios_section = payload.get("scenarios") or {}
    if not isinstance(scenarios_section, Mapping):
        raise TypeError("'scenarios' must be a mapping of scenario definitions")

    scenarios: MutableMapping[str, ScenarioDefinition] = {}
    for scenario_name, definition in scenarios_section.items():
        if not isinstance(scenario_name, str):
            raise TypeError("Scenario names must be strings")
        if not isinstance(definition, Mapping):
            raise TypeError(f"Scenario definition for {scenario_name!r} must be a mapping")

        raw_groups = definition.get("groups", [])
        if raw_groups is None:
            raw_groups = []
        if isinstance(raw_groups, str):
            raw_groups = [raw_groups]
        if not isinstance(raw_groups, (list, tuple)):
            raise TypeError(f"Scenario {scenario_name!r} groups must be a sequence of group names")

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


def _extract_groups_from_payload(payload: Mapping[str, object], source: str) -> Dict[str, Mapping[str, object]]:
    channels = payload.get("channels") or {}
    if not isinstance(channels, Mapping):
        raise TypeError(f"'channels' in {source} must be a mapping with 'groups'")
    available = channels.get("groups") or {}
    if not isinstance(available, Mapping):
        raise TypeError(f"'channels.groups' in {source} must be a mapping of group definitions")

    groups: Dict[str, Mapping[str, object]] = {}
    for group_name, metadata in available.items():
        if not isinstance(group_name, str):
            raise TypeError(f"Channel group names in {source} must be strings")
        if not isinstance(metadata, Mapping):
            raise TypeError(f"Channel group {group_name!r} in {source} must be a mapping")
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