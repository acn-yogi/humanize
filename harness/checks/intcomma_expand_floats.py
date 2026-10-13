#!/usr/bin/env python3
"""Fail-first check for spec 0008 (issue #431): intcomma(expand=True) never uses exponent notation for floats.

Must FAIL on the base commit (no `expand` keyword) and PASS on the result. It also pins the default:
without the option, large floats keep today's output.
"""

from __future__ import annotations

import sys

from humanize import intcomma

EXPAND = [
    ((1e16,), "10,000,000,000,000,000"),
    ((1e22,), "10,000,000,000,000,000,000,000"),
    ((1.5e20,), "150,000,000,000,000,000,000"),
    ((-1e17,), "-100,000,000,000,000,000"),
    ((1234.5,), "1,234.5"),
    ((1_234_567.25,), "1,234,567.25"),
    ((1e22, 2), "10,000,000,000,000,000,000,000.00"),
    ((12345, ), "12,345"),
]
DEFAULT = [((1e22,), "1e+22"), ((1.5e20,), "1.5e+20"), ((1234.5,), "1,234.5")]


def main() -> int:
    problems = []
    for args, expected in EXPAND:
        try:
            got = intcomma(*args, expand=True)
        except TypeError as exc:
            problems.append(f"intcomma{args!r} with expand=True raised {exc}")
            continue
        if got != expected:
            problems.append(f"intcomma{args!r} with expand=True = {got!r}, expected {expected!r}")
    for args, expected in DEFAULT:
        got = intcomma(*args)
        if got != expected:
            problems.append(f"default intcomma{args!r} changed: {got!r}, expected {expected!r}")
    for p in problems:
        print(f"FAIL: {p}")
    if not problems:
        print(f"PASS: expand=True writes {len(EXPAND)} cases in full and the default is unchanged")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
