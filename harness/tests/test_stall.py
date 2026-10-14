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
