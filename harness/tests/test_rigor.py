"""The rigor checks: noise gate, suite sanity, rule, leak guards, case-start heuristic, whyHard."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import rigor  # noqa: E402


def summ(passes, trials, cost=0.0, errors=0):
    return {"passes": passes, "trials": trials, "errors": errors, "costUsd": cost, "runs": [{"costUsd": cost / max(trials, 1)}] * trials}


class NoiseGateTests(unittest.TestCase):
    def test_floor_above_the_delta_is_too_noisy(self):
        g = rigor.noise_gate(summ(1, 3), summ(3, 3), 0.1)
        self.assertTrue(g["tooNoisy"])
        self.assertEqual(g["noiseFloor"], 0.6667)

    def test_floor_equal_to_the_delta_is_not_too_noisy(self):
        self.assertFalse(rigor.noise_gate(summ(1, 10), summ(2, 10), 0.1)["tooNoisy"])

    def test_no_control_arm_changes_nothing(self):
        g = rigor.noise_gate(summ(1, 3), None, 0.0)
        self.assertEqual((g["controlPresent"], g["tooNoisy"], g["noiseFloor"]), (False, False, None))
        self.assertFalse(rigor.noise_gate(summ(1, 3), summ(0, 0), 0.0)["tooNoisy"])

    def test_the_default_is_a_tenth(self):
        self.assertEqual(rigor.DEFAULT_MIN_DETECTABLE_DELTA, 0.1)


class SuiteTests(unittest.TestCase):
    def test_saturated_at_ninety_five_percent(self):
        s = rigor.suite_sanity({"a": {"current": summ(19, 20)}})
        self.assertEqual(s["suite"], {"baselinePassRate": 0.95, "saturated": True, "objectiveSuggestion": "cost-at-parity"})
        s = rigor.suite_sanity({"a": {"current": summ(18, 20)}})
        self.assertFalse(s["suite"]["saturated"])
        self.assertIsNone(s["suite"]["objectiveSuggestion"])

    def test_an_empty_suite_is_not_saturated(self):
        self.assertEqual(rigor.suite_sanity({"a": {}})["suite"], {"baselinePassRate": None, "saturated": False, "objectiveSuggestion": None})

    def test_impossible_needs_two_arms_and_no_pass_anywhere(self):
        s = rigor.suite_sanity({"a": {"current": summ(0, 3), "candidate": summ(0, 3)}, "b": {"current": summ(0, 3)},
                                "c": {"current": summ(0, 3), "candidate": summ(1, 3)}, "d": {"current": summ(0, 3), "control": summ(0, 3), "candidate": None}})
        self.assertEqual(s["impossibleOrAmbiguous"], ["a", "d"])

    def test_grader_agreement_pools_and_is_null_without_a_judge(self):
        self.assertIsNone(rigor.grader_agreement([]))
        self.assertIsNone(rigor.grader_agreement([{"verdict": "earned"}]))
        self.assertEqual(rigor.grader_agreement([{"graderAgreement": {"runs": 3, "agreed": 3, "disagreeing": 0}}, {"graderAgreement": {"runs": 1, "agreed": 1, "disagreeing": 0}}]),
                         {"runs": 4, "agreed": 4, "disagreeing": 0})


class RuleTests(unittest.TestCase):
    def test_keep_overfit_revert(self):
        self.assertEqual(rigor.rule_decision(0.5, 0.2, 0)["decision"], "keep")
        self.assertEqual(rigor.rule_decision(0.5, 0.0, 0)["decision"], "overfit-suspected")
        self.assertEqual(rigor.rule_decision(0.5, -0.2, 0)["decision"], "overfit-suspected")
        self.assertEqual(rigor.rule_decision(0.5, 0.2, 1)["decision"], "revert")
        self.assertEqual(rigor.rule_decision(-0.1, 0.2, 0)["decision"], "revert")
        self.assertEqual(rigor.rule_decision(0.0, 0.0, 0)["decision"], "revert")

    def test_a_worse_held_out_case_blocks_keep(self):
        r = rigor.rule_decision(0.5, 0.3, 0, [{"case": "h1", "delta": 0.6}, {"case": "h2", "delta": -0.1}])
        self.assertEqual(r["decision"], "overfit-suspected")
        self.assertEqual(r["heldOutWorse"], ["h2"])

    def test_no_decision_without_both_deltas(self):
        self.assertIsNone(rigor.rule_decision(0.5, None, 0)["decision"])
        self.assertIsNone(rigor.rule_decision(None, 0.5, 0)["decision"])


QUOTE = "Docstring edit puts the new text inside the unclosed '0 minutes' example, which breaks the rendered docs"


class LeakTests(unittest.TestCase):
    case = {"id": "lint-on-result", "hits": [{"text": QUOTE}], "nextCandidates": {"rejections": [{"reasons": ["short reason"]}]}}

    def test_a_verbatim_failure_quote_in_an_added_line_is_flagged(self):
        diff = "+++ b/harness/pack/CLAUDE.md\n+Remember: " + QUOTE.replace("'", "") + "\n"
        hits = rigor.leak_scan(diff, [self.case])
        self.assertEqual([h["kind"] for h in hits], ["failure-quote"])
        self.assertEqual(hits[0]["check"], "pack-embeds-failure")

    def test_a_case_id_in_an_added_line_is_flagged_as_a_whole_word(self):
        self.assertEqual([h["kind"] for h in rigor.leak_scan("+if task == lint-on-result:\n", [self.case])], ["case-id"])
        self.assertEqual(rigor.leak_scan("+lint-on-results are fine\n+x lint-on-result-2\n", [self.case]), [])

    def test_removed_and_context_lines_and_short_texts_do_not_count(self):
        self.assertEqual(rigor.leak_scan("-" + QUOTE + "\n " + QUOTE + "\n+short reason\n", [self.case]), [])

    def test_a_partial_run_shorter_than_eight_words_is_not_flagged(self):
        self.assertEqual(rigor.leak_scan("+Docstring edit puts the new text inside\n", [self.case]), [])


def git(root, *a):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(root), *a], capture_output=True, text=True, check=True).stdout.strip()


class CaseStartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        git(self.root, "init", "-q", "-b", "main")
        (self.root / "f.py").write_text("x = 1\n", encoding="utf-8")
        git(self.root, "add", "."); git(self.root, "commit", "-q", "-m", "pre")
        self.pre = git(self.root, "rev-parse", "HEAD")
        (self.root / "f.py").write_text("x = 1\nfixed_marker = True\n", encoding="utf-8")
        git(self.root, "commit", "-qam", "fix")
        self.fix = git(self.root, "rev-parse", "HEAD")

    def tearDown(self):
        self.tmp.cleanup()

    def case(self, base, **kw):
        return {"id": "c", "kind": "trajectory", "baseSha": base, "fixSha": self.fix, **kw}

    def test_the_pre_fix_commit_is_clean(self):
        self.assertEqual(rigor.case_start_warnings(self.root, self.case(self.pre)), [])

    def test_a_base_that_already_has_the_fix_warns(self):
        w = rigor.case_start_warnings(self.root, self.case(self.fix))
        self.assertEqual(len(w), 1)
        self.assertIn("already contains the fix", w[0])

    def test_the_fix_sha_is_read_from_fixedIn_when_not_given(self):
        c = {"id": "c", "kind": "trajectory", "baseSha": self.fix, "fixedIn": f"harness/x ({self.fix[:7]}), merged"}
        self.assertEqual(len(rigor.case_start_warnings(self.root, c)), 1)

    def test_an_expected_file_that_already_carries_the_fix_text_warns(self):
        w = rigor.case_start_warnings(self.root, self.case(self.fix, expectedFile="f.py", fixText="fixed_marker = True"))
        self.assertTrue(any("already contains the fix text" in x for x in w))
        self.assertEqual(rigor.case_start_warnings(self.root, self.case(self.pre, expectedFile="f.py", fixText="fixed_marker = True")), [])

    def test_flags_cases_and_unknown_bases_are_skipped(self):
        self.assertEqual(rigor.case_start_warnings(self.root, {"id": "f", "baseSha": self.fix}), [])
        self.assertEqual(rigor.case_start_warnings(self.root, self.case("0" * 40)), [])


class WhyHardTests(unittest.TestCase):
    def test_status(self):
        self.assertEqual(rigor.why_hard_status({"whyHard": "Because the hook never looked at lint."}), "ok")
        self.assertEqual(rigor.why_hard_status({"promotedAt": "2026-10-16T00:00:00Z"}), "missing")
        self.assertEqual(rigor.why_hard_status({"promotedAt": "x", "whyHard": rigor.WHY_HARD_PLACEHOLDER}), "missing")
        self.assertEqual(rigor.why_hard_status({"promotedAt": "x", "whyHard": "  "}), "missing")
        self.assertEqual(rigor.why_hard_status({"whyHard": rigor.WHY_HARD_PLACEHOLDER}), "missing")
        self.assertEqual(rigor.why_hard_status({"id": "old"}), "legacy")

    def make_root(self, tmp, cases):
        root = Path(tmp)
        (root / "harness/cases").mkdir(parents=True)
        for c in cases:
            (root / "harness/cases" / f"{c['id']}.json").write_text(json.dumps(c), encoding="utf-8")
        return root

    def test_lint_cases_refuses_and_warns(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.make_root(d, [
                {"id": "promoted", "kind": "trajectory", "promotedAt": "2026-10-16T00:00:00Z", "whyHard": rigor.WHY_HARD_PLACEHOLDER},
                {"id": "legacy", "kind": "trajectory"},
                {"id": "good", "kind": "trajectory", "whyHard": "a real reason", "promotedAt": "2026-10-16T00:00:00Z"},
                {"id": "flags", "expect": {}}])
            lines, refused = rigor.lint_cases(root)
        self.assertEqual(refused, 1)
        self.assertTrue(any(l.startswith("REFUSE") and "promoted" in l and "case-missing-why-hard" in l for l in lines))
        self.assertTrue(any(l.startswith("WARN") and "legacy" in l and "legacy-no-why-hard" in l for l in lines))
        self.assertFalse(any("good" in l or "flags" in l for l in lines))
        self.assertFalse(any(l.startswith(("PASS", "FAIL")) for l in lines))

    def test_cli_why_hard_refuses_with_exit_3_and_writes_the_verdict(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.make_root(d, [{"id": "p", "kind": "trajectory", "promotedAt": "x"}])
            rc = rigor.main(["why-hard", str(root / "harness/cases/p.json")])
            v = json.loads((root / "runs/proofs/p/verdict.json").read_text(encoding="utf-8"))
        self.assertEqual(rc, 3)
        self.assertEqual(v["verdict"], "case-missing-why-hard")

    def test_cli_why_hard_lets_a_legacy_case_run(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.make_root(d, [{"id": "old", "kind": "trajectory"}])
            self.assertEqual(rigor.main(["why-hard", str(root / "harness/cases/old.json")]), 0)

    def test_cli_noise_gate_exits_3_with_the_verdict_and_0_without_a_control_arm(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for arm, s in (("current", summ(1, 3)), ("control", summ(3, 3))):
                (root / "runs/proofs/c" / arm).mkdir(parents=True)
                (root / "runs/proofs/c" / arm / "summary.json").write_text(json.dumps(s), encoding="utf-8")
            self.assertEqual(rigor.main(["noise-gate", str(root), "c"]), 3)
            v = json.loads((root / "runs/proofs/c/verdict.json").read_text(encoding="utf-8"))
            self.assertEqual((v["verdict"], v["minDetectableDelta"]), ("noise-too-high", 0.1))
            self.assertEqual(rigor.main(["noise-gate", str(root), "c", "--min-detectable-delta", "0.9"]), 0)
            (root / "runs/proofs/c/control/summary.json").unlink()
            self.assertEqual(rigor.main(["noise-gate", str(root), "c"]), 0)


class ShippedCasesTests(unittest.TestCase):
    def test_the_two_shipped_trajectory_cases_carry_a_written_why_hard(self):
        root = Path(__file__).resolve().parents[2]
        for cid in ("lint-on-result", "lint-in-quick-checks"):
            case = json.loads((root / "harness/cases" / f"{cid}.json").read_text(encoding="utf-8"))
            self.assertEqual(rigor.why_hard_status(case), "ok", cid)
            self.assertGreater(len(case["whyHard"]), 80)

    def test_the_shipped_cases_start_at_the_pre_fix_commit(self):
        root = Path(__file__).resolve().parents[2]
        lines, refused = rigor.lint_cases(root)
        self.assertEqual(refused, 0)
        self.assertFalse([l for l in lines if "case-start-carries-answer" in l], lines)


if __name__ == "__main__":
    unittest.main()
