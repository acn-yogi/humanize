#!/usr/bin/env python3
"""The proving loop's rigor checks, from Anthropic's "Automating Eval Design and Hillclimbing".

Pure functions over records already on disk (summaries, cases, diffs). No model is asked anything.
proof.py, case-run.sh and cases.sh call them; the names here are the names in the verdict JSON.

    rigor.py noise-gate <root> <case id> [--min-detectable-delta 0.1]   pre-flight for case-run.sh --pack candidate
    rigor.py why-hard <case file>                                       refuse a promoted case with no real whyHard
    rigor.py lint-cases <root>                                          WARN/REFUSE lines for cases.sh

Exit 0 when clear, 3 when a pre-flight refuses (the refusal is written to
runs/proofs/<case>/verdict.json and printed as one JSON line), 1 from lint-cases on a REFUSE.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_MIN_DETECTABLE_DELTA = 0.1
SATURATED_AT = 0.95
WHY_HARD_PLACEHOLDER = "TODO: why is this hard"
LEAK_RUN_WORDS = 8
PACK_PATHS = ("harness/pack/", "harness/hooks/", ".claude/workbench/settings.template.json")


def load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def rate(summary: dict | None) -> float | None:
    if not summary or not summary.get("trials"):
        return None
    return round(summary.get("passes", 0) / summary["trials"], 4)


def mean_cost(summary: dict | None) -> float | None:
    """Mean cost per trial: all recorded rows (an error trial still cost what it cost)."""
    if not summary:
        return None
    n = len(summary.get("runs") or []) or ((summary.get("trials") or 0) + (summary.get("errors") or 0))
    return round(float(summary.get("costUsd") or 0) / n, 4) if n else None


# 1. Pre-flight noise gate ---------------------------------------------------------------------

def noise_gate(before: dict | None, control: dict | None, min_detectable_delta: float = DEFAULT_MIN_DETECTABLE_DELTA) -> dict:
    """With a control arm, a noise floor above the smallest delta worth detecting means the proof
    cannot see what it is looking for: add repetitions or cases. Without a control arm: no change."""
    out = {"minDetectableDelta": min_detectable_delta, "controlPresent": False, "noiseFloor": None, "tooNoisy": False}
    rb, rc = rate(before), rate(control)
    if rb is None or rc is None:
        return out
    floor = round(abs(rb - rc), 4)
    out.update({"controlPresent": True, "noiseFloor": floor, "tooNoisy": floor > min_detectable_delta})
    return out


# 2. Suite sanity ------------------------------------------------------------------------------

def suite_sanity(per_case: dict[str, dict[str, dict | None]]) -> dict:
    """per_case: case id -> {arm: summary} for arms current, candidate, control.
    baselinePassRate: passes over conclusive trials of the current pack, across the suite.
    impossibleOrAmbiguous: cases that failed every replicate in every arm (at least two arms ran)."""
    passes = trials = 0
    impossible: list[str] = []
    for cid, arms in per_case.items():
        cur = arms.get("current")
        if cur:
            passes += cur.get("passes", 0)
            trials += cur.get("trials", 0)
        ran = [s for s in arms.values() if s and s.get("trials")]
        if len(ran) >= 2 and all(s.get("passes", 0) == 0 for s in ran):
            impossible.append(cid)
    base = round(passes / trials, 4) if trials else None
    saturated = base is not None and base >= SATURATED_AT
    return {"suite": {"baselinePassRate": base, "saturated": saturated, "objectiveSuggestion": "cost-at-parity" if saturated else None},
            "impossibleOrAmbiguous": impossible}


def grader_agreement(judges: list[dict]) -> dict | None:
    """Pooled over the judge.json files: runs, how many runs matched their trial's final verdict, how many did not."""
    rows = [j.get("graderAgreement") for j in judges if j.get("graderAgreement")]
    if not rows:
        return None
    return {"runs": sum(r["runs"] for r in rows), "agreed": sum(r["agreed"] for r in rows), "disagreeing": sum(r["disagreeing"] for r in rows)}


