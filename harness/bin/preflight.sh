#!/bin/bash
# preflight.sh: what this machine has, and what the demo can and cannot do on it.
#
#   harness/bin/preflight.sh [--quiet]
#
# Exit 0 when a workbench can run here; 1 with each missing piece named when it cannot.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=../lib/common.sh
. "${REPO}/harness/lib/common.sh"
quiet=0; [ "${1:-}" = --quiet ] && quiet=1
bad=0
ok()   { [ "$quiet" = 1 ] || printf '  ok    %-22s %s\n' "$1" "$2"; }
miss() { printf '  MISS  %-22s %s\n' "$1" "$2" >&2; bad=1; }
note() { [ "$quiet" = 1 ] || printf '  note  %-22s %s\n' "$1" "$2"; }

[ "$quiet" = 1 ] || echo "workbench preflight: $(uname -sr)"
if [ "$(uname -s)" != Linux ]; then
  miss platform "the native sandbox needs Linux or WSL2 (bubblewrap); on Windows run this inside WSL2"
  exit 1
fi
grep -qi microsoft /proc/version 2>/dev/null && ok platform "WSL2" || ok platform "Linux"

for t in claude git jq bwrap socat timeout uv python3 node; do
  p="$(command -v "$t" 2>/dev/null || true)"
  case "$t:$p" in
    *:) miss "$t" "not installed in this Linux" ;;
    claude:/mnt/*) miss claude "resolves to a Windows install (${p}); install Claude Code inside this Linux" ;;
    *) ok "$t" "$p" ;;
  esac
done
command -v claude >/dev/null && ok "claude version" "$(claude --version 2>/dev/null | head -1)"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null && ok "python >= 3.11" "$(python3 --version)" || miss "python >= 3.11" "tomllib is needed"
node -e 'process.exit(Number(process.versions.node.split(".")[0]) < 22 ? 1 : 0)' 2>/dev/null && ok "node >= 22" "$(node --version) (runs the router's TypeScript directly)" || miss "node >= 22" "needed for type stripping"
if command -v bwrap >/dev/null && bwrap --ro-bind / / --unshare-net --unshare-pid -- true 2>/dev/null; then
  ok "bubblewrap namespaces" "unprivileged user namespaces work"
else
  miss "bubblewrap namespaces" "bwrap cannot create namespaces (unprivileged user namespaces must be on)"
fi

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then ok "model credentials" "ANTHROPIC_API_KEY"
elif [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then ok "model credentials" "CLAUDE_CODE_OAUTH_TOKEN"
elif [ "${WORKBENCH_AUTH:-}" = windows-login ]; then ok "model credentials" "the Windows Claude Code login (WORKBENCH_AUTH=windows-login)"
else miss "model credentials" "set ANTHROPIC_API_KEY, CLAUDE_CODE_OAUTH_TOKEN, or WORKBENCH_AUTH=windows-login (WSL)"
fi

# Publishing is optional: without it a run ends with the packet and branch on this machine.
if command -v gh >/dev/null; then ok "publish (gh)" "$(command -v gh)"
elif command -v gh.exe >/dev/null; then ok "publish (gh)" "gh.exe through WSL interop; git.exe pushes with the Windows credentials"
else note "publish (gh)" "no gh: runs end with a local packet and branch, no PR"
fi
[ "$quiet" = 1 ] || {
  echo "  note  placement              one machine: a git worktree per task, the native sandbox, no microVM."
  echo "                               Attended use, or unattended on code we own (this fork)."
}
exit "$bad"
