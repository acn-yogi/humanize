#!/usr/bin/env python3
"""Release readiness verdict over the changes the harness merged: hard gates from facts.

    verdict.py --state demo/live/state.json --runs runs --fork owner/name [--recordings demo/recordings] [--offline]

The harness's last output. Every merged change (state.json worktrees with status merged, or
every ledger row with a PR when no state is given) must have: a packet on record, every check
passed in the fresh clone, a clean scope, a reviewer approval, and a route that was not a
rejection. Then the fork's own CI on the base branch's head is read through gh (skipped with
--offline). A verdict is "ready" only when every gate passes and at least one change merged;
anything else is "not ready" with the failed gates named. Nothing here can lift a blocker: a
readiness agent may add one, never remove one. Prints one JSON object. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def gh(*args: str):
    exe = "gh" if shutil.which("gh") else "gh.exe"
    r = subprocess.run([exe, *args], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout.replace("\r", ""))
    except json.JSONDecodeError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state")
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--recordings", default="demo/recordings")
    ap.add_argument("--fork", required=True)
    ap.add_argument("--base", default="main")
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    runs, rec = Path(a.runs), Path(a.recordings)
    state = load(Path(a.state)) if a.state else None
    changes = []
    if state:
        changes = [{"task": w["task"], "spec": w["spec"], "pr": w.get("pr")} for w in state.get("worktrees", []) if w.get("status") == "merged" and w.get("task")]
    merged_from = "state.json (status merged)"
    if not changes:
        # Nothing merged: judge what the ledger shows was opened, so the verdict says why it is not ready.
        ledger = runs / "ledger.jsonl" if (runs / "ledger.jsonl").exists() else rec / "ledger.jsonl"
        merged_from = f"{ledger} (opened, not merged)"
        if ledger.exists():
            for line in ledger.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("pr"):
                    changes.append({"task": row["taskId"], "spec": row["spec"], "pr": row["pr"], "unmerged": True})
    gates = []

    def gate(name: str, ok: bool | None, detail: str) -> None:
        gates.append({"gate": name, "result": "pass" if ok else "skip" if ok is None else "fail", "detail": detail})

    if not changes:
        gate("merged", False, "no merged change on record")
    else:
        unmerged = [c["spec"] for c in changes if c.get("unmerged")]
        gate("merged", not unmerged, f"{len(changes) - len(unmerged)} merged change(s)" + (f"; {len(unmerged)} opened but not merged: {', '.join(unmerged[:5])}" if unmerged else ""))
    missing, checks_bad, scope_bad, review_bad, route_bad = [], [], [], [], []
    for c in changes:
        pdir = next((d for d in (runs / c["task"], rec / c["task"], *runs.glob(f"proofs/*/{c['task']}")) if (d / "packet.json").exists()), None)
        pk = load(pdir / "packet.json") if pdir else None
        if not pk:
            missing.append(c["spec"])
            continue
        if not pk.get("allChecksPass"):
            checks_bad.append(c["spec"])
        sc = pk.get("scope") or {}
        if (sc.get("outside") or []) or (sc.get("harness") or []):
            scope_bad.append(c["spec"])
        if ((pk.get("review") or {}).get("verdict")) != "approve":
            review_bad.append(c["spec"])
        if (pk.get("decision") or {}).get("path") in (None, "reject"):
            route_bad.append(c["spec"])
    gate("evidence", not missing, "a packet on record for every change" if not missing else f"no packet for {', '.join(missing[:5])}")
    gate("checks", not checks_bad, "every check passed in a fresh clone with no network" if not checks_bad else f"checks failed: {', '.join(checks_bad[:5])}")
    gate("scope", not scope_bad, "every diff inside its spec's scope" if not scope_bad else f"outside scope: {', '.join(scope_bad[:5])}")
    gate("review", not review_bad, "the adversarial reviewer approved every change" if not review_bad else f"reviewer did not approve: {', '.join(review_bad[:5])}")
    gate("route", not route_bad, "every change took an approval path" if not route_bad else f"rejected: {', '.join(route_bad[:5])}")
    if a.offline:
        gate("ci", None, "offline: the fork's CI was not read")
    else:
        head = gh("api", f"repos/{a.fork}/commits/{a.base}", "--jq", "{sha: .sha}")
        sha = (head or {}).get("sha")
        runs_json = gh("api", f"repos/{a.fork}/commits/{sha}/check-runs?per_page=50") if sha else None
        if not runs_json:
            gate("ci", None, f"no check runs readable for {a.base} on {a.fork}")
        else:
            cr = runs_json.get("check_runs") or []
            failed = [r["name"] for r in cr if r.get("conclusion") in ("failure", "timed_out", "cancelled", "action_required")]
            pending = [r["name"] for r in cr if r.get("status") != "completed"]
            if failed:
                gate("ci", False, f"{a.base} at {sha[:12]}: failed {', '.join(failed[:5])}")
            elif pending:
                gate("ci", None, f"{a.base} at {sha[:12]}: {len(pending)} check(s) still running")
            else:
                gate("ci", True, f"{a.base} at {sha[:12]}: {len(cr)} check run(s) green" if cr else f"{a.base} at {sha[:12]}: no check runs yet")
    verdict = "ready" if all(g["result"] != "fail" for g in gates) and changes and not any(c.get("unmerged") for c in changes) else "not ready"
    out = {"v": 1, "verdict": verdict, "fork": a.fork, "base": a.base, "merged": len([c for c in changes if not c.get("unmerged")]),
           "changes": changes, "gates": gates, "source": merged_from,
           "handoff": "the fork's release.yml builds and inspects the package on every push to main (the dark deploy); a tagged release is the flag flip and stays a person's decision"}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
