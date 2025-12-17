#!/usr/bin/env python3
"""
quick_check.py

Validate Run-2 output pickle/gzip artifacts by inspecting tuple-keyed histograms
and region_yields using the conventions encoded in the workflow/processor.

Usage:
  python quick_check.py path/to/output.pkl.gz [--max-empty-print N] [--strict-unknown]
"""

from __future__ import annotations

import argparse
import gzip
import sys
from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import cloudpickle

DEFAULT_MAX_EMPTY_PRINT = 10


def smart_load_output(path: str) -> Any:
    """Load an output file by sniffing its magic bytes."""

    with open(path, "rb") as f:
        magic4 = f.read(4)

    if magic4[:2] == b"\x1f\x8b":
        with gzip.open(path, "rb") as fin:
            return cloudpickle.load(fin)

    if magic4 == b"\x04\x22\x4d\x18":
        from coffea.util import load

        return load(path)

    raise RuntimeError(
        f"Unrecognized output format for {path!r}: magic={magic4.hex()} "
        "(expected gzip 1f8b... or lz4 frame 04224d18)."
    )


def _infer_expected_sidecars() -> List[str]:
    """Best-effort inference of non-histogram keys from workflow/processor code."""

    candidates: List[str] = []
    try:
        from analysis.topeft_run2 import analysis_processor

        key = getattr(analysis_processor.AnalysisProcessor, "VARIATION_SUMMARY_KEY", None)
        if key:
            candidates.append(str(key))
        candidates.append("region_yields")
    except Exception:
        candidates.append("region_yields")
    return candidates


def _is_mapping(obj: Any) -> bool:
    return isinstance(obj, MutableMapping) or isinstance(obj, Mapping)


def _inventory_tuple_keys(payload: Mapping[Any, Any]) -> Tuple[List[Tuple[Any, ...]], Dict[str, set]]:
    tuple_keys: List[Tuple[Any, ...]] = []
    uniques = {
        "variable": set(),
        "channel": set(),
        "application": set(),
        "dataset": set(),
        "systematic": set(),
    }

    for key in payload.keys():
        if isinstance(key, tuple) and len(key) == 5:
            tuple_keys.append(key)
            uniques["variable"].add(key[0])
            uniques["channel"].add(key[1])
            uniques["application"].add(key[2])
            uniques["dataset"].add(key[3])
            uniques["systematic"].add(key[4])
    return tuple_keys, uniques


def _dense_empty_info(hist_obj: Any) -> Tuple[Optional[str], Optional[int]]:
    dense = getattr(hist_obj, "_dense_hists", None)
    if isinstance(dense, dict):
        if len(dense) == 0:
            return "dense_map_empty", 0
        nonzero = 0
        total = 0
        for val in dense.values():
            try:
                arr = getattr(val, "values", lambda: val)()
            except Exception:
                arr = val
            try:
                arr_len = len(arr)  # type: ignore[arg-type]
            except Exception:
                arr_len = None
            total += 1 if arr_len is not None else 0
            if arr_len:
                try:
                    if getattr(arr, "sum", lambda: 0)() != 0:
                        nonzero += 1
                except Exception:
                    nonzero += 1
        if total == 0:
            return "dense_map_no_lengths", len(dense)
        if nonzero == 0:
            return "dense_map_all_zero", len(dense)
        return None, len(dense)
    return None, None


def classify_histogram_empty(hist_obj: Any) -> Tuple[str, str]:
    """Return (status, reason) where status is empty/non-empty/unknown."""

    dense_reason, dense_len = _dense_empty_info(hist_obj)
    if dense_reason:
        return "empty", dense_reason
    if dense_len:
        return "non-empty", "dense_map_nonzero"

    # Fallback to values() if present
    values_fn = getattr(hist_obj, "values", None)
    if callable(values_fn):
        try:
            vals = values_fn()
            if isinstance(vals, Mapping):
                if not vals:
                    return "empty", "values_mapping_empty"
                has_nonzero = False
                for payload in vals.values():
                    try:
                        arr = payload[0] if isinstance(payload, tuple) else payload
                        if getattr(arr, "size", None) not in (None, 0):
                            has_nonzero = True
                            break
                    except Exception:
                        continue
                return ("non-empty" if has_nonzero else "empty", "values_mapping_checked")
            else:
                size = getattr(vals, "size", None)
                if size is not None and size > 0:
                    return "non-empty", "values_size>0"
                return "empty", "values_size==0"
        except Exception as exc:
            return "unknown", f"values_failed:{exc}"

    return "unknown", "no_dense_or_values"


def _describe_sidecars(payload: Mapping[Any, Any]) -> List[Tuple[Any, str]]:
    results: List[Tuple[Any, str]] = []
    expected = set(_infer_expected_sidecars())
    for key, value in payload.items():
        if not isinstance(key, tuple):
            label = type(value).__name__
            if key in expected:
                label = f"{label} (expected sidecar)"
            results.append((key, label))
    return results


