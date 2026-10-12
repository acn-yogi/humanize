#!/usr/bin/env python3
"""Acceptance check for spec 0004 (issue #184): a humanize command and python -m humanize."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

RUNS = [
    (["naturalsize", "8589934592"], "8.6 GB"),
    (["naturalsize", "--binary", "8589934592"], "8.0 GiB"),
    (["intcomma", "1234567"], "1,234,567"),
]


def main() -> int:
    problems = []
    for args, want in RUNS:
        proc = subprocess.run([sys.executable, "-m", "humanize", *args], capture_output=True, text=True, timeout=30)
        got = proc.stdout.strip()
        if proc.returncode != 0 or got != want:
            problems.append(f"python -m humanize {' '.join(args)} -> exit {proc.returncode}, {got!r}; expected {want!r}")
    scripts = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8")).get("project", {}).get("scripts", {})
    if "humanize" not in scripts:
        problems.append("pyproject.toml has no [project.scripts] humanize entry")
    for p in problems:
        print(f"FAIL: {p}")
    if not problems:
        print(f"PASS: {len(RUNS)} invocations and the console script entry")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
