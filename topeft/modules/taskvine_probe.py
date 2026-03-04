"""topeft entrypoint for topcoffea TaskVine manager probe."""

from __future__ import annotations

import sys
from typing import Sequence


def _delegate_main(argv: Sequence[str] | None = None) -> int:
    import topcoffea

    return int(topcoffea.modules.taskvine_probe.main(argv))


def main(argv: Sequence[str] | None = None) -> int:
    return _delegate_main(argv)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
