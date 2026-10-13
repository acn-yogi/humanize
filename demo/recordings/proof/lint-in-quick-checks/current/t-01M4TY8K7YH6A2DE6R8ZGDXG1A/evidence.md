**Workbench evidence packet** for spec `0002-bugfix-precisedelta-sign`, from upstream issue python-humanize/humanize#379.

> **Route: per PR: a person reviews this change.** A person reviews this PR.
> - adversarial review raised findings
> - Regression: precisedelta(datetime) now raises TypeError (value < 0 on a datetime); on base it returned '1 hour'
> - Zero is detected by scanning the translated output for digits instead of using the computed values
> - test_precisedelta_zero_has_no_sign has an assert that ignores its parameter, so zero coverage is weaker than it looks
> - No test covers the datetime input path the change broke

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
- Regression: precisedelta(datetime) now raises TypeError (value < 0 on a datetime); on base it returned '1 hour'
- Zero is detected by scanning the translated output for digits instead of using the computed values
- test_precisedelta_zero_has_no_sign has an assert that ignores its parameter, so zero coverage is weaker than it looks
- No test covers the datetime input path the change broke

### The loops, and their caps
| Loop | What happened | Cap |
|---|---|---|
| 1 session (round 0) | `sonnet`: success, 8 turns, $0.15 | 40 turns, $3.0 |
| 2 finish (Stop hook) | 0 block(s), 1 pass(es) of the quick checks | 3 continuations |
| 3 retry (`--resume`) | 0 retry round(s) | 0 |
| 4 queue | dispatched by `harness/bin/dispatch.sh` or run directly | 3 tasks per wake-up |

Spend: $0.36 in total across 1 worker and 1 reviewer session(s), as Claude Code estimates it.

### Provenance
- Base `main` at `527b16acd7a1`; result `b7fce5a7cb7b`.
- 2.1.296 (Claude Code), pack `pack-d812d07de777`, placement: one machine: git worktree, native sandbox (bubblewrap), no microVM.
- Task `t-01M4TY8K7YH6A2DE6R8ZGDXG1A`, 2026-10-13T15:32:08Z to 2026-10-13T15:38:35Z. Transcripts, checks log and packet.json stay with the run.

<sub>Opened by the workbench harness on a fork. Nothing here was sent upstream.</sub>
