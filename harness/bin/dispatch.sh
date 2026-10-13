#!/bin/bash
# dispatch.sh: loop 4, the queue. Takes the next approved specs, runs each in its own
# workbench, several at once, and stops at the queue cap. What puts work in the queue is
# configuration (harness/config.toml [triggers]): a ticket watch, schedule entries and a budget
# pool. A trigger only feeds the queue; the workbench and the sandboxed run are unchanged.
#
#   harness/bin/dispatch.sh --dry-run [--pool-usd N]   show the queue, the forecast and the pool math, spend nothing
#   harness/bin/dispatch.sh [--only ID]... [--pool-usd N]
#                                                     one wake-up: run up to tasks_per_queue_run specs
#   harness/bin/dispatch.sh --every MINUTES            wake up on a fixed timer until stopped (the old loop)
#   harness/bin/dispatch.sh --watch [--pool-usd N]     stay up: every minute check the halt flag, fire the
#                                                     schedule entries that are due, poll tickets every
#                                                     poll_minutes, apply the pool
#   --pool-usd N     the budget pool for this run, over [triggers.budget] pool_usd (0: unlimited within caps)
#   --no-publish, --no-review   passed through to workbench.sh
#
# The halt flag beats every trigger: while runs/HALT (or $WORKBENCH_HALT) exists nothing starts.
#   touch runs/HALT      stop starting work (running tasks finish within their caps)
#   rm runs/HALT         resume
#
# The pool: the dispatcher starts another task only while at least one per-task cap
# (caps.max_budget_usd) still fits in what is left of the pool for its window, debits each
# finished task's cost from the ledger, and when the pool is exhausted with work still queued
# writes one budget-exhausted row {pool, spent, window, leftInQueue} to runs/ledger.jsonl.
#
# Every wake-up ends with a line in runs/ledger.jsonl for each task it started, whatever the
# outcome. A spec that already ran (a PR, a batch, a merge) is not run again.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=../lib/common.sh
. "${REPO}/harness/lib/common.sh"
dry=0 every="" watch=0 pool_usd="" only=() extra=()
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry=1; shift ;;
    --every) every="${2:?}"; shift 2 ;;
    --watch) watch=1; shift ;;
    --pool-usd) pool_usd="${2:?}"; shift 2 ;;
    --only) only+=("${2:?}"); shift 2 ;;
    --no-publish|--no-review) extra+=("$1"); shift ;;
    -h|--help) sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
