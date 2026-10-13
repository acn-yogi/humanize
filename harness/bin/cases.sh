#!/bin/bash
# cases.sh: the harness's own eval cases, each a finding that once got past a piece of the
# harness, kept so the fix stays fixed. Two shapes:
#
#   flags       (the default) names changed paths and the risk flags the facts must carry for
#               them; harness/lib/flags.ts computes the flags the way the router does. Re-run
#               every time: it costs nothing.
#   trajectory  (kind: "trajectory") a real spec run k times under the current and a candidate
#               pack and scored from the packets (harness/bin/case-run.sh). Re-running it costs
#               k sessions, so the suite lists it with its last proof (the case's "proof" field,
#               written by the proving loop): PASS when the proof's verdict is SHIP, FAIL when a
#               shipped case (fixedIn set) has a later proof that did not ship, NOTE while no
#               proof exists yet or the proof did not ship (the fix is not on main: nothing to guard).
#
#   harness/bin/cases.sh            -> one PASS, FAIL or NOTE line per case; exit 1 on any FAIL
set -uo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
bad=0
for c in "${REPO}"/harness/cases/*.json; do
  id="$(jq -r .id "$c")"
  kind="$(jq -r '.kind // "flags"' "$c")"
  if [ "$kind" = trajectory ]; then
    if [ "$(jq -r '.proof == null' "$c")" = true ]; then
      printf 'NOTE  %-24s trajectory case, no proof yet (status %s): %s\n' "$id" "$(jq -r '.status // "draft"' "$c")" "$(jq -r '.runner // "harness/bin/case-run.sh"' "$c")"
      continue
    fi
    line="$(jq -r '.proof | "before pass^\(.k) \(.before.passK) (\(.before.passes) of \(.before.trials)), after pass^\(.k) \(.after.passK) (\(.after.passes) of \(.after.trials)), regressions \(.regressions // 0), judge \(.judge | map(.verdict) | join(",")), \(.verdict) at \(.provenAt // .at)"' "$c")"
    if [ "$(jq -r .proof.verdict "$c")" = SHIP ]; then
      printf 'PASS  %-24s %s\n' "$id" "$line"
    elif [ "$(jq -r '.fixedIn // empty' "$c")" != "" ]; then
      printf 'FAIL  %-24s %s\n' "$id" "$line"; bad=1
    else
      printf 'NOTE  %-24s not shipped: %s; %s\n' "$id" "$(jq -r '.proof.reasons | join("; ")' "$c")" "$line"
    fi
    continue
  fi
  got="$(jq -c .changedPaths "$c" | node --no-warnings "${REPO}/harness/lib/flags.ts")"
  diff="$(jq -nc --argjson got "$got" --argjson want "$(jq -c .expect "$c")" \
    '[$want | to_entries[] | select($got[.key] != .value) | "\(.key): got \($got[.key]), expected \(.value)"] | join("; ")')"
  if [ -z "$diff" ] || [ "$diff" = '""' ]; then
    printf 'PASS  %-24s %s\n' "$id" "$(jq -r '.expect | to_entries | map(select(.value)) | map(.key) | join(", ") | if . == "" then "no flag" else . end' "$c") on $(jq -r '.changedPaths | join(", ")' "$c")"
  else
    printf 'FAIL  %-24s %s\n' "$id" "$(jq -r . <<< "$diff")"; bad=1
  fi
done
exit "$bad"
