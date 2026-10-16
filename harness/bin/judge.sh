#!/bin/bash
# judge.sh: both trajectories. For a proof trial that passed under a harness change, a model
# other than the worker's reads the worker's transcript and the check output and says whether
# the agent earned the pass (ran and fixed what the check asked) or gamed it (weakened, skipped,
# noqa-ed), with a verbatim quote from the transcript; a quote that is not there makes the
# verdict unknown. Writes <trial dir>/judge.json.
#
#   harness/bin/judge.sh <trial run dir> [--model opus] [--budget 0.15] [--max-turns 3] [--dry-run]
#                        [--repeat N] [--before DIR] [--seed S]
#
# Independence and rigor (harness/lib/judge.py, DEMO.md "Rigor from the eval design article"):
# judge.json records judgeModel and the judge refuses (verdict judge-not-independent) when it is the
# model that ran the trial; --before DIR shuffles the before and after results into A and B
# (judgeBlind: true); --repeat N (default 1) runs the judge N times on the same trial and records
# graderAgreement {runs, agreed, disagreeing}. The prompt asks for a rubric of checkable claims,
# each with a verbatim quote, not a numeric scale.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=../lib/auth.sh
. "${REPO}/harness/lib/auth.sh"
dry=0; for a in "$@"; do [ "$a" = --dry-run ] && dry=1; done
[ "$dry" = 1 ] || load_auth
exec python3 "${REPO}/harness/lib/judge.py" "$@"
