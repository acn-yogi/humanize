#!/usr/bin/env python3
"""A minimal five-field cron matcher for the schedule trigger.

    cron.py due  "<expr>" <tz> [<iso minute>]     -> {"due": true|false, "at": "..."}
    cron.py next "<expr>" <tz> [<count>]          -> JSON list of the next fire times

Fields: minute (0-59), hour (0-23), day of month (1-31), month (1-12), day of week (0-7,
0 and 7 both Sunday). Each field is "*", a number, a range "a-b", a list "a,b,c", or any of
those with a step "/n" ("*/30", "1-5/2"). No names, no "L", "W" or "#": a schedule entry that
needs more than this is a schedule entry a person should look at.

As in cron, when both day of month and day of week are restricted either one matching is
enough. The timezone comes from the entry (tz = "UTC", "Europe/Zurich"); matching is done on
the wall clock in that zone, so an entry fires at 06:00 local through daylight-saving changes.

Standard library only (Python 3.9+ for zoneinfo).
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from zoneinfo import ZoneInfo

BOUNDS = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]
NAMES = ["minute", "hour", "day of month", "month", "day of week"]


class CronError(ValueError):
    pass


def _parse_field(text: str, lo: int, hi: int, name: str) -> set[int]:
    values: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            raise CronError(f"{name}: empty list item in {text!r}")
        step = 1
        if "/" in part:
            part, step_text = part.split("/", 1)
            if not step_text.isdigit() or int(step_text) < 1:
                raise CronError(f"{name}: step must be a whole number of 1 or more in {text!r}")
            step = int(step_text)
        if part == "*":
            start, end = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            if not (a.isdigit() and b.isdigit()):
                raise CronError(f"{name}: range needs two numbers in {text!r}")
            start, end = int(a), int(b)
            if start > end:
                raise CronError(f"{name}: range {part!r} runs backwards")
        elif part.isdigit():
            start = end = int(part)
            if step != 1:
                # "5/15" means from 5 to the top of the range every 15, as in Vixie cron.
                end = hi
        else:
            raise CronError(f"{name}: cannot read {part!r} in {text!r}")
        if start < lo or end > hi:
            raise CronError(f"{name}: {part!r} is outside {lo}-{hi}")
        values.update(range(start, end + 1, step))
    if name == "day of week" and 7 in values:
        values.discard(7)
        values.add(0)
    return values


def parse(expr: str) -> list[set[int]]:
    """The five fields of a cron expression as sets of allowed values."""
    fields = expr.split()
    if len(fields) != 5:
        raise CronError(f"a cron expression has 5 fields, {expr!r} has {len(fields)}")
    return [_parse_field(f, lo, hi, name) for f, (lo, hi), name in zip(fields, BOUNDS, NAMES)]


def matches(expr: str, when: dt.datetime) -> bool:
    """Does the wall-clock minute of `when` (already in the entry's zone) match the expression."""
    minute, hour, dom, month, dow = parse(expr)
    if when.minute not in minute or when.hour not in hour or when.month not in month:
        return False
    dom_star = dom == set(range(1, 32))
    dow_star = dow == set(range(0, 7))
    # Python: Monday is 0; cron: Sunday is 0.
    cron_dow = (when.weekday() + 1) % 7
    dom_ok = when.day in dom
    dow_ok = cron_dow in dow
    if dom_star or dow_star:
        return dom_ok and dow_ok
    return dom_ok or dow_ok


def to_zone(when: dt.datetime, tz: str) -> dt.datetime:
    zone = ZoneInfo(tz)
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when.astimezone(zone).replace(second=0, microsecond=0)


def is_due(expr: str, tz: str, when: dt.datetime) -> bool:
    """True when the minute containing `when` matches, on the wall clock of `tz`."""
    return matches(expr, to_zone(when, tz))


def next_fire(expr: str, tz: str, after: dt.datetime, limit_days: int = 400) -> dt.datetime | None:
    """The first matching minute strictly after `after`, in the entry's zone; None within limit_days."""
    parse(expr)
    t = to_zone(after, tz) + dt.timedelta(minutes=1)
    end = t + dt.timedelta(days=limit_days)
    while t <= end:
        if matches(expr, t):
            return t
        # Skip whole hours and days that cannot match, so a monthly entry is found quickly.
        _, hour, dom, month, _ = parse(expr)
        if t.month not in month:
            t = (t.replace(day=1, hour=0, minute=0) + dt.timedelta(days=32)).replace(day=1)
            continue
        if t.hour not in hour:
            t = t.replace(minute=0) + dt.timedelta(hours=1)
            continue
        t += dt.timedelta(minutes=1)
    return None


def next_fires(expr: str, tz: str, after: dt.datetime, count: int = 3) -> list[dt.datetime]:
    out: list[dt.datetime] = []
    t = after
    for _ in range(count):
        n = next_fire(expr, tz, t)
        if n is None:
            break
        out.append(n)
        t = n
    return out


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[0] in ("due", "next"):
        expr, tz = argv[1], argv[2]
        try:
            if argv[0] == "due":
                when = dt.datetime.fromisoformat(argv[3]) if len(argv) > 3 else dt.datetime.now(dt.timezone.utc)
                local = to_zone(when, tz)
                print(json.dumps({"due": matches(expr, local), "at": local.isoformat(timespec="minutes"), "expr": expr, "tz": tz}))
            else:
                count = int(argv[3]) if len(argv) > 3 else 3
                fires = next_fires(expr, tz, dt.datetime.now(dt.timezone.utc), count)
                print(json.dumps([f.isoformat(timespec="minutes") for f in fires]))
        except (CronError, ValueError) as e:
            print(f"cron.py: {e}", file=sys.stderr)
            return 2
        return 0
    print("usage: cron.py due '<expr>' <tz> [<iso>] | next '<expr>' <tz> [<count>]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
