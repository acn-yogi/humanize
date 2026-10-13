#!/bin/bash
# shape.sh: phase 3, shaping. A documented intent in; a plan and draft specs with fail-first
# checks out, for a person to approve. The shaper writes no code: it plans the work and writes
# the checks that will prove the work was done. Nothing it produces runs until a person sets a
# spec to approved and commits it, so the human control sits exactly where it did before.
#
#   harness/bin/shape.sh intents/<id>.md [--base BRANCH] [--out DIR] [--no-copy]
#                        [--issue N --approved-by LOGIN]
#
#   --issue N --approved-by LOGIN   the ticket watch's headless intake: the intent came from the
#              fork's issue N and LOGIN's label on it is the approval. When the intake check
#              passes, the specs are stamped status = "approved", approved_by = LOGIN and
#              trigger = "ticket:N" so the normal dispatch path takes them; when it fails they
#              stay drafts, with the trigger, for a person to finish.
#
#   1 Intent   the intent and the whole harness come from the BASE commit; the phase must be 3
#   2 Shape    a git worktree for this run alone; headless Claude Code (claude -p) in dontAsk
#              mode under the settings template, the native sandbox and the pack, allowed to
#              write only specs/, harness/checks/ and plans/
#                loop 1 session   --max-turns and --max-budget-usd
#                loop 2 finish    the Stop hook runs the intake check and blocks a false finish
#   3 Intake   the intake check again, under bubblewrap with no network: valid draft specs, a
#              plan that names them, and every check failing on today's code; the scope check
#              on everything the session wrote; the dispatcher's forecast for the new specs
#   4 Hand-off the proposals are copied into the working tree, uncommitted, for a person
#
# Linux or WSL2 only. Exit 0 when the run completed, whatever the intake said; 2 when it could
# not start. The last line on stdout is "shape-id: <id>".
set -euo pipefail
umask 077

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=../lib/common.sh
. "${REPO}/harness/lib/common.sh"

intent="" base="" out="${REPO}/runs" copy=1 issue="" approved_by=""
while [ $# -gt 0 ]; do
  case "$1" in
    --base) base="${2:?}"; shift 2 ;;
    --out) out="${2:?}"; shift 2 ;;
    --no-copy) copy=0; shift ;;
    --issue) issue="${2:?}"; shift 2 ;;
    --approved-by) approved_by="${2:?}"; shift 2 ;;
    -*) die "unknown option: $1" ;;
    *) intent="$1"; shift ;;
  esac
done
[ -n "$intent" ] || die "usage: shape.sh intents/<id>.md [--base BRANCH] [--out DIR] [--no-copy] [--issue N --approved-by LOGIN]"
[ -z "$issue" ] || { [[ "$issue" =~ ^[0-9]+$ ]] && [ -n "$approved_by" ]; } || die "--issue takes the fork's issue number and needs --approved-by LOGIN (the login whose label approved it)"

"${REPO}/harness/bin/preflight.sh" --quiet || die "preflight failed: run harness/bin/preflight.sh for the details"
# shellcheck source=../lib/auth.sh
. "${REPO}/harness/lib/auth.sh"
load_auth

# ---- 1. Intent: from the base commit; the phase must allow shaping ---------------------------
[ -n "$base" ] || base="$(python3 -c 'import tomllib,sys;print(tomllib.load(open(sys.argv[1],"rb"))["github"]["base"])' "${REPO}/harness/config.toml")"
base_sha="$(g -C "$REPO" rev-parse --verify --quiet "${base}^{commit}")" || die "no branch ${base}"
intent_rel="intents/$(basename "$intent")"
g -C "$REPO" cat-file -e "${base_sha}:${intent_rel}" 2>/dev/null \
  || die "${intent_rel} is not committed on ${base}: the shaper reads documented intents from the base commit only"

id="s-$(date -u +%Y%m%dT%H%M%S)"
tdir="${WB_HOME}/${id}" work="${tdir}/work" T="${tdir}/trusted"
mkdir -p "$out"; out="$(cd "$out" && pwd)"; rdir="${out}/${id}"
[[ "$tdir" =~ ^/[A-Za-z0-9._/-]+$ ]] || die "WORKBENCH_HOME must be a plain absolute path"
mkdir -p "${tdir}/evidence" "${tdir}/claude-config" "$T" "$rdir" "${HOME}/.cache/uv"
echo "$base_sha" > "${tdir}/base_sha"
: > "${tdir}/loops.jsonl"
# Everything the operator sees is also the recording.
exec > >(tee -a "${rdir}/console.log") 2>&1

