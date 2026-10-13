#!/usr/bin/env python3
"""Fail-first check for spec 0005: naturalday(weekday=True) names the next six days by weekday.

Must FAIL on the base commit (the keyword does not exist) and PASS on the result.
"""

from __future__ import annotations

import datetime as dt
import sys

from freezegun import freeze_time

from humanize import naturalday

NOW = dt.date(2026, 10, 14)  # a Wednesday

# (days from today, expected with weekday=True)
FUTURE = [
    (0, "today"),
    (1, "tomorrow"),
    (2, "Friday"),
    (3, "Saturday"),
    (4, "Sunday"),
    (5, "Monday"),
    (6, "Tuesday"),
    (7, "Oct 21"),
    (30, "Nov 13"),
]
# Past days and the default stay as they are until spec 0006.
PAST = [(-1, "yesterday"), (-2, "Oct 12"), (-6, "Oct 08")]


def main() -> int:
    problems: list[str] = []
    try:
        check(problems)
    except TypeError as e:
        problems.append(f"naturalday() rejected the weekday keyword: {e}")
    for p in problems:
        print(f"FAIL: {p}")
    if not problems:
        print("PASS: future days within six days are named by weekday, the rest is unchanged")
    return 1 if problems else 0


def check(problems: list[str]) -> None:
    with freeze_time(NOW):
        for days, want in FUTURE:
            day = NOW + dt.timedelta(days=days)
            try:
                got = naturalday(day, weekday=True)
            except TypeError as e:
                problems.append(f"naturalday({day}, weekday=True) raised {e}")
                continue
            if got != want:
                problems.append(f"naturalday({day}, weekday=True) = {got!r}, expected {want!r}")
            as_dt = dt.datetime.combine(day, dt.time(23, 59))
            if naturalday(as_dt, weekday=True) != want:
                problems.append(f"naturalday({as_dt}, weekday=True) differs from the date result {want!r}")
        for days, want in PAST:
            day = NOW + dt.timedelta(days=days)
            got = naturalday(day, weekday=True)
            if got != want:
                problems.append(f"past day {day}: weekday=True gave {got!r}, expected {want!r} for now")
        for days in range(-10, 11):
            day = NOW + dt.timedelta(days=days)
            if naturalday(day) != naturalday(day, weekday=False):
                problems.append(f"weekday=False changed the result for {day}")
        if naturalday(NOW + dt.timedelta(days=2)) != "Oct 16":
            problems.append("the default output changed")
        if naturalday(NOW + dt.timedelta(days=3), "%d/%m", weekday=True) != "Saturday":
            problems.append("format and weekday do not combine")
        if naturalday(NOW + dt.timedelta(days=9), "%d/%m", weekday=True) != "23/10":
            problems.append("format is not used outside the window")
        if naturalday("nope", weekday=True) != "nope":
            problems.append("a non-date value is not returned as a string")


if __name__ == "__main__":
    sys.exit(main())
