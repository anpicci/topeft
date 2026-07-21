"""Resolve and validate requested data-driven analysis products."""

from __future__ import annotations

import copy
import re
import warnings
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from topcoffea.modules.get_param_from_jsons import GetParam
from topcoffea.modules.utils import canonicalize_process_name

from topeft.modules.paths import topeft_path
from topeft.modules.sumw2_policy import resolved_sumw2_policy, sumw2_target


DATA_DRIVEN_PRODUCTS_SCHEMA_VERSION = 1
RESOLVED_DATA_DRIVEN_CONTRACT_VERSION = 1
DATA_DRIVEN_PRODUCT_NAMES = ("nonprompt", "flips")
_PRODUCT_ROLES = {
    "nonprompt": ("data", "prompt_mc"),
    "flips": ("data",),
}
_SELECTOR_FIELDS = frozenset({"process_names", "process_prefixes"})
_PRODUCT_FIELDS = frozenset({"enabled", "source_contributors"})
_NAME_REGEX = re.compile(
    r"^(?P<process>.*?)(?:UL)?(?P<year>(?:\d{2}(?:APV|EE|BPix)?|\d{4}(?:EE|BPix)?))$"
)
_KNOWN_YEARS = frozenset(
    {"16APV", "16", "17", "18", "2022", "2022EE", "2023", "2023BPix"}
)
_get_te_param = GetParam(topeft_path("params/params.json"))
_LEGACY_PROMPT_BASE_NAMES = tuple(
    sorted(set(_get_te_param("prompt_subtraction_samples")))
)


class data_driven_product_error(ValueError):
    """A requested data-driven product cannot be resolved or certified."""


@dataclass(frozen=True)
class normalized_process_selector:
    process_names: tuple[str, ...] = ()
    process_prefixes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, list[str]]:
        output: dict[str, list[str]] = {}
        if self.process_names:
            output["process_names"] = list(self.process_names)
        if self.process_prefixes:
            output["process_prefixes"] = list(self.process_prefixes)
        return output


@dataclass(frozen=True)
class resolved_product:
    enabled: bool
    configured_selectors: tuple[tuple[str, normalized_process_selector], ...]
    source_contributors: tuple[tuple[str, tuple[str, ...]], ...]
    source_datasets: tuple[tuple[str, tuple[str, ...]], ...]
    output_processes: tuple[str, ...]

    def selector_for(self, role: str) -> normalized_process_selector:
        return dict(self.configured_selectors)[role]

    def contributors_for(self, role: str) -> tuple[str, ...]:
        return dict(self.source_contributors)[role]

    def datasets_for(self, role: str) -> tuple[str, ...]:
        return dict(self.source_datasets)[role]

    def required_processes(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    process
                    for _role, processes in self.source_contributors
                    for process in processes
                }
            )
        )


@dataclass(frozen=True)
class resolved_data_driven_products:
    source: str
    metadata_path: str
    runtime_families: tuple[str, ...]
    products: tuple[tuple[str, resolved_product], ...]
    warnings: tuple[str, ...] = ()

    def product(self, name: str) -> resolved_product:
        return dict(self.products)[name]

    def enabled_products(self) -> tuple[str, ...]:
        return tuple(
            name for name, product in self.products if product.enabled
        )

    def requested_provenance(self) -> dict[str, Any]:
        return {
            "schema_version": DATA_DRIVEN_PRODUCTS_SCHEMA_VERSION,
            "source": self.source,
            "products": {
                name: {"enabled": product.enabled}
                for name, product in self.products
            },
            "warnings": list(self.warnings),
        }

    def required_targets(self) -> tuple[sumw2_target, ...]:
        targets = set()
        for family in self.runtime_families:
            for _name, product in self.products:
                if not product.enabled:
                    continue
                process_to_datasets: dict[str, set[str]] = {}
                for role, processes in product.source_contributors:
                    datasets = set(product.datasets_for(role))
                    for process in processes:
                        process_to_datasets.setdefault(process, set()).update(
                            dataset
                            for dataset in datasets
                            if dataset.split("\0", 1)[0] == process
                        )
                for process, datasets in process_to_datasets.items():
                    for encoded_dataset in datasets:
                        _process, dataset = encoded_dataset.split("\0", 1)
                        targets.add(sumw2_target(dataset, process, family))
        family_order = {
            family: index for index, family in enumerate(self.runtime_families)
        }
        return tuple(
            sorted(
                targets,
                key=lambda target: (
                    target.dataset,
                    target.process,
                    family_order[target.family],
                ),
            )
        )


