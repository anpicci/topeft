import os
import sys

import numpy as np


def _diagnostics(prefix_realpath: str, np_path: str) -> str:
    return "\n".join(
        [
            f"numpy.__file__={np.__file__}",
            f"numpy.__version__={np.__version__}",
            f"sys.executable={sys.executable}",
            f"sys.prefix={sys.prefix}",
            f"prefix_realpath={prefix_realpath}",
            f"np_path_realpath={np_path}",
            f"np_path_under_prefix={np_path.startswith(prefix_realpath + os.sep)}",
            f"sys.path[:15]={sys.path[:15]}",
        ]
    )


def test_numpy_import_uses_env_site_packages():
    path = os.path.realpath(np.__file__)
    prefix_realpath = os.path.realpath(sys.prefix)
    disallowed_prefixes = ("/usr/lib", "/usr/lib64", "/cvmfs")
    assert not path.startswith(disallowed_prefixes), (
        "numpy loaded from disallowed system path:\n"
        f"  path={path}\n{_diagnostics(prefix_realpath, path)}"
    )
    assert path.startswith(prefix_realpath + os.sep), (
        "numpy is not coming from the active environment prefix:\n"
        f"  path={path}\n{_diagnostics(prefix_realpath, path)}"
    )
