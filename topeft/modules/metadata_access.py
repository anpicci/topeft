"""Run2-agnostic metadata access helpers for processors.

This module lets non-Run2 processors request metadata-driven utilities without
importing ``analysis.topeft_run2`` directly. Authority remains in
``analysis.topeft_run2.metadata_authority``; this file only delegates.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, MutableMapping, Sequence

from analysis.topeft_run2 import metadata_authority


def _normalize_scenario_name(scenario_name: str | None) -> str:
    name = (scenario_name or "TOP_22_006").strip()
    if not name:
        raise ValueError("scenario_name must be provided to load metadata")
    return name


def _ensure_required_sections(
    metadata: Mapping[str, object],
    required_sections: Sequence[str] | None,
) -> None:
    for section in tuple(required_sections or ()):
        if not isinstance(metadata.get(section), Mapping):
            raise KeyError(
                f"metadata[{section!r}] is required but missing or not a mapping in in-memory metadata."
            )


def _metadata_path_label(metadata_path: str | Path | None) -> Path:
    if metadata_path is None:
        return Path("<in-memory>")
    candidate = Path(metadata_path).expanduser()
    if not candidate.is_absolute():
        candidate = metadata_authority.get_repo_root() / candidate
    return candidate


def load_metadata_bundle_for_processor(
    metadata: Mapping[str, object] | None = None,
    metadata_path: str | Path | None = None,
    scenario_name: str | None = None,
    *,
    strict: bool = True,
    required_sections: Sequence[str] | None = ("channels",),
) -> metadata_authority.MetadataBundle:
    """Return a metadata bundle suitable for processor utilities."""

    scenario = _normalize_scenario_name(scenario_name)
    if metadata is None:
        return metadata_authority.load_metadata_bundle(
            metadata_path,
            scenario,
            strict=strict,
            required_sections=required_sections,
            metadata_source="explicit" if metadata_path else "default",
        )

    _ensure_required_sections(metadata, required_sections)
    scenarios = metadata_authority.load_scenarios()
    channels = metadata_authority.resolve_channels_for_scenario(
        scenario,
        metadata,
        scenarios=scenarios,
        strict=strict,
        source_label="in-memory metadata",
    )
    scenario_def = scenarios.get(scenario)
    if scenario_def is None:
        known = ", ".join(sorted(scenarios)) or "<none>"
        raise ValueError(
            f"Unknown scenario '{scenario}'. Known scenarios: {known}"
        )
    payload = metadata if isinstance(metadata, MutableMapping) else dict(metadata)
    path_label = _metadata_path_label(metadata_path)
    provenance = (
        f"metadata_path={path_label}",
        "metadata_source=in-memory",
        f"scenario={scenario_def.name}",
    )
    return metadata_authority.MetadataBundle(
        metadata_path=path_label,
        metadata=payload,
        channels=channels,
        scenario=scenario_def,
        scenarios=scenarios,
        provenance=provenance,
    )


def golden_json_for_year(
    metadata_bundle: metadata_authority.MetadataBundle | Mapping[str, object],
    year: str,
) -> str:
    """Return the golden JSON path for ``year`` using authority metadata."""

    metadata = (
        metadata_bundle.metadata
        if isinstance(metadata_bundle, metadata_authority.MetadataBundle)
        else metadata_bundle
    )
    return metadata_authority.golden_json_for_year(metadata, str(year))


__all__ = [
    "load_metadata_bundle_for_processor",
    "golden_json_for_year",
]
