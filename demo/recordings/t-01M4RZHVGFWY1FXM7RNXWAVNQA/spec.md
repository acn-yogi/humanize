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
