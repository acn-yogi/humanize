# naturalday() names nearby days by weekday

Upstream issue: python-humanize/humanize#102.

## What

`naturalday()` says "today", "tomorrow" and "yesterday", and falls back to a date format
(`Mar 05`) for every other day. People read a date within the coming or past week as a
weekday: "Friday", "last Friday", "next Monday". Give `naturalday()` an opt-in way to name
days within six days either side of today by weekday, and keep the date format for anything
further away.

## Why

A UI that lists meetings or deadlines for the week reads better as "Thursday" than as
"Oct 15", and callers today have to write that logic themselves around `naturalday()`. It
is a small, contained addition to one public function, which is also why it is the right
size for a first shaped intent on this repository.

## Constraints

- Opt in. Every existing call to `naturalday()` and `naturaldate()` returns exactly what it
  returns today. Default behaviour, default output, same for the existing tests.
- One public function gains the option; the option is a keyword argument, not a new function.
- Past and future days must be told apart in the output. Which words do that is the
  shaper's call, as long as the choice is documented and tested.
- Strings must go through the module's gettext helpers (`_`, `_ngettext`, `P_` as the file
  already uses them) so translators can pick them up later.
- Follow the file's existing style: `import datetime as dt`, Google-style docstrings with an
  example, the parametrized test style in `tests/test_time.py` under `freeze_time`.
- The whole suite stays green; `ruff` and `mypy --strict` stay clean.

## Out of scope

- Translations of the new strings into any locale catalog (a follow-up for translators).
- `naturaltime()`, `naturaldelta()`, `precisedelta()` and every other function.
- Locale-specific first day of the week, or any calendar logic beyond a six-day window.
- Changing the existing "today", "tomorrow" and "yesterday" wording.

## Your job: shape this intent, do not implement it

You are the shaping agent of a workbench harness. Turn the intent above into a plan and 2 or 3
specs. Separate workbench sessions will implement the specs later, one spec per session, each
ending in one pull request that a person reviews. You write no code in src/, tests/ or docs/:
a spec describes the work, and a check proves whether it was done.

Explore first: the function the intent names, its tests, the docs page, how the existing specs
under specs/ are written and how their checks under harness/checks/ work.

Produce exactly these files, nowhere else (edits anywhere else are refused):

1. plans/0001-naturalday-weekdays.md: the plan. In order: the intent restated in your own words; each
   design decision you made where the intent left you a choice, with the reason; the specs in
   the order they should run, one paragraph each saying what it delivers and why it stands on
   its own; what you left out and why; what a reviewer should look at hardest. 300 to 600 words.

2. specs/NNNN-<slug>.md, 2 or 3 of them, numbered from 0005 upward, in exactly the format
   of the example below: TOML front matter between +++ lines, then a Markdown body with the
   headings Intent, Constraints, Out of scope and Acceptance criteria. Rules:
   - status = "draft" and intent = "0001-naturalday-weekdays". A person approves a spec; you never do.
   - class is one of: docs (Documentation pages under docs/ and the mkdocs nav: mechanical, no code), bugfix (A bug fix with a reproducing test that fails on the base and passes on the result), feature (A small new option on an existing public function), packaging (Anything that changes how the package is built, installed or invoked). A spec of class bugfix needs checks.fail_first.
   - scope lists only the files under src/, tests/ and docs/ (and mkdocs.yml) that the spec may
     change. Never harness/, specs/, intents/, plans/, .github/ or pyproject.toml.
   - checks.quick and checks.acceptance are commands of the form
     "python {harness}/checks/<name>.py", plus "python {harness}/checks/changed.py tests/<file>.py"
     where the spec asks for tests. Keep the literal text {harness}: the harness expands it.
   - caps: max_turns between 30 and 40, max_budget_usd between 1.5 and 3.0.

3. harness/checks/<name>.py, one per spec, in the style of the example below: a Python script
   that imports from humanize, exercises the behaviour the spec asks for with concrete cases,
   prints one FAIL line per problem or one PASS line, and exits 1 on any problem. Fail first:
   every check MUST fail on today's code, because the behaviour does not exist yet. Run each
   one yourself from the worktree root to confirm:
   `/home/yogi/.workbench-demo/s-20261013T011217/venv/bin/python harness/checks/<name>.py`. A check that passes today means the spec
   asks for nothing. Where a check needs a fixed "today", use freezegun (installed) or pass
   dates relative to datetime.date.today().

A decomposition that works here: one spec for the behaviour in src/ with its tests; one for the
user-facing documentation where that is separate work; optionally one for an edge case or
follow-up the intent calls out. Each spec must be a change a person can review in one sitting.

