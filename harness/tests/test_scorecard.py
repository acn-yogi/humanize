"""The scorecard math over plain lists: takeovers, comments, uncorrected PRs, cost per merged PR, recurrence."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import scorecard  # noqa: E402

T1, T2, T3 = "t-01M4RYVYEG6H31MRD8C2N01K04", "t-01M4RZHVFWTPBC0BG9QVPBAS3T", "t-01M4RZHVGFWY1FXM7RNXWAVNQA"
LEDGER = [
    {"at": "2026-10-12T21:11:04Z", "taskId": T1, "spec": "0001", "class": "docs", "path": "batch_plan", "costUsd": 0.6, "pr": "https://x/pull/1"},
    {"at": "2026-10-12T21:22:54Z", "taskId": T2, "spec": "0004", "class": "packaging", "path": "per_pr", "costUsd": 0.64, "pr": "https://x/pull/2"},
    {"at": "2026-10-12T21:26:35Z", "taskId": T3, "spec": "0002", "class": "bugfix", "path": "per_pr", "costUsd": 0.9, "pr": "https://x/pull/3"},
    {"at": "2026-10-13T01:14:22Z", "taskId": "s-20261013T011217", "spec": "0001-intent", "class": "shaping", "path": "shape", "costUsd": 0.21, "pr": ""},
    {"at": "2026-10-13T10:00:00Z", "event": "corrected", "source": "pr-comment", "pr": 3, "taskId": T3, "author": "p", "reasonCode": "lint", "url": "u1"},
    {"at": "2026-10-13T10:05:00Z", "event": "corrected", "source": "pr-comment", "pr": 3, "taskId": T3, "author": "p", "reasonCode": "test", "url": "u2"},
    {"at": "2026-10-13T11:00:00Z", "event": "corrected", "source": "manual", "taskId": T2, "action": "takeover", "reasonCode": "wrong-behaviour", "author": "p"},
    {"at": "2026-10-13T11:30:00Z", "event": "budget-exhausted", "pool": 1, "spent": 0.64, "window": "run", "leftInQueue": 2},
]
PRS = [
    {"number": 1, "headRefName": f"workbench/{T1}", "body": "", "mergedAt": "2026-10-13T09:00:00Z"},
    {"number": 2, "headRefName": f"workbench/{T2}", "body": "", "mergedAt": None},
    {"number": 3, "headRefName": f"workbench/{T3}", "body": "", "mergedAt": "2026-10-13T12:00:00Z"},
    {"number": 4, "headRefName": "harness/after-closing-the-gaps", "body": "", "mergedAt": "2026-10-13T03:45:32Z"},
]
PACK = {"bytes": 1000, "files": 5, "paths": list(scorecard.PACK_PATHS)}


class ScorecardTests(unittest.TestCase):
    def test_takeovers_and_comments(self):
        s = scorecard.compute(LEDGER, PRS, [], PACK)
        self.assertEqual(s["manualTakeovers"], 1)
        self.assertEqual(s["humanPrComments"], {"total": 2, "perPr": {"3": 2}})

    def test_prs_with_no_correction_count_harness_prs_only(self):
        s = scorecard.compute(LEDGER, PRS, [], PACK)
        self.assertEqual(s["prsWithNoCorrection"], {"count": 1, "of": 3, "numbers": [1]})

    def test_cost_per_merged_pr_is_the_merged_tasks_cost_over_the_merged_count(self):
        s = scorecard.compute(LEDGER, PRS, [], PACK)
        c = s["costPerMergedPr"]
        self.assertEqual(c["merged"], 2)
        self.assertAlmostEqual(c["totalUsd"], 1.5)
        self.assertAlmostEqual(c["usd"], 0.75)

    def test_no_merged_pr_gives_none(self):
        prs = [dict(p, mergedAt=None) for p in PRS]
        self.assertIsNone(scorecard.compute(LEDGER, prs, [], PACK)["costPerMergedPr"]["usd"])

    def test_offline_leaves_github_signals_unset(self):
        s = scorecard.compute(LEDGER, None, [], PACK)
        self.assertIsNone(s["prsWithNoCorrection"])
        self.assertIsNone(s["costPerMergedPr"])
        self.assertIn("n/a (GitHub not read)", scorecard.render(s))

    def test_recurrence_counts_a_reason_seen_after_its_case_was_proven(self):
        cases = [{"id": "lint-in-quick-checks", "reasonCode": "lint", "provenAt": "2026-10-13T09:00:00Z"},
                 {"id": "tests-later", "reasonCode": "test", "provenAt": "2026-10-13T10:30:00Z"},
                 {"id": "manifest-flag", "changedPaths": ["pyproject.toml"]}]
        r = scorecard.compute(LEDGER, PRS, cases, PACK)["recurrence"]
        self.assertEqual(r["casesWatched"], 2)
        self.assertEqual(r["count"], 1)
        self.assertEqual(r["cases"][0]["case"], "lint-in-quick-checks")

    def test_render_has_one_line_per_signal(self):
        text = scorecard.render(scorecard.compute(LEDGER, PRS, [], PACK))
        for head in ("manual takeovers", "human PR comments", "PRs with no correction", "cost per merged PR", "recurrence",
                     "halts by failure class", "stalls by category", "pack size"):
            self.assertIn(head, text)
        self.assertEqual(len(text.splitlines()), 8)

    def test_halts_by_failure_class_and_stalls_by_category_are_separate_lines(self):
        halted = [
            {"at": "2026-10-14T01:00:00Z", "taskId": "t-01M4ZZZZZZZZZZZZZZZZZZZZZA", "spec": "0005", "class": "feature", "path": "reject", "costUsd": 0.3,
             "pr": "", "failureClass": "genuine", "stall": "variance", "haltReason": "retry-cap"},
            {"at": "2026-10-14T01:10:00Z", "taskId": "t-01M4ZZZZZZZZZZZZZZZZZZZZZB", "spec": "0006", "class": "feature", "path": "reject", "costUsd": 0.1,
             "pr": "", "failureClass": "harness-error", "stall": "harness-or-infra", "haltReason": "rejected"},
            {"at": "2026-10-14T01:20:00Z", "taskId": "t-01M4ZZZZZZZZZZZZZZZZZZZZZC", "spec": "0007", "class": "feature", "path": "reject", "costUsd": 0.2,
             "pr": "", "failureClass": "genuine", "stall": "structural", "haltReason": "stall-structural"},
            {"at": "2026-10-14T01:30:00Z", "taskId": "t-01M4ZZZZZZZZZZZZZZZZZZZZZD", "spec": "0008", "class": "feature", "path": "reject", "costUsd": 0.2,
             "pr": "", "failureClass": "refusal", "stall": None, "haltReason": "rejected"},
            {"at": "2026-10-12T01:30:00Z", "taskId": "t-01M4ZZZZZZZZZZZZZZZZZZZZZE", "spec": "0009", "class": "feature", "path": "reject", "costUsd": 0.2, "pr": ""},
        ]
        s = scorecard.compute(LEDGER + halted, PRS, [], PACK)
        self.assertEqual(s["haltsByFailureClass"], {"halts": 5, "classes": {"genuine": 2, "harness-error": 1, "refusal": 1, "unclassified": 1}})
        self.assertEqual(s["stallsByCategory"], {"stalls": 3, "categories": {"harness-or-infra": 1, "structural": 1, "variance": 1}, "stoppedEarly": 1})
        text = scorecard.render(s)
        self.assertIn("halts by failure class    5 halted task(s): genuine 2, harness-error 1, refusal 1, unclassified 1", text)
        self.assertIn("stalls by category        3 stall(s): harness-or-infra 1, structural 1, variance 1; 1 stopped before the cap (stall-structural)", text)
        self.assertNotIn("failure rate", text.split("never one failure rate")[0].split("halts by")[0])

    def test_no_halts_says_zero_on_both_lines(self):
        text = scorecard.render(scorecard.compute(LEDGER, PRS, [], PACK))
        self.assertIn("halts by failure class    0 halted task(s)", text)
        self.assertIn("stalls by category        0 stall(s)", text)

    def test_pack_size_counts_files_and_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "harness/pack/x").mkdir(parents=True)
            (root / "harness/pack/x/a.ts").write_text("abc", encoding="utf-8")
            (root / "harness/hooks").mkdir(parents=True)
            (root / "harness/hooks/stop-checks.sh").write_text("12345", encoding="utf-8")
            (root / ".claude/workbench").mkdir(parents=True)
            (root / ".claude/workbench/settings.template.json").write_text("{}", encoding="utf-8")
            p = scorecard.pack_size(root)
        self.assertEqual((p["bytes"], p["files"]), (10, 3))


if __name__ == "__main__":
    unittest.main()
