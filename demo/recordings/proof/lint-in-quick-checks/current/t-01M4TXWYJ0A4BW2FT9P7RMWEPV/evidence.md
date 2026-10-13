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

**Scope.** 2 file(s), 47 line(s) changed: `src/humanize/time.py`, `tests/test_time.py`. All inside the spec's scope.

### Adversarial review
A second Claude Code session (`opus`, edits denied) argued against the change: **approve**.
- Sign preserved for all minimum_unit/suppress/format paths via one recursive call; positives and zero unchanged
- Fail-first check and full suite pass; scope limited to time.py and test_time.py
- Minor: zero check scans the output for digits 1-9, and a negative that rounds to zero drops its sign; neither contradicts the spec
- Minor: test repeats an unrelated -3661 assertion in every parametrized case

### The loops, and their caps
| Loop | What happened | Cap |
|---|---|---|
| 1 session (round 0) | `sonnet`: success, 12 turns, $0.14 | 40 turns, $3.0 |
| 2 finish (Stop hook) | 0 block(s), 1 pass(es) of the quick checks | 3 continuations |
| 3 retry (`--resume`) | 0 retry round(s) | 0 |
| 4 queue | dispatched by `harness/bin/dispatch.sh` or run directly | 3 tasks per wake-up |

Spend: $0.32 in total across 1 worker and 1 reviewer session(s), as Claude Code estimates it.

### Provenance
- Base `main` at `527b16acd7a1`; result `5df966eea2ef`.
- 2.1.296 (Claude Code), pack `pack-d812d07de777`, placement: one machine: git worktree, native sandbox (bubblewrap), no microVM.
- Task `t-01M4TXWYJ0A4BW2FT9P7RMWEPV`, 2026-10-13T15:25:47Z to 2026-10-13T15:31:26Z. Transcripts, checks log and packet.json stay with the run.

<sub>Opened by the workbench harness on a fork. Nothing here was sent upstream.</sub>
