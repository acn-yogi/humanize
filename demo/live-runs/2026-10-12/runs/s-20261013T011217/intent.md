+++
id = "0001-naturalday-weekdays"
title = "naturalday() names nearby days by weekday"
issue = "python-humanize/humanize#102"
status = "documented"
documented_by = "yogi.aradhye"
documented_at = "2026-10-12"
+++

# naturalday() names nearby days by weekday

Upstream issue: python-humanize/humanize#102.

## What

`naturalday()` says "today", "tomorrow" and "yesterday", and falls back to a date format
(`Mar 05`) for every other day. People read a date within the coming or past week as a
weekday: "Friday", "last Friday", "next Monday". Give `naturalday()` an opt-in way to name
days within six days either side of today by weekday, and keep the date format for anything
further away.

## Why

A UI that lists meetings or deadlines for the week reads better as "Thursday" than as
"Oct 15", and callers today have to write that logic themselves around `naturalday()`. It
is a small, contained addition to one public function, which is also why it is the right
size for a first shaped intent on this repository.

## Constraints

- Opt in. Every existing call to `naturalday()` and `naturaldate()` returns exactly what it
  returns today. Default behaviour, default output, same for the existing tests.
- One public function gains the option; the option is a keyword argument, not a new function.
- Past and future days must be told apart in the output. Which words do that is the
  shaper's call, as long as the choice is documented and tested.
- Strings must go through the module's gettext helpers (`_`, `_ngettext`, `P_` as the file
  already uses them) so translators can pick them up later.
- Follow the file's existing style: `import datetime as dt`, Google-style docstrings with an
  example, the parametrized test style in `tests/test_time.py` under `freeze_time`.
- The whole suite stays green; `ruff` and `mypy --strict` stay clean.

## Out of scope

- Translations of the new strings into any locale catalog (a follow-up for translators).
- `naturaltime()`, `naturaldelta()`, `precisedelta()` and every other function.
- Locale-specific first day of the week, or any calendar logic beyond a six-day window.
- Changing the existing "today", "tomorrow" and "yesterday" wording.
