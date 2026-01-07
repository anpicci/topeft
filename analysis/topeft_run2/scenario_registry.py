"""Compatibility helpers for resolving scenario metadata paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence

from analysis.topeft_run2 import metadata_authority


def known_scenarios() -> Iterable[str]:
    """Return the scenario names enumerated in run2_scenarios.yaml."""

    return metadata_authority.load_scenarios().keys()


@dataclass(frozen=True)
class ScenarioResolution:
    """Describes the metadata path lookup for a scenario."""

    metadata_path: str
    known_scenarios: Sequence[str]


def resolve_scenario_choice(name: str) -> ScenarioResolution:
    """Return the default metadata path and known names for ``name``."""

    known: List[str] = list(known_scenarios())
    if name not in known:
        available = ", ".join(known)
        raise ValueError(
            f"Unknown scenario '{name}'. Known scenarios: {available}"
        )
    metadata_path = str(metadata_authority.resolve_metadata_path(None))
    return ScenarioResolution(metadata_path=metadata_path, known_scenarios=known)


def resolve_scenario_path(name: str) -> str:
    """Return the default metadata path for ``name`` for backwards compatibility."""

    return resolve_scenario_choice(name).metadata_path


def select_metadata_path(name: str, explicit_path: str | None) -> str:
    """Return ``explicit_path`` when provided, otherwise raise."""

    if explicit_path:
        return explicit_path
    raise ValueError(
        "Explicit metadata path required; scenario registry fallback has been removed."
    )


__all__ = [
    "ScenarioResolution",
    "known_scenarios",
    "resolve_scenario_choice",
    "resolve_scenario_path",
    "select_metadata_path",
]
