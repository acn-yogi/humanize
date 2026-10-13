+++
id = "0009-feature-intcomma-expand-edges"
title = "intcomma(expand=True) also covers tiny floats, strings and locales"
issue = "python-humanize/humanize#431"
intent = "0002-intcomma-should-never-return-scientific"
class = "feature"
status = "draft"
scope = ["src/humanize/number.py", "tests/test_number.py", "tests/test_i18n.py"]

[checks]
quick = ["python {harness}/checks/intcomma_expand_edges.py", "python -m pytest -q -p no:cacheprovider tests/test_number.py tests/test_i18n.py"]
acceptance = ["python {harness}/checks/intcomma_expand_edges.py", "python {harness}/checks/changed.py tests/test_number.py"]

[caps]
max_turns = 40
max_budget_usd = 3.0
+++

# intcomma(expand=True) also covers tiny floats, strings and locales

Upstream issue: python-humanize/humanize#431.

## Intent

Spec 0008 adds `expand=True` for large floats. The same promise, "never scientific notation", must hold for the other inputs `intcomma()` accepts: tiny floats (`1e-7` becomes `'0.0000001'`), strings in exponent notation (`"1e20"` becomes `'100,000,000,000,000,000,000'`, where today the string comes back unchanged) and active locales (under `de_DE`, `1.5e20` becomes `'150.000.000.000.000.000.000'` and `1e-7` becomes `'0,0000001'`).

## Constraints

- Builds on spec 0008; reuse its formatting path rather than adding a second one.
- Only `expand=True` changes behaviour; the default output stays as it is today, including `"1e20"` returned unchanged.
- Inf, NaN, `None` and non-numeric strings give the same result with `expand=True` as without.
- Add parametrized cases to `tests/test_number.py`, and one locale case to `tests/test_i18n.py` that deactivates the locale afterwards.

## Out of scope

- The large-float behaviour itself (spec 0008), docs (spec 0010), any catalog changes.

## Acceptance criteria

1. Fail first: the check fails on the base commit and passes on the result.
2. Tiny floats, exponent strings and a German locale expand as listed in the check.
3. `tests/test_number.py` is part of the change.
4. The full test suite passes; `ruff` and `mypy --strict` are clean.
