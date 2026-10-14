#!/bin/bash
# case-run.sh: run one trajectory case k times and score every trial from facts. The reproduce
# step (--pack current) and the prove step (--pack candidate) of the proving loop.
#
#   harness/bin/case-run.sh harness/cases/<case>.json --pack current|candidate|control [--k 3] [--base BRANCH]
#                           [--out DIR] [--max-usd 3.5] [--holdout]
#
# Each trial is a fresh workbench (workbench.sh --no-publish --trial N --retries 0): the spec
# the case names, run from the base branch's harness (current: [github] base; candidate: the
# case's fixBranch, or --base; control: the current pack a second time, same k, so the verdict
# carries a noise floor, the spread between the two current-pack runs, and proof.py refuses a
# delta inside it as too-small-to-see). --holdout also runs, on the same pack and k, every case
# the case's "holdout" list names: cases the improver never reads, whose delta proof.py reports
# apart. A trial passes when, in its packet, the trusted checks passed on
# a non-empty in-scope change, the reviewer approved at round 0, and ruff check --no-fix (the
# pre-commit pinned version) passes on the result's changed Python files. Nothing is read from
# Claude's account of its work. Writes <out>/trials.jsonl, trials.txt and summary.json under
# runs/proofs/<case id>/<pack>/; stops before a trial that would take the spend past --max-usd.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=../lib/common.sh
. "${REPO}/harness/lib/common.sh"
case_file="" pack="" k="" base="" out="" max_usd="3.5" rescore=0 holdout=0
while [ $# -gt 0 ]; do
  case "$1" in
    --pack) pack="${2:?}"; shift 2 ;;
    --k) k="${2:?}"; shift 2 ;;
    --base) base="${2:?}"; shift 2 ;;
    --out) out="${2:?}"; shift 2 ;;
    --max-usd) max_usd="${2:?}"; shift 2 ;;
    --rescore) rescore=1; shift ;;   # score the trials already on record again from their packets; run nothing
    --holdout) holdout=1; shift ;;   # also run the case's held-out cases on this pack
    -*) die "unknown option: $1" ;;
    *) case_file="$1"; shift ;;
  esac
done
[ -n "$case_file" ] && [ -f "$case_file" ] || die "usage: case-run.sh harness/cases/<case>.json --pack current|candidate|control [--k 3] [--base BRANCH] [--holdout]"
[ "$pack" = current ] || [ "$pack" = candidate ] || [ "$pack" = control ] || die "--pack must be current, candidate or control"
cj() { jq -r "$1" "$case_file"; }
[ "$(cj .kind)" = trajectory ] || die "$(cj .id) is a $(cj .kind) case; case-run.sh runs trajectory cases (cases.sh runs the flags cases)"
spec="$(cj .spec)"; cid="$(cj .id)"
[ -n "$k" ] || k="$(cj '.k // 3')"
[[ "$k" =~ ^([1-9]|10)$ ]] || die "--k must be 1 to 10"
if [ "$holdout" = 1 ]; then
  # The held-out cases: the same pack and k, each under its own runs/proofs/<id>/<pack>/.
  # The improver never reads them; proof.py reports their delta apart from the training case's.
  held="$(cj '(.holdout // []) | .[]')"
  [ -n "$held" ] || log "case ${cid} names no holdout: suite too small to split (nothing held out to run)"
  for h in $held; do
    hf="${REPO}/harness/cases/${h}.json"; [ -f "$hf" ] || die "held-out case ${h} not found (harness/cases/${h}.json)"
    log "holdout: case ${h} on pack ${pack}, k ${k}"
    "${REPO}/harness/bin/case-run.sh" "$hf" --pack "$pack" --k "$k" --max-usd "$max_usd" ${base:+--base "$base"} $( [ "$rescore" = 1 ] && echo --rescore )
  done
fi
if [ -z "$base" ]; then
  if [ "$pack" = current ] || [ "$pack" = control ]; then
    base="$(python3 -c 'import tomllib,sys;print(tomllib.load(open(sys.argv[1],"rb"))["github"]["base"])' "${REPO}/harness/config.toml")"
  else
    base="$(cj '.fixBranch // empty')"; [ -n "$base" ] || die "the case names no fixBranch; pass --base"
  fi