cleanup() {
  local rc=$?
  cp "${tdir}/loops.jsonl" "${rdir}/loops.jsonl" 2>/dev/null || true
  [ -e "$work" ] && { g -C "$REPO" worktree remove --force "$work" 2>/dev/null || rm -rf "$work"; }
  g -C "$REPO" worktree prune 2>/dev/null || true
  rm -rf "$tdir"
  exit "$rc"
}
trap cleanup EXIT

g -C "$REPO" archive "$base_sha" harness .claude specs intents | tar -x -C "$T"
plan="${tdir}/plan.json"
python3 "${T}/harness/lib/plan.py" plan "${T}/harness" "${T}/harness/shaping/0000-shape.md" > "$plan"
cp "$plan" "${rdir}/plan.json"
pj() { jq -r "$1" "$plan"; }
caps() { pj ".caps.$1"; }
[ "$(pj .phase)" -ge 3 ] || die "phase $(pj .phase) ($(pj .phaseName)): shaping needs phase 3. Set harness/config.toml [harness] phase = 3, or WORKBENCH_PHASE=3 for one run"
intent_id="$(python3 -c '
import re,sys,tomllib
t=open(sys.argv[1],encoding="utf-8").read(); m=re.match(r"\A\+\+\+\n(.*?)\n\+\+\+\n",t,re.S)
print(tomllib.loads(m.group(1))["id"] if m else "")' "${T}/${intent_rel}")"
[[ "$intent_id" =~ ^[0-9]{4}-[a-z0-9][a-z0-9-]+$ ]] && [ "$(basename "$intent" .md)" = "$intent_id" ] \
  || die "${intent_rel}: the front matter needs id = \"$(basename "$intent" .md)\""
intent_body="$(python3 -c '
import re,sys
t=open(sys.argv[1],encoding="utf-8").read(); m=re.match(r"\A\+\+\+\n.*?\n\+\+\+\n(.*)\Z",t,re.S); print(m.group(1).strip())' "${T}/${intent_rel}")"
pack_id="pack-$(cd "$T" && find harness/pack harness/hooks .claude/workbench -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-12)"
next_num="$(printf '%04d' "$(( $(ls "${T}/specs" | grep -oE '^[0-9]{4}' | sort -n | tail -1 | sed 's/^0*//') + 1 ))")"
classes="$(python3 -c 'import tomllib,sys;c=tomllib.load(open(sys.argv[1],"rb"))["classes"];print(", ".join(k + " (" + v["description"] + ")" for k,v in c.items() if k!="shaping"))' "${T}/harness/classes.toml")"

log "shape ${id}: intent ${intent_id} on ${base} at ${base_sha:0:12}, ${pack_id}, phase $(pj .phase) ($(pj .phaseName), from $(pj .phaseSource))"
event "${tdir}/loops.jsonl" --arg loop shape --arg event start --arg shapeId "$id" --arg intent "$intent_id" --arg packId "$pack_id"
started_at="$(date -u +%FT%TZ)"

# ---- 2. Shape: worktree, environment, settings, prompt, session ------------------------------
g -C "$REPO" worktree add --quiet --detach "$work" "$base_sha"
export WB_TRUSTED="$T" WB_VENV="${tdir}/venv" WB_SRC="$work" WB_BASE_SHA="$base_sha"
log "setup: the run's Python environment, from the base commit (the shaper runs the checks it writes)"
while IFS= read -r c; do
  { echo "### setup: $c"; confined net "$tdir" "$(expand "$c")"; } >> "${rdir}/setup.log" 2>&1 < /dev/null \
    || die "setup failed on the base commit: see ${rdir}/setup.log"
done < <(pj '.setup[]')
wb_settings "$T" "$tdir" "$plan" "$work" '[]' 1 > "${tdir}/settings.json"
cp "${tdir}/settings.json" "${rdir}/settings.json"
cp "${T}/${intent_rel}" "${rdir}/intent.md"

