# demo/live: the demo's feed

`demo/run-demo.sh` writes here while it runs. The player reads it.

| File | What |
|---|---|
| `events.jsonl` | append-only, one event per line: `{"ts","act","kind","id","title","detail","level","data"}` |
| `state.json` | rewritten on every event: repo facts, phase, budget, the acts (Act 0b under `acts[0].parts.b`), the worktrees, the guardrails Act 0b defined and probed (`name`, `enforcer`, `file`, `rule`, `probe`: pending, refused or allowed, `evidence`), the counters, the last 50 milestones |
| `schema.json` | the shape of both, and the list of milestone ids |
| `validate.py` | `python3 demo/live/validate.py` checks the two files against the schema |
| `console/` | the console log of every workbench, shaper and proving run the driver started |
| `assess.json`, `batch-plan.json`, `verdict.json`, `triggers.json` | Act 0, Act 2, Act 6 and Act 7 outputs |
| `generated.txt` | the files the driver generated (specs, intents, the trap), so `--reset` can remove them |

Everything but the schema, the validator and this page is ignored by git and cleared by
`--reset`. A finished live run is copied to `demo/live-runs/<date>/`, which is committed.

Milestone titles are the projector callouts: "Fail-first holds: the new check fails on today's
code", "Stopped for a person: pyproject.toml is a manifest", "Class docs graduated: 3 of 3 proofs
passed", "Injection denied by the network allowlist". `level` is `key` for those, `info` for
supporting milestones, `warn` for an honest result that did not go the happy way. `kind` is
`milestone` (the callouts), `log` (lines worth keeping), `counter` (a counter changed) or
`state` (an act or a state field changed). In a dry run, `data.dry` is true and recorded costs
are logged without being counted as spend; anything with no recording carries `data.scripted`.
