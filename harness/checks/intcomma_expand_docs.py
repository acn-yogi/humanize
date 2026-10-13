#!/usr/bin/env python3
"""Fail-first check for spec 0010 (issue #431): the intcomma docstring and docs/number.md explain expand=True."""

from __future__ import annotations

import inspect
import pathlib
import sys

from humanize import intcomma

ROOT = pathlib.Path(__file__).resolve().parents[2]


def main() -> int:
    problems = []
    doc = inspect.getdoc(intcomma) or ""
    for needle, what in [
        ("expand", "the expand argument in Args"),
        ("expand=True", "an example using expand=True"),
        ("1e+22", "the default exponent output, so the contrast is visible"),
        ("10,000,000,000,000,000,000,000", "the expanded output"),
    ]:
        if needle not in doc:
            problems.append(f"intcomma docstring lacks {what} ({needle!r})")
    page = ROOT / "docs" / "number.md"
    text = page.read_text(encoding="utf-8") if page.exists() else ""
    for needle, what in [
        ("expand=True", "the keyword in an example"),
        ("scientific", "the problem it solves, in words"),
        ("::: humanize.number", "the existing API reference stays"),
    ]:
        if needle not in text:
            problems.append(f"docs/number.md lacks {what} ({needle!r})")
    if "::: humanize.number" in text and text.find("expand=True") > text.find("::: humanize.number"):
        problems.append("the expand section should come before the API reference")
    for p in problems:
        print(f"FAIL: {p}")
    if not problems:
        print("PASS: docstring and docs page explain expand=True")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
