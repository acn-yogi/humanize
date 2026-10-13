#!/usr/bin/env python3
"""The schedule trigger: which [[triggers.schedule]] entries are due, and the recurring spec one enqueues.

    schedule.py entries <harness dir> [<iso minute>]           -> JSON list: each entry, due now?, next fires
    schedule.py enqueue <harness dir> <specs dir> <name> [<ledger>] [--date YYYY-MM-DD] [--dry-run]
                                                                -> JSON {written, id, trigger, reason}

An entry is {cron, tz} plus either take = "queue" (take the approved queue, up to the caps) or
spec = "<name>" (enqueue harness/recurring/<name>.md as one dated, approved spec). With no
[[triggers.schedule]] entries configured, the default is the 30 minute queue timer the
dispatcher always had.

A recurring spec is a template with TOML front matter like any spec, minus the id. Enqueuing
copies it to specs/<NNNN>-<name>-<yyyymmdd>.md with id, status = "approved" (the template's own
approved_by is the person who approved the recurring work; a template without one stays a
draft), and trigger = "schedule:<name>:<date>". One per day: the same trigger already in a
spec or a ledger row means it was enqueued, and nothing is written again.

Standard library only (Python 3.11+ for tomllib).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cron import CronError, is_due, next_fires, parse  # noqa: E402

DEFAULT_ENTRIES = [{"cron": "*/30 * * * *", "tz": "UTC", "take": "queue"}]


def load_entries(config: dict) -> list[dict]:
    entries = (config.get("triggers") or {}).get("schedule")
    if entries is None:
        return [dict(e) for e in DEFAULT_ENTRIES]
    if not isinstance(entries, list):
        raise CronError("[[triggers.schedule]] must be an array of tables")
    out = []
    for i, e in enumerate(entries):
        if not isinstance(e, dict) or "cron" not in e:
            raise CronError(f"schedule entry {i + 1} needs cron = \"...\"")
        if ("spec" in e) == (e.get("take") == "queue"):
            raise CronError(f"schedule entry {i + 1} ({e['cron']}): either take = \"queue\" or spec = \"<name>\", not both or neither")
        parse(e["cron"])
        out.append({"cron": e["cron"], "tz": e.get("tz", "UTC"), "take": e.get("take"), "spec": e.get("spec")})
    return out


def describe(entry: dict) -> str:
    return "take the approved queue" if entry.get("take") == "queue" else f"enqueue recurring spec {entry.get('spec')}"


def evaluate(config: dict, now: dt.datetime) -> list[dict]:
    rows = []
    for e in load_entries(config):
        rows.append({
            **e,
            "what": describe(e),
            "due": is_due(e["cron"], e["tz"], now),
            "next": [f.isoformat(timespec="minutes") for f in next_fires(e["cron"], e["tz"], now, 2)],
        })
    return rows


def read_front_matter(path: Path) -> tuple[dict, str, str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"\A\+\+\+\n(.*?)\n\+\+\+\n(.*)\Z", text, re.S)
    if not m:
        raise CronError(f"{path}: no TOML front matter between +++ lines")
    return tomllib.loads(m.group(1)), m.group(1), m.group(2)


def seen_triggers(specs_dir: Path, ledger: Path | None) -> set[str]:
    seen: set[str] = set()
    for p in specs_dir.glob("[0-9][0-9][0-9][0-9]-*.md"):
        try:
            meta = read_front_matter(p)[0]
        except (CronError, tomllib.TOMLDecodeError):
            continue
        if isinstance(meta.get("trigger"), str):
            seen.add(meta["trigger"])
    if ledger and ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and isinstance(row.get("trigger"), str):
                seen.add(row["trigger"])
    return seen


def next_number(specs_dir: Path) -> int:
    nums = [int(p.name[:4]) for p in specs_dir.glob("[0-9][0-9][0-9][0-9]-*.md")]
    return max(nums, default=0) + 1


def enqueue(harness: Path, specs_dir: Path, name: str, ledger: Path | None, day: dt.date, dry_run: bool) -> dict:
    template = harness / "recurring" / f"{name}.md"
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,40}", name) or not template.exists():
        return {"written": False, "reason": f"no recurring spec harness/recurring/{name}.md"}
    trigger = f"schedule:{name}:{day.isoformat()}"
    if trigger in seen_triggers(specs_dir, ledger):
        return {"written": False, "trigger": trigger, "reason": f"already enqueued today ({trigger})"}
    meta, front, body = read_front_matter(template)
    if "id" in meta:
        return {"written": False, "reason": f"{template}: a recurring template carries no id; the schedule assigns one"}
    spec_id = f"{next_number(specs_dir):04d}-{name}-{day:%Y%m%d}"
    approved_by = meta.get("approved_by")
    status = "approved" if approved_by else "draft"
    lines = [f'id = "{spec_id}"', f'status = "{status}"', f'trigger = "{trigger}"', f'triggered_at = "{day.isoformat()}"']
    # The template's own status line, if any, is replaced by the one above.
    front = re.sub(r"(?m)^status\s*=.*\n?", "", front)
    text = "+++\n" + "\n".join(lines) + "\n" + front.rstrip("\n") + "\n+++\n" + body
    path = specs_dir / f"{spec_id}.md"
    if not dry_run:
        path.write_text(text, encoding="utf-8")
    return {"written": not dry_run, "id": spec_id, "file": str(path), "trigger": trigger, "status": status,
            "approvedBy": approved_by, "reason": "enqueued from the schedule" if not dry_run else "dry run: would be written"}


def main(argv: list[str]) -> int:
    try:
        if len(argv) >= 2 and argv[0] == "entries":
            config = tomllib.loads((Path(argv[1]) / "config.toml").read_text(encoding="utf-8"))
            now = dt.datetime.fromisoformat(argv[2]) if len(argv) > 2 else dt.datetime.now(dt.timezone.utc)
            print(json.dumps(evaluate(config, now)))
            return 0
        if len(argv) >= 4 and argv[0] == "enqueue":
            harness, specs_dir, name = Path(argv[1]), Path(argv[2]), argv[3]
            rest = argv[4:]
            dry = "--dry-run" in rest
            rest = [r for r in rest if r != "--dry-run"]
            day = dt.datetime.now(dt.timezone.utc).date()
            if "--date" in rest:
                i = rest.index("--date")
                day = dt.date.fromisoformat(rest[i + 1])
                del rest[i:i + 2]
            ledger = Path(rest[0]) if rest else None
            print(json.dumps(enqueue(harness, specs_dir, name, ledger, day, dry)))
            return 0
    except (CronError, ValueError, OSError) as e:
        print(f"schedule.py: {e}", file=sys.stderr)
        return 2
    print("usage: schedule.py entries <harness> [<iso>] | enqueue <harness> <specs> <name> [<ledger>] [--date D] [--dry-run]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
