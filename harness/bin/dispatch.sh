#!/bin/bash
# dispatch.sh: loop 4, the queue. Takes the next approved specs, runs each in its own
# workbench, several at once, and stops at the queue cap. Run it on a timer for unattended
# work on code we own (this fork): --every, or the systemd timer in harness/systemd/.
#
#   harness/bin/dispatch.sh --dry-run           show the queue and what will happen, spend nothing
#   harness/bin/dispatch.sh [--only ID]...      one wake-up: run up to tasks_per_queue_run specs
#   harness/bin/dispatch.sh --every MINUTES     wake up on a timer until stopped
#
# Every wake-up ends with a line in runs/ledger.jsonl for each task it started, whatever the
# outcome. A spec that already ran (a PR, a batch, a merge) is not run again.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=../lib/common.sh
. "${REPO}/harness/lib/common.sh"
dry=0 every="" only=() extra=()
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry=1; shift ;;
    --every) every="${2:?}"; shift 2 ;;
    --only) only+=("${2:?}"); shift 2 ;;
    --no-publish|--no-review) extra+=("$1"); shift ;;
    *) die "unknown argument: $1" ;;
  esac
done
ledger="${REPO}/runs/ledger.jsonl"
mkdir -p "${REPO}/runs"

queue() {
  # The queue is read from the base branch, like everything the harness acts on.
  local base tmp
  base="$(python3 -c 'import tomllib,sys;print(tomllib.load(open(sys.argv[1],"rb"))["github"]["base"])' "${REPO}/harness/config.toml")"
  tmp="$(mktemp -d)"
  g -C "$REPO" archive "$base" harness specs | tar -x -C "$tmp"
  python3 "${tmp}/harness/lib/plan.py" queue "${tmp}/harness" "${tmp}/specs" | node --no-warnings "${tmp}/harness/lib/preroute.ts" "$ledger"
  rm -rf "$tmp"
}

wake() {
  local rows cap par ids=() id
  rows="$(queue)"
  cap="$(python3 -c 'import tomllib,sys;print(tomllib.load(open(sys.argv[1],"rb"))["caps"]["tasks_per_queue_run"])' "${REPO}/harness/config.toml")"
  par="$(python3 -c 'import tomllib,sys;print(tomllib.load(open(sys.argv[1],"rb"))["caps"]["parallel"])' "${REPO}/harness/config.toml")"
  echo "phase: $(jq -r '.[0] | "\(.phase) (\(.phaseName)), from \(.phaseSource)"' <<< "$rows" 2>/dev/null || echo "unknown")"
  echo "queue: $(jq length <<< "$rows") spec(s); this wake-up starts at most ${cap}, ${par} at a time"
  jq -r '.[] | "  \(.action | ascii_upcase)\t\(.id)\t\(.class)\t\(.forecast)"' <<< "$rows" | column -t -s $'\t'
  [ "$dry" = 0 ] || return 0
  while IFS= read -r id; do
    if [ "${#only[@]}" -gt 0 ] && ! printf '%s\n' "${only[@]}" | grep -qx "$id"; then continue; fi
    ids+=("$id")
  done < <(jq -r '.[] | select(.action == "run") | .id' <<< "$rows")
  ids=("${ids[@]:0:$cap}")
  [ "${#ids[@]}" -gt 0 ] || { echo "nothing to run: the queue is empty until a person approves a spec"; return 0; }
  echo "starting: ${ids[*]}"
  printf 'specs/%s.md\n' "${ids[@]}" \
    | xargs -P "$par" -I{} bash -c '"$0/harness/bin/workbench.sh" "$1" "${@:2}" > "$0/runs/console-$(basename "$1" .md)-$(date +%H%M%S).log" 2>&1 || true' \
        "$REPO" {} "${extra[@]+"${extra[@]}"}"
  echo "wake-up done; the ledger's last rows:"
  tail -n "${#ids[@]}" "$ledger" | jq -r '"  \(.spec)  \(.path)  $\(.costUsd * 100 | round / 100)  \(.pr // "")"'
}

if [ -n "$every" ]; then
  [[ "$every" =~ ^[0-9]+$ ]] && [ "$every" -ge 5 ] || die "--every takes minutes, 5 or more"
  while :; do wake; echo "sleeping ${every} min"; sleep $((every * 60)); done
else
  wake
fi
