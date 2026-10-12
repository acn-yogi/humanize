#!/usr/bin/env python3
"""Require that the result changed a path: changed.py <path>...

Compares the result (HEAD) with the base commit in WB_BASE_SHA. Used where a spec asks for a
regression test: the test file must be part of the change.
"""

from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    base = os.environ.get("WB_BASE_SHA", "")
    if not base:
        print("FAIL: WB_BASE_SHA is not set")
        return 1
    out = subprocess.run(["git", "diff", "--name-only", base, "HEAD"], capture_output=True, text=True, check=True).stdout
    changed = set(out.split())
    missing = [p for p in sys.argv[1:] if p not in changed]
    for p in missing:
        print(f"FAIL: {p} is not part of the change")
    if not missing:
        print(f"PASS: the change includes {', '.join(sys.argv[1:])}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
