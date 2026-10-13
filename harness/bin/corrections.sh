#!/bin/bash
# corrections.sh: human corrections from GitHub into the ledger (the record step of the proving
# loop). Reads the fork's PR review comments, reviews and issue comments on the PRs the harness
# opened, keeps the human ones (not a bot, not the harness's own packet, findings or verdict),
# classifies each with a fixed word list (lint, test, scope, wrong-behaviour, style, question,
# other) and appends one "corrected" row per new comment to runs/ledger.jsonl, deduplicated on
# the comment url. Run it as often as you like.
#
#   harness/bin/corrections.sh [--dry-run] [--since ISO] [--bot LOGIN]
#
# Fork only (harness/config.toml [github] repo); the upstream repository is never read.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
mkdir -p "${REPO}/runs"
exec python3 "${REPO}/harness/lib/corrections.py" github "${REPO}/harness" "${REPO}/runs/ledger.jsonl" "$@"
