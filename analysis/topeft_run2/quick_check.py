#!/usr/bin/env python3
"""
quick_check.py

Validate Run-2 output artifacts by inspecting tuple-keyed histogram entries and
sidecars like region_yields.

Key behaviors:
- Smart-loads gzip+cloudpickle or lz4+coffea.util.load outputs.
- Inventories tuple keys of the form (variable, channel, application, dataset, systematic).
- Optionally prints all tuple keys (auto when small; or --print-keys).
- Classifies hist emptiness with conservative heuristics (dense map / values()).
- Summarizes value-object types (overall + per variable).
- Checks region_yields coverage: nonzero yields should have at least one histogram key
  for the same (channel, application, dataset, systematic).
- Optional partner check: enforce existence of *_sumw2 partner histograms.

Usage:
  python quick_check.py path/to/output.pkl.gz [options]
"""

from __future__ import annotations

import argparse
import gzip
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping as ABCMapping, MutableMapping as ABCMutableMapping
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import cloudpickle

DEFAULT_MAX_EMPTY_PRINT = 10
DEFAULT_SMALL_LIMIT = 50
DEFAULT_MAX_KEYS_PRINT = 200
DEFAULT_TOTALS_GROUP = "none"

WARN_NUMPY_IMPORT = False
_WARNED_NUMPY_IMPORT = False


# -----------------------------
# Loading / basic helpers
# -----------------------------
def smart_load_output(path: str) -> Any:
    """Load an output file by sniffing its magic bytes."""
    with open(path, "rb") as f:
        magic4 = f.read(4)

    # gzip
    if magic4[:2] == b"\x1f\x8b":
        with gzip.open(path, "rb") as fin:
            return cloudpickle.load(fin)

    # lz4 frame magic
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
    # Use runtime ABCs (collections.abc), not typing.Mapping, for isinstance checks.
    return isinstance(obj, (ABCMutableMapping, ABCMapping))


# -----------------------------
# Key inventory
# -----------------------------
TupleKey = Tuple[Any, Any, Any, Any, Any]


def _inventory_tuple_keys(payload: Mapping[Any, Any]) -> Tuple[List[TupleKey], Dict[str, set]]:
    tuple_keys: List[TupleKey] = []
    uniques: Dict[str, set] = {
        "variable": set(),
        "channel": set(),
        "application": set(),
        "dataset": set(),
        "systematic": set(),
    }

    for key in payload.keys():
        if isinstance(key, tuple) and len(key) == 5:
            tkey: TupleKey = key  # type: ignore[assignment]
            tuple_keys.append(tkey)
            uniques["variable"].add(tkey[0])
            uniques["channel"].add(tkey[1])
            uniques["application"].add(tkey[2])
            uniques["dataset"].add(tkey[3])
            uniques["systematic"].add(tkey[4])

    # Deterministic ordering helps diffing outputs
    tuple_keys.sort(key=lambda k: tuple(str(x) for x in k))
    return tuple_keys, uniques


def _describe_sidecars(payload: Mapping[Any, Any]) -> List[Tuple[Any, str]]:
    results: List[Tuple[Any, str]] = []
    expected = set(_infer_expected_sidecars())
    for key, value in payload.items():
        if not isinstance(key, tuple):
            label = type(value).__name__
            if key in expected:
                label = f"{label} (expected sidecar)"
            results.append((key, label))
    results.sort(key=lambda kv: str(kv[0]))
    return results


