+++
id = "0001-docs-local-testing"
title = "docs: document how to run the test suite locally"
issue = "python-humanize/humanize#430"
class = "docs"
status = "approved"
approved_by = "yogi.aradhye"
scope = ["docs/testing.md", "mkdocs.yml"]

[checks]
# Quick checks: the Stop hook runs these before Claude may finish (loop 2).
quick = ["python {harness}/checks/docs_testing.py --no-run"]
# Acceptance checks: run after the session in a fresh clone of the result, no network.
acceptance = ["python {harness}/checks/docs_testing.py"]

[caps]
max_turns = 30
max_budget_usd = 1.5
+++

# docs: document how to run the test suite locally

Upstream issue: python-humanize/humanize#430.

## Intent

A first-time contributor can run the same tests CI runs without reading the CI workflow or
`tox.ini` first. Add a short "Testing" page to the documentation that explains:

- how to install the test dependencies,
- how to run the complete test suite,
- how to run a specific test file,
- how to run a focused test with pytest's `-k` option,
- why some tests may be skipped (the translation tests need compiled `.mo` files, which
  `scripts/generate-translation-binaries.sh` builds with `msgfmt` from gettext),
- where the CI test configuration lives (`.github/workflows/test.yml` and `tox.ini`).

## Constraints

- Write the page as `docs/testing.md` and add it to the `nav` in `mkdocs.yml`, after
  "Internationalisation", titled "Testing".
- Every `pytest` command you show in a fenced code block must run and pass from the
  repository root as written. They will be executed. Use real test files and a `-k`
  expression that selects real tests.
- Match the tone and heading style of the existing pages in `docs/`. Keep it short: a
  contributor should read it in two minutes.
- Show the install step as `python -m pip install -e ".[tests]"`. Do not run installs
  yourself: the environment is already set up.

## Out of scope

- `.github/CONTRIBUTING.md` and anything else under `.github/`. The harness treats all of
  `.github/` as CI configuration, which no docs-class change may touch.
- Source code, tests, `pyproject.toml`, `tox.ini`.
- Changing how CI runs.

## Acceptance criteria

These run as checks after the session, in a fresh clone of the result with no network:

1. `docs/testing.md` exists and `mkdocs.yml` lists it in the nav.
2. The page covers each of the six points above.
3. Every pytest command on the page runs and passes as written.
4. The full test suite still passes.
