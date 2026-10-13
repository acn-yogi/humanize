+++
id = "0008-feature-intcomma-expand-floats"
title = "intcomma() takes expand=True to write large floats in full"
issue = "python-humanize/humanize#431"
intent = "0002-intcomma-should-never-return-scientific"
class = "feature"
status = "draft"
scope = ["src/humanize/number.py", "tests/test_number.py"]

[checks]
quick = ["python {harness}/checks/intcomma_expand_floats.py", "python -m pytest -q -p no:cacheprovider tests/test_number.py"]
acceptance = ["python {harness}/checks/intcomma_expand_floats.py", "python {harness}/checks/changed.py tests/test_number.py"]

[caps]
max_turns = 40
max_budget_usd = 3.0
+++

# intcomma() takes expand=True to write large floats in full

Upstream issue: python-humanize/humanize#431.

## Intent

`intcomma(1e22)` returns `'1e+22'` and `intcomma(1.5e20)` returns `'1.5e+20'`: for large floats the result is Python's scientific notation, not digits with separators. Add a keyword argument `expand: bool = False` to `intcomma()`. With `expand=True`, a float is written in full positional notation with the thousands separators, so `intcomma(1e22, expand=True)` returns `'10,000,000,000,000,000,000,000'`.

Format floats from their shortest repr (for example `format(Decimal(repr(value)), ",f")`), so `1.5e20` gives `150,000,000,000,000,000,000` and no spurious digits appear.

## Constraints

- With `expand` left at its default, every call returns exactly what it does today, including `'1e+22'`.
- `expand` comes last, after `ndigits`; existing positional calls keep their meaning.
- With `ndigits` given, the result is fixed-point already; `expand=True` must not change it.
- Integers, non-finite values and the locale separators behave as today.
- Add parametrized cases to `tests/test_number.py`, in the style of `test_intcomma`.

## Out of scope

- Small floats such as `1e-7` and exponent-notation strings (spec 0009).
- Docstring and docs page (spec 0010); any other function, any i18n catalog.

## Acceptance criteria

1. Fail first: the check fails on the base commit and passes on the result.
2. `expand=True` writes the check's large floats in full; the default output is unchanged.
3. `tests/test_number.py` is part of the change.
4. The full test suite passes; `ruff` and `mypy --strict` are clean.