def _parse_process_name(process_name: str) -> tuple[str, str]:
    match = _NAME_REGEX.search(process_name)
    if not match:
        raise data_driven_product_error(
            f"DATA-DRIVEN-E004: process {process_name!r} does not follow the maintained year naming convention."
        )
    base_name = match.group("process")
    year = match.group("year").replace("central", "").replace("UL", "")
    if year not in _KNOWN_YEARS:
        raise data_driven_product_error(
            f"DATA-DRIVEN-E004: process {process_name!r} has unsupported year {year!r}."
        )
    return base_name, year


def generated_process_name(product: str, year: str) -> str:
    if product not in DATA_DRIVEN_PRODUCT_NAMES:
        raise data_driven_product_error(
            f"DATA-DRIVEN-E001: unknown product {product!r}."
        )
    if year not in _KNOWN_YEARS:
        raise data_driven_product_error(
            f"DATA-DRIVEN-E004: unsupported data-driven year {year!r}."
        )
    prefix = product
    raw_name = f"{prefix}{year}" if year.startswith("202") else f"{prefix}UL{year}"
    return canonicalize_process_name(raw_name)


def _require_unique_strings(value: Any, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise data_driven_product_error(
            f"DATA-DRIVEN-E001: {label} must be a nonempty list of strings."
        )
    if any(not isinstance(item, str) or not item for item in value):
        raise data_driven_product_error(
            f"DATA-DRIVEN-E001: {label} entries must be nonempty strings."
        )
    if len(value) != len(set(value)):
        raise data_driven_product_error(
            f"DATA-DRIVEN-E002: {label} contains duplicate selectors."
        )
    return tuple(sorted(value))


def _normalize_selector(raw: Any, *, label: str) -> normalized_process_selector:
    if not isinstance(raw, Mapping):
        raise data_driven_product_error(
            f"DATA-DRIVEN-E001: {label} must be a mapping."
        )
    unknown = sorted(set(raw) - _SELECTOR_FIELDS)
    if unknown:
        raise data_driven_product_error(
            f"DATA-DRIVEN-E001: unknown {label} field(s): {', '.join(unknown)}."
        )
    names = (
        _require_unique_strings(raw["process_names"], label=f"{label}.process_names")
        if "process_names" in raw
        else ()
    )
    prefixes = (
        _require_unique_strings(
            raw["process_prefixes"], label=f"{label}.process_prefixes"
        )
        if "process_prefixes" in raw
        else ()
    )
    if not names and not prefixes:
        raise data_driven_product_error(
            f"DATA-DRIVEN-E001: {label} requires process_names or process_prefixes."
        )
    return normalized_process_selector(names, prefixes)


def _resolve_selector(
    selector: normalized_process_selector,
    *,
    available_processes: Sequence[str],
    label: str,
) -> tuple[str, ...]:
    selector_hits: list[tuple[str, set[str]]] = []
    for name in selector.process_names:
        hits = {process for process in available_processes if process == name}
        if not hits:
            raise data_driven_product_error(
                f"DATA-DRIVEN-E003: {label} process name {name!r} matched nothing."
            )
        selector_hits.append((f"name:{name}", hits))
    for prefix in selector.process_prefixes:
        hits = {
            process for process in available_processes if process.startswith(prefix)
        }
        if not hits:
            raise data_driven_product_error(
                f"DATA-DRIVEN-E003: {label} process prefix {prefix!r} matched nothing."
            )
        selector_hits.append((f"prefix:{prefix}", hits))
    matches_by_process: dict[str, list[str]] = {}
    for selector_name, hits in selector_hits:
        for process in hits:
            matches_by_process.setdefault(process, []).append(selector_name)
    duplicate_matches = {
        process: selectors
        for process, selectors in matches_by_process.items()
        if len(selectors) > 1
    }
    if duplicate_matches:
        raise data_driven_product_error(
            f"DATA-DRIVEN-E002: {label} has ambiguous duplicate resolution: {duplicate_matches}."
        )
    return tuple(sorted(matches_by_process))


def _sample_process_metadata(
    samples: Mapping[str, Mapping[str, Any]],
) -> tuple[tuple[str, ...], dict[str, list[tuple[str, Mapping[str, Any]]]]]:
    by_process: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
    for dataset, sample in samples.items():
        process = sample.get("histAxisName")
        if not isinstance(process, str) or not process:
            raise data_driven_product_error(
                f"DATA-DRIVEN-E004: sample {dataset!r} has invalid histAxisName."
            )
        if not isinstance(sample.get("isData"), bool):
            raise data_driven_product_error(
                f"DATA-DRIVEN-E004: sample {dataset!r} has invalid isData metadata."
            )
        wc_names = sample.get("WCnames")
        if not isinstance(wc_names, list):
            raise data_driven_product_error(
                f"DATA-DRIVEN-E004: sample {dataset!r} has invalid WCnames metadata."
            )
        by_process.setdefault(process, []).append((str(dataset), sample))
    return tuple(sorted(by_process)), by_process


def _validate_role_metadata(
    product_name: str,
    role: str,
    processes: Sequence[str],
    *,
    by_process: Mapping[str, Sequence[tuple[str, Mapping[str, Any]]]],
) -> None:
    for process in processes:
        entries = by_process[process]
        if role == "data":
            invalid = [dataset for dataset, sample in entries if not sample["isData"]]
            if invalid:
                raise data_driven_product_error(
                    f"DATA-DRIVEN-E004: {product_name}.{role} process {process!r} includes non-data datasets {invalid}."
                )
        elif role == "prompt_mc":
            invalid = [
                dataset
                for dataset, sample in entries
                if sample["isData"] or bool(sample["WCnames"])
            ]
            if invalid:
                raise data_driven_product_error(
                    f"DATA-DRIVEN-E004: {product_name}.{role} process {process!r} must be scalar non-EFT MC; invalid datasets={invalid}."
                )


def _implicit_product_configuration(
    *,
    enabled: bool,
    available_processes: Sequence[str],
    by_process: Mapping[str, Sequence[tuple[str, Mapping[str, Any]]]],
) -> dict[str, Any]:
    if not enabled:
        return {
            name: {"enabled": False}
            for name in DATA_DRIVEN_PRODUCT_NAMES
        }
    data_processes = []
    prompt_processes = []
    for process in available_processes:
        base_name, _year = _parse_process_name(process)
        entries = by_process[process]
        if base_name == "data" and all(sample["isData"] for _dataset, sample in entries):
            data_processes.append(process)
        elif (
            base_name in _LEGACY_PROMPT_BASE_NAMES
            and all(
                not sample["isData"] and not sample["WCnames"]
                for _dataset, sample in entries
            )
        ):
            prompt_processes.append(process)
    return {
        "nonprompt": {
            "enabled": True,
            "source_contributors": {
                "data": {"process_names": sorted(data_processes)},
                "prompt_mc": {"process_names": sorted(prompt_processes)},
            },
        },
        "flips": {
            "enabled": True,
            "source_contributors": {
                "data": {"process_names": sorted(data_processes)},
            },
        },
    }


def resolve_data_driven_products(
    data_driven_products: Mapping[str, Any] | None,
    *,
    data_driven_products_present: bool,
    legacy_do_np: bool,
    samples: Mapping[str, Mapping[str, Any]],
    runtime_families: Sequence[str],
    metadata_path: str | None,
) -> resolved_data_driven_products:
    """Resolve explicit or exact legacy-derived product contributors."""

    families = tuple(str(family) for family in runtime_families)
    if len(families) != len(set(families)):
        raise data_driven_product_error(
            "DATA-DRIVEN-E001: runtime histogram families must be unique and ordered."
        )
    available_processes, by_process = _sample_process_metadata(samples)
    product_warnings: list[str] = []
    if data_driven_products_present:
        if not isinstance(data_driven_products, Mapping):
            raise data_driven_product_error(
                "DATA-DRIVEN-E001: data_driven_products must be a mapping."
            )
        unknown_products = sorted(
            set(data_driven_products) - set(DATA_DRIVEN_PRODUCT_NAMES)
        )
        if unknown_products:
            raise data_driven_product_error(
                "DATA-DRIVEN-E001: unknown data_driven_products entries: "
                + ", ".join(unknown_products)
            )
        raw_products = dict(data_driven_products)
        source = "explicit"
    else:
        raw_products = _implicit_product_configuration(
            enabled=legacy_do_np,
            available_processes=available_processes,
            by_process=by_process,
        )
        source = "implicit_legacy_data_driven_default"
        enabled_names = (
            list(DATA_DRIVEN_PRODUCT_NAMES) if legacy_do_np else []
        )
        derived_summary = {
            name: raw_products[name].get("source_contributors", {})
            for name in DATA_DRIVEN_PRODUCT_NAMES
            if raw_products[name]["enabled"]
        }
        message = (
            "DATA-DRIVEN-W001: data_driven_products is absent; derived the exact "
            f"legacy request enabled_products={enabled_names} contributors={derived_summary}. "
            "Add an explicit sibling data_driven_products block to override it; "
            "histogram variables remain controlled only by sumw2_storage."
        )
        product_warnings.append(message)
        warnings.warn(message, UserWarning, stacklevel=2)

    resolved_entries: list[tuple[str, resolved_product]] = []
    for product_name in DATA_DRIVEN_PRODUCT_NAMES:
        raw_product = raw_products.get(product_name, {"enabled": False})
        if not isinstance(raw_product, Mapping):
            raise data_driven_product_error(
                f"DATA-DRIVEN-E001: data_driven_products.{product_name} must be a mapping."
            )
        unknown_fields = sorted(set(raw_product) - _PRODUCT_FIELDS)
        if unknown_fields:
            raise data_driven_product_error(
                f"DATA-DRIVEN-E001: unknown data_driven_products.{product_name} field(s): {', '.join(unknown_fields)}."
            )
        enabled = raw_product.get("enabled")
        if not isinstance(enabled, bool):
            raise data_driven_product_error(
                f"DATA-DRIVEN-E001: data_driven_products.{product_name}.enabled must be boolean."
            )
        source_contributors_raw = raw_product.get("source_contributors")
        if enabled and not isinstance(source_contributors_raw, Mapping):
            raise data_driven_product_error(
                f"DATA-DRIVEN-E001: enabled product {product_name!r} requires source_contributors."
            )
        if source_contributors_raw is None:
            source_contributors_raw = {}
        if not isinstance(source_contributors_raw, Mapping):
            raise data_driven_product_error(
                f"DATA-DRIVEN-E001: {product_name}.source_contributors must be a mapping."
            )
        expected_roles = set(_PRODUCT_ROLES[product_name])
        unknown_roles = sorted(set(source_contributors_raw) - expected_roles)
        missing_roles = sorted(expected_roles - set(source_contributors_raw)) if enabled else []
        if unknown_roles or missing_roles:
            raise data_driven_product_error(
                f"DATA-DRIVEN-E001: invalid {product_name} source roles; missing={missing_roles} unknown={unknown_roles}."
            )
        configured_selectors = []
        resolved_roles = []
        dataset_roles = []
        for role in _PRODUCT_ROLES[product_name]:
            if role not in source_contributors_raw:
                selector = normalized_process_selector()
                matches: tuple[str, ...] = ()
            else:
                selector = _normalize_selector(
                    source_contributors_raw[role],
                    label=f"data_driven_products.{product_name}.source_contributors.{role}",
                )
                matches = _resolve_selector(
                    selector,
                    available_processes=available_processes,
                    label=f"data_driven_products.{product_name}.source_contributors.{role}",
                )
                _validate_role_metadata(
                    product_name,
                    role,
                    matches,
                    by_process=by_process,
                )
            configured_selectors.append((role, selector))
            resolved_roles.append((role, matches))
            encoded_datasets = tuple(
                sorted(
                    f"{process}\0{dataset}"
                    for process in matches
                    for dataset, _sample in by_process[process]
                )
            )
            dataset_roles.append((role, encoded_datasets))
        if product_name == "nonprompt" and enabled:
            data_processes = set(dict(resolved_roles)["data"])
            prompt_processes = set(dict(resolved_roles)["prompt_mc"])
            overlap = sorted(data_processes & prompt_processes)
            if overlap:
                raise data_driven_product_error(
                    f"DATA-DRIVEN-E002: nonprompt data and prompt_mc roles overlap: {overlap}."
                )
        data_processes = dict(resolved_roles).get("data", ())
        output_processes = tuple(
            sorted(
                {
                    generated_process_name(product_name, _parse_process_name(process)[1])
                    for process in data_processes
                }
            )
        ) if enabled else ()
        resolved_entries.append(
            (
                product_name,
                resolved_product(
                    enabled=enabled,
                    configured_selectors=tuple(configured_selectors),
                    source_contributors=tuple(resolved_roles),
                    source_datasets=tuple(dataset_roles),
                    output_processes=output_processes,
                ),
            )
        )
    return resolved_data_driven_products(
        source=source,
        metadata_path=metadata_path or "<command-line/default>",
        runtime_families=families,
        products=tuple(resolved_entries),
        warnings=tuple(product_warnings),
    )


def certify_data_driven_preflight(
    resolved_products: resolved_data_driven_products,
    policy: resolved_sumw2_policy,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Require every source dataset/process/family target before processing."""

    required_targets = set(resolved_products.required_targets())
    selected_targets = set(policy.resolved_targets)
    missing_targets = sorted(required_targets - selected_targets)
    if missing_targets:
        first = missing_targets[0]
        product_names = [
            name
            for name, product in resolved_products.products
            if product.enabled and first.process in product.required_processes()
        ]
        product_name = product_names[0] if product_names else "unknown"
        product = resolved_products.product(product_name)
        family_required = sorted(
            {
                target.process
                for target in required_targets
                if target.family == first.family
            }
        )
        selected_processes = sorted(policy.selected_processes(first.family))
        missing_processes = sorted(set(family_required) - set(selected_processes))
        configured = {
            role: selector.to_dict()
            for role, selector in product.configured_selectors
        }
        raise data_driven_product_error(
            "Cannot produce requested data-driven product "
            f"{product_name!r} for family {first.family!r}. "
            f"metadata_path={resolved_products.metadata_path!r} "
            f"metadata_source={resolved_products.source!r} "
            f"resolved_sumw2_mode={policy.requested_mode!r} "
            f"configured_contributor_selectors={configured} "
            f"resolved_required_contributors={family_required} "
            f"resolved_selected_sumw2_processes={selected_processes} "
            f"missing_contributors={missing_processes} "
            f"missing_dataset_targets={[target.to_dict() for target in missing_targets[:10]]}. "
            "Correct one of: add every missing source process/dataset for every applicable "
            "family to sumw2_storage, modify data_driven_products source_contributors, "
            f"or disable {product_name}."
        )

    requested = resolved_products.requested_provenance()
    families: dict[str, Any] = {}
    for family in resolved_products.runtime_families:
        family_products = {}
        for product_name, product in resolved_products.products:
            source_contributors = {
                role: list(processes)
                for role, processes in product.source_contributors
            }
            required_processes = list(product.required_processes()) if product.enabled else []
            required_family_targets = [
                target.to_dict()
                for target in resolved_products.required_targets()
                if target.family == family
                and target.process in set(required_processes)
            ]
            family_products[product_name] = {
                "enabled": product.enabled,
                "output_processes": list(product.output_processes),
                "source_contributors": source_contributors,
                "required_source_sumw2_processes": required_processes,
                "required_source_sumw2_targets": required_family_targets,
                "requirements_satisfied": True,
            }
        families[family] = family_products
    contract = {
        "contract_version": RESOLVED_DATA_DRIVEN_CONTRACT_VERSION,
        "families": families,
    }
    return requested, contract


def validate_serialized_data_driven_contract(
    requested: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    policy: resolved_sumw2_policy,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the portable requested-product and resolved-family records."""

    if not isinstance(requested, Mapping) or set(requested) != {
        "schema_version",
        "source",
        "products",
        "warnings",
    }:
        raise data_driven_product_error(
            "Invalid requested_data_driven_products fields."
        )
    if requested["schema_version"] != DATA_DRIVEN_PRODUCTS_SCHEMA_VERSION:
        raise data_driven_product_error(
            "Unsupported requested_data_driven_products schema version."
        )
    if requested["source"] not in {
        "explicit",
        "implicit_legacy_data_driven_default",
    }:
        raise data_driven_product_error(
            "Invalid requested_data_driven_products source."
        )
    if not isinstance(requested["warnings"], list) or any(
        not isinstance(item, str) for item in requested["warnings"]
    ):
        raise data_driven_product_error(
            "requested_data_driven_products.warnings must be a string list."
        )
    products = requested["products"]
    if not isinstance(products, Mapping) or list(products) != list(DATA_DRIVEN_PRODUCT_NAMES):
        raise data_driven_product_error(
            "requested_data_driven_products products must use canonical order."
        )
    for product_name, product in products.items():
        if not isinstance(product, Mapping) or set(product) != {"enabled"} or not isinstance(product["enabled"], bool):
            raise data_driven_product_error(
                f"Invalid requested product record for {product_name!r}."
            )
    if not isinstance(contract, Mapping) or set(contract) != {
        "contract_version",
        "families",
    }:
        raise data_driven_product_error("Invalid resolved_data_driven_contract fields.")
    if contract["contract_version"] != RESOLVED_DATA_DRIVEN_CONTRACT_VERSION:
        raise data_driven_product_error(
            "Unsupported resolved_data_driven_contract version."
        )
    families = contract["families"]
    if not isinstance(families, Mapping) or list(families) != list(policy.runtime_histogram_families):
        raise data_driven_product_error(
            "resolved_data_driven_contract families must match runtime family order."
        )
    selected_targets = set(policy.resolved_targets)
    product_fields = {
        "enabled",
        "output_processes",
        "source_contributors",
        "required_source_sumw2_processes",
        "required_source_sumw2_targets",
        "requirements_satisfied",
    }
    for family, family_products in families.items():
        if not isinstance(family_products, Mapping) or list(family_products) != list(DATA_DRIVEN_PRODUCT_NAMES):
            raise data_driven_product_error(
                f"Family {family!r} must contain canonical data-driven products."
            )
        for product_name, product in family_products.items():
            if not isinstance(product, Mapping) or set(product) != product_fields:
                raise data_driven_product_error(
                    f"Invalid resolved product fields for {family}/{product_name}."
                )
            enabled = products[product_name]["enabled"]
            if product["enabled"] is not enabled or product["requirements_satisfied"] is not True:
                raise data_driven_product_error(
                    f"Requested/resolved product mismatch for {family}/{product_name}."
                )
            expected_roles = set(_PRODUCT_ROLES[product_name])
            contributors = product["source_contributors"]
            if not isinstance(contributors, Mapping) or set(contributors) != expected_roles:
                raise data_driven_product_error(
                    f"Invalid contributor roles for {family}/{product_name}."
                )
            for role, processes_for_role in contributors.items():
                if not isinstance(processes_for_role, list) or processes_for_role != sorted(set(processes_for_role)):
                    raise data_driven_product_error(
                        f"Contributor role {family}/{product_name}/{role} must be sorted and unique."
                    )
            required_processes = sorted(
                {
                    process
                    for processes_for_role in contributors.values()
                    for process in processes_for_role
                }
            ) if enabled else []
            if product["required_source_sumw2_processes"] != required_processes:
                raise data_driven_product_error(
                    f"Required source processes disagree with contributor roles for {family}/{product_name}."
                )
            output_processes = product["output_processes"]
            expected_outputs = sorted(
                {
                    generated_process_name(product_name, _parse_process_name(process)[1])
                    for process in contributors.get("data", [])
                }
            ) if enabled else []
            if output_processes != expected_outputs:
                raise data_driven_product_error(
                    f"Generated output labels disagree with source data years for {family}/{product_name}."
                )
            raw_targets = product["required_source_sumw2_targets"]
            if not isinstance(raw_targets, list):
                raise data_driven_product_error(
                    f"Required source targets must be a list for {family}/{product_name}."
                )
            normalized_targets = []
            for raw_target in raw_targets:
                if not isinstance(raw_target, Mapping) or set(raw_target) != {"dataset", "process", "family"}:
                    raise data_driven_product_error(
                        f"Malformed source target for {family}/{product_name}."
                    )
                target = sumw2_target(
                    raw_target["dataset"], raw_target["process"], raw_target["family"]
                )
                if target.family != family or target.process not in required_processes:
                    raise data_driven_product_error(
                        f"Source target disagrees with family/process roles for {family}/{product_name}."
                    )
                normalized_targets.append(target)
            if normalized_targets != sorted(set(normalized_targets)):
                raise data_driven_product_error(
                    f"Source targets must be unique and deterministic for {family}/{product_name}."
                )
            expected_targets = sorted(
                target
                for target in selected_targets
                if target.family == family and target.process in required_processes
            ) if enabled else []
            if normalized_targets != expected_targets:
                raise data_driven_product_error(
                    f"Required source targets disagree with the immutable sumw2 policy for {family}/{product_name}: "
                    f"expected={[target.to_dict() for target in expected_targets]} "
                    f"observed={[target.to_dict() for target in normalized_targets]}."
                )
            missing = sorted(set(normalized_targets) - selected_targets)
            if missing:
                raise data_driven_product_error(
                    f"Resolved source targets are not selected by sumw2 policy for {family}/{product_name}: {[target.to_dict() for target in missing]}."
                )
    return copy.deepcopy(dict(requested)), copy.deepcopy(dict(contract))


def validate_requested_product_input(
    sidecar: Mapping[str, Any],
    *,
    artifact_kind: str,
) -> None:
    """Validate one requested transformation against processor payload content."""

    requested = sidecar.get("requested_data_driven_products")
    contract = sidecar.get("resolved_data_driven_contract")
    if requested is None or contract is None:
        raise data_driven_product_error(
            "Processor artifact lacks the requested data-driven product contract. "
            "Regenerate it with run_analysis and data_driven_products metadata."
        )
    policy = resolved_sumw2_policy_from_sidecar(sidecar)
    validate_serialized_data_driven_contract(requested, contract, policy=policy)
    product_name = "flips" if artifact_kind == "flips_output" else "nonprompt"
    if artifact_kind not in {"nonprompt_output", "flips_output"}:
        raise data_driven_product_error(
            f"Unknown requested transformed artifact kind {artifact_kind!r}."
        )
    if not requested["products"][product_name]["enabled"]:
        raise data_driven_product_error(
            f"Data-driven product {product_name!r} was not requested in the processor sidecar. "
            "Regenerate the processor PKL with the appropriate data_driven_products entry."
        )
    manifest_families = sidecar["sumw2_content_manifest"]["families"]
    for family, family_products in contract["families"].items():
        product = family_products[product_name]
        required = set(product["required_source_sumw2_processes"])
        manifest = manifest_families[family]
        nominal = set(manifest["scalar_nominal_processes"])
        companions = set(manifest["sumw2_processes"])
        missing_nominal = sorted(required - nominal)
        missing_companions = sorted(required - companions)
        if missing_nominal or missing_companions:
            raise data_driven_product_error(
                f"Cannot build requested product {product_name!r}: family={family!r} "
                f"missing_source_nominal={missing_nominal} "
                f"missing_source_sumw2={missing_companions}. Regenerate the processor "
                "artifact after correcting sumw2_storage and data_driven_products."
            )


def resolved_sumw2_policy_from_sidecar(
    sidecar: Mapping[str, Any],
) -> resolved_sumw2_policy:
    from topeft.modules.sumw2_policy import resolved_policy_from_provenance

    return resolved_policy_from_provenance(sidecar["sumw2_storage_provenance"])
