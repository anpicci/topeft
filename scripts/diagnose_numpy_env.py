#!/usr/bin/env python3
"""Diagnose NumPy import location and PYTHONPATH contamination.

This checks that NumPy is imported from the active conda environment and not
from system/CVMFS locations that can trigger ABI mismatches. It prints key
environment details and exits non-zero on violations.

Example:
  PYTHONPATH="" PYTHONNOUSERSITE=1 $PYTHON_ENV scripts/diagnose_numpy_env.py
"""

from __future__ import annotations

import os
import sys

def _real(path: str) -> str:
    return os.path.realpath(path)


def _line(label: str, value: object) -> None:
    print(f"{label}={value}")


def main() -> int:
    exe = sys.executable
    prefix = sys.prefix
    exe_real = _real(exe)
    prefix_real = _real(prefix)
    numpy_import_error = None
    try:
        import numpy as np  # pylint: disable=import-error
    except Exception as exc:
        numpy_import_error = f"{type(exc).__name__}: {exc}"
        numpy_version = "(import failed)"
        numpy_file = "(import failed)"
        numpy_real = "(import failed)"
    else:
        numpy_version = np.__version__
        numpy_file = np.__file__
        numpy_real = _real(numpy_file)
    pythonpath = os.environ.get("PYTHONPATH") or "(unset)"

    _line("sys.executable", exe)
    _line("sys.executable_realpath", exe_real)
    _line("sys.prefix", prefix)
    _line("sys.prefix_realpath", prefix_real)
    _line("PYTHONPATH", pythonpath)
    _line("sys.path[:20]", sys.path[:20])
    _line("numpy.__version__", numpy_version)
    _line("numpy.__file__", numpy_file)
    _line("numpy.__file__realpath", numpy_real)

    disallowed_prefixes = ("/usr/lib", "/usr/lib64", "/cvmfs")
    errors: list[str] = []
    if numpy_import_error is not None:
        errors.append(f"numpy import failed ({numpy_import_error})")
    if numpy_import_error is None:
        if numpy_real.startswith(disallowed_prefixes):
            errors.append(
                "numpy loaded from disallowed system path "
                f"(prefixes={disallowed_prefixes}, path={numpy_real})"
            )
        if not numpy_real.startswith(prefix_real + os.sep):
            errors.append(
                "numpy is not under the active sys.prefix "
                f"(prefix={prefix_real}, path={numpy_real})"
            )

    if errors:
        _line("validation", "FAIL")
        for err in errors:
            _line("error", err)
        return 1

    _line("validation", "OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
