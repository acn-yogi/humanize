#!/bin/bash
# env.sh: the demo's Python environment, built exactly the way harness/bin/intake.sh builds the
# intake environment (a clone of HEAD under the workbench home, the setup commands from
# harness/config.toml under bubblewrap with network, rebuilt only when HEAD moves).
#
#   demo/lib/env.sh python      -> prints the venv's python
#   demo/lib/env.sh pytest      -> runs the suite in the clone with no network; prints pytest's summary line
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=../../harness/lib/common.sh
. "${REPO}/harness/lib/common.sh"
idir="${WB_HOME}/intake"
export WB_TRUSTED="$REPO" WB_VENV="${idir}/venv" WB_SRC="${idir}/src"
WB_BASE_SHA="$(g -C "$REPO" rev-parse HEAD)"; export WB_BASE_SHA
mkdir -p "$idir" "${HOME}/.cache/uv"
[ -d "$WB_SRC" ] || g clone --quiet --no-local "$REPO" "$WB_SRC"
g -C "$WB_SRC" fetch --quiet "$REPO" HEAD && g -C "$WB_SRC" checkout --quiet --force --detach FETCH_HEAD
if [ ! -x "${WB_VENV}/bin/python" ] || [ "$(cat "${idir}/sha" 2>/dev/null)" != "$WB_BASE_SHA" ]; then
  log "env: building the environment from HEAD ${WB_BASE_SHA:0:12} (${idir})"
  while IFS= read -r c; do
    confined net "$idir" "$(expand "$c")" < /dev/null || die "setup failed: $c"
  done < <(python3 -c 'import tomllib,sys;[print(c) for c in tomllib.load(open(sys.argv[1],"rb"))["setup"]["commands"]]' "${REPO}/harness/config.toml")
  echo "$WB_BASE_SHA" > "${idir}/sha"
fi
case "${1:-python}" in
  python) echo "${WB_VENV}/bin/python" ;;
  pytest)
    confined nonet "$WB_SRC" "python -m pytest -q -p no:cacheprovider" "$WB_VENV" < /dev/null 2>&1 | tail -1 ;;
  *) die "usage: env.sh python|pytest" ;;
esac
