#!/usr/bin/env python3
"""Fail-first check for spec 0002 (issue #379): precisedelta() keeps the sign of a negative delta.

Must FAIL on the base commit (that is the bug) and PASS on the result. The workbench runs it
on both and records the before and after in the evidence packet.
"""

from __future__ import annotations

import datetime as dt
import sys

from humanize import precisedelta

CASES = [
    (dt.timedelta(seconds=3661), {}),
    (dt.timedelta(days=2, hours=4), {}),
    (dt.timedelta(seconds=3661), {"minimum_unit": "minutes"}),
    (dt.timedelta(milliseconds=1500), {"minimum_unit": "milliseconds"}),
    (dt.timedelta(days=400), {"suppress": ["months"]}),
    (90061, {}),
]


def main() -> int:
    problems = []
    for value, kwargs in CASES:
        positive = precisedelta(value, **kwargs)
        negative = precisedelta(-value, **kwargs)
        if negative != "-" + positive:
            problems.append(f"precisedelta(-{value!r}, {kwargs}) = {negative!r}, expected {'-' + positive!r}")
    zero = precisedelta(dt.timedelta(0))
    if zero.startswith("-"):
        problems.append(f"zero gained a sign: {zero!r}")
    for p in problems:
        print(f"FAIL: {p}")
    if not problems:
        print(f"PASS: the sign survives in all {len(CASES)} cases and zero has none")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
