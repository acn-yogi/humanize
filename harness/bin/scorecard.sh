#!/bin/bash
# scorecard.sh: the human-touch signals and whether the harness is learning, from the ledger
# and the fork's PR list: manual takeovers, human PR comments (total and per PR), PRs with no
# human correction, cost per merged PR, recurrence (a reason code seen again after its case was
# proven fixed), pack size. One line each; --json for the same as one object.
#
#   harness/bin/scorecard.sh [--json] [--offline] [--ledger FILE]
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
exec python3 "${REPO}/harness/lib/scorecard.py" "$REPO" "$@"
