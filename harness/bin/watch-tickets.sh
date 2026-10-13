#!/bin/bash
# watch-tickets.sh: the ticket watch, one poll. Reads this fork's GitHub issues (never
# upstream), applies [triggers.ticket] (the label, the approvers, one issue one task) and, for
# each issue that qualifies, runs the intake headless on it: the issue becomes an intent on the
# base branch, shape.sh --issue turns it into specs, and the specs are approved with
# approved_by = the approver and trigger = "ticket:<number>", for the normal dispatch path to
# take. If intake says not ready, the specs stay drafts and, only when comment = true, the open
# questions go back on the issue as a comment.
#
#   harness/bin/watch-tickets.sh --dry-run [--json]    which issues would start work and why; nothing written
#   harness/bin/watch-tickets.sh [--quiet]             one live poll: intake and specs for every qualifying issue
#
# A dry run reads the fork even when [triggers.ticket] enabled = false, and says so. The live
# poll refuses while enabled = false or while the halt flag (runs/HALT) exists. The last line of
# a live poll is "started N" (tasks written to the queue). Exit 0 unless GitHub is unreachable.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=../lib/common.sh
. "${REPO}/harness/lib/common.sh"
dry=0 json=0 quiet=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry=1; shift ;;
    --json) json=1; shift ;;
    --quiet) quiet=1; shift ;;
    -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
H="${REPO}/harness"
ledger="${REPO}/runs/ledger.jsonl"
HALT="${WORKBENCH_HALT:-${REPO}/runs/HALT}"
if command -v gh >/dev/null; then GH=gh; elif command -v gh.exe >/dev/null; then GH=gh.exe; else die "no gh: the ticket watch reads the fork's issues with gh"; fi
cfg() { python3 -c 'import tomllib,sys,json
d=tomllib.load(open(sys.argv[1],"rb"))
for k in sys.argv[2].split("."): d=d[k]
print(json.dumps(d) if isinstance(d,(dict,list,bool)) else d)' "${H}/config.toml" "$1"; }
say() { [ "$quiet" = 1 ] && [ "$json" = 0 ] && return 0; echo "$@"; }

fork="$(cfg github.repo)"
upstream="$(cfg github.upstream)"
[ "$fork" != "$upstream" ] || die "[github] repo is the upstream repository; the ticket watch reads the fork only"
enabled="$(cfg triggers.ticket.enabled)"
label="$(cfg triggers.ticket.label)"
approvers="$(cfg triggers.ticket.approvers | jq -r 'join(", ")')"
comment="$(cfg triggers.ticket.comment)"
if [ "$dry" = 0 ]; then
  [ "$enabled" = true ] || die "[triggers.ticket] enabled = false: set it to true for a live poll (--dry-run reads anyway)"
  [ ! -e "$HALT" ] || { log "halted: ${HALT} exists; the ticket watch starts nothing"; echo "started 0"; exit 0; }
fi

# ---- Read the fork ----------------------------------------------------------------------------
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "${tmp}/timelines"
"$GH" api "repos/${fork}/issues?state=open&per_page=100" > "${tmp}/issues.json" \
  || die "gh api repos/${fork}/issues failed: is gh signed in, and are issues enabled on the fork?"
# Timelines only for the open issues that carry the label: that is where the approver is read.
while IFS= read -r n; do
  "$GH" api --paginate "repos/${fork}/issues/${n}/timeline" | jq -s 'add // []' > "${tmp}/timelines/${n}.json" \
    || log "timeline of #${n} unreadable; it will be skipped"
done < <(jq -r --arg l "$label" '.[] | select(.pull_request == null and (.labels | map(.name) | index($l) != null)) | .number' "${tmp}/issues.json")
rows="$(python3 "${H}/lib/tickets.py" evaluate "$H" "${REPO}/specs" "$ledger" --issues "${tmp}/issues.json" --timelines "${tmp}/timelines")"

# ---- Report ------------------------------------------------------------------------------------
n_issues="$(jq '[.[] | select(.pull_request == null)] | length' "${tmp}/issues.json")"
n_prs="$(jq '[.[] | select(.pull_request != null)] | length' "${tmp}/issues.json")"
if [ "$json" = 1 ]; then
  jq -c --arg fork "$fork" --arg label "$label" --arg approvers "$approvers" --argjson enabled "$enabled" --argjson comment "$comment" --argjson dry "$dry" \
     --argjson issues "$n_issues" --argjson prs "$n_prs" \
     '{fork: $fork, label: $label, approvers: $approvers, enabled: $enabled, comment: $comment, dryRun: ($dry == 1), openIssues: $issues, pullRequestsSkipped: $prs,
       rows: [.[] | select(.reason != "a pull request, not a ticket")], wouldStart: [.[] | select(.action == "start") | .number]}' <<< "$rows"
else
  say "ticket watch: ${fork} open issues with label ${label}; approvers: ${approvers:-none listed}; comment on not-ready: ${comment}; [triggers.ticket] enabled = ${enabled}$( [ "$dry" = 1 ] && echo " (dry run: reads the fork, writes nothing, posts nothing)")"
  say "read ${n_issues} open issue(s) from ${fork}; ${n_prs} pull request(s) in the same list skipped (not tickets)"
  jq -r '.[] | select(.reason != "a pull request, not a ticket") | "  \(.action | ascii_upcase)\t#\(.number)\t\(.title | .[0:60])\t\(.reason)"' <<< "$rows" | column -t -s $'\t'
fi
starts="$(jq -r '.[] | select(.action == "start") | .number' <<< "$rows")"
count="$(printf '%s\n' "$starts" | grep -c . || true)"
if [ "$dry" = 1 ]; then
  [ "$json" = 1 ] || say "would start ${count} task(s)$( [ "$count" -gt 0 ] && echo ": intake runs headless on each issue (shape.sh --issue), the spec is approved by the login that set the label, trigger ticket:<number>")"
  exit 0
