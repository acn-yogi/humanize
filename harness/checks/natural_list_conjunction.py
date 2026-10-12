#!/usr/bin/env python3
"""Acceptance check for spec 0003 (issue #214): natural_list() takes a conjunction."""

from __future__ import annotations

import inspect
import sys

from humanize import natural_list

EXPECT = [
    ((["a", "b", "c"],), {}, "a, b and c"),
    ((["a", "b"],), {}, "a and b"),
    ((["a", "b", "c"],), {"conjunction": "or"}, "a, b or c"),
    ((["a", "b"],), {"conjunction": "or"}, "a or b"),
    ((["a"],), {"conjunction": "or"}, "a"),
    (([],), {"conjunction": "or"}, ""),
    (([1, 2, 3],), {"conjunction": "and also"}, "1, 2 and also 3"),
]


def main() -> int:
    problems = []
    for args, kwargs, want in EXPECT:
        try:
            got = natural_list(*args, **kwargs)
        except TypeError as e:
            problems.append(f"natural_list{args} {kwargs} raised {e}")
            continue
        if got != want:
            problems.append(f"natural_list{args} {kwargs} = {got!r}, expected {want!r}")
    doc = inspect.getdoc(natural_list) or ""
    if "conjunction" not in doc:
        problems.append("the docstring does not document conjunction")
    for p in problems:
        print(f"FAIL: {p}")
    if not problems:
        print(f"PASS: {len(EXPECT)} cases and the docstring")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
