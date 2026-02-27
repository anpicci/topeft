import os
import subprocess
import sys


def test_run2_worker_module_imports_without_analysis_dependency() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = ""

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import topeft.modules.run2.analysis_processor; "
                "loaded = any(m == 'analysis' or m.startswith('analysis.') for m in sys.modules); "
                "print(loaded)"
            ),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "False", proc.stdout
