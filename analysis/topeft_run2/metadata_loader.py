"""Deprecated helpers for loading metadata bundles.

Callers should migrate to ``analysis.topeft_run2.metadata_authority``. This
module remains as a thin, deprecated delegator for backwards compatibility.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Optional, Sequence

from analysis.topeft_run2 import metadata_authority


@dataclass(frozen=True)
class MetadataBundle:
    """Container describing a resolved metadata YAML payload."""

    path: Path
    payload: MutableMapping[str, Any]
    channels: Optional[Mapping[str, Any]]
    systematics: Optional[Mapping[str, Any]]
    variables: Optional[Mapping[str, Any]]


def resolve_metadata_path(metadata_path: str | Path) -> Path:
    """Return the absolute path to ``metadata_path`` ensuring it exists."""

    warnings.warn(
        "analysis.topeft_run2.metadata_loader.resolve_metadata_path is deprecated; "
        "use analysis.topeft_run2.metadata_authority.resolve_metadata_path instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    if not metadata_path:
        raise ValueError("metadata_path must be provided")
    return metadata_authority.resolve_metadata_path(metadata_path)


def _ensure_mapping(payload: object, description: str) -> MutableMapping[str, Any]:
    if not isinstance(payload, MutableMapping):
        raise TypeError(f"{description} must be a mapping at the top level")
    return payload


def _extract_section(
    payload: MutableMapping[str, Any],
    section: str,
) -> Optional[Mapping[str, Any]]:
    raw_value = payload.get(section)
    if raw_value is None:
        return None
    if not isinstance(raw_value, Mapping):
        raise TypeError(f"metadata['{section}'] must be a mapping when present")
    return raw_value


def load_metadata(
    metadata_path: str | Path,
    *,
    required_sections: Sequence[str] | None = None,
) -> MetadataBundle:
    """Load the metadata YAML at ``metadata_path`` and return its contents.

    Args:
        metadata_path: Path (absolute or relative) pointing to the metadata YAML.
        required_sections: Optional iterable of top-level keys that must exist
            and be mappings (for example ``("channels", "variables")``).

    Raises:
        FileNotFoundError: when ``metadata_path`` does not exist.
        RuntimeError: if the YAML cannot be parsed.
        TypeError: when the payload or a requested section is not a mapping.
        KeyError: when a required section is missing.
    """

    warnings.warn(
        "analysis.topeft_run2.metadata_loader.load_metadata is deprecated; "
        "use analysis.topeft_run2.metadata_authority.load_metadata_payload instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    resolved_path, mapping_payload = metadata_authority.load_metadata_payload(
        metadata_path,
        required_sections=required_sections,
    )
    return MetadataBundle(
        path=resolved_path,
        payload=_ensure_mapping(mapping_payload, str(resolved_path)),
        channels=_extract_section(mapping_payload, "channels"),
        systematics=_extract_section(mapping_payload, "systematics"),
        variables=_extract_section(mapping_payload, "variables"),
    )


__all__ = ["MetadataBundle", "load_metadata", "resolve_metadata_path"]
