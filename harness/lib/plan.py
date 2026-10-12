#!/usr/bin/env python3
"""Turn a spec into a plan the shell scripts can read, and check a diff against its scope.

    plan.py plan <harness dir> <spec.md>          -> plan JSON on stdout
    plan.py scope <plan.json> <path>...            -> JSON list of paths outside the spec's scope
    plan.py queue <harness dir> <specs dir>        -> JSON list of plans, one per spec file

A spec is Markdown with TOML front matter between two "+++" lines. The front matter carries
what machines act on (class, scope, checks, caps); the Markdown body carries what the human
approved (intent, constraints, out of scope, acceptance criteria) and is the prompt Claude
gets. Caps in a spec may lower the harness ceilings in config.toml, never raise them.

Standard library only (Python 3.11+ for tomllib), so it runs before any install.
"""

from __future__ import annotations

import fnmatch
import json
import re
import sys
import tomllib
from pathlib import Path

ID_RE = re.compile(r"^[0-9]{4}-[a-z0-9][a-z0-9-]{1,60}$")
STATUSES = {"draft", "approved", "parked"}
# Paths no task may change, whatever its spec says: the harness judges the work, so the
# work never edits the harness.
HARNESS_PATHS = ["harness/**", "specs/**", ".claude/**", "DEMO.md", "demo/**", "CLAUDE.md"]


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


def build_plan(harness: Path, spec_path: Path) -> dict:
    config = tomllib.loads((harness / "config.toml").read_text(encoding="utf-8"))
    classes = tomllib.loads((harness / "classes.toml").read_text(encoding="utf-8"))
    meta, body = read_front_matter(spec_path)

    spec_id = meta.get("id")
    if not isinstance(spec_id, str) or not ID_RE.match(spec_id):
        fail(f"{spec_path}: id must look like 0001-short-name")
    if spec_path.stem != spec_id:
        fail(f"{spec_path}: the file name must be the id ({spec_id}.md)")
    status = meta.get("status", "draft")
    if status not in STATUSES:
        fail(f"{spec_path}: status must be one of {sorted(STATUSES)}")
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
        "class": cls,
        "classRow": class_row,
        "status": status,
        "approvedBy": meta.get("approved_by"),
        "scope": str_list(meta.get("scope"), "scope"),
        "harnessPaths": HARNESS_PATHS,
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
    else:
        fail("usage: plan.py plan <harness> <spec> | scope <plan.json> <path>... | queue <harness> <specs>")


if __name__ == "__main__":
    main(sys.argv[1:])
