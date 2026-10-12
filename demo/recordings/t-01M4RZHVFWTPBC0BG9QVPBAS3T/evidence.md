**Workbench evidence packet** for spec `0004-cli-entrypoint`, from upstream issue python-humanize/humanize#184.

> **Route: per PR: a person reviews this change.** A person reviews this PR.
> - high risk: touches package manifests or lockfiles (pyproject.toml)
> - high risk: class packaging is high risk by policy
> - adversarial review raised findings
> - intword/intcomma print unhumanized input with exit 0 for inputs like 1e3, 1e6, 1200000.5 that the CLI's own validation accepts, so errors don't reliably go to stderr with a non-zero exit as the spec requires
> - tests only cover abc/nan/inf, so this silent failure path is untested
> - huge integers are rejected with a misleading 'not a finite number' error
> - harness facts report touchesManifests=false although pyproject.toml changed; the required human approval must not be skipped
> - two commits with the same message, where the second deletes docs the first added; should be squashed

### What a person approved
- Spec `specs/0004-cli-entrypoint.md`, class `packaging`, intent approved by yogi.aradhye.
- Scope: `src/humanize/__main__.py`, `src/humanize/cli.py`, `pyproject.toml`, `tests/test_cli.py`, `docs/cli.md`, `mkdocs.yml`.

### Acceptance checks (fresh clone of the result, bubblewrap, no network)
| Check | Result |
|---|---|
| `python -m pytest -q -p no:cacheprovider -x` | pass |
| `python {harness}/checks/cli_entrypoint.py` | pass |
| `python {harness}/checks/changed.py tests/test_cli.py` | pass |

**Scope.** 4 file(s), 132 line(s) changed: `pyproject.toml`, `src/humanize/__main__.py`, `src/humanize/cli.py`, `tests/test_cli.py`. All inside the spec's scope.

### Rounds: what was rejected, and what the retry fixed
| Round | Checks | Reviewer | Router |
|---|---|---|---|
| 0 | pass | reject | per_pr |
| 1 | pass | reject | per_pr |

Round 0 findings, handed back to the same session with `claude --resume` (loop 3):
- intcomma/intword echo non-numeric input (e.g. 'abc') to stdout with exit 0, violating 'errors go to stderr with non-zero exit'
- naturaldelta accepts inf/nan and prints them with exit 0
- error-path tests cover only naturalsize and naturaldelta, so the gap is untested
- adds docs/cli.md and an mkdocs nav entry beyond the spec's scope
- pyproject.toml changed but touchesManifests reports false; needs explicit human approval per criterion 4

### Adversarial review
A second Claude Code session (`opus`, edits denied) argued against the change: **reject**.
- intword/intcomma print unhumanized input with exit 0 for inputs like 1e3, 1e6, 1200000.5 that the CLI's own validation accepts, so errors don't reliably go to stderr with a non-zero exit as the spec requires
- tests only cover abc/nan/inf, so this silent failure path is untested
- huge integers are rejected with a misleading 'not a finite number' error
- harness facts report touchesManifests=false although pyproject.toml changed; the required human approval must not be skipped
- two commits with the same message, where the second deletes docs the first added; should be squashed

### The loops, and their caps
| Loop | What happened | Cap |
|---|---|---|
| 1 session (round 0) | `sonnet`: success, 4 turns, $0.10 | 40 turns, $3.0 |
| 1 session (round 1) | `sonnet`: success, 2 turns, $0.14 | 40 turns, $3.0 |
| 2 finish (Stop hook) | 0 block(s), 2 pass(es) of the quick checks | 3 continuations |
| 3 retry (`--resume`) | 1 retry round(s) | 1 |
| 4 queue | dispatched by `harness/bin/dispatch.sh` or run directly | 3 tasks per wake-up |

Spend: $0.64 in total across 2 worker and 2 reviewer session(s), as Claude Code estimates it.

### Provenance
- Base `main` at `52a0efb50be9`; result `31068a11438b`.
- 2.1.296 (Claude Code), pack `pack-d812d07de777`, placement: one machine: git worktree, native sandbox (bubblewrap), no microVM.
- Task `t-01M4RZHVFWTPBC0BG9QVPBAS3T`, 2026-10-12T21:16:04Z to 2026-10-12T21:22:27Z. Transcripts, checks log and packet.json stay with the run.

<sub>Opened by the workbench harness on a fork. Nothing here was sent upstream.</sub>
