#!/usr/bin/env python3
"""The verdict table of one proof: before pass^k, after pass^k, regressions, cost, judge verdicts.

    proof.py <repo root> <case id> [--fix-branch BRANCH] [--cases-output FILE] [--write-case] [--record]
                                   [--min-detectable-delta F] [--objective performance|cost-at-parity] [--block-on-leak]

Reads runs/proofs/<case>/current/summary.json (the reproduce step), runs/proofs/<case>/candidate/
summary.json (the prove step), runs/proofs/<case>/control/summary.json when present (the
no-change control: the current pack run a second time, so the spread between the two
current-pack runs is a measured noise floor), the case's held-out cases' summaries when the
case names a "holdout" list, every candidate trial's judge.json (both trajectories) and the
regression suite's output (harness/bin/cases.sh, saved to a file), and writes
runs/proofs/<case>/verdict.json and verdict.txt.

SHIP only when: the case failed at least once on the current pack (reproduced), after pass^k is
1, the regression suite has no FAIL, every judge verdict is "earned" (at least one judge), the
fingerprints of before and after agree beyond the pack id, and, when a control arm exists, the
after-minus-before delta is outside the noise floor (inside it is "too-small-to-see").
The held-out delta is reported apart when a holdout exists; "no holdout: suite too small"
otherwise. Anything else is NO-SHIP with the reasons named. --write-case puts the proof on the case in
harness/cases/<case>.json (proof, status, fixedIn, provenAt) whatever the verdict, so the suite
lists it; --record copies the proof folder (without bundles) to demo/recordings/proof/.

Rigor from Anthropic's "Automating Eval Design and Hillclimbing with Claude" (DEMO.md, "Rigor from
the eval design article"; the checks live in rigor.py). The verdict JSON gains: minDetectableDelta
(--min-detectable-delta, default 0.1; a control arm whose noise floor exceeds it makes the verdict
`noise-too-high`), suite {baselinePassRate, saturated, objectiveSuggestion}, impossibleOrAmbiguous,
graderAgreement {runs, agreed, disagreeing} (null without a judge), rule {trainDelta, heldOutDelta,
decision: keep | revert | overfit-suspected} (informational, whenever a holdout exists), leaks (check
`pack-embeds-failure`: warns, and with --block-on-leak the verdict is `pack-embeds-failure`),
objective (--objective performance|cost-at-parity; under cost-at-parity a candidate whose accuracy
is within the noise floor but whose mean cost per trial is not lower by more than the control arm's
cost spread is `cost-not-lower`), and `judge-not-independent` when a judge is the model that ran
the trial. These special verdicts replace SHIP/NO-SHIP: nothing was proven, nothing was disproven.
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
import rigor  # noqa: E402


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


def rate(s: dict) -> float | None:
    return round(s["passes"] / s["trials"], 4) if s.get("trials") else None


def control_arm(before: dict, control: dict | None, after: dict) -> dict:
    """The noise floor: the spread between the two current-pack runs (reproduce and control).
    A delta inside it is too small to see. Without a control arm the floor is not measured."""
    if not control or not control.get("trials") or not before["trials"]:
        return {"present": False, "note": "no control arm: noise floor not measured (case-run.sh --pack control runs the current pack again)",
                "noiseFloor": None, "delta": None, "tooSmallToSee": False, "control": control}
    floor = round(abs(rate(before) - rate(control)), 4)
    delta = round(rate(after) - rate(before), 4) if after["trials"] else None
    too_small = delta is not None and abs(delta) <= floor
    return {"present": True, "noiseFloor": floor, "delta": delta, "tooSmallToSee": too_small,
            "beforeRate": rate(before), "controlRate": rate(control), "afterRate": rate(after) if after["trials"] else None, "control": control}


def cost_arm(before_summary: dict | None, after_summary: dict | None, control_summary: dict | None) -> dict:
    """Mean cost per trial on each side, and the control arm's cost spread (the current pack twice)."""
    b, a, c = (rigor.mean_cost(x) for x in (before_summary, after_summary, control_summary))
    spread = round(abs(b - c), 4) if b is not None and c is not None else 0.0
    return {"before": b, "after": a, "control": c, "spread": spread,
            "lower": b is not None and a is not None and (b - a) > spread}


def git_pack_diff(root: Path, branch: str | None) -> str:
    """The branch's diff against main restricted to the pack and hook paths."""
    if not branch or not git(root, "rev-parse", "--short", branch):
        return ""
    mb = git(root, "merge-base", "main", branch)
    tip = git(root, "rev-parse", branch)
    base = mb if mb and mb != tip else f"{branch}~1"
    return git(root, "diff", base, branch, "--", *rigor.PACK_PATHS)


