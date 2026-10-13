"""The demo's event feed: events.jsonl (append-only) and state.json (rewritten on every event).

The shape is fixed by demo/live/schema.json; demo/live/validate.py checks files against it.
Milestone titles are the projector callouts: what important thing just happened, in one line.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from pathlib import Path

ACT_TITLES = {
    0: "Bring in the repo",
    1: "The audience's feature",
    2: "The batch of twenty",
    3: "The trap",
    4: "Autonomy earned",
    5: "The harness fixes itself",
    6: "Ready to release",
}

COUNTERS = [
    "specs", "workbenches", "checks_passed", "checks_failed", "prs", "merged_by_policy",
    "stopped_for_person", "denied", "spend", "human_prompts",
]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def fresh_state(cap: float, mode: str, run_id: str) -> dict:
    return {
        "repo": {"full_name": "", "url": "", "license": "", "tests": 0, "test_seconds": 0, "open_issues": 0},
        "deployment": "native",
        "phase": 2,
        "budget": {"cap": cap, "spent": 0.0},
        "acts": [{"n": n, "title": t, "status": "pending", "started": None, "ended": None, "summary": None} for n, t in ACT_TITLES.items()],
        "worktrees": [],
        "counters": {k: (0.0 if k == "spend" else 0) for k in COUNTERS},
        "milestones": [],
        "mode": mode,
        "run_id": run_id,
        "updated": now(),
    }


class Feed:
    def __init__(self, live: Path, cap: float, mode: str, run_id: str, echo=None):
        self.live = live
        self.live.mkdir(parents=True, exist_ok=True)
        self.events_path = live / "events.jsonl"
        self.state_path = live / "state.json"
        self.lock = threading.RLock()
        self.echo = echo
        self.act = 0
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.state["mode"] = mode
            self.state["budget"]["cap"] = cap
            # A resumed run keeps its spend and counters; the acts keep their status.
            for a in self.state["acts"]:
                if a["status"] == "running":
                    a["status"] = "pending"
        else:
            self.state = fresh_state(cap, mode, run_id)
            self.events_path.write_text("", encoding="utf-8")
            self._write_state()

    # ---- raw -----------------------------------------------------------------------------
    def emit(self, kind: str, id: str, title: str, detail: str = "", level: str = "info", data: dict | None = None, act: int | None = None) -> dict:
        ev = {
            "ts": now(),
            "act": self.act if act is None else act,
            "kind": kind,
            "id": id,
            "title": title,
            "detail": detail,
            "level": level,
            "data": data or {},
        }
        with self.lock:
            with self.events_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
            if kind == "milestone":
                self.state["milestones"] = (self.state["milestones"] + [ev])[-50:]
            self._write_state()
        if self.echo:
            self.echo(ev)
        return ev

    def _write_state(self) -> None:
        self.state["updated"] = now()
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.state, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.state_path)

    # ---- typed ----------------------------------------------------------------------------
    def milestone(self, id: str, title: str, detail: str = "", level: str = "key", **data) -> dict:
        return self.emit("milestone", id, title, detail, level, data)

    def log(self, id: str, title: str, detail: str = "", level: str = "info", **data) -> dict:
        return self.emit("log", id, title, detail, level, data)

    def warn(self, id: str, title: str, detail: str = "", **data) -> dict:
        return self.emit("log", id, title, detail, "warn", data)

    def count(self, name: str, delta: float = 1) -> None:
        with self.lock:
            c = self.state["counters"]
            if name == "spend":
                c["spend"] = round(float(c["spend"]) + float(delta), 4)
                self.state["budget"]["spent"] = c["spend"]
            else:
                c[name] = int(c[name]) + int(delta)
            value = c[name]
        self.emit("counter", f"counter.{name}", f"{name} = {value}", "", "info", {"name": name, "value": value, "delta": delta})

    def spend(self, usd: float, what: str = "") -> None:
        if usd:
            self.count("spend", round(float(usd), 4))

    def set(self, path: str, value) -> None:
        """Set a state field by dotted path (for example repo.license) and record it."""
        with self.lock:
            node = self.state
            keys = path.split(".")
            for k in keys[:-1]:
                node = node.setdefault(k, {})
            node[keys[-1]] = value
        self.emit("state", f"state.{path}", f"{path} set", "", "info", {"path": path, "value": value})

    def act_start(self, n: int) -> None:
        self.act = n
        with self.lock:
            row = self.state["acts"][n]
            row["status"] = "running"
            row["started"] = row["started"] or now()
        self.emit("state", "state.act", f"Act {n}: {ACT_TITLES[n]}", "started", "info", {"n": n, "status": "running"})

    def act_end(self, n: int, status: str = "done", summary: dict | None = None) -> None:
        with self.lock:
            row = self.state["acts"][n]
            row["status"] = status
            row["ended"] = now()
            if summary is not None:
                row["summary"] = summary
        self.emit("state", "state.act", f"Act {n}: {ACT_TITLES[n]}", status, "info", {"n": n, "status": status, "summary": summary or {}})

    def act_status(self, n: int) -> str:
        return self.state["acts"][n]["status"]

    def worktree(self, task: str, **fields) -> dict:
        """Upsert a worktree row by task id (or spec when the task is not known yet)."""
        with self.lock:
            rows = self.state["worktrees"]
            row = next((r for r in rows if r["task"] == task), None)
            if row is None and fields.get("spec"):
                row = next((r for r in rows if r["task"] == "" and r["spec"] == fields["spec"]), None)
                if row is not None:
                    row["task"] = task
            if row is None:
                row = {"task": task, "spec": "", "class": "", "path": "", "status": "created", "pr": None, "cost": 0.0, "act": self.act}
                rows.append(row)
            row.update({k: v for k, v in fields.items() if v is not None})
            self._write_state()
            return dict(row)

    def worktree_row(self, task: str) -> dict | None:
        with self.lock:
            return next((dict(r) for r in self.state["worktrees"] if r["task"] == task), None)

    def human_prompt(self, question: str, answer: str) -> None:
        self.count("human_prompts")
        self.log("human.prompt", "A person answered", f"{question} -> {answer}", question=question, answer=answer)
