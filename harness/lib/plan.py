#!/usr/bin/env python3
"""Turn a spec into a plan the shell scripts can read, and check a diff against its scope.

    plan.py plan <harness dir> <spec.md>          -> plan JSON on stdout
    plan.py scope <plan.json> <path>...            -> JSON list of paths outside the spec's scope
    plan.py queue <harness dir> <specs dir>        -> JSON list of plans, one per spec file
    plan.py phase <harness dir>                    -> the phase, as JSON {phase, name, source}

A spec is Markdown with TOML front matter between two "+++" lines. The front matter carries
what machines act on (class, scope, checks, caps); the Markdown body carries what the human
approved (intent, constraints, out of scope, acceptance criteria) and is the prompt Claude
gets. Caps in a spec may lower the harness ceilings in config.toml, never raise them.

Every plan carries the harness phase (config.toml [harness] phase, 0 to 3), which the
dispatcher's forecast, the router and the shaper honour. WORKBENCH_PHASE in the operator's
environment overrides it for one command; the plan records which source it came from.

Standard library only (Python 3.11+ for tomllib), so it runs before any install.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
import tomllib
from pathlib import Path

ID_RE = re.compile(r"^[0-9]{4}-[a-z0-9][a-z0-9-]{1,60}$")
STATUSES = {"draft", "approved", "parked"}
KINDS = {"task", "shape"}
PHASES = {0: "assess", 1: "assisted", 2: "autonomous by class", 3: "self-improving"}
# Paths no task may change, whatever its spec says: the harness judges the work, so the
# work never edits the harness. Intents and plans are what people approve; specs are what
# the harness runs; none of them is a task's to change.
HARNESS_PATHS = ["harness/**", "specs/**", "intents/**", "plans/**", ".claude/**", "DEMO.md", "demo/**", "CLAUDE.md"]
# A shaping session (phase 3) proposes specs, checks and a plan, all as drafts a person
# approves. Everything else in the harness stays closed to it.
SHAPE_HARNESS_PATHS = [
    "harness/bin/**", "harness/lib/**", "harness/hooks/**", "harness/pack/**", "harness/proofs/**",
    "harness/guardrails/**", "harness/shaping/**", "harness/systemd/**", "harness/config.toml",
    "harness/classes.toml", "harness/.gitattributes", "intents/**", ".claude/**", "DEMO.md", "demo/**", "CLAUDE.md",
]


def fail(msg: str) -> None:
    print(f"plan.py: {msg}", file=sys.stderr)
    sys.exit(2)


def read_front_matter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"\A\+\+\+\n(.*?)\n\+\+\+\n(.*)\Z", text, re.S)
    if not m:
        fail(f"{path}: no TOML front matter between +++ lines")
    try:
        meta = tomllib.loads(m.group(1))
    except tomllib.TOMLDecodeError as e:
        fail(f"{path}: front matter is not valid TOML: {e}")
    return meta, m.group(2).strip() + "\n"


def str_list(value, what: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        fail(f"{what} must be a list of strings")
    return value


def read_phase(config: dict) -> dict:
    """The harness phase: WORKBENCH_PHASE from the operator's environment, else config.toml."""
    source = "harness/config.toml"
    raw = config.get("harness", {}).get("phase", 2)
    env = os.environ.get("WORKBENCH_PHASE")
    if env is not None and env != "":
        raw, source = env, "WORKBENCH_PHASE (operator override for this command)"
    try:
        phase = int(raw)
    except (TypeError, ValueError):
        fail(f"phase must be a whole number 0 to 3, not {raw!r} (from {source})")
    if phase not in PHASES:
        fail(f"phase must be 0 to 3, not {phase} (from {source})")
    return {"phase": phase, "name": PHASES[phase], "source": source}


