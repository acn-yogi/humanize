#!/usr/bin/env python3
"""Human corrections into the ledger: the record step of the proving loop.

    corrections.py github <harness dir> <ledger.jsonl> [--dry-run] [--since ISO] [--bot LOGIN]...
        reads the fork's PR review comments, reviews and issue comments on the PRs the harness
        opened (branches workbench/<task id>), keeps the human ones, and appends one ledger row
        per new comment:
          {"at","event":"corrected","source":"pr-comment","pr":N,"taskId","author","reasonCode","url"}
    corrections.py manual <ledger.jsonl> <taskId> --action takeover|edit|reject --reason CODE [--note TEXT] [--author LOGIN]
        the same row for a correction made outside GitHub (source "manual").
    corrections.py classify TEXT...     prints the reason code for each text (for a person checking the classifier)

A comment is a human correction when its author is not a bot (a login ending in [bot] or one
named with --bot, the harness's own posting identity when it has one) and its body is not the
harness's own text (the evidence packet it posts as the PR body, the retry findings, a verdict
line). On this fork the harness opens PRs as the owner and never comments, so the body test is
what separates the two. Rows are deduplicated on url (GitHub) or on the whole row (manual), so
both commands can run again and again. The reason classifier is a fixed, ordered list of word
patterns: lint, test, scope, wrong-behaviour, style, question, other.

Standard library only; gh (or gh.exe in WSL) does the reading, the fork only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

REASONS = ("lint", "test", "scope", "wrong-behaviour", "style", "question", "other")
# Ordered: the first pattern that matches names the reason. Lint before style (a line-length
# comment is lint, not taste); behaviour before test (a failing test about wrong output is
# about the output); question last among the findings, since a finding may end in a question.
PATTERNS = [
    ("lint", re.compile(r"\b(ruff|lint(?:er|ing)?|flake8|pyflakes|black|isort|prettier|pre-commit|mypy|E\d{3}|W\d{3}|F\d{3}|line[- ]length|too long|exceeds? \d+ ch|format(?:ting|ter)|trailing whitespace|unused import)\b", re.I)),
    ("test", re.compile(r"\b(tests?|pytest|coverage|assert(?:ion)?s?|parametri[sz]e|fixture|untested|test case)\b", re.I)),
    ("scope", re.compile(r"\b(out of scope|outside (the|its) scope|scope|unrelated|not asked|beyond the spec|revert|should not (have )?(touch|chang)|drive-by|unnecessary (change|file))\b", re.I)),
    ("wrong-behaviour", re.compile(r"\b(bug|wrong|incorrect|should (return|be|print|exit|raise)|breaks?|broken|regression|crash(?:es)?|fails? (on|for|with)|exit code|returns? the wrong|off by one|does not handle|doesn't handle|edge case)\b", re.I)),
    ("style", re.compile(r"\b(style|naming|rename|readab(?:le|ility)|docstring|comment|typo|wording|spelling|idiom(?:atic)?|simplif(?:y|ier)|nit|clearer|consistent)\b", re.I)),
]
QUESTION_RE = re.compile(r"\?\s*$|^\s*(why|how|what|could|should|would|can|is|are|does|do|did)\b", re.I | re.M)

# The harness's own text, never a human correction.
HARNESS_TEXT = (
    "**Workbench evidence packet**",
    "The workbench checked your change and did not accept it",
    "Opened by the workbench harness on a fork",
)
VERDICT_LINE = re.compile(r'^\s*\{"verdict":\s*"(approve|reject)"', re.M)
TASK_RE = re.compile(r"\bt-[0-9A-HJKMNP-TV-Z]{26}\b")


def classify(body: str) -> str:
    text = body or ""
    for code, pat in PATTERNS:
        if pat.search(text):
            return code
    if QUESTION_RE.search(text.strip()):
        return "question"
    return "other"


def is_harness_text(body: str) -> bool:
    text = body or ""
    return any(m in text for m in HARNESS_TEXT) or bool(VERDICT_LINE.search(text))


def is_bot(login: str, bots: list[str]) -> bool:
    return login.endswith("[bot]") or login in bots


def task_id_of(pr: dict) -> str:
    """The task id from the PR body (the packet names it) or the branch name workbench/<task id>."""
    for text in (pr.get("headRefName") or "", pr.get("body") or ""):
        m = TASK_RE.search(text)
        if m:
            return m.group(0)
    return ""


def gh_bin() -> str:
    return "gh" if shutil.which("gh") else "gh.exe"


def gh_json(*args: str):
    r = subprocess.run([gh_bin(), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"corrections: gh {' '.join(args[:3])} failed: {r.stderr.strip()[:300]}")
    out = r.stdout.replace("\r", "").strip()
    return json.loads(out) if out else []


def read_ledger(path: Path) -> list[dict]:
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def append_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rows_from_comments(pr: dict, comments: list[dict], bots: list[str], since: str | None) -> list[dict]:
    """Ledger rows for the human corrections among a PR's comments (review comments, reviews, issue comments)."""
    rows = []
    task = task_id_of(pr)
    for c in comments:
        author = ((c.get("user") or {}).get("login")) or ""
        body = c.get("body") or ""
        at = c.get("submitted_at") or c.get("created_at") or ""
        url = c.get("html_url") or ""
        if not body.strip() or not url:
            continue
        if is_bot(author, bots) or is_harness_text(body):
            continue
        if since and at and at < since:
            continue
        rows.append({"at": at or now(), "event": "corrected", "source": "pr-comment", "pr": int(pr["number"]),
                     "taskId": task, "author": author, "reasonCode": classify(body), "url": url,
                     "excerpt": body.strip().replace("\n", " ")[:160]})
    return rows


