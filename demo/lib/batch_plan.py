#!/usr/bin/env python3
"""Plan a mechanical batch of docs-class specs from what the repository actually needs.

    batch_plan.py scan  --python <venv python> [--src src/humanize] [--docs docs]   -> JSON list of items
    batch_plan.py write --python <venv python> --approved-by NAME [--cap 20] [--hold-back 1] [--first 100]
                                                                                 -> JSON plan, writes specs/ and plans/

Two mechanical classes of work, both documentation, both verified by a check that fails today:
  docstring   a public function whose docstring is missing a Google-style section (Examples,
              Args, Returns, Raises): harness/checks/docstring_sections.py says which
  page        a docs/<module>.md page that is only a title and the API directive:
              harness/checks/docs_module_page.py

Each item becomes one spec of class docs with scope limited to the one file, caps of 20 turns
and $1, and the check as both the quick check and the acceptance check. The last --hold-back
items are written with status = "draft" and listed separately: Act 4 runs one after the class
graduates. Standard library only.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def public_functions(src: Path) -> list[tuple[str, str]]:
    out = []
    for f in sorted(src.glob("*.py")):
        if f.name.startswith("_"):
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                out.append((f.stem, node.name))
    return out


def scan(python: str, src: Path, docs: Path) -> list[dict]:
    items = []
    for mod, fn in public_functions(src):
        target = f"humanize.{mod}:{fn}"
        r = subprocess.run([python, str(ROOT / "harness/checks/docstring_sections.py"), target],
                           capture_output=True, text=True, cwd=ROOT)
        if r.returncode != 0:
            missing = re.findall(r"missing section (\w+):|no docstring", r.stdout)
            items.append({"kind": "docstring", "module": mod, "function": fn, "target": target,
                          "file": f"src/humanize/{mod}.py",
                          "missing": [m or "docstring" for m in missing] or ["docstring"],
                          "check": f"python {{harness}}/checks/docstring_sections.py {target}"})
    for page in sorted(docs.glob("*.md")):
        mod = page.stem
        if not (src / f"{mod}.py").exists():
            continue
        r = subprocess.run([python, str(ROOT / "harness/checks/docs_module_page.py"), f"docs/{mod}.md", f"humanize.{mod}"],
                           capture_output=True, text=True, cwd=ROOT)
        if r.returncode != 0:
            items.append({"kind": "page", "module": mod, "function": None, "target": f"docs/{mod}.md",
                          "file": f"docs/{mod}.md", "missing": ["introduction", "example"],
                          "check": f"python {{harness}}/checks/docs_module_page.py docs/{mod}.md humanize.{mod}"})
    return items


def spec_text(item: dict, spec_id: str, status: str, approved_by: str) -> str:
    if item["kind"] == "docstring":
        title = f"docstring: complete the docstring of {item['module']}.{item['function']}()"
        missing = ", ".join(item["missing"])
        intent = (
            f"`humanize.{item['module']}.{item['function']}()` is public API and its docstring is missing: {missing}. "
            "A reader of the rendered documentation (mkdocstrings, Google style) should see what the function does, "
            "what each parameter means, what comes back, what it raises, and at least two examples that run."
        )
        constraints = [
            f"Edit only the docstring of `{item['function']}` in `{item['file']}`. No behaviour change: not one line of code outside the docstring.",
            "Google style, as `naturaldelta()` in `src/humanize/time.py` already does it: a one-sentence summary ending in a period, then `Args:`, `Returns:`, `Raises:` (only where the function raises) and `Examples:` sections.",
            "Every `>>>` example must pass under doctest as written (`ELLIPSIS` and whitespace normalisation are on). Use values whose output does not depend on today's date or the active locale, or activate and deactivate a locale inside the example.",
            "Lines stay within 88 characters (ruff and black run in CI).",
        ]
        out_of_scope = [
            "Any other function, any test, any page under `docs/`, `pyproject.toml`, the locale catalogs.",
            "Changing what the function returns or raises.",
        ]
        acceptance = [
            f"`python {{harness}}/checks/docstring_sections.py {item['target']}` passes: the sections are present, the Args names match the signature, the examples run.",
            "The full test suite passes.",
        ]
    else:
        title = f"docs: introduce the {item['module']} module on its documentation page"
        intent = (
            f"`docs/{item['module']}.md` is a title and the `::: humanize.{item['module']}` directive, so the published page is an API "
            "dump with no introduction. Add a short introduction above the directive: what the module is for, when "
            "to reach for it, and one runnable example block that shows two or three of its functions."
        )
        constraints = [
            f"Edit only `docs/{item['module']}.md`. Keep the `::: humanize.{item['module']}` directive as the last thing on the page.",
            "At least 60 words of prose above the directive and at least one fenced ```python block that runs as written against the installed package (it is executed by the check).",
            "Match the tone of `docs/index.md`. No claims about behaviour you have not run.",
            "Prettier with prose-wrap always and a print width of 88 runs in CI: wrap prose at 88 columns.",
        ]
        out_of_scope = [
            "`mkdocs.yml`, every other page, the source code and the tests.",
        ]
        acceptance = [
            f"`python {{harness}}/checks/docs_module_page.py docs/{item['module']}.md humanize.{item['module']}` passes.",
            "The full test suite passes.",
        ]
    fm = [
        "+++",
        f'id = "{spec_id}"',
        f'title = "{title}"',
        'class = "docs"',
        f'status = "{status}"',
        f'approved_by = "{approved_by}"' if status == "approved" else f'# approved_by = "{approved_by}" once a person approves this draft',
        f'scope = ["{item["file"]}"]',
        f'batch_item = "{item["kind"]}"',
        "",
        "[checks]",
        f'quick = ["{item["check"]}"]',
        f'acceptance = ["{item["check"]}"]',
        "",
        "[caps]",
        "max_turns = 20",
        "max_budget_usd = 1.0",
        "+++",
    ]
    body = [
        "",
        f"# {title}",
        "",
        "## Intent",
        "",
        intent,
        "",
        "## Constraints",
        "",
        *[f"- {c}" for c in constraints],
        "",
        "## Out of scope",
        "",
        *[f"- {o}" for o in out_of_scope],
        "",
        "## Acceptance criteria",
        "",
        *[f"{i}. {a}" for i, a in enumerate(acceptance, 1)],
        "",
    ]
    return "\n".join(fm + body)


def slug(item: dict) -> str:
    if item["kind"] == "docstring":
        return f"docs-docstring-{item['module']}-{item['function'].replace('_', '-')}"
    return f"docs-page-{item['module']}"


def write(items: list[dict], approved_by: str, cap: int, hold_back: int, first: int, batch_id: str) -> dict:
    items = items[:cap]
    specs_dir, plans_dir = ROOT / "specs", ROOT / "plans"
    specs_dir.mkdir(exist_ok=True)
    plans_dir.mkdir(exist_ok=True)
    # Keep the simplest items for the hold-back: a graduation proof should not hinge on the hardest spec.
    order = sorted(items, key=lambda i: (i["kind"] != "docstring", len(i["missing"])))
    held = order[:hold_back] if hold_back else []
    batch = [i for i in items if i not in held]
    rows = []
    n = first
    for item in batch + held:
        spec_id = f"{n:04d}-{slug(item)}"
        status = "approved" if item in batch else "draft"
        path = specs_dir / f"{spec_id}.md"
        existing = next(specs_dir.glob(f"[0-9][0-9][0-9][0-9]-{slug(item)}.md"), None)
        if existing is not None:
            spec_id = existing.stem
            path = existing
        else:
            path.write_text(spec_text(item, spec_id, status, approved_by), encoding="utf-8")
            n += 1
        rows.append({**item, "spec": spec_id, "path": str(path.relative_to(ROOT)).replace("\\", "/"), "status": status,
                     "held": item in held})
    today = dt.date.today().isoformat()
    plan_path = plans_dir / f"{batch_id}.md"
    lines = [
        f"# Batch plan {batch_id}: documentation the repository is missing",
        "",
        f"Planned {today} by `demo/lib/batch_plan.py` from two checks run on today's code: "
        "`harness/checks/docstring_sections.py` on every public function and "
        "`harness/checks/docs_module_page.py` on every module page. Every item below fails its check today "
        "and the same check is the spec's acceptance check, so a spec asks only for work that is missing.",
        "",
        "One human yes approves the whole batch (`harness/classes.toml`, `[batches." + batch_id + "]`). "
        "Each spec still passes its own checks in a fresh clone and its own adversarial review before it joins; "
        "one command then merges the batch.",
        "",
        "| Spec | Kind | Target | Missing today |",
        "|---|---|---|---|",
    ]
    for r in rows:
        if not r["held"]:
            lines.append(f"| `{r['spec']}` | {r['kind']} | `{r['target']}` | {', '.join(r['missing'])} |")
    if held:
        lines += ["", "Held back as drafts for the graduation step (Act 4), not part of this batch:", ""]
        for r in rows:
            if r["held"]:
                lines.append(f"- `{r['spec']}`: {r['target']}")
    lines.append("")
    plan_path.write_text("\n".join(lines), encoding="utf-8")
    return {"batch": batch_id, "plan": str(plan_path.relative_to(ROOT)).replace("\\", "/"), "specs": rows,
            "approved_by": approved_by, "date": today}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["scan", "write"])
    ap.add_argument("--python", required=True, help="a python with the repository installed (the intake venv)")
    ap.add_argument("--src", default="src/humanize")
    ap.add_argument("--docs", default="docs")
    ap.add_argument("--approved-by", default="")
    ap.add_argument("--cap", type=int, default=20)
    ap.add_argument("--hold-back", type=int, default=1)
    ap.add_argument("--first", type=int, default=100, help="the first spec number to use")
    ap.add_argument("--batch", default=f"docs-batch-{dt.date.today():%Y%m%d}")
    a = ap.parse_args()
    items = scan(a.python, ROOT / a.src, ROOT / a.docs)
    if a.command == "scan":
        print(json.dumps(items, indent=1))
        return 0
    print(json.dumps(write(items, a.approved_by, a.cap, a.hold_back, a.first, a.batch), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
