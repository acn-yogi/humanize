#!/bin/bash
# intake.sh: the intake check for shaped specs, run by a person on the working tree before
# approving anything. The same check the shaper's Stop hook and shape.sh ran, repeated here
# outside any Claude session: valid draft specs, a plan that names them, no scope into the
# harness, and every check failing on today's code. Then the dispatcher's forecast for them.
#
#   harness/bin/intake.sh [--intent ID] [specs/NNNN-slug.md ...]
#
# Without spec files, the new and changed files under specs/ (per git status) are checked.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=../lib/common.sh
. "${REPO}/harness/lib/common.sh"
args=() specs=()
while [ $# -gt 0 ]; do
  case "$1" in
    --intent) args+=(--intent "${2:?}"); shift 2 ;;
    -*) die "unknown option: $1" ;;
    *) specs+=("$1"); shift ;;
  esac
done
"${REPO}/harness/bin/preflight.sh" --quiet 2>/dev/null || die "preflight failed: run harness/bin/preflight.sh for the details"

# One environment for intake, built from the working tree with network, reused across runs.
export WB_TRUSTED="$REPO" WB_VENV="${WB_HOME}/intake-venv" WB_SRC="$REPO"
WB_BASE_SHA="$(g -C "$REPO" rev-parse HEAD)"; export WB_BASE_SHA
mkdir -p "$WB_HOME" "${HOME}/.cache/uv"
if [ ! -x "${WB_VENV}/bin/python" ]; then
  log "intake: building the environment once (${WB_VENV})"
  while IFS= read -r c; do
    confined net "$WB_HOME" "$(expand "$c")" < /dev/null || die "setup failed: $c"
  done < <(python3 -c 'import tomllib,sys;[print(c) for c in tomllib.load(open(sys.argv[1],"rb"))["setup"]["commands"]]' "${REPO}/harness/config.toml")
fi

log "intake: harness/checks/shape_output.py on the working tree, under bubblewrap, no network"
rc=0
confined nonet "$REPO" "python harness/checks/shape_output.py ${args[*]+"${args[*]}"} $( [ "${#specs[@]}" -gt 0 ] && printf -- '--specs %s' "${specs[*]}" )" "$WB_VENV" < /dev/null || rc=$?
log "intake: $( [ "$rc" = 0 ] && echo "PASS, every line held" || echo "FAIL (exit ${rc})" )"

log "forecast: what the queue would do with them (drafts wait; nothing runs until a person approves)"
ids="$(python3 - "${specs[@]}" <<'PY'
import re, subprocess, sys
files = sys.argv[1:] or [l[3:].strip() for l in subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--", "specs"],
                         capture_output=True, text=True).stdout.splitlines()]
print("\n".join(re.sub(r"^.*/|\.md$", "", f) for f in files if f.endswith(".md")))
PY
)"
python3 "${REPO}/harness/lib/plan.py" queue "${REPO}/harness" "${REPO}/specs" | node --no-warnings "${REPO}/harness/lib/preroute.ts" "${REPO}/runs/ledger.jsonl" \
  | jq -r --argjson ids "$(jq -R . <<< "$ids" | jq -sc .)" '.[] | select(.id as $i | $ids | index($i)) | "  \(.action | ascii_upcase)\t\(.id)\t\(.class)\t\(.forecast)"' \
  | column -t -s $'\t'
exit "$rc"