fi

# ---- Intake, live: issue -> intent -> shape.sh --issue -> approved specs on the base branch ---
base="$(cfg github.base)"
[ "$(g -C "$REPO" rev-parse --abbrev-ref HEAD)" = "$base" ] || die "the working tree must be on ${base}: the intake commits the intent and the specs there for the queue to read"
started=0
for n in $starts; do
  row="$(jq -c --argjson n "$n" '.[] | select(.number == $n)' <<< "$rows")"
  approver="$(jq -r .approver <<< "$row")"
  issue_json="$(jq -c --argjson n "$n" '.[] | select(.number == $n)' "${tmp}/issues.json")"
  intent_id="$(python3 - "$REPO" "$fork" "$n" "$approver" <<'PY' <<< "$issue_json"
import datetime as dt, json, re, sys
from pathlib import Path
repo, fork, n, approver = sys.argv[1:5]
issue = json.load(sys.stdin)
intents = Path(repo) / "intents"; intents.mkdir(exist_ok=True)
title = (issue.get("title") or f"issue #{n}").strip()
words = re.findall(r"[a-z0-9]+", title.lower())
slug = ("ticket-" + n + "-" + "-".join(words[:4]))[:50].strip("-")
num = max([1] + [int(p.name[:4]) + 1 for p in intents.glob("[0-9][0-9][0-9][0-9]-*.md")])
intent_id = f"{num:04d}-{slug}"
body = (issue.get("body") or "").strip()
excerpt = ("\n\nFrom the ticket:\n\n> " + "\n> ".join(body[:1500].splitlines())) if body else ""
today = dt.date.today().isoformat()
text = f'''+++
id = "{intent_id}"
title = "{title.replace('"', "'")[:100]}"
issue = "{fork}#{n}"
status = "documented"
documented_by = "{approver}"
documented_at = "{today}"
trigger = "ticket:{n}"
captured = "ticket watch: the issue is the ask, the approver's label is the approval; constraints and out of scope are the harness defaults"
+++

# {title[:100]}

Ticket: https://github.com/{fork}/issues/{n}, labelled for the harness by {approver}.

## What

{title}{excerpt}

## Why

A person with approval rights set the ticket's label, which is this harness's approval. The
shaper turns the ticket into a plan and specs whose checks fail on today's code, so what the
ticket asks for and what the harness will verify are the same thing.

## Constraints

- Opt in where behaviour changes: every existing call returns exactly what it returns today,
  and the existing tests pass unchanged.
- One public function per spec where possible; a new option is a keyword argument, not a new
  function.
- Follow the file's existing style: Google-style docstrings with an example, the parametrized
  test style of the matching `tests/test_*.py`.
- The whole suite stays green; `ruff` and `mypy --strict` stay clean.

## Out of scope

- Any function the ticket does not name, and anything under `.github/`, `pyproject.toml` or the
  harness.
- Changing existing wording or defaults.
'''
(intents / f"{intent_id}.md").write_text(text, encoding="utf-8")
print(intent_id)
PY
)"
  g -C "$REPO" add -- "intents/${intent_id}.md"
  g -C "$REPO" commit --quiet --no-verify -m "ticket watch: intent ${intent_id} from ${fork}#${n} (approved by ${approver})" -- "intents/${intent_id}.md"
  log "ticket #${n}: intent intents/${intent_id}.md committed on ${base}; shaping (WORKBENCH_PHASE=3 for this one command)"
  out="$(WORKBENCH_PHASE=3 "${REPO}/harness/bin/shape.sh" "intents/${intent_id}.md" --issue "$n" --approved-by "$approver" 2>&1 | tee /dev/stderr)" || true
  shape_id="$(grep -oE '^shape-id: \S+' <<< "$out" | awk '{print $2}' || true)"
  summary="${REPO}/runs/${shape_id}/summary.json"
  if [ -z "$shape_id" ] || [ ! -f "$summary" ]; then log "ticket #${n}: the shaper did not finish; nothing queued"; continue; fi
  files="$(jq -r '.files[]' "$summary")"
  # shellcheck disable=SC2086
  [ -z "$files" ] || { g -C "$REPO" add -- $files && g -C "$REPO" commit --quiet --no-verify -m "ticket watch: $(jq -r '.intake.specs | length' "$summary") spec(s) shaped from ${fork}#${n}, trigger ticket:${n}" -- $files; }
  if [ "$(jq -r .intake.ok "$summary")" = true ]; then
    started=$((started + 1))
    log "ticket #${n}: $(jq -r '.intake.specs | join(", ")' "$summary") approved by ${approver} (trigger ticket:${n}), committed on ${base}; the next queue wake-up runs them"
  else
    log "ticket #${n}: intake not ready; the specs stay drafts (trigger ticket:${n})"
    if [ "$comment" = true ]; then
      body="$(printf 'The harness read this ticket (set by @%s) and shaped it, but its intake check found open questions before any work can start:\n\n```\n%s\n```\n\nA person edits the draft specs (`specs/`, trigger `ticket:%s`) or answers here; the next poll does not start work on this ticket until the specs are approved.' "$approver" "$(grep -E '^FAIL' "${REPO}/runs/${shape_id}/intake.txt" | head -20)" "$n")"
      "$GH" api -X POST "repos/${fork}/issues/${n}/comments" -f body="$body" >/dev/null && log "ticket #${n}: open questions posted as a comment on the fork's issue" || log "ticket #${n}: could not post the comment"
    fi
  fi
done
echo "started ${started}"