# -----------------------------
# Region totals helpers
# -----------------------------
def _parse_region_value(value: Any) -> Tuple[Optional[float], Optional[float]]:
    """Return (n_events, sumw) parsed from a region_yields entry."""

    try:
        try:
            import numpy as np  # type: ignore
        except Exception:
            global _WARNED_NUMPY_IMPORT
            np = None  # type: ignore
            if WARN_NUMPY_IMPORT and not _WARNED_NUMPY_IMPORT:
                print(
                    "WARNING: numpy import failed; using duck-typed region_yields parsing (totals may be incomplete).",
                    file=sys.stderr,
                )
                _WARNED_NUMPY_IMPORT = True

        # Numpy-native handling
        if np is not None and isinstance(value, np.ndarray):
            flat = value.ravel()
            if flat.size >= 2:
                return float(flat[0]), float(flat[1])
            if flat.size == 1:
                return float(flat[0]), None
            return None, None

        if np is not None and isinstance(value, np.generic):
            return None, float(value)

        # Plain python numeric
        if isinstance(value, (int, float)):
            return None, float(value)

        # Plain python sequences
        if isinstance(value, (list, tuple)):
            if len(value) >= 2:
                return float(value[0]), float(value[1])
            if len(value) == 1:
                return float(value[0]), None

        # Duck-typed fallbacks when numpy is unavailable or types differ
        for attr in ("ravel", "flatten"):
            try:
                if hasattr(value, attr):
                    flat = getattr(value, attr)()
                    # Prefer .size if present
                    if hasattr(flat, "size"):
                        size = flat.size  # type: ignore[attr-defined]
                        if size >= 2:
                            return float(flat[0]), float(flat[1])
                        if size == 1:
                            return float(flat[0]), None
                    else:
                        try:
                            size = len(flat)  # type: ignore[arg-type]
                        except Exception:
                            size = None
                        if size is not None:
                            if size >= 2:
                                return float(flat[0]), float(flat[1])
                            if size == 1:
                                return float(flat[0]), None
            except Exception:
                continue

        # Scalar-like with .item()
        try:
            if hasattr(value, "item"):
                scalar = value.item()
                return None, float(scalar)
        except Exception:
            pass

        # Generic indexable sequence (exclude mappings)
        try:
            if not _is_mapping(value) and hasattr(value, "__len__") and hasattr(value, "__getitem__"):
                size = len(value)  # type: ignore[arg-type]
                if size >= 2:
                    return float(value[0]), float(value[1])
                if size == 1:
                    return float(value[0]), None
        except Exception:
            pass

    except Exception:
        return None, None

    return None, None


def _compute_region_totals(region_obj: Any, by: str) -> Dict[str, Any]:
    totals: Dict[str, Any] = {
        "entries": 0,
        "skipped": 0,
        "total_n_events": None,  # Optional[float]
        "total_sumw": None,      # Optional[float]
        "grouped": {},           # Dict[Any, Dict[str, Optional[float]]]
    }
    if not _is_mapping(region_obj):
        return totals

    total_n: Optional[float] = None
    total_w: Optional[float] = None
    grouped: Dict[Any, Dict[str, Optional[float]]] = {}

    for key, value in region_obj.items():
        totals["entries"] += 1
        n_events, sumw = _parse_region_value(value)
        if n_events is None and sumw is None:
            totals["skipped"] += 1
            continue

        if n_events is not None:
            total_n = (total_n or 0.0) + n_events
        if sumw is not None:
            total_w = (total_w or 0.0) + sumw

        if by != "none":
            if isinstance(key, tuple) and len(key) >= 4:
                dataset, channel, app, syst = key[0], key[1], key[2], key[3]
            else:
                dataset = channel = app = syst = None

            if by == "dataset":
                grp_key = dataset
            elif by == "channel":
                grp_key = channel
            elif by == "application":
                grp_key = app
            elif by == "systematic":
                grp_key = syst
            elif by == "all":
                grp_key = (dataset, channel, app, syst)
            else:
                grp_key = None

            if grp_key is not None:
                info = grouped.setdefault(grp_key, {"n_events": None, "sumw": None})
                if n_events is not None:
                    info["n_events"] = (info["n_events"] or 0.0) + n_events
                if sumw is not None:
                    info["sumw"] = (info["sumw"] or 0.0) + sumw

    totals["total_n_events"] = total_n
    totals["total_sumw"] = total_w
    totals["grouped"] = grouped
    return totals


def _print_totals(totals: Dict[str, Any], by: str) -> None:
    print(f"[totals] region_yields entries: {totals['entries']} (skipped: {totals['skipped']})")
    n_events = totals.get("total_n_events")
    sumw = totals.get("total_sumw")
    n_str = "unknown" if n_events is None else f"{n_events}"
    w_str = "unknown" if sumw is None else f"{sumw}"
    print(f"[totals] total_n_events={n_str} total_sumw={w_str}")

    if by != "none":
        grouped = totals.get("grouped") or {}
        for key in sorted(grouped, key=lambda k: str(k)):
            info = grouped[key]
            n = info.get("n_events")
            w = info.get("sumw")
            n_val = "unknown" if n is None else f"{n}"
            w_val = "unknown" if w is None else f"{w}"
            print(f"[totals:{by}] {key}: n_events={n_val} sumw={w_val}")


