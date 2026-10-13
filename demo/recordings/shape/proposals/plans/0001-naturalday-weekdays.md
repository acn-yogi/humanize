# Plan 0001: naturalday() names nearby days by weekday

## The intent, restated

`naturalday()` should be able to say "Friday" or "last Friday" for days within six days of
today instead of "Oct 16". It must be opt-in, so every existing call returns what it does
now, and it must be one keyword on the existing function, with translatable strings and
tests in the file's current style.

## Design decisions

- **Option name and type: `weekday: bool = False`.** A boolean matches the intent's
  "opt-in keyword" and cannot collide with `format`, which stays the second positional
  parameter so no existing call changes meaning.
- **Wording: bare weekday for future, "last <weekday>" for past.** The intent says the
  two must be told apart and leaves the words to us. These mirror the examples in the
  intent ("Friday", "last Friday"). I did not use "next" for the future because "Friday"
  alone already reads as the coming one and keeps the common case short.
- **Window: 2 to 6 days either side.** Days 0 and ±1 keep today's wording. Day 7 would
  repeat today's weekday and be ambiguous, so it falls back to the date format.
- **Weekday names through gettext, not `strftime("%A")`.** `strftime` follows the process
  locale, while the module translates through `humanize.i18n`. Each name and the
  `"last %s"` template are separate `_()` strings. Catalogs are left to translators.
- **Past and future split into two specs.** The past wording is the only genuine design
  choice in the feature and deserves its own review.

## The specs, in order

1. **0005-feature-naturalday-weekday-future** adds the keyword, the weekday-name
   machinery and future days, with tests. It stands alone: `weekday=True` is useful and
   safe on its own, and past days simply behave as today.
2. **0006-feature-naturalday-weekday-past** adds "last <weekday>" for past days. It
   depends on 0005 for the keyword and names, but is a small diff over it.
3. **0007-docs-naturalday-weekdays** documents the option in `docs/time.md`. It is
   separate, docs-only work and can be reviewed without reading the code, so it runs last
   when the behaviour is final.

## Left out

Translations of new strings, `naturaldate()` and every other function, locale-specific
first day of the week, "this/next" prefixes, and any change to the existing wording. All
are excluded by the intent or are follow-ups.

## What a reviewer should look at hardest

- That the default path is byte-for-byte the old behaviour; the check compares
  `weekday=False` with the default for days -10 to +10, but the diff deserves a read.
- The boundary at day ±6 versus ±7, including tz-aware datetimes, where "today" is
  computed in the value's timezone.
- That every user-visible string goes through `_`, and that "last %s" wraps an
  already-translated weekday name.
- That the examples in the docs match real output.
- Spec 0005 leaves past days unchanged on purpose; confirm 0006 closes that gap.
