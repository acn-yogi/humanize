#!/bin/bash
# Shared by the workbench scripts and hooks. Adapted from the workbench-sandbox local mode
# (scripts/local/workbench-local.sh), which this demo copies rather than calls.

WB_HOME="${WORKBENCH_HOME:-${HOME}/.workbench-demo}"
PATH="${HOME}/.local/bin:${PATH}"

log() { printf '%s %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
die() { printf 'workbench: %s\n' "$*" >&2; exit 2; }

# Every git command: no hooks, no fsmonitor, and the Windows-side checkout is trusted, so
# nothing the agent left in a worktree runs and WSL git does not refuse /mnt/c.
g() { git -c core.hooksPath=/dev/null -c core.fsmonitor=false -c core.untrackedCache=false -c safe.directory='*' "$@"; }

# Credential folders: denied to Claude Code's file tools, hidden from every shell command the
# harness runs (setup, checks, the Stop hook's checks), and listed in the sandbox's denyRead.
wb_secrets() {
  local p prof
  {
    # .demo-decoy holds the demo's decoy secret (demo/run-demo.sh plants it). It stands in for a
    # real secret file, so it is hidden exactly like one.
    for p in .ssh .aws .config/gcloud .config/gh .config/hub .config/git/credentials .azure .kube .docker .gnupg       .git-credentials .netrc .npmrc .pypirc .claude .local/share/keyrings .terraform.d .vault-token       .cargo/credentials .cargo/credentials.toml .m2/settings.xml .gradle/gradle.properties .demo-decoy; do
      [ -e "${HOME}/${p}" ] && realpath -e "${HOME}/${p}"
    done
    # In WSL the Windows profiles are mounted too, with the Windows Claude login and gh token.
    # Junctions such as "Default User" resolve to a real profile, listed once.
    if grep -qi microsoft /proc/version 2>/dev/null; then
      for prof in /mnt/*/Users/*/; do
        [ -L "${prof%/}" ] && continue
        for p in .ssh .aws .azure .kube .docker .gnupg .config .claude .git-credentials .netrc .npmrc AppData; do
          [ -e "${prof%/}/${p}" ] && realpath -e "${prof%/}/${p}"
        done
      done
    fi
  } 2>/dev/null | sort -u
  return 0
}

# confined <net|nonet> <writable dir> <command> [read-only dir]...
# bash -c <command> in <writable dir> under bubblewrap: root read-only, credential folders and
# the workbench home hidden, the one writable dir, its own PID namespace, no network unless
# "net", a clean environment, and a timeout. Extra read-only dirs (the task's trusted harness
# copy, its virtualenv) are put back on top of the hidden workbench home.
confined() {
  local mode="$1" dir="$2" cmd="$3"; shift 3
  local s args=(--ro-bind / / --dev /dev --proc /proc --tmpfs /tmp --unshare-pid --unshare-ipc --unshare-uts
                --die-with-parent --new-session)
  [ "$mode" = net ] || args+=(--unshare-net)
  while IFS= read -r s; do
    [ -n "$s" ] || continue
    if [ -d "$s" ]; then args+=(--tmpfs "$s"); else args+=(--ro-bind /dev/null "$s"); fi
  done < <(wb_secrets)
  args+=(--tmpfs "$WB_HOME")
  for s in "$@"; do [ -e "$s" ] && args+=(--ro-bind "$s" "$s"); done
  [ "$mode" != net ] || args+=(--bind "${HOME}/.cache/uv" "${HOME}/.cache/uv")
  args+=(--bind "$dir" "$dir" --chdir "$dir")
  timeout --kill-after=10 "${WB_CHECK_TIMEOUT:-600}" bwrap "${args[@]}" -- \
    env -i HOME="$HOME" PATH="${WB_VENV:+${WB_VENV}/bin:}${HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin" \
      LANG=C.UTF-8 TERM=dumb CI=1 FORCE_COLOR=0 NO_COLOR=1 SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0 \
      WB_BASE_SHA="${WB_BASE_SHA:-}" UV_CACHE_DIR="${HOME}/.cache/uv" \
      bash -c "$cmd"
}

# expand <command>: fill {harness}, {venv} and {src} from WB_TRUSTED, WB_VENV and WB_SRC.
expand() {
  local c="$1"
  c="${c//\{harness\}/${WB_TRUSTED}/harness}"
  c="${c//\{venv\}/${WB_VENV}}"
  c="${c//\{src\}/${WB_SRC}}"
  printf '%s' "$c"
}

# event <file> <json fields as jq args...>: append one ledger-style line.
event() {
  local file="$1"; shift
  jq -nc --arg at "$(date -u +%FT%TZ)" "$@" '$ARGS.named + {at: $at}' >> "$file"
}

# wb_settings <trusted dir> <task dir> <plan.json> <worktree> <extra deny rules JSON> <with hooks: 1|0>
# The settings Claude Code runs under, from the trusted settings template: file tools only in
# the worktree, credential folders denied to tools and hidden from the sandbox, network only to
# the spec's allowed hosts, and the hooks pointed at the trusted harness copy.
wb_settings() {
  local T="$1" tdir="$2" plan="$3" work="$4" extra="$5" with_hooks="$6" secrets domains envvars
  secrets="$(wb_secrets | jq -R . | jq -sc 'map(select(length > 0))')"
  domains="$(jq -c '.sandbox.allowed_domains' "$plan")"
  # The session inherits the operator's environment. Every token-like variable in it (a proxy
  # password, a cloud key) is denied to shell commands beside the template's fixed list; names
  # only, never values. Claude Code's own CLAUDE_CODE_* variables are its to keep.
  envvars="$(env | cut -d= -f1 | grep -iE 'token|api_key|secret|password|credential|^gh_' | grep -v '^CLAUDE_CODE_' | sort -u | jq -R . | jq -sc 'map(select(length > 0) | {name: ., mode: "deny"})')"
  jq --arg work "$work" --arg hooks "${T}/harness/hooks" --arg task "$tdir" --argjson secrets "$secrets" \
     --argjson domains "$domains" --argjson extra "$extra" --argjson withHooks "$with_hooks" --argjson envvars "$envvars" '
    walk(if type == "string" then (split("{{WORK}}") | join($work) | split("{{HOOKS}}") | join($hooks) | split("{{TASK}}") | join($task)) else . end)
    | .permissions.deny += ([$secrets[] | "Read(/\(.))", "Read(/\(.)/**)"] + $extra)
    | .sandbox.filesystem.denyRead = $secrets
    | .sandbox.network.allowedDomains = $domains
    | .sandbox.credentials.envVars = ((.sandbox.credentials.envVars // []) + $envvars | unique_by(.name))
    | if $withHooks == 1 then . else del(.hooks) end' "${T}/.claude/workbench/settings.template.json"
}