def holdout_arm(root: Path, case: dict) -> dict:
    """The held-out cases' delta, apart from the training case's. The improver never reads them."""
    ids = [str(x) for x in (case.get("holdout") or [])]
    if not ids:
        return {"present": False, "note": "no holdout: suite too small", "cases": []}
    rows = []
    b_pass = b_trials = a_pass = a_trials = 0
    for cid in ids:
        b = side(load(root / "runs/proofs" / cid / "current/summary.json"))
        a = side(load(root / "runs/proofs" / cid / "candidate/summary.json"))
        rows.append({"case": cid, "before": {"passes": b["passes"], "trials": b["trials"], "passK": b["passK"]},
                     "after": {"passes": a["passes"], "trials": a["trials"], "passK": a["passK"]},
                     "delta": (round(rate(a) - rate(b), 4) if b["trials"] and a["trials"] else None)})
        b_pass += b["passes"]; b_trials += b["trials"]; a_pass += a["passes"]; a_trials += a["trials"]
    before_rate = round(b_pass / b_trials, 4) if b_trials else None
    after_rate = round(a_pass / a_trials, 4) if a_trials else None
    unrun = [r["case"] for r in rows if r["before"]["trials"] == 0 or r["after"]["trials"] == 0]
    return {"present": True, "cases": rows, "beforeRate": before_rate, "afterRate": after_rate,
            "delta": (round(after_rate - before_rate, 4) if before_rate is not None and after_rate is not None else None),
            "unrun": unrun, "note": ("held-out delta measured on cases the improver never read" if not unrun else
                                     "held-out cases not run on both packs yet: " + ", ".join(unrun) + " (case-run.sh --holdout)")}


