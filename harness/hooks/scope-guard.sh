#!/bin/bash
# PreToolUse hook on Edit, Write, MultiEdit and NotebookEdit: holds the spec's scope while
# Claude works. A file outside the spec's scope, or any harness file, is denied with a reason
# Claude can act on. Best effort, like every hook: a shell command can still write a file, so
# the authoritative scope check runs on the diff after the session.
#
#   scope-guard.sh <task dir>      (stdin: the PreToolUse hook's JSON input)
set -uo pipefail
tdir="$1"
# shellcheck source=../lib/common.sh
. "${tdir}/trusted/harness/lib/common.sh"

input="$(cat)"
work="${tdir}/work"
path="$(jq -r '.tool_input.file_path // .tool_input.notebook_path // empty' <<< "$input")"
tool="$(jq -r '.tool_name // "?"' <<< "$input")"
[ -n "$path" ] || exit 0
case "$path" in /*) ;; *) path="${work}/${path}" ;; esac
rel="$(realpath -m --relative-to="$work" "$path")"

deny() {
  event "${tdir}/loops.jsonl" --arg loop scope --arg decision deny --arg tool "$tool" --arg path "$rel" --arg reason "$1"
  jq -n --arg r "$1" '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $r}}'
  exit 0
}

case "$rel" in ../*|..) deny "workbench scope: ${path} is outside this task's worktree." ;; esac
verdict="$(python3 "${tdir}/trusted/harness/lib/plan.py" scope "${tdir}/plan.json" "$rel")"
if [ "$(jq '.harness | length' <<< "$verdict")" != 0 ]; then
  deny "workbench scope: ${rel} is part of the harness that judges this task; no task may change it."
fi
if [ "$(jq '.outside | length' <<< "$verdict")" != 0 ]; then
  deny "workbench scope: ${rel} is outside this spec's scope ($(jq -r '.scope | join(", ")' "${tdir}/plan.json")). Stay inside it, or stop and say the spec needs a change."
fi
exit 0
