"""Metadata-backed channel contracts for missing-parton card production."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from topeft.modules.paths import topeft_path


SUPPORTED_SR_REGISTRIES = (
    "TOP22_006_CH_LST_SR", "TAU_CH_LST_SR", "OFFZ_SPLIT_CH_LST_SR",
    "FWD_CH_LST_SR", "ALL_CH_LST_SR",
)
DEFAULT_SR_REGISTRY = "ALL_CH_LST_SR"
SR_CHANNEL_CONFIG_KEY = DEFAULT_SR_REGISTRY
EXPECTED_BASE_CHANNEL_COUNT = 34
EXPECTED_FINAL_CHANNEL_COUNT = 132
LEGACY_MISSING_PARTON_BRANCH = "tllq"
LEGACY_MISSING_PARTON_BASE_CHANNELS = (
    "2los_onZ_1tau",
    "2lss_4t_m",
    "2lss_4t_p",
    "2lss_fwd_m",
    "2lss_fwd_p",
    "2lss_m_1tau_offZ",
    "2lss_m_1tau_onZ",
    "2lss_m",
    "2lss_p_1tau_offZ",
    "2lss_p_1tau_onZ",
    "2lss_p",
    "3l_1tau_1b",
    "3l_1tau_2b",
    "3l_m_offZ_1b_fwd",
    "3l_m_offZ_2b_fwd",
    "3l_m_offZ_high_1b",
    "3l_m_offZ_high_2b",
    "3l_m_offZ_low_1b",
    "3l_m_offZ_low_2b",
    "3l_m_offZ_none_1b",
    "3l_m_offZ_none_2b",
    "3l_onZ_1b_fwd",
    "3l_onZ_1b",
    "3l_onZ_2b_fwd",
    "3l_onZ_2b",
    "3l_p_offZ_1b_fwd",
    "3l_p_offZ_2b_fwd",
    "3l_p_offZ_high_1b",
    "3l_p_offZ_high_2b",
    "3l_p_offZ_low_1b",
    "3l_p_offZ_low_2b",
    "3l_p_offZ_none_1b",
    "3l_p_offZ_none_2b",
    "4l",
)
LEGACY_MISSING_PARTON_PAYLOAD_LENGTHS = MappingProxyType(
    {
        "2los_onZ_1tau": 4,
        "2lss_4t_m": 8,
        "2lss_4t_p": 8,
        "2lss_fwd_m": 8,
        "2lss_fwd_p": 8,
        "2lss_m_1tau_offZ": 7,
        "2lss_m_1tau_onZ": 7,
        "2lss_m": 8,
        "2lss_p_1tau_offZ": 7,
        "2lss_p_1tau_onZ": 7,
        "2lss_p": 8,
        "3l_1tau_1b": 6,
        "3l_1tau_2b": 6,
        "3l_m_offZ_1b_fwd": 6,
        "3l_m_offZ_2b_fwd": 5,
        "3l_m_offZ_high_1b": 6,
        "3l_m_offZ_high_2b": 6,
        "3l_m_offZ_low_1b": 6,
        "3l_m_offZ_low_2b": 6,
        "3l_m_offZ_none_1b": 6,
        "3l_m_offZ_none_2b": 6,
        "3l_onZ_1b_fwd": 5,
        "3l_onZ_1b": 6,
        "3l_onZ_2b_fwd": 5,
        "3l_onZ_2b": 6,
        "3l_p_offZ_1b_fwd": 6,
        "3l_p_offZ_2b_fwd": 5,
        "3l_p_offZ_high_1b": 6,
        "3l_p_offZ_high_2b": 6,
        "3l_p_offZ_low_1b": 6,
        "3l_p_offZ_low_2b": 6,
        "3l_p_offZ_none_1b": 6,
        "3l_p_offZ_none_2b": 6,
        "4l": 5,
    }
)


@dataclass(frozen=True)
class channel_appl_contract:
    """Exact base/final-channel mappings to their authoritative SR appl labels."""

    base_to_sr_appl: Mapping[str, str]
    final_to_base: Mapping[str, str]

    def base_channel(self, channel: str) -> str:
        channel = str(channel)
        if channel in self.base_to_sr_appl:
            return channel
        if channel in self.final_to_base:
            return self.final_to_base[channel]
        raise ValueError(
            f"Unknown missing-parton channel {channel!r}; it is not defined by "
            f"{SR_CHANNEL_CONFIG_KEY} metadata."
        )

    def expected_sr_appl(self, channel: str) -> str:
        return self.base_to_sr_appl[self.base_channel(channel)]


def normalize_sr_registry(sr_registry: str | None = None) -> str:
    registry = DEFAULT_SR_REGISTRY if sr_registry is None else sr_registry
    if registry not in SUPPORTED_SR_REGISTRIES:
        raise ValueError(f"Unsupported SR registry {registry!r}; expected one of {SUPPORTED_SR_REGISTRIES!r}.")
    return registry


def load_or_validate_selected_registry(sr_registry: str | None = None, config_path=None):
    registry = normalize_sr_registry(sr_registry)
    path = topeft_path("channels/ch_lst.json") if config_path is None else config_path
    with open(path, encoding="utf-8") as handle:
        config = json.load(handle)
    if registry not in config:
        raise ValueError(f"Selected SR registry {registry!r} is absent from {path}.")
    return registry, config[registry]


def parse_sr_njet_token(source_label: str) -> tuple[str, int, str]:
    source_label = str(source_label)
    if not source_label.startswith(("=", ">")):
        raise ValueError(
            f"Unsupported n-jet label {source_label!r} in {SR_CHANNEL_CONFIG_KEY}; "
            "expected an exact '=N' or inclusive '>N' label."
        )
    try:
        threshold = int(source_label[1:])
    except ValueError as exc:
        raise ValueError(
            f"Invalid n-jet threshold {source_label!r} in {SR_CHANNEL_CONFIG_KEY}."
        ) from exc
    if threshold < 0:
        raise ValueError(
            f"Negative n-jet threshold {source_label!r} in {SR_CHANNEL_CONFIG_KEY}."
        )
    return ("exactly" if source_label.startswith("=") else "atleast", threshold, f"_{threshold}j")


def _parse_njet_source_label(source_label: str) -> int:
    return parse_sr_njet_token(source_label)[1]


def _final_channel_name(base_channel: str, source_label: str) -> str:
    threshold = _parse_njet_source_label(source_label)
    return f"{base_channel}_{threshold}j"


def build_channel_appl_contract(
    sr_config: Mapping[str, Mapping[str, object]],
    *,
    expected_base_count: int | None = None,
    expected_final_count: int | None = None,
) -> channel_appl_contract:
    """Build and validate an exact channel-to-SR-application contract."""
    base_to_sr_appl = {}
    final_to_base = {}
    base_sources = {}
    final_sources = {}

    for family, family_config in sr_config.items():
        missing_fields = {
            field
            for field in ("lep_chan_lst", "appl_lst", "jet_lst")
            if field not in family_config
        }
        if missing_fields:
            raise ValueError(
                f"Incomplete {SR_CHANNEL_CONFIG_KEY} metadata for family {family!r}; "
                f"missing fields {sorted(missing_fields)!r}."
            )

        appl_labels = [str(label) for label in family_config["appl_lst"]]
        sr_appl_labels = [label for label in appl_labels if label.startswith("isSR_")]
        if len(sr_appl_labels) != 1:
            raise ValueError(
                f"Family {family!r} in {SR_CHANNEL_CONFIG_KEY} must define exactly one "
                f"authoritative isSR_* appl label; found {sr_appl_labels!r} in "
                f"{appl_labels!r}."
            )
        sr_appl = sr_appl_labels[0]

        jet_labels = [str(label) for label in family_config["jet_lst"]]
        if not jet_labels:
            raise ValueError(
                f"Family {family!r} in {SR_CHANNEL_CONFIG_KEY} has no n-jet labels."
            )

        channel_definitions = family_config["lep_chan_lst"]
        if not channel_definitions:
            raise ValueError(
                f"Family {family!r} in {SR_CHANNEL_CONFIG_KEY} has no channel definitions."
            )

        for channel_definition in channel_definitions:
            if not channel_definition or not str(channel_definition[0]):
                raise ValueError(
                    f"Family {family!r} in {SR_CHANNEL_CONFIG_KEY} contains an empty "
                    "channel definition."
                )
            base_channel = str(channel_definition[0])
            if base_channel in base_to_sr_appl:
                raise ValueError(
                    f"Duplicate base channel {base_channel!r} in {SR_CHANNEL_CONFIG_KEY}: "
                    f"family {base_sources[base_channel]!r} conflicts with family "
                    f"{family!r}."
                )
            base_to_sr_appl[base_channel] = sr_appl
            base_sources[base_channel] = family

            for jet_label in jet_labels:
                final_channel = _final_channel_name(base_channel, jet_label)
                if final_channel in final_to_base:
                    raise ValueError(
                        f"Duplicate final channel {final_channel!r} in "
                        f"{SR_CHANNEL_CONFIG_KEY}: {final_sources[final_channel]!r} "
                        f"conflicts with {(family, base_channel, jet_label)!r}."
                    )
                final_to_base[final_channel] = base_channel
                final_sources[final_channel] = (family, base_channel, jet_label)

    if expected_base_count is not None and len(base_to_sr_appl) != expected_base_count:
        raise ValueError(
            f"Invalid {SR_CHANNEL_CONFIG_KEY} base-channel cardinality: expected "
            f"{expected_base_count}, found {len(base_to_sr_appl)}."
        )
    if expected_final_count is not None and len(final_to_base) != expected_final_count:
        raise ValueError(
            f"Invalid {SR_CHANNEL_CONFIG_KEY} final-channel cardinality: expected "
            f"{expected_final_count}, found {len(final_to_base)}."
        )

    return channel_appl_contract(
        base_to_sr_appl=MappingProxyType(dict(base_to_sr_appl)),
        final_to_base=MappingProxyType(dict(final_to_base)),
    )


def load_missing_parton_channel_contract(
    config_path: str | Path | None = None,
) -> channel_appl_contract:
    """Load the canonical all-analysis SR channel/application contract."""
    if config_path is None:
        config_path = topeft_path("channels/ch_lst.json")
    with open(config_path, encoding="utf-8") as config_stream:
        full_config = json.load(config_stream)
    if SR_CHANNEL_CONFIG_KEY not in full_config:
        raise ValueError(
            f"Missing {SR_CHANNEL_CONFIG_KEY!r} metadata in {str(config_path)!r}."
        )
    return build_channel_appl_contract(
        full_config[SR_CHANNEL_CONFIG_KEY],
        expected_base_count=EXPECTED_BASE_CHANNEL_COUNT,
        expected_final_count=EXPECTED_FINAL_CHANNEL_COUNT,
    )


def _physical_njet_index(final_channel: str) -> int:
    suffix = str(final_channel).rsplit("_", 1)[-1]
    if not suffix.endswith("j"):
        raise ValueError(
            f"Invalid final missing-parton channel {final_channel!r}; "
            "expected a physical '_Nj' suffix."
        )
    try:
        return int(suffix[:-1])
    except ValueError as exc:
        raise ValueError(
            f"Invalid physical njet suffix {suffix!r} for final channel "
            f"{final_channel!r}."
        ) from exc


def legacy_missing_parton_payload_lengths(
    contract: channel_appl_contract | None = None,
) -> Mapping[str, int]:
    """Return the exact public producer length for each base-category TTree."""
    if contract is None:
        contract = load_missing_parton_channel_contract()

    expected_categories = set(LEGACY_MISSING_PARTON_BASE_CHANNELS)
    observed_categories = set(contract.base_to_sr_appl)
    if observed_categories != expected_categories:
        raise ValueError(
            "The metadata-defined SR base categories do not match the public "
            "34-TTree missing-parton contract: "
            f"missing={sorted(expected_categories - observed_categories)!r}, "
            f"unexpected={sorted(observed_categories - expected_categories)!r}."
        )

    for base_channel in LEGACY_MISSING_PARTON_BASE_CHANNELS:
        physical_indices = [
            _physical_njet_index(final_channel)
            for final_channel, mapped_base in contract.final_to_base.items()
            if mapped_base == base_channel
        ]
        if not physical_indices:
            raise ValueError(
                f"No final-channel njet metadata found for legacy base category "
                f"{base_channel!r}."
            )
        payload_length = LEGACY_MISSING_PARTON_PAYLOAD_LENGTHS[base_channel]
        if max(physical_indices) >= payload_length:
            raise ValueError(
                f"Legacy missing-parton array for {base_channel!r} has length "
                f"{payload_length}, but metadata requires physical njet index "
                f"{max(physical_indices)}."
            )
    return LEGACY_MISSING_PARTON_PAYLOAD_LENGTHS


def validate_legacy_missing_parton_values(
    values,
    *,
    base_channel: str,
    expected_length: int,
):
    """Validate one stored fractional-shift array from the public payload."""
    import numpy as np

    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or len(array) != expected_length:
        raise ValueError(
            f"Invalid legacy missing-parton array for {base_channel!r}: expected "
            f"one-dimensional length {expected_length}, found shape={array.shape}."
        )
    if not np.all(np.isfinite(array)):
        nonfinite = np.flatnonzero(~np.isfinite(array)).tolist()
        raise ValueError(
            f"Non-finite legacy missing-parton values for {base_channel!r} at "
            f"indices {nonfinite!r}."
        )
    negative = np.flatnonzero(array < 0.0).tolist()
    if negative:
        raise ValueError(
            f"Negative stored missing-parton fractions for {base_channel!r} at "
            f"indices {negative!r}; no clipping or absolute-value fallback is allowed."
        )
    invalid_kappa = np.flatnonzero(1.0 + array <= 0.0).tolist()
    if invalid_kappa:
        raise ValueError(
            f"Invalid missing-parton consumer kappa values for {base_channel!r} at "
            f"indices {invalid_kappa!r}; kappa_up = 1 + stored_fraction must be positive."
        )
    return array


def validate_legacy_missing_parton_payload(
    payload_path: str | Path,
    *,
    require_key_order: bool = True,
) -> Mapping[str, object]:
    """Validate and read the public 34-TTree ``tllq`` payload schema."""
    import numpy as np
    import uproot

    payload_path = Path(payload_path)
    expected_lengths = legacy_missing_parton_payload_lengths()
    expected_keys = list(LEGACY_MISSING_PARTON_BASE_CHANNELS)

    with uproot.open(payload_path) as payload_file:
        observed_keys = list(payload_file.keys(recursive=False, cycle=False))
        observed_set = set(observed_keys)
        expected_set = set(expected_keys)
        if observed_set != expected_set or len(observed_keys) != len(expected_keys):
            raise ValueError(
                f"Invalid legacy missing-parton key set in {payload_path}: expected "
                f"exactly {len(expected_keys)} base-category TTrees, "
                f"missing={sorted(expected_set - observed_set)!r}, "
                f"unexpected={sorted(observed_set - expected_set)!r}. "
                "The 132-final-channel scalar schema is not compatible."
            )
        if require_key_order and observed_keys != expected_keys:
            raise ValueError(
                f"Non-deterministic legacy missing-parton key order in {payload_path}: "
                f"expected={expected_keys!r}, observed={observed_keys!r}."
            )

        classnames = payload_file.classnames(recursive=False, cycle=False)
        payload_values = {}
        for base_channel in expected_keys:
            classname = classnames.get(base_channel)
            if classname != "TTree":
                raise ValueError(
                    f"Invalid legacy missing-parton object {base_channel!r} in "
                    f"{payload_path}: expected TTree, found {classname!r}. "
                    "Scalar histograms and directory payloads are not compatible."
                )
            tree = payload_file[base_channel]
            branch_names = list(tree.keys())
            if branch_names != [LEGACY_MISSING_PARTON_BRANCH]:
                raise ValueError(
                    f"Invalid branches for legacy missing-parton tree "
                    f"{base_channel!r} in {payload_path}: expected only "
                    f"{LEGACY_MISSING_PARTON_BRANCH!r}, found {branch_names!r}."
                )
            branch = tree[LEGACY_MISSING_PARTON_BRANCH]
            if branch.typename != "double":
                raise ValueError(
                    f"Invalid branch type for {base_channel!r}/"
                    f"{LEGACY_MISSING_PARTON_BRANCH} in {payload_path}: expected "
                    f"'double', found {branch.typename!r}."
                )
            values = np.asarray(branch.array(library="np"), dtype=np.float64)
            payload_values[base_channel] = validate_legacy_missing_parton_values(
                values,
                base_channel=base_channel,
                expected_length=expected_lengths[base_channel],
            )

    return MappingProxyType(payload_values)
