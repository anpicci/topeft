"""topeft wrapper around topcoffea remote environment packaging."""

from __future__ import annotations

import argparse
import importlib
import sys
from typing import Sequence

OK_PREFIX = "[topeft.remote_environment] OK: "
ERROR_PREFIX = "[topeft.remote_environment] ERROR: "


def _resolve_environment_path() -> str:
    remote_environment = importlib.import_module("topcoffea.modules.remote_environment")
    get_environment = getattr(remote_environment, "get_environment", None)
    if not callable(get_environment):
        raise AttributeError(
            "topcoffea.modules.remote_environment does not expose callable get_environment()."
        )
    env_path = get_environment()
    if not env_path:
        raise RuntimeError("Delegated remote_environment returned an empty path.")
    return str(env_path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve/build the TaskVine worker python environment tarball via "
            "topcoffea.modules.remote_environment."
        ),
    )
    parser.add_argument(
        "--print",
        dest="print_mode",
        choices=("path", "status", "both"),
        default="path",
        help=(
            "Output mode: 'path' prints the tarball path to stdout and status to stderr; "
            "'status' prints only status to stderr; 'both' prints status to stdout."
        ),
    )
    return parser


def _emit_success(path: str, *, print_mode: str) -> None:
    status_line = f"{OK_PREFIX}{path}"
    if print_mode == "path":
        print(path, file=sys.stdout, flush=True)
        print(status_line, file=sys.stderr, flush=True)
        return
    if print_mode == "status":
        print(status_line, file=sys.stderr, flush=True)
        return
    if print_mode == "both":
        print(status_line, file=sys.stdout, flush=True)
        return
    raise ValueError(f"Unsupported print mode: {print_mode}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        env_path = _resolve_environment_path()
    except Exception as exc:
        print(f"{ERROR_PREFIX}{exc}", file=sys.stderr, flush=True)
        return 1
    _emit_success(env_path, print_mode=args.print_mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
