#!/usr/bin/env python3
"""Run the test suite several times and report any test whose result flips: suite_repeat.py [--times 3]

Run from the repository root of the result. Each run is `python -m pytest -q -p no:cacheprovider -rf`;
the failed test ids are read from the summary lines. A test that fails in some runs and passes in
others is flaky; a test that fails in every run is a failure. Prints one FAIL line per problem or
one PASS line, exits 1 on any problem. Used by the recurring maintenance spec
harness/recurring/flaky-test-hunt.md.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

FAILED_RE = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.M)


def run_once() -> tuple[int, set[str]]:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rf", "--no-header"], capture_output=True, text=True)
    return r.returncode, {m.group(1).split(" - ")[0] for m in FAILED_RE.finditer(r.stdout)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--times", type=int, default=3, help="how many full runs (default 3)")
    a = ap.parse_args()
    if a.times < 1:
        print("FAIL: --times must be 1 or more")
        return 1
    runs: list[set[str]] = []
    codes: list[int] = []
    for i in range(a.times):
        rc, failed = run_once()
        codes.append(rc)
        runs.append(failed)
        print(f"run {i + 1} of {a.times}: exit {rc}, {len(failed)} failed")
    seen = set().union(*runs)
    problems = []
    for test in sorted(seen):
        n = sum(test in r for r in runs)
        if n == a.times:
            problems.append(f"{test}: fails in every run")
        else:
            problems.append(f"{test}: flaky, fails in {n} of {a.times} runs")
    for rc_i, rc in enumerate(codes):
        if rc != 0 and not runs[rc_i]:
            problems.append(f"run {rc_i + 1} exited {rc} without naming a failed test (collection error?)")
    for p in problems:
        print(f"FAIL: {p}")
    if not problems:
        print(f"PASS: {a.times} run(s) of the suite agree; no test flipped and none failed")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