# 4. Keep, revert or overfit -------------------------------------------------------------------

def rule_decision(train_delta: float | None, held_delta: float | None, regressions: int | None, held_cases: list[dict] | None = None) -> dict:
    """keep: train and held-out both improved and nothing regressed. overfit-suspected: train up with
    held-out flat or down (or one held-out case worse). revert: any regression, or no improvement.
    Informational; decision is null while the held-out arm has not been run on both packs."""
    held_worse = [r["case"] for r in (held_cases or []) if r.get("delta") is not None and r["delta"] < 0]
    out = {"trainDelta": train_delta, "heldOutDelta": held_delta, "decision": None, "heldOutWorse": held_worse}
    if train_delta is None or held_delta is None:
        out["note"] = "held-out arm not run on both packs: no decision"
        return out
    regressed = bool(regressions) or train_delta < 0
    if regressed:
        out["decision"] = "revert"
    elif train_delta > 0 and held_delta > 0 and not held_worse:
        out["decision"] = "keep"
    elif train_delta > 0:
        out["decision"] = "overfit-suspected"
    else:
        out["decision"] = "revert"
    return out


# 5. Leak guards -------------------------------------------------------------------------------

def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9_'\-]+", s.lower())


def failure_quotes(case: dict) -> list[str]:
    """The verbatim failure texts a case carries: audit hits and the next-candidate rejection reasons."""
    out = [str(h.get("text") or "") for h in case.get("hits") or []]
    for rj in (case.get("nextCandidates") or {}).get("rejections") or []:
        out.extend(str(r) for r in rj.get("reasons") or [])
    return [q for q in out if len(_words(q)) >= LEAK_RUN_WORDS]


def added_lines(diff_text: str) -> str:
    return "\n".join(l[1:] for l in diff_text.splitlines() if l.startswith("+") and not l.startswith("+++"))


def leak_scan(diff_text: str, cases: list[dict]) -> list[dict]:
    """check pack-embeds-failure. In the added lines of a pack or hook diff: a run of LEAK_RUN_WORDS
    or more words copied from a recorded failure, or a case id of the cases being proved as a whole word."""
    added = added_lines(diff_text)
    aw = _words(added)
    joined = " " + " ".join(aw) + " "
    hits: list[dict] = []
    for c in cases:
        for q in failure_quotes(c):
            qw = _words(q)
            for i in range(0, len(qw) - LEAK_RUN_WORDS + 1):
                if " " + " ".join(qw[i:i + LEAK_RUN_WORDS]) + " " in joined:
                    hits.append({"check": "pack-embeds-failure", "kind": "failure-quote", "case": c.get("id"), "text": " ".join(qw[i:i + LEAK_RUN_WORDS])})
                    break
        cid = str(c.get("id") or "")
        if cid and re.search(r"(?<![\w-])" + re.escape(cid) + r"(?![\w-])", added):
            hits.append({"check": "pack-embeds-failure", "kind": "case-id", "case": cid, "text": cid})
    return hits


def case_start_warnings(root: Path, case: dict) -> list[str]:
    """cases.sh warning case-start-carries-answer. Trajectory cases only. Two heuristics:
    (1) the case's baseSha already has the fix in its history (the fix commit is an ancestor of it);
    (2) expectedFile at baseSha already contains fixText (both optional case fields)."""
    if case.get("kind") != "trajectory":
        return []
    base = str(case.get("baseSha") or "")
    out: list[str] = []

    def git(*a: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(root), *a], capture_output=True, text=True)

    if base and git("cat-file", "-e", f"{base}^{{commit}}").returncode == 0:
        fix = str(case.get("fixSha") or "")
        if not fix:
            m = re.search(r"\(([0-9a-f]{7,40})\)", str(case.get("fixedIn") or ""))
            fix = m.group(1) if m else ""
        if fix and git("cat-file", "-e", f"{fix}^{{commit}}").returncode == 0:
            full_fix = git("rev-parse", fix).stdout.strip()
            full_base = git("rev-parse", base).stdout.strip()
            if git("merge-base", "--is-ancestor", full_fix, full_base).returncode == 0:
                out.append(f"base {base[:7]} already contains the fix {fix[:7]}: not the pre-fix commit")
        ef, ft = case.get("expectedFile"), case.get("fixText")
        if ef and ft:
            shown = git("show", f"{base}:{ef}")
            if shown.returncode == 0 and str(ft) in shown.stdout:
                out.append(f"{ef} at base {base[:7]} already contains the fix text")
    return out


