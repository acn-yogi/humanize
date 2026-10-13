#!/usr/bin/env python3
"""The ticket watch: which of the fork's issues start work, and why each one does or does not.

    tickets.py evaluate <harness dir> <specs dir> <ledger.jsonl> --issues <issues.json> --timelines <dir>
        -> JSON list, one row per issue: {number, title, url, matched, action, reason, approver, trigger}

The caller (harness/bin/watch-tickets.sh) fetches the issues and each issue's timeline from the
fork with gh; this module only decides. The rules, in the order they are applied:

  1. Pull requests are not tickets (GitHub's issues API lists both).
  2. The issue is open and carries [triggers.ticket] label.
  3. The label was last added by a login in [triggers.ticket] approvers (the issue's timeline:
     the last "labeled" event for that label, with no "unlabeled" after it). Their adding it is
     the approval; a label added by anyone else is a request, not an approval, and starts nothing.
  4. One issue, one task: trigger = "ticket:<number>" already in a spec's front matter or a ledger
     row means it ran. A "reopened" event later than that spec or row makes the issue count again.

Standard library only (Python 3.11+ for tomllib).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import tomllib
from pathlib import Path


def parse_at(value) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        t = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t


def ticket_config(config: dict) -> dict:
    t = dict((config.get("triggers") or {}).get("ticket") or {})
    t.setdefault("enabled", False)
    t.setdefault("source", "github")
    t.setdefault("label", "priority:high")
    t.setdefault("approvers", [])
    t.setdefault("poll_minutes", 5)
    t.setdefault("comment", False)
    if not isinstance(t["approvers"], list) or not all(isinstance(a, str) for a in t["approvers"]):
        raise ValueError("[triggers.ticket] approvers must be a list of logins")
    if not isinstance(t["label"], str) or not t["label"]:
        raise ValueError("[triggers.ticket] label must be a non-empty string")
    return t


def label_added_by(timeline: list[dict], label: str) -> tuple[str | None, str | None]:
    """(login, at) of the last 'labeled' event for the label with no 'unlabeled' after it; (None, None) otherwise."""
    who, at = None, None
    for ev in timeline:
        if not isinstance(ev, dict) or (ev.get("label") or {}).get("name") != label:
            continue
        if ev.get("event") == "labeled":
            who, at = (ev.get("actor") or {}).get("login"), ev.get("created_at")
        elif ev.get("event") == "unlabeled":
            who, at = None, None
    return who, at


def last_reopened(timeline: list[dict]) -> dt.datetime | None:
    times = [parse_at(ev.get("created_at")) for ev in timeline if isinstance(ev, dict) and ev.get("event") == "reopened"]
    times = [t for t in times if t]
    return max(times) if times else None


def seen_triggers(specs_dir: Path, ledger: Path | None) -> dict[str, dt.datetime | None]:
    """trigger -> the latest time it was taken (a spec's triggered_at or a ledger row's at)."""
    seen: dict[str, dt.datetime | None] = {}

    def note(trigger, when) -> None:
        if not isinstance(trigger, str):
            return
        t = parse_at(when)
        if trigger not in seen or (t and (seen[trigger] is None or t > seen[trigger])):
            seen[trigger] = t

    for p in sorted(specs_dir.glob("[0-9][0-9][0-9][0-9]-*.md")):
        m = re.match(r"\A\+\+\+\n(.*?)\n\+\+\+\n", p.read_text(encoding="utf-8"), re.S)
        if not m:
            continue
        try:
            meta = tomllib.loads(m.group(1))
        except tomllib.TOMLDecodeError:
            continue
        note(meta.get("trigger"), meta.get("triggered_at"))
    if ledger and ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                note(row.get("trigger"), row.get("at"))
    return seen


def evaluate(config: dict, issues: list[dict], timelines: dict[int, list[dict]], seen: dict[str, dt.datetime | None]) -> list[dict]:
    t = ticket_config(config)
    label, approvers = t["label"], t["approvers"]
    rows = []
    for issue in issues:
        if not isinstance(issue, dict) or not isinstance(issue.get("number"), int):
            continue
        n = issue["number"]
        row = {"number": n, "title": issue.get("title", ""), "url": issue.get("html_url", ""), "state": issue.get("state", ""),
               "labels": [lb.get("name") for lb in issue.get("labels") or [] if isinstance(lb, dict)],
               "matched": False, "action": "skip", "reason": "", "approver": None, "labeledAt": None, "trigger": f"ticket:{n}"}
        if issue.get("pull_request"):
            row["reason"] = "a pull request, not a ticket"
        elif issue.get("state") != "open":
            row["reason"] = f"not open ({issue.get('state')})"
        elif label not in row["labels"]:
            row["reason"] = f"no {label} label"
        else:
            timeline = timelines.get(n) or []
            who, at = label_added_by(timeline, label)
            if who is None:
                row["reason"] = f"{label} is on the issue but the timeline does not say who added it"
            elif who not in approvers:
                row["reason"] = f"{label} added by {who}, who is not in approvers ({', '.join(approvers) or 'none listed'}): a request, not an approval"
            else:
                row["approver"], row["labeledAt"] = who, at
                taken = seen[row["trigger"]] if row["trigger"] in seen else "never"
                reopened = last_reopened(timeline)
                if taken != "never" and not (reopened and (taken is None or reopened > taken)):
                    row["reason"] = f"already ran as {row['trigger']}" + (f" ({taken.isoformat(timespec='minutes')})" if taken else "") + "; a reopened issue counts again"
                else:
                    row["matched"], row["action"] = True, "start"
                    row["reason"] = f"{label} added by {who} (approver)" + (f" at {at}" if at else "") + (
                        f"; reopened {reopened.isoformat(timespec='minutes')} after it last ran, so it counts again" if taken != "never" else "")
        rows.append(row)
    return rows


def _opt(rest: list[str], name: str) -> str | None:
    if name in rest:
        i = rest.index(name)
        value = rest[i + 1]
        del rest[i:i + 2]
        return value
    return None


def main(argv: list[str]) -> int:
    if len(argv) < 4 or argv[0] != "evaluate":
        print("usage: tickets.py evaluate <harness> <specs> <ledger> --issues <issues.json> --timelines <dir>", file=sys.stderr)
        return 2
    try:
        config = tomllib.loads((Path(argv[1]) / "config.toml").read_text(encoding="utf-8"))
        rest = argv[4:]
        issues_file = _opt(rest, "--issues")
        tl_dir = _opt(rest, "--timelines")
        if not issues_file:
            raise ValueError("--issues <file> is required")
        issues = json.loads(Path(issues_file).read_text(encoding="utf-8"))
        timelines: dict[int, list[dict]] = {}
        if tl_dir:
            for p in Path(tl_dir).glob("*.json"):
                if p.stem.isdigit():
                    timelines[int(p.stem)] = json.loads(p.read_text(encoding="utf-8"))
        seen = seen_triggers(Path(argv[2]), Path(argv[3]))
        print(json.dumps(evaluate(config, issues, timelines, seen)))
    except (ValueError, OSError, IndexError, KeyError) as e:
        print(f"tickets.py: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
