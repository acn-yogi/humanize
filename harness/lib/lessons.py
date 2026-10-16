#!/usr/bin/env python3
"""The lessons ledger: what was found, who decided what to do with it, and whether it came back.

    lessons.py [--cwd DIR] [--lessons FILE] draft [--ledger FILE] [--proofs DIR...] [--roots DIR...] [--no-audit]
    lessons.py list [--status S] [--source S] [--json]
    lessons.py approve <id> --by NAME [--portable]       a person only: refused under HARNESS_AGENT_SESSION=1
    lessons.py reject  <id> --by NAME [--reason TEXT]    a person only
    lessons.py route [<id>...] [--change-path P]
    lessons.py start <id> --by NAME
    lessons.py close <id> --by NAME (--proof VERDICT.json | --pr REF [--prs FILE])
    lessons.py seed (--out FILE | --in FILE) [--deny WORD...]

runs/lessons.jsonl is append-only: a change of state appends a new row for the same id, readers
fold by id and the last row wins. Three feeds draft lessons from records already on disk (proof
verdicts and audit codes; halted ledger rows, rejected reviews, failing trusted checks and stall
review items; corrected ledger rows). Nothing here asks a model anything, and nothing spends.
DEMO.md, "The lessons ledger", is the design. Standard library only.

Exit 0 done, 1 refused (a rule above), 2 refused because an agent session is running (or usage),
3 routing refused because the change would touch a guardrail.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit  # noqa: E402

SOURCES = ("eval-fail", "test-fail", "human-correction", "build-retro", "external")
WEIGHTS = {"human-correction": 3, "eval-fail": 2, "test-fail": 1, "build-retro": 2, "external": 2}
STATUSES = ("draft", "approved", "routed", "in-progress", "closed", "recurred", "rejected")
OPEN_STATUSES = ("draft", "approved", "routed", "in-progress", "recurred")
DISPOSITIONS = ("case", "spec", "pack", "code", "parked", "none")
AGENT_ENV = "HARNESS_AGENT_SESSION"
DEFAULT_PROOF_DIRS = ("runs/proofs", "demo/recordings/proof")
DEFAULT_AUDIT_ROOTS = ("runs", "demo/recordings")
SKIPPED_AUDIT_CODES = {"STOP_HOOK_BLOCKED"}  # loop 2 doing its job is not a lesson

# Paths a lesson may never change through routing: guardrails, settings, the scope hook, the kill switch.
GUARDED = (
    re.compile(r"(^|/)harness/guardrails(/|$)"),
    re.compile(r"(^|/)[^/]*settings[^/]*\.(json|toml)$", re.I),
    re.compile(r"(^|/)managed-settings", re.I),
    re.compile(r"(^|/)harness/hooks/scope", re.I),
    re.compile(r"(^|/)HALT$"),
    re.compile(r"kill[-_]?switch", re.I),
)
# The only places routing writes.
WRITABLE = ("harness/cases/drafts/", "specs/drafts/", "runs/lessons.jsonl")

REASON_TEXT = {
    "lint": "lint findings", "test": "missing or wrong tests", "scope": "a change outside the intended scope",
    "wrong-behaviour": "behaviour that is wrong", "style": "style", "question": "a question about the change",
    "other": "another reason",
}
PROOF_TEXT = {
    "noise-too-high": "The proof stopped: the control arm's noise floor is above the smallest delta worth detecting",
    "overfit-suspected": "The proof's keep-or-revert rule suspects overfitting: train up with held-out flat or down",
    "impossible-or-ambiguous": "A case failed every replicate in every arm: it is impossible or its check is ambiguous",
    "grader-disagreement": "The judge disagreed with itself across repeated runs on one output",
    "cost-not-lower": "A candidate under the cost-at-parity objective did not cost less per trial",
    "judge-not-independent": "The judge was the model that ran the trial",
    "NO-SHIP": "A proof ended NO-SHIP and was kept on record",
}
AUDIT_PACK = {"LINT_FAILED", "NO_TOOL_CALL", "IGNORED_ERROR", "UNSOURCED_SPECIFIC", "CLAIMED_SUCCESS_NO_STATE"}
AUDIT_SPEC = {"SPEC_CONTRADICTION", "SCOPE_BLOCKS_FIX"}
AUDIT_CODE = {"MODEL_MISMATCH", "SESSION_ERROR"}


class LessonError(Exception):
    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def agent_session(env: dict | None = None) -> bool:
    return str((env if env is not None else os.environ).get(AGENT_ENV, "")).strip().lower() in ("1", "true", "yes")


def require_person(action: str, by: str | None, env: dict | None = None) -> str:
    if agent_session(env):
        raise LessonError(
            f"lessons: refusing to {action} under an agent session ({AGENT_ENV}=1). A lesson is "
            f"approved or rejected by a person in their own terminal; agents cannot approve their own lessons.", 2)
    if not by or not by.strip():
        raise LessonError(f"lessons: {action} needs --by <name>, the person who decides", 2)
    return by.strip()


# The file ---------------------------------------------------------------------------------------

def read_rows(path: Path) -> list[dict]:
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def append_rows(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def fold(rows: list[dict]) -> dict[str, dict]:
    """The last row per id, in order of first appearance."""
    out: dict[str, dict] = {}
    for r in rows:
        if r.get("id"):
            out[r["id"]] = r
    return out


def history(rows: list[dict]) -> dict[str, list[dict]]:
    h: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("id"):
            h.setdefault(r["id"], []).append(r)
    return h


def normalize(text: str) -> str:
    t = text.lower()
    t = re.sub(r"https?://\S+", "<url>", t)
    t = re.sub(r"\bt-[0-9a-hjkmnp-tv-z]{26}\b", "<task>", t)
    t = re.sub(r"\b[0-9a-f]{7,40}\b", "<hash>", t)
    t = re.sub(r"(?<![\w/.-])(?:[\w.-]+[/\\])+[\w.-]+", "<path>", t)
    t = re.sub(r"\d+(?:\.\d+)?", "<n>", t)
    return re.sub(r"\s+", " ", t).strip()


def signature(cls: str, finding: str) -> str:
    return hashlib.sha1(f"{cls}|{normalize(finding)}".encode("utf-8")).hexdigest()


def lesson_id(sig: str) -> str:
    return "les-" + sig[:8]


def new_row(prev: dict | None, ts: str, **changes) -> dict:
    row = json.loads(json.dumps(prev)) if prev else {}
    row.update(changes)
    row["ts"] = ts
    return row


# Disposition rules ------------------------------------------------------------------------------

def propose(kind: str, cls: str, detail: str, recurrences: int) -> str:
    """The proposed disposition. kind: audit, halt, review, checks, continue, proof, human."""
    recurring = recurrences >= 2
    if kind == "audit":
        if cls == "REVIEW_REJECTED":
            return "case" if recurring else "parked"
        if cls in AUDIT_SPEC:
            return "spec"
        if cls in AUDIT_PACK:
            return "pack"
        if cls in AUDIT_CODE:
            return "code"
        return "parked"
    if kind in ("review", "checks", "continue"):
        return "case" if recurring else "parked"
    if kind == "halt":
        fclass, _, stall = detail.partition("|")
        if stall in ("structural", "artifact-gap"):
            return "spec"
        if stall in ("harness-or-infra", "grader-disagreement"):
            return "code"
        if stall == "variance":
            return "none"
        if fclass in ("harness-error", "timeout"):
            return "code"
        if fclass == "refusal":
            return "pack"
        if fclass == "genuine":
            return "case" if recurring else "parked"
        return "parked"
    if kind == "proof":
        if cls in ("noise-too-high", "impossible-or-ambiguous"):
            return "case"
        if cls in ("judge-not-independent", "grader-disagreement"):
            return "code"
        return "pack"  # NO-SHIP, cost-not-lower, overfit-suspected: a proof refusal
    if kind == "human":
        return {"lint": "pack", "style": "pack", "test": "case", "wrong-behaviour": "case",
                "scope": "spec", "question": "none"}.get(cls, "parked")
    return "parked"


# Candidates from the feeds ----------------------------------------------------------------------

@dataclass
class Cand:
    source: str
    kind: str
    cls: str
    finding: str
    occ: str                       # the occurrence key: a task, a proof verdict, a comment
    evidence: list[str] = field(default_factory=list)
    ts: str | None = None
    detail: str = ""
    disposition: str | None = None  # an override (seeded lessons keep theirs)
    portable: bool = False


def audit_finding(code: str) -> str:
    return f"Audit {code}: {audit.DESCRIPTION[code]}"


def rel(p: Path, cwd: Path) -> str:
    try:
        return p.resolve().relative_to(cwd.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def feed_audit(cwd: Path, roots: list[Path]) -> list[Cand]:
    report = audit.audit(roots, cwd)
    out = []
    for c in report["classes"]:
        if c["code"] in SKIPPED_AUDIT_CODES:
            continue
        for h in c["items"]:
            occ = f"task:{h['taskId']}"
            where = h["file"] + (f":{h['line']}" if h.get("line") else "")
            out.append(Cand("eval-fail", "audit", c["code"], audit_finding(c["code"]), occ, [occ, where], None))
    return out


def feed_proofs(cwd: Path, dirs: list[Path]) -> list[Cand]:
    out = []
    for d in dirs:
        for f in sorted(d.glob("*/verdict.json")) if d.exists() else []:
            try:
                v = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            case, at, ev = v.get("case") or f.parent.name, v.get("at"), rel(f, cwd)

            def add(code: str, cls: str | None = None) -> None:
                occ = f"proof:{case}:{code}@{at}"
                out.append(Cand("eval-fail", "proof", cls or code, f"Proof verdict {code}: {PROOF_TEXT[code]}", occ, [occ, ev], at, detail=code))

            verdict = v.get("verdict")
            if verdict in ("noise-too-high", "judge-not-independent", "cost-not-lower"):
                add(verdict)
            elif verdict == "NO-SHIP":
                add("NO-SHIP", v.get("failureClass") or "NO-SHIP")
            if (v.get("rule") or {}).get("decision") == "overfit-suspected":
                add("overfit-suspected")
            if v.get("impossibleOrAmbiguous"):
                add("impossible-or-ambiguous")
            ga = v.get("graderAgreement") or {}
            if ga.get("disagreeing"):
                add("grader-disagreement")
    return out


REVIEW_RE = re.compile(r"adversarial review raised findings|reviewer.*reject", re.I)
CHECKS_RE = re.compile(r"trusted checks? failed|acceptance checks? failed", re.I)


def feed_ledger(cwd: Path, ledger: Path) -> list[Cand]:
    out = []
    for r in read_rows(ledger):
        at = r.get("at")
        if r.get("event") == "corrected":
            reason = r.get("reasonCode") or "other"
            occ = r.get("url") or ("correction:" + json.dumps({k: r.get(k) for k in ("taskId", "action", "reasonCode", "note")}, sort_keys=True))
            ev = [occ] + ([f"task:{r['taskId']}"] if r.get("taskId") else [])
            out.append(Cand("human-correction", "human", reason, f"A person corrected the work: {REASON_TEXT.get(reason, reason)}", occ, ev, at, detail=reason))
            continue
        task = r.get("taskId")
        if not task or r.get("event") is not None or "costUsd" not in r:
            continue
        occ = f"task:{task}"
        ev = [occ, f"{rel(ledger, cwd)}#{task}"]
        reasons = " ; ".join(str(x) for x in (r.get("reasons") or []))
        if r.get("path") == "reject":
            fclass, stall = r.get("failureClass"), r.get("stall")
            cls = stall or fclass or "unclassified"
            finding = f"A task halted with failure class {fclass or 'unclassified'}" + (f" and stall category {stall}" if stall else "")
            out.append(Cand("test-fail", "halt", cls, finding, occ, ev, at, detail=f"{fclass or ''}|{stall or ''}"))
        if REVIEW_RE.search(reasons):
            out.append(Cand("test-fail", "review", "REVIEW_REJECTED", audit_finding("REVIEW_REJECTED"), occ, ev, at))
        if CHECKS_RE.search(reasons):
            out.append(Cand("test-fail", "checks", "CHECKS_FAILED", "Trusted checks failed on a task", occ, ev, at))
        cw = (r.get("stallReview") or {}).get("continueWith") or []
        if cw:
            out.append(Cand("test-fail", "continue", "genuine-continue",
                            "Genuine failures remained after two flat rejected attempts", f"{occ}:continue", ev, at))
    return out


# Drafting ---------------------------------------------------------------------------------------

def apply(rows: list[dict], cands: list[Cand], stamp: str) -> list[dict]:
    """The rows to append for these candidates. Pure over rows; running it again on the result adds nothing."""
    cur = fold(rows)
    added: list[dict] = []
    for c in sorted(cands, key=lambda c: (c.ts or "", c.occ)):
        sig = signature(c.cls, c.finding)
        lid = lesson_id(sig)
        prev = cur.get(lid)
        weight = WEIGHTS[c.source]
        if prev is None:
            row = {"id": lid, "ts": stamp, "source": c.source, "sourceRef": c.occ, "finding": c.finding, "class": c.cls,
                   "signature": sig, "evidence": list(dict.fromkeys([c.occ] + c.evidence)),
                   "proposedDisposition": c.disposition or propose(c.kind, c.cls, c.detail, 1), "status": "draft",
                   "links": {"caseId": None, "specId": None, "packId": None, "prRef": None},
                   "recurrences": 1, "portable": c.portable, "weight": weight, "approvedBy": None, "closedBy": None, "note": ""}
        else:
            if c.occ in prev.get("evidence", []) or prev["status"] == "rejected":
                continue
            ev = list(dict.fromkeys(prev.get("evidence", []) + [c.occ] + c.evidence))
            changes = {"evidence": ev, "recurrences": prev["recurrences"] + 1, "weight": max(prev["weight"], weight)}
            status = prev["status"]
            if status == "draft" and not c.disposition:
                changes["proposedDisposition"] = propose(c.kind, c.cls, c.detail, changes["recurrences"])
            if status == "closed" and (c.ts is None or c.ts > prev["ts"]):
                changes["status"] = "recurred"
                changes["note"] = f"recurred after close: {c.occ}"
            row = new_row(prev, stamp, **changes)
        cur[lid] = row
        added.append(row)
    return added


def draft(cwd: Path, lessons: Path, ledger: Path | None = None, proof_dirs: list[Path] | None = None,
          roots: list[Path] | None = None, use_audit: bool = True, stamp: str | None = None) -> tuple[list[dict], list[str]]:
    cands: list[Cand] = []
    notes: list[str] = []
    ledger = ledger or cwd / "runs/ledger.jsonl"
    proof_dirs = proof_dirs if proof_dirs is not None else [cwd / d for d in DEFAULT_PROOF_DIRS]
    cands += feed_proofs(cwd, proof_dirs)
    cands += feed_ledger(cwd, ledger)
    if use_audit:
        try:
            cands += feed_audit(cwd, roots if roots is not None else [cwd / r for r in DEFAULT_AUDIT_ROOTS])
        except audit.UnknownShape as e:
            notes.append(f"audit feed skipped, unknown transcript shape: {e}")
    added = apply(read_rows(lessons), cands, stamp or now())
    append_rows(lessons, added)
    return added, notes


# Person actions ---------------------------------------------------------------------------------

def get(rows: list[dict], lid: str) -> dict:
    cur = fold(rows).get(lid)
    if cur is None:
        raise LessonError(f"lessons: no lesson {lid}")
    return cur


def approve(lessons: Path, lid: str, by: str | None, portable: bool = False, env: dict | None = None, stamp: str | None = None) -> dict:
    by = require_person("approve", by, env)
    cur = get(read_rows(lessons), lid)
    if cur["status"] not in ("draft", "recurred"):
        raise LessonError(f"lessons: {lid} is {cur['status']}; only a draft or recurred lesson is approved")
    row = new_row(cur, stamp or now(), status="approved", approvedBy=by, portable=bool(portable or cur.get("portable")))
    append_rows(lessons, [row])
    return row


def reject(lessons: Path, lid: str, by: str | None, reason: str = "", env: dict | None = None, stamp: str | None = None) -> dict:
    by = require_person("reject", by, env)
    cur = get(read_rows(lessons), lid)
    if cur["status"] not in ("draft", "recurred"):
        raise LessonError(f"lessons: {lid} is {cur['status']}; only a draft or recurred lesson is rejected")
    row = new_row(cur, stamp or now(), status="rejected", approvedBy=by, note=reason or "rejected without a reason")
    append_rows(lessons, [row])
    return row


def start(lessons: Path, lid: str, by: str, stamp: str | None = None) -> dict:
    cur = get(read_rows(lessons), lid)
    if cur["status"] != "routed":
        raise LessonError(f"lessons: {lid} is {cur['status']}; only a routed lesson starts")
    row = new_row(cur, stamp or now(), status="in-progress", note=f"started by {by}")
    append_rows(lessons, [row])
    return row


# Routing ----------------------------------------------------------------------------------------

def guarded(paths) -> list[str]:
    hits = []
    for p in paths or []:
        norm = str(p).replace("\\", "/")
        if any(g.search(norm) for g in GUARDED):
            hits.append(str(p))
    return hits


def assert_writable(path: str) -> None:
    norm = path.replace("\\", "/")
    if guarded([norm]) or not any(norm.startswith(w) or norm == w for w in WRITABLE):
        raise LessonError(f"lessons: routing may not write {path}", 3)


def spec_draft(cur: dict) -> str:
    sid = "draft-" + cur["id"]
    return (
        "+++\n"
        f'id = "{sid}"\n'
        f'title = "lesson {cur["id"]}: {cur["class"]}"\n'
        'class = "TODO"\n'
        'status = "draft"\n'
        f'lesson = "{cur["id"]}"\n'
        "scope = []\n"
        "\n[checks]\n# A person writes the fail-first and acceptance checks, then moves this file to specs/ with a number.\n"
        "quick = []\nacceptance = []\n"
        "+++\n\n"
        f"# Lesson {cur['id']}\n\n"
        f"Class: {cur['class']}. Seen {cur['recurrences']} time(s). Source: {cur['source']}.\n\n"
        "## Intent\n\n"
        f"{cur['finding']}.\n\n"
        "A person decides what change this spec asks for, what the scope is and how to check it.\n\n"
        "## Evidence\n\n" + "\n".join(f"- {e}" for e in cur.get("evidence", [])) + "\n"), sid


def route(lessons: Path, cwd: Path, ids: list[str] | None = None, change_paths: list[str] | None = None,
          roots: list[Path] | None = None, stamp: str | None = None) -> list[dict]:
    """Route the approved lessons. Returns one result per lesson: {id, result, message}."""
    stamp = stamp or now()
    rows = read_rows(lessons)
    cur = fold(rows)
    wanted = [i for i in (ids or [l["id"] for l in cur.values() if l["status"] == "approved"])]
    results = []
    for lid in wanted:
        les = get(rows, lid)
        if les["status"] != "approved":
            results.append({"id": lid, "result": "skipped", "message": f"{lid} is {les['status']}, not approved"})
            continue
        paths = list((les.get("links") or {}).get("changePaths") or []) + list(change_paths or [])
        bad = guarded(paths)
        if bad:
            results.append({"id": lid, "result": "refused", "message": f"{lid} would touch a guardrail ({', '.join(bad)}); a person changes those, not the loop"})
            continue
        links = dict(les.get("links") or {})
        if paths:
            links["changePaths"] = paths
        disp, note, msg = les["proposedDisposition"], "", ""
        if disp == "case":
            rts = roots if roots is not None else [cwd / r for r in DEFAULT_AUDIT_ROOTS]
            out = None
            try:
                report = audit.audit(rts, cwd)
                if les["class"] in audit.CODES:
                    drafts = cwd / "harness/cases/drafts"
                    assert_writable(rel(drafts / "x.json", cwd))
                    out = audit.promote(report, les["class"], rts, drafts, cwd)
            except SystemExit:
                out = None
            except audit.UnknownShape as e:
                msg = f"audit refused: {e}"
            if out is None:
                results.append({"id": lid, "result": "skipped", "message": msg or f"{lid}: class {les['class']} has no audit hit to promote; a person writes the case"})
                continue
            links["caseId"] = out.stem
            msg = f"case draft {rel(out, cwd)} (whyHard is a placeholder until a person writes it)"
        elif disp == "spec":
            text, sid = spec_draft(les)
            target = f"specs/drafts/{les['id']}.md"
            assert_writable(target)
            (cwd / "specs/drafts").mkdir(parents=True, exist_ok=True)
            (cwd / target).write_text(text, encoding="utf-8", newline="\n")
            links["specId"] = sid
            msg = f"spec draft {target}"
        elif disp == "pack":
            case = next((json.loads(f.read_text(encoding="utf-8")).get("id") for f in sorted((cwd / "harness/cases").glob("*.json"))
                         if json.loads(f.read_text(encoding="utf-8")).get("failureClass") == les["class"]), None) or links.get("caseId") or "<case id>"
            links["caseId"] = links.get("caseId") or (case if case != "<case id>" else None)
            msg = (f"pack change: prove it with the proving loop, not run here:\n"
                   f"  harness/bin/case-run.sh harness/cases/{case}.json --pack candidate --k 3\n"
                   f"  python3 harness/lib/proof.py . {case}")
        else:
            msg = f"{disp}: recorded only"
        row = new_row(les, stamp, status="routed", links=links, note=msg.split("\n")[0])
        append_rows(lessons, [row])
        rows.append(row)
        results.append({"id": lid, "result": "routed", "message": msg})
    return results


# Close ------------------------------------------------------------------------------------------

def pr_number(ref: str) -> int | None:
    m = re.search(r"(?:pull/|#)(\d+)\s*$|^(\d+)$", ref.strip())
    return int(m.group(1) or m.group(2)) if m else None


def fork_prs(cwd: Path) -> list[dict]:
    config = tomllib.loads((cwd / "harness/config.toml").read_text(encoding="utf-8"))
    fork = config["github"]["repo"]
    if fork == config["github"]["upstream"]:
        raise LessonError("lessons: refusing to read the upstream repository")
    exe = "gh" if shutil.which("gh") else "gh.exe"
    r = subprocess.run([exe, "pr", "list", "--repo", fork, "--state", "all", "--limit", "200", "--json", "number,url,mergedAt"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise LessonError(f"lessons: gh failed, the PR cannot be checked: {r.stderr.strip()[:200]}")
    return json.loads(r.stdout or "[]")


def close(lessons: Path, cwd: Path, lid: str, by: str | None, proof: str | None = None, pr: str | None = None,
          prs: list[dict] | None = None, stamp: str | None = None) -> dict:
    if not by or not by.strip():
        raise LessonError("lessons: close needs --by <name>", 2)
    if bool(proof) == bool(pr):
        raise LessonError("lessons: close needs exactly one of --proof <verdict path> or --pr <ref>")
    cur = get(read_rows(lessons), lid)
    if cur["status"] not in ("approved", "routed", "in-progress", "recurred"):
        raise LessonError(f"lessons: {lid} is {cur['status']}; approve it first" if cur["status"] == "draft" else f"lessons: {lid} is {cur['status']} and cannot be closed")
    links = dict(cur.get("links") or {})
    if proof:
        p = Path(proof) if Path(proof).is_absolute() else cwd / proof
        if not p.is_file():
            raise LessonError(f"lessons: {proof} does not exist; a lesson closes on a real proof verdict")
        try:
            v = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise LessonError(f"lessons: {proof} is not a verdict JSON file")
        if v.get("verdict") != "SHIP":
            raise LessonError(f"lessons: {proof} has verdict {v.get('verdict')!r}; only a SHIP verdict closes a lesson")
        links["proof"] = rel(p, cwd)
    else:
        n = pr_number(pr)
        if n is None:
            raise LessonError(f"lessons: {pr!r} is not a PR reference (a number, #N or a pull URL)")
        found = next((x for x in (prs if prs is not None else fork_prs(cwd)) if int(x["number"]) == n), None)
        if found is None:
            raise LessonError(f"lessons: PR {pr} was not found on the fork")
        if not found.get("mergedAt"):
            raise LessonError(f"lessons: PR {pr} is not merged; only a merged PR closes a lesson")
        links["prRef"] = pr
    row = new_row(cur, stamp or now(), status="closed", closedBy=by.strip(), links=links, note="closed on " + ("proof " + proof if proof else "merged PR " + pr))
    append_rows(lessons, [row])
    return row


# List, mine, metrics ----------------------------------------------------------------------------

def rank(lessons: list[dict]) -> list[dict]:
    by_new = sorted(lessons, key=lambda l: l.get("ts", ""), reverse=True)
    return sorted(by_new, key=lambda l: (l["status"] != "recurred", -(l.get("weight", 0) * l.get("recurrences", 0))))


def listing(rows: list[dict], status: str | None = None, source: str | None = None) -> list[dict]:
    out = list(fold(rows).values())
    if status:
        out = [l for l in out if l["status"] == status]
    if source:
        out = [l for l in out if l["source"] == source]
    return rank(out)


def open_ranked(rows: list[dict]) -> list[dict]:
    """What the mine step ranks beside the failure classes: open lessons that still ask for work."""
    return rank([l for l in fold(rows).values()
                 if l["status"] in OPEN_STATUSES and l["proposedDisposition"] not in ("parked", "none")])


def render_list(items: list[dict]) -> str:
    if not items:
        return "no lessons"
    out = [f"{'id':<13}{'status':<12}{'w*n':>4}  {'source':<17}{'disposition':<12}{'class':<26}finding"]
    for l in items:
        out.append(f"{l['id']:<13}{l['status']:<12}{l['weight'] * l['recurrences']:>4}  {l['source']:<17}{l['proposedDisposition']:<12}{l['class']:<26}{l['finding']}")
    return "\n".join(out)


def parse_ts(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def metrics(rows: list[dict]) -> dict:
    hist = history(rows)
    cur = fold(rows)
    closed_ever = [i for i, h in hist.items() if any(r["status"] == "closed" for r in h)]
    recurred = [i for i, h in hist.items() if any(r["status"] == "recurred" for r in h)]
    days = []
    for i in closed_ever:
        h = hist[i]
        first_close = next(r for r in h if r["status"] == "closed")
        days.append((parse_ts(first_close["ts"]) - parse_ts(h[0]["ts"])).total_seconds() / 86400)
    days.sort()
    median = None
    if days:
        mid = len(days) // 2
        median = round(days[mid] if len(days) % 2 else (days[mid - 1] + days[mid]) / 2, 2)
    by_source = {s: sum(1 for l in cur.values() if l["source"] == s) for s in SOURCES}
    n = len(cur)
    return {
        "opened": n,
        "closed": sum(1 for l in cur.values() if l["status"] == "closed"),
        "closedEver": len(closed_ever),
        "recurred": len(recurred),
        "open": sum(1 for l in cur.values() if l["status"] in OPEN_STATUSES),
        "medianDaysToClose": median,
        "bySource": by_source,
        "shareBySource": {s: round(c / n, 4) if n else 0.0 for s, c in by_source.items()},
        "closedLessonsThatCameBack": {"count": len([i for i in recurred if i in closed_ever]), "ofClosed": len(closed_ever),
                                      "rate": round(len([i for i in recurred if i in closed_ever]) / len(closed_ever), 4) if closed_ever else None},
    }


def render_metrics(m: dict) -> list[str]:
    sh = m["shareBySource"]
    pct = lambda s: f"{round(sh[s] * 100)}%"  # noqa: E731
    back = m["closedLessonsThatCameBack"]
    return [
        f"lessons                   {m['opened']} opened, {m['closed']} closed, {m['recurred']} recurred, {m['open']} open; "
        f"median days to close {m['medianDaysToClose'] if m['medianDaysToClose'] is not None else 'none yet'}",
        f"lessons by source         human correction {pct('human-correction')}, eval fail {pct('eval-fail')}, test {pct('test-fail')}, "
        f"build retro {pct('build-retro')}, external {pct('external')}",
        f"closed lessons that came back  {back['count']} of {back['ofClosed']} closed"
        + (f" ({round(back['rate'] * 100)}%)" if back["rate"] is not None else "") + " (the fix did not hold)",
    ]


# Portable seed ----------------------------------------------------------------------------------

PATH_RE = re.compile(r"(?<![\w])(?:[A-Za-z]:)?(?:[\w.-]*[/\\])+[\w.-]*")
SCRUBS = (
    re.compile(r"https?://\S+"),
    re.compile(r"\bt-[0-9A-HJKMNP-TV-Z]{26}\b"),
    re.compile(r"\b(?:PR|pull request)\s*#?\d+\b", re.I),
    re.compile(r"#\d+\b"),
    re.compile(r"\bpull/\d+\b"),
    re.compile(r"\b[0-9a-f]{7,40}\b"),
    PATH_RE,
)


def scrub(text: str, deny: list[str]) -> str:
    for rx in SCRUBS:
        text = rx.sub("", text)
    for w in deny:
        if w.strip():
            text = re.sub(re.escape(w.strip()), "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip(" .,;:")


def seed_export(rows: list[dict], out: Path, deny: list[str] | None = None) -> int:
    items = []
    for l in fold(rows).values():
        if not l.get("portable") or l["status"] == "rejected":
            continue
        items.append({"class": scrub(str(l["class"]), deny or []), "finding": scrub(l["finding"], deny or []),
                      "proposedDisposition": l["proposedDisposition"]})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"v": 1, "lessons": items}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return len(items)


def seed_import(lessons: Path, src: Path, stamp: str | None = None) -> list[dict]:
    data = json.loads(src.read_text(encoding="utf-8"))
    cands = []
    for it in data.get("lessons", []):
        if it.get("proposedDisposition") not in DISPOSITIONS or not it.get("finding") or not it.get("class"):
            raise LessonError(f"lessons: {src} has a seed row that is not {{class, finding, proposedDisposition}}")
        ref = "seed:" + signature(it["class"], it["finding"])[:12]
        cands.append(Cand("external", "seed", it["class"], it["finding"], ref, [ref], None, disposition=it["proposedDisposition"], portable=True))
    added = apply(read_rows(lessons), cands, stamp or now())
    append_rows(lessons, added)
    return added


# Command line -----------------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--cwd", default=".")
    ap.add_argument("--lessons", default="runs/lessons.jsonl")
    ap.add_argument("--now", help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft")
    d.add_argument("--ledger")
    d.add_argument("--proofs", nargs="+")
    d.add_argument("--roots", nargs="+")
    d.add_argument("--no-audit", action="store_true")
    ls = sub.add_parser("list")
    ls.add_argument("--status", choices=STATUSES)
    ls.add_argument("--source", choices=SOURCES)
    ls.add_argument("--json", action="store_true")
    for name in ("approve", "reject"):
        p = sub.add_parser(name)
        p.add_argument("id")
        p.add_argument("--by")
        if name == "approve":
            p.add_argument("--portable", action="store_true")
        else:
            p.add_argument("--reason", default="")
    r = sub.add_parser("route")
    r.add_argument("ids", nargs="*")
    r.add_argument("--change-path", action="append", default=[])
    r.add_argument("--roots", nargs="+")
    s = sub.add_parser("start")
    s.add_argument("id")
    s.add_argument("--by", required=True)
    c = sub.add_parser("close")
    c.add_argument("id")
    c.add_argument("--by")
    c.add_argument("--proof")
    c.add_argument("--pr")
    c.add_argument("--prs", help="a saved gh pr list JSON file instead of reading GitHub")
    sd = sub.add_parser("seed")
    sd.add_argument("--out")
    sd.add_argument("--in", dest="inp")
    sd.add_argument("--deny", nargs="*", default=[])
    a = ap.parse_args(argv)
    cwd = Path(a.cwd).resolve()
    lessons = Path(a.lessons) if Path(a.lessons).is_absolute() else cwd / a.lessons

    def paths(vals):
        return [Path(v) if Path(v).is_absolute() else cwd / v for v in vals] if vals is not None else None

    try:
        if a.cmd == "draft":
            added, notes = draft(cwd, lessons, paths([a.ledger])[0] if a.ledger else None, paths(a.proofs), paths(a.roots), not a.no_audit, a.now)
            for n in notes:
                print(f"note: {n}")
            for r in added:
                print(f"{'drafted' if r['recurrences'] == 1 else 'updated'} {r['id']}  {r['status']:<9}{r['recurrences']:>3}x  {r['source']:<17}{r['proposedDisposition']:<7}{r['class']}")
            print(f"lessons: {len(added)} row(s) appended to {rel(lessons, cwd)}" + (" (nothing new)" if not added else ""))
            return 2 if notes else 0
        rows = read_rows(lessons)
        if a.cmd == "list":
            items = listing(rows, a.status, a.source)
            print(json.dumps(items, indent=1, ensure_ascii=False) if a.json else render_list(items))
        elif a.cmd == "approve":
            r = approve(lessons, a.id, a.by, a.portable, stamp=a.now)
            print(f"approved {r['id']} by {r['approvedBy']}" + (" (portable)" if r["portable"] else ""))
        elif a.cmd == "reject":
            r = reject(lessons, a.id, a.by, a.reason, stamp=a.now)
            print(f"rejected {r['id']} by {r['approvedBy']}: {r['note']}")
        elif a.cmd == "route":
            res = route(lessons, cwd, a.ids or None, a.change_path, paths(a.roots), a.now)
            for x in res:
                print(f"{x['result']:<8} {x['id']}  {x['message']}")
            print(f"route: {sum(1 for x in res if x['result'] == 'routed')} routed, {sum(1 for x in res if x['result'] == 'skipped')} skipped, "
                  f"{sum(1 for x in res if x['result'] == 'refused')} refused")
            if any(x["result"] == "refused" for x in res):
                return 3
        elif a.cmd == "start":
            r = start(lessons, a.id, a.by, a.now)
            print(f"in-progress {r['id']}")
        elif a.cmd == "close":
            prs = json.loads(Path(a.prs).read_text(encoding="utf-8")) if a.prs else None
            r = close(lessons, cwd, a.id, a.by, a.proof, a.pr, prs, a.now)
            print(f"closed {r['id']} by {r['closedBy']}: {r['note']}")
        elif a.cmd == "seed":
            if bool(a.out) == bool(a.inp):
                raise LessonError("lessons: seed needs exactly one of --out FILE or --in FILE", 2)
            if a.out:
                n = seed_export(rows, Path(a.out) if Path(a.out).is_absolute() else cwd / a.out, a.deny)
                print(f"seed: {n} portable lesson(s) exported to {a.out} (class, finding, disposition only)")
            else:
                added = seed_import(lessons, Path(a.inp) if Path(a.inp).is_absolute() else cwd / a.inp, a.now)
                print(f"seed: {len(added)} lesson(s) imported as draft, source external")
    except LessonError as e:
        print(str(e), file=sys.stderr)
        return e.code
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
