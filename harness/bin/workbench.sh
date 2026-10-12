#!/bin/bash
# workbench.sh: one task, end to end. Spec in; a checked change and its evidence out.
#
#   harness/bin/workbench.sh specs/<id>.md [--base BRANCH] [--no-publish] [--no-review]
#                            [--out DIR] [--trial N]
#
#   1 Spec     the spec and the whole harness come from the BASE commit, never the work tree
#   2 Work     a git worktree for this task alone; headless Claude Code (claude -p) in dontAsk
#              mode under the settings template, the native sandbox and the pack
#                loop 1 session   --max-turns and --max-budget-usd
#                loop 2 finish    the Stop hook runs the quick checks and blocks a false finish
#   3 Check    the acceptance checks in a fresh clone of the result under bubblewrap with no
#              network; fail-first on the base; the scope check on the diff; then a second
#              Claude, a different model with edits denied, argues against the change
#                loop 3 retry     on a rejection, claude --resume with the findings
#   4 Route    the router decides from facts, never from Claude's account; evidence packet;
#              a PR on the fork with the packet as its body (publish.sh)
#
# Linux or WSL2 only: the native sandbox needs bubblewrap. Exit 0 when the task ran, whatever
# its outcome; 2 when it could not start. The last line on stdout is "task-id: <id>".
set -euo pipefail
umask 077

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=../lib/common.sh
. "${REPO}/harness/lib/common.sh"

spec="" base="" publish=1 review=1 out="${REPO}/runs" trial=""
while [ $# -gt 0 ]; do
  case "$1" in
    --base) base="${2:?}"; shift 2 ;;
    --no-publish) publish=0; shift ;;
    --no-review) review=0; shift ;;
    --out) out="${2:?}"; shift 2 ;;
    --trial) trial="${2:?}"; shift 2 ;;
    -*) die "unknown option: $1" ;;
    *) spec="$1"; shift ;;
  esac
done
[ -n "$spec" ] || die "usage: workbench.sh specs/<id>.md [--base BRANCH] [--no-publish] [--no-review]"

# ---- Prerequisites: say exactly what is missing ---------------------------------------------
"${REPO}/harness/bin/preflight.sh" --quiet || die "preflight failed: run harness/bin/preflight.sh for the details"
# shellcheck source=../lib/auth.sh
. "${REPO}/harness/lib/auth.sh"
load_auth

# ---- 1. Spec: from the base commit -----------------------------------------------------------
[ -n "$base" ] || base="$(python3 -c 'import tomllib,sys;print(tomllib.load(open(sys.argv[1],"rb"))["github"]["base"])' "${REPO}/harness/config.toml")"
base_sha="$(g -C "$REPO" rev-parse --verify --quiet "${base}^{commit}")" || die "no branch ${base}"
spec_rel="specs/$(basename "$spec")"
g -C "$REPO" cat-file -e "${base_sha}:${spec_rel}" 2>/dev/null \
  || die "${spec_rel} is not committed on ${base}: the harness runs approved specs from the base commit only"

task_id="t-$(python3 -c 'import os,time
a="0123456789ABCDEFGHJKMNPQRSTVWXYZ";t=int(time.time()*1000);s=""
for _ in range(10): s=a[t%32]+s; t//=32
print(s+"".join(a[b%32] for b in os.urandom(16)))')"
branch="workbench/${task_id}"
tdir="${WB_HOME}/${task_id}"
work="${tdir}/work"
mkdir -p "$out"; out="$(cd "$out" && pwd)"
rdir="${out}/${task_id}"
[[ "$tdir" =~ ^/[A-Za-z0-9._/-]+$ ]] || die "WORKBENCH_HOME must be a plain absolute path"
mkdir -p "${tdir}/evidence" "${tdir}/claude-config" "${tdir}/trusted" "$rdir" "${HOME}/.cache/uv"
echo "$base_sha" > "${tdir}/base_sha"
: > "${tdir}/loops.jsonl"

