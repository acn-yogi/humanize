#!/bin/bash
# run-demo.sh: the scripted, re-runnable demo. Eight acts on the fork, each emitting milestones
# to demo/live/events.jsonl and demo/live/state.json as they happen (schema: demo/live/schema.json).
#
#   demo/run-demo.sh [--repo URL] [--acts 0,1,2] [--dry-run] [--reset] [--budget 25] [--serve]
#                    [--ask "one line" | --issue N] [--approve-batch] [--yes] [--concurrency 4]
#
#   --dry-run        spend nothing: the milestones come from demo/recordings/
#   --reset          close the demo's PRs on the fork, remove demo branches, worktrees and
#                    generated specs, clear demo/live (schema and validator stay)
#   --budget USD     the driver's hard stop for the whole run (default 25); Claude Code's own
#                    caps sit under it
#   --serve          a local http server on 127.0.0.1:8765 serving demo/ (the player and the feed)
#   --ask / --issue  Act 1's input when nobody is at the keyboard
#   --approve-batch  the one human yes on the batch plan (Act 2) and the held-back spec (Act 4)
#
# Acts: 0 bring in the repo, 0b build the workbench, 1 the audience's feature, 2 the batch,
# 3 the trap, 4 autonomy earned, 5 the harness fixes itself (no spend), 6 ready to release (no
# spend), 7 triggers: what starts the work (no spend). Every act is
# idempotent and resumable: state.json remembers what ran. Linux or WSL2, the same environment
# as harness/bin/workbench.sh. Nothing here ever pushes to the upstream repository.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="${HOME}/.local/bin:${PATH}"

dry=0
for a in "$@"; do case "$a" in --dry-run|--reset|-h|--help) dry=1 ;; esac; done
if [ "$dry" = 0 ]; then
  "${REPO}/harness/bin/preflight.sh" --quiet || { echo "run-demo: preflight failed; run harness/bin/preflight.sh for the details" >&2; exit 2; }
  # shellcheck source=../harness/lib/auth.sh
  . "${REPO}/harness/lib/auth.sh"
  load_auth
  echo "run-demo: credentials: ${WB_AUTH}" >&2
else
  command -v python3 >/dev/null || { echo "run-demo: python3 is needed" >&2; exit 2; }
fi
exec python3 "${REPO}/demo/lib/run_demo.py" "$@"