# -----------------------------
# Histogram emptiness heuristics
# -----------------------------
def _dense_empty_info(hist_obj: Any) -> Tuple[Optional[str], Optional[int]]:
    dense = getattr(hist_obj, "_dense_hists", None)
    if isinstance(dense, dict):
        if len(dense) == 0:
            return "dense_map_empty", 0

        nonzero = 0
        observed = 0
        for val in dense.values():
            try:
                arr = getattr(val, "values", lambda: val)()
            except Exception:
                arr = val

            # Try to decide if this payload is "empty"
            try:
                arr_len = len(arr)  # type: ignore[arg-type]
            except Exception:
                arr_len = None

            if arr_len is None:
                continue

            observed += 1
            if arr_len == 0:
                continue

            # Non-empty length; check sum() if available
            try:
                if getattr(arr, "sum", lambda: 0)() != 0:
                    nonzero += 1
                else:
                    # length nonzero but sum zero is ambiguous; still count as "has content"
                    nonzero += 1
            except Exception:
                nonzero += 1

        if observed == 0:
            return "dense_map_no_lengths", len(dense)
        if nonzero == 0:
            return "dense_map_all_zero", len(dense)
        return None, len(dense)

    return None, None


def classify_histogram_empty(hist_obj: Any) -> Tuple[str, str]:
    """Return (status, reason) where status is 'empty'/'non-empty'/'unknown'."""
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
            if isinstance(vals, ABCMapping):
                if not vals:
                    return "empty", "values_mapping_empty"

                # Try to find any non-empty payload
                for payload in vals.values():
                    try:
                        arr = payload[0] if isinstance(payload, tuple) else payload
                        size = getattr(arr, "size", None)
                        if size is not None:
                            if size > 0:
                                return "non-empty", "values_mapping_has_size>0"
                            continue
                        # If size is missing, try len()
                        if len(arr) > 0:  # type: ignore[arg-type]
                            return "non-empty", "values_mapping_has_len>0"
                    except Exception:
                        continue

                return "empty", "values_mapping_checked_all_empty"

            size = getattr(vals, "size", None)
            if size is not None:
                return ("non-empty" if size > 0 else "empty", "values_size_checked")

            try:
                return ("non-empty" if len(vals) > 0 else "empty", "values_len_checked")  # type: ignore[arg-type]
            except Exception as exc:
                msg = str(exc)
                if msg.strip() in {"()", "( )"}:
                    return "empty", "values_raised_empty_tuple"
                return "unknown", f"values_uninterpretable:{exc}"

        except Exception as exc:
            msg = str(exc)
            if msg.strip() in {"()", "( )"}:
                return "empty", "values_raised_empty_tuple"
            return "unknown", f"values_failed:{exc}"

    return "unknown", "no_dense_or_values"


# -----------------------------
# Diagnostics / summaries
# -----------------------------
def _print_inventory(
    tuple_keys: List[TupleKey],
    uniques: Dict[str, set],
    sidecars: List[Tuple[Any, str]],
) -> None:
    print(f"Histogram entries: {len(tuple_keys)}")
    for name in ("variable", "channel", "application", "dataset", "systematic"):
        vals = sorted(str(v) for v in uniques[name])
        preview = ", ".join(vals[:30])
        if len(vals) > 30:
            preview += " ..."
        print(f"  {name}s ({len(vals)}): {preview}")

    if sidecars:
        print("Sidecar keys (non-tuple):")
        for key, desc in sidecars:
            print(f"  {key!r}: {desc}")
    else:
        print("No sidecar keys detected.")


def _maybe_print_keys(
    tuple_keys: List[TupleKey],
    *,
    print_keys: bool,
    small_limit: int,
    max_keys_print: int,
) -> None:
    should_print = print_keys or (len(tuple_keys) <= small_limit)
    if not should_print:
        return

    n = min(len(tuple_keys), max_keys_print)
    print(f"Tuple keys ({n}/{len(tuple_keys)} shown):")
    for k in tuple_keys[:n]:
        print(f"  {k}")
    if n < len(tuple_keys):
        print(f"  ... (use --max-keys-print {len(tuple_keys)} to show all)")


