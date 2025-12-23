"""Resolve the authoritative metadata path for Run 2 execution."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from analysis.topeft_run2.metadata_loader import resolve_metadata_path
from analysis.topeft_run2.scenario_registry import resolve_scenario_choice

MetadataResolution = Tuple[str, str]


def _normalize_metadata_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    candidate = str(value).strip()
    return candidate or None


def resolve_effective_metadata_path(
    *,
    scenario_name: str,
    metadata_cli: Optional[str] = None,
    metadata_options: Optional[str] = None,
) -> MetadataResolution:
    """Return the metadata path and its provenance for ``scenario_name``.

    Precedence:
      1) Explicit CLI metadata path.
      2) Metadata path from options YAML.
      3) Scenario registry fallback.
    """

    if not scenario_name:
        raise ValueError("scenario_name must be provided to resolve metadata")

    metadata_cli = _normalize_metadata_value(metadata_cli)
    metadata_options = _normalize_metadata_value(metadata_options)

    if metadata_cli:
        metadata_path = metadata_cli
        provenance = "cli"
    elif metadata_options:
        metadata_path = metadata_options
        provenance = "options"
    else:
        resolution = resolve_scenario_choice(scenario_name)
        metadata_path = resolution.metadata_path
        provenance = "scenario_registry"

    resolved = resolve_metadata_path(metadata_path)
    return str(Path(resolved)), provenance


__all__ = ["resolve_effective_metadata_path", "MetadataResolution"]
