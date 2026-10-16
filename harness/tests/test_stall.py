"""Failure classes and stall categories from planted session, round and loop records."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import stall  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PLAN = {"checks": {"acceptance": ["python -m pytest -q", "python {harness}/checks/x.py", "python {harness}/checks/changed.py tests/test_time.py"],
                   "failFirst": ["python {harness}/checks/x.py"], "mustNotChange": []}}


def session(round_=0, subtype="success", exit_=0, is_error=False, result="Done.", role="worker"):
    return {"role": role, "round": round_, "subtype": subtype, "exit": exit_, "isError": is_error, "result": result, "sessionId": "s"}


def rnd(round_, checks_pass=True, verdict="approve", path=None, changed=("src/humanize/time.py",), checks=None):
    return {"round": round_, "allChecksPass": checks_pass, "changedPaths": list(changed),
            "verdict": {"verdict": verdict, "reasons": ["r"]} if verdict else None,
            "path": path or ("reject" if not checks_pass else ("per_pr" if verdict == "reject" else "per_pr")),
            "checks": checks or ([] if checks_pass else [{"cmd": "python -m pytest -q", "exit": 1}])}


def record(sessions=None, rounds=None, loops=None, texts=("Done.",), scope=None, changed=("src/humanize/time.py",)):
    return {"sessions": sessions if sessions is not None else [session()], "rounds": rounds if rounds is not None else [rnd(0)],
            "loops": loops or [], "scope": scope or {"outside": [], "harness": []}, "checks": [],
            "authorTexts": list(texts), "checkPaths": stall.check_paths(PLAN), "changedPaths": list(changed)}


class FailureClassTests(unittest.TestCase):
    def test_a_timed_out_session_is_timeout_and_harness_or_infra(self):
        c = stall.classify(record(sessions=[session(exit_=124, subtype="")]), 1, 1)
        self.assertEqual((c["failureClass"], c["stall"]), ("timeout", "harness-or-infra"))

    def test_a_session_error_is_harness_error_even_before_the_cap(self):
        c = stall.classify(record(sessions=[session(is_error=True, subtype="error_during_execution", result="API Error: 502")]), 0, 1)
        self.assertEqual((c["failureClass"], c["stall"]), ("harness-error", "harness-or-infra"))
        self.assertIn("API Error", c["evidence"])

    def test_a_budget_cap_is_not_a_harness_error(self):
        c = stall.classify(record(sessions=[session(subtype="error_max_budget_usd")], rounds=[rnd(0, checks_pass=False)]), 1, 1)
        self.assertEqual(c["failureClass"], "genuine")

    def test_a_refusal_with_no_change_is_refusal(self):
        c = stall.classify(record(rounds=[rnd(0, checks_pass=False, changed=())], texts=("I can't do this: the task asks me to delete the test suite.",), changed=()), 1, 1)
        self.assertEqual(c["failureClass"], "refusal")

    def test_a_refusal_phrase_with_a_change_is_genuine(self):
        c = stall.classify(record(rounds=[rnd(0, checks_pass=False)], texts=("I can't see why the check fails, but I changed time.py.",)), 1, 1)
        self.assertEqual(c["failureClass"], "genuine")


class StallTests(unittest.TestCase):
    def test_no_stall_below_the_cap_without_a_structural_signal(self):
        c = stall.classify(record(rounds=[rnd(0, checks_pass=False)]), 0, 1)
        self.assertEqual(c["failureClass"], "genuine")
        self.assertIsNone(c["stall"])
        self.assertFalse(c["atCap"])

    def test_a_contradiction_named_by_the_author_is_structural_before_the_cap(self):
        c = stall.classify(record(rounds=[rnd(0, checks_pass=False)],
                                  texts=("The acceptance criteria contradict each other: section Constraints says zero never gains a sign and the check expects '-0 seconds'.",)), 0, 1)
        self.assertEqual(c["stall"], "structural")
        self.assertIn("contradiction", c["stallEvidence"])

    def test_scope_denials_on_a_path_the_checks_name_are_structural(self):
        loops = [{"loop": "scope", "decision": "deny", "tool": "Edit", "path": "tests/test_time.py", "reason": "outside this spec's scope"}]
        c = stall.classify(record(rounds=[rnd(0, checks_pass=False, path="reject")], loops=loops), 0, 1)
        self.assertEqual(c["stall"], "structural")
        self.assertIn("tests/test_time.py", c["stallEvidence"])

    def test_scope_denials_on_an_unrelated_path_are_not_structural(self):
        loops = [{"loop": "scope", "decision": "deny", "tool": "Write", "path": "README.md", "reason": "outside this spec's scope"}]
        c = stall.classify(record(rounds=[rnd(0, checks_pass=False, path="reject")], loops=loops), 1, 1)
        self.assertNotEqual(c["stall"], "structural")

    def test_an_out_of_scope_diff_on_a_needed_path_is_structural(self):
        c = stall.classify(record(rounds=[rnd(0, checks_pass=True, verdict=None, path="reject", changed=("src/humanize/time.py", "src/humanize/i18n.py"))],
                                  scope={"outside": ["src/humanize/i18n.py"], "harness": []}, changed=("src/humanize/time.py", "src/humanize/i18n.py")), 0, 1)
        self.assertEqual(c["stall"], "structural")

    def test_the_same_check_failing_twice_with_the_reviewer_approving_is_grader_disagreement(self):
        failing = [{"cmd": "python {harness}/checks/x.py", "exit": 1}]
        c = stall.classify(record(rounds=[rnd(0, checks_pass=False, verdict="approve", checks=failing), rnd(1, checks_pass=False, verdict="approve", checks=failing)]), 1, 1)
        self.assertEqual(c["stall"], "grader-disagreement")
        self.assertIn("checks/x.py", c["stallEvidence"])

    def test_checks_passing_while_the_reviewer_rejects_twice_is_grader_disagreement(self):
        c = stall.classify(record(rounds=[rnd(0, True, "reject"), rnd(1, True, "reject")]), 1, 1)
        self.assertEqual(c["stall"], "grader-disagreement")

    def test_checks_flipping_between_rounds_is_variance(self):
        c = stall.classify(record(rounds=[rnd(0, checks_pass=True, verdict="reject"), rnd(1, checks_pass=False, verdict="approve")]), 1, 1)
        self.assertEqual(c["stall"], "variance")

    def test_a_missing_module_named_by_the_author_is_an_artifact_gap(self):
        c = stall.classify(record(rounds=[rnd(0, checks_pass=False)], texts=("The check imports humanize.extras but No module named humanize.extras exists on this branch.",)), 1, 1)
        self.assertEqual(c["stall"], "artifact-gap")

    def test_no_signal_at_the_cap_is_an_artifact_gap_with_the_reason_said(self):
        c = stall.classify(record(rounds=[rnd(0, checks_pass=False)]), 1, 1)
        self.assertEqual((c["failureClass"], c["stall"]), ("genuine", "artifact-gap"))
        self.assertIn("no stronger signal", c["stallEvidence"])

    def test_the_closed_sets(self):
        self.assertEqual(set(stall.FAILURE_CLASSES), {"harness-error", "refusal", "timeout", "genuine"})
        self.assertEqual(set(stall.STALLS), {"artifact-gap", "grader-disagreement", "harness-or-infra", "structural", "variance"})


class StallReviewTests(unittest.TestCase):
    """After two consecutive flat rejected attempts: the remaining failures by stall category, no edit, genuine ones under continueWith."""

    def flat_record(self, **kw):
        return record(rounds=[rnd(0, checks_pass=False, verdict="reject"), rnd(1, checks_pass=False, verdict="reject"), rnd(2, checks_pass=False, verdict="reject")], **kw)

    def test_two_consecutive_flat_rejected_attempts_write_a_review(self):
        c = stall.classify(self.flat_record(), 2, 2)
        rv = c["stallReview"]
        self.assertEqual(rv["flatAttempts"], 2)
        self.assertFalse(rv["edited"])
        self.assertEqual([r["source"] for r in rv["remaining"]], ["check", "reviewer"])
        self.assertEqual(rv["byCategory"], {"genuine": ["python -m pytest -q", "r"]})
        self.assertEqual(rv["continueWith"], ["python -m pytest -q", "r"])

    def test_one_flat_attempt_is_not_enough(self):
        rec = record(rounds=[rnd(0, checks_pass=False, verdict="reject"), rnd(1, checks_pass=False, verdict="reject")])
        self.assertIsNone(stall.classify(rec, 1, 2)["stallReview"])
        self.assertIsNone(stall.classify(record(), 0, 2)["stallReview"])

    def test_progress_between_attempts_is_not_flat(self):
        # 2 failures, then 1, then 1: the second attempt improved, so there are never two flat ones in a row.
        rec = record(rounds=[rnd(0, checks_pass=False, verdict="reject"), rnd(1, checks_pass=False, verdict="approve"), rnd(2, checks_pass=False, verdict="approve")])
        self.assertIsNone(stall.classify(rec, 2, 2)["stallReview"])

    def test_approved_or_passing_rounds_are_not_rejected_attempts(self):
        rec = record(rounds=[rnd(0, True, "approve"), rnd(1, True, "approve"), rnd(2, True, "approve")])
        self.assertIsNone(stall.classify(rec, 2, 2)["stallReview"])

    def test_the_failures_are_sorted_by_the_existing_stall_categories(self):
        failing = [{"cmd": "python {harness}/checks/x.py", "exit": 1}, {"cmd": "python -m pytest -q", "exit": 1}]
        passed_once = {"round": 0, "allChecksPass": False, "changedPaths": ["a.py"], "verdict": {"verdict": "reject", "reasons": ["r1", "r2", "r3"]}, "path": "reject",
                       "checks": [{"cmd": "python -m pytest -q", "exit": 0}, {"cmd": "python {harness}/checks/x.py", "exit": 1}]}
        rec = record(rounds=[passed_once,
                             {**passed_once, "round": 1, "checks": failing},
                             {**passed_once, "round": 2, "checks": failing}])
        rv = stall.classify(rec, 2, 2)["stallReview"]
        cats = {r["failure"]: r["stall"] for r in rv["remaining"]}
        self.assertEqual(cats["python -m pytest -q"], "variance")        # passed in one round, failed in another
        self.assertEqual(cats["python {harness}/checks/x.py"], "genuine")
        self.assertEqual(cats["r1"], "genuine")
        self.assertEqual(rv["continueWith"], ["python {harness}/checks/x.py", "r1", "r2", "r3"])
        self.assertNotIn("variance", [x for x in rv["continueWith"]])
        self.assertEqual(list(rv["byCategory"]), ["variance", "genuine"])

    def test_a_check_failing_while_the_reviewer_approves_is_grader_disagreement(self):
        failing = [{"cmd": "python {harness}/checks/x.py", "exit": 1}]
        rec = record(rounds=[rnd(i, checks_pass=False, verdict="approve", checks=failing) for i in range(3)])
        rv = stall.classify(rec, 2, 2)["stallReview"]
        self.assertEqual(rv["byCategory"], {"grader-disagreement": ["python {harness}/checks/x.py"]})
        self.assertEqual(rv["continueWith"], [])

    def test_a_harness_error_leaves_nothing_to_continue_with(self):
        rec = self.flat_record(sessions=[session(is_error=True, subtype="error_during_execution", result="API Error: 502")])
        c = stall.classify(rec, 2, 2)
        rv = c["stallReview"]
        self.assertEqual(set(rv["byCategory"]), {"harness-or-infra"})
        self.assertEqual(rv["continueWith"], [])
        self.assertEqual(c["stall"], "harness-or-infra")

    def test_a_missing_module_named_by_the_author_is_an_artifact_gap_for_the_failing_check(self):
        rec = self.flat_record(texts=("The check imports humanize.extras but No module named humanize.extras exists.",))
        rv = stall.classify(rec, 2, 2)["stallReview"]
        self.assertEqual({r["source"]: r["stall"] for r in rv["remaining"]}["check"], "artifact-gap")
        self.assertEqual(rv["continueWith"], ["r"])

    def test_the_review_does_not_change_the_halt_or_the_retry_cap(self):
        before = stall.classify(record(rounds=[rnd(0, checks_pass=False)]), 2, 2)
        after = stall.classify(self.flat_record(), 2, 2)
        for k in ("failureClass", "stall", "atCap", "retries", "retryCap"):
            self.assertEqual(after[k], before[k], k)
        self.assertEqual(after["retryCap"], 2)

    def test_a_planted_run_dir_carries_the_review(self):
        with tempfile.TemporaryDirectory() as d:
            r = Path(d)
            (r / "plan.json").write_text(json.dumps(PLAN), encoding="utf-8")
            (r / "facts.json").write_text(json.dumps({"checks": [], "changedPaths": ["src/humanize/time.py"]}), encoding="utf-8")
            (r / "scope.json").write_text(json.dumps({"outside": [], "harness": []}), encoding="utf-8")
            (r / "sessions.json").write_text(json.dumps([session()]), encoding="utf-8")
            (r / "rounds.jsonl").write_text("".join(json.dumps(rnd(i, checks_pass=False, verdict="reject")) + "\n" for i in range(3)), encoding="utf-8")
            c = stall.classify(stall.read_record(r), 2, 2)
        self.assertEqual(c["stallReview"]["flatAttempts"], 2)


class RunDirTests(unittest.TestCase):
    def test_a_planted_run_dir_is_read_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            r = Path(d)
            (r / "plan.json").write_text(json.dumps(PLAN), encoding="utf-8")
            (r / "facts.json").write_text(json.dumps({"checks": [{"cmd": "python -m pytest -q", "exit": 1}], "changedPaths": ["src/humanize/time.py"]}), encoding="utf-8")
            (r / "scope.json").write_text(json.dumps({"outside": [], "harness": []}), encoding="utf-8")
            (r / "sessions.json").write_text(json.dumps([session()]), encoding="utf-8")
            (r / "rounds.jsonl").write_text(json.dumps(rnd(0, checks_pass=False, path="reject")) + "\n", encoding="utf-8")
            (r / "loops.jsonl").write_text(json.dumps({"loop": "scope", "decision": "deny", "tool": "Edit", "path": "tests/test_time.py", "reason": "x"}) + "\n", encoding="utf-8")
            (r / "transcript.jsonl").write_text(
                '{"type":"system","subtype":"init","session_id":"s"}\n'
                '{"type":"assistant","message":{"model":"claude-sonnet-5-5","content":[{"type":"text","text":"I could not edit tests/test_time.py: the scope guard refused it."}]}}\n'
                '{"type":"result","subtype":"success","is_error":false,"result":"I could not edit tests/test_time.py: the scope guard refused it."}\n', encoding="utf-8")
            rec = stall.read_record(r)
            self.assertEqual(rec["checkPaths"], ["tests/test_time.py"])
            self.assertEqual(len(rec["authorTexts"]), 1)
            c = stall.classify(rec, 0, 1)
            self.assertEqual((c["failureClass"], c["stall"]), ("genuine", "structural"))

    def test_the_recorded_tasks_are_genuine_and_not_stalled(self):
        for d in sorted((ROOT / "demo/recordings").glob("t-*")):
            rec = stall.read_record(d)
            c = stall.classify(rec, 1, 1)
            self.assertEqual(c["failureClass"], "genuine", d.name)
            self.assertNotEqual(c["stall"], "structural", d.name)


if __name__ == "__main__":
    unittest.main()
