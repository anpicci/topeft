"""Deprecated compatibility helpers for resolving scenario metadata paths."""

from __future__ import annotations

import warnings
from typing import Iterable

from analysis.topeft_run2 import metadata_authority


def known_scenarios() -> Iterable[str]:
    """Return the scenario names enumerated in run2_scenarios.yaml."""

    _warn_deprecated()
    return metadata_authority.known_scenarios()


def resolve_scenario_choice(name: str) -> metadata_authority.ScenarioResolution:
    """Return the default metadata path and known names for ``name``."""

    _warn_deprecated()
    return metadata_authority.resolve_scenario_choice(name)


def resolve_scenario_path(name: str) -> str:
    """Return the default metadata path for ``name`` for backwards compatibility."""

    _warn_deprecated()
    return str(resolve_scenario_choice(name).metadata_path)


def select_metadata_path(name: str, explicit_path: str | None) -> str:
    """Return ``explicit_path`` when provided, otherwise raise."""

    _warn_deprecated()
    resolve_scenario_choice(name)
    selected, _ = metadata_authority.select_metadata_source(
        explicit_path,
        None,
        metadata_authority.DEFAULT_METADATA_RELATIVE,
    )
    return str(selected)


def _warn_deprecated() -> None:
    warnings.warn(
        "analysis.topeft_run2.scenario_registry is deprecated; "
        "use analysis.topeft_run2.metadata_authority instead.",
        DeprecationWarning,
        stacklevel=2,
    )


__all__ = [
    "known_scenarios",
    "resolve_scenario_choice",
    "resolve_scenario_path",
    "select_metadata_path",
]
