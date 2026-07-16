"""Metadata-backed channel contracts for missing-parton card production."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from topeft.modules.paths import topeft_path


SR_CHANNEL_CONFIG_KEY = "ALL_CH_LST_SR"
EXPECTED_BASE_CHANNEL_COUNT = 34
EXPECTED_FINAL_CHANNEL_COUNT = 132


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


def _parse_njet_source_label(source_label: str) -> int:
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
    return threshold


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