# 7. Adversarial sampling ----------------------------------------------------------------------

def why_hard_status(case: dict) -> str:
    """ok: a real whyHard. missing: a promoted case (promotedAt set) with none or the placeholder.
    legacy: no whyHard and no promotedAt (warns only)."""
    wh = str(case.get("whyHard") or "").strip()
    real = bool(wh) and wh != WHY_HARD_PLACEHOLDER
    if real:
        return "ok"
    if case.get("promotedAt") or ("whyHard" in case):
        return "missing"
    return "legacy"


def refuse(root: Path, case_id: str, code: str, reasons: list[str], **extra) -> dict:
    v = {"v": 1, "case": case_id, "verdict": code, "reasons": reasons, **extra}
    d = root / "runs/proofs" / case_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "verdict.json").write_text(json.dumps(v, indent=1) + "\n", encoding="utf-8")
    return v


def lint_cases(root: Path) -> tuple[list[str], int]:
    lines: list[str] = []
    refused = 0
    for f in sorted((root / "harness/cases").glob("*.json")):
        case = load(f)
        if not isinstance(case, dict) or case.get("kind") != "trajectory":
            continue
        cid = case.get("id", f.stem)
        st = why_hard_status(case)
        if st == "missing":
            lines.append(f"REFUSE {cid:<24} case-missing-why-hard: write whyHard (a promoted case says why it is hard); the placeholder is not an answer")
            refused += 1
        elif st == "legacy":
            lines.append(f"WARN  {cid:<24} legacy-no-why-hard: add whyHard when this case is next touched")
        for w in case_start_warnings(root, case):
            lines.append(f"WARN  {cid:<24} case-start-carries-answer: {w}")
    return lines, refused


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("noise-gate")
    g.add_argument("root")
    g.add_argument("case")
    g.add_argument("--min-detectable-delta", type=float, default=DEFAULT_MIN_DETECTABLE_DELTA)
    w = sub.add_parser("why-hard")
    w.add_argument("case_file")
    lc = sub.add_parser("lint-cases")
    lc.add_argument("root")
    a = ap.parse_args(argv)
    if a.cmd == "noise-gate":
        root = Path(a.root)
        pd = root / "runs/proofs" / a.case
        gate = noise_gate(load(pd / "current/summary.json"), load(pd / "control/summary.json"), a.min_detectable_delta)
        if gate["tooNoisy"]:
            v = refuse(root, a.case, "noise-too-high",
                       [f"noise floor {gate['noiseFloor']:.2f} is above the minimum detectable delta {gate['minDetectableDelta']:.2f}: add repetitions or cases"],
                       minDetectableDelta=gate["minDetectableDelta"], noiseFloor=gate["noiseFloor"])
            print(json.dumps(v))
            return 3
        print(json.dumps(gate))
        return 0
    if a.cmd == "why-hard":
        case = load(Path(a.case_file)) or {}
        st = why_hard_status(case)
        if st == "missing":
            root = Path(a.case_file).resolve().parents[2]
            v = refuse(root, case.get("id", Path(a.case_file).stem), "case-missing-why-hard",
                       ["a promoted case needs a written whyHard before it runs; it is missing or still the placeholder"])
            print(json.dumps(v))
            return 3
        if st == "legacy":
            print("legacy-no-why-hard", file=sys.stderr)
        return 0
    lines, refused = lint_cases(Path(a.root))
    for l in lines:
        print(l)
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