def _infer_region_schema(region_obj: Any) -> str:
    if not _is_mapping(region_obj) or not region_obj:
        return "unknown"
    sample_key = next(iter(region_obj.keys()))
    if isinstance(sample_key, tuple):
        return f"tuple(len={len(sample_key)})"
    return type(sample_key).__name__


def _region_yields_entries(region_obj: Any) -> Iterable[Tuple[Any, Any]]:
    if _is_mapping(region_obj):
        return region_obj.items()
    return ()


def _has_hist_for(tuple_keys: List[Tuple[Any, ...]], channel: Any, app: Any, dataset: Any, syst: Any) -> bool:
    for var, ch, ap, ds, sy in tuple_keys:
        if ch == channel and ap == app and ds == dataset and sy == syst:
            return True
    return False


def _check_region_yields(payload: Mapping[Any, Any], tuple_keys: List[Tuple[Any, ...]]) -> List[str]:
    missing: List[str] = []
    region_obj = payload.get("region_yields")
    if region_obj is None:
        return missing

    schema = _infer_region_schema(region_obj)
    print(f"[region_yields] detected schema: {schema}")

    for key, value in _region_yields_entries(region_obj):
        try:
            n_events = float(value[0]) if isinstance(value, (list, tuple)) else float(value)
        except Exception:
            n_events = 0.0
        if n_events <= 0:
            continue

        if isinstance(key, tuple) and len(key) >= 4:
            dataset, channel, app, syst = key[0], key[1], key[2], key[3]
        else:
            # Cannot interpret; skip reporting to avoid false positives
            continue

        if not _has_hist_for(tuple_keys, channel, app, dataset, syst):
            missing.append(f"Missing histogram for region_yield key={key!r}")

    return missing


def _print_inventory(tuple_keys: List[Tuple[Any, ...]], uniques: Dict[str, set], sidecars: List[Tuple[Any, str]]) -> None:
    print(f"Histogram entries: {len(tuple_keys)}")
    for name in ("variable", "channel", "application", "dataset", "systematic"):
        vals = sorted(str(v) for v in uniques[name])
        print(f"  {name}s ({len(vals)}): {', '.join(vals[:30])}" + (" ..." if len(vals) > 30 else ""))
    if sidecars:
        print("Sidecar keys (non-tuple):")
        for key, desc in sidecars:
            print(f"  {key!r}: {desc}")
    else:
        print("No sidecar keys detected.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a topeft Run-2 output pickle.")
    parser.add_argument(
        "path",
        nargs="?",
        default="histos/refact_250901_c1_it_test_cr.pkl.gz",
        help="Path to the output file (default: %(default)s).",
    )
    parser.add_argument(
        "--max-empty-print",
        type=int,
        default=DEFAULT_MAX_EMPTY_PRINT,
        help="Print at most N empty histogram diagnostics.",
    )
    parser.add_argument(
        "--strict-unknown",
        action="store_true",
        help="Treat unknown histogram states as failures.",
    )
    args = parser.parse_args()

    out = smart_load_output(args.path)

    if not _is_mapping(out):
        print(f"Loaded object is not a mapping: {type(out)}")
        sys.exit(1)

    tuple_keys, uniques = _inventory_tuple_keys(out)
    sidecars = _describe_sidecars(out)

    _print_inventory(tuple_keys, uniques, sidecars)

    empty_entries: List[Tuple[Tuple[Any, ...], str]] = []
    unknown_entries: List[Tuple[Tuple[Any, ...], str]] = []

    for key in tuple_keys:
        hist_obj = out.get(key)
        status, reason = classify_histogram_empty(hist_obj)
        if status == "empty":
            empty_entries.append((key, reason))
        elif status == "unknown":
            unknown_entries.append((key, reason))

    if empty_entries:
        print(f"Empty histograms detected: {len(empty_entries)}")
        for key, reason in empty_entries[: max(args.max_empty_print, 0)]:
            print(f"  {key}: {reason}")
    else:
        print("No empty histograms detected.")

    if unknown_entries:
        print(f"Unknown histogram states: {len(unknown_entries)}")
        for key, reason in unknown_entries[: max(args.max_empty_print, 0)]:
            print(f"  {key}: {reason}")

    missing_from_region = _check_region_yields(out, tuple_keys)
    if missing_from_region:
        print(f"Region->hist coverage gaps: {len(missing_from_region)}")
        for msg in missing_from_region[: max(args.max_empty_print, 0)]:
            print(f"  {msg}")
    else:
        print("No region_yields coverage gaps detected.")

    fail = False
    if empty_entries:
        fail = True
    if missing_from_region:
        fail = True
    if args.strict_unknown and unknown_entries:
        fail = True

    if fail:
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
