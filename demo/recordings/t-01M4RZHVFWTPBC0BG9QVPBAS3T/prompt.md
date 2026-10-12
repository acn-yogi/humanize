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

## How this workbench works

- This git worktree is yours alone for this task: /home/yogi/.workbench-demo/t-01M4RZHVFWTPBC0BG9QVPBAS3T/work
- The Python environment is ready. Run tests with `/home/yogi/.workbench-demo/t-01M4RZHVFWTPBC0BG9QVPBAS3T/venv/bin/python -m pytest -q -p no:cacheprovider`.
  Do not install anything.
- Edit only: src/humanize/__main__.py, src/humanize/cli.py, pyproject.toml, tests/test_cli.py, docs/cli.md, mkdocs.yml. Edits anywhere else are refused.
- When you say you are done, a Stop hook runs the spec's quick checks. If they fail you will be
  told why and asked to continue.
- After you finish, the acceptance checks run again in a fresh clone with no network, and a
  separate reviewer argues against the change. Fix causes, never checks.
- Do not run git commit. The workbench commits the worktree for you.