fi
g -C "$REPO" rev-parse --verify --quiet "${base}^{commit}" >/dev/null || die "no branch ${base}"
[ -n "$out" ] || out="${REPO}/runs/proofs/${cid}/${pack}"
mkdir -p "$out"; out="$(cd "$out" && pwd)"
ruff_ver="$(sed -n '/ruff-pre-commit/,/rev:/s/.*rev: v//p' "${REPO}/.pre-commit-config.yaml" | head -1)"
RUFF="ruff@${ruff_ver:-0.16.10}"
# What a pass needs, from the case: the facts a trial must carry. The default is the broad
# check; a narrow case names fewer keys (for instance no review0).
keys="$(cj '(.stateCheckKeys // ["checksPass", "changed", "failFirst", "review0", "ruffOk"]) | @json')"
trials="${out}/trials.jsonl"

# score <task run dir> <trial> -> one JSON row
score() {
  local rdir="$1" i="$2" p="$1/packet.json" head files ruff_rc=0 ruff_out="" wt
  head="$(jq -r '.headCommit // empty' "$p")"
  files="$(jq -r '[.changedPaths[] | select(endswith(".py"))] | join(" ")' "$p")"
  if [ -n "$head" ] && [ -n "$files" ]; then
    wt="$(mktemp -d)"
    g -C "$REPO" worktree add --quiet --detach "$wt" "$head"
    # shellcheck disable=SC2086
    ruff_out="$(cd "$wt" && uvx "$RUFF" check --no-fix --output-format concise $files 2>&1)" || ruff_rc=$?
    g -C "$REPO" worktree remove --force "$wt" 2>/dev/null || rm -rf "$wt"
  else
    ruff_out="no Python file changed"
  fi
  printf '%s\n' "$ruff_out" > "${rdir}/ruff.txt"
  jq -c --argjson i "$i" --arg pack "$pack" --arg base "$base" --argjson ruffRc "$ruff_rc" --argjson keys "$keys" \
     --argjson ruffFindings "$(grep -cE '^[^ ]+:[0-9]+:[0-9]+: ' <<< "$ruff_out" || true)" --arg rdir "$rdir" '
    (.rounds // []) as $r | ($r[0] // {}) as $r0 |
    {trial: $i, taskId, pack: $pack, base: $base, baseSha: .baseCommit, headSha: .headCommit, packId, dir: $rdir,
     # The environment fingerprint (pack, Claude Code version, served model): proof.py voids a
     # before/after comparison whose fingerprints differ on anything but the pack id.
     fingerprint: (.fingerprint // null),
     checksPass: .allChecksPass,
     changed: ((.changedPaths | length) > 0 and ((.scope.outside + .scope.harness) | length) == 0),
     failFirst: (.grading == null or .grading.ok),
     review0: (($r0.verdict.verdict // .review.verdict // "none") == "approve"),
     reviewVerdict0: ($r0.verdict.verdict // .review.verdict // "none"),
     reviewReasons0: ($r0.verdict.reasons // .review.reasons // []),
     rounds: ($r | length), retries: .loops.retries,
     ruffOk: ($ruffRc == 0), ruffFindings: $ruffFindings,
     stopBlocks: ([.loops.finish[] | select(.result == "block")] | length),
     workerTurns: ([.loops.sessions[] | select(.role == "worker") | .turns] | add),
     # A session that ended on an API or network error (is_error in its result) is an error of
     # the environment, not of the trajectory: the trial is inconclusive, neither pass nor fail.
     sessionErrors: [.loops.sessions[] | select(.isError == true or ((.subtype // "") | startswith("error"))) | "\(.role) round \(.round): \(.subtype)\(if (.result // "") | startswith("API Error") then ", " + (.result | .[0:120]) else "" end)"],
     costUsd: .costUsd}
    | .stateCheckKeys = $keys
    | .outcome = (if (.sessionErrors | length) > 0 then "error"
                  elif ([.[$keys[]]] | all) then "pass" else "fail" end)
    | .why = ([(.sessionErrors[] | "session error: " + .),
               (if ("checksPass" | IN($keys[])) and (.checksPass | not) then "trusted checks failed" else empty end),
               (if ("changed" | IN($keys[])) and (.changed | not) then "empty or out-of-scope diff" else empty end),
               (if ("failFirst" | IN($keys[])) and (.failFirst | not) then "fail-first did not hold" else empty end),
               (if ("review0" | IN($keys[])) and (.review0 | not) then "reviewer: \(.reviewVerdict0) at round 0" else empty end),
               (if ("ruffOk" | IN($keys[])) and (.ruffOk | not) then "ruff: \(.ruffFindings) finding(s)" else empty end)] | join("; "))' "$p"
}

# A case may reuse another case's recorded trials on the same packs (case.reuse.<pack>: a
# folder of task runs). On the first run, the task folders are copied and scored again under
# this case's own state check; nothing is run for them.
reuse="$(cj ".reuse.${pack} // empty")"
if [ ! -s "$trials" ] && [ -n "$reuse" ]; then
  src="${REPO}/${reuse}"; [ -d "$src" ] || die "reuse folder ${reuse} not found"
  : > "$trials"
  log "reusing the trials of ${reuse}: copying its task folders, scoring them under this case's state check ${keys}"
  cp "${src}/ledger.jsonl" "${out}/ledger.jsonl" 2>/dev/null || true
  for d in "${src}"/t-*/; do [ -d "$d" ] && cp -r "$d" "${out}/"; done
  n=0
  while IFS= read -r old; do
    n=$((n + 1)); id="$(jq -r '.taskId // empty' <<< "$old")"
    if [ -n "$id" ] && [ -f "${out}/${id}/packet.json" ]; then score "${out}/${id}" "$n" >> "$trials"; else jq -c --argjson n "$n" '.trial = $n' <<< "$old" >> "$trials"; fi
  done < "${src}/trials.jsonl"
fi
touch "$trials"
done_n="$(wc -l < "$trials" | tr -d ' ')"
spent="$(jq -s 'map(.costUsd // 0) | add // 0' "$trials")"
spent0="$spent"   # --max-usd caps what this invocation adds, not the record it continues
log "case ${cid}: spec ${spec}, pack ${pack} (base ${base} at $(g -C "$REPO" rev-parse --short "$base")), k ${k}, ${done_n} trial(s) already on record, \$${spent} spent, cap \$${max_usd} for this run; ruff ${ruff_ver}; pass needs ${keys}"

if [ "$rescore" = 1 ] && [ "$done_n" != 0 ]; then
  # Score every recorded trial again from its packet and result tree (the scoring may have
  # changed; the record has not). Rows without a task folder stay as they are.
  : > "${trials}.new"
  while IFS= read -r old; do
    id="$(jq -r '.taskId // empty' <<< "$old")"; i="$(jq -r .trial <<< "$old")"
    if [ -n "$id" ] && [ -f "${out}/${id}/packet.json" ]; then score "${out}/${id}" "$i" >> "${trials}.new"; else printf '%s\n' "$old" >> "${trials}.new"; fi
  done < "$trials"
  mv "${trials}.new" "$trials"
  log "rescored ${done_n} trial(s); no new trial runs under --rescore"
fi

# Run until k conclusive trials are on record (an error trial takes a slot in the file, not in
# k), and never more than k error trials in one invocation: a network or credential problem is
# not something to retry forever on someone's money.
i="$done_n"
conclusive="$(jq -s 'map(select(.outcome != "error")) | length' "$trials")"
errors=0
while [ "$rescore" = 0 ] && [ "$conclusive" -lt "$k" ]; do
  if [ "$errors" -ge "$k" ]; then
    log "stopping: ${errors} error trial(s) in this run (the cap is k=${k}); fix the environment, then run again"
    break
  fi
  i=$((i + 1))
  # The spend guard: the case's expected cost per run (budgetUsdPerRun, from the recorded runs
  # of its spec) against the cap for this run. Claude Code's own per-session caps sit under it.
  est="$(cj '.budgetUsdPerRun // 1.0')"
  run_spent="$(python3 -c 'import sys; print(round(float(sys.argv[1]) - float(sys.argv[2]), 4))' "$spent" "$spent0")"
  if python3 -c 'import sys; sys.exit(0 if float(sys.argv[1]) + float(sys.argv[2]) > float(sys.argv[3]) else 1)' "$run_spent" "$est" "$max_usd"; then
    log "trial ${i} (conclusive ${conclusive} of ${k}) not started: \$${run_spent} spent in this run and the next trial is expected to cost about \$${est}, over the \$${max_usd} cap"
    break
  fi
  log "trial ${i} (conclusive ${conclusive} of ${k}): workbench.sh specs/${spec}.md --base ${base} --no-publish --retries 0"
  id="$("${REPO}/harness/bin/workbench.sh" "specs/${spec}.md" --base "$base" --no-publish --trial "$i" --retries 0 --out "$out" 2> >(tee "${out}/console-${i}.log" >&2) | sed -n 's/^task-id: //p' | tail -1)" || true
  if [ -z "$id" ] || [ ! -f "${out}/${id}/packet.json" ]; then
    # The workbench could not start or did not finish (credentials, preflight, a cap): nothing
    # to score, and nothing a second attempt would change. Record it and stop.
    row="$(jq -nc --argjson i "$i" --arg pack "$pack" --arg base "$base" '{trial: $i, pack: $pack, base: $base, outcome: "error", why: "the workbench did not finish", costUsd: 0}')"
    printf '%s\n' "$row" >> "$trials"
    log "trial ${i}: error (the workbench did not finish: see console-${i}.log); stopping"
    break
  fi
  row="$(score "${out}/${id}" "$i")"
  printf '%s\n' "$row" >> "$trials"
  spent="$(jq -s 'map(.costUsd // 0) | add // 0' "$trials")"
  conclusive="$(jq -s 'map(select(.outcome != "error")) | length' "$trials")"
  [ "$(jq -r .outcome <<< "$row")" != error ] || errors=$((errors + 1))
  log "trial ${i}: $(jq -r '"\(.outcome)\(if .why != "" and .why != null then " (" + .why + ")" else "" end), $\(.costUsd // 0 | . * 100 | round / 100)"' <<< "$row")"
done

# The table and the summary.
{
  printf 'case %s, pack %s (base %s), spec %s, ruff %s\n' "$cid" "$pack" "$base" "$spec" "$ruff_ver"
  printf '%-6s %-28s %-8s %-7s %-10s %-12s %-6s %-7s %s\n' trial task outcome checks reviewer0 ruff blocks cost why
  jq -r '[.trial, (.taskId // "-"), .outcome, (if .checksPass == true then "pass" elif .checksPass == false then "FAIL" else "-" end),
          (.reviewVerdict0 // "-"), (if .ruffOk == true then "pass" elif .ruffOk == false then "\(.ruffFindings) finding(s)" else "-" end),
          (.stopBlocks // "-"), ("$" + ((.costUsd // 0) * 100 | round / 100 | tostring)), (.why // "")] | @tsv' "$trials" \
    | awk -F'\t' '{ printf "%-6s %-28s %-8s %-7s %-10s %-12s %-6s %-7s %s\n", $1, $2, $3, $4, $5, $6, $7, $8, $9 }'
  # pass^k over the conclusive trials: an error trial (a session that died on the network) is
  # named, counted, and left out of the ratio; it is neither evidence for nor against the pack.
  jq -s -r '(map(select(.outcome == "pass")) | length) as $p | (map(select(.outcome == "error")) | length) as $e | (length - $e) as $c |
    "pass^k: \(if $c > 0 and $p == $c then 1 else 0 end) (\($p) of \($c) conclusive trial(s) passed\(if $e > 0 then ", \($e) error trial(s) not counted" else "" end)), $\(map(.costUsd // 0) | add // 0 | . * 100 | round / 100) in all"' "$trials"
  # A task folder with no packet and no row is a trial the runner did not finish (killed, or the
  # machine went down): named here, counted nowhere, its worker's spend read from its transcript.
  for d in "${out}"/t-*/; do
    [ -d "$d" ] && [ ! -f "${d}packet.json" ] && ! grep -q "\"taskId\":\"$(basename "$d")\"" "$trials" || continue
    printf 'interrupted: %s (no packet; worker spend $%s)\n' "$(basename "$d")" \
      "$(jq -s 'map(select(.type == "result") | .total_cost_usd // 0) | add // 0 | . * 100 | round / 100' "${d}transcript.jsonl" 2>/dev/null || echo 0)"
  done
} | tee "${out}/trials.txt" >&2
interrupted="$(for d in "${out}"/t-*/; do
    [ -d "$d" ] && [ ! -f "${d}packet.json" ] && ! grep -q "\"taskId\":\"$(basename "$d")\"" "$trials" || continue
    jq -nc --arg t "$(basename "$d")" --argjson c "$(jq -s 'map(select(.type == "result") | .total_cost_usd // 0) | add // 0' "${d}transcript.jsonl" 2>/dev/null || echo 0)" '{taskId: $t, costUsd: $c}'
  done | jq -sc '.')"
jq -s --arg cid "$cid" --arg pack "$pack" --arg base "$base" --arg spec "$spec" --argjson k "$k" --arg sha "$(g -C "$REPO" rev-parse "$base")" --argjson intr "$interrupted" '
  (map(select(.outcome == "pass")) | length) as $p | (map(select(.outcome == "error")) | length) as $e | (length - $e) as $c |
  {case: $cid, pack: $pack, base: $base, baseSha: $sha, spec: $spec, k: $k, trials: $c, errors: $e, passes: $p,
   passK: (if $c > 0 and $p == $c then 1 else 0 end), costUsd: (map(.costUsd // 0) | add // 0),
   interrupted: $intr, interruptedCostUsd: ($intr | map(.costUsd) | add // 0),
   packIds: (map(.packId // empty) | unique), fingerprints: (map(.fingerprint // empty) | unique),
   at: (now | todate), runs: .}' "$trials" > "${out}/summary.json"
jq -c '{case, pack, k, trials, errors, passes, passK, costUsd, interrupted: (.interrupted | length), packIds}' "${out}/summary.json"
