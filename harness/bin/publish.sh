#!/bin/bash
# publish.sh: push one task's branch to the fork and open a PR with the evidence packet as its
# body. The approval path decides the labels, and a graduated class with auto_merge merges by
# policy. Prints the PR URL.
#
#   harness/bin/publish.sh <task run dir> <branch>
#
# Only ever the fork named in harness/config.toml. It refuses the upstream repository, any
# repository that is not a fork of it, and any branch that is not workbench/<task id>. Never
# forces. In WSL it uses git.exe and gh.exe, so the Windows credentials stay on Windows and
# are never visible inside Linux, where Claude works.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=../lib/common.sh
. "${REPO}/harness/lib/common.sh"

rdir="${1:?task run dir}" branch="${2:?branch}"
[[ "$branch" =~ ^workbench/t-[0-9A-HJKMNP-TV-Z]{26}$ ]] || die "publish: not a workbench branch: ${branch}"
plan="${rdir}/plan.json"
fork="$(jq -r .github.repo "$plan")"
upstream="$(jq -r .github.upstream "$plan")"
basebr="$(jq -r .github.base "$plan")"

if command -v gh >/dev/null; then GH=(gh); GIT=(git -C "$REPO"); winpath() { printf '%s' "$1"; }
elif command -v gh.exe >/dev/null; then GH=(gh.exe); GIT=(git.exe -C "$(wslpath -w "$REPO")"); winpath() { wslpath -w "$1"; }
else die "publish: no gh"; fi

# The fork guard: never the upstream, only a fork whose parent is the upstream.
[ "$fork" != "$upstream" ] || die "publish: refusing to publish to the upstream repository ${upstream}"
parent="$("${GH[@]}" repo view "$fork" --json parent --jq '.parent.owner.login + "/" + .parent.name' | tr -d '\r')"
[ "$parent" = "$upstream" ] || die "publish: ${fork} is not a fork of ${upstream} (parent: ${parent:-none})"

d="${rdir}/decision.json"
path="$(jq -r .path "$d")" cls="$(jq -r .className "$d")"
labels=(workbench "class:${cls}" "route:${path}")
case "$path" in
  per_pr) labels+=(needs-human) ;;
  batch_plan) labels+=("batch:$(jq -r .batchPlanId "$plan")") ;;
esac
for l in "${labels[@]}"; do "${GH[@]}" label create "$l" --repo "$fork" --force --color 5319e7 >/dev/null 2>&1 || true; done

push_out="$("${GIT[@]}" push --quiet origin "refs/heads/${branch}:refs/heads/${branch}" 2>&1)" \
  || { printf '%s\n' "$push_out" >&2; die "publish: push failed"; }
title="[workbench] $(jq -r .title "$plan")"
label_args=(); for l in "${labels[@]}"; do label_args+=(--label "$l"); done
url="$("${GH[@]}" pr create --repo "$fork" --base "$basebr" --head "$branch" --title "$title" \
  --body-file "$(winpath "${rdir}/evidence.md")" "${label_args[@]}" | tr -d '\r' | tail -1)"
echo "$url" > "${rdir}/pr.txt"

if [ "$path" = graduated ] && [ "$(jq -r '.classRow.auto_merge // false' "$plan")" = true ]; then
  "${GH[@]}" pr merge "$url" --repo "$fork" --squash --delete-branch >/dev/null
  log "merged by policy: class ${cls} is graduated"
fi
echo "$url"