def build_plan(harness: Path, spec_path: Path) -> dict:
    config = tomllib.loads((harness / "config.toml").read_text(encoding="utf-8"))
    classes = tomllib.loads((harness / "classes.toml").read_text(encoding="utf-8"))
    meta, body = read_front_matter(spec_path)
    phase = read_phase(config)

    spec_id = meta.get("id")
    if not isinstance(spec_id, str) or not ID_RE.match(spec_id):
        fail(f"{spec_path}: id must look like 0001-short-name")
    if spec_path.stem != spec_id:
        fail(f"{spec_path}: the file name must be the id ({spec_id}.md)")
    status = meta.get("status", "draft")
    if status not in STATUSES:
        fail(f"{spec_path}: status must be one of {sorted(STATUSES)}")
    kind = meta.get("kind", "task")
    if kind not in KINDS:
        fail(f"{spec_path}: kind must be one of {sorted(KINDS)}")
    cls = meta.get("class")
    class_row = classes.get("classes", {}).get(cls)
    if class_row is None:
        fail(f"{spec_path}: class {cls!r} is not in classes.toml")

    ceilings = config["caps"]
    caps = dict(ceilings)
    for key, value in (meta.get("caps") or {}).items():
        if key not in ceilings:
            fail(f"{spec_path}: unknown cap {key}")
        if not isinstance(value, (int, float)) or value <= 0:
            fail(f"{spec_path}: cap {key} must be a positive number")
        # A spec may lower a cap, never raise it above the harness ceiling.
        caps[key] = min(value, ceilings[key])

    checks = meta.get("checks") or {}
    fail_first = str_list(checks.get("fail_first"), "checks.fail_first")
    if class_row.get("fail_first") and not fail_first:
        fail(f"{spec_path}: class {cls} needs checks.fail_first (a check that fails on the base)")

    batch_id = class_row.get("batch")
    batch_row = classes.get("batches", {}).get(batch_id) if batch_id else None

    return {
        "id": spec_id,
        "file": str(spec_path),
        "title": meta.get("title", spec_id),
        "issue": meta.get("issue"),
        "intent": meta.get("intent"),
        "kind": kind,
        "class": cls,
        "classRow": class_row,
        "status": status,
        "approvedBy": meta.get("approved_by"),
        # What put the spec in the queue: "ticket:<n>" (the ticket watch), "schedule:<name>:<date>"
        # (a schedule entry), or null when a person wrote and approved it by hand.
        "trigger": meta.get("trigger"),
        "triggeredAt": meta.get("triggered_at"),
        "scope": str_list(meta.get("scope"), "scope"),
        "harnessPaths": SHAPE_HARNESS_PATHS if kind == "shape" else HARNESS_PATHS,
        "checks": {
            "quick": str_list(checks.get("quick"), "checks.quick"),
            "acceptance": str_list(config["checks"]["always"], "config checks.always")
            + str_list(checks.get("acceptance"), "checks.acceptance"),
            "failFirst": fail_first,
        },
        "setup": str_list(config["setup"]["commands"], "config setup.commands"),
        "caps": caps,
        "models": config["models"],
        "github": config["github"],
        "sandbox": config["sandbox"],
        "phase": phase["phase"],
        "phaseName": phase["name"],
        "phaseSource": phase["source"],
        "batchPlanId": batch_id,
        "batchPlanRow": ({"class": f"batch:{batch_id}", **batch_row} if batch_row else None),
        "body": body,
    }


def matches(path: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if fnmatch.fnmatchcase(path, pat):
            return True
        # "docs/**" also names the folder itself.
        if pat.endswith("/**") and path == pat[:-3]:
            return True
    return False


def out_of_scope(plan: dict, paths: list[str]) -> dict:
    harness = [p for p in paths if matches(p, plan["harnessPaths"])]
    outside = [p for p in paths if p not in harness and not matches(p, plan["scope"])]
    return {"harness": harness, "outside": outside}


def main(argv: list[str]) -> None:
    if len(argv) >= 3 and argv[0] == "plan":
        print(json.dumps(build_plan(Path(argv[1]), Path(argv[2]))))
    elif len(argv) >= 2 and argv[0] == "scope":
        plan = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        print(json.dumps(out_of_scope(plan, argv[2:])))
    elif len(argv) == 3 and argv[0] == "queue":
        specs = sorted(Path(argv[2]).glob("[0-9][0-9][0-9][0-9]-*.md"))
        print(json.dumps([build_plan(Path(argv[1]), s) for s in specs]))
    elif len(argv) == 2 and argv[0] == "phase":
        config = tomllib.loads((Path(argv[1]) / "config.toml").read_text(encoding="utf-8"))
        print(json.dumps(read_phase(config)))
    else:
        fail("usage: plan.py plan <harness> <spec> | scope <plan.json> <path>... | queue <harness> <specs> | phase <harness>")


if __name__ == "__main__":
    main(sys.argv[1:])
