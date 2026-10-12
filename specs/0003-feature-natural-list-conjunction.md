+++
id = "0003-feature-natural-list-conjunction"
title = "natural_list() takes a conjunction"
issue = "python-humanize/humanize#214"
class = "feature"
# Claude drafted this spec from the issue. A person has not approved its intent yet, so the
# dispatcher leaves it in the queue: no spend until a human says yes to the intent.
status = "draft"
scope = ["src/humanize/lists.py", "tests/test_lists.py", "docs/lists.md"]

[checks]
quick = ["python {harness}/checks/natural_list_conjunction.py"]
acceptance = ["python {harness}/checks/natural_list_conjunction.py", "python {harness}/checks/changed.py tests/test_lists.py"]

[caps]
max_turns = 30
max_budget_usd = 2.0
+++

# natural_list() takes a conjunction

Upstream issue: python-humanize/humanize#214.

## Intent

`natural_list([1, 2, 3])` always joins with "and". Callers need "or" too, and the maintainer
suggested accepting any string. Add a keyword argument `conjunction: str = "and"` so that
`natural_list([1, 2, 3], conjunction="or")` returns `'1, 2 or 3'`.

## Constraints

- The default output does not change.
- Any string works: `conjunction="and also"` gives `'1, 2 and also 3'`.
- No Oxford comma, matching today's output.
- Document the parameter in the docstring with an example.
- Add tests to `tests/test_lists.py` in the existing parametrized style.

## Out of scope

- Translating the conjunction (there is no i18n for this function today; a separate issue).
- Any other function.

## Acceptance criteria

1. The check's cases pass, including the default, "or", two items, one item, no items and a
   multi-word conjunction.
2. The docstring documents `conjunction`.
3. `tests/test_lists.py` is part of the change.
4. The full test suite passes.
