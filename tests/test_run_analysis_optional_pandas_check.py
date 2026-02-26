"""Guard optional pandas checks in run_analysis startup."""

from __future__ import annotations

import os
import subprocess
import sys


def test_run_analysis_module_import_does_not_import_pandas_by_default() -> None:
    env = os.environ.copy()
    env["TOPEFT_IMPORT_CHECK_PANDAS"] = "0"
    env["TOPCOFFEA_IMPORT_CHECK_PANDAS"] = "0"
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import analysis.topeft_run2.run_analysis as _run_analysis; "
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
    assert "Optional pandas ABI check enabled" not in completed.stderr