cleanup() {
  local rc=$?
  cp "${tdir}/loops.jsonl" "${rdir}/loops.jsonl" 2>/dev/null || true
  for w in "$work" "${tdir}/review"; do
    [ -e "$w" ] && { g -C "$REPO" worktree remove --force "$w" 2>/dev/null || rm -rf "$w"; }
  done
  g -C "$REPO" worktree prune 2>/dev/null || true
  rm -rf "$tdir"
  exit "$rc"
}
trap cleanup EXIT

# The trusted harness: the base commit's harness, hooks, pack, settings template and specs.
g -C "$REPO" archive "$base_sha" harness .claude specs | tar -x -C "${tdir}/trusted"
T="${tdir}/trusted"
python3 "${T}/harness/lib/plan.py" plan "${T}/harness" "${T}/${spec_rel}" > "${tdir}/plan.json"
cp "${tdir}/plan.json" "${rdir}/plan.json"
plan="${tdir}/plan.json"
pj() { jq -r "$1" "$plan"; }
[ "$(pj .status)" = approved ] || die "spec $(pj .id) is $(pj .status): a person approves the intent before any spend"
# The pack id names everything that shapes a run: the pack, the hooks, the settings template.
pack_id="pack-$(cd "$T" && find harness/pack harness/hooks .claude/workbench -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-12)"

caps() { pj ".caps.$1"; }
log "task ${task_id}: spec $(pj .id) (class $(pj .class)) on ${base} at ${base_sha:0:12}, ${pack_id}"
event "${tdir}/loops.jsonl" --arg loop task --arg event start --arg taskId "$task_id" --arg spec "$(pj .id)" --arg packId "$pack_id"
started_at="$(date -u +%FT%TZ)"

# ---- 2. Work: worktree, environment, settings ------------------------------------------------
g -C "$REPO" worktree add --quiet -b "$branch" "$work" "$base_sha"
gitfile="$(cat "${work}/.git")"

# Setup on the base commit, with network, under bubblewrap: only the base's own manifests run
# with a network. The task's virtualenv lives outside the worktree.
export WB_TRUSTED="$T" WB_VENV="${tdir}/venv" WB_SRC="$work" WB_BASE_SHA="$base_sha"
log "setup: the task's Python environment, from the base commit"
while IFS= read -r c; do
  { echo "### setup: $c"; confined net "$tdir" "$(expand "$c")"; } >> "${rdir}/setup.log" 2>&1 < /dev/null \
    || die "setup failed on the base commit: see ${rdir}/setup.log"
done < <(pj '.setup[]')

# settings <worktree> <extra deny rules JSON> <with hooks: 1|0> > file
settings() { wb_settings "$T" "$tdir" "$plan" "$@"; }
settings "$work" '[]' 1 > "${tdir}/settings.json"
cp "${tdir}/settings.json" "${rdir}/settings.json"

