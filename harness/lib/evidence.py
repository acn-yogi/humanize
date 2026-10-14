#!/usr/bin/env python3
"""Render a task's evidence packet as the PR body: evidence.py <task run dir> > evidence.md

A reviewer reads this instead of re-deriving it: what was approved, what ran, what the
checks and the reviewer found, which loops turned and what they cost, and why the router
chose this approval path. Everything here comes from packet.json, which was assembled from
facts computed outside the session.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PATHS = {
    "per_pr": "per PR: a person reviews this change",
    "batch_plan": "per batch: joins an approved batch plan; one approval merges the batch",
    "graduated": "graduated: merges by policy",
    "reject": "rejected: halted with reasons, no PR",
}


def code(s: str) -> str:
    return "`" + s.replace("`", "'") + "`"


def render(p: dict) -> str:
    """The PR body for one packet."""
    spec, d = p["spec"], p["decision"]
    out: list[str] = []
    w = out.append

    w(f"**Workbench evidence packet** for spec `{spec['id']}`, from upstream issue {spec['issue']}.")
    w("")
    w(f"> **Route: {PATHS.get(d['path'], d['path'])}.** {d.get('next', '')}")
    for r in d.get("reasons", []):
        w(f"> - {r}")
    w("")

    w("### What a person approved")
    w(f"- Spec `specs/{spec['id']}.md`, class `{spec['class']}`, intent approved by {spec.get('approvedBy') or 'nobody yet'}.")
    w(f"- Scope: {', '.join(code(s) for s in spec['scope'])}.")
    w("")

    w("### Acceptance checks (fresh clone of the result, bubblewrap, no network)")
    w("| Check | Result |")
    w("|---|---|")
    for c in p["checks"]:
        w(f"| {code(c['cmd'])} | {'pass' if c['exit'] == 0 else 'FAIL, exit ' + str(c['exit'])} |")
    g = p.get("grading")
    if g:
        w("")
        w("**Fail first.** The reproducing check must fail on the base commit and pass on the result.")
        w("| Check | Base | Result |")
        w("|---|---|---|")
        for b, r in zip(g["baseChecks"], g["checks"]):
            w(f"| {code(b['cmd'])} | exit {b['exit']} {'(fails, as it must)' if b['exit'] else '(PASSES: no bug shown)'} | exit {r['exit']} |")
    neg = p.get("negatives")
    if neg:
        w("")
        w("**Must not change.** Behaviour the suite does not cover and the change must keep: each check passes on the base and must still pass on the result.")
        w("| Check | Base | Result |")
        w("|---|---|---|")
        for b, r in zip(neg["baseChecks"], neg["checks"]):
            w(f"| {code(b['cmd'])} | exit {b['exit']} {'(passes, as it must)' if b['exit'] == 0 else '(FAILS: not an invariant)'} | exit {r['exit']} {'(still passes)' if r['exit'] == 0 else '(FAILS: the change broke it)'} |")
    sc = p["scope"]
    w("")
    w(f"**Scope.** {len(p['changedPaths'])} file(s), {p['linesChanged']} line(s) changed: "
      + ", ".join(code(x) for x in p["changedPaths"]) + ". "
      + ("All inside the spec's scope." if not (sc["outside"] or sc["harness"]) else
         "Outside scope: " + ", ".join(code(x) for x in sc["outside"] + sc["harness"]) + "."))
    w("")

    rounds = p.get("rounds") or []
    if len(rounds) > 1:
        w("### Rounds: what was rejected, and what the retry fixed")
        w("| Round | Checks | Reviewer | Router |")
        w("|---|---|---|---|")
        for r in rounds:
            v = (r.get("verdict") or {}).get("verdict", "none")
            w(f"| {r['round']} | {'pass' if r['allChecksPass'] else 'FAIL'} | {v} | {r['path']} |")
        for r in rounds[:-1]:
            w("")
            w(f"Round {r['round']} findings, handed back to the same session with `claude --resume` (loop 3):")
            for reason in (r.get("verdict") or {}).get("reasons") or r.get("reasons", []):
                w(f"- {reason}")
        w("")

    rv = p.get("review")
    w("### Adversarial review")
    if rv:
        w(f"A second Claude Code session (`{p['models']['reviewer']}`, edits denied) argued against the change: **{rv['verdict']}**.")
        for r in rv.get("reasons", []):
            w(f"- {r}")
    else:
        w("No review ran.")
    w("")

    lp = p["loops"]
    w("### The loops, and their caps")
    w("| Loop | What happened | Cap |")
    w("|---|---|---|")
    workers = [s for s in lp["sessions"] if s.get("role") == "worker"]
    for s in workers:
        w(f"| 1 session (round {s['round']}) | `{p['models']['worker']}`: {s.get('subtype')}, {s.get('turns')} turns, ${s.get('costUsd', 0):.2f} | {p['caps']['max_turns']} turns, ${p['caps']['max_budget_usd']} |")
    blocks = [f for f in lp["finish"] if f.get("result") == "block"]
    passes = [f for f in lp["finish"] if f.get("result") == "pass"]
    w(f"| 2 finish (Stop hook) | {len(blocks)} block(s), {len(passes)} pass(es) of the quick checks | {p['caps']['continuations']} continuations |")
    w(f"| 3 retry (`--resume`) | {lp['retries']} retry round(s) | {p['caps']['retries']} |")
    w(f"| 4 queue | dispatched by `harness/bin/dispatch.sh` or run directly | {p['caps']['tasks_per_queue_run']} tasks per wake-up |")
    reviewers = [s for s in lp["sessions"] if s.get("role") == "reviewer"]
    total = p.get("costUsd", 0)
    w("")
    w(f"Spend: ${total:.2f} in total across {len(workers)} worker and {len(reviewers)} reviewer session(s), as Claude Code estimates it.")
    if lp["scopeDenials"]:
        w("")
        w("Scope guard refusals while Claude worked:")
        for s in lp["scopeDenials"]:
            w(f"- {s.get('tool')} on `{s.get('path')}`")
    w("")

    halt = p.get("halt")
    if halt:
        w("### Halt")
        w(f"- Reason `{halt.get('reason')}`, failure class `{halt.get('failureClass')}`"
          + (f", stall `{halt.get('stall')}`" if halt.get("stall") else "") + ".")
        w(f"- {halt.get('stallEvidence') or halt.get('evidence')}")
        w("")

    w("### Provenance")
    w(f"- Base `{p['baseBranch']}` at `{p['baseCommit'][:12]}`; result `{p['headCommit'][:12]}`.")
    fp = p.get("fingerprint") or {}
    served = fp.get("servedModel") or {}
    w(f"- {p['claudeCodeVersion']}, pack `{p['packId']}`, placement: {p['placement']}."
      + (f" Served model: author `{served.get('author')}`, reviewer `{served.get('reviewer')}` (configured `{p['models'].get('worker')}` / `{p['models'].get('reviewer')}`)." if served else ""))
    w(f"- Task `{p['taskId']}`, {p['startedAt']} to {p['endedAt']}. Transcripts, checks log and packet.json stay with the run.")
    w("")
    w("<sub>Opened by the workbench harness on a fork. Nothing here was sent upstream.</sub>")
    return "\n".join(out)


def main() -> None:
    run = Path(sys.argv[1])
    print(render(json.loads((run / "packet.json").read_text(encoding="utf-8"))))


if __name__ == "__main__":
    main()
