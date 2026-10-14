#!/bin/bash
# prove.sh: the proving loop's measurement. Runs one spec k times, each in a fresh workbench
# with nothing carried over, and scores pass^k: the share of attempts that all pass, so 1 only
# when every attempt passed. Graduation reads this, never a single lucky pass.
#
#   harness/bin/prove.sh specs/<id>.md [--k 3] [--record]
#
# A trial passes when the trusted checks pass on a non-empty change inside the spec's scope,
# fail-first held (if the spec has it) and the reviewer approved. --record writes
# harness/proofs/<class>.json for a person to commit (the proofs are evaluator records: the
# loop proposes them, people merge them). Trials never publish.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=../lib/common.sh
. "${REPO}/harness/lib/common.sh"
spec="" k=3 record=0
while [ $# -gt 0 ]; do
  case "$1" in
    --k) k="${2:?}"; shift 2 ;;
    --record) record=1; shift ;;
    *) spec="$1"; shift ;;
  esac
done
[ -n "$spec" ] && [[ "$k" =~ ^([1-9]|10)$ ]] || die "usage: prove.sh specs/<id>.md [--k 1..10] [--record]"
out="${REPO}/runs/proofs/$(basename "$spec" .md)-$(date -u +%Y%m%dT%H%M%S)"
mkdir -p "$out"
trials='[]'
for i in $(seq 1 "$k"); do
  log "trial ${i} of ${k}"
  id="$("${REPO}/harness/bin/workbench.sh" "$spec" --no-publish --trial "$i" --out "$out" | sed -n 's/^task-id: //p' | tail -1)"
  [ -n "$id" ] || { trials="$(jq -c --argjson i "$i" '. + [{trial: $i, outcome: "error", reasons: ["the workbench did not start"]}]' <<< "$trials")"; continue; }
  p="${out}/${id}/packet.json"
  t="$(jq -c --argjson i "$i" '{trial: $i, taskId, packId, fingerprint: (.fingerprint // null),
    outcome: (if .allChecksPass and (.changedPaths | length) > 0 and ((.scope.outside + .scope.harness) | length) == 0
                 and (.grading == null or .grading.ok) and (.review.verdict // "none") == "approve" then "pass" else "fail" end),
    path: .decision.path, costUsd}' "$p")"
  trials="$(jq -c --argjson t "$t" '. + [$t]' <<< "$trials")"
  log "trial ${i}: $(jq -r .outcome <<< "$t")"
done
cls="$(python3 "${REPO}/harness/lib/plan.py" plan "${REPO}/harness" "$spec" | jq -r .class)"
verdict="$(jq -n --argjson t "$trials" --arg c "$cls" --arg s "$(basename "$spec" .md)" --argjson k "$k" '
  ($t | map(select(.outcome == "pass")) | length) as $passes |
  {class: $c, cases: [$s], k: $k, trials: ($t | length), passes: $passes,
   passK: (if ($t | length) > 0 and $passes == ($t | length) then 1 else 0 end),
   imageId: ($t | map(.packId) | unique | if length == 1 then .[0] else "mixed" end), driver: "guest",
   # Every trial of one proof must share an environment (Claude Code version, served model);
   # a proof whose trials ran on two environments is not one measurement.
   fingerprints: ($t | map(.fingerprint // empty) | unique),
   comparison: ($t | map(.fingerprint // empty | del(.packId)) | unique
                | if length == 0 then "fingerprint-not-recorded" elif length == 1 then "valid" else "invalid-fingerprint" end),
   costUsd: ($t | map(.costUsd // 0) | add), at: (now | todate), runs: $t}')"
echo "$verdict" | tee "${out}/verdict.json" | jq '{class, k, passes, passK, imageId, comparison, costUsd}'
[ "$(jq -r .comparison <<< "$verdict")" != invalid-fingerprint ] || log "the trials ran on different environments (fingerprints differ beyond the pack id): the proof is not one measurement"
if [ "$record" = 1 ]; then
  echo "$verdict" | jq 'del(.runs)' > "${REPO}/harness/proofs/${cls}.json"
  log "wrote harness/proofs/${cls}.json: review it and commit it to graduate the class (people merge proofs, the loop does not)"
fi
