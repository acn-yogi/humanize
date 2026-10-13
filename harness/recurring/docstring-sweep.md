+++
# A recurring maintenance spec. No id: the schedule trigger assigns one when it enqueues this
# as specs/NNNN-docstring-sweep-<date>.md, with status = "approved", trigger =
# "schedule:docstring-sweep:<date>" and the approved_by below, which is the person who
# approved the recurring work once. Each dated instance still ends at a PR for a person.
title = "Docstring sweep: every public function keeps a complete Google-style docstring with examples that run"
class = "maintenance"
approved_by = "yogi.aradhye"
scope = ["src/humanize/*.py"]

[checks]
quick = ["python {harness}/checks/docstring_sweep.py --limit 5"]
acceptance = ["python {harness}/checks/docstring_sweep.py"]

[caps]
max_turns = 30
max_budget_usd = 2.0
+++

# Docstring sweep

A scheduled maintenance task. Every function humanize exports should carry a complete
Google-style docstring: a one-sentence summary, Args that match the signature, Returns, Raises
where the source raises, and Examples that pass under doctest.

## Intent

Bring every exported function's docstring back to that standard where it has drifted since the
last sweep: a parameter added without an Args line, an example whose output changed, a missing
Returns.

## Constraints

- Docstrings only. No change to any function's behaviour or signature, and no change to the
  tests.
- Examples must run: write them from the function's actual output in this environment.
- Follow the file's existing docstring style; do not reflow docstrings that already pass.
- When every function already passes, change nothing and say so in one line.

## Out of scope

- The documentation pages under `docs/` (a separate docs spec).
- Translations, tests, packaging.

## Acceptance criteria

1. `python {harness}/checks/docstring_sweep.py` passes: every function in `humanize.__all__`
   passes `docstring_sections.py`.
2. The full suite passes.
