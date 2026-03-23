#!/usr/bin/env python
"""Run a TOPEFT DDR processor-count sweep and summarize transaction activity."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence


DEFAULT_NS = (1, 2, 5, 10, 50, 200, 1000)
DEFAULT_WRAP = "/users/apiccine/work/ChUpdate/codex-run.sh"


@dataclass
class SweepResult:
    n: int
    iteration: int
    return_code: int
    elapsed_seconds: float
    run_dir: Path | None
    category_lines: int
    processing_tokens: int
    accumulating_tokens: int
    transactions_found: bool


def _parse_ns(value: str) -> List[int]:
    values: List[int] = []
    for part in str(value).split(","):
        token = part.strip()
        if not token:
            continue
        try:
            parsed = int(token)
        except ValueError as exc:
            raise ValueError(f"Invalid N value {token!r} in {value!r}.") from exc
        if parsed <= 0:
            raise ValueError(f"N must be > 0, got {parsed}.")
        values.append(parsed)
    if not values:
        raise ValueError("At least one N value must be provided.")
    return values


def _list_run_dirs(root: Path) -> List[Path]:
    if not root.exists():
        return []
    dirs: List[Path] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        if entry.name in {"vine-cache", "most-recent"}:
            continue
        if entry.is_symlink():
            continue
        dirs.append(entry)
    return dirs


def _latest_run_dir(root: Path, before: Sequence[Path]) -> Path | None:
    before_set = {path.resolve() for path in before}
    after = _list_run_dirs(root)
    if not after:
        return None
    fresh = [path for path in after if path.resolve() not in before_set]
    candidates = fresh if fresh else after
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _parse_transactions(path: Path) -> tuple[int, int, int, bool]:
    if not path.exists() or not path.is_file():
        return (0, 0, 0, False)

    category_pattern = re.compile(r"CATEGORY (processing|accumulating)")
    category_lines = 0
    processing_tokens = 0
    accumulating_tokens = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if category_pattern.search(line):
                category_lines += 1
            processing_tokens += line.count("processing#")
            accumulating_tokens += line.count("accumulating#")
    return (category_lines, processing_tokens, accumulating_tokens, True)


def _build_command(*, analysis_dir: Path, options: str, max_processors: int) -> str:
    return (
        f"cd {shlex.quote(str(analysis_dir))} && "
        f"TOPEFT_DDR_DEBUG=1 TOPEFT_DDR_MAX_PROCESSORS={int(max_processors)} "
        f"./full_run.sh --options {shlex.quote(options)}"
    )


def _run_single(
    *,
    wrap: str,
    analysis_dir: Path,
    options: str,
    manager_name: str,
    n: int,
    iteration: int,
    show_run_output: bool,
) -> SweepResult:
    run_root = Path(f"/tmp/topeft/{manager_name}/vine-run-info")
    before = _list_run_dirs(run_root)

    shell_command = _build_command(
        analysis_dir=analysis_dir,
        options=options,
        max_processors=n,
    )
    command = [
        wrap,
        "/bin/bash",
        "--noprofile",
        "--norc",
        "-c",
        shell_command,
    ]
    started = time.time()
    completed = subprocess.run(
        command,
        check=False,
        stdout=None if show_run_output else subprocess.DEVNULL,
        stderr=None if show_run_output else subprocess.DEVNULL,
        text=False,
    )
    elapsed_seconds = time.time() - started

    run_dir = _latest_run_dir(run_root, before)
    category_lines = 0
    processing_tokens = 0
    accumulating_tokens = 0
    transactions_found = False
    if run_dir is not None:
        transactions_path = run_dir / "vine-logs" / "transactions"
        (
            category_lines,
            processing_tokens,
            accumulating_tokens,
            transactions_found,
        ) = _parse_transactions(transactions_path)

    return SweepResult(
        n=n,
        iteration=iteration,
        return_code=completed.returncode,
        elapsed_seconds=elapsed_seconds,
        run_dir=run_dir,
        category_lines=category_lines,
        processing_tokens=processing_tokens,
        accumulating_tokens=accumulating_tokens,
        transactions_found=transactions_found,
    )


def _print_table(results: Iterable[SweepResult]) -> None:
    print(
        "N iteration rc category_lines processing_tokens accumulating_tokens "
        "elapsed_seconds run_info_dir"
    )
    for result in results:
        run_dir_text = str(result.run_dir) if result.run_dir is not None else "<none>"
        print(
            f"{result.n:<5} "
            f"{result.iteration:<9} "
            f"{result.return_code:<2} "
            f"{result.category_lines:<14} "
            f"{result.processing_tokens:<17} "
            f"{result.accumulating_tokens:<19} "
            f"{result.elapsed_seconds:>14.2f} "
            f"{run_dir_text}"
        )


def _default_ns_string() -> str:
    from_env = os.environ.get("TOPEFT_DDR_SWEEP_NS")
    if from_env:
        return from_env
    return ",".join(str(value) for value in DEFAULT_NS)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run repeated full_run.sh DDR scans with different "
            "TOPEFT_DDR_MAX_PROCESSORS values and summarize transactions."
        )
    )
    parser.add_argument(
        "--options",
        default="configs/fullR2_run.yml:cr",
        help="Value forwarded to ./full_run.sh --options.",
    )
    parser.add_argument(
        "--Ns",
        default=_default_ns_string(),
        help=(
            "Comma-separated TOPEFT_DDR_MAX_PROCESSORS values. "
            "Default: 1,2,5,10,50,200,1000 (or TOPEFT_DDR_SWEEP_NS)."
        ),
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=int(os.environ.get("TOPEFT_DDR_SWEEP_REPEAT", "1")),
        help="Number of times to run each N value.",
    )
    parser.add_argument(
        "--manager-name",
        default=f"{os.environ.get('USER', 'user')}-taskvine-coffea",
        help="TaskVine manager name used to locate /tmp/topeft/<manager>/vine-run-info.",
    )
    parser.add_argument(
        "--analysis-dir",
        default=str(Path(__file__).resolve().parents[1]),
        help="Directory containing full_run.sh (default: analysis/topeft_run2).",
    )
    parser.add_argument(
        "--wrap",
        default=os.environ.get("WRAP", DEFAULT_WRAP),
        help="Path to codex-run wrapper.",
    )
    parser.add_argument(
        "--show-run-output",
        action="store_true",
        help="Stream full_run.sh output instead of suppressing it.",
    )
    parser.add_argument(
        "--halt-on-failure",
        action="store_true",
        help="Stop sweep immediately if any run returns a non-zero exit code.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.repeat <= 0:
        raise ValueError("--repeat must be >= 1.")

    ns_values = _parse_ns(args.Ns)
    analysis_dir = Path(args.analysis_dir).expanduser().resolve()
    wrap = str(args.wrap)
    if not analysis_dir.exists():
        raise FileNotFoundError(f"--analysis-dir does not exist: {analysis_dir}")
    if not (analysis_dir / "full_run.sh").exists():
        raise FileNotFoundError(f"Expected full_run.sh in {analysis_dir}")
    if not Path(wrap).exists():
        raise FileNotFoundError(f"--wrap path does not exist: {wrap}")

    print(f"# manager_name={args.manager_name}")
    print(f"# analysis_dir={analysis_dir}")
    print(f"# options={args.options}")
    print(f"# Ns={','.join(str(v) for v in ns_values)}")
    print(f"# repeat={args.repeat}")
    print(f"# show_run_output={int(bool(args.show_run_output))}")

    results: List[SweepResult] = []
    for n in ns_values:
        for iteration in range(1, args.repeat + 1):
            result = _run_single(
                wrap=wrap,
                analysis_dir=analysis_dir,
                options=args.options,
                manager_name=args.manager_name,
                n=n,
                iteration=iteration,
                show_run_output=bool(args.show_run_output),
            )
            results.append(result)
            _print_table([result])
            if args.halt_on_failure and result.return_code != 0:
                print(
                    f"# stopping early due to rc={result.return_code} at N={n}, iteration={iteration}",
                    file=sys.stderr,
                )
                _print_table(results)
                return result.return_code

    print("# sweep_complete")
    _print_table(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
