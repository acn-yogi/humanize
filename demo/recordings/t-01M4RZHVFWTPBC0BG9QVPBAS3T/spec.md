+++
id = "0004-cli-entrypoint"
title = "A humanize command and python -m humanize"
issue = "python-humanize/humanize#184"
class = "packaging"
status = "approved"
approved_by = "yogi.aradhye"
# pyproject.toml is a package manifest: the router sends any change to it to a person, per PR,
# whatever the checks and the reviewer say. This spec is approved to RUN; its result still
# stops for a human before it can merge.
scope = ["src/humanize/__main__.py", "src/humanize/cli.py", "pyproject.toml", "tests/test_cli.py", "docs/cli.md", "mkdocs.yml"]

[checks]
quick = ["python {harness}/checks/cli_entrypoint.py"]
acceptance = ["python {harness}/checks/cli_entrypoint.py", "python {harness}/checks/changed.py tests/test_cli.py"]

[caps]
max_turns = 40
max_budget_usd = 3.0
+++

# A humanize command and python -m humanize

Upstream issue: python-humanize/humanize#184.

## Intent

Let people use the most common functions from a shell without opening Python, as the
maintainer sketched in the issue: one `humanize` command with a subcommand per function,
also reachable as `python -m humanize`.

    $ python -m humanize naturalsize 8589934592
    8.6 GB
    $ python -m humanize naturalsize --binary 8589934592
    8.0 GiB

## Constraints

- Subcommands for a small set only: `naturalsize` (with `--binary`, `--gnu` and `--format`),
  `intcomma`, `intword` and `naturaldelta` (seconds as a number).
- Standard library `argparse` only. No new dependency.
- A console script `humanize = "humanize.cli:main"` under `[project.scripts]` in
  `pyproject.toml`, and `src/humanize/__main__.py` calling the same `main`.
- Errors go to stderr with a non-zero exit; output is the bare result and a newline.
- Tests in `tests/test_cli.py` that call `main()` with arguments and read stdout.

## Out of scope

- Every other function. Shell completion. Reading values from stdin.
- Any change to existing public functions.

## Acceptance criteria

1. `python -m humanize naturalsize 8589934592` prints `8.6 GB`; with `--binary`, `8.0 GiB`;
   `python -m humanize intcomma 1234567` prints `1,234,567`.
2. `pyproject.toml` declares the `humanize` console script.
3. `tests/test_cli.py` is part of the change, and the full suite passes.
4. A person approves the PR: it changes the package manifest, which is high risk by policy.
