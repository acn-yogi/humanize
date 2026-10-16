#!/bin/bash
# lessons.sh: the lessons ledger (runs/lessons.jsonl, append-only). Three feeds draft lessons from
# records the harness already holds; a person approves; routing uses the paths that exist.
# Nothing here asks a model anything and nothing spends. Design: DEMO.md, "The lessons ledger".
#
#   harness/bin/lessons.sh draft [--no-audit] [--ledger FILE] [--proofs DIR...] [--roots DIR...]
#   harness/bin/lessons.sh list [--status S] [--source S] [--json]
#   harness/bin/lessons.sh approve <id> --by <name> [--portable]    a person only (exit 2 under an agent session)
#   harness/bin/lessons.sh reject <id> --by <name> [--reason TEXT]  a person only
#   harness/bin/lessons.sh route [<id>...] [--change-path P]        approved lessons: case draft, spec draft, pack command
#   harness/bin/lessons.sh start <id> --by <name>                   routed to in-progress
#   harness/bin/lessons.sh close <id> --by <name> --proof <verdict path> | --pr <ref> [--prs FILE]
#   harness/bin/lessons.sh seed --out FILE | --in FILE [--deny WORD...]
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
[ $# -ge 1 ] || { sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
exec python3 "${REPO}/harness/lib/lessons.py" --cwd "$REPO" "$@"
