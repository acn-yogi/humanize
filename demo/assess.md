# Phase 0: readiness assessment of the humanize fork

Assessed 12 October 2026 against `acn-yogi/humanize` at the commit the harness was installed
on, using only what the repository shows and what the GitHub API returns to a read-only
viewer (`gh api`, `gh pr list`, `gh issue list`). Upstream `python-humanize/humanize` was
read, never written to. Every line below names the observation it rests on.

**Headline: 25 of 50. Ready for phase 1 (assisted) today, which is what ran. Phase 2
(autonomous by class) needs two things the fork does not have: branch protection on
`main`, and CI that actually runs on the fork's PRs. Phase 3 (self-improving) needs a
proving record (`harness/proofs/` is empty) and an agreed stand-in for a feature flag,
which a library does not have.**

| Dimension | Score | One line |
|---|---|---|
| Tests | 4 | 744 pass in six seconds; 112 skip without compiled catalogs |
| CI | 3 | Well built upstream; has never run once on the fork |
| Branch protection | 0 | `main` unprotected, no rulesets, three merge methods allowed |
| CODEOWNERS | 1 | None; one maintainer by social fact, nothing encoded |
| Backlog shape | 4 | Small, crisp, reproducible issues; thin labels |
| Secrets hygiene | 4 | Trusted Publishing, pinned actions, scanning on; Dependabot off |
| Flag service | 1 | None (a library); an opt-in convention can stand in |
| Deploy pipeline | 3 | Build and inspect on every push, release by tag; dark on the fork |
| Observability | 2 | Benchmarks and coverage exist upstream; dark on the fork; ledger only |
| Eval seed | 3 | Four specs, one fail-first, three recorded runs; no pass^k yet |

Scores: 0 absent, 1 ad hoc, 2 present but not usable here, 3 usable with gaps, 4 solid, 5
nothing to add for this phase.

Later the same day the two gaps that held phase 2 back were closed and the fork was assessed
again: **32 of 50**. The table above is the before; the section "After closing the gaps" at
the end has the after, dimension by dimension, with the evidence.

## Tests: 4

Observed: `tests/` holds seven files and 68 test functions, almost all parametrized, and
the suite reports `744 passed, 112 skipped in 6.02s` in a fresh clone with no network
(`demo/recordings/t-01M4RYVYEG6H31MRD8C2N01K04/checks.log`). `pyproject.toml` sets
`filterwarnings = ["error"]`, so a warning fails a test. Time tests pin the clock with
`freezegun`. `tox.ini` adds `--doctest-modules`, so docstring examples are tests too.
Coverage is collected (`--cov humanize --cov tests`) and uploaded to Codecov from CI.

Gaps: the 112 skips are the i18n tests, which need compiled `.mo` catalogs that a plain
checkout does not have (the recorded reviewer confirmed this against `tests/test_i18n.py`
and `test.yml`). No coverage threshold is enforced, so a change can lower coverage and stay
green.

Closes it: run `scripts/generate-translation-binaries.sh` in the workbench setup step so the
i18n tests run on every task; a coverage floor in `pyproject.toml` or the Codecov config.

## CI: 3

Observed upstream design, present in the fork: ten workflows under `.github/workflows/`.
`test.yml` runs the suite on a matrix of Python versions (including free-threaded builds)
across Windows, macOS and Ubuntu and uploads coverage; `lint.yml` runs the pre-commit set
(ruff, black, actionlint, zizmor, pyproject-fmt, prettier and more); `docs.yml` builds the
site; `benchmark.yml` runs CodSpeed; `require-pr-label.yml` enforces a changelog label;
`release.yml` builds and inspects the package on every push. Every `uses:` is pinned to a
commit SHA with a version comment. Top-level `permissions: {}` with per-job grants.

Observed on the fork: all ten workflows are `active`, and `gh api
repos/acn-yogi/humanize/actions/runs` returns a total of zero. `gh pr checks` on PR #3
says `no checks reported`. The three workbench PRs were verified by the harness's own
checks in a fresh clone under bubblewrap, and by nothing else.

