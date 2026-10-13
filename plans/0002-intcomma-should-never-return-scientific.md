# Plan 0002: intcomma() can write large floats without scientific notation

## The intent, restated

`intcomma(1e22)` returns `'1e+22'`, which defeats the point of a function that promises digits
with separators. The audience asked that it never return scientific notation. Because every
existing call must keep its output, the guarantee has to be something a caller turns on.

## Design decisions

- **A keyword, `expand: bool = False`, last in the signature.** The constraints rule out
  changing defaults and new functions. A boolean after `ndigits` leaves positional calls
  untouched. The literal ask, "never", holds for callers who opt in; I did not make it the
  default because `'1e+22'` is today's output and callers may depend on it.
- **Format from the shortest repr via `Decimal`.** `Decimal(repr(x))` formatted with `,f`
  gives `1.5e20` as `150,000,000,000,000,000,000`. Formatting the float's exact binary value
  would print noise digits, so I rejected it.
- **`ndigits` is untouched.** It already yields fixed-point text for floats.
- **No new user-visible strings,** so no gettext work. Locale separators are still applied
  by the existing translate step, and a spec checks that.

## The specs, in order

- **0008-feature-intcomma-expand-floats** adds the option and handles large floats, the case
  in the issue title. It stands alone: it ships a working opt-in with tests.
- **0009-feature-intcomma-expand-edges** extends the guarantee to tiny floats (`1e-7`),
  strings such as `"1e20"` and an active locale. It is separate because it touches the string
  parsing path and the i18n test, which a reviewer should read on its own. It needs 0008.
- **0010-docs-intcomma-expand** documents the option in the docstring and `docs/number.md`.
  It is mechanical, has no behaviour change and runs last so the examples match what shipped.

## Left out

- Making expansion the default, or changing any existing output.
- `intword`, `scientific`, `metric` and every other function; catalog translations.
- Very long float strings with more than 17 digits: they keep going through the float path.

## What a reviewer should look at hardest

- That the default path is byte-for-byte as before, including `'1e+22'` and `"1e20"` returned
  unchanged.
- That `Decimal(repr(x))` is used rather than the exact binary expansion, and that negative
  values and `-0.0` come out sensibly.
- That the exponent-string handling in 0009 does not alter how plain strings such as
  `"1.234.567,89"` are parsed under other locales.
- That doctests in 0010 are exact, since they run in the test suite.
