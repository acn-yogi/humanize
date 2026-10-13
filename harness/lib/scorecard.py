#!/usr/bin/env python3
"""The scorecard: the human-touch signals and whether the harness is learning, from the ledger.

    scorecard.py <repo root> [--ledger runs/ledger.jsonl] [--json] [--offline] [--prs FILE]

One line per signal (and --json for the same as one object):

    manual takeovers          corrected rows with source manual and action takeover
    human PR comments         corrected rows with source pr-comment: total, and per PR
    PRs with no correction    harness PRs (branch workbench/<task>) with no corrected row
    cost per merged PR        sum of costUsd of the tasks whose PR merged, over the merged count
    recurrence                a reason code seen in a corrected row after the case for it was
                              marked fixed (harness/cases/*.json with reasonCode and provenAt)
    pack size                 bytes and files under harness/pack, harness/hooks and the settings template

The PR list comes from gh pr list on the fork (never upstream); --offline reads none and says
so; --prs FILE reads a saved JSON list instead (tests). The math lives in compute(), which takes
plain lists so it can be tested without gh. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path

PACK_PATHS = ("harness/pack", "harness/hooks", ".claude/workbench/settings.template.json")
TASK_RE = re.compile(r"\bt-[0-9A-HJKMNP-TV-Z]{26}\b")


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def pack_size(root: Path) -> dict:
    files = 0
    size = 0
    for rel in PACK_PATHS:
        p = root / rel
        if p.is_file():
            files += 1
            size += p.stat().st_size
        elif p.is_dir():
            for f in p.rglob("*"):
                if f.is_file() and "__pycache__" not in f.parts and not f.name.endswith(".pyc"):
                    files += 1
                    size += f.stat().st_size
    return {"bytes": size, "files": files, "paths": list(PACK_PATHS)}


def task_of_pr(pr: dict) -> str:
    for text in (pr.get("headRefName") or "", pr.get("body") or ""):
        m = TASK_RE.search(text)
        if m:
            return m.group(0)
    return ""


def compute(ledger: list[dict], prs: list[dict] | None, cases: list[dict], pack: dict) -> dict:
    """The scorecard from plain lists. prs is None when GitHub was not read."""
    tasks = {r["taskId"]: r for r in ledger if r.get("taskId") and r.get("event") is None and "costUsd" in r}
    corrected = [r for r in ledger if r.get("event") == "corrected"]
    takeovers = [r for r in corrected if r.get("source") == "manual" and r.get("action") == "takeover"]
    comments = [r for r in corrected if r.get("source") == "pr-comment"]
    per_pr = Counter(int(r["pr"]) for r in comments if r.get("pr") is not None)
    corrected_tasks = {r.get("taskId") for r in corrected if r.get("taskId")}
    corrected_prs = {int(r["pr"]) for r in corrected if r.get("pr") is not None}

    harness_prs = [p for p in (prs or []) if str(p.get("headRefName", "")).startswith("workbench/")]
    merged = [p for p in harness_prs if p.get("mergedAt")]
    no_correction = [p for p in harness_prs if int(p["number"]) not in corrected_prs and task_of_pr(p) not in corrected_tasks]
    merged_cost = 0.0
    merged_with_cost = 0
    for p in merged:
        t = tasks.get(task_of_pr(p))
        if t is not None:
            merged_cost += float(t.get("costUsd") or 0)
            merged_with_cost += 1
    cost_per_merged = round(merged_cost / len(merged), 4) if merged else None

    recurrences = []
    for c in cases:
        code, fixed_at = c.get("reasonCode"), c.get("provenAt") or c.get("fixedAt")
        if not code or not fixed_at:
            continue
        later = [r for r in corrected if r.get("reasonCode") == code and str(r.get("at", "")) > str(fixed_at)]
        if later:
            recurrences.append({"case": c.get("id"), "reasonCode": code, "fixedAt": fixed_at, "count": len(later),
                                "urls": [r.get("url") or r.get("taskId") for r in later][:5]})
    return {
        "v": 1,
        "manualTakeovers": len(takeovers),
        "humanPrComments": {"total": len(comments), "perPr": {str(k): v for k, v in sorted(per_pr.items())}},
        "prsWithNoCorrection": {"count": len(no_correction), "of": len(harness_prs), "numbers": [int(p["number"]) for p in no_correction]} if prs is not None else None,
        "costPerMergedPr": {"usd": cost_per_merged, "merged": len(merged), "mergedWithCost": merged_with_cost, "totalUsd": round(merged_cost, 4)} if prs is not None else None,
        "recurrence": {"count": sum(r["count"] for r in recurrences), "cases": recurrences, "casesWatched": len([c for c in cases if c.get("reasonCode") and (c.get("provenAt") or c.get("fixedAt"))])},
        "packSize": pack,
        "tasks": len(tasks),
        "corrected": len(corrected),
    }


def render(s: dict) -> str:
    out = []
    w = out.append
    w(f"manual takeovers          {s['manualTakeovers']}")
    pp = s["humanPrComments"]["perPr"]
    w(f"human PR comments         {s['humanPrComments']['total']}" + (": " + ", ".join(f"PR #{k}: {v}" for k, v in pp.items()) if pp else ""))
    if s["prsWithNoCorrection"] is None:
        w("PRs with no correction    n/a (GitHub not read)")
    else:
        n = s["prsWithNoCorrection"]
        w(f"PRs with no correction    {n['count']} of {n['of']} harness PR(s)" + (f" (#{', #'.join(map(str, n['numbers']))})" if n["numbers"] else ""))
    if s["costPerMergedPr"] is None:
        w("cost per merged PR        n/a (GitHub not read)")
    elif s["costPerMergedPr"]["merged"] == 0:
        w("cost per merged PR        n/a (no harness PR merged yet)")
    else:
        c = s["costPerMergedPr"]
        w(f"cost per merged PR        ${c['usd']:.2f} ({c['merged']} merged, ${c['totalUsd']:.2f} in all; {c['mergedWithCost']} with a ledger cost)")
    r = s["recurrence"]
    if r["casesWatched"] == 0:
        w("recurrence                n/a (no proven case carries a reason code yet)")
    else:
        w(f"recurrence                {r['count']} over {r['casesWatched']} proven case(s)" + ("".join(f"; {x['reasonCode']} again after {x['case']} ({x['count']})" for x in r["cases"]) if r["cases"] else ""))
    p = s["packSize"]
    w(f"pack size                 {p['bytes']} bytes, {p['files']} files ({', '.join(p['paths'])})")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("root")
    ap.add_argument("--ledger", default="runs/ledger.jsonl")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--prs", help="a saved gh pr list JSON file instead of reading GitHub")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    ledger = read_jsonl(root / a.ledger if not Path(a.ledger).is_absolute() else Path(a.ledger))
    cases = []
    for f in sorted((root / "harness/cases").glob("*.json")):
        cases.append(json.loads(f.read_text(encoding="utf-8")))
    prs = None
    if a.prs:
        prs = json.loads(Path(a.prs).read_text(encoding="utf-8"))
    elif not a.offline:
        config = tomllib.loads((root / "harness/config.toml").read_text(encoding="utf-8"))
        fork = config["github"]["repo"]
        if fork == config["github"]["upstream"]:
            raise SystemExit("scorecard: refusing to read the upstream repository")
        exe = "gh" if shutil.which("gh") else "gh.exe"
        r = subprocess.run([exe, "pr", "list", "--repo", fork, "--state", "all", "--limit", "200",
                            "--json", "number,headRefName,body,url,state,mergedAt"], capture_output=True, text=True)
        if r.returncode == 0:
            prs = json.loads(r.stdout.replace("\r", "") or "[]")
        else:
            print(f"scorecard: gh failed ({r.stderr.strip()[:200]}); GitHub signals not read", file=sys.stderr)
    s = compute(ledger, prs, cases, pack_size(root))
    print(json.dumps(s, indent=1) if a.json else render(s))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
