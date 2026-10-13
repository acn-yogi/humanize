+++
id = "0006-feature-naturalday-weekday-past"
title = "naturalday(weekday=True) names the past six days \"last <weekday>\""
issue = "python-humanize/humanize#102"
intent = "0001-naturalday-weekdays"
class = "feature"
status = "draft"
scope = ["src/humanize/time.py", "tests/test_time.py"]

[checks]
quick = ["python {harness}/checks/naturalday_weekday_past.py", "python -m pytest -q -p no:cacheprovider tests/test_time.py"]
acceptance = ["python {harness}/checks/naturalday_weekday_past.py", "python {harness}/checks/changed.py tests/test_time.py"]

[caps]
max_turns = 35
max_budget_usd = 2.5
+++

# naturalday(weekday=True) names the past six days "last <weekday>"

Upstream issue: python-humanize/humanize#102.

## Intent

Builds on spec 0005, which added `weekday=True` for future days. With `weekday=True`, a
day 2 to 6 days before today is returned as `"last Friday"`. This is how past and future are
told apart: future days are the bare weekday, past days carry "last". "yesterday" keeps its
wording, and days 7 or more back use `format`.

The phrase is one translatable template, `_("last %s")` applied to the already translated
weekday name, so a translator can reorder it. Reuse the weekday names from 0005.

## Constraints

- Everything 0005 guarantees still holds, and the default output is unchanged.
- No ambiguity: a past weekday never renders as a bare name, a future one never gets "last".
- Add parametrized tests to `tests/test_time.py` under `freeze_time` for each of days -2 to
  -6, the day -7 boundary, a `datetime` value, and a check that `naturaldate()` is unchanged.
- Update the docstring example to show a past day.

## Out of scope

- "this" or "next" prefixes, `naturaldate()` changes, translations in catalogs, docs pages.

## Acceptance criteria

1. Fail first: the check fails on the base commit and passes on the result.
2. Days -2 to -6 give `last <weekday>`; -7 and beyond use `format`.
3. Days +2 to +6 still give the bare weekday.
4. `tests/test_time.py` is part of the change.
5. The full test suite, `ruff` and `mypy --strict` pass.
