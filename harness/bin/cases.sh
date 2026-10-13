#!/bin/bash
# cases.sh: the harness's own eval cases, each a finding that once got past a piece of the
# harness, kept so the fix stays fixed. A case names changed paths and the risk flags the facts
# must carry for them; harness/lib/flags.ts computes the flags the way the router does.
#
#   harness/bin/cases.sh            -> one PASS or FAIL line per case; exit 1 on any FAIL
set -uo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
bad=0
for c in "${REPO}"/harness/cases/*.json; do
  id="$(jq -r .id "$c")"
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