{ cat <<EOF
${intent_body}

## Your job: shape this intent, do not implement it

You are the shaping agent of a workbench harness. Turn the intent above into a plan and 2 or 3
specs. Separate workbench sessions will implement the specs later, one spec per session, each
ending in one pull request that a person reviews. You write no code in src/, tests/ or docs/:
a spec describes the work, and a check proves whether it was done.

Explore first: the function the intent names, its tests, the docs page, how the existing specs
under specs/ are written and how their checks under harness/checks/ work.

Produce exactly these files, nowhere else (edits anywhere else are refused):

1. plans/${intent_id}.md: the plan. In order: the intent restated in your own words; each
   design decision you made where the intent left you a choice, with the reason; the specs in
   the order they should run, one paragraph each saying what it delivers and why it stands on
   its own; what you left out and why; what a reviewer should look at hardest. 300 to 600 words.

2. specs/NNNN-<slug>.md, 2 or 3 of them, numbered from ${next_num} upward, in exactly the format
   of the example below: TOML front matter between +++ lines, then a Markdown body with the
   headings Intent, Constraints, Out of scope and Acceptance criteria. Rules:
   - status = "draft" and intent = "${intent_id}". A person approves a spec; you never do.
   - class is one of: ${classes}. A spec of class bugfix needs checks.fail_first.
   - scope lists only the files under src/, tests/ and docs/ (and mkdocs.yml) that the spec may
     change. Never harness/, specs/, intents/, plans/, .github/ or pyproject.toml.
   - checks.quick and checks.acceptance are commands of the form
     "python {harness}/checks/<name>.py", plus "python {harness}/checks/changed.py tests/<file>.py"
     where the spec asks for tests. Keep the literal text {harness}: the harness expands it.
   - caps: max_turns between 30 and 40, max_budget_usd between 1.5 and 3.0.

3. harness/checks/<name>.py, one per spec, in the style of the example below: a Python script
   that imports from humanize, exercises the behaviour the spec asks for with concrete cases,
   prints one FAIL line per problem or one PASS line, and exits 1 on any problem. Fail first:
   every check MUST fail on today's code, because the behaviour does not exist yet. Run each
   one yourself from the worktree root to confirm:
   \`${WB_VENV}/bin/python harness/checks/<name>.py\`. A check that passes today means the spec
   asks for nothing. Where a check needs a fixed "today", use freezegun (installed) or pass
   dates relative to datetime.date.today().

A decomposition that works here: one spec for the behaviour in src/ with its tests; one for the
user-facing documentation where that is separate work; optionally one for an edge case or
follow-up the intent calls out. Each spec must be a change a person can review in one sitting.

When you are done, say so in one line. A Stop hook then runs harness/checks/shape_output.py,
which validates the specs, confirms the plan names them and runs every check to confirm it fails
today. If anything is off you are told what and asked to continue.

## The spec format, by example: specs/0002-bugfix-precisedelta-sign.md

\`\`\`markdown
$(cat "${T}/specs/0002-bugfix-precisedelta-sign.md")
\`\`\`

## The check behind that spec: harness/checks/precisedelta_sign.py

\`\`\`python
$(cat "${T}/harness/checks/precisedelta_sign.py")
\`\`\`

## How this workbench works

- This git worktree is yours alone for this run: ${work}
- The Python environment is ready: \`${WB_VENV}/bin/python\` has humanize and its test extras
  installed. Run tests with \`${WB_VENV}/bin/python -m pytest -q -p no:cacheprovider\`. Do not
  install anything.
- Write only under: $(jq -r '.scope | join(", ")' "$plan"). Edits anywhere else are refused.
- Do not run git commit. The harness collects your files for a person to review.
EOF
} > "${rdir}/prompt.md"

claude_version="$(claude --version 2>/dev/null | head -1)"
model="$(pj '.models.shaper // .models.worker')"
log "loop 1 session: claude -p, model ${model}, caps $(caps max_turns) turns and \$$(caps max_budget_usd)"
rc=0
( cd "$work" && env CLAUDE_CONFIG_DIR="${tdir}/claude-config" \
    timeout --signal=TERM --kill-after=30 "$(caps time_limit_sec)" \
    claude -p --input-format text --permission-mode dontAsk --output-format stream-json --verbose \
      --model "$model" --max-turns "$(caps max_turns)" --max-budget-usd "$(caps max_budget_usd)" \
      --plugin-dir "${T}/harness/pack" --settings "${tdir}/settings.json" --setting-sources user --strict-mcp-config \
    < "${rdir}/prompt.md" >> "${rdir}/transcript.jsonl" 2>> "${rdir}/claude.stderr" ) || rc=$?
session="$(jq -sc '[.[] | select(.type == "result")] | last // {} | {sessionId: .session_id, subtype, isError: .is_error,
  turns: .num_turns, costUsd: (.total_cost_usd // 0), denials: ((.permission_denials // []) | length),
  result: ((.result // "") | .[0:600])}' "${rdir}/transcript.jsonl" 2>/dev/null || echo '{}')"
session="$(jq -c --argjson rc "$rc" '. + {role: "shaper", exit: $rc}' <<< "$session")"
event "${tdir}/loops.jsonl" --arg loop session --arg subtype "$(jq -r .subtype <<< "$session")" \
  --argjson turns "$(jq '.turns // 0' <<< "$session")" --argjson costUsd "$(jq '.costUsd // 0' <<< "$session")"
log "session ended: $(jq -r '"\(.subtype), \(.turns) turns, $\(.costUsd)"' <<< "$session")"

# ---- 3. Intake: what the session wrote, checked outside the session ---------------------------
gw() { g -C "$work" "$@"; }
changed="$(gw status --porcelain --untracked-files=all | cut -c4- | jq -R . | jq -sc 'map(select(length > 0))')"
# shellcheck disable=SC2046
python3 "${T}/harness/lib/plan.py" scope "$plan" $(jq -r '.[]' <<< "$changed") > "${rdir}/scope.json"
log "files: $(jq length <<< "$changed") written; outside scope: $(jq -r '(.outside + .harness) | if length == 0 then "none" else join(", ") end' "${rdir}/scope.json")"
jq -r '.[]' <<< "$changed" | sed 's/^/  /'
log "intake check: harness/checks/shape_output.py under bubblewrap, no network (the Stop hook ran the same)"
irc=0
{ confined nonet "$work" "python harness/checks/shape_output.py --intent ${intent_id}" "$T" "$WB_VENV"; } > "${rdir}/intake.txt" 2>&1 < /dev/null || irc=$?
grep -E '^(PASS|FAIL) ' "${rdir}/intake.txt" | sed 's/^/  /' || true
intake_json="$(grep -E '^\{' "${rdir}/intake.txt" | tail -1 || echo '{}')"
log "intake: $( [ "$irc" = 0 ] && echo "PASS, every line held" || echo "FAIL (exit ${irc}): a person reads the FAIL lines before approving anything")"
# The dispatcher's forecast for the new specs: drafts wait, so nothing here will run or spend.
log "forecast: what the queue would do with the proposals (nothing runs: they are drafts)"
python3 "${T}/harness/lib/plan.py" queue "${T}/harness" "${work}/specs" 2>/dev/null | node --no-warnings "${T}/harness/lib/preroute.ts" /dev/null \
  | jq -r --argjson ids "$(jq -c '.specs // []' <<< "$intake_json")" '.[] | select(.id as $i | $ids | index($i)) | "  \(.action | ascii_upcase)\t\(.id)\t\(.class)\t\(.forecast)"' \
  | column -t -s $'\t' | tee "${rdir}/forecast.txt" || true

# A ticket's intake: the approver's label is the approval, so specs that passed intake are
# stamped approved for the queue; specs that did not stay drafts. Both carry the trigger, so
# the ticket is never taken twice (one issue, one task) and the ledger can say what started it.
if [ -n "$issue" ]; then
  stamp_status="$( [ "$irc" = 0 ] && echo approved || echo draft )"
  # shellcheck disable=SC2046
  python3 - "$work" "$stamp_status" "$approved_by" "ticket:${issue}" "$(date -u +%FT%TZ)" $(jq -r '.specs[]?' <<< "$intake_json") <<'PY'
import re, sys
from pathlib import Path
work, status, who, trigger, at, *ids = sys.argv[1:]
for spec_id in ids:
    p = Path(work) / "specs" / f"{spec_id}.md"
    text = p.read_text(encoding="utf-8")
    m = re.match(r"\A\+\+\+\n(.*?)\n\+\+\+\n", text, re.S)
    if not m:
        continue
    front = re.sub(r"(?m)^(status|approved_by|trigger|triggered_at)\s*=.*\n?", "", m.group(1))
    front = front.rstrip("\n") + f'\nstatus = "{status}"\napproved_by = "{who}"\ntrigger = "{trigger}"\ntriggered_at = "{at}"\n'
    p.write_text("+++\n" + front + "+++\n" + text[m.end():], encoding="utf-8")
PY
  log "ticket #${issue}: $(jq -r '.specs | length' <<< "$intake_json") spec(s) stamped status = \"${stamp_status}\", approved_by = \"${approved_by}\", trigger = \"ticket:${issue}\"$( [ "$irc" = 0 ] || echo " (intake failed: drafts until a person finishes them)")"
fi

# ---- 4. Hand-off: proposals into the working tree, uncommitted; the record ---------------------
mkdir -p "${rdir}/proposals"
copied=0 skipped=()
while IFS= read -r p; do
  [ -n "$p" ] || continue
  mkdir -p "${rdir}/proposals/$(dirname "$p")" && cp "${work}/${p}" "${rdir}/proposals/${p}"
  if [ "$copy" = 1 ] && [ "$(jq -r '(.outside + .harness) | length' "${rdir}/scope.json")" = 0 ]; then
    if [ -e "${REPO}/${p}" ]; then skipped+=("$p"); else mkdir -p "${REPO}/$(dirname "$p")"; cp "${work}/${p}" "${REPO}/${p}"; copied=$((copied + 1)); fi
  fi
done < <(jq -r '.[]' <<< "$changed")
find "${tdir}/evidence" -maxdepth 1 -type f -name '*.jsonl' -print0 | sort -z | xargs -0 -r cat > "${rdir}/pack-evidence.jsonl"
cp "${tdir}/loops.jsonl" "${rdir}/loops.jsonl"
jq -n --arg id "$id" --arg intent "$intent_id" --argjson phase "$(pj .phase)" --arg phaseSource "$(pj .phaseSource)" \
  --arg model "$model" --arg v "$claude_version" --arg pack "$pack_id" --arg base "$base" --arg baseSha "$base_sha" \
  --arg s "$started_at" --arg e "$(date -u +%FT%TZ)" --argjson session "$session" --argjson changed "$changed" \
  --slurpfile scope "${rdir}/scope.json" --argjson intake "$intake_json" --argjson irc "$irc" --argjson copied "$copied" \
  --slurpfile loops "${rdir}/loops.jsonl" --arg trigger "${issue:+ticket:${issue}}" \
  '{v: 1, shapeId: $id, intent: $intent, trigger: (if $trigger == "" then null else $trigger end), phase: $phase, phaseSource: $phaseSource, model: $model, claudeCodeVersion: $v,
    packId: $pack, baseBranch: $base, baseCommit: $baseSha, startedAt: $s, endedAt: $e, session: $session,
    files: $changed, scope: $scope[0], intake: ($intake + {exit: $irc, ok: ($irc == 0)}),
    finish: [$loops[] | select(.loop == "finish")], scopeDenials: [$loops[] | select(.loop == "scope")],
    copiedIntoWorkingTree: $copied, costUsd: ($session.costUsd // 0)}' > "${rdir}/summary.json"
event "${out}/ledger.jsonl" --arg taskId "$id" --arg spec "$intent_id" --arg class shaping --arg path shape \
  --argjson reasons "$(jq -c '[.specs[]?] | map("draft spec " + .)' <<< "$intake_json")" \
  --argjson costUsd "$(jq '.costUsd // 0' <<< "$session")" --argjson retries 0 --arg pr "" --arg packId "$pack_id" --arg trial "" \
  --arg trigger "${issue:+ticket:${issue}}"
[ "${#skipped[@]}" = 0 ] || log "not copied (a file with that name already exists in the working tree): ${skipped[*]}"
log "done: $(jq -r '.specs | length' <<< "$intake_json") draft spec(s) for ${intent_id}, intake $( [ "$irc" = 0 ] && echo PASS || echo FAIL ), \$$(jq -r '(.costUsd // 0) * 100 | round / 100' <<< "$session"); ${copied} file(s) copied into the working tree, uncommitted. A person reviews them, sets status = \"approved\" on the specs they want, and commits."
echo "shape-id: ${id}"
