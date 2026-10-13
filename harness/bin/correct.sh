#!/bin/bash
# correct.sh: record a human correction made outside GitHub: a person took the task over,
# edited the result by hand, or rejected it. One "corrected" row in runs/ledger.jsonl, source
# "manual"; the same correction recorded twice is written once.
#
#   harness/bin/correct.sh <taskId> --action takeover|edit|reject --reason lint|test|scope|wrong-behaviour|style|question|other [--note TEXT]
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
[ $# -ge 1 ] || { sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
mkdir -p "${REPO}/runs"
exec python3 "${REPO}/harness/lib/corrections.py" manual "${REPO}/runs/ledger.jsonl" "$@"
