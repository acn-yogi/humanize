#!/bin/bash
# intake.sh: the intake check for shaped specs, run by a person on the working tree before
# approving anything. The same check the shaper's Stop hook and shape.sh ran, repeated here
# outside any Claude session: valid draft specs, a plan that names them, no scope into the
# harness, and every check failing on today's code. Then the dispatcher's forecast for them.
#
#   harness/bin/intake.sh [--intent ID] [--issue N] [specs/NNNN-slug.md ...]
#
# Without spec files, the new and changed files under specs/ (per git status) are checked;
# with --issue N, the specs the ticket watch wrote for the fork's issue N (trigger = "ticket:N").
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=../lib/common.sh
. "${REPO}/harness/lib/common.sh"
args=() specs=() issue=""
while [ $# -gt 0 ]; do
  case "$1" in
    --intent) args+=(--intent "${2:?}"); shift 2 ;;
    --issue) issue="${2:?}"; shift 2 ;;
    -*) die "unknown option: $1" ;;
    *) specs+=("$1"); shift ;;
  esac
done
if [ -n "$issue" ]; then
  while IFS= read -r f; do specs+=("$f"); done < <(grep -lE "^trigger = \"ticket:${issue}\"" "${REPO}"/specs/[0-9]*.md 2>/dev/null | sed "s,^${REPO}/,,")
  [ "${#specs[@]}" -gt 0 ] || die "no spec carries trigger = \"ticket:${issue}\": the ticket watch has not shaped issue #${issue}"
fi
"${REPO}/harness/bin/preflight.sh" --quiet 2>/dev/null || die "preflight failed: run harness/bin/preflight.sh for the details"

# One environment for intake: a clone of HEAD under the workbench home (the editable install
# writes src/humanize/_version.py, so it cannot be built from the read-only working tree),
# rebuilt only when HEAD moves. The checks themselves run on the working tree.
idir="${WB_HOME}/intake"
export WB_TRUSTED="$REPO" WB_VENV="${idir}/venv" WB_SRC="${idir}/src"
WB_BASE_SHA="$(g -C "$REPO" rev-parse HEAD)"; export WB_BASE_SHA
mkdir -p "$idir" "${HOME}/.cache/uv"
[ -d "$WB_SRC" ] || g clone --quiet --no-local "$REPO" "$WB_SRC"
g -C "$WB_SRC" fetch --quiet "$REPO" HEAD && g -C "$WB_SRC" checkout --quiet --force --detach FETCH_HEAD
if [ ! -x "${WB_VENV}/bin/python" ] || [ "$(cat "${idir}/sha" 2>/dev/null)" != "$WB_BASE_SHA" ]; then
  log "intake: building the environment from HEAD ${WB_BASE_SHA:0:12} (${idir})"
  while IFS= read -r c; do
    confined net "$idir" "$(expand "$c")" < /dev/null || die "setup failed: $c"
  done < <(python3 -c 'import tomllib,sys;[print(c) for c in tomllib.load(open(sys.argv[1],"rb"))["setup"]["commands"]]' "${REPO}/harness/config.toml")
  echo "$WB_BASE_SHA" > "${idir}/sha"
fi

log "intake: harness/checks/shape_output.py on the working tree, under bubblewrap, no network (humanize from HEAD ${WB_BASE_SHA:0:12})"
rc=0
confined nonet "$REPO" "python harness/checks/shape_output.py ${args[*]+"${args[*]}"} $( [ "${#specs[@]}" -gt 0 ] && printf -- '--specs %s' "${specs[*]}" )" "$WB_VENV" "$WB_SRC" < /dev/null || rc=$?
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
