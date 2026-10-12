#!/bin/bash
# replay.sh: the fallback when a live run cannot happen. Plays a recorded console log at a
# readable pace, then points at the recorded packet, evidence and transcript.
#
#   harness/bin/replay.sh [demo/recordings/<run>] [--fast]
set -uo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
dir="" delay=0.6
for a in "$@"; do case "$a" in --fast) delay=0.05 ;; *) dir="$a" ;; esac; done
# Default: the first recorded run, spec 0001 (PR #1).
[ -n "$dir" ] || dir="$(ls -d "${REPO}"/demo/recordings/t-* 2>/dev/null | head -1)"
[ -f "${dir}/console.log" ] || { echo "no console.log in ${dir}"; exit 2; }
echo "=== replay of a recorded run: ${dir#"${REPO}"/} ==="
while IFS= read -r line; do printf '%s\n' "$line"; sleep "$delay"; done < "${dir}/console.log"
echo
echo "Recorded alongside it:"
for f in spec.md plan.json prompt.md transcript.jsonl checks.log facts.json verdict.json decision.json packet.json evidence.md pr.txt; do
  [ -e "${dir}/${f}" ] && printf '  %s\n' "${dir#"${REPO}"/}/${f}"
done
