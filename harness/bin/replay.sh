#!/bin/bash
# replay.sh: the fallback when a live run cannot happen. Plays a recorded console log at a
# readable pace, then points at the recorded packet, evidence and transcript.
#
#   harness/bin/replay.sh [demo/recordings/<run>] [--fast]
set -uo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
dir="${1:-$(ls -d "${REPO}"/demo/recordings/t-* 2>/dev/null | tail -1)}"
delay=0.6; [ "${2:-}" = --fast ] && delay=0.05
[ -f "${dir}/console.log" ] || { echo "no console.log in ${dir}"; exit 2; }
echo "=== replay of a recorded run: ${dir#"${REPO}"/} ==="
while IFS= read -r line; do printf '%s\n' "$line"; sleep "$delay"; done < "${dir}/console.log"
echo
echo "Recorded alongside it:"
for f in spec.md plan.json prompt.md transcript.jsonl checks.log facts.json verdict.json decision.json packet.json evidence.md pr.txt; do
  [ -e "${dir}/${f}" ] && printf '  %s\n' "${dir#"${REPO}"/}/${f}"
done
