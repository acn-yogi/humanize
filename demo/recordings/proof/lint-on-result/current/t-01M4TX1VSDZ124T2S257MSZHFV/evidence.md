**Workbench evidence packet** for spec `0002-bugfix-precisedelta-sign`, from upstream issue python-humanize/humanize#379.

> **Route: rejected: halted with reasons, no PR.** Halted with the reasons above. No PR.
> - no changes

### What a person approved
- Spec `specs/0002-bugfix-precisedelta-sign.md`, class `bugfix`, intent approved by yogi.aradhye.
- Scope: `src/humanize/time.py`, `tests/test_time.py`.

### Acceptance checks (fresh clone of the result, bubblewrap, no network)
| Check | Result |
|---|---|
| `python -m pytest -q -p no:cacheprovider -x` | pass |
| `python {harness}/checks/precisedelta_sign.py` | FAIL, exit 1 |
| `python {harness}/checks/changed.py tests/test_time.py` | FAIL, exit 1 |

**Fail first.** The reproducing check must fail on the base commit and pass on the result.
| Check | Base | Result |
|---|---|---|
| `python {harness}/checks/precisedelta_sign.py` | exit 1 (fails, as it must) | exit 1 |

**Scope.** 0 file(s), 0 line(s) changed: . All inside the spec's scope.

### Adversarial review
No review ran.

### The loops, and their caps
| Loop | What happened | Cap |
|---|---|---|
| 1 session (round 0) | `sonnet`: success, 1 turns, $0.00 | 40 turns, $3.0 |
| 2 finish (Stop hook) | 0 block(s), 0 pass(es) of the quick checks | 3 continuations |
| 3 retry (`--resume`) | 0 retry round(s) | 0 |
| 4 queue | dispatched by `harness/bin/dispatch.sh` or run directly | 3 tasks per wake-up |

Spend: $0.00 in total across 1 worker and 0 reviewer session(s), as Claude Code estimates it.

### Provenance
- Base `main` at `527b16acd7a1`; result `527b16acd7a1`.
- 2.1.296 (Claude Code), pack `pack-d812d07de777`, placement: one machine: git worktree, native sandbox (bubblewrap), no microVM.
- Task `t-01M4TX1VSDZ124T2S257MSZHFV`, 2026-10-13T15:11:02Z to 2026-10-13T15:13:30Z. Transcripts, checks log and packet.json stay with the run.

<sub>Opened by the workbench harness on a fork. Nothing here was sent upstream.</sub>
