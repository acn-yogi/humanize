#!/bin/bash
# audit.sh: the mine step of the proving loop. A reference-free L1 audit over every recorded
# session (runs/ and demo/recordings/ by default): the worker and reviewer transcripts, the
# loops, the rounds, the check output, the packet and the ledger row of each task. Ranks the
# failure classes by recurrence (distinct tasks) and lists every hit with its file and line.
#
#   harness/bin/audit.sh [--roots DIR...] [--json] [--promote CODE]
#
#   --promote CODE   write harness/cases/drafts/<code>.json: the real prompt, the base sha, the
#                    task ids, and an empty checks list for a person to fill
#
# Exit 1 when a FAIL-severity class has a hit, 0 on WARN or clean, 2 when a transcript has a
# shape the normalizer does not know (it never reports a clean audit it did not run).
# No model is asked anything; nothing here spends.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
exec python3 "${REPO}/harness/lib/audit.py" --cwd "$REPO" "$@"
