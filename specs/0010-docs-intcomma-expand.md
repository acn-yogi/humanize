+++
id = "0010-docs-intcomma-expand"
title = "docs: document intcomma(expand=True)"
issue = "python-humanize/humanize#431"
intent = "0002-intcomma-should-never-return-scientific"
class = "docs"
status = "draft"
scope = ["src/humanize/number.py", "docs/number.md"]

[checks]
quick = ["python {harness}/checks/intcomma_expand_docs.py"]
acceptance = ["python {harness}/checks/intcomma_expand_docs.py"]

[caps]
max_turns = 30
max_budget_usd = 1.5
+++

# docs: document intcomma(expand=True)

Upstream issue: python-humanize/humanize#431.

## Intent

Document the option from specs 0008 and 0009. Extend the `intcomma()` docstring in the existing Google style: an `expand` entry under Args and examples showing `intcomma(1e22)` giving `'1e+22'` next to `intcomma(1e22, expand=True)` giving `'10,000,000,000,000,000,000,000'`. Add a short section to `docs/number.md`, above the `::: humanize.number` line, explaining that large floats print in scientific notation by default and that `expand=True` writes them in full.

## Constraints

- Docstring and docs only; no behaviour change. Docstring examples run as doctests, so they must be exact.
- Do not alter existing docstring wording or examples.

## Out of scope

- Code changes, tests, other functions or pages.

## Acceptance criteria

1. Fail first: the check fails on the base commit and passes on the result.
2. The docstring and `docs/number.md` carry the contents the check lists.
3. The full test suite, including doctests, passes.
