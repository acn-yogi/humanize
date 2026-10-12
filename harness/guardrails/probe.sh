#!/bin/bash
# The guardrail probe's shell half. Claude runs this with its Bash tool, so every line below
# runs inside Claude Code's native sandbox, exactly as Claude's own commands do. Each line
# prints what the sandbox allowed; guardrails.sh compares it with what should happen.
cd "$(dirname "$0")/../.." 2>/dev/null || true
work="${1:-$PWD}"
say() { printf 'PROBE %-18s %s\n' "$1" "$2"; }

code="$(curl -sS -m 8 -o /dev/null -w '%{http_code}' https://example.com 2>/dev/null)"; rc=$?
say net-other "$( [ "$rc" = 0 ] && [ "$code" = 200 ] && echo "reached example.com (HTTP ${code})" || echo "blocked (curl exit ${rc}, HTTP ${code:-none})")"

code="$(curl -sS -m 15 -o /dev/null -w '%{http_code}' https://pypi.org/simple/humanize/ 2>/dev/null)"; rc=$?
say net-pypi "$( [ "$rc" = 0 ] && [ "$code" = 200 ] && echo "reached pypi.org (HTTP ${code})" || echo "blocked (curl exit ${rc}, HTTP ${code:-none})")"

if [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}${ANTHROPIC_API_KEY:-}${ANTHROPIC_AUTH_TOKEN:-}" ]; then
  say token "VISIBLE to shell commands"
else
  say token "hidden from shell commands"
fi

found=0
for f in /mnt/*/Users/*/.claude/.credentials.json "${HOME}/.claude/.credentials.json" "${HOME}/.ssh/id_ed25519" "${HOME}/.ssh/id_rsa"; do
  [ -e "$f" ] || continue
  found=1
  if head -c 1 "$f" >/dev/null 2>&1; then say credentials "READ ${f}"; else say credentials "denied ${f}"; fi
done
[ "$found" = 1 ] || say credentials "denied (no credential file is even visible)"

if touch "${HOME}/wb-probe-bash.txt" 2>/dev/null; then say write-outside "WROTE ${HOME}/wb-probe-bash.txt"; else say write-outside "denied ${HOME}/wb-probe-bash.txt"; fi
mkdir -p "${work}/probe" 2>/dev/null
if touch "${work}/probe/bash-inside.txt" 2>/dev/null; then say write-inside "allowed in the worktree"; else say write-inside "DENIED in the worktree"; fi
