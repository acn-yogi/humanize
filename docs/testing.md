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
python -m pytest tests/test_filesize.py -k naturalsize
```

## Skipped tests

The translation tests need compiled `.mo` files. If they are missing, those tests are
skipped. Build them with `msgfmt` from [gettext](https://www.gnu.org/software/gettext/):

```shell
scripts/generate-translation-binaries.sh
```

## Continuous integration

CI runs the tests with the configuration in `.github/workflows/test.yml` and `tox.ini`.
