#!/usr/bin/env python3
"""The intake check for shaped specs: shape_output.py [--intent ID] [--specs specs/a.md ...]

Phase 3. A shaping session turns a documented intent into a plan and draft specs. Before a
person reads them, this check asks the questions a person would ask first, and answers them
from the files and from running the checks, never from the shaper's account:

  - 2 to 4 specs, each valid for plan.py (id, class in classes.toml, scope, checks, caps)
  - every spec is a draft that names its intent: the shaper proposes, a person approves
  - no spec's scope reaches into the harness, the specs, the intents or the plans
  - every check the spec names exists, and every acceptance and fail-first check FAILS on
    today's code (a check that passes today describes work that is already done)
  - every negative ([checks] must_not_change, optional) PASSES on today's code (one that fails
    describes a bug, not an invariant: the spec is refused with the reason)
  - the plan (plans/<intent>.md) exists and names every spec

Run from the repository root (or the shaping worktree). {harness} in a check expands to the
tree's own harness/ folder, so checks the shaper added are found. Without --specs, the new
and changed spec files are taken from git status. Exit 0 when every line is PASS.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path.cwd()
HARNESS = ROOT / "harness"
sys.path.insert(0, str(HARNESS / "lib"))
import plan as planlib  # noqa: E402

problems: list[str] = []
passes: list[str] = []


def ok(msg: str) -> None:
    passes.append(msg)


def bad(msg: str) -> None:
    problems.append(msg)


def git_new_specs() -> list[Path]:
    out = subprocess.run(["git", "-c", "safe.directory=*", "status", "--porcelain", "--untracked-files=all", "--", "specs"],
                         capture_output=True, text=True, check=False).stdout
    files = []
    for line in out.splitlines():
        p = line[3:].strip()
        if p.startswith("specs/") and p.endswith(".md"):
            files.append(ROOT / p)
    return sorted(files)


def run_check(cmd: str) -> int:
    cmd = cmd.replace("{harness}", str(HARNESS))
    try:
        r = subprocess.run(["bash", "-c", cmd], cwd=ROOT, capture_output=True, text=True, timeout=300,
                           env={**os.environ, "WB_BASE_SHA": os.environ.get("WB_BASE_SHA", "")})
    except subprocess.TimeoutExpired:
        return 124
    return r.returncode


def scope_reaches_harness(scope: list[str]) -> list[str]:
    hits = []
    for s in scope:
        probe = s.replace("/**", "/x").replace("*", "x")
        if planlib.matches(probe, planlib.HARNESS_PATHS) or any(fnmatch.fnmatchcase(h, s) for h in planlib.HARNESS_PATHS):
            hits.append(s)
    return hits


def negatives_on_base(p: dict, run) -> list[tuple[str, bool]]:
    """The negatives ([checks] must_not_change) on today's code: each must PASS. One that fails
    describes a bug, not an invariant, and belongs in a bugfix spec of its own, so the spec is
    refused. Returns (line, ok) pairs; run is the check runner (injected for tests)."""
    out: list[tuple[str, bool]] = []
    for c in dict.fromkeys(p["checks"].get("mustNotChange") or []):
        rc = run(c)
        if rc == 0:
            out.append((f"{p['id']}: must_not_change holds on today's code: {c}", True))
        else:
            out.append((f"{p['id']}: refused: must_not_change already fails on today's code (exit {rc}): {c}; "
                        "a check that fails today describes a bug, not an invariant, and belongs in a bugfix spec", False))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--intent", help="the intent id the specs must name (default: the one plan under plans/)")
    ap.add_argument("--specs", nargs="*", help="spec files (default: new or changed files under specs/ per git)")
    args = ap.parse_args()

    specs = [ROOT / s for s in args.specs] if args.specs else git_new_specs()
    if not 2 <= len(specs) <= 4:
        bad(f"{len(specs)} spec file(s) found; a shaping run produces 2 to 4")
    else:
        ok(f"{len(specs)} spec file(s): {', '.join(p.name for p in specs)}")

    intent = args.intent
    plans = sorted((ROOT / "plans").glob("*.md")) if (ROOT / "plans").is_dir() else []
    if intent is None:
        if len(plans) == 1:
            intent = plans[0].stem
        elif not plans:
            bad("no plan under plans/")
        else:
            bad(f"{len(plans)} plans under plans/; pass --intent")
    plan_file = ROOT / "plans" / f"{intent}.md" if intent else None
    if plan_file and not plan_file.is_file():
        bad(f"plan missing: plans/{intent}.md")
    plan_text = plan_file.read_text(encoding="utf-8") if plan_file and plan_file.is_file() else ""
    if plan_text and len(plan_text.split()) < 80:
        bad(f"plans/{intent}.md is too short to be a plan ({len(plan_text.split())} words)")
    elif plan_text:
        ok(f"plan plans/{intent}.md, {len(plan_text.split())} words")

    always = tomllib.loads((HARNESS / "config.toml").read_text(encoding="utf-8"))["checks"]["always"]
    ids: list[str] = []
    for spec in specs:
        if not spec.is_file():
            bad(f"{spec}: missing")
            continue
        try:
            p = planlib.build_plan(HARNESS, spec)
        except SystemExit:
            bad(f"{spec.name}: plan.py rejects it (see the line above)")
            continue
        ids.append(p["id"])
        if p["kind"] != "task":
            bad(f"{p['id']}: kind must be task")
        if p["status"] != "draft":
            bad(f"{p['id']}: status is {p['status']}; the shaper proposes drafts, a person approves")
        if intent and p.get("intent") != intent:
            bad(f"{p['id']}: intent must be {intent!r}, found {p.get('intent')!r}")
        if not p["scope"]:
            bad(f"{p['id']}: scope is empty")
        reach = scope_reaches_harness(p["scope"])
        if reach:
            bad(f"{p['id']}: scope reaches the harness: {', '.join(reach)}")
        own = [c for c in p["checks"]["acceptance"] if c not in always]
        if not own:
            bad(f"{p['id']}: no acceptance checks of its own")
        if not p["checks"]["quick"]:
            bad(f"{p['id']}: no quick checks (the Stop hook needs them)")
        for c in dict.fromkeys(own + p["checks"]["failFirst"]):
            script = c.replace("{harness}", str(HARNESS)).split()
            for tok in script:
                if tok.endswith(".py") and not Path(tok).is_file():
                    bad(f"{p['id']}: check names a missing file: {tok}")
            if "changed.py" in c:
                continue  # proves a test file is part of the change; meaningful only on a result
            rc = run_check(c)
            if rc == 0:
                bad(f"{p['id']}: check passes on today's code (it must fail): {c}")
            else:
                ok(f"{p['id']}: fails on today's code (exit {rc}): {c}")
        for line, is_ok in negatives_on_base(p, run_check):
            (ok if is_ok else bad)(line)
        if plan_text and p["id"] not in plan_text:
            bad(f"{p['id']}: the plan does not name it")
        else:
            ok(f"{p['id']}: class {p['class']}, status {p['status']}, scope {', '.join(p['scope'])}")

    for line in passes:
        print(f"PASS  {line}")
    for line in problems:
        print(f"FAIL  {line}")
    print(json.dumps({"specs": ids, "intent": intent, "pass": len(passes), "fail": len(problems)}))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
