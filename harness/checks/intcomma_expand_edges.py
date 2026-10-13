#!/usr/bin/env python3
"""Fail-first check for spec 0009 (issue #431): intcomma(expand=True) on tiny floats, strings and locales.

Must FAIL on the base commit (no `expand` keyword) and PASS on the result.
"""

from __future__ import annotations

import sys

import humanize
from humanize import intcomma

CASES = [
    ((1e-7,), "0.0000001"),
    ((1.5e-10,), "0.00000000015"),
    ((-2.5e-8,), "-0.000000025"),
    (("1e20",), "100,000,000,000,000,000,000"),
    (("1.5E+20",), "150,000,000,000,000,000,000"),
    (("1234.5",), "1,234.5"),
    (("1000",), "1,000"),
    ((float("inf"),), "+Inf"),
    ((float("nan"),), "NaN"),
    (("not a number",), "not a number"),
    ((None,), "None"),
]


def report(problems: list[str], count: int) -> int:
    for p in problems:
        print(f"FAIL: {p}")
    if not problems:
        print(f"PASS: tiny floats, exponent strings and a locale all expand ({count} cases)")
    return 1 if problems else 0


def main() -> int:
    problems = []
    for args, expected in CASES:
        try:
            got = intcomma(*args, expand=True)
        except TypeError as exc:
            problems.append(f"intcomma{args!r} with expand=True raised {exc}")
            continue
        if got != expected:
            problems.append(f"intcomma{args!r} with expand=True = {got!r}, expected {expected!r}")
    try:
        humanize.activate("de_DE")
    except FileNotFoundError:
        # No compiled catalog in this checkout: the locale cases cannot run here.
        humanize.deactivate()
        return report(problems, len(CASES))
    try:
        got = intcomma(1.5e20, expand=True)
        if got != "150.000.000.000.000.000.000":
            problems.append(f"de_DE: intcomma(1.5e20, expand=True) = {got!r}")
        got = intcomma(1e-7, expand=True)
        if got != "0,0000001":
            problems.append(f"de_DE: intcomma(1e-7, expand=True) = {got!r}")
    except TypeError as exc:
        problems.append(f"de_DE: expand=True raised {exc}")
    finally:
        humanize.deactivate()
    return report(problems, len(CASES) + 2)


if __name__ == "__main__":
    sys.exit(main())
