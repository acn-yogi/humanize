#!/bin/bash
# Model credentials for a workbench run, in order of preference:
#
#   ANTHROPIC_API_KEY          a Console key with its own workspace spend limit (the hard cap)
#   CLAUDE_CODE_OAUTH_TOKEN    a long-lived token from `claude setup-token`
#   WORKBENCH_AUTH=windows-login
#                              in WSL only: the access token of the person's Claude Code login
#                              on Windows, read at run time into this process's environment.
#                              Never written to disk, never refreshed from here (so the Windows
#                              login is untouched), and hidden from every shell command by the
#                              sandbox's credentials.envVars rule.
#
# Whatever the source, the session sees it only as an environment variable that the sandbox
# denies to shell commands, and the checks run with a clean environment (env -i).

load_auth() {
  if [ -n "${ANTHROPIC_API_KEY:-}" ]; then WB_AUTH="ANTHROPIC_API_KEY from the environment"; return 0; fi
  if [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then WB_AUTH="CLAUDE_CODE_OAUTH_TOKEN from the environment"; return 0; fi
  if [ "${WORKBENCH_AUTH:-}" = windows-login ]; then
    local profile file left
    profile="$(cmd.exe /c 'echo %USERPROFILE%' 2>/dev/null | tr -d '\r')"
    [ -n "$profile" ] || die "WORKBENCH_AUTH=windows-login needs WSL interop (cmd.exe) to find the Windows profile"
    file="$(wslpath -u "$profile")/.claude/.credentials.json"
    [ -r "$file" ] || die "no Claude Code login on Windows at ${file}"
    left="$(python3 -c 'import json,sys,time;d=json.load(open(sys.argv[1]))["claudeAiOauth"];print(int(d.get("expiresAt",0)/1000-time.time())//60)' "$file")"
    [ "$left" -gt 10 ] || die "the Windows Claude Code login token expires in ${left} min: use Claude Code on Windows once so it refreshes, then rerun"
    CLAUDE_CODE_OAUTH_TOKEN="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["claudeAiOauth"]["accessToken"])' "$file")"
    export CLAUDE_CODE_OAUTH_TOKEN
    WB_AUTH="the Windows Claude Code login, read at run time (${left} min left)"
    return 0
  fi
  die "no model credentials: set ANTHROPIC_API_KEY, or CLAUDE_CODE_OAUTH_TOKEN (from claude setup-token), or in WSL WORKBENCH_AUTH=windows-login"
}
