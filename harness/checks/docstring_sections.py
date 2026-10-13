#!/usr/bin/env python3
"""Check that a public function's docstring is complete, Google style, with examples that run.

    docstring_sections.py humanize.time:naturalday [--needs Examples,Args,Returns,Raises]

Run from the repository root of the result (the installed humanize is the tree under test).
Without --needs, the sections required are derived from the function: a one-line summary
always; Args when the function takes parameters; Returns when it is not annotated -> None;
Raises when its source raises; Examples always, and every example must pass under doctest.
The Args names must match the signature. Prints one FAIL line per problem or one PASS line,
exits 1 on any problem. Fail first: on today's code the function this spec names is missing
at least one of these sections, so this check fails on the base and passes on the result.
"""

from __future__ import annotations

import argparse
import doctest
import importlib
import inspect
import io
import re
import sys

SECTION_RE = re.compile(r"^(Args|Returns|Raises|Examples|Yields|Note|Notes):\s*$", re.M)


def sections(doc: str) -> dict[str, str]:
    """Google-style sections of a docstring: name -> body text."""
    out: dict[str, str] = {}
    matches = list(SECTION_RE.finditer(doc))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(doc)
        out[m.group(1)] = doc[m.end():end]
    return out


def needed(fn) -> list[str]:
    needs = ["Examples"]
    sig = inspect.signature(fn)
    if any(p.name not in ("self", "cls") for p in sig.parameters.values()):
        needs.append("Args")
    if sig.return_annotation not in (None, "None", type(None)):
        needs.append("Returns")
    try:
        src = inspect.getsource(fn)
    except OSError:
        src = ""
    if re.search(r"^\s+raise\s", src, re.M):
        needs.append("Raises")
    return needs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="module:function, for example humanize.time:naturalday")
    ap.add_argument("--needs", help="comma separated sections to require (default: derived from the function)")
    a = ap.parse_args()
    mod_name, _, fn_name = a.target.partition(":")
    mod = importlib.import_module(mod_name)
    fn = getattr(mod, fn_name, None)
    problems: list[str] = []
    if fn is None:
        print(f"FAIL: {a.target}: no such function")
        return 1
    doc = inspect.getdoc(fn) or ""
    if not doc.strip():
        print(f"FAIL: {a.target}: no docstring")
        return 1
    summary = doc.strip().splitlines()[0]
    if len(summary) < 10 or not summary.endswith("."):
        problems.append(f"summary line should be one sentence ending in a period: {summary!r}")
    needs = [s.strip() for s in a.needs.split(",")] if a.needs else needed(fn)
    found = sections(doc)
    for s in needs:
        if s not in found or not found[s].strip():
            problems.append(f"missing section {s}:")
    if "Args" in found:
        documented = set(re.findall(r"^\s{0,8}(\*{0,2}\w+)(?:\s*\([^)]*\))?:", found["Args"], re.M))
        params = {("*" if p.kind == p.VAR_POSITIONAL else "**" if p.kind == p.VAR_KEYWORD else "") + p.name
                  for p in inspect.signature(fn).parameters.values() if p.name not in ("self", "cls")}
        for missing in sorted(params - documented):
            problems.append(f"Args: parameter {missing} is not documented")
        for extra in sorted(documented - params):
            problems.append(f"Args: documents {extra}, which is not a parameter")
    if "Examples" in found:
        if ">>>" not in found["Examples"]:
            problems.append("Examples: no >>> example to run")
        else:
            finder = doctest.DocTestFinder(recurse=False)
            runner = doctest.DocTestRunner(optionflags=doctest.ELLIPSIS | doctest.NORMALIZE_WHITESPACE, verbose=False)
            out = io.StringIO()
            for test in finder.find(fn, fn_name, module=mod):
                runner.run(test, out=out.write)
            if runner.failures:
                problems.append(f"Examples: {runner.failures} doctest failure(s)")
                for line in out.getvalue().splitlines()[:12]:
                    problems.append("  " + line)
            elif runner.tries == 0:
                problems.append("Examples: doctest found nothing to run")
    for p in problems:
        print(f"FAIL: {a.target}: {p}")
    if not problems:
        print(f"PASS: {a.target}: sections {', '.join(needs)} present; {runner.tries if 'Examples' in found else 0} example(s) pass")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
