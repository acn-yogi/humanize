**Workbench evidence packet** for spec `0002-bugfix-precisedelta-sign`, from upstream issue python-humanize/humanize#379.

> **Route: per PR: a person reviews this change.** A person reviews this PR.
> - adversarial review raised findings
> - Docstring edit leaves the previous fenced code block unclosed, so the new prose and the stray pycon fence render inside the 0-minutes example in the mkdocs docs
> - Zero detection scans rendered (possibly translated) text for digits 1-9 instead of using the computed delta, which is fragile

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

**Scope.** 2 file(s), 64 line(s) changed: `src/humanize/time.py`, `tests/test_time.py`. All inside the spec's scope.

### Adversarial review
A second Claude Code session (`opus`, edits denied) argued against the change: **reject**.
- Docstring edit leaves the previous fenced code block unclosed, so the new prose and the stray pycon fence render inside the 0-minutes example in the mkdocs docs
- Zero detection scans rendered (possibly translated) text for digits 1-9 instead of using the computed delta, which is fragile

### The loops, and their caps
| Loop | What happened | Cap |
|---|---|---|
| 1 session (round 0) | `sonnet`: success, 6 turns, $0.13 | 40 turns, $3.0 |
| 2 finish (Stop hook) | 0 block(s), 1 pass(es) of the quick checks | 3 continuations |
| 3 retry (`--resume`) | 0 retry round(s) | 0 |
| 4 queue | dispatched by `harness/bin/dispatch.sh` or run directly | 3 tasks per wake-up |

Spend: $0.36 in total across 1 worker and 1 reviewer session(s), as Claude Code estimates it.

### Provenance
- Base `harness/lint-in-quick-checks` at `168c9deea626`; result `40af8c2b5d2d`.
- 2.1.296 (Claude Code), pack `pack-7cd23886890b`, placement: one machine: git worktree, native sandbox (bubblewrap), no microVM.
- Task `t-01M4TZ5F1GKE6SRTHPBY5DF95P`, 2026-10-13T15:47:55Z to 2026-10-13T15:54:16Z. Transcripts, checks log and packet.json stay with the run.

<sub>Opened by the workbench harness on a fork. Nothing here was sent upstream.</sub>
