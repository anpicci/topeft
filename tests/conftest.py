import os
import sys


def pytest_sessionstart(session):
    if os.environ.get("TOPEFT_DEBUG_IMPORTS") != "1":
        return
    try:
        import numpy as np
    except Exception as exc:  # pragma: no cover - debug-only path
        print(f"TOPEFT_DEBUG_IMPORTS numpy import failed: {exc!r}")
        return
    print(f"TOPEFT_DEBUG_IMPORTS numpy={np.__version__} file={np.__file__}")
    print(f"TOPEFT_DEBUG_IMPORTS python={sys.executable}")
    print(f"TOPEFT_DEBUG_IMPORTS py39_paths={[p for p in sys.path if 'python3.9' in p]}")
