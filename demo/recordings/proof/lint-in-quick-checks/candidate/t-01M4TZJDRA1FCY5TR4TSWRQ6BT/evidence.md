**Workbench evidence packet** for spec `0002-bugfix-precisedelta-sign`, from upstream issue python-humanize/humanize#379.

> **Route: per PR: a person reviews this change.** A person reviews this PR.
> - adversarial review raised findings
> - Regression: precisedelta(datetime) now raises TypeError (worked on base, returned '1 hour')
> - Sub-unit negative values render as signed zero, e.g. '-0 seconds' / '-0 minutes'
> - Tests lack datetime and round-to-zero negative cases, so the regression went unnoticed
> - Sign check is fragile and redundant with _date_and_delta; uses a redundant local import

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

**Scope.** 2 file(s), 50 line(s) changed: `src/humanize/time.py`, `tests/test_time.py`. All inside the spec's scope.

### Adversarial review
A second Claude Code session (`opus`, edits denied) argued against the change: **reject**.
- Regression: precisedelta(datetime) now raises TypeError (worked on base, returned '1 hour')
- Sub-unit negative values render as signed zero, e.g. '-0 seconds' / '-0 minutes'
- Tests lack datetime and round-to-zero negative cases, so the regression went unnoticed
- Sign check is fragile and redundant with _date_and_delta; uses a redundant local import

### The loops, and their caps
| Loop | What happened | Cap |
|---|---|---|
| 1 session (round 0) | `sonnet`: success, 7 turns, $0.12 | 40 turns, $3.0 |
| 2 finish (Stop hook) | 0 block(s), 1 pass(es) of the quick checks | 3 continuations |
| 3 retry (`--resume`) | 0 retry round(s) | 0 |
| 4 queue | dispatched by `harness/bin/dispatch.sh` or run directly | 3 tasks per wake-up |

Spend: $0.33 in total across 1 worker and 1 reviewer session(s), as Claude Code estimates it.

### Provenance
- Base `harness/lint-in-quick-checks` at `168c9deea626`; result `f37849165a6f`.
- 2.1.296 (Claude Code), pack `pack-7cd23886890b`, placement: one machine: git worktree, native sandbox (bubblewrap), no microVM.
- Task `t-01M4TZJDRA1FCY5TR4TSWRQ6BT`, 2026-10-13T15:54:59Z to 2026-10-13T16:01:09Z. Transcripts, checks log and packet.json stay with the run.

<sub>Opened by the workbench harness on a fork. Nothing here was sent upstream.</sub>
