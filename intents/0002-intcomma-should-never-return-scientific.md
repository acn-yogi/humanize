+++
id = "0002-intcomma-should-never-return-scientific"
title = "intcomma should never return scientific notation for large floats"
issue = "python-humanize/humanize#431"
status = "documented"
documented_by = "the audience"
documented_at = "2026-10-12"
captured = "non-interactive: the ask is the audience's; constraints and out of scope are the harness defaults"
+++

# intcomma should never return scientific notation for large floats

Upstream issue: python-humanize/humanize#431.

## What

intcomma should never return scientific notation for large floats

## Why

Someone asked for it, in one line, with the audience watching. The shaper's job is to turn
that line into a plan and specs whose checks fail on today's code, so that what the audience
asked for and what the harness will verify are the same thing.

## Constraints

- Opt in where behaviour changes: every existing call returns exactly what it returns today,
  and the existing tests pass unchanged.
- One public function per spec where possible; a new option is a keyword argument, not a new
  function.
- Strings go through the module's gettext helpers so translators can pick them up.
- Follow the file's existing style: Google-style docstrings with an example, the parametrized
  test style of the matching `tests/test_*.py`.
- The whole suite stays green; `ruff` and `mypy --strict` stay clean.

## Out of scope

- Translations into any locale catalog.
- Any function the ask does not name, and anything under `.github/`, `pyproject.toml` or the
  harness.
- Changing existing wording or defaults.
