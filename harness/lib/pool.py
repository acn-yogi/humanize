#!/usr/bin/env python3
"""The budget pool: what the ledger says was spent in the window, and how many tasks still fit.

    pool.py status <harness dir> <ledger.jsonl> [--pool-usd N] [--since ISO] [--now ISO] [--queued N]
        -> JSON {pool, window, spent, left, perTaskCap, fits, canStart, exhausted, since, rows}

    pool.py exhausted-row <harness dir> <ledger.jsonl> [--pool-usd N] [--since ISO] [--queued N]
        -> one ledger row {event: "budget-exhausted", pool, spent, window, leftInQueue, at}

The pool is [triggers.budget] pool_usd (0: no pool, unlimited within the caps); --pool-usd
overrides it for one run. The window says which ledger rows count: "run" (rows at or after
--since, the dispatcher's start), "day", "week" (Monday to Sunday) or "month", on the UTC
calendar. Spent is the sum of costUsd over those rows (every task's row, whatever its outcome).
The per-task cap is caps.max_budget_usd: the dispatcher starts another task only while at
least one cap still fits in what is left, so a task can never be started that the pool cannot
pay for in full. Tasks already running finish within their own caps.

Standard library only (Python 3.11+ for tomllib).
"""

from __future__ import annotations

import datetime as dt
import json
import math
import sys
import tomllib
from pathlib import Path

WINDOWS = ("run", "day", "week", "month")


def window_start(window: str, now: dt.datetime, since: dt.datetime | None) -> dt.datetime | None:
    """The first instant whose ledger rows count. None means every row counts."""
    now = now.astimezone(dt.timezone.utc)
    if window == "run":
        return since
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if window == "day":
        return day
    if window == "week":
        return day - dt.timedelta(days=day.weekday())
    if window == "month":
        return day.replace(day=1)
    raise ValueError(f"window must be one of {', '.join(WINDOWS)}, not {window!r}")


def read_rows(ledger: Path) -> list[dict]:
    rows = []
    if not ledger.exists():
        return rows
    for line in ledger.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def parse_at(value) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        t = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def spent_in(rows: list[dict], start: dt.datetime | None) -> tuple[float, int]:
    """Sum of costUsd over the task rows at or after start (budget-exhausted rows carry no cost)."""
    total, n = 0.0, 0
    for row in rows:
        cost = row.get("costUsd")
        if not isinstance(cost, (int, float)) or isinstance(cost, bool):
            continue
        if start is not None:
            at = parse_at(row.get("at"))
            if at is None or at < start:
                continue
        total += float(cost)
        n += 1
    return round(total, 6), n


def status(config: dict, rows: list[dict], pool_override: float | None, since: dt.datetime | None,
           now: dt.datetime | None = None, queued: int = 0) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    budget = (config.get("triggers") or {}).get("budget") or {}
    pool = float(pool_override) if pool_override is not None else float(budget.get("pool_usd", 0) or 0)
    if pool < 0:
        raise ValueError("pool_usd cannot be negative")
    window = str(budget.get("window", "run"))
    if window not in WINDOWS:
        raise ValueError(f"window must be one of {', '.join(WINDOWS)}, not {window!r}")
    cap = float(config["caps"]["max_budget_usd"])
    if cap <= 0:
        raise ValueError("caps.max_budget_usd must be positive")
    start = window_start(window, now, since)
    spent, n = spent_in(rows, start)
    if pool == 0:
        return {"pool": 0, "window": window, "spent": spent, "left": None, "perTaskCap": cap, "fits": None,
                "canStart": True, "exhausted": False, "unlimited": True, "since": start.isoformat() if start else None,
                "rows": n, "queued": queued,
                "line": f"pool: none (pool_usd = 0): unlimited within the caps, ${cap:.2f} per task"}
    left = round(max(0.0, pool - spent), 6)
    fits = int(math.floor(left / cap + 1e-9))
    return {"pool": pool, "window": window, "spent": spent, "left": left, "perTaskCap": cap, "fits": fits,
            "canStart": fits >= 1, "exhausted": fits < 1, "unlimited": False,
            "since": start.isoformat() if start else None, "rows": n, "queued": queued,
            "line": f"pool: ${pool:.2f} (window {window}), spent ${spent:.2f} over {n} task(s), left ${left:.2f}, "
                    f"per-task cap ${cap:.2f}: {fits} more task(s) fit"}


def exhausted_row(st: dict, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    return {"event": "budget-exhausted", "pool": st["pool"], "spent": st["spent"], "window": st["window"],
            "leftInQueue": int(st.get("queued") or 0), "perTaskCap": st["perTaskCap"],
            "at": now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def _opt(rest: list[str], name: str) -> str | None:
    if name in rest:
        i = rest.index(name)
        value = rest[i + 1]
        del rest[i:i + 2]
        return value
    return None


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[0] not in ("status", "exhausted-row"):
        print("usage: pool.py status|exhausted-row <harness> <ledger> [--pool-usd N] [--since ISO] [--now ISO] [--queued N]", file=sys.stderr)
        return 2
    try:
        config = tomllib.loads((Path(argv[1]) / "config.toml").read_text(encoding="utf-8"))
        rest = argv[3:]
        pool = _opt(rest, "--pool-usd")
        since = _opt(rest, "--since")
        now = _opt(rest, "--now")
        queued = _opt(rest, "--queued")
        st = status(config, read_rows(Path(argv[2])), float(pool) if pool is not None else None,
                    parse_at(since) if since else None, parse_at(now) if now else None, int(queued or 0))
        print(json.dumps(st if argv[0] == "status" else exhausted_row(st, parse_at(now) if now else None)))
    except (ValueError, KeyError, OSError, IndexError) as e:
        print(f"pool.py: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
