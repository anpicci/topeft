"""topeft wrapper around topcoffea remote environment packaging."""

from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from typing import Dict, Iterable, List, Optional
from typing import Sequence

import topcoffea

OK_PREFIX = "[topeft.remote_environment] OK: "
ERROR_PREFIX = "[topeft.remote_environment] ERROR: "

DEFAULT_EXTRA_PIP_LOCAL: Dict[str, List[str]] = {
    "topeft": ["topeft", "setup.py"],
    "dynamic_data_reduction": ["src", "pyproject.toml"],
}
DEFAULT_EXTRA_CONDA: List[str] = ["pyyaml"]


def _load_delegate_module() -> object:
    remote_environment = topcoffea.import_module("topcoffea.modules.remote_environment")
    get_environment = getattr(remote_environment, "get_environment", None)
    if not callable(get_environment):
        raise AttributeError(
            "topcoffea.modules.remote_environment does not expose callable get_environment()."
        )
    return remote_environment


def _merge_extra_pip_local(
    extra_pip_local: Optional[dict[str, Iterable[str]]],
) -> dict[str, list[str]]:
    merged = deepcopy(DEFAULT_EXTRA_PIP_LOCAL)
    if extra_pip_local:
        for key, value in extra_pip_local.items():
            merged[str(key)] = [str(token) for token in value]
    return merged


def _merge_extra_conda(extra_conda: Optional[Sequence[str]]) -> list[str]:
    merged = list(DEFAULT_EXTRA_CONDA)
    if extra_conda:
        for package in extra_conda:
            pkg = str(package)
            if pkg and pkg not in merged:
                merged.append(pkg)
    return merged


def get_environment(
    *,
    extra_pip_local: dict[str, list[str]] | None = None,
    extra_conda: list[str] | None = None,
    **kwargs: object,
) -> str:
    """Return the distributed environment tarball path for topeft TaskVine runs.

    This is a thin delegate to ``topcoffea.modules.remote_environment`` with
    topeft defaults applied for editable package tracking.
    """

    remote_environment = _load_delegate_module()
    get_environment_fn = getattr(remote_environment, "get_environment")
    env_path = get_environment_fn(
        extra_pip_local=_merge_extra_pip_local(extra_pip_local),
        extra_conda=_merge_extra_conda(extra_conda),
        **kwargs,
    )
    if not env_path:
        raise RuntimeError("Delegated remote_environment returned an empty path.")
    return str(env_path)


def __getattr__(name: str) -> object:
    """Delegate selected attributes (for example ``env_dir_cache``) to topcoffea."""

    remote_environment = _load_delegate_module()
    try:
        return getattr(remote_environment, name)
    except AttributeError as exc:
        raise AttributeError(name) from exc


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
        env_path = get_environment()
    except Exception as exc:
        print(f"{ERROR_PREFIX}{exc}", file=sys.stderr, flush=True)
        return 1
    _emit_success(env_path, print_mode=args.print_mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
