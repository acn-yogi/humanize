# Testing

## Install

Install humanize in editable mode with the test dependencies:

```shell
python -m pip install -e ".[tests]"
```

## Run the tests

Run the complete test suite from the repository root:

```shell
python -m pytest
```

Run a single test file:

```shell
python -m pytest tests/test_filesize.py
```

Run only the tests whose names match an expression with `-k`:

```shell
python -m pytest tests/test_number.py -k intword
```

## Skipped tests

Some translation tests in `tests/test_i18n.py` are skipped when the compiled `.mo` files
are missing. The test that checks translation updates is also skipped unless `bash`,
`xgettext`, `msgmerge` and `msgfmt` (from [gettext](https://www.gnu.org/software/gettext/))
are on your `PATH`.

To build the `.mo` files, run this from the repository root. It needs `msgfmt` on your
`PATH`:

```shell
scripts/generate-translation-binaries.sh
```

## Continuous integration

CI runs the tests with the configuration in `.github/workflows/test.yml` and `tox.ini`.
