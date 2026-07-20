"""Automatic sidecars and stage-aware validation for histogram pickle artifacts."""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import os
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
import uuid
from typing import Any

import cloudpickle

from topeft.modules.axes import info_2d as axes_info_2d
from topeft.modules.nominal_schema import (
    NOMINAL_CONTAINER_LAYOUT,
    NOMINAL_CONTAINER_SCHEMA_VERSION,
    eft_nominal_key,
    is_split_nominal_mapping,
    scalar_nominal_key,
    sumw2_key,
    validate_nominal_mapping,
)
from topeft.modules.sumw2_policy import resolved_policy_from_provenance


METADATA_SCHEMA_VERSION = 2
SUMW2_CONTENT_MANIFEST_VERSION = 1
ARTIFACT_KINDS = frozenset(
    {"processor_output", "nonprompt_output", "flips_output"}
)


class histogram_artifact_error(RuntimeError):
    """Base error for histogram artifact metadata failures."""


class histogram_sidecar_error(histogram_artifact_error):
    """A sidecar is absent, malformed, or paired with the wrong pickle."""


class histogram_content_error(histogram_artifact_error):
    """A serialized histogram payload disagrees with its generated manifest."""


class histogram_merge_error(histogram_artifact_error):
    """Input sidecars cannot describe one valid merged artifact."""


