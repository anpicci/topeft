"""Shared helpers for loading metadata bundles once per execution."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Optional, Sequence

import yaml

logger = logging.getLogger(__name__)


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

    if not metadata_path:
        raise ValueError("metadata_path must be provided")
    candidate = Path(metadata_path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    try:
        return candidate.resolve(strict=True)
    except FileNotFoundError as exc:  # pragma: no cover - filesystem error details
        raise FileNotFoundError(
            f"Metadata file '{candidate}' could not be found."
        ) from exc


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

    resolved_path = resolve_metadata_path(metadata_path)
    try:
        with resolved_path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - depends on parser internals
        raise RuntimeError(
            f"Failed to parse metadata YAML '{resolved_path}': {exc}"
        ) from exc

    mapping_payload = _ensure_mapping(payload, str(resolved_path))

    sections = tuple(required_sections or ())
    for section in sections:
        if not isinstance(mapping_payload.get(section), Mapping):
            raise KeyError(
                f"metadata[{section!r}] is required but missing or not a mapping in '{resolved_path}'."
            )

    return MetadataBundle(
        path=resolved_path,
        payload=mapping_payload,
        channels=_extract_section(mapping_payload, "channels"),
        systematics=_extract_section(mapping_payload, "systematics"),
        variables=_extract_section(mapping_payload, "variables"),
    )


__all__ = ["MetadataBundle", "load_metadata", "resolve_metadata_path"]
