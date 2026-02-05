import os
import sys

import numpy as np


def _diagnostics() -> str:
    return "\n".join(
        [
            f"numpy.__file__={np.__file__}",
            f"numpy.__version__={np.__version__}",
            f"sys.executable={sys.executable}",
            f"sys.prefix={sys.prefix}",
            f"sys.path[:15]={sys.path[:15]}",
        ]
    )


def test_numpy_import_uses_env_site_packages():
    path = os.path.realpath(np.__file__)
    disallowed_prefixes = ("/usr/lib", "/usr/lib64", "/cvmfs")
    assert not path.startswith(disallowed_prefixes), (
        "numpy loaded from disallowed system path:\n"
        f"  path={path}\n{_diagnostics()}"
    )