[ -z "$pool_usd" ] || [[ "$pool_usd" =~ ^[0-9]+(\.[0-9]+)?$ ]] || die "--pool-usd takes a number of dollars"
ledger="${REPO}/runs/ledger.jsonl"
HALT="${WORKBENCH_HALT:-${REPO}/runs/HALT}"
mkdir -p "${REPO}/runs"
H="${REPO}/harness"
cfg() { python3 -c 'import tomllib,sys,json
d=tomllib.load(open(sys.argv[1],"rb"))
for k in sys.argv[2].split("."): d=d[k]
print(json.dumps(d) if isinstance(d,(dict,list,bool)) else d)' "${H}/config.toml" "$1"; }
RUN_START="$(date -u +%FT%TZ)"
exhausted_written=0

halted() {
  if [ -e "$HALT" ]; then
    log "halted: ${HALT} exists; nothing starts until it is removed (running tasks finish within their caps)"
    return 0
  fi
  return 1
}

queue() {
  # The queue is read from the base branch, like everything the harness acts on.
  local base tmp
  base="$(cfg github.base)"
  tmp="$(mktemp -d)"
  g -C "$REPO" archive "$base" harness specs | tar -x -C "$tmp"
  python3 "${tmp}/harness/lib/plan.py" queue "${tmp}/harness" "${tmp}/specs" | node --no-warnings "${tmp}/harness/lib/preroute.ts" "$ledger"
  rm -rf "$tmp"
}

# pool_status <runnable count>: JSON from pool.py for this run's window.
pool_status() {
  python3 "${H}/lib/pool.py" status "$H" "$ledger" --since "$RUN_START" --queued "$1" ${pool_usd:+--pool-usd "$pool_usd"}
}

pool_line() { jq -r .line <<< "$1"; }

# exhausted_row <pool status json>: one budget-exhausted row, once per exhaustion.
exhausted_row() {
  [ "$exhausted_written" = 0 ] || return 0
  python3 "${H}/lib/pool.py" exhausted-row "$H" "$ledger" --since "$RUN_START" --queued "$(jq .queued <<< "$1")" ${pool_usd:+--pool-usd "$pool_usd"} >> "$ledger"
  exhausted_written=1
  log "budget-exhausted: pool \$$(jq -r .pool <<< "$1"), spent \$$(jq -r '.spent * 100 | round / 100' <<< "$1") (window $(jq -r .window <<< "$1")), $(jq -r .queued <<< "$1") approved spec(s) left in the queue; nothing more starts. Ledger row written."
}

wake() {
  local rows cap par ids=() id n pool runnable
  halted && return 0
  rows="$(queue)"
  cap="$(cfg caps.tasks_per_queue_run)"
  par="$(cfg caps.parallel)"
  echo "phase: $(jq -r '.[0] | "\(.phase) (\(.phaseName)), from \(.phaseSource)"' <<< "$rows" 2>/dev/null || echo "unknown")"
  echo "queue: $(jq length <<< "$rows") spec(s); this wake-up starts at most ${cap}, ${par} at a time"
  jq -r '.[] | "  \(.action | ascii_upcase)\t\(.id)\t\(.class)\t\(.forecast)"' <<< "$rows" | column -t -s $'\t'
  while IFS= read -r id; do
    if [ "${#only[@]}" -gt 0 ] && ! printf '%s\n' "${only[@]}" | grep -qx "$id"; then continue; fi
    ids+=("$id")
  done < <(jq -r '.[] | select(.action == "run") | .id' <<< "$rows")
  runnable="${#ids[@]}"
  pool="$(pool_status "$runnable")"
  pool_line "$pool"
  if [ "$(jq .unlimited <<< "$pool")" != true ]; then
    n="$(jq .fits <<< "$pool")"
    if [ "$n" -lt "$cap" ]; then cap="$n"; fi
    if [ "$cap" = 0 ] && [ "$runnable" -gt 0 ]; then
      if [ "$dry" = 1 ]; then
        echo "budget-exhausted: the pool cannot pay for one more task; ${runnable} approved spec(s) wait. A live wake-up writes the budget-exhausted row to runs/ledger.jsonl and starts nothing."
      else
        exhausted_row "$pool"
      fi
      return 0
    fi
  fi
  exhausted_written=0
  [ "$dry" = 0 ] || { [ "$runnable" = 0 ] || echo "would start: ${ids[*]:0:$cap}"; return 0; }
  ids=("${ids[@]:0:$cap}")
  [ "${#ids[@]}" -gt 0 ] || { echo "nothing to run: the queue is empty until a person approves a spec"; return 0; }
  echo "starting: ${ids[*]}"
  printf 'specs/%s.md\n' "${ids[@]}" \
    | xargs -P "$par" -I{} bash -c '"$0/harness/bin/workbench.sh" "$1" "${@:2}" > "$0/runs/console-$(basename "$1" .md)-$(date +%H%M%S).log" 2>&1 || true' \
        "$REPO" {} "${extra[@]+"${extra[@]}"}"
  echo "wake-up done; the ledger's last rows:"
  tail -n "${#ids[@]}" "$ledger" | jq -r '"  \(.spec)  \(.path)  $\(.costUsd * 100 | round / 100)  \(.pr // "")"'
  # Debit what the tasks spent; say so when the pool can no longer start the next one.
  pool="$(pool_status $(( runnable - ${#ids[@]} )))"
  pool_line "$pool"
  if [ "$(jq .exhausted <<< "$pool")" = true ] && [ $(( runnable - ${#ids[@]} )) -gt 0 ]; then exhausted_row "$pool"; fi
}

# enqueue_recurring <name>: a schedule entry's recurring spec becomes one dated, approved spec
# on the base branch, so the next queue wake-up finds it where it finds every spec.
enqueue_recurring() {
  local name="$1" base r id file
  base="$(cfg github.base)"
  r="$(python3 "${H}/lib/schedule.py" enqueue "$H" "${REPO}/specs" "$name" "$ledger" $( [ "$dry" = 1 ] && echo --dry-run ))"
  if [ "$(jq .written <<< "$r")" != true ]; then log "schedule: ${name}: $(jq -r .reason <<< "$r")$( [ -n "$(jq -r '.id // ""' <<< "$r")" ] && echo " ($(jq -r .id <<< "$r"))")"; return 0; fi
  id="$(jq -r .id <<< "$r")"; file="specs/${id}.md"
  if [ "$(g -C "$REPO" rev-parse --abbrev-ref HEAD)" = "$base" ]; then
    g -C "$REPO" add -- "$file" && g -C "$REPO" commit --quiet --no-verify -m "schedule: ${id} enqueued from harness/recurring/${name}.md" -- "$file" \
      && log "schedule: ${name}: ${file} written and committed on ${base} ($(jq -r .trigger <<< "$r")); push ${base} when you want the PR to diff only the task's change" \
      || log "schedule: ${name}: ${file} written; the commit on ${base} failed, so the queue will not see it until it is committed"
  else
    log "schedule: ${name}: ${file} written but the working tree is not on ${base}; commit it there for the queue to see it"
  fi
}

tick() {
  # One minute of watch mode: the halt flag, the schedule entries, the ticket poll.
  local entries due_queue=0 e minute started
  halted && return 0
  entries="$(python3 "${H}/lib/schedule.py" entries "$H")"
  while IFS= read -r e; do
    [ -n "$e" ] || continue
    if [ "$(jq -r .take <<< "$e")" = queue ]; then due_queue=1
    else log "schedule: entry $(jq -r .cron <<< "$e") ($(jq -r .tz <<< "$e")) is due: $(jq -r .what <<< "$e")"; enqueue_recurring "$(jq -r .spec <<< "$e")"; fi
  done < <(jq -c '.[] | select(.due)' <<< "$entries")
  if [ "$(cfg triggers.ticket.enabled 2>/dev/null || echo false)" = true ]; then
    minute=$(( $(date +%s) / 60 ))
    if [ $(( minute % $(cfg triggers.ticket.poll_minutes) )) = 0 ]; then
      started="$("${REPO}/harness/bin/watch-tickets.sh" --quiet $( [ "$dry" = 1 ] && echo --dry-run ) 2>&1 | tee /dev/stderr | grep -oE '^started [0-9]+' | awk '{print $2}' || true)"
      [ "${started:-0}" = 0 ] || { log "tickets: ${started} task(s) written from tickets; waking the queue now"; due_queue=1; }
    fi
  fi
  if [ "$due_queue" = 1 ]; then log "schedule: the queue entry is due; wake-up"; wake; fi
}

if [ "$watch" = 1 ]; then
  [ -z "$every" ] || die "--watch and --every do not combine; --watch reads the schedule entries from config.toml"
  log "watch: ticking every minute$( [ "$dry" = 1 ] && echo " (dry run: nothing starts, nothing is written)"); halt flag ${HALT}; schedule entries:"
  python3 "${H}/lib/schedule.py" entries "$H" | jq -r '.[] | "  \(.cron)  \(.tz)  \(.what); next \(.next[0] // "never")"'
  log "watch: ticket watch $( [ "$(cfg triggers.ticket.enabled)" = true ] && echo "on: $(cfg triggers.ticket.label) by $(cfg triggers.ticket.approvers | jq -r 'join(", ")'), every $(cfg triggers.ticket.poll_minutes) min" || echo "off ([triggers.ticket] enabled = false)")"
  log "watch: $(pool_line "$(pool_status 0)")"
  while :; do
    tick || log "tick failed (exit $?); the watch continues"
    sleep $(( 60 - $(date +%s) % 60 ))
  done
elif [ -n "$every" ]; then
  [[ "$every" =~ ^[0-9]+$ ]] && [ "$every" -ge 5 ] || die "--every takes minutes, 5 or more"
  while :; do wake; echo "sleeping ${every} min"; sleep $((every * 60)); done
else
  wake
fi