def build(root: Path, case_id: str, fix_branch: str | None, cases_output: str | None, *,
          min_detectable_delta: float = rigor.DEFAULT_MIN_DETECTABLE_DELTA, objective: str = "performance",
          block_on_leak: bool = False, pack_diff: str | None = None) -> dict:
    case = load(root / "harness/cases" / f"{case_id}.json") or {}
    pdir = root / "runs/proofs" / case_id
    before_summary = load(pdir / "current/summary.json")
    after_summary = load(pdir / "candidate/summary.json")
    before = side(before_summary)
    after = side(after_summary)
    control_summary = load(pdir / "control/summary.json")
    control = control_arm(before, side(control_summary) if control_summary else None, after)
    holdout = holdout_arm(root, case)
    judges = []
    for r in after["runs"]:
        j = load(pdir / "candidate" / str(r.get("taskId") or "") / "judge.json") if r.get("taskId") else None
        if j:
            judges.append({"taskId": r["taskId"], "verdict": j.get("verdict"), "quote": j.get("quote", ""), "reasons": j.get("reasons", []),
                           "quoteFound": j.get("quoteFound"), "model": j.get("judgeModel") or j.get("model"), "judgeModel": j.get("judgeModel") or j.get("model"),
                           "workerModel": j.get("workerModel"), "judgeBlind": j.get("judgeBlind"), "graderAgreement": j.get("graderAgreement"),
                           "costUsd": j.get("costUsd", 0)})
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
    cost = cost_arm(before_summary, after_summary, control_summary)
    parity = objective == "cost-at-parity"
    floor = control["noiseFloor"] if control["present"] and control["noiseFloor"] is not None else 0.0
    reproduced = before["trials"] > 0 and before["passes"] < before["trials"]
    if not parity and not reproduced:
        reasons.append("not reproduced: the case never failed on the current pack" if before["trials"] else "no reproduce trials on record")
    if parity and not before["trials"]:
        reasons.append("no reproduce trials on record")
    if after["trials"] == 0:
        reasons.append("no candidate trials on record")
    elif parity:
        if before["trials"] and rate(after) < rate(before) - floor:
            reasons.append(f"accuracy fell outside the noise floor: after {rate(after):.2f}, before {rate(before):.2f}, floor {floor:.2f}")
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
    # The no-change control: a delta inside the spread of two current-pack runs is noise.
    if control["present"] and control["tooSmallToSee"] and not parity:
        reasons.append(f"too-small-to-see: after minus before is {control['delta']:+.2f}, inside the noise floor {control['noiseFloor']:.2f} "
                       f"(current pack twice: {control['beforeRate']:.2f} and {control['controlRate']:.2f})")
    # Rigor checks (rigor.py). The gates come first: they say the proof cannot be read, not that it failed.
    gate = rigor.noise_gate(before_summary, control_summary, min_detectable_delta)
    gate_code, gate_reasons = None, []
    if gate["tooNoisy"]:
        gate_code = "noise-too-high"
        gate_reasons.append(f"noise-too-high: the noise floor {gate['noiseFloor']:.2f} is above the minimum detectable delta {min_detectable_delta:.2f}: add repetitions or cases")
    dependent = [j for j in judges if j.get("judgeModel") and j.get("workerModel") and (j["judgeModel"] == j["workerModel"] or j["judgeModel"] in j["workerModel"])]
    if dependent or any(j["verdict"] == "judge-not-independent" for j in judges):
        gate_code = gate_code or "judge-not-independent"
        gate_reasons.append("judge-not-independent: the judge is the model that ran the trial; run judge.sh with another --model")
    per_case = {case_id: {"current": before_summary, "candidate": after_summary, "control": control_summary}}
    for hc in case.get("holdout") or []:
        per_case[str(hc)] = {a: load(root / "runs/proofs" / str(hc) / a / "summary.json") for a in ("current", "candidate", "control")}
    sanity = rigor.suite_sanity(per_case)
    leaks = rigor.leak_scan(pack_diff if pack_diff is not None else git_pack_diff(root, fix_branch or case.get("fixBranch")),
                            [case] + [load(root / "harness/cases" / f"{h}.json") or {"id": str(h)} for h in case.get("holdout") or []])
    if leaks and block_on_leak:
        gate_code = gate_code or "pack-embeds-failure"
        gate_reasons.append("pack-embeds-failure: the pack or hook diff carries a recorded failure or a case id of the cases being proved (" + "; ".join(f"{l['kind']} {l['text'][:60]}" for l in leaks) + ")")
    if parity and not gate_code and not reasons and not cost["lower"]:
        gate_code = "cost-not-lower"
        gate_reasons.append(f"cost-not-lower: mean cost per trial is ${cost['after']:.2f} after against ${cost['before']:.2f} before; it must be lower by more than the control arm's cost spread (${cost['spread']:.2f})")
    elif parity and reasons and not cost["lower"]:
        reasons.append(f"cost-not-lower: ${cost['after']} per trial after against ${cost['before']} before (spread ${cost['spread']})")
    held_cases = holdout["cases"] if holdout.get("present") else []
    train_delta = round(rate(after) - rate(before), 4) if before["trials"] and after["trials"] else None
    rule = (rigor.rule_decision(train_delta, holdout.get("delta") if not holdout.get("unrun") else None, regressions, held_cases)
            if holdout.get("present") else None)
    judge_cost = round(sum(float(j.get("costUsd") or 0) for j in judges), 4)
    control_cost = round(float((control.get("control") or {}).get("costUsd") or 0), 4)
    return {
        "v": 1, "case": case_id, "spec": case.get("spec"), "k": case.get("k", after.get("k") or before.get("k")),
        "failureClass": case.get("failureClass"), "reasonCode": case.get("reasonCode"),
        "before": before, "after": after, "regressions": regressions, "casesOutput": cases_output or "",
        "fingerprint": comparison, "control": control, "holdout": holdout,
        "judge": judges, "fix": fix,
        "minDetectableDelta": min_detectable_delta, "objective": objective,
        "costPerTrial": cost, "suite": sanity["suite"], "impossibleOrAmbiguous": sanity["impossibleOrAmbiguous"],
        "graderAgreement": rigor.grader_agreement(judges), "rule": rule, "leaks": leaks,
        "costUsd": {"before": before["costUsd"], "after": after["costUsd"], "control": control_cost, "judge": judge_cost,
                    "interrupted": round(before["interruptedCostUsd"] + after["interruptedCostUsd"], 4),
                    "total": round(before["costUsd"] + after["costUsd"] + control_cost + judge_cost + before["interruptedCostUsd"] + after["interruptedCostUsd"], 4)},
        "verdict": gate_code or ("SHIP" if not reasons else "NO-SHIP"), "reasons": gate_reasons + reasons,
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
    c = v.get("control") or {}
    if c.get("present"):
        ctl = c.get("control") or {}
        w(f"control (current pack again): {ctl.get('passes')} of {ctl.get('trials')} passed; noise floor {c['noiseFloor']:.2f} "
          f"(reproduce {c['beforeRate']:.2f} vs control {c['controlRate']:.2f}); after minus before {c['delta']:+.2f}"
          + (" -> too small to see" if c["tooSmallToSee"] else " -> outside the noise" if c["delta"] is not None else ""))
    else:
        w(f"control: {c.get('note', 'none')}")
    h = v.get("holdout") or {}
    if h.get("present"):
        w(f"holdout ({len(h['cases'])} case(s) the improver never read): before {h['beforeRate']} after {h['afterRate']}"
          + (f", delta {h['delta']:+.2f}" if h.get("delta") is not None else "") + f"; {h['note']}")
        for r in h["cases"]:
            w(f"  {r['case']:<28} before {r['before']['passes']} of {r['before']['trials']}, after {r['after']['passes']} of {r['after']['trials']}"
              + (f", delta {r['delta']:+.2f}" if r.get("delta") is not None else ""))
    else:
        w(f"holdout: {h.get('note', 'no holdout: suite too small')}")
    w("")
    s = v.get("suite") or {}
    if s:
        w(f"suite: baseline pass rate {s.get('baselinePassRate')}, saturated {s.get('saturated')}"
          + (f" (consider --objective {s['objectiveSuggestion']})" if s.get("objectiveSuggestion") else "")
          + (f"; impossible or ambiguous: {', '.join(v['impossibleOrAmbiguous'])}" if v.get("impossibleOrAmbiguous") else ""))
    w(f"objective: {v.get('objective', 'performance')}, minimum detectable delta {v.get('minDetectableDelta')}"
      + (f"; mean cost per trial ${v['costPerTrial']['before']} before, ${v['costPerTrial']['after']} after" if (v.get("costPerTrial") or {}).get("before") is not None and v["costPerTrial"].get("after") is not None else ""))
    r = v.get("rule")
    if r:
        w(f"rule: train delta {r['trainDelta']}, held-out delta {r['heldOutDelta']} -> {r['decision'] or r.get('note')}")
    for lk in v.get("leaks") or []:
        w(f"leak ({lk['check']}): {lk['kind']} for case {lk['case']}: {lk['text'][:80]}")
    ga = v.get("graderAgreement")
    if ga:
        w(f"grader agreement: {ga['agreed']} of {ga['runs']} judge run(s) agreed, {ga['disagreeing']} disagreeing")
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
    w(f"spend: before ${c['before']:.2f}, after ${c['after']:.2f}, control ${c.get('control', 0):.2f}, judge ${c['judge']:.2f}, interrupted ${c.get('interrupted', 0):.2f}, total ${c['total']:.2f}")
    w(f"verdict: {v['verdict']}" + (": " + "; ".join(v["reasons"]) if v["reasons"] else " (reproduced, after pass^k 1, no regression, every judge verdict earned)" if v["verdict"] == "SHIP" else ""))
    return "\n".join(out)


def write_case(root: Path, v: dict) -> Path:
    p = root / "harness/cases" / f"{v['case']}.json"
    case = load(p) or {"id": v["case"], "kind": "trajectory"}
    case["proof"] = {
        "k": v["k"],
        "before": {k: v["before"][k] for k in ("passK", "passes", "trials", "errors", "costUsd", "base", "baseSha", "packIds")},
        "after": {k: v["after"][k] for k in ("passK", "passes", "trials", "errors", "costUsd", "base", "baseSha", "packIds")},
        "regressions": v["regressions"],
        "fingerprint": (v.get("fingerprint") or {}).get("comparison"),
        "control": ({k: v["control"].get(k) for k in ("noiseFloor", "delta", "tooSmallToSee")} if (v.get("control") or {}).get("present") else None),
        "holdout": ({k: v["holdout"].get(k) for k in ("beforeRate", "afterRate", "delta")} | {"cases": [r["case"] for r in v["holdout"]["cases"]]}
                    if (v.get("holdout") or {}).get("present") else None),
        "judge": [{"taskId": j["taskId"], "verdict": j["verdict"], "model": j.get("model")} for j in v["judge"]],
        "verdict": v["verdict"], "reasons": v["reasons"], "at": v["at"],
        "provenAt": v["at"] if v["verdict"] == "SHIP" else None,
        "record": f"runs/proofs/{v['case']}/verdict.json (copy: demo/recordings/proof/{v['case']}/)",
    }
    if v["verdict"] == "SHIP":
        case["status"] = "proven"
        case["fixedIn"] = f"{v['fix']['branch']} ({v['fix']['sha']}), merged to main: {', '.join(v['fix']['files'])}"
        case["provenAt"] = v["at"]
    elif v["verdict"] != "NO-SHIP":
        pass  # a gate (noise-too-high, judge-not-independent, ...): nothing was measured well enough to change the case's status
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
    ap.add_argument("--min-detectable-delta", type=float, default=rigor.DEFAULT_MIN_DETECTABLE_DELTA)
    ap.add_argument("--objective", choices=("performance", "cost-at-parity"), default="performance")
    ap.add_argument("--block-on-leak", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    cases_out = Path(a.cases_output).read_text(encoding="utf-8") if a.cases_output else None
    v = build(root, a.case, a.fix_branch, cases_out, min_detectable_delta=a.min_detectable_delta, objective=a.objective, block_on_leak=a.block_on_leak)
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