{ cat <<EOF
$(pj .body)

## How this workbench works

- This git worktree is yours alone for this task: ${work}
- The Python environment is ready. Run tests with \`${WB_VENV}/bin/python -m pytest -q -p no:cacheprovider\`.
  Do not install anything.
- Edit only: $(jq -r '.scope | join(", ")' "$plan"). Edits anywhere else are refused.
- When you say you are done, a Stop hook runs the spec's quick checks. If they fail you will be
  told why and asked to continue.
- After you finish, the acceptance checks run again in a fresh clone with no network, and a
  separate reviewer argues against the change. Fix causes, never checks.
- Do not run git commit. The workbench commits the worktree for you.
EOF
} > "${rdir}/prompt.md"

# claude_run <cwd> <settings> <prompt file> <transcript> <model> <max turns> <max budget> [args...]
claude_version="$(claude --version 2>/dev/null | head -1)"
claude_run() {
  local cwd="$1" set="$2" prompt="$3" transcript="$4" model="$5" turns="$6" budget="$7"; shift 7
  ( cd "$cwd" && env CLAUDE_CONFIG_DIR="${tdir}/claude-config" \
      timeout --signal=TERM --kill-after=30 "$(caps time_limit_sec)" \
      claude -p --input-format text --permission-mode dontAsk --output-format stream-json --verbose \
        --model "$model" --max-turns "$turns" --max-budget-usd "$budget" \
        --plugin-dir "${T}/harness/pack" --settings "$set" --setting-sources user --strict-mcp-config "$@" \
      < "$prompt" >> "$transcript" 2>> "${rdir}/claude.stderr" )
}
# summary <transcript>: the last result event of a session, as one JSON object.
summary() {
  jq -sc '[.[] | select(.type == "result")] | last // {} | {sessionId: .session_id, subtype, isError: .is_error,
    turns: .num_turns, costUsd: (.total_cost_usd // 0), denials: ((.permission_denials // []) | length),
    result: ((.result // "") | .[0:600])}' "$1" 2>/dev/null || echo '{}'
}

sessions='[]'
run_worker() {  # run_worker <round> [--resume <id>]
  local round="$1"; shift
  local rc=0 s
  log "loop 1 session: claude -p, round ${round}, model $(pj .models.worker), caps $(caps max_turns) turns and \$$(caps max_budget_usd)"
  claude_run "$work" "${tdir}/settings.json" "${tdir}/prompt-${round}.md" "${rdir}/transcript.jsonl" \
    "$(pj .models.worker)" "$(caps max_turns)" "$(caps max_budget_usd)" "$@" || rc=$?
  s="$(summary <(jq -c 'select(.type == "result")' "${rdir}/transcript.jsonl" | tail -1))"
  s="$(jq -c --argjson r "$round" --argjson rc "$rc" '. + {round: $r, role: "worker", exit: $rc}' <<< "$s")"
  sessions="$(jq -c --argjson s "$s" '. + [$s]' <<< "$sessions")"
  event "${tdir}/loops.jsonl" --arg loop session --argjson round "$round" --arg subtype "$(jq -r .subtype <<< "$s")" \
    --argjson turns "$(jq '.turns // 0' <<< "$s")" --argjson costUsd "$(jq '.costUsd // 0' <<< "$s")"
  log "session ended: $(jq -r '"\(.subtype), \(.turns) turns, $\(.costUsd)"' <<< "$s")"
}

# ---- 3. Check: commit, fresh clone, fail-first, scope, reviewer, route -----------------------
gw() { g -C "$work" -c user.name=workbench -c user.email=workbench@workbench.invalid "$@"; }
check="${tdir}/check"
evaluate() {  # evaluate <round>: writes facts.json, scope.json, verdict.json, decision.json
  local round="$1" c rc
  # The worktree's .git is a file naming the repository's git folder. Put it back as created.
  if [ ! -f "${work}/.git" ] || [ -L "${work}/.git" ] || [ "$(cat "${work}/.git")" != "$gitfile" ]; then
    log "the worktree's .git was changed; restoring it"; rm -rf "${work}/.git"; printf '%s\n' "$gitfile" > "${work}/.git"
  fi
  if [ -n "$(gw status --porcelain)" ]; then
    gw add -A && gw commit --quiet --no-verify -m "$(pj .title)" -m "Spec: $(pj .id) ($(pj .issue)). Workbench task ${task_id}, round ${round}."
  fi
  head_sha="$(gw rev-parse HEAD)"
  commits="$(gw rev-list --count "${base_sha}..HEAD")"

  # A fresh clone of the result. Setup runs once, on the base commit, with network.
  if [ ! -d "$check" ]; then
    g clone --quiet --no-local "$REPO" "$check"
    g -C "$check" checkout --quiet --detach "$base_sha"
    WB_VENV="${check}/.venv" WB_SRC="$check"
    while IFS= read -r c; do
      { echo "### setup (base, network): $c"; confined net "$check" "$(expand "$c")"; } >> "${rdir}/checks.log" 2>&1 < /dev/null \
        || die "setup failed in the check clone: see ${rdir}/checks.log"
    done < <(pj '.setup[]')
  fi
  g -C "$check" fetch --quiet "$REPO" "$branch"
  WB_VENV="${check}/.venv" WB_SRC="$check"

  # Fail first: each reproducing check must fail on the base and pass on the result.
  local base_checks='[]' ff_checks='[]' ff_ok=true ff_reasons='[]'
  if [ "$(jq '.checks.failFirst | length' "$plan")" != 0 ]; then
    g -C "$check" checkout --quiet --force --detach "$base_sha"
    while IFS= read -r c; do
      rc=0; { echo "### fail-first on the BASE (must fail): $c"; confined nonet "$check" "$(expand "$c")" "$T"; } >> "${rdir}/checks.log" 2>&1 < /dev/null || rc=$?
      base_checks="$(jq -c --arg c "$c" --argjson x "$rc" '. + [{cmd: $c, exit: $x}]' <<< "$base_checks")"
      [ "$rc" != 0 ] || { ff_ok=false; ff_reasons="$(jq -c --arg c "$c" '. + ["fail-first: \($c) passes on the base; it must fail there"]' <<< "$ff_reasons")"; }
    done < <(pj '.checks.failFirst[]')
  fi
  g -C "$check" checkout --quiet --force --detach "$head_sha"
  g -C "$check" clean -fdxq -e .venv -e 'src/*/_version.py'
  local results='[]' all_pass=true
  while IFS= read -r c; do
    rc=0; { echo "### check (result, no network): $c"; confined nonet "$check" "$(expand "$c")" "$T"; } >> "${rdir}/checks.log" 2>&1 < /dev/null || rc=$?
    results="$(jq -c --arg c "$c" --argjson x "$rc" '. + [{cmd: $c, exit: $x, runs: 1, flaky: false}]' <<< "$results")"
    [ "$rc" = 0 ] || all_pass=false
    log "check: $( [ "$rc" = 0 ] && echo PASS || echo "FAIL (exit ${rc})" )  ${c}"
  done < <(pj '.checks.acceptance[]')
  local grading=null
  if [ "$(jq '.checks.failFirst | length' "$plan")" != 0 ]; then
    while IFS= read -r c; do
      rc="$(jq --arg c "$c" '[.[] | select(.cmd == $c) | .exit] | first // 1' <<< "$results")"
      ff_checks="$(jq -c --arg c "$c" --argjson x "$rc" '. + [{cmd: $c, exit: $x, runs: 1, flaky: false}]' <<< "$ff_checks")"
      [ "$rc" = 0 ] || { ff_ok=false; ff_reasons="$(jq -c --arg c "$c" '. + ["fail-first: \($c) fails on the result"]' <<< "$ff_reasons")"; }
    done < <(pj '.checks.failFirst[]')
    grading="$(jq -nc --argjson b "$base_checks" --argjson c "$ff_checks" --argjson ok "$ff_ok" --argjson r "$ff_reasons" \
      '{mode: "fail-first", caseId: null, patchApplied: false, baseChecks: $b, checks: $c, ok: $ok, reasons: $r}')"
    log "fail-first: base $(jq -r 'map("exit \(.exit)") | join(", ")' <<< "$base_checks"), result $(jq -r 'map("exit \(.exit)") | join(", ")' <<< "$ff_checks") -> $( [ "$ff_ok" = true ] && echo held || echo "did not hold")"
  fi

  # Facts, in the shape the router reads. Risk flags are recomputed by the router from the paths.
  local changed lines links bundle_sha=""
  changed="$(gw diff --name-only -z "$base_sha" HEAD | jq -R -s -c 'split("\u0000") | map(select(length > 0))')"
  lines="$(gw diff --numstat "$base_sha" HEAD | awk '{ a += ($1 == "-" ? 0 : $1); d += ($2 == "-" ? 0 : $2) } END { print a + d + 0 }')"
  links="$(gw diff --raw "$base_sha" HEAD | awk '$1 ~ /^:(120000|160000)$/ || $2 ~ /^(120000|160000)$/ { f = 1 } END { print (f ? "true" : "false") }')"
  if [ "$commits" != 0 ]; then
    gw bundle create --quiet "${rdir}/result.bundle" "${base_sha}..${branch}"
    bundle_sha="$(sha256sum "${rdir}/result.bundle" | cut -d' ' -f1)"
  fi
  gw diff "$base_sha" HEAD > "${rdir}/diff.patch"
  jq -n --arg t "$task_id" --argjson p "$changed" --argjson n "$lines" --argjson l "$links" --argjson c "$results" \
    --argjson ok "$all_pass" --arg h "$head_sha" --arg b "$base_sha" --arg bs "$bundle_sha" --argjson gr "$grading" \
    '{taskId: $t, changedPaths: $p, touchesCi: false, touchesInstructions: false, touchesManifests: false,
      touchesSecurityPaths: false, touchesLinks: $l, linesChanged: $n, checks: $c, allChecksPass: $ok,
      resultSha: $h, baseSha: $b, grading: $gr}
      + (if $bs == "" then {resultBundleVersionId: null, resultBundleETag: null}
         else {resultBundleVersionId: ("local-" + $t), resultBundleETag: ("\"" + $bs + "\"")} end)' > "${rdir}/facts.json"
  # shellcheck disable=SC2046
  python3 "${T}/harness/lib/plan.py" scope "$plan" $(jq -r '.[]' <<< "$changed") > "${rdir}/scope.json"
  log "diff: ${commits} commit(s), $(jq length <<< "$changed") file(s), ${lines} line(s); outside scope: $(jq -r '(.outside + .harness) | if length == 0 then "none" else join(", ") end' "${rdir}/scope.json")"

  # The adversarial reviewer: a different model, on the result, with edits denied.
  rm -f "${rdir}/verdict.json"
  if [ "$review" = 1 ] && [ "$commits" != 0 ]; then
    [ -e "${tdir}/review" ] && g -C "$REPO" worktree remove --force "${tdir}/review"
    g -C "$REPO" worktree add --quiet --detach "${tdir}/review" "$head_sha"
    settings "${tdir}/review" '["Edit", "Write", "NotebookEdit"]' 0 > "${tdir}/review-settings.json"
    cat > "${tdir}/review-prompt.md" <<PROMPT
You are the adversarial reviewer for a change another Claude session produced. The change is
checked out in this folder as commits on top of its base ${base_sha}. You did not write it.

The spec it was meant to satisfy, as a person approved it:

$(pj .body)

Facts computed outside that session (diff, checks in a fresh clone with no network, scope):

$(cat "${rdir}/facts.json")
$(cat "${rdir}/scope.json")

Argue against merging it. Read the diff (git diff ${base_sha} HEAD) and the files it touches.
You may run the tests: \`${tdir}/venv/bin/python -m pytest -q -p no:cacheprovider\` (that
environment has this exact result installed).
Look for behaviour the spec did not ask for, anything the spec asked for that is missing,
weakened or skipped tests, claims that read as correct but are not, changes outside the
spec's scope, and anything a maintainer of this project would push back on. Do not modify
files. Approve only if you cannot make a convincing case against it.

End your reply with one line that holds only this JSON object and nothing else:
{"verdict": "approve" or "reject", "reasons": ["short reason", "..."]}
PROMPT
    log "reviewer: $(pj .models.reviewer), edits denied, arguing against the change"
    claude_run "${tdir}/review" "${tdir}/review-settings.json" "${tdir}/review-prompt.md" "${rdir}/review-transcript.jsonl" \
      "$(pj .models.reviewer)" "$(caps review_max_turns)" "$(caps review_max_budget_usd)" || true
    local s verdict="" line cand result_text
    s="$(summary <(jq -c 'select(.type == "result")' "${rdir}/review-transcript.jsonl" | tail -1))"
    sessions="$(jq -c --argjson s "$(jq -c --argjson r "$round" '. + {round: $r, role: "reviewer"}' <<< "$s")" '. + [$s]' <<< "$sessions")"
    result_text="$(jq -r 'select(.type == "result") | .result // empty' "${rdir}/review-transcript.jsonl" 2>/dev/null | tail -c 200000)"
    while IFS= read -r line; do
      cand="$(jq -c 'select((.verdict == "approve" or .verdict == "reject") and (.reasons | type == "array"))
        | {verdict, reasons: [.reasons[] | tostring]}' <<< "$line" 2>/dev/null)" || continue
      [ -z "$cand" ] || verdict="$cand"
    done < <(printf '%s\n' "$result_text" | grep -E '^[[:space:]]*\{.*\}[[:space:]]*$' || true)
    [ -n "$verdict" ] || verdict='{"verdict":"reject","reasons":["the reviewer gave no parsable verdict"]}'
    printf '%s\n' "$verdict" > "${rdir}/verdict.json"
    g -C "$REPO" worktree remove --force "${tdir}/review" 2>/dev/null || true
    log "reviewer verdict: $(jq -r '"\(.verdict): \(.reasons | join("; "))"' <<< "$verdict" | cut -c1-300)"
  fi

  # The packet must exist before routing; the full packet is rewritten after the last round.
  jq -n --arg t "$task_id" '{v: 1, taskId: $t, partial: true}' > "${rdir}/packet.json"
  node --no-warnings "${T}/harness/lib/route.ts" "$rdir" "${T}/harness" "$pack_id" > /dev/null
  log "router: $(jq -r '"\(.path): \(.reasons | join("; "))"' "${rdir}/decision.json" | cut -c1-300)"
  # Each round's outcome stays in the packet, so a rejection and its retry are on the record.
  jq -nc --argjson r "$round" --argjson ok "$all_pass" --slurpfile d "${rdir}/decision.json" \
    --argjson v "$(cat "${rdir}/verdict.json" 2>/dev/null || echo null)" --slurpfile f "${rdir}/facts.json" \
    '{round: $r, allChecksPass: $ok, grading: $f[0].grading, changedPaths: $f[0].changedPaths, verdict: $v,
      path: $d[0].path, reasons: $d[0].reasons}' >> "${rdir}/rounds.jsonl"
  event "${tdir}/loops.jsonl" --arg loop check --argjson round "$round" --arg path "$(jq -r .path "${rdir}/decision.json")" \
    --argjson allChecksPass "$all_pass" --arg verdict "$(jq -r '.verdict // "none"' "${rdir}/verdict.json" 2>/dev/null || echo none)"
}

# The worker's first round, then retry rounds while the result is rejected (loop 3).
cp "${rdir}/prompt.md" "${tdir}/prompt-0.md"
run_worker 0
evaluate 0
round=0
needs_retry() {
  local p v sub
  p="$(jq -r .path "${rdir}/decision.json")"
  v="$(jq -r '.verdict // "none"' "${rdir}/verdict.json" 2>/dev/null || echo none)"
  sub="$(jq -r 'map(select(.role == "worker")) | last | .subtype // ""' <<< "$sessions")"
  # A session that ran out of budget is a halt with a reason, not something to resume.
  [ "$sub" != error_max_budget_usd ] || return 1
  [ "$p" = reject ] || [ "$v" = reject ]
}
while needs_retry && [ "$round" -lt "$(caps retries)" ]; do
  round=$((round + 1))
  sid="$(jq -r 'map(select(.role == "worker")) | last | .sessionId // empty' <<< "$sessions")"
  [ -n "$sid" ] || break
  {
    echo "The workbench checked your change and did not accept it. Findings, from processes outside your session:"
    echo
    jq -r '.reasons[] | "- router: \(.)"' "${rdir}/decision.json"
    [ -f "${rdir}/verdict.json" ] && jq -r '.reasons[] | "- reviewer: \(.)"' "${rdir}/verdict.json"
    jq -r '.checks[] | select(.exit != 0) | "- failing check (fresh clone, no network): \(.cmd)"' "${rdir}/facts.json"
    echo
    echo "Fix the causes within the spec's scope, then finish. Do not weaken or skip any check."
  } > "${tdir}/prompt-${round}.md"
  cp "${tdir}/prompt-${round}.md" "${rdir}/retry-${round}.md"
  log "loop 3 retry ${round} of $(caps retries): claude --resume ${sid} with the findings"
  event "${tdir}/loops.jsonl" --arg loop retry --argjson round "$round" --arg sessionId "$sid"
  echo 0 > "${tdir}/continuations"
  run_worker "$round" --resume "$sid"
  evaluate "$round"
done
ended_at="$(date -u +%FT%TZ)"

# ---- 4. Evidence packet, PR, ledger -----------------------------------------------------------
evidence_lines="$(find "${tdir}/evidence" -maxdepth 1 -type f -name '*.jsonl' -print0 | sort -z | xargs -0 -r cat | wc -l)"
find "${tdir}/evidence" -maxdepth 1 -type f -name '*.jsonl' -print0 | sort -z | xargs -0 -r cat > "${rdir}/pack-evidence.jsonl"
cp "${tdir}/loops.jsonl" "${rdir}/loops.jsonl"
jq -n --arg t "$task_id" --arg trial "$trial" --slurpfile plan "$plan" --slurpfile facts "${rdir}/facts.json" \
  --slurpfile scope "${rdir}/scope.json" --slurpfile decision "${rdir}/decision.json" \
  --argjson verdict "$(cat "${rdir}/verdict.json" 2>/dev/null || echo null)" --argjson sessions "$sessions" \
  --slurpfile loops "${rdir}/loops.jsonl" --arg v "$claude_version" --arg pack "$pack_id" --arg base "$base" \
  --arg s "$started_at" --arg e "$ended_at" --argjson ev "$evidence_lines" \
  --slurpfile rounds "${rdir}/rounds.jsonl" '
  ($plan[0]) as $p | ($facts[0]) as $f |
  {v: 1, taskId: $t, trial: (if $trial == "" then null else ($trial | tonumber) end),
   spec: {id: $p.id, title: $p.title, issue: $p.issue, class: $p.class, approvedBy: $p.approvedBy, scope: $p.scope},
   placement: "one machine: git worktree, native sandbox (bubblewrap), no microVM",
   claudeCodeVersion: $v, packId: $pack, models: $p.models, caps: $p.caps,
   startedAt: $s, endedAt: $e, baseBranch: $base, baseCommit: $f.baseSha, headCommit: $f.resultSha,
   changedPaths: $f.changedPaths, linesChanged: $f.linesChanged,
   checks: $f.checks, allChecksPass: $f.allChecksPass, grading: $f.grading, scope: $scope[0],
   review: $verdict, decision: $decision[0], rounds: $rounds,
   loops: {
     sessions: $sessions,
     finish: [$loops[] | select(.loop == "finish")],
     scopeDenials: [$loops[] | select(.loop == "scope")],
     retries: ([$loops[] | select(.loop == "retry")] | length)
   },
   costUsd: ([$sessions[].costUsd // 0] | add // 0),
   packEvidenceLines: $ev}' > "${rdir}/packet.json"
python3 "${T}/harness/lib/evidence.py" "$rdir" > "${rdir}/evidence.md"

path="$(jq -r .path "${rdir}/decision.json")"
pr=""
if [ "$publish" = 1 ] && [ "$path" != reject ]; then
  pr="$("${REPO}/harness/bin/publish.sh" "$rdir" "$branch")" || log "publish failed: the branch and packet are kept locally"
fi
event "${out}/ledger.jsonl" --arg taskId "$task_id" --arg spec "$(pj .id)" --arg class "$(pj .class)" --arg path "$path" \
  --argjson reasons "$(jq -c .reasons "${rdir}/decision.json")" --argjson costUsd "$(jq .costUsd "${rdir}/packet.json")" \
  --argjson retries "$(jq .loops.retries "${rdir}/packet.json")" --arg pr "$pr" --arg packId "$pack_id" --arg trial "$trial"
log "done: ${path}$( [ -n "$pr" ] && echo ", ${pr}" ), \$$(jq -r '.costUsd * 100 | round / 100' "${rdir}/packet.json") in total; packet ${rdir}/packet.json"
echo "task-id: ${task_id}"
