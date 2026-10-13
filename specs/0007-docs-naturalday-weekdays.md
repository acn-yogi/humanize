+++
id = "0007-docs-naturalday-weekdays"
title = "docs: document naturalday(weekday=True)"
issue = "python-humanize/humanize#102"
intent = "0001-naturalday-weekdays"
class = "docs"
status = "draft"
scope = ["docs/time.md"]

[checks]
quick = ["python {harness}/checks/naturalday_weekday_docs.py"]
acceptance = ["python {harness}/checks/naturalday_weekday_docs.py"]

[caps]
max_turns = 30
max_budget_usd = 1.5
+++

# docs: document naturalday(weekday=True)

Upstream issue: python-humanize/humanize#102.

## Intent

`docs/time.md` is only an API reference today. Add a short "Weekday names" section above
the `::: humanize.time` line that explains the opt-in `weekday=True` option of
`naturalday()`: days within six days ahead read as `Friday`, days within six days back as
`last Friday`, "today", "tomorrow" and "yesterday" keep their wording, and anything further
away uses the date format. Include a small example block with outputs that match the
behaviour from specs 0005 and 0006, written relative to a stated fixed date.

## Constraints

- Only `docs/time.md` changes; keep the `::: humanize.time` reference.
- Examples must be accurate for the implemented behaviour.
- No code changes.

## Out of scope

- Any source, test or mkdocs.yml change, and translation instructions.

## Acceptance criteria

1. Fail first: the check fails on the base commit and passes on the result.
2. The page names `naturalday`, shows `weekday=True`, the "last" wording and the six-day window.
3. The section comes before the API reference.