def dedupe(existing: list[dict], new: list[dict]) -> list[dict]:
    seen = {r.get("url") for r in existing if r.get("event") == "corrected" and r.get("url")}
    manual = {json.dumps({k: r.get(k) for k in ("taskId", "action", "reasonCode", "note")}, sort_keys=True)
              for r in existing if r.get("event") == "corrected" and r.get("source") == "manual"}
    out = []
    for r in new:
        if r.get("url"):
            if r["url"] in seen:
                continue
            seen.add(r["url"])
        else:
            key = json.dumps({k: r.get(k) for k in ("taskId", "action", "reasonCode", "note")}, sort_keys=True)
            if key in manual:
                continue
            manual.add(key)
        out.append(r)
    return out


def cmd_github(a: argparse.Namespace) -> int:
    config = tomllib.loads((Path(a.harness) / "config.toml").read_text(encoding="utf-8"))
    fork, upstream = config["github"]["repo"], config["github"]["upstream"]
    if fork == upstream:
        raise SystemExit("corrections: refusing to read the upstream repository")
    prs = gh_json("pr", "list", "--repo", fork, "--state", "all", "--limit", "200",
                  "--json", "number,headRefName,body,url,state,mergedAt")
    harness_prs = [p for p in prs if str(p.get("headRefName", "")).startswith("workbench/")]
    ledger = Path(a.ledger)
    existing = read_ledger(ledger)
    new: list[dict] = []
    for pr in harness_prs:
        n = pr["number"]
        comments = (gh_json("api", f"repos/{fork}/pulls/{n}/comments", "--paginate")
                    + gh_json("api", f"repos/{fork}/pulls/{n}/reviews", "--paginate")
                    + gh_json("api", f"repos/{fork}/issues/{n}/comments", "--paginate"))
        new.extend(rows_from_comments(pr, comments, a.bot, a.since))
    rows = dedupe(existing, new)
    for r in rows:
        print(f"{'would add' if a.dry_run else 'added'}  PR #{r['pr']}  {r['taskId'] or '(no task id)'}  {r['author']}  {r['reasonCode']:<15} {r['url']}")
    if not a.dry_run and rows:
        append_rows(ledger, rows)
    print(f"corrections: {len(harness_prs)} harness PR(s) on {fork}, {len(new)} human comment(s), "
          f"{len(rows)} new row(s){' (dry run, nothing written)' if a.dry_run else ''}, ledger {ledger}")
    return 0


def cmd_manual(a: argparse.Namespace) -> int:
    if not TASK_RE.fullmatch(a.taskId):
        raise SystemExit(f"corrections: {a.taskId} is not a workbench task id (t-<26 chars>)")
    ledger = Path(a.ledger)
    row = {"at": now(), "event": "corrected", "source": "manual", "taskId": a.taskId, "action": a.action,
           "reasonCode": a.reason, "author": a.author or os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"}
    if a.note:
        row["note"] = a.note
    rows = dedupe(read_ledger(ledger), [row])
    if rows:
        append_rows(ledger, rows)
        print(f"recorded  {a.taskId}  {a.action}  {a.reason}" + (f"  {a.note}" if a.note else ""))
    else:
        print(f"already recorded  {a.taskId}  {a.action}  {a.reason}" + (f"  {a.note}" if a.note else ""))
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("github")
    g.add_argument("harness")
    g.add_argument("ledger")
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--since", help="ISO timestamp; comments before it are ignored")
    g.add_argument("--bot", action="append", default=[], help="a login whose comments are the harness's own, never a human's")
    g.set_defaults(fn=cmd_github)
    m = sub.add_parser("manual")
    m.add_argument("ledger")
    m.add_argument("taskId")
    m.add_argument("--action", required=True, choices=("takeover", "edit", "reject"))
    m.add_argument("--reason", required=True, choices=REASONS)
    m.add_argument("--note", default="")
    m.add_argument("--author", default="")
    m.set_defaults(fn=cmd_manual)
    c = sub.add_parser("classify")
    c.add_argument("text", nargs="+")
    c.set_defaults(fn=lambda a: [print(f"{classify(t):<15} {t[:80]}") for t in a.text] and 0)
    a = ap.parse_args(argv)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