def metadata_sidecar_path(pkl_path: str | os.PathLike[str]) -> Path:
    """Return the one canonical sidecar path without replacing any suffix."""

    return Path(f"{os.fspath(pkl_path)}.metadata.json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_identity(identity_path: Path, *, pkl_basename: str) -> dict[str, Any]:
    return {
        "pkl_basename": pkl_basename,
        "pkl_size_bytes": identity_path.stat().st_size,
        "pkl_sha256": _sha256(identity_path),
    }


def _process_labels(histogram: Any | None) -> list[str]:
    if histogram is None:
        return []
    try:
        return sorted({str(value) for value in histogram.axes["process"]})
    except Exception:
        return []


def _family_process_content(
    histograms: Mapping[str, Any],
    family: str,
) -> dict[str, list[str] | int]:
    dimensionality = 2 if family in axes_info_2d else 1
    if dimensionality == 2:
        scalar = histograms.get(family)
        eft = None
    else:
        scalar = histograms.get(scalar_nominal_key(family))
        eft = histograms.get(eft_nominal_key(family))
    companion = histograms.get(sumw2_key(family))
    return {
        "dimensionality": dimensionality,
        "scalar_nominal_processes": _process_labels(scalar),
        "eft_nominal_processes": _process_labels(eft),
        "sumw2_processes": _process_labels(companion),
    }


def _normalize_required_processes(
    required_sumw2_processes: Mapping[str, Iterable[str]] | None,
) -> dict[str, list[str]]:
    output = {}
    for family, processes in (required_sumw2_processes or {}).items():
        output[str(family)] = sorted({str(process) for process in processes})
    return output


def build_sumw2_content_manifest(
    histograms: Mapping[str, Any],
    *,
    sumw2_storage_provenance: Mapping[str, Any],
    artifact_kind: str,
    required_sumw2_processes: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, Any]:
    """Describe actual nominal and companion process content deterministically."""

    if artifact_kind not in ARTIFACT_KINDS:
        raise histogram_sidecar_error(
            f"Unknown histogram artifact kind {artifact_kind!r}."
        )
    policy = resolved_policy_from_provenance(sumw2_storage_provenance)
    explicit_required = _normalize_required_processes(required_sumw2_processes)
    unknown_required = sorted(
        set(explicit_required) - set(policy.runtime_histogram_families)
    )
    if unknown_required:
        raise histogram_sidecar_error(
            "Required sumw2 process mapping contains unknown families: "
            + ", ".join(unknown_required)
        )

    families = {}
    for family in policy.runtime_histogram_families:
        content = _family_process_content(histograms, family)
        if family in explicit_required:
            required = explicit_required[family]
        elif artifact_kind == "processor_output":
            nominal_processes = set(content["scalar_nominal_processes"]) | set(
                content["eft_nominal_processes"]
            )
            required = sorted(
                nominal_processes & set(policy.selected_processes(family))
            )
        else:
            required = list(content["sumw2_processes"])
        families[family] = {
            **content,
            "required_sumw2_processes": required,
        }
    return {
        "manifest_version": SUMW2_CONTENT_MANIFEST_VERSION,
        "families": families,
    }


def _normalize_lineage_inputs(
    lineage_inputs: Iterable[Mapping[str, Any]],
) -> list[dict[str, str]]:
    normalized = []
    expected_keys = {"pkl_basename", "artifact_kind", "pkl_sha256"}
    for raw_input in lineage_inputs:
        if not isinstance(raw_input, Mapping) or set(raw_input) != expected_keys:
            raise histogram_sidecar_error(
                "Lineage inputs must contain exactly pkl_basename, artifact_kind, and pkl_sha256."
            )
        values = {key: raw_input[key] for key in sorted(expected_keys)}
        if any(not isinstance(value, str) or not value for value in values.values()):
            raise histogram_sidecar_error(
                "Lineage input identity fields must be nonempty strings."
            )
        if values["artifact_kind"] not in ARTIFACT_KINDS:
            raise histogram_sidecar_error(
                f"Unknown lineage artifact kind {values['artifact_kind']!r}."
            )
        normalized.append(values)
    normalized.sort(
        key=lambda item: (
            item["pkl_basename"],
            item["artifact_kind"],
            item["pkl_sha256"],
        )
    )
    if len(normalized) != len(
        {
            (item["pkl_basename"], item["artifact_kind"], item["pkl_sha256"])
            for item in normalized
        }
    ):
        raise histogram_sidecar_error("Lineage inputs must be unique.")
    return normalized


def _build_sidecar_payload(
    pkl_path: Path,
    histograms: Mapping[str, Any],
    *,
    identity_path: Path,
    artifact_kind: str,
    merged: bool,
    sumw2_storage_provenance: Mapping[str, Any],
    lineage_inputs: Iterable[Mapping[str, Any]],
    required_sumw2_processes: Mapping[str, Iterable[str]] | None,
) -> dict[str, Any]:
    identity = _file_identity(identity_path, pkl_basename=pkl_path.name)
    return {
        "metadata_schema_version": METADATA_SCHEMA_VERSION,
        "artifact": {
            **identity,
            "artifact_kind": artifact_kind,
            "merged": bool(merged),
            "nominal_container_schema_version": NOMINAL_CONTAINER_SCHEMA_VERSION,
            "nominal_container_layout": NOMINAL_CONTAINER_LAYOUT,
        },
        "sumw2_storage_provenance": copy.deepcopy(
            dict(sumw2_storage_provenance)
        ),
        "sumw2_content_manifest": build_sumw2_content_manifest(
            histograms,
            sumw2_storage_provenance=sumw2_storage_provenance,
            artifact_kind=artifact_kind,
            required_sumw2_processes=required_sumw2_processes,
        ),
        "lineage": {"inputs": _normalize_lineage_inputs(lineage_inputs)},
    }


def lineage_input_from_sidecar(sidecar: Mapping[str, Any]) -> dict[str, str]:
    artifact = sidecar["artifact"]
    return {
        "pkl_basename": artifact["pkl_basename"],
        "artifact_kind": artifact["artifact_kind"],
        "pkl_sha256": artifact["pkl_sha256"],
    }


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    *,
    label: str,
) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing or unknown:
        raise histogram_sidecar_error(
            f"Invalid {label} fields; missing={missing} unknown={unknown}."
        )


