#!/usr/bin/env python3
"""Standalone helper to build data driven histograms from saved metadata.

Quickstart examples:
  - Metadata sidecar: python run_data_driven.py --metadata-json histos/plotsTopEFT_np.pkl.gz.metadata.json \
      --apply-renormfact-envelope
  - Direct pickle paths: python run_data_driven.py --input-pkl histos/plotsTopEFT.pkl.gz \
      --output-pkl histos/plotsTopEFT_np.pkl.gz --apply-renormfact-envelope
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import threading
import time
import tracemalloc
from typing import Any, Dict, Iterable, List, Optional, Tuple

import topcoffea.modules.utils as utils

from topeft.modules.dataDrivenEstimation import DataDrivenProducer
from topeft.modules.get_renormfact_envelope import get_renormfact_envelope


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Finalize deferred nonprompt/flips histograms using the metadata emitted by run_analysis.py.\n\n"
            "Quickstart:\n"
            "  - Metadata sidecar: python run_data_driven.py --metadata-json histos/plotsTopEFT_np.pkl.gz.metadata.json\\\n"
            "      --apply-renormfact-envelope\n"
            "  - Direct pickle paths: python run_data_driven.py --input-pkl histos/plotsTopEFT.pkl.gz\\\n"
            "      --output-pkl histos/plotsTopEFT_np.pkl.gz --apply-renormfact-envelope"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--metadata-json",
        help=(
            "Path to the metadata file created by run_analysis.py when using "
            "--np-postprocess=defer."
        ),
    )
    parser.add_argument(
        "--input-pkl",
        help="Path to the histogram pickle emitted by run_analysis.py (pre data-driven step).",
    )
    parser.add_argument(
        "--output-pkl",
        help="Destination for the histogram pickle with data-driven contributions applied.",
    )
    parser.add_argument(
        "--apply-renormfact-envelope",
        action="store_true",
        help="Also run the renorm/fact envelope step on the output histogram.",
    )
    parser.add_argument(
        "--only-flips",
        action="store_true",
        help="Drop nonprompt processes so only flips contributions remain in the output histograms.",
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=float,
        default=30.0,
        help=(
            "Emit a progress heartbeat while histograms are finalized. "
            "Set to 0 to log every histogram; combine with --quiet to suppress the heartbeat."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Silence progress heartbeats during histogram finalization.",
    )
    parser.add_argument(
        "--mem-report",
        action="store_true",
        help=(
            "Print stage-tagged memory (RSS) usage and periodic memory heartbeats while "
            "processing histograms."
        ),
    )
    parser.add_argument(
        "--mem-tracemalloc",
        action="store_true",
        help=(
            "Also collect and print tracemalloc top allocations at major stages. "
            "Implies --mem-report."
        ),
    )
    parser.add_argument(
        "--mem-top-n",
        type=int,
        default=20,
        help="How many tracemalloc entries to print per stage when --mem-tracemalloc is enabled.",
    )
    parser.add_argument(
        "--iterator-mode",
        action="store_true",
        help=(
            "Use streaming iterator mode: process histograms incrementally and "
            "serialize with a streaming pickle writer."
        ),
    )
    return parser


def _load_metadata(metadata_path: str) -> Dict[str, Any]:
    if not os.path.exists(metadata_path):
        raise FileNotFoundError(f"Metadata file not found: {metadata_path}")
    with open(metadata_path) as metadata_stream:
        payload = json.load(metadata_stream)
    version = payload.get("metadata_version")
    if version != 1:
        raise ValueError(
            f"Unsupported metadata schema version {version!r}. Expected version 1 metadata."
        )
    resolved_years = payload.get("resolved_years")
    sample_years = payload.get("sample_years")
    if resolved_years and sample_years:
        resolved_set = set(resolved_years)
        sample_set = set(sample_years)
        missing = resolved_set - sample_set
        if missing:
            raise ValueError(
                "Metadata contains requested years that are not present in the samples: "
                f"{sorted(missing)}"
            )
    return payload


def _default_output_path(input_path: str) -> str:
    if input_path.endswith(".pkl.gz"):
        base = input_path[:-7]
    elif input_path.endswith(".pkl"):
        base = input_path[:-4]
    else:
        base = input_path
    return f"{base}_np.pkl.gz"


def _resolve_path(
    arg_value: Optional[str],
    metadata_value: Optional[str],
    *,
    metadata_dir: Optional[str] = None,
) -> Optional[str]:
    if arg_value:
        return arg_value
    if not metadata_value:
        return None
    if metadata_dir and not os.path.isabs(metadata_value):
        return os.path.normpath(os.path.join(metadata_dir, metadata_value))
    return os.path.normpath(metadata_value)


def _validate_input_path(input_path: str) -> None:
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Histogram pickle not found: {input_path}")


def _peak_rss_mb() -> float:
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports ru_maxrss in KiB; macOS reports bytes.
    if sys.platform == "darwin":
        return peak_rss / (1024.0 * 1024.0)
    return peak_rss / 1024.0


def _current_rss_mb() -> float:
    try:
        with open("/proc/self/status") as status_stream:
            for line in status_stream:
                if line.startswith("VmRSS:"):
                    fields = line.split()
                    if len(fields) >= 2:
                        return float(fields[1]) / 1024.0
    except OSError:
        pass
    # Fallback when /proc is unavailable.
    return _peak_rss_mb()


class _MemoryReporter:
    def __init__(
        self,
        *,
        enabled: bool,
        include_tracemalloc: bool,
        heartbeat_seconds: float,
        top_n: int,
    ) -> None:
        self.enabled = enabled
        self.include_tracemalloc = include_tracemalloc
        self.heartbeat_seconds = heartbeat_seconds
        self.top_n = max(1, top_n)
        self._stage = "startup"
        self._stage_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if not self.enabled:
            return
        if self.include_tracemalloc and not tracemalloc.is_tracing():
            tracemalloc.start(25)

        interval = self.heartbeat_seconds if self.heartbeat_seconds > 0 else 30.0

        def _heartbeat_worker() -> None:
            while not self._stop_event.wait(interval):
                self._emit(f"heartbeat ({self._get_stage()})", include_top=False)

        self._thread = threading.Thread(
            target=_heartbeat_worker,
            name="run-data-driven-mem-heartbeat",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if not self.enabled:
            return
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if self.include_tracemalloc and tracemalloc.is_tracing():
            tracemalloc.stop()

    def _get_stage(self) -> str:
        with self._stage_lock:
            return self._stage

    def _set_stage(self, stage: str) -> None:
        with self._stage_lock:
            self._stage = stage

    def _emit(self, stage: str, *, include_top: bool) -> None:
        rss_mb = _current_rss_mb()
        peak_mb = _peak_rss_mb()
        print(
            f"[run_data_driven][mem] {stage}: "
            f"rss={rss_mb:.1f} MB peak={peak_mb:.1f} MB"
        )

        if not include_top:
            return
        if not self.include_tracemalloc or not tracemalloc.is_tracing():
            return

        stats = tracemalloc.take_snapshot().statistics("lineno")
        count = min(len(stats), self.top_n)
        print(f"[run_data_driven][mem] top {count} allocations ({stage}):")
        for idx, stat in enumerate(stats[:count], start=1):
            frame = stat.traceback[0]
            print(
                "[run_data_driven][mem]   "
                f"{idx:02d}. {frame.filename}:{frame.lineno} "
                f"{stat.size / (1024.0 * 1024.0):.1f} MB in {stat.count} blocks"
            )

    def mark(self, stage: str, *, include_top: bool = False) -> None:
        if not self.enabled:
            return
        self._set_stage(stage)
        self._emit(stage, include_top=include_top)


def _filter_to_flips(histo: Any) -> Any:
    if histo is None:
        return histo
    process_axis: Optional[Iterable[str]] = None
    try:
        process_axis = list(histo.axes["process"])  # type: ignore[index]
    except Exception:
        process_axis = None
    if not process_axis:
        return histo
    flips = [proc for proc in process_axis if "flips" in proc.lower()]
    if not flips:
        return histo
    to_remove = [proc for proc in process_axis if proc not in flips]
    if not to_remove:
        return histo
    if not hasattr(histo, "remove"):
        return histo
    return histo.remove("process", to_remove)


def _maybe_emit_heartbeat(
    *,
    count: int,
    start_time: float,
    last_heartbeat: float,
    heartbeat_seconds: float,
    quiet: bool,
) -> Tuple[float, bool]:
    if quiet:
        return last_heartbeat, False
    now = time.monotonic()
    if heartbeat_seconds <= 0 or now - last_heartbeat >= heartbeat_seconds:
        elapsed = now - start_time
        print(f"[run_data_driven] Processed {count} histograms after {elapsed:.1f}s...")
        return now, True
    return last_heartbeat, False


def _envelope_single_histogram(key: str, histo: Any) -> Any:
    enveloped = get_renormfact_envelope({key: histo}, verbose=False)
    return enveloped[key]


def _finalize_histograms(
    input_pkl: str,
    output_pkl: str,
    *,
    only_flips: bool,
    apply_envelope: bool,
    iterator_mode: bool,
    heartbeat_seconds: float,
    quiet: bool,
    mem_report: bool,
    mem_tracemalloc: bool,
    mem_top_n: int,
) -> None:
    memory_reporter = _MemoryReporter(
        enabled=(mem_report or mem_tracemalloc),
        include_tracemalloc=mem_tracemalloc,
        heartbeat_seconds=heartbeat_seconds,
        top_n=mem_top_n,
    )
    memory_reporter.start()

    try:
        memory_reporter.mark("start")
        memory_reporter.mark("before DataDrivenProducer(...)")
        ddp = DataDrivenProducer(input_pkl, output_pkl, iterator_mode=iterator_mode)
        memory_reporter.mark("after DataDrivenProducer(...)", include_top=mem_tracemalloc)
        os.makedirs(os.path.dirname(output_pkl) or ".", exist_ok=True)

        start_time = time.monotonic()
        last_heartbeat = start_time
        processed = 0

        if iterator_mode:
            if apply_envelope:
                memory_reporter.mark(
                    "iterator mode: envelope is applied per histogram",
                    include_top=mem_tracemalloc,
                )

            def _iter_output_items():
                nonlocal processed, last_heartbeat
                for key, histo in ddp.iter_data_driven_histograms():
                    processed += 1
                    last_heartbeat, emitted_heartbeat = _maybe_emit_heartbeat(
                        count=processed,
                        start_time=start_time,
                        last_heartbeat=last_heartbeat,
                        heartbeat_seconds=heartbeat_seconds,
                        quiet=quiet,
                    )

                    working_histo = _filter_to_flips(histo) if only_flips else histo
                    if apply_envelope:
                        working_histo = _envelope_single_histogram(key, working_histo)

                    if emitted_heartbeat:
                        memory_reporter.mark(f"processed {processed} histograms")

                    yield key, working_histo
                    del working_histo
                    del histo

            memory_reporter.mark("before dump_dict_streaming()", include_top=mem_tracemalloc)
            utils.dump_dict_streaming(
                output_pkl,
                _iter_output_items(),
                protocol=3,
                clear_memo_interval=1,
            )
            memory_reporter.mark("after dump_dict_streaming()")
        else:
            histograms = ddp.getDataDrivenHistogram()
            memory_reporter.mark("after getDataDrivenHistogram()")

            filtered: Optional[Dict[str, Any]] = {} if only_flips else None
            for key, histo in histograms.items():
                processed += 1
                last_heartbeat, emitted_heartbeat = _maybe_emit_heartbeat(
                    count=processed,
                    start_time=start_time,
                    last_heartbeat=last_heartbeat,
                    heartbeat_seconds=heartbeat_seconds,
                    quiet=quiet,
                )

                if only_flips:
                    assert filtered is not None
                    filtered[key] = _filter_to_flips(histo)

                if emitted_heartbeat:
                    memory_reporter.mark(f"processed {processed} histograms")

            if only_flips:
                assert filtered is not None
                memory_reporter.mark("before only-flips replacement")
                histograms = filtered
                del filtered
                memory_reporter.mark("after only-flips replacement")

            if apply_envelope:
                memory_reporter.mark("before get_renormfact_envelope()", include_top=mem_tracemalloc)
                histograms = get_renormfact_envelope(histograms, verbose=False)
                memory_reporter.mark("after get_renormfact_envelope()", include_top=mem_tracemalloc)

            memory_reporter.mark("before dump_to_pkl()", include_top=mem_tracemalloc)
            utils.dump_to_pkl(output_pkl, histograms)
            memory_reporter.mark("after dump_to_pkl()")

        if not quiet and processed:
            elapsed = time.monotonic() - start_time
            print(f"[run_data_driven] Finalized {processed} histograms in {elapsed:.1f}s.")

        del ddp
    finally:
        memory_reporter.stop()


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_argument_parser()
    args = parser.parse_args(argv)

    metadata: Dict[str, Any] = {}
    metadata_dir: Optional[str] = None
    if args.metadata_json:
        metadata = _load_metadata(args.metadata_json)
        metadata_dir = os.path.dirname(os.path.abspath(args.metadata_json))
        if not metadata.get("do_np", True):
            raise ValueError(
                "Metadata indicates nonprompt estimation was disabled (do_np=False). Nothing to do."
            )

    input_pkl = _resolve_path(
        args.input_pkl, metadata.get("input_histogram"), metadata_dir=metadata_dir
    )
    if not input_pkl:
        raise ValueError("Input histogram path must be provided via --input-pkl or the metadata file.")
    _validate_input_path(input_pkl)

    output_pkl = _resolve_path(
        args.output_pkl, metadata.get("output_histogram"), metadata_dir=metadata_dir
    )
    if not output_pkl:
        output_pkl = _default_output_path(input_pkl)

    _finalize_histograms(
        input_pkl,
        output_pkl,
        only_flips=args.only_flips,
        apply_envelope=args.apply_renormfact_envelope,
        iterator_mode=args.iterator_mode,
        heartbeat_seconds=args.heartbeat_seconds,
        quiet=args.quiet,
        mem_report=args.mem_report,
        mem_tracemalloc=args.mem_tracemalloc,
        mem_top_n=args.mem_top_n,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
