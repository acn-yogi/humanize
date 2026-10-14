#!/usr/bin/env python3
"""The failure class and stall category of a halted task, from signals already on record.

    stall.py <task run dir> --retries N --retry-cap M     -> {failureClass, stall, evidence, atCap}

Every halt carries a failure class from a closed set, and the ledger and the scorecard report
the four apart, never as one failure rate:

    harness-error   a session ended on an API, network or sandbox error, or the run failed
    refusal         the author declined the task and changed nothing
    timeout         the session hit the wall clock
    genuine         none of the above: the work ran and did not pass

A task that reaches the retry cap also carries a stall category, so the next queue pass does
not spend the same again on the same spec:

    artifact-gap          the session lacked something the spec assumed (a fixture, a module, a credential)
    grader-disagreement   the checks and the reviewer want different things: the same acceptance
                          failure twice with the reviewer approving, or the checks passing in every
                          round while the reviewer rejected two of them
    harness-or-infra      the halt is a harness or serving error, not the spec's
    structural            the spec contradicts itself, or the scope cuts the change off from the
                          paths it needs (scope denials or an out-of-scope diff on them)
    variance              the checks passed on one attempt and failed on another with no structural cause

Structural is read after every rejected round, not only at the cap: workbench.sh stops the retry
loop on it and writes the halt with reason stall-structural. Everything here is read from
sessions.json, rounds.jsonl, loops.jsonl, scope.json, facts.json, plan.json and the worker
transcript's final message. No model is asked anything. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

FAILURE_CLASSES = ("harness-error", "refusal", "timeout", "genuine")
STALLS = ("artifact-gap", "grader-disagreement", "harness-or-infra", "structural", "variance")

# Exit codes of coreutils timeout: 124 on the time limit, 137 when the kill-after fired.
TIMEOUT_EXITS = {124, 137}
CAP_SUBTYPES = {"error_max_turns", "error_max_budget_usd"}
REFUSAL_RE = re.compile(r"\b(I (can(?:no|')t|won't|will not|am not able to|'m not able to|must decline|decline to)|not something I can|I(?:'m| am) unable to)\b", re.I)
# A contradiction inside the spec, between its own parts. "The change contradicts the spec" is a
# reviewer's finding about the change, not this; the patterns need two spec parts, or the spec
# against itself.
CONTRADICTION_RE = re.compile(
    r"(?:\b(?:spec|criteria|criterion|constraints?|sections?|requirements?)\b[^.\n]{0,80}\bcontradicts? (?:each other|one another|itself)\b"
    r"|\bcontradict(?:ion|ory)\b [^.\n]{0,20}\b(?:in|within|between|inside) (?:the |its |two )?(?:own )?(?:spec|criteria|constraints?|sections?|requirements?)\b"
    r"|\bspec (?:contradicts itself|is self-contradictory|is inconsistent with itself)\b"
    r"|\bmutually exclusive\b"
    r"|\b(?:cannot|can't|can not) (?:both|satisfy both|meet both|be met together)\b"
    r"|\bno (?:change|implementation|code) [^.\n]{0,40}\bsatisf(?:y|ies) both\b"
    r"|\bconflict(?:s|ing)? between (?:the |two )?(?:spec|constraints?|criteria|requirements?|sections?)\b)", re.I)
ARTIFACT_RE = re.compile(
    r"\b(No such file|not found|No module named|ModuleNotFoundError|ImportError|not installed|command not found|"
    r"missing (?:fixture|file|dependency|credential|module|package|data)|permission denied|could not find|does not exist|"
    r"no (?:fixture|credential|API key|token|dataset) (?:was )?(?:available|provided|present))\b", re.I)
PATH_RE = re.compile(r"(?<![\w/.-])((?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z0-9]+)")


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def final_texts(transcript: Path) -> list[str]:
    """The final message of each worker session in a stream-json transcript (one per round)."""
    out: list[str] = []
    last_text = ""
    for ev in read_jsonl(transcript):
        if ev.get("type") == "assistant":
            msg = ev.get("message") or {}
            for block in msg.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text":
                    last_text = str(block.get("text") or "")
        elif ev.get("type") == "result":
            out.append(str(ev.get("result") or "") or last_text)
            last_text = ""
    if last_text:
        out.append(last_text)
    return out


def check_paths(plan: dict) -> list[str]:
    """Repository paths an acceptance or fail-first check names (not the harness's own files)."""
    paths: list[str] = []
    checks = plan.get("checks") or {}
    for cmd in list(checks.get("acceptance") or []) + list(checks.get("failFirst") or []) + list(checks.get("mustNotChange") or []):
        for tok in str(cmd).split():
            if "{harness}" in tok or tok.startswith("-"):
                continue
            m = PATH_RE.search(tok)
            if m and m.group(1) not in paths:
                paths.append(m.group(1))
    return paths


def read_record(rdir: Path) -> dict:
    plan = read_json(rdir / "plan.json", {})
    facts = read_json(rdir / "facts.json", {})
    return {
        "sessions": read_json(rdir / "sessions.json", []),
        "rounds": read_jsonl(rdir / "rounds.jsonl"),
        "loops": read_jsonl(rdir / "loops.jsonl"),
        "scope": read_json(rdir / "scope.json", {"outside": [], "harness": []}),
        "checks": facts.get("checks") or [],
        "authorTexts": final_texts(rdir / "transcript.jsonl"),
        "checkPaths": check_paths(plan),
        "changedPaths": facts.get("changedPaths") or [],
    }


def failure_class(rec: dict) -> tuple[str, str]:
    workers = [s for s in rec.get("sessions") or [] if s.get("role") == "worker"]
    for s in workers:
        if int(s.get("exit") or 0) in TIMEOUT_EXITS or "timeout" in str(s.get("subtype") or ""):
            return "timeout", f"worker round {s.get('round')}: exit {s.get('exit')} ({s.get('subtype') or 'timed out'})"
    for s in workers:
        sub = str(s.get("subtype") or "")
        result = str(s.get("result") or "")
        if s.get("isError") or result.startswith("API Error") or (sub.startswith("error") and sub not in CAP_SUBTYPES) \
                or (int(s.get("exit") or 0) != 0):
            return "harness-error", f"worker round {s.get('round')}: {sub or 'error'}, exit {s.get('exit')}" + (f", {result[:120]}" if result else "")
    for ev in rec.get("loops") or []:
        if ev.get("loop") == "task" and ev.get("event") == "run-failed":
            return "harness-error", f"run-failed: {ev.get('reason') or ev.get('note') or 'the run did not finish'}"
    texts = rec.get("authorTexts") or []
    rounds = rec.get("rounds") or []
    last_changed = rounds[-1].get("changedPaths") if rounds else rec.get("changedPaths")
    if texts and REFUSAL_RE.search(texts[-1]) and not last_changed:
        return "refusal", f"the author declined and changed nothing: {REFUSAL_RE.search(texts[-1]).group(0)!r}"
    return "genuine", "the work ran and did not pass"


def structural(rec: dict) -> str | None:
    """The evidence of a structural stall, or None."""
    texts = rec.get("authorTexts") or []
    for i, t in enumerate(texts):
        m = CONTRADICTION_RE.search(t)
        if m:
            start = max(0, m.start() - 60)
            return f"the author's final message (round {i}) names a contradiction in the spec: {t[start:m.end() + 60].strip()!r}"
    needed = set(rec.get("checkPaths") or [])
    for p in rec.get("changedPaths") or []:
        needed.add(p)
    rounds = rec.get("rounds") or []
    rejected_rounds = {r.get("round") for r in rounds if r.get("path") == "reject" or ((r.get("verdict") or {}).get("verdict") == "reject")}
    rnd = 0
    denied: list[str] = []
    for ev in rec.get("loops") or []:
        if ev.get("loop") == "retry":
            rnd = int(ev.get("round", rnd + 1))
        if ev.get("loop") == "scope" and ev.get("decision") == "deny" and (rnd in rejected_rounds or not rounds):
            path = str(ev.get("path") or "")
            if path in needed or any(path.endswith(f"test_{Path(p).stem}.py") for p in needed) or any(mentions(path, t) for t in texts):
                denied.append(path)
    if denied:
        return "scope denials on paths the change needs: " + ", ".join(sorted(set(denied)))
    outside = [p for p in (rec.get("scope") or {}).get("outside") or [] if p in needed]
    if outside:
        return "the diff needs paths outside the spec's scope: " + ", ".join(outside)
    return None


def mentions(path: str, text: str) -> bool:
    return bool(path) and path in text and bool(re.search(r"\b(import|call|caller|uses?|needs?|outside (?:the )?scope|refused|denied)\b", text, re.I))


def stall_category(rec: dict, fclass: str) -> tuple[str, str]:
    if fclass in ("harness-error", "timeout"):
        return "harness-or-infra", "the halt is a harness or serving error, not the spec's"
    why = structural(rec)
    if why:
        return "structural", why
    rounds = rec.get("rounds") or []
    passes = [bool(r.get("allChecksPass")) for r in rounds]
    approvals = [(r.get("verdict") or {}).get("verdict") for r in rounds]
    failing: list[set[str]] = []
    for r in rounds:
        cmds = {str(c.get("cmd")) for c in (r.get("checks") or []) if c.get("exit") not in (0, None)}
        failing.append(cmds)
    repeated = set()
    for i in range(1, len(rounds)):
        if approvals[i] == "approve" and approvals[i - 1] == "approve":
            repeated |= failing[i] & failing[i - 1]
    if repeated:
        return "grader-disagreement", "the same acceptance check failed twice with the reviewer approving: " + ", ".join(sorted(repeated))
    if len(rounds) >= 2 and all(passes) and approvals.count("reject") >= 2:
        return "grader-disagreement", "the checks passed in every round and the reviewer rejected two of them"
    if len(set(passes)) > 1:
        return "variance", "the trusted checks passed on one attempt and failed on another: " + ", ".join("pass" if p else "FAIL" for p in passes)
    for i, t in enumerate(rec.get("authorTexts") or []):
        m = ARTIFACT_RE.search(t)
        if m:
            return "artifact-gap", f"the author's final message (round {i}) names something missing: {m.group(0)!r}"
    return "artifact-gap", "no stronger signal: the session ran to the cap without the checks and the reviewer agreeing; something the spec assumed was not there"


def classify(rec: dict, retries: int, retry_cap: int) -> dict:
    fclass, evidence = failure_class(rec)
    at_cap = retries >= retry_cap
    stall = None
    stall_evidence = None
    if fclass in ("harness-error", "timeout"):
        stall, stall_evidence = stall_category(rec, fclass)
    else:
        why = structural(rec)
        if why:
            stall, stall_evidence = "structural", why
        elif at_cap:
            stall, stall_evidence = stall_category(rec, fclass)
    return {"failureClass": fclass, "evidence": evidence, "stall": stall, "stallEvidence": stall_evidence, "atCap": at_cap,
            "retries": retries, "retryCap": retry_cap}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("rdir")
    ap.add_argument("--retries", type=int, default=0, help="retry rounds run so far")
    ap.add_argument("--retry-cap", type=int, default=0, help="the retry cap (caps.retries)")
    a = ap.parse_args(argv)
    print(json.dumps(classify(read_record(Path(a.rdir)), a.retries, a.retry_cap)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
