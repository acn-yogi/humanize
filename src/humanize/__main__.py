"""Allow `python -m humanize`."""

from __future__ import annotations

import sys

from humanize.cli import main

if __name__ == "__main__":
    sys.exit(main())