Gaps: CI has not run once on the fork, so the second, independent verification the phase 2
routing assumes is missing. The cause was not diagnosed here (GitHub disables scheduled and
sometimes all workflows on forks until a person enables them; the push came from the Windows
`git.exe` with the person's credentials). No Codecov or CodSpeed token exists on the fork
(`actions/secrets` returns zero), so those two uploads would fail or skip even once runs
start.

Closes it: enable Actions runs on the fork and open one PR to confirm `Test` and `Lint`
run; make the harness's router read the check runs (`gh pr checks`) as a fact next to its
own checks; leave Codecov and CodSpeed dark on the fork (they belong to the project).

## Branch protection: 0

Observed on the fork: `gh api repos/acn-yogi/humanize/branches/main/protection` returns
`Branch not protected`; `rules/branches/main` returns `[]`; squash, merge-commit and rebase
merges are all allowed; `delete_branch_on_merge` is false. Anyone with write access, and
any script with the person's token, can push to `main` directly. Upstream's protection is
not visible to a read-only viewer (the API needs admin rights), so nothing is claimed about it.

Gaps: the whole of phase 2 rests on "merges by policy" being the only way to merge. Today
`harness/bin/approve-batch.sh --merge` and the graduated path in `publish.sh` would merge
without any required check, because none is required.

Closes it: one ruleset on `main`: pull request required, status checks `Test` and `Lint`
required, linear history, no force pushes, and the harness's merges going through the same
gate. The sandbox already keeps the token out of Claude's sessions (guardrail probe, PASS);
protection makes the same true for every other actor.

## CODEOWNERS: 1

Observed: no `CODEOWNERS` file at `.github/`, the root or `docs/`. `pyproject.toml` names
one maintainer; the contributor list is one person with 655 commits, Renovate with 88, and
the original author with 34. Ownership is unambiguous and entirely social.

Gaps: the router's `per_pr` route says "a person reviews this PR" without being able to
name the person. The high-risk path rules in `harness/lib/risk.ts` (CI, manifests,
instruction files, security paths) stand in for ownership of the sensitive paths.

Closes it: a `CODEOWNERS` with three lines (`.github/`, `pyproject.toml`,
`src/humanize/locale/`) so a `per_pr` PR requests its reviewer, and so the router can
read ownership instead of carrying it.

## Backlog shape: 4

Observed upstream: 18 open issues in the list, 52 open issues and PRs by the repository
count. Most are small and come with a reproduction and an expected output (`#431`
intcomma scientific notation, `#423` metric rounding, `#419` OverflowError, `#366`
naturalsize format strings, `#379` precisedelta sign, `#356` intword carry). Several are
feature proposals with a clear shape (`#214` conjunction, `#227` more intword words, `#102`
weekdays, `#129` ISO 8601 input). Three need a human translator (`#270`, `#263`, `#181`).
Four issues already became specs in `specs/`; one became the intent in `intents/`.

Gaps: labels are thin. Of the 18, three carry a label (`bug`, `enhancement`, `help wanted`);
the fork has issues disabled (`has_issues: false`), so the backlog lives upstream only.

Closes it: a label per class (`class:bugfix`, `class:feature`, `class:docs`,
`class:packaging`, `class:i18n`) applied by a person, read by the shaper to pick intents and
by the dispatcher to forecast. Issues stay upstream; the fork never comments there.

## Secrets hygiene: 4

Observed: zero Actions secrets on the fork. Secret scanning and push protection are
enabled; Dependabot security updates and alerts are disabled; validity checks and
non-provider patterns are off. Releases use PyPI Trusted Publishing (`id-token: write`),
so no PyPI token exists anywhere. `zizmor` audits the workflows in pre-commit. Renovate
runs upstream with `minimumReleaseAge: 7 days`. `.github/SECURITY.md` routes reports to
Tidelift. No `.env` files; the attended settings deny reading any. The harness denies the
model token to shell commands and hides credential folders; the live probe recorded PASS
on every credential line (`demo/recordings/guardrails/report.txt`).

Gaps: Dependabot is off on the fork and Renovate's app is not installed there, so the fork
gets no dependency alerts at all.

Closes it: enable Dependabot alerts on the fork (one setting); keep zero secrets on the
fork, which the harness never needs.

## Flag service: 1

Observed: none, and none expected. `humanize` is a library with no runtime configuration,
no environment toggles and no service to call. Phase 3's "dark deploy behind a flag, and the
flag is the human control" has no literal home here.

Gaps: without a stand-in, a phase 3 loop has nowhere to put a change that is merged but not
yet live.

Closes it: a written convention that plays the flag's part for a library. New behaviour
ships opt-in with the default unchanged (a keyword argument that defaults to today's output);
flipping a default is its own spec, approved by a person. The intent in
`intents/0001-naturalday-weekdays.md` is written that way. The pre-release path to
TestPyPI in `release.yml` is the dark deploy; a tagged release is the flag flip.

## Deploy pipeline: 3

Observed: `release.yml` runs `hynek/build-and-inspect-python-package` on every push and PR,
publishes to TestPyPI and PyPI on a GitHub release through Trusted Publishing, and version
numbers come from tags via `hatch-vcs`. `release-drafter.yml` drafts the notes from PR
labels and `require-pr-label.yml` makes sure each PR carries one. `RELEASING.md` is a
six-item checklist.

Gaps: on the fork the workflow has never run (see CI), and the fork must never publish: it
is not the project, and no PyPI publisher is or should be registered for it. So the only
deploy artefact available to a loop on the fork is the inspected wheel from the build job,
once Actions run.

Closes it: Actions on; treat the `build-package` job's artefact as the dark deploy for the
demo; keep the publish jobs upstream's.

## Observability: 2

Observed: as a library, `humanize` has and needs no runtime telemetry. What the project does
measure: performance on every push and PR through CodSpeed (`tests/test_benchmarks.py`),
coverage through Codecov, and a documentation build on Read the Docs. On the fork none of
these has produced a data point. The harness records what it does: `runs/ledger.jsonl` (one
line per task), `loops.jsonl` per task, the evidence packet on each PR, the pack's evidence
stream, and `demo/recordings/` for the runs kept.

Gaps: the harness has the data and no view of it; the project's signals are dark on the fork.

Closes it: a status page that reads the ledger and the packets at run time (spend, routes,
retries, reviewer findings), so figures live where they can be dated and corrected; Actions
on, so the benchmark runs on the fork's PRs.

## Eval seed: 3

Observed: four specs with runnable acceptance checks (`harness/checks/`), one with a
fail-first check that is proven to fail on the base and pass on the result (spec 0002, PR
#3), three recorded end-to-end runs with facts, verdicts and decisions, two adversarial
reviewer rounds per run with findings on the record, and 744 tests as the regression oracle.
`harness/bin/prove.sh` exists and `harness/proofs/` is empty: no class has a pass^k record.

Gaps: graduation (phase 2) and the proving loop (phase 3) read a record nobody has written
yet. One fail-first check is a start, not a seed.

Closes it: run `prove.sh --k 3` on the docs class (three runs, about two dollars); approve
the shaped specs so every new spec arrives with a fail-first check; keep the reviewers'
findings as cases.

## What this says about the phases

- Phase 1 can run now, and did: specs 0001, 0002 and 0004 produced PRs #1, #3 and #2, each
  verified by the harness and each waiting for a person.
- Phase 2 is built and partly shown (PR #1 joined an approved batch; the router stopped PR #2
  for its manifest change) but should not be switched on for merges until `main` is
  protected and CI runs on the fork.
- Phase 3's shaping ran once (`demo/recordings/shape/`). The proving loop and the opt-in
  convention come first before anything it shapes merges by policy.

## After closing the gaps (12 October 2026, later the same day)

The same method and the same read-only evidence (`gh api`, `gh pr checks`, `gh ruleset
view`), after three changes on the fork. No model spend: every step was `gh`, `git` and a
text editor.

**Headline: 32 of 50, from 25.** Phase 2 can now be switched on for merges: `main` takes
changes only through a pull request with green required checks, and the harness's merge
path still works, as the owner's bypass (below).

| Dimension | Before | After | What changed |
|---|---|---|---|
| Tests | 4 | 4 | Nothing; still the regression oracle |
| CI | 3 | 4 | Actions run on the fork; `Test successful`, `lint` and `mypy` report on every PR |
| Branch protection | 0 | 4 | One ruleset on `main`: PR only, three required checks, one review, threads resolved, linear history, no force push, no deletion |
| CODEOWNERS | 1 | 3 | `.github/CODEOWNERS`, every path owned by `@acn-yogi`, and the ruleset requires a code owner review |
| Backlog shape | 4 | 4 | Nothing; the fork gained the seven `changelog:` labels upstream's PR workflow asks for |
| Secrets hygiene | 4 | 4 | Still zero secrets on the fork, and none added |
| Flag service | 1 | 1 | Nothing; the opt-in convention still stands in |
| Deploy pipeline | 3 | 3 | `Build & verify package` now runs green on every PR, so the inspected wheel exists; publishing stays upstream's |
| Observability | 2 | 2 | The coverage upload runs without a Codecov token and is ignored; CodSpeed (`benchmarks`) fails without its token; both dark by design |
| Eval seed | 3 | 3 | Nothing; `harness/proofs/` is still empty |

### CI: 4

Observed: `repos/acn-yogi/humanize/actions/permissions` returns `enabled: true,
allowed_actions: all`. The reason the three PRs showed `no checks reported` was simpler than
a disabled fork: Actions were switched on after the branches had been pushed, and GitHub never
runs a workflow for an event that happened before it was enabled. One empty commit per PR
branch, then a close and reopen so the `pull_request` runs used a merge commit that includes
the lint configuration below, gave each PR its runs.

Results per PR, latest run of each check (`gh pr checks N`):

| PR | `Test successful` (27 jobs) | `lint` | `mypy` | `Build & verify package` | `label` | `benchmarks` |
|---|---|---|---|---|---|---|
| #1 docs | pass | fail: prettier wants `docs/testing.md` rewrapped at 88 columns | pass | pass | pass | fail, no CodSpeed token |
| #2 CLI | pass | fail: `pyproject-fmt` reorders the new `[project.scripts]` entry; ruff PT006 in `tests/test_cli.py` | pass | pass | pass | fail, no CodSpeed token |
| #3 precisedelta | pass | fail: ruff E501 and black in `tests/test_time.py` | pass | pass | pass | fail, no CodSpeed token |

`main` itself is green: `Test successful`, `lint` and `mypy` all pass on its head.

The `lint` failures are real findings on the changed files, and they are what a second,
independent verifier is for: the harness runs the test suite and the acceptance checks in a
fresh clone, and never ran upstream's pre-commit set. Two things were changed so `lint` says
something about the library change alone. The harness and demo folders are excluded from
pre-commit and mypy (`.pre-commit-config.yaml` `exclude`, `pyproject.toml` `[tool.mypy]
exclude`): they are tooling beside the library and carry their own checks. And the fork
received the seven `changelog:` labels that `Require PR label` asks for; upstream's `Sync
labels` workflow cannot create them on the fork, because its action builds a Docker image
and the `ubuntu-slim` runner has no Docker.

Gaps: the three open PRs cannot merge until their `lint` findings are fixed, which is the
right outcome. Codecov and CodSpeed stay dark (no tokens on the fork, by design), so
`benchmarks` is red on every PR and is not required.

Closes it: `prek run --all-files` (or `tox -e lint`) among the harness's quick checks, so a
workbench fixes formatting before it opens the PR; the router reading `gh pr checks` as a
fact beside its own checks.

### Branch protection: 4

Observed: `gh ruleset view 24964704 -R acn-yogi/humanize`, "main: merge by policy only",
active, target `~DEFAULT_BRANCH`. Rules: `deletion` (nobody deletes `main`),
`non_fast_forward` (no force pushes), `required_linear_history`, `pull_request` (one
approving review, code owner review, stale reviews dismissed on push, review threads
resolved, squash the only merge method), `required_status_checks` (`Test successful`,
`lint`, `mypy`, each from GitHub Actions, non-strict so a PR need not be rebased onto the
latest `main` first). The rule as posted is kept in `demo/ruleset.json`. Classic branch
protection was not used: a ruleset is what `gh` reads and writes cleanly, and it carries the
bypass list explicitly instead of a single "include administrators" switch.

The one bypass: `RepositoryRole` admin (actor id 5), mode `always`. This is the merge-by-policy
path. `publish.sh` (graduated classes) and `approve-batch.sh --merge` (batches) both run `gh pr
merge <pr> --squash --delete-branch` with the owner's token; the owner is the only admin and
cannot approve their own PR, so without the bypass no harness merge could ever satisfy the
review rule. Not enforcing against the admin is the choice here. It is a hole only for the
owner's token, which the sandbox already keeps out of every Claude session (guardrail probe,
PASS); for every other actor the rule is absolute. The harness's exact command was tested
under the rule on the PR that carried this section: see "The merge path, tested".

Gaps: the bypass lets the harness merge a graduated PR before its required checks finish,
and the router does not yet read the check runs. Until it does, graduation (`prove.sh`) plus
the harness's own checks are the gate for the harness, and the ruleset is the gate for
everyone else.

Closes it: `publish.sh` waits on `gh pr checks --watch` before `gh pr merge`, so the bypass
covers the review only, never the checks; a bot account or GitHub App as the bypass actor in
place of the admin role, so the owner's own token stops being the exception.

### CODEOWNERS: 3

Observed: `.github/CODEOWNERS` with `*`, `/.github/`, `/harness/`, `/specs/`,
`/pyproject.toml` and `/src/humanize/locale/` all owned by `@acn-yogi`, and the ruleset
requires a code owner review. A `per_pr` PR now requests its reviewer by name.

Gaps: one owner who also authors every PR, so the owner's review is only ever satisfied by
the bypass. Ownership is encoded; a second reviewer does not exist.

Closes it: a second maintainer, or a reviewing bot, on the sensitive paths.

### The merge path, tested

The commit that added this section went to `main` through the new gate with the harness's
command exactly as `publish.sh` and `approve-batch.sh` run it: `gh pr merge <url> --repo
acn-yogi/humanize --squash --delete-branch`, the owner's token, no review, required checks
not yet reported. The PR number, the outcome and the merge commit are in `DEMO.md` step 0.
