+++
# A recurring maintenance spec. No id: the schedule trigger assigns one when it enqueues this
# as specs/NNNN-flaky-test-hunt-<date>.md, with status = "approved", trigger =
# "schedule:flaky-test-hunt:<date>" and the approved_by below, which is the person who
# approved the recurring work once. Each dated instance still ends at a PR for a person.
title = "Flaky test hunt: the suite run three times, any test that flips fixed or pinned"
class = "maintenance"
approved_by = "yogi.aradhye"
scope = ["tests/**"]

[checks]
quick = ["python {harness}/checks/suite_repeat.py --times 2"]
acceptance = ["python {harness}/checks/suite_repeat.py --times 3"]

[caps]
max_turns = 25
max_budget_usd = 1.5
+++

# Flaky test hunt

A scheduled maintenance task. Run the test suite three times in a row and look for tests whose
result changes between runs.

## Intent

Find every test that passes in one run and fails in another, and make it deterministic: fix
the test's own assumption (time, ordering, locale, random data) where that is the cause, and
only where the cause is a real product bug, leave the test as it is and say so in the PR body.

## Constraints

- Change only files under `tests/`. A product fix is a separate spec a person writes.
- Do not mark a test skipped or xfail to make it quiet. A test that flips is either fixed or
  reported, never hidden.
- Keep the suite's running time within a second of today's.
- When no test flips in three runs, change nothing and say so in one line.

## Out of scope

- Any file under `src/`, `docs/` or the package configuration.
- Adding dependencies (no `pytest-randomly`, no `flaky` plugin).

## Acceptance criteria

1. `python {harness}/checks/suite_repeat.py --times 3` passes: three runs of the suite agree
   with each other and every test passes.
2. The full suite passes.
