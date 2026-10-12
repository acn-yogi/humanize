#!/usr/bin/env python3
"""Acceptance check for spec 0001 (issue #430): a contributor page on running the tests.

    docs_testing.py [--no-run]

Run from the repository root of the result. Checks that docs/testing.md exists, is in the
mkdocs nav, covers each point the issue asks for, and that every pytest command it tells a
contributor to run actually runs and passes here (no network). --no-run skips that last part,
for the quick check the Stop hook runs while Claude is still working.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path

PAGE = Path("docs/testing.md")
MAX_COMMANDS = 8

# Each point from the issue, and the evidence on the page that it is covered.
POINTS = {
    "how to install the test dependencies": [r"\[tests\]"],
    "how to run the complete test suite": [r"(^|\s)(python -m )?pytest(\s*$|\s+-q\s*$)"],
    "how to run a specific test file": [r"pytest\s+(-\S+\s+)*tests/test_\w+\.py"],
    "how to run a focused test with -k": [r"pytest\s.*-k\s"],
    "why some tests may be skipped": [r"skip", r"msgfmt|gettext|\.mo\b|translation"],
    "where the CI test configuration lives": [r"\.github/workflows/test\.yml"],
}


def code_lines(text: str) -> list[str]:
    """Lines inside fenced code blocks, with a leading '$ ' prompt removed."""
    lines, inside = [], False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            inside = not inside
            continue
        if inside:
            lines.append(re.sub(r"^\s*\$\s+", "", line).strip())
    return lines


def main() -> int:
    run = "--no-run" not in sys.argv[1:]
    problems: list[str] = []

    if not PAGE.is_file():
        print(f"FAIL: {PAGE} does not exist")
        return 1
    text = PAGE.read_text(encoding="utf-8")

    nav = Path("mkdocs.yml").read_text(encoding="utf-8")
    if not re.search(r"^\s*-\s*[^:\n]+:\s*testing\.md\s*$", nav, re.M):
        problems.append("mkdocs.yml nav has no entry for testing.md")

    for point, patterns in POINTS.items():
        missing = [p for p in patterns if not re.search(p, text, re.I | re.M)]
        if missing:
            problems.append(f"does not cover: {point} (looked for {', '.join(missing)})")

    commands = [c for c in code_lines(text) if re.match(r"^(python -m )?pytest(\s|$)", c)]
    if not commands:
        problems.append("no pytest command in a fenced code block")
    if run:
        for cmd in commands[:MAX_COMMANDS]:
            argv = shlex.split(cmd)
            if argv[0] == "pytest":
                argv = ["python", "-m", *argv]
            argv += ["-p", "no:cacheprovider"]
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=180)
            # 5 is pytest's "no tests collected": a -k example that matches nothing is wrong.
            status = "ok" if proc.returncode == 0 else f"exit {proc.returncode}"
            print(f"documented command: {cmd}  ->  {status}")
            if proc.returncode != 0:
                tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-5:])
                problems.append(f"documented command fails: {cmd}\n{tail}")

    for p in problems:
        print(f"FAIL: {p}")
    if not problems:
        print(f"PASS: {PAGE} covers all {len(POINTS)} points" + (f" and its {len(commands)} pytest commands run" if run else ""))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
