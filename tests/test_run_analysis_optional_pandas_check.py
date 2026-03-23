"""Guard optional import checks in run_analysis startup."""

from __future__ import annotations

import os
import subprocess
import sys


def test_run_analysis_module_import_does_not_import_pandas_by_default() -> None:
    env = os.environ.copy()
    env.pop("TOPEFT_IMPORT_CHECK_MODULES", None)
    env["TOPCOFFEA_IMPORT_CHECK_PANDAS"] = "0"
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "from analysis.topeft_run2.run_analysis import _verify_numpy_abi; "
                "_verify_numpy_abi(); "
                "print('PANDAS_LOADED=' + str(int('pandas' in sys.modules)))"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    assert "PANDAS_LOADED=0" in completed.stdout
    assert "Optional import checks enabled" not in completed.stderr
    assert "pandas" not in completed.stderr.lower()


def test_run_analysis_optional_module_check_is_generic() -> None:
    env = os.environ.copy()
    env["TOPEFT_IMPORT_CHECK_MODULES"] = "json"
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from analysis.topeft_run2.run_analysis import _verify_numpy_abi; "
                "_verify_numpy_abi(); "
                "print('OPTIONAL_CHECK_OK=1')"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    assert "OPTIONAL_CHECK_OK=1" in completed.stdout
    assert "Optional import checks enabled via TOPEFT_IMPORT_CHECK_MODULES=json" in completed.stderr
