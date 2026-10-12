**Workbench evidence packet** for spec `0002-bugfix-precisedelta-sign`, from upstream issue python-humanize/humanize#379.

> **Route: per PR: a person reviews this change.** A person reviews this PR.
> - adversarial review raised findings
> - New test lines exceed 88 chars (tests/test_time.py:846-848, 862, 875); E501 is enabled via ruff 'E' and black would reformat, so pre-commit fails
> - precisedelta(timedelta(microseconds=-1)) returns '-0 seconds', a rendered zero with a sign, untested against the 'zero never gains a sign' constraint
> - Sign derived from clock comparison (date > now) plus a dead datetime guard instead of checking the input's sign directly
> - Two commits with the same message, the second partly undoing the first; should be squashed

### What a person approved
- Spec `specs/0002-bugfix-precisedelta-sign.md`, class `bugfix`, intent approved by yogi.aradhye.
- Scope: `src/humanize/time.py`, `tests/test_time.py`.

### Acceptance checks (fresh clone of the result, bubblewrap, no network)
| Check | Result |
|---|---|
| `python -m pytest -q -p no:cacheprovider -x` | pass |
| `python {harness}/checks/precisedelta_sign.py` | pass |
| `python {harness}/checks/changed.py tests/test_time.py` | pass |

**Fail first.** The reproducing check must fail on the base commit and pass on the result.
| Check | Base | Result |
|---|---|---|
| `python {harness}/checks/precisedelta_sign.py` | exit 1 (fails, as it must) | exit 0 |

**Scope.** 2 file(s), 57 line(s) changed: `src/humanize/time.py`, `tests/test_time.py`. All inside the spec's scope.

### Rounds: what was rejected, and what the retry fixed
| Round | Checks | Reviewer | Router |
|---|---|---|---|
| 0 | pass | reject | per_pr |
| 1 | pass | reject | per_pr |

Round 0 findings, handed back to the same session with `claude --resume` (loop 3):
- Docstring edit puts the new text inside the unclosed '0 minutes' example, which breaks the mkdocstrings-rendered docs
- Extends 'zero never gains a sign' to any negative value whose output renders as zero, using a fragile scan for digits 1-9 in the output string, which the spec did not ask for
- Unnecessary public-wrapper/private-helper split that repeats _date_and_delta's type checks

### Adversarial review
A second Claude Code session (`opus`, edits denied) argued against the change: **reject**.
- New test lines exceed 88 chars (tests/test_time.py:846-848, 862, 875); E501 is enabled via ruff 'E' and black would reformat, so pre-commit fails
- precisedelta(timedelta(microseconds=-1)) returns '-0 seconds', a rendered zero with a sign, untested against the 'zero never gains a sign' constraint
- Sign derived from clock comparison (date > now) plus a dead datetime guard instead of checking the input's sign directly
- Two commits with the same message, the second partly undoing the first; should be squashed

### The loops, and their caps
| Loop | What happened | Cap |
|---|---|---|
| 1 session (round 0) | `sonnet`: success, 10 turns, $0.17 | 40 turns, $3.0 |
| 1 session (round 1) | `sonnet`: success, 5 turns, $0.26 | 40 turns, $3.0 |
| 2 finish (Stop hook) | 0 block(s), 2 pass(es) of the quick checks | 3 continuations |
| 3 retry (`--resume`) | 1 retry round(s) | 1 |
| 4 queue | dispatched by `harness/bin/dispatch.sh` or run directly | 3 tasks per wake-up |

Spend: $0.90 in total across 2 worker and 2 reviewer session(s), as Claude Code estimates it.

### Provenance
- Base `main` at `52a0efb50be9`; result `999bd24cb4d4`.
- 2.1.296 (Claude Code), pack `pack-d812d07de777`, placement: one machine: git worktree, native sandbox (bubblewrap), no microVM.
- Task `t-01M4RZHVGFWY1FXM7RNXWAVNQA`, 2026-10-12T21:16:04Z to 2026-10-12T21:26:09Z. Transcripts, checks log and packet.json stay with the run.

<sub>Opened by the workbench harness on a fork. Nothing here was sent upstream.</sub>
