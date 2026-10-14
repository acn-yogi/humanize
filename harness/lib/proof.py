#!/usr/bin/env python3
"""The verdict table of one proof: before pass^k, after pass^k, regressions, cost, judge verdicts.

    proof.py <repo root> <case id> [--fix-branch BRANCH] [--cases-output FILE] [--write-case] [--record]

Reads runs/proofs/<case>/current/summary.json (the reproduce step), runs/proofs/<case>/candidate/
summary.json (the prove step), every candidate trial's judge.json (both trajectories) and the
regression suite's output (harness/bin/cases.sh, saved to a file), and writes
runs/proofs/<case>/verdict.json and verdict.txt.

SHIP only when: the case failed at least once on the current pack (reproduced), after pass^k is
1, the regression suite has no FAIL, and every judge verdict is "earned" (at least one judge).
Anything else is NO-SHIP with the reasons named. --write-case puts the proof on the case in
harness/cases/<case>.json (proof, status, fixedIn, provenAt) whatever the verdict, so the suite
lists it; --record copies the proof folder (without bundles) to demo/recordings/proof/.
Standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fingerprint  # noqa: E402


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def git(root: Path, *args: str) -> str:
    r = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "safe.directory=*", "-C", str(root), *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def side(summary: dict | None) -> dict:
    if not summary:
        return {"passK": None, "passes": 0, "trials": 0, "errors": 0, "costUsd": 0.0, "interrupted": [], "interruptedCostUsd": 0.0, "base": None, "baseSha": None, "packIds": [], "fingerprints": [], "runs": []}
    return {"passK": summary.get("passK"), "passes": summary.get("passes", 0), "trials": summary.get("trials", 0),
            "errors": summary.get("errors", 0), "costUsd": round(float(summary.get("costUsd") or 0), 4), "base": summary.get("base"), "baseSha": summary.get("baseSha"),
            "packIds": summary.get("packIds") or [], "k": summary.get("k"),
            "fingerprints": summary.get("fingerprints") or [],
            "interrupted": summary.get("interrupted") or [], "interruptedCostUsd": round(float(summary.get("interruptedCostUsd") or 0), 4),
            "runs": [{k: r.get(k) for k in ("trial", "taskId", "outcome", "why", "checksPass", "reviewVerdict0", "ruffOk", "ruffFindings", "stopBlocks", "costUsd", "workerTurns")} for r in summary.get("runs") or []]}


def build(root: Path, case_id: str, fix_branch: str | None, cases_output: str | None) -> dict:
    case = load(root / "harness/cases" / f"{case_id}.json") or {}
    pdir = root / "runs/proofs" / case_id
    before = side(load(pdir / "current/summary.json"))
    after = side(load(pdir / "candidate/summary.json"))
    judges = []
    for r in after["runs"]:
        j = load(pdir / "candidate" / str(r.get("taskId") or "") / "judge.json") if r.get("taskId") else None
        if j:
            judges.append({"taskId": r["taskId"], "verdict": j.get("verdict"), "quote": j.get("quote", ""), "reasons": j.get("reasons", []),
                           "quoteFound": j.get("quoteFound"), "model": j.get("model"), "costUsd": j.get("costUsd", 0)})
    branch = fix_branch or case.get("fixBranch")
    fix = {"branch": branch, "sha": git(root, "rev-parse", "--short", branch) if branch else "", "files": [], "diffstat": ""}
    if branch and fix["sha"]:
        main = "main"
        merge_base = git(root, "merge-base", main, branch)
        if merge_base and merge_base != git(root, "rev-parse", branch):
            fix["files"] = [f for f in git(root, "diff", "--name-only", merge_base, branch).splitlines() if f]
            fix["diffstat"] = git(root, "diff", "--shortstat", merge_base, branch)
            fix["commits"] = [l for l in git(root, "log", "--format=%h %s", f"{merge_base}..{branch}").splitlines() if l]
        else:
            # The branch is merged (or is main): describe its tip commit, which is the fix.
            fix["files"] = [f for f in git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", branch).splitlines() if f]
            fix["diffstat"] = git(root, "show", "--shortstat", "--format=", branch).strip()
            fix["commits"] = [l for l in git(root, "log", "-1", "--format=%h %s", branch).splitlines() if l]
            fix["merged"] = True
    regressions = None
    if cases_output is not None:
        regressions = len([l for l in cases_output.splitlines() if l.startswith("FAIL")])
    reasons = []
    reproduced = before["trials"] > 0 and before["passes"] < before["trials"]
    if not reproduced:
        reasons.append("not reproduced: the case never failed on the current pack" if before["trials"] else "no reproduce trials on record")
    if after["trials"] == 0:
        reasons.append("no candidate trials on record")
    elif after["passK"] != 1:
        reasons.append(f"after pass^k is {after['passK']} ({after['passes']} of {after['trials']} passed)")
    if regressions is None:
        reasons.append("the regression suite was not run")
    elif regressions:
        reasons.append(f"{regressions} regression case(s) FAIL")
    if not judges:
        reasons.append("no judge verdict on record")
    elif any(j["verdict"] != "earned" for j in judges):
        reasons.append("judge: " + ", ".join(f"{j['taskId'][-6:]} {j['verdict']}" for j in judges if j["verdict"] != "earned"))
    # Same fingerprint on both sides, or the comparison is void: the pack id is the thing under
    # test; the Claude Code version and the served model must match.
    comparison = fingerprint.compare(before["fingerprints"], after["fingerprints"]) if before["trials"] and after["trials"] else {"comparison": "fingerprint-not-recorded", "differences": []}
    if comparison["comparison"] == "invalid-fingerprint":
        reasons.append("invalid-fingerprint: before and after ran on different environments (" + "; ".join(comparison["differences"]) + "); rerun the before side on the current environment")
    judge_cost = round(sum(float(j.get("costUsd") or 0) for j in judges), 4)
    return {
        "v": 1, "case": case_id, "spec": case.get("spec"), "k": case.get("k", after.get("k") or before.get("k")),
        "failureClass": case.get("failureClass"), "reasonCode": case.get("reasonCode"),
        "before": before, "after": after, "regressions": regressions, "casesOutput": cases_output or "",
        "fingerprint": comparison,
        "judge": judges, "fix": fix,
        "costUsd": {"before": before["costUsd"], "after": after["costUsd"], "judge": judge_cost,
                    "interrupted": round(before["interruptedCostUsd"] + after["interruptedCostUsd"], 4),
                    "total": round(before["costUsd"] + after["costUsd"] + judge_cost + before["interruptedCostUsd"] + after["interruptedCostUsd"], 4)},
        "verdict": "SHIP" if not reasons else "NO-SHIP", "reasons": reasons,
        "at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def table(v: dict) -> str:
    out = []
    w = out.append
    b, a = v["before"], v["after"]
    w(f"proof: case {v['case']} (spec {v['spec']}, {v['failureClass']}, reason {v['reasonCode']}), k={v['k']}")
    w(f"fix under test: branch {v['fix']['branch']} at {v['fix']['sha'] or '?'}: {', '.join(v['fix']['files']) or '?'}" + (f" ({v['fix']['diffstat']})" if v['fix'].get('diffstat') else ""))
    w("")
    def row(label: str, left: str, right: str) -> None:
        w(f"{label:<22} {left:<28} {right:<28}")

    row("", "before (current pack)", "after (candidate pack)")
    row("pass^k", str(b["passK"]), str(a["passK"]))
    row("passes", f"{b['passes']} of {b['trials']}" + (f" (+{b['errors']} error)" if b.get("errors") else ""), f"{a['passes']} of {a['trials']}" + (f" (+{a['errors']} error)" if a.get("errors") else ""))
    row("cost", f"${b['costUsd']:.2f}", f"${a['costUsd']:.2f}")
    row("pack", ", ".join(b["packIds"]) or "-", ", ".join(a["packIds"]) or "-")
    row("base", f"{b['base']} {str(b['baseSha'])[:12]}", f"{a['base']} {str(a['baseSha'])[:12]}")
    def fp_text(s: dict) -> str:
        fps = s.get("fingerprints") or []
        if not fps:
            return "not recorded"
        parts = []
        for f in fps:
            m = f.get("servedModel") or {}
            parts.append(f"{f.get('claudeCodeVersion')}; {m.get('author')} / {m.get('reviewer')}")
        return " | ".join(parts)
    row("fingerprint", fp_text(b)[:28], fp_text(a)[:28])
    fpc = v.get("fingerprint") or {}
    w(f"{'comparison':<22} {fpc.get('comparison', 'fingerprint-not-recorded')}" + (": " + "; ".join(fpc.get("differences") or []) if fpc.get("differences") and fpc.get("comparison") == "invalid-fingerprint" else ""))
    w("")
    for name, s in (("before", b), ("after", a)):
        w(f"{name} trials:")
        for r in s["runs"]:
            w(f"  {r['trial']}  {r.get('taskId') or '-':<28} {r['outcome']:<6} checks {'pass' if r.get('checksPass') else 'FAIL'}, reviewer0 {r.get('reviewVerdict0')}, ruff {'pass' if r.get('ruffOk') else str(r.get('ruffFindings')) + ' finding(s)'}, stop blocks {r.get('stopBlocks')}, {r.get('workerTurns')} turns, ${float(r.get('costUsd') or 0):.2f}" + (f"  ({r['why']})" if r.get("why") else ""))
        for x in s.get("interrupted") or []:
            w(f"  -  {x['taskId']:<28} interrupted before its review (no packet, not counted), worker ${float(x.get('costUsd') or 0):.2f}")
    w("")
    w(f"regressions (harness/bin/cases.sh): {v['regressions'] if v['regressions'] is not None else 'not run'}")
    for line in (v.get("casesOutput") or "").splitlines():
        w(f"  {line}")
    w("")
    w("judge (both trajectories, a different model):")
    for j in v["judge"] or []:
        w(f"  {j['taskId']}  {j['verdict']}  ({j.get('model')}, ${float(j.get('costUsd') or 0):.2f}, quote found: {j.get('quoteFound')})")
        if j.get("quote"):
            w(f"    quote: {j['quote'][:300]}")
        for r in j.get("reasons") or []:
            w(f"    - {r}")
    if not v["judge"]:
        w("  none")
    w("")
    c = v["costUsd"]
    w(f"spend: before ${c['before']:.2f}, after ${c['after']:.2f}, judge ${c['judge']:.2f}, interrupted ${c.get('interrupted', 0):.2f}, total ${c['total']:.2f}")
    w(f"verdict: {v['verdict']}" + (": " + "; ".join(v["reasons"]) if v["reasons"] else " (reproduced, after pass^k 1, no regression, every judge verdict earned)"))
    return "\n".join(out)


def write_case(root: Path, v: dict) -> Path:
    p = root / "harness/cases" / f"{v['case']}.json"
    case = load(p) or {"id": v["case"], "kind": "trajectory"}
    case["proof"] = {
        "k": v["k"],
        "before": {k: v["before"][k] for k in ("passK", "passes", "trials", "errors", "costUsd", "base", "baseSha", "packIds")},
        "after": {k: v["after"][k] for k in ("passK", "passes", "trials", "errors", "costUsd", "base", "baseSha", "packIds")},
        "regressions": v["regressions"],
        "judge": [{"taskId": j["taskId"], "verdict": j["verdict"], "model": j.get("model")} for j in v["judge"]],
        "verdict": v["verdict"], "reasons": v["reasons"], "at": v["at"],
        "provenAt": v["at"] if v["verdict"] == "SHIP" else None,
        "record": f"runs/proofs/{v['case']}/verdict.json (copy: demo/recordings/proof/{v['case']}/)",
    }
    if v["verdict"] == "SHIP":
        case["status"] = "proven"
        case["fixedIn"] = f"{v['fix']['branch']} ({v['fix']['sha']}), merged to main: {', '.join(v['fix']['files'])}"
        case["provenAt"] = v["at"]
    else:
        # The mistake was shown; the fix tried did not clear the case. The case stays as it is.
        case["status"] = "reproduced, not fixed" if v["before"]["trials"] and v["before"]["passes"] < v["before"]["trials"] else "not reproduced"
    p.write_text(json.dumps(case, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def record(root: Path, case_id: str) -> Path:
    """Copy the proof folder (without bundles) to demo/recordings/proof/<case>/, replacing an older copy."""
    src = root / "runs/proofs" / case_id
    dst = root / "demo/recordings/proof" / case_id
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("result.bundle", "judge-config", "__pycache__", "*.stderr"))
    return dst


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("root")
    ap.add_argument("case")
    ap.add_argument("--fix-branch")
    ap.add_argument("--cases-output", help="file holding harness/bin/cases.sh output")
    ap.add_argument("--write-case", action="store_true")
    ap.add_argument("--record", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    cases_out = Path(a.cases_output).read_text(encoding="utf-8") if a.cases_output else None
    v = build(root, a.case, a.fix_branch, cases_out)
    pdir = root / "runs/proofs" / a.case
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "verdict.json").write_text(json.dumps(v, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    text = table(v)
    (pdir / "verdict.txt").write_text(text + "\n", encoding="utf-8")
    print(text)
    if a.write_case:
        print(f"case updated: {write_case(root, v).relative_to(root)}")
    if a.record:
        print(f"recorded: {record(root, a.case).relative_to(root)}")
    return 0 if v["verdict"] == "SHIP" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