When you are done, say so in one line. A Stop hook then runs harness/checks/shape_output.py,
which validates the specs, confirms the plan names them and runs every check to confirm it fails
today. If anything is off you are told what and asked to continue.

## The spec format, by example: specs/0002-bugfix-precisedelta-sign.md

```markdown
+++
id = "0002-bugfix-precisedelta-sign"
title = "precisedelta() keeps the sign of a negative timedelta"
issue = "python-humanize/humanize#379"
class = "bugfix"
status = "approved"
approved_by = "yogi.aradhye"
scope = ["src/humanize/time.py", "tests/test_time.py"]

[checks]
quick = ["python {harness}/checks/precisedelta_sign.py", "python -m pytest -q -p no:cacheprovider tests/test_time.py"]
# Must fail on the base commit and pass on the result: proof the change fixed the bug.
fail_first = ["python {harness}/checks/precisedelta_sign.py"]
acceptance = ["python {harness}/checks/precisedelta_sign.py", "python {harness}/checks/changed.py tests/test_time.py"]

[caps]
max_turns = 40
max_budget_usd = 3.0
+++

# precisedelta() keeps the sign of a negative timedelta

Upstream issue: python-humanize/humanize#379.

## Intent

`precisedelta()` silently drops the sign of a negative timedelta, so
`precisedelta(timedelta(seconds=-3661))` and `precisedelta(timedelta(seconds=3661))` both
return `'1 hour, 1 minute and 1 second'`. A negative delta rendered in a UI becomes
indistinguishable from a positive one.

Preserve the sign: when the value is negative, the result is the result for its absolute
value with a leading `-`, the way `str(timedelta)` keeps its sign. So
`precisedelta(timedelta(seconds=-3661))` returns `'-1 hour, 1 minute and 1 second'`.

## Constraints

- Positive values and zero render exactly as they do today. Zero never gains a sign.
- The rule holds for every `minimum_unit`, `suppress` and `format`, and for a plain number
  of seconds as well as a `timedelta`.
- Add a parametrized regression test to `tests/test_time.py` that fails without the fix,
  following the existing test style there.
- Update the docstring with one negative example.

## Out of scope

- `naturaldelta()` and `naturaltime()`: their wording is directionless by design.
- Any other function, any i18n catalog, and packaging files.

## Acceptance criteria

1. Fail first: the reproducing check fails on the base commit and passes on the result.
2. For the cases in the check, `precisedelta(-x) == "-" + precisedelta(x)`, and zero has no sign.
3. `tests/test_time.py` is part of the change.
4. The full test suite passes.
```

## The check behind that spec: harness/checks/precisedelta_sign.py

```python
#!/usr/bin/env python3
"""Fail-first check for spec 0002 (issue #379): precisedelta() keeps the sign of a negative delta.

Must FAIL on the base commit (that is the bug) and PASS on the result. The workbench runs it
on both and records the before and after in the evidence packet.
"""

from __future__ import annotations

import datetime as dt
import sys

from humanize import precisedelta

CASES = [
    (dt.timedelta(seconds=3661), {}),
    (dt.timedelta(days=2, hours=4), {}),
    (dt.timedelta(seconds=3661), {"minimum_unit": "minutes"}),
    (dt.timedelta(milliseconds=1500), {"minimum_unit": "milliseconds"}),
    (dt.timedelta(days=400), {"suppress": ["months"]}),
    (90061, {}),
]


def main() -> int:
    problems = []
    for value, kwargs in CASES:
        positive = precisedelta(value, **kwargs)
        negative = precisedelta(-value, **kwargs)
        if negative != "-" + positive:
            problems.append(f"precisedelta(-{value!r}, {kwargs}) = {negative!r}, expected {'-' + positive!r}")
    zero = precisedelta(dt.timedelta(0))
    if zero.startswith("-"):
        problems.append(f"zero gained a sign: {zero!r}")
    for p in problems:
        print(f"FAIL: {p}")
    if not problems:
        print(f"PASS: the sign survives in all {len(CASES)} cases and zero has none")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
```

## How this workbench works

- This git worktree is yours alone for this run: /home/yogi/.workbench-demo/s-20261013T011217/work
- The Python environment is ready: `/home/yogi/.workbench-demo/s-20261013T011217/venv/bin/python` has humanize and its test extras
  installed. Run tests with `/home/yogi/.workbench-demo/s-20261013T011217/venv/bin/python -m pytest -q -p no:cacheprovider`. Do not
  install anything.
- Write only under: specs/**, harness/checks/**, plans/**. Edits anywhere else are refused.
- Do not run git commit. The harness collects your files for a person to review.
