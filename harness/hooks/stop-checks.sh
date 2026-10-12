#!/bin/bash
# Loop 2, finish. Claude Code runs this Stop hook when Claude declares it is done. It runs the
# spec's quick checks on the worktree under bubblewrap with no network. If they fail, it
# blocks the stop and hands the failures back as Claude's next instruction, up to the
# continuation cap; at the cap it lets the session end and the retry loop takes over.
#
#   stop-checks.sh <task dir>      (stdin: the Stop hook's JSON input)
#
# The hook lives in the task's trusted copy of the harness, outside the worktree, so the
# session cannot edit the check that decides whether it may stop.
set -uo pipefail
tdir="$1"
# shellcheck source=../lib/common.sh
. "${tdir}/trusted/harness/lib/common.sh"

input="$(cat)"
plan="${tdir}/plan.json"
loops="${tdir}/loops.jsonl"
n="$(cat "${tdir}/continuations" 2>/dev/null || echo 0)"
cap="$(jq -r '.caps.continuations' "$plan")"
active="$(jq -r '.stop_hook_active // false' <<< "$input")"

export WB_TRUSTED="${tdir}/trusted" WB_VENV="${tdir}/venv" WB_SRC="${tdir}/work"
WB_BASE_SHA="$(cat "${tdir}/base_sha")"; export WB_BASE_SHA
WB_CHECK_TIMEOUT=300

failures="" passed=0 failed=0
while IFS= read -r c; do
  [ -n "$c" ] || continue
  cmd="$(expand "$c")"
  res="$(confined nonet "${tdir}/work" "$cmd" "$WB_TRUSTED" "$WB_VENV" 2>&1)"; rc=$?
  if [ "$rc" = 0 ]; then
    passed=$((passed + 1))
  else
    failed=$((failed + 1))
    failures+="\$ ${c}   (exit ${rc})"$'\n'"$(tail -n 25 <<< "$res")"$'\n\n'
  fi
done < <(jq -r '.checks.quick[]' "$plan")

if [ "$failed" = 0 ]; then
  event "$loops" --arg loop finish --arg result pass --argjson continuation "$n" --argjson checks "$passed" --arg stopHookActive "$active"
  exit 0
fi
if [ "$n" -ge "$cap" ]; then
  event "$loops" --arg loop finish --arg result cap --argjson continuation "$n" --argjson failed "$failed" \
    --arg note "continuation cap reached: the session ends and the trusted checks decide"
  exit 0
fi
echo $((n + 1)) > "${tdir}/continuations"
event "$loops" --arg loop finish --arg result block --argjson continuation $((n + 1)) --argjson failed "$failed"
jq -n --arg r "Not done yet: ${failed} of the spec's quick checks fail on your worktree (continuation $((n + 1)) of ${cap}). Fix the cause, not the check, then finish again.

${failures}" '{decision: "block", reason: $r}'
exit 0