def _type_name(obj: Any) -> str:
    try:
        return f"{obj.__class__.__module__}.{obj.__class__.__name__}"
    except Exception:
        return type(obj).__name__


def _summarize_value_types(payload: Mapping[Any, Any], tuple_keys: List[TupleKey]) -> None:
    overall: Counter[str] = Counter()
    by_var: Dict[str, Counter[str]] = defaultdict(Counter)

    for k in tuple_keys:
        v = payload.get(k)
        tn = _type_name(v)
        overall[tn] += 1
        by_var[str(k[0])][tn] += 1

    if not overall:
        print("No histogram values to summarize.")
        return

    print("Histogram value types (overall):")
    for t, c in overall.most_common():
        print(f"  {t}: {c}")

    print("Histogram value types (by variable):")
    for var in sorted(by_var.keys()):
        cnt = by_var[var]
        parts = ", ".join(f"{t}={c}" for t, c in cnt.most_common())
        print(f"  {var}: {parts}")


# -----------------------------
# region_yields checks
# -----------------------------
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


def _has_hist_for(
    tuple_keys: Sequence[TupleKey],
    *,
    channel: Any,
    app: Any,
    dataset: Any,
    syst: Any,
) -> bool:
    for _, ch, ap, ds, sy in tuple_keys:
        if ch == channel and ap == app and ds == dataset and sy == syst:
            return True
    return False


def _check_region_yields(payload: Mapping[Any, Any], tuple_keys: List[TupleKey]) -> List[str]:
    missing: List[str] = []
    region_obj = payload.get("region_yields")
    if region_obj is None:
        return missing

    schema = _infer_region_schema(region_obj)
    print(f"[region_yields] detected schema: {schema}")

    for key, value in _region_yields_entries(region_obj):
        n_events, _ = _parse_region_value(value)
        if n_events is None or n_events <= 0:
            continue

        if isinstance(key, tuple) and len(key) >= 4:
            dataset, channel, app, syst = key[0], key[1], key[2], key[3]
        else:
            # Cannot interpret; skip reporting to avoid false positives
            continue

        if not _has_hist_for(tuple_keys, channel=channel, app=app, dataset=dataset, syst=syst):
            missing.append(f"Missing histogram for region_yield key={key!r}")

    return missing


# -----------------------------
# Partner checks: *_sumw2
# -----------------------------
def _build_key_set(tuple_keys: Sequence[TupleKey]) -> set:
    return set(tuple_keys)


def _check_sumw2_partners(
    tuple_keys: List[TupleKey],
    *,
    require_all: bool,
    require_for_vars: Optional[Sequence[str]],
) -> List[str]:
    """
    Partner rule:
      For a base variable "x", expect "x_sumw2" with identical (ch, app, ds, syst).
      For a variable already ending in "_sumw2", expect the base partner as well.
    """
    if not require_all and not require_for_vars:
        return []

    keyset = _build_key_set(tuple_keys)
    missing: List[str] = []

    def want_var(var: str) -> bool:
        if require_all:
            return True
        if not require_for_vars:
            return False
        return var in set(require_for_vars)

    for var, ch, app, ds, syst in tuple_keys:
        var_s = str(var)

        if var_s.endswith("_sumw2"):
            base = var_s[: -len("_sumw2")]
            if want_var(base) and (base, ch, app, ds, syst) not in keyset:
                missing.append(
                    f"Missing base partner for sumw2 variable: ({base!r}, {ch!r}, {app!r}, {ds!r}, {syst!r})"
                )
        else:
            if want_var(var_s) and (f"{var_s}_sumw2", ch, app, ds, syst) not in keyset:
                missing.append(
                    f"Missing sumw2 partner: ({(var_s + '_sumw2')!r}, {ch!r}, {app!r}, {ds!r}, {syst!r})"
                )

    return missing


