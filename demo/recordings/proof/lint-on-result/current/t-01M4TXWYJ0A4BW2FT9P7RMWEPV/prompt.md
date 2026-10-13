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

## How this workbench works

- This git worktree is yours alone for this task: /home/yogi/.workbench-demo/t-01M4TXWYJ0A4BW2FT9P7RMWEPV/work
- The Python environment is ready. Run tests with `/home/yogi/.workbench-demo/t-01M4TXWYJ0A4BW2FT9P7RMWEPV/venv/bin/python -m pytest -q -p no:cacheprovider`.
  Do not install anything.
- Edit only: src/humanize/time.py, tests/test_time.py. Edits anywhere else are refused.
- When you say you are done, a Stop hook runs the spec's quick checks. If they fail you will be
  told why and asked to continue.
- After you finish, the acceptance checks run again in a fresh clone with no network, and a
  separate reviewer argues against the change. Fix causes, never checks.
- Do not run git commit. The workbench commits the worktree for you.
