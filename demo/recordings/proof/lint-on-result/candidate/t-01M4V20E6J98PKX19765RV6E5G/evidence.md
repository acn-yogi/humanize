**Workbench evidence packet** for spec `0002-bugfix-precisedelta-sign`, from upstream issue python-humanize/humanize#379.

> **Route: per PR: a person reviews this change.** A person reviews this PR.
> - class bugfix is approved per PR (harness/classes.toml)

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

**Scope.** 2 file(s), 66 line(s) changed: `src/humanize/time.py`, `tests/test_time.py`. All inside the spec's scope.

### Adversarial review
A second Claude Code session (`opus`, edits denied) argued against the change: **approve**.
- Meets all acceptance criteria; fail-first check passes and full suite green
- No behaviour change for positive, zero, or non-numeric inputs versus base
- Scope limited to time.py and tests/test_time.py
- Only nits: digit-scan zero detection is hacky, odd '%+' formats yield '-+'

### The loops, and their caps
| Loop | What happened | Cap |
|---|---|---|
| 1 session (round 0) | `sonnet`: success, 7 turns, $0.14 | 40 turns, $3.0 |
| 2 finish (Stop hook) | 0 block(s), 1 pass(es) of the quick checks | 3 continuations |
| 3 retry (`--resume`) | 0 retry round(s) | 0 |
| 4 queue | dispatched by `harness/bin/dispatch.sh` or run directly | 3 tasks per wake-up |

Spend: $0.40 in total across 1 worker and 1 reviewer session(s), as Claude Code estimates it.

### Provenance
- Base `harness/lint-in-quick-checks` at `168c9deea626`; result `df8ca0c8832e`.
- 2.1.296 (Claude Code), pack `pack-7cd23886890b`, placement: one machine: git worktree, native sandbox (bubblewrap), no microVM.
- Task `t-01M4V20E6J98PKX19765RV6E5G`, 2026-10-13T16:37:42Z to 2026-10-13T16:45:58Z. Transcripts, checks log and packet.json stay with the run.

<sub>Opened by the workbench harness on a fork. Nothing here was sent upstream.</sub>
