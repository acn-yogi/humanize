**Workbench evidence packet** for spec `0001-docs-local-testing`, from upstream issue python-humanize/humanize#430.

> **Route: per batch: joins an approved batch plan; one approval merges the batch.** Joins approved batch docs-2026-10: one person approves the batch with harness/bin/approve-batch.sh.
> - instance of approved batch plan docs-2026-10

### What a person approved
- Spec `specs/0001-docs-local-testing.md`, class `docs`, intent approved by yogi.aradhye.
- Scope: `docs/testing.md`, `mkdocs.yml`.

### Acceptance checks (fresh clone of the result, bubblewrap, no network)
| Check | Result |
|---|---|
| `python -m pytest -q -p no:cacheprovider -x` | pass |
| `python {harness}/checks/docs_testing.py` | pass |

**Scope.** 2 file(s), 48 line(s) changed: `docs/testing.md`, `mkdocs.yml`. All inside the spec's scope.

### Rounds: what was rejected, and what the retry fixed
| Round | Checks | Reviewer | Router |
|---|---|---|---|
| 0 | pass | reject | per_pr |
| 1 | pass | approve | batch_plan |

Round 0 findings, handed back to the same session with `claude --resume` (loop 3):
- The -k example selects all 76 tests in tests/test_filesize.py (same as running the file), so it does not show focusing a test run as the spec intends
- The translation-binaries script has to run from the repo root and needs msgfmt on PATH; the page doesn't say so
- The skip explanation leaves out the other skip reason in test_i18n.py

### Adversarial review
A second Claude Code session (`opus`, edits denied) argued against the change: **approve**.
- Only docs/testing.md and mkdocs.yml changed, nav entry placed as specified
- All three pytest commands on the page run and pass (744 passed/112 skipped; 76 passed; 46 passed)
- All six required points covered and the skip/CI claims match tests/test_i18n.py and test.yml
- Nits only: two identically-named commits to squash, script invocation relies on shell fallback

### The loops, and their caps
| Loop | What happened | Cap |
|---|---|---|
| 1 session (round 0) | `sonnet`: success, 4 turns, $0.07 | 30 turns, $1.5 |
| 1 session (round 1) | `sonnet`: success, 4 turns, $0.10 | 30 turns, $1.5 |
| 2 finish (Stop hook) | 0 block(s), 2 pass(es) of the quick checks | 3 continuations |
| 3 retry (`--resume`) | 1 retry round(s) | 1 |
| 4 queue | dispatched by `harness/bin/dispatch.sh` or run directly | 3 tasks per wake-up |

Spend: $0.59 in total across 2 worker and 2 reviewer session(s), as Claude Code estimates it.

### Provenance
- Base `main` at `92871c5f72ea`; result `06a9ca2f6716`.
- 2.1.296 (Claude Code), pack `pack-d812d07de777`, placement: one machine: git worktree, native sandbox (bubblewrap), no microVM.
- Task `t-01M4RYVYEG6H31MRD8C2N01K04`, 2026-10-12T21:04:06Z to 2026-10-12T21:10:40Z. Transcripts, checks log and packet.json stay with the run.

<sub>Opened by the workbench harness on a fork. Nothing here was sent upstream.</sub>
