import os

import numpy as np


def test_numpy_import_uses_env_site_packages():
    path = os.path.realpath(np.__file__)
    disallowed_prefixes = ("/usr/lib", "/usr/lib64", "/cvmfs")
    assert not path.startswith(disallowed_prefixes), (
        f"numpy loaded from disallowed system path: {path}"
    )
    assert not np.__version__.startswith("1."), (
        f"unexpected numpy version: {np.__version__}"
    )
