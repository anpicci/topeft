"""Helpers for validating metadata/systematics consistency."""

from __future__ import annotations

from typing import Mapping, Sequence, Set


def _metadata_systematics_section(metadata: Mapping[str, object]) -> Mapping[str, object]:
    section = metadata.get("systematics") if metadata else {}
    if not section:
        return {}
    if not isinstance(section, Mapping):
        raise TypeError("metadata['systematics'] must be a mapping of definitions")
    return section


def metadata_non_nominal_bases(metadata: Mapping[str, object]) -> Set[str]:
    """Return the non-nominal systematic base names declared in metadata."""

    bases: Set[str] = set()
    for name, entry in _metadata_systematics_section(metadata).items():
        if not isinstance(name, str) or name == "nominal":
            continue
        if not isinstance(entry, Mapping):
            continue
        bases.add(name)
    return bases


def _normalize_applies_to(entry: Mapping[str, object]) -> Set[str]:
    applies = entry.get("applies_to") or ()
    normalized = {
        str(item).strip().lower()
        for item in applies
        if isinstance(item, str) and item.strip()
    }
    if not normalized:
        normalized = {"all"}
    return normalized


def expected_systematic_bases(
    metadata: Mapping[str, object],
    *,
    has_mc_samples: bool,
    has_data_samples: bool,
    tau_analysis: bool,
) -> Set[str]:
    """Return the systematic bases that should be scheduled for a run."""

    expected: Set[str] = set()
    for name, entry in _metadata_systematics_section(metadata).items():
        if not isinstance(entry, Mapping) or name == "nominal":
            continue
        applies_to = _normalize_applies_to(entry)
        targets_mc = {"all", "mc"} & applies_to
        targets_data = {"all", "data"} & applies_to
        if targets_mc and not has_mc_samples:
            targets_mc = set()
        if targets_data and not has_data_samples:
            targets_data = set()
        if not targets_mc and not targets_data:
            continue
        if entry.get("tau_only") and not tau_analysis:
            continue
        expected.add(name)
    return expected


def plan_systematic_bases(tasks: Sequence[object]) -> Set[str]:
    """Return the set of systematic bases referenced by the planned tasks."""

    bases: Set[str] = set()
    for task in tasks:
        variations = getattr(task, "variations", ())
        for variation in variations or ():
            var_name = getattr(variation, "name", None)
            if not var_name or var_name == "nominal":
                continue
            base = getattr(variation, "base", None)
            if base:
                bases.add(str(base))
    return bases


def validate_histogram_plan_systematics(
    *,
    metadata: Mapping[str, object],
    tasks: Sequence[object],
    do_systs: bool,
    has_mc_samples: bool,
    has_data_samples: bool,
    tau_analysis: bool,
    metadata_source: str,
) -> None:
    """Ensure the histogram plan variations align with the metadata definition."""

    plan_bases = plan_systematic_bases(tasks)
    expected = expected_systematic_bases(
        metadata,
        has_mc_samples=has_mc_samples,
        has_data_samples=has_data_samples,
        tau_analysis=tau_analysis,
    )

    if not do_systs:
        if plan_bases:
            raise ValueError(
                "Systematic variations were scheduled even though --do-systs is disabled: "
                f"{', '.join(sorted(plan_bases))}."
            )
        return

    if not expected:
        if plan_bases:
            raise ValueError(
                f"Histogram plan requested systematic bases {', '.join(sorted(plan_bases))} "
                "but no metadata variations are expected for this sample selection."
            )
        return

    missing = expected - plan_bases
    if missing:
        raise ValueError(
            "Histogram plan is missing systematic bases "
            f"{', '.join(sorted(missing))} declared in metadata {metadata_source}."
        )

    extra = plan_bases - expected
    if extra:
        raise ValueError(
            "Histogram plan requested unexpected systematic bases "
            f"{', '.join(sorted(extra))} that are not active for this run."
        )


__all__ = [
    "metadata_non_nominal_bases",
    "expected_systematic_bases",
    "plan_systematic_bases",
    "validate_histogram_plan_systematics",
]
