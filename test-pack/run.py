#!/usr/bin/env python3
"""Entry point for the workbench readiness pack.

    python run.py

See README.md for how to add checks and configure environments.
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 9):  # pragma: no cover - ancient images only
    print(
        "test-pack needs Python 3.9 or newer. "
        f"This interpreter is {sys.version.split()[0]} ({sys.executable}).",
        file=sys.stderr,
    )
    raise SystemExit(2)

from testpack.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
