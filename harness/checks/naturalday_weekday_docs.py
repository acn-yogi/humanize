#!/usr/bin/env python3
"""Fail-first check for spec 0007: docs/time.md documents naturalday(weekday=True)."""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
REQUIRED = [
    ("weekday=True", "the keyword in an example"),
    ("last ", "the wording used for past days"),
    ("six days", "the width of the window"),
    ("::: humanize.time", "the existing API reference stays"),
]


def main() -> int:
    page = ROOT / "docs" / "time.md"
    text = page.read_text(encoding="utf-8") if page.exists() else ""
    problems = [f"docs/time.md lacks {what} ({needle!r})" for needle, what in REQUIRED if needle not in text]
    if "naturalday" not in text:
        problems.append("docs/time.md never mentions naturalday")
    if text.find("::: humanize.time") != -1 and text.find("weekday=True") > text.find("::: humanize.time"):
        problems.append("the weekday section should come before the API reference")
    for p in problems:
        print(f"FAIL: {p}")
    if not problems:
        print("PASS: docs/time.md documents the weekday option")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
