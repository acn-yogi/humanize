#!/usr/bin/env python3
"""Run docstring_sections.py over every function humanize exports: docstring_sweep.py [--limit N]

Run from the repository root of the result (the installed humanize is the tree under test). One
FAIL line per function that fails its docstring check, with the first reason; one PASS line when
every function passes; exit 1 on any problem. --limit N stops after N failing functions (the
quick check, so the Stop hook answers fast). Used by harness/recurring/docstring-sweep.md.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def targets() -> list[str]:
    humanize = importlib.import_module("humanize")
    out = []
    for name in sorted(getattr(humanize, "__all__", [])):
        obj = getattr(humanize, name, None)
        if inspect.isfunction(obj):
            out.append(f"{obj.__module__}:{name}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="stop after this many failing functions (0: all)")
    a = ap.parse_args()
    names = targets()
    if not names:
        print("FAIL: humanize exports no functions (is humanize installed?)")
        return 1
    failed = 0
    checked = 0
    for t in names:
        r = subprocess.run([sys.executable, str(HERE / "docstring_sections.py"), t], capture_output=True, text=True)
        checked += 1
        if r.returncode != 0:
            failed += 1
            first = next((line for line in r.stdout.splitlines() if line.startswith("FAIL")), r.stdout.strip()[:200] or "no output")
            print(first)
            if a.limit and failed >= a.limit:
                print(f"FAIL: stopped at --limit {a.limit} after {checked} of {len(names)} functions")
                return 1
    if failed:
        print(f"FAIL: {failed} of {len(names)} exported functions fail their docstring check")
        return 1
    print(f"PASS: {len(names)} exported functions carry complete docstrings with examples that run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
