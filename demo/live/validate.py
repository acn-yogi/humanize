#!/usr/bin/env python3
"""Validate the demo's live feed against demo/live/schema.json.

    python3 demo/live/validate.py [demo/live]

Checks every line of events.jsonl against the event schema, state.json against the state
schema, every milestone id against the known list, and that state.milestones holds the last
(at most 50) milestone events in order. Standard library only. Exit 0 when everything holds,
1 with one line per problem otherwise.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def check(value, schema: dict, where: str, problems: list[str]) -> None:
    """A small JSON Schema subset: type, enum, pattern, required, properties, items, minimum, maximum."""
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        ok = False
        for name in types:
            py = TYPES[name]
            if isinstance(value, py) and not (name in ("integer", "number") and isinstance(value, bool)):
                ok = True
        if not ok:
            problems.append(f"{where}: expected {t}, got {type(value).__name__}")
            return
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{where}: {value!r} is not one of {schema['enum']}")
    if "pattern" in schema and isinstance(value, str) and not re.search(schema["pattern"], value):
        problems.append(f"{where}: {value!r} does not match {schema['pattern']}")
    if "minimum" in schema and isinstance(value, (int, float)) and value < schema["minimum"]:
        problems.append(f"{where}: {value} is below {schema['minimum']}")
    if "maximum" in schema and isinstance(value, (int, float)) and value > schema["maximum"]:
        problems.append(f"{where}: {value} is above {schema['maximum']}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                problems.append(f"{where}: missing {key}")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                check(value[key], sub, f"{where}.{key}", problems)
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in schema.get("properties", {}):
                    problems.append(f"{where}: unexpected {key}")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            check(item, schema["items"], f"{where}[{i}]", problems)


def main(argv: list[str]) -> int:
    live = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent
    schema = json.loads((Path(__file__).resolve().parent / "schema.json").read_text(encoding="utf-8"))
    problems: list[str] = []
    events = []
    ev_path = live / "events.jsonl"
    if not ev_path.exists():
        problems.append(f"{ev_path}: missing")
    else:
        for n, line in enumerate(ev_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                problems.append(f"events.jsonl:{n}: blank line (the file is append-only, one event per line)")
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError as e:
                problems.append(f"events.jsonl:{n}: not JSON ({e})")
                continue
            check(ev, schema["event"], f"events.jsonl:{n}", problems)
            if isinstance(ev, dict) and ev.get("kind") == "milestone" and ev.get("id") not in schema["milestoneIds"]:
                problems.append(f"events.jsonl:{n}: milestone id {ev.get('id')!r} is not in schema.milestoneIds")
            # Act 0b's guardrail milestones carry a fixed data shape: the player and the runbook build against it.
            if isinstance(ev, dict) and ev.get("kind") == "milestone" and ev.get("id") in ("guardrail.defined", "guardrail.probed"):
                key = "guardrailDefined" if ev["id"] == "guardrail.defined" else "guardrailProbed"
                check(ev.get("data"), schema[key], f"events.jsonl:{n}.data", problems)
                if ev.get("act") != 0 or (ev.get("data") or {}).get("part") != "b":
                    problems.append(f"events.jsonl:{n}: {ev['id']} must carry act 0 and data.part \"b\" (Act 0b)")
            events.append(ev)
        for a, b in zip(events, events[1:]):
            if isinstance(a, dict) and isinstance(b, dict) and str(a.get("ts")) > str(b.get("ts")):
                problems.append(f"events.jsonl: timestamps go backwards at {b.get('ts')} (after {a.get('ts')})")
                break
    st_path = live / "state.json"
    if not st_path.exists():
        problems.append(f"{st_path}: missing")
    else:
        try:
            state = json.loads(st_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            problems.append(f"state.json: not JSON ({e})")
            state = None
        if state is not None:
            check(state, schema["state"], "state.json", problems)
            if isinstance(state, dict):
                ms = [e for e in events if isinstance(e, dict) and e.get("kind") == "milestone"][-50:]
                got = state.get("milestones") or []
                if len(got) > 50:
                    problems.append(f"state.json.milestones: {len(got)} entries, the cap is 50")
                if [m.get("id") for m in ms] != [m.get("id") for m in got if isinstance(m, dict)]:
                    problems.append("state.json.milestones: not the last milestone events of events.jsonl in order")
                acts = state.get("acts") or []
                if [a.get("n") for a in acts if isinstance(a, dict)] != list(range(7)):
                    problems.append("state.json.acts: expected one row per act 0 to 6, in order")
                # Every guardrail a probe reported on must have been defined first, and the state row must agree
                # with the last probe milestone for it.
                defined = {e["data"].get("name") for e in events if isinstance(e, dict) and e.get("id") == "guardrail.defined" and isinstance(e.get("data"), dict)}
                last_probe: dict[str, str] = {}
                for e in events:
                    if isinstance(e, dict) and e.get("id") == "guardrail.probed" and isinstance(e.get("data"), dict):
                        if e["data"].get("name") not in defined:
                            problems.append(f"events.jsonl: guardrail.probed for {e['data'].get('name')!r} without a guardrail.defined before it")
                        last_probe[e["data"].get("name")] = e["data"].get("result")
                rows = {g.get("name"): g for g in (state.get("guardrails") or []) if isinstance(g, dict)}
                for name, result in last_probe.items():
                    if name not in rows:
                        problems.append(f"state.json.guardrails: no row for {name!r}, which events.jsonl probed")
                    elif rows[name].get("probe") != result:
                        problems.append(f"state.json.guardrails[{name!r}].probe is {rows[name].get('probe')!r}, the last probe said {result!r}")
                c = state.get("counters") or {}
                b = state.get("budget") or {}
                if isinstance(c, dict) and isinstance(b, dict) and c.get("spend") is not None and b.get("spent") is not None:
                    if abs(float(c["spend"]) - float(b["spent"])) > 0.005:
                        problems.append("state.json: counters.spend and budget.spent disagree")
    for p in problems:
        print(f"FAIL  {p}")
    if not problems:
        n_ms = len([e for e in events if isinstance(e, dict) and e.get("kind") == "milestone"])
        print(f"PASS  {len(events)} event(s), {n_ms} milestone(s); events.jsonl and state.json match {Path(__file__).parent.name}/schema.json")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