def _require_sorted_unique_strings(value: Any, *, label: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise histogram_sidecar_error(f"{label} must be a list of nonempty strings.")
    if value != sorted(set(value)):
        raise histogram_sidecar_error(
            f"{label} must be unique and lexically ordered."
        )
    return list(value)


def _validate_sidecar_structure(
    sidecar: Mapping[str, Any],
    *,
    pkl_path: Path,
) -> dict[str, Any]:
    if not isinstance(sidecar, Mapping):
        raise histogram_sidecar_error("Histogram sidecar must be a JSON object.")
    _require_exact_keys(
        sidecar,
        {
            "metadata_schema_version",
            "artifact",
            "sumw2_storage_provenance",
            "sumw2_content_manifest",
            "lineage",
        },
        label="histogram sidecar",
    )
    if sidecar["metadata_schema_version"] != METADATA_SCHEMA_VERSION:
        raise histogram_sidecar_error(
            "Unsupported histogram metadata schema version "
            f"{sidecar['metadata_schema_version']!r}."
        )

    artifact = sidecar["artifact"]
    if not isinstance(artifact, Mapping):
        raise histogram_sidecar_error("Histogram sidecar artifact must be an object.")
    _require_exact_keys(
        artifact,
        {
            "pkl_basename",
            "pkl_size_bytes",
            "pkl_sha256",
            "artifact_kind",
            "merged",
            "nominal_container_schema_version",
            "nominal_container_layout",
        },
        label="artifact",
    )
    if artifact["pkl_basename"] != pkl_path.name:
        raise histogram_sidecar_error(
            "Histogram artifact identity mismatch: "
            f"pkl_path={pkl_path} sidecar_path={metadata_sidecar_path(pkl_path)} "
            f"expected_basename={artifact['pkl_basename']!r} "
            f"observed_basename={pkl_path.name!r}. Regenerate the sidecar with the artifact producer."
        )
    if not isinstance(artifact["pkl_size_bytes"], int) or artifact["pkl_size_bytes"] < 0:
        raise histogram_sidecar_error("artifact.pkl_size_bytes must be a nonnegative integer.")
    if (
        not isinstance(artifact["pkl_sha256"], str)
        or len(artifact["pkl_sha256"]) != 64
        or any(character not in "0123456789abcdef" for character in artifact["pkl_sha256"])
    ):
        raise histogram_sidecar_error("artifact.pkl_sha256 must be a SHA-256 hex digest.")
    if artifact["artifact_kind"] not in ARTIFACT_KINDS:
        raise histogram_sidecar_error(
            f"Unknown histogram artifact kind {artifact['artifact_kind']!r}."
        )
    if not isinstance(artifact["merged"], bool):
        raise histogram_sidecar_error("artifact.merged must be a boolean.")
    if artifact["nominal_container_schema_version"] != NOMINAL_CONTAINER_SCHEMA_VERSION:
        raise histogram_sidecar_error("Artifact nominal schema version is incompatible.")
    if artifact["nominal_container_layout"] != NOMINAL_CONTAINER_LAYOUT:
        raise histogram_sidecar_error("Artifact nominal container layout is incompatible.")

    policy = resolved_policy_from_provenance(sidecar["sumw2_storage_provenance"])
    manifest = sidecar["sumw2_content_manifest"]
    if not isinstance(manifest, Mapping):
        raise histogram_sidecar_error("sumw2_content_manifest must be an object.")
    _require_exact_keys(
        manifest,
        {"manifest_version", "families"},
        label="sumw2_content_manifest",
    )
    if manifest["manifest_version"] != SUMW2_CONTENT_MANIFEST_VERSION:
        raise histogram_sidecar_error("Unsupported sumw2 content manifest version.")
    families = manifest["families"]
    if not isinstance(families, Mapping):
        raise histogram_sidecar_error("sumw2_content_manifest.families must be an object.")
    if list(families) != list(policy.runtime_histogram_families):
        raise histogram_sidecar_error(
            "Manifest families must match authoritative runtime family order: "
            f"expected={list(policy.runtime_histogram_families)} observed={list(families)}."
        )
    family_fields = {
        "dimensionality",
        "scalar_nominal_processes",
        "eft_nominal_processes",
        "sumw2_processes",
        "required_sumw2_processes",
    }
    for family, family_manifest in families.items():
        if not isinstance(family_manifest, Mapping):
            raise histogram_sidecar_error(f"Manifest family '{family}' must be an object.")
        _require_exact_keys(
            family_manifest,
            family_fields,
            label=f"manifest family '{family}'",
        )
        expected_dimensionality = 2 if family in axes_info_2d else 1
        if family_manifest["dimensionality"] != expected_dimensionality:
            raise histogram_sidecar_error(
                f"Manifest family '{family}' has wrong dimensionality."
            )
        for field_name in family_fields - {"dimensionality"}:
            _require_sorted_unique_strings(
                family_manifest[field_name],
                label=f"manifest family '{family}' field '{field_name}'",
            )
        required = set(family_manifest["required_sumw2_processes"])
        observed = set(family_manifest["sumw2_processes"])
        if not required <= observed:
            raise histogram_sidecar_error(
                f"Manifest family '{family}' requires sumw2 processes absent from its content: "
                + ", ".join(sorted(required - observed))
            )

    lineage = sidecar["lineage"]
    if not isinstance(lineage, Mapping):
        raise histogram_sidecar_error("lineage must be an object.")
    _require_exact_keys(lineage, {"inputs"}, label="lineage")
    if not isinstance(lineage["inputs"], list):
        raise histogram_sidecar_error("lineage.inputs must be a list.")
    normalized_lineage = _normalize_lineage_inputs(lineage["inputs"])
    if normalized_lineage != lineage["inputs"]:
        raise histogram_sidecar_error("lineage.inputs must use deterministic ordering.")
    if (
        artifact["artifact_kind"] == "processor_output"
        and not artifact["merged"]
        and lineage["inputs"]
    ):
        raise histogram_sidecar_error(
            "An unmerged processor_output lineage.inputs list must be empty."
        )
    if (
        (artifact["artifact_kind"] != "processor_output" or artifact["merged"])
        and not lineage["inputs"]
    ):
        raise histogram_sidecar_error(
            f"{artifact['artifact_kind']} merged={artifact['merged']} requires generated input lineage."
        )
    return copy.deepcopy(dict(sidecar))


def read_histogram_sidecar(
    pkl_path: str | os.PathLike[str],
) -> dict[str, Any]:
    """Read the canonical colocated sidecar; callers never pass a JSON path."""

    pkl_path = Path(pkl_path)
    sidecar_path = metadata_sidecar_path(pkl_path)
    if not sidecar_path.is_file():
        raise FileNotFoundError(f"Histogram sidecar not found: {sidecar_path}")
    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise histogram_sidecar_error(
            f"Could not read histogram sidecar '{sidecar_path}': {error}"
        ) from error
    return _validate_sidecar_structure(payload, pkl_path=pkl_path)


def _validate_content_manifest(
    pkl_path: Path,
    histograms: Mapping[str, Any],
    sidecar: Mapping[str, Any],
) -> None:
    artifact_kind = sidecar["artifact"]["artifact_kind"]
    expected_manifest = sidecar["sumw2_content_manifest"]
    actual_manifest = build_sumw2_content_manifest(
        histograms,
        sumw2_storage_provenance=sidecar["sumw2_storage_provenance"],
        artifact_kind=artifact_kind,
        required_sumw2_processes={
            family: family_manifest["required_sumw2_processes"]
            for family, family_manifest in expected_manifest["families"].items()
        },
    )
    for family, expected in expected_manifest["families"].items():
        observed = actual_manifest["families"][family]
        for field_name in (
            "scalar_nominal_processes",
            "eft_nominal_processes",
            "sumw2_processes",
        ):
            if expected[field_name] == observed[field_name]:
                continue
            expected_processes = expected[field_name]
            observed_processes = observed[field_name]
            missing = sorted(set(expected_processes) - set(observed_processes))
            unexpected = sorted(set(observed_processes) - set(expected_processes))
            raise histogram_content_error(
                "Histogram artifact content mismatch: "
                f"pkl_path={pkl_path} sidecar_path={metadata_sidecar_path(pkl_path)} "
                f"artifact_kind={artifact_kind} family={family} field={field_name} "
                f"expected_processes={expected_processes} observed_processes={observed_processes} "
                f"missing_required_companions={missing if field_name == 'sumw2_processes' else []} "
                f"unexpected_companions={unexpected if field_name == 'sumw2_processes' else []}. "
                "Regenerate the PKL and sidecar together with run_analysis, run_data_driven, "
                "or the merged-cache writer."
            )
        required = set(expected["required_sumw2_processes"])
        observed_sumw2 = set(observed["sumw2_processes"])
        missing_required = sorted(required - observed_sumw2)
        if missing_required:
            raise histogram_content_error(
                "Histogram artifact is missing required companions: "
                f"pkl_path={pkl_path} sidecar_path={metadata_sidecar_path(pkl_path)} "
                f"artifact_kind={artifact_kind} family={family} "
                f"expected_processes={sorted(required)} observed_processes={sorted(observed_sumw2)} "
                f"missing_required_companions={missing_required} unexpected_companions=[]. "
                "Regenerate this artifact with its maintained producer."
            )


def _validate_artifact_identity(pkl_path: Path, sidecar: Mapping[str, Any]) -> None:
    expected = sidecar["artifact"]
    observed_size = pkl_path.stat().st_size
    observed_sha256 = _sha256(pkl_path)
    if (
        observed_size != expected["pkl_size_bytes"]
        or observed_sha256 != expected["pkl_sha256"]
    ):
        raise histogram_sidecar_error(
            "Histogram artifact identity mismatch: "
            f"pkl_path={pkl_path} sidecar_path={metadata_sidecar_path(pkl_path)} "
            f"expected_basename={expected['pkl_basename']!r} observed_basename={pkl_path.name!r} "
            f"expected_size={expected['pkl_size_bytes']} observed_size={observed_size} "
            f"expected_sha256={expected['pkl_sha256']} observed_sha256={observed_sha256}. "
            "Regenerate or restore the matching PKL/sidecar pair."
        )


def validate_processor_output(
    pkl_path: str | os.PathLike[str],
    histograms: Mapping[str, Any],
    sidecar: Mapping[str, Any],
) -> None:
    if sidecar["artifact"]["artifact_kind"] != "processor_output":
        raise histogram_content_error("Expected artifact_kind=processor_output.")
    policy = resolved_policy_from_provenance(sidecar["sumw2_storage_provenance"])
    validate_nominal_mapping(
        histograms,
        runtime_families=policy.runtime_histogram_families,
        schema_version=NOMINAL_CONTAINER_SCHEMA_VERSION,
        policy=policy,
    )
    expected_manifest = build_sumw2_content_manifest(
        histograms,
        sumw2_storage_provenance=sidecar["sumw2_storage_provenance"],
        artifact_kind="processor_output",
    )
    for family in policy.runtime_histogram_families:
        expected_required = expected_manifest["families"][family][
            "required_sumw2_processes"
        ]
        observed_required = sidecar["sumw2_content_manifest"]["families"][family][
            "required_sumw2_processes"
        ]
        if observed_required != expected_required:
            raise histogram_content_error(
                f"processor_output family '{family}' has required_sumw2_processes "
                f"{observed_required}, expected {expected_required} from source allocation."
            )


def _validate_transformed_output(
    pkl_path: str | os.PathLike[str],
    histograms: Mapping[str, Any],
    sidecar: Mapping[str, Any],
    *,
    artifact_kind: str,
) -> None:
    if sidecar["artifact"]["artifact_kind"] != artifact_kind:
        raise histogram_content_error(f"Expected artifact_kind={artifact_kind}.")
    policy = resolved_policy_from_provenance(sidecar["sumw2_storage_provenance"])
    validate_nominal_mapping(
        histograms,
        runtime_families=policy.runtime_histogram_families,
        schema_version=NOMINAL_CONTAINER_SCHEMA_VERSION,
        policy=None,
    )
    manifest_families = sidecar["sumw2_content_manifest"]["families"]
    for family in policy.runtime_histogram_families:
        family_manifest = manifest_families[family]
        if not policy.selects_family(family) and sumw2_key(family) in histograms:
            raise histogram_content_error(
                f"{artifact_kind} pkl_path={pkl_path} family={family} contains a "
                "companion for a source-policy-unselected family. Regenerate it "
                "with run_data_driven."
            )
        if policy.selects_family(family) and sumw2_key(family) not in histograms:
            raise histogram_content_error(
                f"{artifact_kind} pkl_path={pkl_path} family={family} is missing its "
                f"required transformed companion. Regenerate it with run_data_driven."
            )
        if family_manifest["required_sumw2_processes"] != family_manifest[
            "sumw2_processes"
        ]:
            raise histogram_content_error(
                f"{artifact_kind} family '{family}' must require exactly its generated "
                "transformed sumw2 process content."
            )
        nominal_processes = set(family_manifest["scalar_nominal_processes"]) | set(
            family_manifest["eft_nominal_processes"]
        )
        unexpected_companions = sorted(
            set(family_manifest["sumw2_processes"]) - nominal_processes
        )
        if unexpected_companions:
            raise histogram_content_error(
                f"{artifact_kind} pkl_path={pkl_path} family={family} contains "
                f"unexpected transformed companions {unexpected_companions} without "
                "matching nominal process content. Regenerate it with run_data_driven."
            )
        if artifact_kind == "flips_output":
            for field_name in (
                "scalar_nominal_processes",
                "sumw2_processes",
            ):
                unexpected = [
                    process
                    for process in family_manifest[field_name]
                    if "flips" not in process.lower()
                ]
                if unexpected:
                    raise histogram_content_error(
                        f"flips_output family '{family}' contains non-flips processes in "
                        f"{field_name}: {unexpected}. Regenerate with run_data_driven --only-flips."
                    )


def validate_nonprompt_output(
    pkl_path: str | os.PathLike[str],
    histograms: Mapping[str, Any],
    sidecar: Mapping[str, Any],
) -> None:
    _validate_transformed_output(
        pkl_path,
        histograms,
        sidecar,
        artifact_kind="nonprompt_output",
    )


def validate_flips_output(
    pkl_path: str | os.PathLike[str],
    histograms: Mapping[str, Any],
    sidecar: Mapping[str, Any],
) -> None:
    _validate_transformed_output(
        pkl_path,
        histograms,
        sidecar,
        artifact_kind="flips_output",
    )


def _load_histograms(pkl_path: Path) -> dict[str, Any]:
    from topcoffea.modules.utils import get_hist_from_pkl

    loaded = get_hist_from_pkl(str(pkl_path), allow_empty=False)
    if not isinstance(loaded, dict):
        raise histogram_content_error(
            f"Histogram PKL '{pkl_path}' did not contain a dictionary."
        )
    return loaded


def _recognized_legacy_metadata(payload: Any) -> bool:
    return (
        isinstance(payload, Mapping)
        and payload.get("metadata_version") == 1
        and {
            "input_histogram",
            "sumw2_storage_provenance",
            "nominal_container_schema_version",
            "nominal_container_layout",
        }
        <= set(payload)
    )


def validate_histogram_artifact(
    pkl_path: str | os.PathLike[str],
    histograms: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a split artifact or classify an explicit legacy uniform payload."""

    pkl_path = Path(pkl_path)
    loaded = dict(histograms) if histograms is not None else _load_histograms(pkl_path)
    split_payload = is_split_nominal_mapping(loaded)
    sidecar_path = metadata_sidecar_path(pkl_path)
    if not sidecar_path.is_file():
        if split_payload:
            split_keys = sorted(
                key
                for key in loaded
                if key.endswith("__scalar_nominal") or key.endswith("__eft_nominal")
            )
            raise histogram_sidecar_error(
                "Schema-v2 histogram PKL is missing its required automatic sidecar: "
                f"pkl_path={pkl_path} expected_sidecar_path={sidecar_path} "
                f"detected_split_sibling_keys={split_keys}. Expected producer: run_analysis, "
                "run_data_driven, or a merged-cache writer. Regenerate the artifact with its "
                "maintained producer; do not supply a sidecar path manually."
            )
        return {
            "schema": "legacy_uniform",
            "metadata": None,
            "legacy_metadata_present": False,
        }

    try:
        raw_payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise histogram_sidecar_error(
            "Could not read automatic histogram sidecar: "
            f"pkl_path={pkl_path} sidecar_path={sidecar_path} error={error}. "
            "Regenerate the PKL and sidecar together with the maintained producer."
        ) from error
    if _recognized_legacy_metadata(raw_payload):
        if split_payload:
            raise histogram_sidecar_error(
                f"Schema-v2 PKL '{pkl_path}' has obsolete version-1 metadata at "
                f"'{sidecar_path}'. Regenerate it with the maintained producer."
            )
        return {
            "schema": "legacy_uniform",
            "metadata": None,
            "legacy_metadata_present": True,
        }
    sidecar = _validate_sidecar_structure(raw_payload, pkl_path=pkl_path)
    _validate_content_manifest(pkl_path, loaded, sidecar)
    artifact_kind = sidecar["artifact"]["artifact_kind"]
    if artifact_kind == "processor_output":
        validate_processor_output(pkl_path, loaded, sidecar)
    elif artifact_kind == "nonprompt_output":
        validate_nonprompt_output(pkl_path, loaded, sidecar)
    elif artifact_kind == "flips_output":
        validate_flips_output(pkl_path, loaded, sidecar)
    else:  # pragma: no cover - structural validation already rejects this
        raise histogram_sidecar_error(f"Unknown artifact kind {artifact_kind!r}.")
    _validate_artifact_identity(pkl_path, sidecar)
    return {
        "schema": NOMINAL_CONTAINER_LAYOUT,
        "metadata": sidecar,
        "legacy_metadata_present": False,
    }


def merge_histogram_sidecars(
    sidecars: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate merge compatibility and derive deterministic output metadata inputs."""

    sidecars = tuple(sidecars)
    if not sidecars:
        raise histogram_merge_error("No histogram sidecars were provided for merge.")
    kinds = {sidecar["artifact"]["artifact_kind"] for sidecar in sidecars}
    if len(kinds) != 1:
        raise histogram_merge_error(
            "Cannot merge incompatible histogram artifact kinds: "
            + ", ".join(sorted(kinds))
        )
    kind = next(iter(kinds))
    layouts = {
        (
            sidecar["artifact"]["nominal_container_schema_version"],
            sidecar["artifact"]["nominal_container_layout"],
        )
        for sidecar in sidecars
    }
    if len(layouts) != 1:
        raise histogram_merge_error("Cannot merge incompatible nominal schemas/layouts.")
    provenance = copy.deepcopy(sidecars[0]["sumw2_storage_provenance"])
    provenance_identity = json.dumps(provenance, sort_keys=True, separators=(",", ":"))
    for sidecar in sidecars[1:]:
        current_identity = json.dumps(
            sidecar["sumw2_storage_provenance"],
            sort_keys=True,
            separators=(",", ":"),
        )
        if current_identity != provenance_identity:
            raise histogram_merge_error(
                "Maintained histogram merging requires identical source-allocation provenance."
            )
    family_orders = [
        tuple(sidecar["sumw2_content_manifest"]["families"])
        for sidecar in sidecars
    ]
    if any(order != family_orders[0] for order in family_orders[1:]):
        raise histogram_merge_error("Cannot merge incompatible family manifests.")
    required = {}
    for family in family_orders[0]:
        dimensions = {
            sidecar["sumw2_content_manifest"]["families"][family]["dimensionality"]
            for sidecar in sidecars
        }
        if len(dimensions) != 1:
            raise histogram_merge_error(
                f"Cannot merge incompatible dimensionality for family '{family}'."
            )
        required[family] = sorted(
            {
                process
                for sidecar in sidecars
                for process in sidecar["sumw2_content_manifest"]["families"][family][
                    "required_sumw2_processes"
                ]
            }
        )
    return {
        "artifact_kind": kind,
        "merged": True,
        "sumw2_storage_provenance": provenance,
        "required_sumw2_processes": required,
        "lineage_inputs": [lineage_input_from_sidecar(sidecar) for sidecar in sidecars],
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def write_histogram_sidecar(
    pkl_path: str | os.PathLike[str],
    *,
    histograms: Mapping[str, Any],
    artifact_kind: str,
    sumw2_storage_provenance: Mapping[str, Any],
    merged: bool = False,
    lineage_inputs: Iterable[Mapping[str, Any]] = (),
    required_sumw2_processes: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, Any]:
    """Write one automatic sidecar for an already finalized PKL."""

    pkl_path = Path(pkl_path)
    payload = _build_sidecar_payload(
        pkl_path,
        histograms,
        identity_path=pkl_path,
        artifact_kind=artifact_kind,
        merged=merged,
        sumw2_storage_provenance=sumw2_storage_provenance,
        lineage_inputs=lineage_inputs,
        required_sumw2_processes=required_sumw2_processes,
    )
    _validate_sidecar_structure(payload, pkl_path=pkl_path)
    temporary_path = metadata_sidecar_path(pkl_path).with_name(
        f".{metadata_sidecar_path(pkl_path).name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        _write_json(temporary_path, payload)
        os.replace(temporary_path, metadata_sidecar_path(pkl_path))
    finally:
        temporary_path.unlink(missing_ok=True)
    return payload


def _default_pickle_writer(path: str, histograms: Mapping[str, Any]) -> None:
    with gzip.open(path, "wb") as stream:
        cloudpickle.dump(histograms, stream)


def write_histogram_artifact(
    pkl_path: str | os.PathLike[str],
    *,
    artifact_kind: str,
    sumw2_storage_provenance: Mapping[str, Any],
    histograms: Mapping[str, Any] | None = None,
    payload_writer: Callable[[str], None] | None = None,
    merged: bool = False,
    lineage_inputs: Iterable[Mapping[str, Any]] = (),
    required_sumw2_processes: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, Any]:
    """Stage, validate, and publish a PKL/sidecar pair as one logical output."""

    if (histograms is None) == (payload_writer is None):
        raise ValueError("Provide exactly one of histograms or payload_writer.")
    pkl_path = Path(pkl_path)
    pkl_path.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    staged_pkl = pkl_path.parent / f".{pkl_path.name}.{token}.pkl.gz"
    staged_sidecar = pkl_path.parent / f".{pkl_path.name}.{token}.metadata.json.tmp"
    final_sidecar = metadata_sidecar_path(pkl_path)
    backup_pkl = pkl_path.parent / f".{pkl_path.name}.{token}.backup"
    backup_sidecar = pkl_path.parent / f".{final_sidecar.name}.{token}.backup"
    had_pkl = pkl_path.exists()
    had_sidecar = final_sidecar.exists()
    published_pkl = False
    published_sidecar = False
    try:
        if payload_writer is not None:
            payload_writer(str(staged_pkl))
        else:
            assert histograms is not None
            _default_pickle_writer(str(staged_pkl), histograms)
        manifest_histograms = (
            dict(histograms)
            if histograms is not None
            else _load_histograms(staged_pkl)
        )
        sidecar = _build_sidecar_payload(
            pkl_path,
            manifest_histograms,
            identity_path=staged_pkl,
            artifact_kind=artifact_kind,
            merged=merged,
            sumw2_storage_provenance=sumw2_storage_provenance,
            lineage_inputs=lineage_inputs,
            required_sumw2_processes=required_sumw2_processes,
        )
        _validate_sidecar_structure(sidecar, pkl_path=pkl_path)
        _validate_content_manifest(pkl_path, manifest_histograms, sidecar)
        if artifact_kind == "processor_output":
            validate_processor_output(pkl_path, manifest_histograms, sidecar)
        elif artifact_kind == "nonprompt_output":
            validate_nonprompt_output(pkl_path, manifest_histograms, sidecar)
        else:
            validate_flips_output(pkl_path, manifest_histograms, sidecar)
        _write_json(staged_sidecar, sidecar)

        if had_pkl:
            os.replace(pkl_path, backup_pkl)
        if had_sidecar:
            os.replace(final_sidecar, backup_sidecar)
        os.replace(staged_pkl, pkl_path)
        published_pkl = True
        os.replace(staged_sidecar, final_sidecar)
        published_sidecar = True
        backup_pkl.unlink(missing_ok=True)
        backup_sidecar.unlink(missing_ok=True)
        return sidecar
    except Exception:
        if published_sidecar:
            final_sidecar.unlink(missing_ok=True)
        if published_pkl:
            pkl_path.unlink(missing_ok=True)
        if backup_pkl.exists():
            os.replace(backup_pkl, pkl_path)
        if backup_sidecar.exists():
            os.replace(backup_sidecar, final_sidecar)
        raise
    finally:
        staged_pkl.unlink(missing_ok=True)
        staged_sidecar.unlink(missing_ok=True)
        backup_pkl.unlink(missing_ok=True)
        backup_sidecar.unlink(missing_ok=True)
