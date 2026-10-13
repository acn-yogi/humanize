#!/bin/bash
# The guardrail probe's shell half. Claude runs this with its Bash tool, so every line below
# runs inside Claude Code's native sandbox, exactly as Claude's own commands do. Each line
# prints what the sandbox allowed; guardrails.sh compares it with what should happen.
#
#   probe.sh <worktree> [decoy file]
cd "$(dirname "$0")/../.." 2>/dev/null || true
work="${1:-$PWD}"
decoy="${2:-${HOME}/.demo-decoy/token.txt}"
say() { printf 'PROBE %-18s %s\n' "$1" "$2"; }
fetch() {  # fetch <url> <seconds>: "reached <host> (HTTP n)" or "blocked (curl exit n, HTTP n)"
  local code rc host
  host="$(sed -E 's#^https?://([^/]+).*#\1#' <<< "$1")"
  code="$(curl -sS -m "$2" -o /dev/null -w '%{http_code}' "$1" 2>/dev/null)"; rc=$?
  if [ "$rc" = 0 ] && [ "$code" != 000 ]; then echo "reached ${host} (HTTP ${code})"; else echo "blocked (curl exit ${rc}, HTTP ${code:-none})"; fi
}

# Network allowlist: a host off the list, an allowed host, and a host the repository's own
# .claude/settings.json allows (api.github.com). The last one proves the repository's settings
# never loaded: the session runs with --setting-sources user and the managed settings file.
say net-other "$(fetch https://example.com 8)"
say net-pypi "$(fetch https://pypi.org/simple/humanize/ 15)"
say net-repo-settings "$(fetch https://api.github.com 8)"

# Credentials: the model token, any token-like variable, the person's credential files, the decoy.
if [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}${ANTHROPIC_API_KEY:-}${ANTHROPIC_AUTH_TOKEN:-}" ]; then
  say token "VISIBLE to shell commands"
else
  say token "hidden from shell commands"
fi
n="$(env | grep -iEc '^[^=]*(token|api_key|secret|password|gh_)[^=]*=' || true)"
if [ "${n:-0}" = 0 ]; then say env-tokens "none: env | grep -i token finds nothing"; else say env-tokens "VISIBLE: ${n} token-like variable(s): $(env | grep -iE '^[^=]*(token|api_key|secret|password|gh_)[^=]*=' | cut -d= -f1 | paste -sd, -)"; fi

found=0
for f in /mnt/*/Users/*/.claude/.credentials.json "${HOME}/.claude/.credentials.json" "${HOME}/.ssh/id_ed25519" "${HOME}/.ssh/id_rsa"; do
  [ -e "$f" ] || continue
  found=1
  if head -c 1 "$f" >/dev/null 2>&1; then say credentials "READ ${f}"; else say credentials "denied ${f}"; fi
done
[ "$found" = 1 ] || say credentials "denied (no credential file is even visible)"

if [ -e "$decoy" ]; then
  if head -c 1 "$decoy" >/dev/null 2>&1; then say decoy "READ ${decoy}"; else say decoy "denied ${decoy}"; fi
else
  say decoy "denied (${decoy} is not even visible)"
fi

# Filesystem: writes outside the worktree, and inside it.
if touch "${HOME}/wb-probe-bash.txt" 2>/dev/null; then say write-outside "WROTE ${HOME}/wb-probe-bash.txt"; else say write-outside "denied ${HOME}/wb-probe-bash.txt"; fi
mkdir -p "${work}/probe" 2>/dev/null
if touch "${work}/probe/bash-inside.txt" 2>/dev/null; then say write-inside "allowed in the worktree"; else say write-inside "DENIED in the worktree"; fi

# Upstream and main: the push URL for upstream is disabled in git itself; a push to the fork's
# main from inside the session has no route (github.com is off the list) and no token.
out="$(cd "$work" && git push upstream HEAD:main 2>&1)"; rc=$?
[ "$rc" = 0 ] && say push-upstream "PUSHED to upstream" || say push-upstream "refused (git exit ${rc}): $(tail -1 <<< "$out" | cut -c1-120)"
out="$(cd "$work" && GIT_TERMINAL_PROMPT=0 timeout 20 git push origin HEAD:main 2>&1)"; rc=$?
[ "$rc" = 0 ] && say push-main "PUSHED to main" || say push-main "refused (git exit ${rc}): $(grep -v '^$' <<< "$out" | tail -1 | cut -c1-120)"
