#!/usr/bin/env python3
"""Fail-first check for spec 0006: naturalday(weekday=True) names the past six days "last <weekday>".

Must FAIL on the base commit and PASS on the result.
"""

from __future__ import annotations

import datetime as dt
import sys

from freezegun import freeze_time

from humanize import naturalday, naturaldate

NOW = dt.date(2026, 10, 14)  # a Wednesday

PAST = [
    (-1, "yesterday"),
    (-2, "last Monday"),
    (-3, "last Sunday"),
    (-4, "last Saturday"),
    (-5, "last Friday"),
    (-6, "last Thursday"),
    (-7, "Oct 07"),
    (-40, "Sep 04"),
]
FUTURE = [(2, "Friday"), (6, "Tuesday"), (7, "Oct 21")]


def main() -> int:
    problems = []
    with freeze_time(NOW):
        for days, want in PAST:
            day = NOW + dt.timedelta(days=days)
            try:
                got = naturalday(day, weekday=True)
            except TypeError as e:
                problems.append(f"naturalday({day}, weekday=True) raised {e}")
                continue
            if got != want:
                problems.append(f"naturalday({day}, weekday=True) = {got!r}, expected {want!r}")
            if days < -1 and naturalday(day) == got:
                problems.append(f"the default output for {day} changed to {got!r}")
        for days, want in FUTURE:
            day = NOW + dt.timedelta(days=days)
            try:
                got = naturalday(day, weekday=True)
            except TypeError:
                got = None
            if got != want:
                problems.append(f"future day {day}: got {got!r}, expected {want!r}")
        past_dt = dt.datetime(2026, 10, 11, 8, 0)
        try:
            if naturalday(past_dt, weekday=True) != "last Sunday":
                problems.append("a datetime value is not treated like its date")
        except TypeError:
            problems.append("datetime with weekday=True raised TypeError")
        if naturaldate(NOW - dt.timedelta(days=3)) != "Oct 11":
            problems.append("naturaldate() changed")
    for p in problems:
        print(f"FAIL: {p}")
    if not problems:
        print("PASS: past days within six days read 'last <weekday>', the rest is unchanged")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
