#!/bin/bash
# approve-batch.sh: per-batch approval for mechanical classes. Lists the open PRs that joined
# a batch, one line of evidence each, and with --merge a person approves the whole batch with
# one command. Each PR already passed its own checks and its own adversarial review.
#
#   harness/bin/approve-batch.sh docs-2026-10 [--merge]
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
batch="${1:?batch id}" merge=0
[ "${2:-}" = --merge ] && merge=1
fork="$(python3 -c 'import tomllib,sys;print(tomllib.load(open(sys.argv[1],"rb"))["github"]["repo"])' "${REPO}/harness/config.toml")"
if command -v gh >/dev/null; then GH=gh; else GH=gh.exe; fi
prs="$("$GH" pr list --repo "$fork" --label "batch:${batch}" --state open --json number,title,url,headRefName | tr -d '\r')"
n="$(jq length <<< "$prs")"
echo "batch ${batch} on ${fork}: ${n} open PR(s)"
jq -r '.[] | "  #\(.number)  \(.title)\n        \(.url)"' <<< "$prs"
[ "$n" -gt 0 ] || exit 0
if [ "$merge" = 1 ]; then
  for num in $(jq -r '.[].number' <<< "$prs"); do
    "$GH" pr merge "$num" --repo "$fork" --squash --delete-branch >/dev/null && echo "  merged #${num}"
  done
  echo "batch ${batch}: one approval, ${n} merge(s)"
else
  echo "approve the whole batch: harness/bin/approve-batch.sh ${batch} --merge"
fi