# -----------------------------
# Main
# -----------------------------
def main() -> None:
    from topeft.modules.logging_config import configure_topeft_logging
    configure_topeft_logging("INFO")

    parser = argparse.ArgumentParser(description="Validate a topeft Run-2 output pickle.")
    parser.add_argument(
        "path",
        nargs="?",
        default="histos/refact_250901_c1_it_test_cr.pkl.gz",
        help="Path to the output file (default: %(default)s).",
    )

    # Printing / verbosity knobs
    parser.add_argument(
        "--print-keys",
        action="store_true",
        help="Print tuple histogram keys (also auto-prints when entries <= --small-limit).",
    )
    parser.add_argument(
        "--small-limit",
        type=int,
        default=DEFAULT_SMALL_LIMIT,
        help="Auto-print tuple keys when the number of entries is <= N.",
    )
    parser.add_argument(
        "--max-keys-print",
        type=int,
        default=DEFAULT_MAX_KEYS_PRINT,
        help="Maximum number of tuple keys to print when printing keys.",
    )

    # Diagnostics knobs
    parser.add_argument(
        "--max-empty-print",
        type=int,
        default=DEFAULT_MAX_EMPTY_PRINT,
        help="Print at most N empty/unknown histogram diagnostics.",
    )
    parser.add_argument(
        "--strict-unknown",
        action="store_true",
        help="Treat unknown histogram states as failures.",
    )
    parser.add_argument(
        "--no-print-totals",
        action="store_true",
        help="Disable totals reporting from region_yields.",
    )
    parser.add_argument(
        "--totals-by",
        choices=["none", "dataset", "channel", "application", "systematic", "all"],
        default=DEFAULT_TOTALS_GROUP,
        help="Group totals by this key when printing region_yields summaries.",
    )
    parser.add_argument(
        "--warn-numpy-import",
        action="store_true",
        help="Emit a warning if numpy import fails; parsing will fall back to duck-typing.",
    )

    # Partner checks
    parser.add_argument(
        "--require-sumw2",
        action="store_true",
        help="Require *_sumw2 partners for ALL variables (and base partners for *_sumw2 vars).",
    )
    parser.add_argument(
        "--require-sumw2-for",
        nargs="*",
        default=None,
        help="Require *_sumw2 partners only for these base variables (space-separated).",
    )

    args = parser.parse_args()

    global WARN_NUMPY_IMPORT
    WARN_NUMPY_IMPORT = bool(args.warn_numpy_import)

    out = smart_load_output(args.path)

    if not _is_mapping(out):
        print(f"Loaded object is not a mapping: {type(out)}")
        sys.exit(1)

    tuple_keys, uniques = _inventory_tuple_keys(out)
    sidecars = _describe_sidecars(out)

    _print_inventory(tuple_keys, uniques, sidecars)
    _maybe_print_keys(
        tuple_keys,
        print_keys=args.print_keys,
        small_limit=args.small_limit,
        max_keys_print=args.max_keys_print,
    )

    _summarize_value_types(out, tuple_keys)

    # Emptiness scan
    empty_entries: List[Tuple[TupleKey, str]] = []
    unknown_entries: List[Tuple[TupleKey, str]] = []

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

    # region_yields coverage
    missing_from_region = _check_region_yields(out, tuple_keys)
    if missing_from_region:
        print(f"Region->hist coverage gaps: {len(missing_from_region)}")
        for msg in missing_from_region[: max(args.max_empty_print, 0)]:
            print(f"  {msg}")
    else:
        print("No region_yields coverage gaps detected.")

    if not args.no_print_totals and "region_yields" in out:
        totals = _compute_region_totals(out.get("region_yields"), args.totals_by)
        _print_totals(totals, args.totals_by)

    # sumw2 partner checks
    sumw2_missing = _check_sumw2_partners(
        tuple_keys,
        require_all=bool(args.require_sumw2),
        require_for_vars=args.require_sumw2_for,
    )
    if sumw2_missing:
        print(f"sumw2 partner gaps: {len(sumw2_missing)}")
        for msg in sumw2_missing[: max(args.max_empty_print, 0)]:
            print(f"  {msg}")
    else:
        if args.require_sumw2 or args.require_sumw2_for:
            print("No sumw2 partner gaps detected.")

    # Determine exit code
    fail = False
    if empty_entries:
        fail = True
    if missing_from_region:
        fail = True
    if sumw2_missing:
        fail = True
    if args.strict_unknown and unknown_entries:
        fail = True

    sys.exit(2 if fail else 0)


if __name__ == "__main__":
    main()
