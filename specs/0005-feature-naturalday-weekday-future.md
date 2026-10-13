+++
id = "0005-feature-naturalday-weekday-future"
title = "naturalday(weekday=True) names the coming six days by weekday"
issue = "python-humanize/humanize#102"
intent = "0001-naturalday-weekdays"
class = "feature"
status = "draft"
scope = ["src/humanize/time.py", "tests/test_time.py"]

[checks]
quick = ["python {harness}/checks/naturalday_weekday_future.py", "python -m pytest -q -p no:cacheprovider tests/test_time.py"]
acceptance = ["python {harness}/checks/naturalday_weekday_future.py", "python {harness}/checks/changed.py tests/test_time.py"]

[caps]
max_turns = 35
max_budget_usd = 2.5
+++

# naturalday(weekday=True) names the coming six days by weekday

Upstream issue: python-humanize/humanize#102.

## Intent

Add a keyword argument `weekday: bool = False` to `naturalday()`. When it is true, a day
that is 2 to 6 days after today is returned as its English weekday name (`"Friday"`).
"today" and "tomorrow" keep their wording; every other day, including 7 or more days ahead,
is formatted with `format` as before. Past days are not touched here (spec 0006 handles them).

Weekday names come from the module's gettext helper, one `_("Monday")` style string per
weekday, never from `strftime("%A")`, which depends on the process locale rather than on
`humanize.i18n`.

## Constraints

- With `weekday` omitted or false, output is identical to today for every input.
- `weekday` is keyword-only-compatible: `format` stays the second positional parameter.
- Works for `date` and `datetime` values, including tz-aware ones, using the same "today"
  logic already in the function. Non-date input still returns `str(value)`.
- Add parametrized tests to `tests/test_time.py` under `freeze_time`, in the existing style,
  covering each of the six days, the day-7 boundary and the default.
- Extend the docstring (Google style) with the argument and one example.

## Out of scope

- Past days, `naturaldate()`, translations in any catalog, docs pages.

## Acceptance criteria

1. Fail first: the check fails on the base commit and passes on the result.
2. Days +2 to +6 give the weekday name; +7 and beyond use `format`.
3. `weekday=False` and the default give identical output for the days -10 to +10.
4. `tests/test_time.py` is part of the change.
5. The full test suite, `ruff` and `mypy --strict` pass.
