#!/usr/bin/env python3
"""The mine step of the proving loop: a reference-free L1 audit over recorded sessions.

    audit.py [--roots DIR...] [--json] [--promote CODE] [--drafts DIR]

Reads every task on record (a folder with packet.json under the roots; runs/ and
demo/recordings/ by default), normalizes its Claude Code stream-json transcripts (the worker's
transcript.jsonl and the reviewer's review-transcript.jsonl) into one Trace per session, and
runs the checks below against the trace, the packet, loops.jsonl, rounds.jsonl, checks.log and
the ledger row. Nothing here asks a model anything: every hit is a fact in a file, with the
file and line it came from.

Checks (one code each; a hit carries taskId, spec, class, file, line, round, turn):

    NO_TOOL_CALL             a worker session that called no tool, or never ran a check
    IGNORED_ERROR            a tool result with is_error and no tool call after it
    UNSOURCED_SPECIFIC       the final message says a check or test passed, and no tool call
                             in the task's sessions ran one
    CLAIMED_SUCCESS_NO_STATE the final message claims done while the packet shows the checks
                             failing or no changed path, or the Stop hook gave up at its cap
    REVIEW_REJECTED          the adversarial reviewer rejected a round (its reasons are the text)
    STOP_HOOK_BLOCKED        the Stop hook bounced a finish (loop 2 working; a warning)
    LINT_FAILED              lint among the reviewer's reasons or in the check output

Output: failure classes ranked by recurrence (distinct tasks, then hits), the hits under each.
Exit 1 when any FAIL-severity class has a hit, 0 on WARN or clean. --promote CODE writes a
case draft harness/cases/drafts/<code>.json with the real prompt (the spec body), the base sha
from the packet, the task ids and an empty checks list for a person to fill.

The normalizer is versioned (TRACE_VERSION) and fails loudly on a shape it does not know,
rather than parsing nothing and reporting a clean audit. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

TRACE_VERSION = 1

# Top-level stream-json event types Claude Code writes; anything else is an unknown shape.
KNOWN_TYPES = {"system", "assistant", "user", "result", "rate_limit_event", "tool_progress", "stream_event"}

SEVERITY = {
    "REVIEW_REJECTED": "FAIL",
    "LINT_FAILED": "FAIL",
    "CLAIMED_SUCCESS_NO_STATE": "FAIL",
    "IGNORED_ERROR": "FAIL",
    "UNSOURCED_SPECIFIC": "FAIL",
    "NO_TOOL_CALL": "FAIL",
    "STOP_HOOK_BLOCKED": "WARN",
}
DESCRIPTION = {
    "REVIEW_REJECTED": "the adversarial reviewer rejected a round",
    "LINT_FAILED": "lint findings in the reviewer's reasons or the check output",
    "CLAIMED_SUCCESS_NO_STATE": "the final message claims done; the packet or the Stop hook says otherwise",
    "IGNORED_ERROR": "a tool result with is_error, and no tool call after it",
    "UNSOURCED_SPECIFIC": "the final message says a check or test passed with no tool call that ran one",
    "NO_TOOL_CALL": "a worker session that called no tool, or never ran a check",
    "STOP_HOOK_BLOCKED": "the Stop hook bounced a finish (loop 2 doing its job)",
}
CODES = list(SEVERITY)

# What counts as running a check, in a tool call's input.
CHECK_RE = re.compile(r"pytest|unittest|/checks/|\bruff\b|\bmypy\b|\btox\b|\bnpm test\b|pre-commit|\bflake8\b|\bblack\b", re.I)
LINT_RE = re.compile(r"\bruff\b|\blint\b|\bflake8\b|\bblack\b|pre-commit|\bE\d{3}\b|\bW\d{3}\b|\bF\d{3}\b|line.?length|exceeds? 88", re.I)
TEST_RE = re.compile(r"pytest|unittest|\btests?\b|\bsuite\b|\bcheck(s|ers)?\b", re.I)
# A claim that something passed. Scoped to one sentence so "the suite passes" matches and a
# whole paragraph with "tests" and "passed" ten lines apart does not.
CLAIM_RE = re.compile(
    r"(?P<what>suite|tests?|checks?|lint(?:er|ing)?|ruff|mypy|docstring examples|examples)[^.\n]{0,80}?\b(?P<how>pass(?:es|ed)?|green|clean)\b"
    r"|\b(?P<n>\d+) passed\b",
    re.I,
)
SUCCESS_RE = re.compile(r"\b(done|complete[d]?|fixed|implemented|now (keeps|works|returns|has)|I (added|changed|updated|fixed|addressed))\b", re.I)


class UnknownShape(Exception):
    """A line the normalizer does not know. Raised, never swallowed."""


# ---- the Trace -------------------------------------------------------------------------------
@dataclass
class ToolCall:
    turn: int
    line: int
    id: str
    name: str
    input: str
    is_error: bool | None = None
    result: str = ""
    result_line: int | None = None


@dataclass
class Trace:
    version: int
    file: str
    index: int                 # which session in the file (a resumed round appends a second)
    session_id: str
    first_line: int
    last_line: int
    turns: int = 0
    tool_calls: list[ToolCall] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    final_text: str = ""
    final_line: int | None = None
    subtype: str = ""
    is_error: bool = False
    cost_usd: float = 0.0
    num_turns: int = 0
    denials: int = 0


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text", "")) for b in content if isinstance(b, dict))
    return "" if content is None else json.dumps(content)


def normalize(path: Path) -> list[Trace]:
    """Claude Code stream-json (one session, or several appended by --resume) -> Traces."""
    traces: list[Trace] = []
    cur: Trace | None = None
    by_id: dict[str, ToolCall] = {}
    text = path.read_text(encoding="utf-8", errors="replace")
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError as e:
            raise UnknownShape(f"{path}:{n}: not JSON ({e.msg})") from None
        if not isinstance(ev, dict) or "type" not in ev:
            raise UnknownShape(f"{path}:{n}: no 'type' field")
        t = ev["type"]
        if t not in KNOWN_TYPES:
            raise UnknownShape(f"{path}:{n}: unknown event type {t!r}")
        if t == "system" and ev.get("subtype") == "init":
            cur = Trace(TRACE_VERSION, str(path), len(traces), str(ev.get("session_id", "")), n, n)
            traces.append(cur)
            by_id = {}
            continue
        if cur is None:
            # A session has to start with its init line; anything before it is a shape we do not know.
            raise UnknownShape(f"{path}:{n}: {t} event before any system/init line")
        cur.last_line = n
        if t == "assistant":
            msg = ev.get("message")
            if not isinstance(msg, dict) or not isinstance(msg.get("content"), list):
                raise UnknownShape(f"{path}:{n}: assistant event without message.content list")
            cur.turns += 1
            for block in msg["content"]:
                if not isinstance(block, dict):
                    raise UnknownShape(f"{path}:{n}: assistant content block is not an object")
                bt = block.get("type")
                if bt == "tool_use":
                    tc = ToolCall(cur.turns, n, str(block.get("id", "")), str(block.get("name", "")), json.dumps(block.get("input", {}), ensure_ascii=False))
                    cur.tool_calls.append(tc)
                    by_id[tc.id] = tc
                elif bt == "text":
                    cur.texts.append(str(block.get("text", "")))
                elif bt not in ("thinking", "redacted_thinking"):
                    raise UnknownShape(f"{path}:{n}: unknown assistant block type {bt!r}")
        elif t == "user":
            msg = ev.get("message")
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        tc = by_id.get(str(block.get("tool_use_id", "")))
                        if tc is None:
                            raise UnknownShape(f"{path}:{n}: tool_result for an unknown tool_use_id")
                        tc.is_error = bool(block.get("is_error", False))
                        tc.result = _text_of(block.get("content"))[:2000]
                        tc.result_line = n
            elif not isinstance(content, str) and content is not None:
                raise UnknownShape(f"{path}:{n}: user content is neither a list nor a string")
        elif t == "result":
            cur.subtype = str(ev.get("subtype", ""))
            cur.is_error = bool(ev.get("is_error", False))
            cur.cost_usd = float(ev.get("total_cost_usd") or 0)
            cur.num_turns = int(ev.get("num_turns") or 0)
            cur.denials = len(ev.get("permission_denials") or [])
            cur.final_text = str(ev.get("result") or "") or (cur.texts[-1] if cur.texts else "")
            cur.final_line = n
    if not traces:
        raise UnknownShape(f"{path}: no session (no system/init line) in the file")
    for tr in traces:
        if tr.final_line is None:
            # A session cut off before its result line is still a session; its last text is the final text.
            tr.final_text = tr.texts[-1] if tr.texts else ""
    return traces


def read_jsonl(path: Path) -> list[tuple[int, dict]]:
    rows: list[tuple[int, dict]] = []
    if not path.exists():
        return rows
    for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append((n, json.loads(line)))
        except json.JSONDecodeError as e:
            raise UnknownShape(f"{path}:{n}: not JSON ({e.msg})") from None
    return rows


# ---- one task's record -----------------------------------------------------------------------
@dataclass
class Hit:
    code: str
    taskId: str
    spec: str
    cls: str
    file: str
    line: int | None
    round: int | None
    turn: int | None
    text: str

    def as_dict(self) -> dict:
        d = asdict(self)
        d["class"] = d.pop("cls")
        return d


@dataclass
class TaskRecord:
    dir: Path
    packet: dict
    ledger: dict | None
    worker: list[Trace]
    reviewer: list[Trace]
    loops: list[tuple[int, dict]]
    rounds: list[tuple[int, dict]]
    checks_log: str
    evidence_lines: int

    @property
    def task_id(self) -> str:
        return str(self.packet.get("taskId", self.dir.name))

    @property
    def spec(self) -> str:
        return str((self.packet.get("spec") or {}).get("id", ""))

    @property
    def cls(self) -> str:
        return str((self.packet.get("spec") or {}).get("class", ""))


def load_task(d: Path, ledger_rows: dict[str, dict]) -> TaskRecord:
    packet = json.loads((d / "packet.json").read_text(encoding="utf-8"))
    worker = normalize(d / "transcript.jsonl") if (d / "transcript.jsonl").exists() else []
    reviewer = normalize(d / "review-transcript.jsonl") if (d / "review-transcript.jsonl").exists() else []
    evidence = 0
    if (d / "pack-evidence.jsonl").exists():
        for n, row in read_jsonl(d / "pack-evidence.jsonl"):
            if "event" not in row:
                raise UnknownShape(f"{d / 'pack-evidence.jsonl'}:{n}: evidence row without 'event'")
            evidence += 1
    checks_log = (d / "checks.log").read_text(encoding="utf-8", errors="replace") if (d / "checks.log").exists() else ""
    return TaskRecord(d, packet, ledger_rows.get(str(packet.get("taskId"))), worker, reviewer,
                      read_jsonl(d / "loops.jsonl"), read_jsonl(d / "rounds.jsonl"), checks_log, evidence)


def find_tasks(roots: list[Path], cwd: Path) -> tuple[list[TaskRecord], list[str]]:
    """Every folder with a packet.json under the roots; a task seen under two roots counts once."""
    tasks: list[TaskRecord] = []
    notes: list[str] = []
    seen: dict[str, Path] = {}
    for root in roots:
        if not root.exists():
            notes.append(f"{rel(root, cwd)}: no such folder")
            continue
        ledger_rows: dict[str, dict] = {}
        for _, row in read_jsonl(root / "ledger.jsonl"):
            if row.get("taskId"):
                ledger_rows[str(row["taskId"])] = row
        for p in sorted(root.rglob("packet.json")):
            d = p.parent
            try:
                rec = load_task(d, ledger_rows)
            except UnknownShape:
                raise
            except (OSError, json.JSONDecodeError, ValueError) as e:
                raise UnknownShape(f"{d}: cannot read the task record ({e})") from None
            if rec.packet.get("partial"):
                notes.append(f"{rel(d, cwd)}: partial packet (the task did not finish); skipped")
                continue
            if rec.task_id in seen:
                notes.append(f"{rel(d, cwd)}: same task as {rel(seen[rec.task_id], cwd)}; counted once")
                continue
            seen[rec.task_id] = d
            tasks.append(rec)
    return tasks, notes


# ---- the checks -------------------------------------------------------------------------------
def rel(p: Path | str, cwd: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(cwd.resolve())).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def check_task(t: TaskRecord, cwd: Path) -> list[Hit]:
    hits: list[Hit] = []

    def hit(code: str, file: Path | str, line: int | None, rnd: int | None, turn: int | None, text: str) -> None:
        hits.append(Hit(code, t.task_id, t.spec, t.cls, rel(file, cwd), line, rnd, turn, text[:500]))

    # Worker sessions: one per round (round 1 is the --resume continuation).
    calls_so_far: list[ToolCall] = []
    for rnd, tr in enumerate(t.worker):
        calls_so_far = calls_so_far + tr.tool_calls
        if not tr.tool_calls:
            hit("NO_TOOL_CALL", tr.file, tr.first_line, rnd, None, "the session called no tool at all")
        elif not any(CHECK_RE.search(c.input) for c in tr.tool_calls):
            hit("NO_TOOL_CALL", tr.file, tr.first_line, rnd, None,
                f"{len(tr.tool_calls)} tool call(s), none ran a check (pytest, ruff, the harness checks)")
        for i, c in enumerate(tr.tool_calls):
            if c.is_error:
                later = tr.tool_calls[i + 1:]
                if not later:
                    hit("IGNORED_ERROR", tr.file, c.result_line or c.line, rnd, c.turn,
                        f"{c.name} failed ({c.result[:160].strip()!r}) and no tool call followed")
        final = tr.final_text
        for m in CLAIM_RE.finditer(final):
            claim = m.group(0)
            lint_claim = bool(LINT_RE.search(claim))
            # A claim about lint needs a lint call; a claim about tests needs a test call.
            if lint_claim and not any(LINT_RE.search(c.input) for c in calls_so_far):
                hit("UNSOURCED_SPECIFIC", tr.file, tr.final_line, rnd, tr.turns, f"claims {claim!r}; no tool call ran a linter")
            elif not lint_claim and not any(CHECK_RE.search(c.input) for c in calls_so_far):
                hit("UNSOURCED_SPECIFIC", tr.file, tr.final_line, rnd, tr.turns, f"claims {claim!r}; no tool call ran a test or check")
        if SUCCESS_RE.search(final):
            row = next((r for _, r in t.rounds if r.get("round") == rnd), None)
            all_pass = row.get("allChecksPass") if row else t.packet.get("allChecksPass")
            changed = row.get("changedPaths") if row else t.packet.get("changedPaths")
            if all_pass is False:
                hit("CLAIMED_SUCCESS_NO_STATE", t.dir / "rounds.jsonl" if row else t.dir / "packet.json", None, rnd, tr.turns,
                    "the final message claims done; the trusted checks failed in the fresh clone")
            if not changed:
                hit("CLAIMED_SUCCESS_NO_STATE", t.dir / "rounds.jsonl" if row else t.dir / "packet.json", None, rnd, tr.turns,
                    "the final message claims done; the diff is empty")
    # The Stop hook: each block is a false finish it caught; a cap is a finish it had to let go.
    rnd = 0
    for n, ev in t.loops:
        if ev.get("loop") == "retry":
            rnd = int(ev.get("round", rnd + 1))
        if ev.get("loop") == "finish" and ev.get("result") == "block":
            hit("STOP_HOOK_BLOCKED", t.dir / "loops.jsonl", n, rnd, None,
                f"{ev.get('failed', '?')} quick check(s) failed on the worktree; continuation {ev.get('continuation')}")
        if ev.get("loop") == "finish" and ev.get("result") == "cap":
            hit("CLAIMED_SUCCESS_NO_STATE", t.dir / "loops.jsonl", n, rnd, None,
                "the Stop hook let the session end at its continuation cap with quick checks still failing")
    # The reviewer, round by round.
    for n, row in t.rounds:
        v = row.get("verdict") or {}
        if v.get("verdict") == "reject":
            reasons = [str(r) for r in v.get("reasons") or []]
            hit("REVIEW_REJECTED", t.dir / "rounds.jsonl", n, row.get("round"), None, "; ".join(reasons) or "no reasons given")
            lint = [r for r in reasons if LINT_RE.search(r)]
            if lint:
                hit("LINT_FAILED", t.dir / "rounds.jsonl", n, row.get("round"), None, "; ".join(lint))
    if not t.rounds and (t.packet.get("review") or {}).get("verdict") == "reject":
        reasons = [str(r) for r in (t.packet["review"].get("reasons") or [])]
        hit("REVIEW_REJECTED", t.dir / "packet.json", None, None, None, "; ".join(reasons))
        if any(LINT_RE.search(r) for r in reasons):
            hit("LINT_FAILED", t.dir / "packet.json", None, None, None, "; ".join(r for r in reasons if LINT_RE.search(r)))
    # Lint in the check output: a failing check whose command or output names the linter.
    for n, block in enumerate(re.split(r"^### ", t.checks_log, flags=re.M)):
        head = block.split("\n", 1)[0]
        if LINT_RE.search(head) and re.search(r"Found \d+ error|error:|\bE\d{3}\b|\bF\d{3}\b|\bW\d{3}\b", block):
            hit("LINT_FAILED", t.dir / "checks.log", None, None, None, f"check output: {head[:120]}")
    return hits


# ---- ranking and output -----------------------------------------------------------------------
def rank(hits: list[Hit]) -> list[dict]:
    by_code: dict[str, list[Hit]] = defaultdict(list)
    for h in hits:
        by_code[h.code].append(h)
    classes = []
    for code, hs in by_code.items():
        tasks = sorted({h.taskId for h in hs})
        classes.append({"code": code, "severity": SEVERITY[code], "description": DESCRIPTION[code],
                        "tasks": len(tasks), "hits": len(hs), "taskIds": tasks,
                        "specs": sorted({h.spec for h in hs}), "items": [h.as_dict() for h in hs]})
    classes.sort(key=lambda c: (-c["tasks"], -c["hits"], c["code"]))
    return classes


def render(report: dict) -> str:
    out: list[str] = []
    w = out.append
    s = report["summary"]
    w(f"audit: {s['tasks']} task(s) under {', '.join(s['roots'])}; {s['sessions']} session(s) normalized (trace v{TRACE_VERSION}), "
      f"{s['toolCalls']} tool call(s), {s['evidenceLines']} pack evidence line(s)")
    for n in report["notes"]:
        w(f"  note: {n}")
    w("")
    if not report["classes"]:
        w("clean: no hit on any check")
    for c in report["classes"]:
        w(f"{c['severity']:<5} {c['code']:<25} {c['tasks']} task(s), {c['hits']} hit(s)   {c['description']}")
        for h in c["items"]:
            where = h["file"] + (f":{h['line']}" if h["line"] else "")
            rnd = f" round {h['round']}" if h["round"] is not None else ""
            turn = f" turn {h['turn']}" if h["turn"] is not None else ""
            w(f"      {h['taskId']}  {h['spec']} ({h['class']}){rnd}{turn}  {where}")
            w(f"        {h['text']}")
        w("")
    w(f"result: {report['result']} ({report['failHits']} FAIL hit(s), {report['warnHits']} WARN hit(s))")
    return "\n".join(out)


def audit(roots: list[Path], cwd: Path) -> dict:
    tasks, notes = find_tasks(roots, cwd)
    hits: list[Hit] = []
    for t in tasks:
        hits.extend(check_task(t, cwd))
    classes = rank(hits)
    fails = sum(c["hits"] for c in classes if c["severity"] == "FAIL")
    warns = sum(c["hits"] for c in classes if c["severity"] == "WARN")
    return {
        "v": 1,
        "traceVersion": TRACE_VERSION,
        "summary": {
            "roots": [rel(r, cwd) for r in roots],
            "tasks": len(tasks),
            "sessions": sum(len(t.worker) + len(t.reviewer) for t in tasks),
            "toolCalls": sum(len(tr.tool_calls) for t in tasks for tr in t.worker + t.reviewer),
            "evidenceLines": sum(t.evidence_lines for t in tasks),
            "costUsd": round(sum(float(t.packet.get("costUsd") or 0) for t in tasks), 4),
        },
        "notes": notes,
        "tasks": [{"taskId": t.task_id, "spec": t.spec, "class": t.cls, "dir": rel(t.dir, cwd),
                   "baseCommit": t.packet.get("baseCommit"), "costUsd": t.packet.get("costUsd"),
                   "pr": (t.ledger or {}).get("pr") or ""} for t in tasks],
        "classes": classes,
        "failHits": fails,
        "warnHits": warns,
        "result": "FAIL" if fails else ("WARN" if warns else "clean"),
    }


def promote(report: dict, code: str, roots: list[Path], drafts: Path, cwd: Path) -> Path:
    """Write a case draft for one failure class: the real prompt, the base sha, the task ids."""
    cls = next((c for c in report["classes"] if c["code"] == code), None)
    if cls is None:
        raise SystemExit(f"audit: no hit for {code}; nothing to promote")
    # The spec the class showed on most; the others are named in the draft.
    per_spec: dict[str, int] = defaultdict(int)
    for h in cls["items"]:
        per_spec[h["spec"]] += 1
    spec_id = max(per_spec, key=lambda s: (per_spec[s], s))
    task = next(t for t in report["tasks"] if t["spec"] == spec_id)
    tdir = cwd / task["dir"]
    prompt = ""
    plan = tdir / "plan.json"
    if plan.exists():
        prompt = json.loads(plan.read_text(encoding="utf-8")).get("body", "")
    if not prompt and (tdir / "prompt.md").exists():
        prompt = (tdir / "prompt.md").read_text(encoding="utf-8").split("\n## How this workbench works", 1)[0]
    draft = {
        "id": code.lower().replace("_", "-"),
        "kind": "trajectory",
        "status": "draft",
        "from": f"audit over {', '.join(report['summary']['roots'])}: {cls['tasks']} task(s), {cls['hits']} hit(s) of {code} ({cls['description']})",
        "failureClass": code,
        "spec": spec_id,
        "specFile": f"specs/{spec_id}.md",
        "otherSpecs": sorted(s for s in per_spec if s != spec_id),
        "tasks": cls["taskIds"],
        "baseSha": task["baseCommit"],
        "prompt": prompt,
        "k": 3,
        "checks": [],
        "hits": [{k: h[k] for k in ("taskId", "spec", "round", "file", "line", "text")} for h in cls["items"]],
    }
    drafts.mkdir(parents=True, exist_ok=True)
    out = drafts / f"{draft['id']}.json"
    out.write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--roots", nargs="+", default=["runs", "demo/recordings"])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--promote", metavar="CODE", choices=CODES)
    ap.add_argument("--drafts", default="harness/cases/drafts")
    ap.add_argument("--cwd", default=".", help="the repository root the paths are relative to")
    a = ap.parse_args(argv)
    cwd = Path(a.cwd).resolve()
    roots = [Path(r) if Path(r).is_absolute() else cwd / r for r in a.roots]
    try:
        report = audit(roots, cwd)
    except UnknownShape as e:
        print(f"audit: unknown shape, refusing to report a clean audit: {e}", file=sys.stderr)
        return 2
    if a.promote:
        out = promote(report, a.promote, roots, Path(a.drafts) if Path(a.drafts).is_absolute() else cwd / a.drafts, cwd)
        report["promoted"] = rel(out, cwd)
    print(json.dumps(report, indent=1, ensure_ascii=False) if a.json else render(report))
    if a.promote and not a.json:
        print(f"promoted: {report['promoted']} (fill in checks; a person approves the case)")
    return 1 if report["result"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
