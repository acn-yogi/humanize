#!/usr/bin/env python3
"""Check that pyproject.toml declares the package as typed: the "Typing :: Typed" classifier.

The package ships src/humanize/py.typed, so the classifier is the one missing piece. Run from
the repository root of the result. Fails on today's code. Exit 1 on any problem.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

WANT = "Typing :: Typed"


def main() -> int:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    classifiers = data.get("project", {}).get("classifiers", [])
    problems = []
    if WANT not in classifiers:
        problems.append(f"classifier {WANT!r} is missing from [project] classifiers")
    if not Path("src/humanize/py.typed").exists():
        problems.append("src/humanize/py.typed is missing, so the classifier would be a false claim")
    for p in problems:
        print(f"FAIL: {p}")
    if not problems:
        print(f"PASS: {WANT!r} declared and py.typed shipped")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
