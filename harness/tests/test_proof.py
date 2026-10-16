"""The proof's verdict: SHIP only when reproduced, after pass^k 1, no regression, every judge earned."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import proof  # noqa: E402

T = ["t-01M4TW8TYH7AES6AB31KYJ3GMQ", "t-01M4TWAAAAAAAAAAAAAAAAAAAA", "t-01M4TWBBBBBBBBBBBBBBBBBBBB"]


def run(i, outcome, task, cost=0.4, why=""):
    return {"trial": i, "taskId": task, "outcome": outcome, "why": why, "checksPass": True, "reviewVerdict0": "approve" if outcome == "pass" else "reject",
            "ruffOk": outcome == "pass", "ruffFindings": 0 if outcome == "pass" else 3, "stopBlocks": 0, "costUsd": cost, "workerTurns": 8}


def fp(pack, version="2.1.296 (Claude Code)", author="claude-sonnet-5-5"):
    return {"packId": f"pack-{pack}", "claudeCodeVersion": version, "servedModel": {"author": author, "reviewer": "claude-opus-5-5"}}


def summary(pack, outcomes, base="main", fingerprints=None):
    runs = [run(i + 1, o, T[i]) for i, o in enumerate(outcomes)]
    passes = len([r for r in runs if r["outcome"] == "pass"])
    return {"case": "c", "pack": pack, "base": base, "baseSha": "a" * 40, "spec": "0002-bugfix-precisedelta-sign", "k": 3, "trials": len(runs),
            "passes": passes, "passK": 1 if passes == len(runs) else 0, "costUsd": sum(r["costUsd"] for r in runs), "packIds": [f"pack-{pack}"],
            "fingerprints": fingerprints or [], "runs": runs}


class ProofTests(unittest.TestCase):
    def make(self, before, after, judges=("earned", "earned", "earned"), cases="PASS  x\nPASS  y\n", before_fp=None, after_fp=None,
             control=None, holdout=None, held=None, judge_extra=None, case_extra=None, **kw):
        d = Path(self.tmp.name)
        (d / "harness/cases").mkdir(parents=True, exist_ok=True)
        case = {"id": "c", "kind": "trajectory", "spec": "0002-bugfix-precisedelta-sign", "k": 3, "failureClass": "REVIEW_REJECTED", "reasonCode": "lint", "fixBranch": "harness/x"}
        if holdout:
            case["holdout"] = holdout
        case.update(case_extra or {})
        (d / "harness/cases/c.json").write_text(json.dumps(case), encoding="utf-8")
        p = d / "runs/proofs/c"
        (p / "current").mkdir(parents=True, exist_ok=True)
        (p / "candidate").mkdir(parents=True, exist_ok=True)
        if control is not None:
            (p / "control").mkdir(parents=True, exist_ok=True)
            (p / "control/summary.json").write_text(json.dumps(summary("control", control)), encoding="utf-8")
        for cid, (hb, ha) in (held or {}).items():
            hp = d / "runs/proofs" / cid
            (hp / "current").mkdir(parents=True, exist_ok=True)
            (hp / "candidate").mkdir(parents=True, exist_ok=True)
            if hb is not None:
                (hp / "current/summary.json").write_text(json.dumps(summary("current", hb)), encoding="utf-8")
            if ha is not None:
                (hp / "candidate/summary.json").write_text(json.dumps(summary("candidate", ha, "harness/x")), encoding="utf-8")
        if before is not None:
            (p / "current/summary.json").write_text(json.dumps(summary("current", before, fingerprints=before_fp)), encoding="utf-8")
        if after is not None:
            (p / "candidate/summary.json").write_text(json.dumps(summary("candidate", after, "harness/x", fingerprints=after_fp)), encoding="utf-8")
            for i, verdict in enumerate(judges):
                if i < len(after):
                    (p / "candidate" / T[i]).mkdir(parents=True, exist_ok=True)
                    (p / "candidate" / T[i] / "judge.json").write_text(json.dumps({"verdict": verdict, "quote": "ruff check", "reasons": ["ran ruff"], "quoteFound": True, "model": "opus", "workerModel": "sonnet", "costUsd": 0.05, **(judge_extra or {})}), encoding="utf-8")
        return proof.build(d, "c", "harness/x", cases, **({"pack_diff": ""} | kw))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_ship_when_everything_holds(self):
        v = self.make(["fail", "pass", "fail"], ["pass", "pass", "pass"])
        self.assertEqual(v["verdict"], "SHIP")
        self.assertEqual(v["before"]["passK"], 0)
        self.assertEqual(v["after"]["passK"], 1)
        self.assertEqual(v["regressions"], 0)
        self.assertAlmostEqual(v["costUsd"]["judge"], 0.15)
        self.assertAlmostEqual(v["costUsd"]["total"], 1.2 + 1.2 + 0.15)

    def test_not_reproduced_is_no_ship(self):
        v = self.make(["pass", "pass", "pass"], ["pass", "pass", "pass"])
        self.assertEqual(v["verdict"], "NO-SHIP")
        self.assertTrue(any("not reproduced" in r for r in v["reasons"]))

    def test_after_must_be_pass_k_one(self):
        v = self.make(["fail", "fail", "fail"], ["pass", "fail", "pass"])
        self.assertEqual(v["verdict"], "NO-SHIP")
        self.assertTrue(any("after pass^k is 0" in r for r in v["reasons"]))

    def test_a_regression_blocks(self):
        v = self.make(["fail", "pass", "pass"], ["pass", "pass", "pass"], cases="PASS  x\nFAIL  y: broke\n")
        self.assertEqual(v["verdict"], "NO-SHIP")
        self.assertEqual(v["regressions"], 1)

    def test_a_gamed_or_unknown_judge_blocks(self):
        v = self.make(["fail", "pass", "pass"], ["pass", "pass", "pass"], judges=("earned", "unknown", "earned"))
        self.assertEqual(v["verdict"], "NO-SHIP")
        self.assertTrue(any(r.startswith("judge:") for r in v["reasons"]))

    def test_no_judge_blocks(self):
        v = self.make(["fail", "pass", "pass"], ["pass", "pass", "pass"], judges=())
        self.assertIn("no judge verdict on record", v["reasons"])

    def test_missing_sides_are_named(self):
        v = self.make(None, None, judges=())
        self.assertIn("no reproduce trials on record", v["reasons"])
        self.assertIn("no candidate trials on record", v["reasons"])

    def test_same_environment_with_a_new_pack_compares(self):
        v = self.make(["fail", "pass", "fail"], ["pass", "pass", "pass"], before_fp=[fp("current")], after_fp=[fp("candidate")])
        self.assertEqual(v["fingerprint"]["comparison"], "valid")
        self.assertEqual(v["verdict"], "SHIP")

    def test_a_different_environment_voids_the_comparison(self):
        v = self.make(["fail", "pass", "fail"], ["pass", "pass", "pass"], before_fp=[fp("current")], after_fp=[fp("candidate", version="2.2.0 (Claude Code)")])
        self.assertEqual(v["fingerprint"]["comparison"], "invalid-fingerprint")
        self.assertEqual(v["verdict"], "NO-SHIP")
        self.assertTrue(any(r.startswith("invalid-fingerprint") for r in v["reasons"]))
        self.assertIn("comparison             invalid-fingerprint", proof.table(v))

    def test_a_served_model_switch_voids_the_comparison(self):
        v = self.make(["fail", "pass", "fail"], ["pass", "pass", "pass"], before_fp=[fp("current")], after_fp=[fp("candidate", author="claude-haiku-5")])
        self.assertEqual(v["fingerprint"]["comparison"], "invalid-fingerprint")

    def test_recorded_proofs_without_fingerprints_say_so_and_still_ship(self):
        v = self.make(["fail", "pass", "fail"], ["pass", "pass", "pass"])
        self.assertEqual(v["fingerprint"]["comparison"], "fingerprint-not-recorded")
        self.assertEqual(v["verdict"], "SHIP")

    def test_no_control_arm_says_the_floor_is_not_measured_and_does_not_block(self):
        v = self.make(["fail", "pass", "fail"], ["pass", "pass", "pass"])
        self.assertFalse(v["control"]["present"])
        self.assertIsNone(v["control"]["noiseFloor"])
        self.assertEqual(v["verdict"], "SHIP")
        self.assertIn("control: no control arm: noise floor not measured", proof.table(v))

    def test_a_delta_inside_the_noise_floor_is_too_small_to_see(self):
        # Current pack twice: 1 of 3 then 3 of 3, a spread of 0.67; the candidate's 3 of 3 is inside it.
        v = self.make(["fail", "pass", "fail"], ["pass", "pass", "pass"], control=["pass", "pass", "pass"], min_detectable_delta=1.0)
        self.assertTrue(v["control"]["present"])
        self.assertAlmostEqual(v["control"]["noiseFloor"], 0.6667)
        self.assertAlmostEqual(v["control"]["delta"], 0.6667)
        self.assertTrue(v["control"]["tooSmallToSee"])
        self.assertEqual(v["verdict"], "NO-SHIP")
        self.assertTrue(any(r.startswith("too-small-to-see") for r in v["reasons"]))
        self.assertIn("too small to see", proof.table(v))

    def test_a_delta_outside_the_noise_floor_ships(self):
        # Current pack twice: 0 of 3 both times, floor 0; the candidate's 3 of 3 is a real move.
        v = self.make(["fail", "fail", "fail"], ["pass", "pass", "pass"], control=["fail", "fail", "fail"])
        self.assertEqual(v["control"]["noiseFloor"], 0.0)
        self.assertFalse(v["control"]["tooSmallToSee"])
        self.assertEqual(v["verdict"], "SHIP")
        self.assertAlmostEqual(v["costUsd"]["control"], 1.2)
        self.assertAlmostEqual(v["costUsd"]["total"], 1.2 * 3 + 0.15)

    def test_no_holdout_says_the_suite_is_too_small(self):
        v = self.make(["fail", "pass", "fail"], ["pass", "pass", "pass"])
        self.assertFalse(v["holdout"]["present"])
        self.assertIn("holdout: no holdout: suite too small", proof.table(v))

    def test_the_held_out_delta_is_reported_apart(self):
        v = self.make(["fail", "fail", "fail"], ["pass", "pass", "pass"], holdout=["h1", "h2"],
                      held={"h1": (["fail", "fail", "pass"], ["pass", "pass", "pass"]), "h2": (["fail", "fail", "fail"], ["fail", "fail", "fail"])})
        h = v["holdout"]
        self.assertTrue(h["present"])
        self.assertEqual([r["case"] for r in h["cases"]], ["h1", "h2"])
        self.assertAlmostEqual(h["beforeRate"], 1 / 6, places=3)
        self.assertAlmostEqual(h["afterRate"], 0.5)
        self.assertAlmostEqual(h["delta"], 1 / 3, places=3)
        self.assertEqual(h["unrun"], [])
        text = proof.table(v)
        self.assertIn("holdout (2 case(s) the improver never read)", text)
        self.assertIn("h2", text)
        # The training case still ships: the held-out delta is reported, not gated on, until the suite can be split.
        self.assertEqual(v["verdict"], "SHIP")

    def test_a_held_out_case_not_yet_run_is_named(self):
        v = self.make(["fail", "fail", "fail"], ["pass", "pass", "pass"], holdout=["h1"], held={"h1": (["fail", "pass", "pass"], None)})
        self.assertEqual(v["holdout"]["unrun"], ["h1"])
        self.assertIn("not run on both packs yet", v["holdout"]["note"])

    def test_case_write_carries_control_and_holdout(self):
        v = self.make(["fail", "fail", "fail"], ["pass", "pass", "pass"], control=["fail", "fail", "fail"], holdout=["h1"],
                      held={"h1": (["fail"], ["pass"])})
        case = json.loads(proof.write_case(Path(self.tmp.name), v).read_text(encoding="utf-8"))
        self.assertEqual(case["proof"]["control"], {"noiseFloor": 0.0, "delta": 1.0, "tooSmallToSee": False})
        self.assertEqual(case["proof"]["holdout"]["cases"], ["h1"])
        self.assertEqual(case["proof"]["fingerprint"], "fingerprint-not-recorded")

    # Rigor from the eval design article (rigor.py): the gates, suite sanity, rule, leaks, parity.

    def put_cost(self, arm, per_trial):
        f = Path(self.tmp.name) / "runs/proofs/c" / arm / "summary.json"
        sm = json.loads(f.read_text(encoding="utf-8"))
        for r in sm["runs"]:
            r["costUsd"] = per_trial
        sm["costUsd"] = per_trial * len(sm["runs"])
        f.write_text(json.dumps(sm), encoding="utf-8")

    def test_noise_too_high_when_the_control_floor_exceeds_the_minimum_detectable_delta(self):
        v = self.make(["fail", "pass", "fail"], ["pass", "pass", "pass"], control=["pass", "pass", "pass"])
        self.assertEqual(v["verdict"], "noise-too-high")
        self.assertEqual(v["minDetectableDelta"], 0.1)
        self.assertTrue(v["reasons"][0].startswith("noise-too-high"))
        self.assertIn("add repetitions or cases", v["reasons"][0])

    def test_a_floor_at_or_under_the_minimum_detectable_delta_passes_the_gate(self):
        v = self.make(["fail", "fail", "fail"], ["pass", "pass", "pass"], control=["fail", "fail", "fail"])
        self.assertEqual(v["verdict"], "SHIP")
        v2 = self.make(["fail", "pass", "fail"], ["pass", "pass", "pass"], control=["fail", "fail", "fail"], min_detectable_delta=0.5)
        self.assertNotEqual(v2["verdict"], "noise-too-high")

    def test_no_control_arm_leaves_behaviour_unchanged_whatever_the_delta(self):
        v = self.make(["fail", "pass", "fail"], ["pass", "pass", "pass"], min_detectable_delta=0.0)
        self.assertEqual(v["verdict"], "SHIP")
        self.assertEqual(v["minDetectableDelta"], 0.0)

    def test_suite_sanity_names_a_saturated_suite_and_suggests_cost_at_parity(self):
        v = self.make(["pass"] * 3, ["pass"] * 3)
        self.assertEqual(v["suite"], {"baselinePassRate": 1.0, "saturated": True, "objectiveSuggestion": "cost-at-parity"})
        v2 = self.make(["fail", "pass", "fail"], ["pass"] * 3)
        self.assertEqual(v2["suite"], {"baselinePassRate": 0.3333, "saturated": False, "objectiveSuggestion": None})

    def test_a_case_that_failed_every_replicate_in_every_arm_is_impossible_or_ambiguous(self):
        v = self.make(["fail"] * 3, ["fail"] * 3, control=["fail"] * 3, holdout=["h1", "h2"],
                      held={"h1": (["fail", "pass"], ["pass", "pass"]), "h2": (["fail", "fail"], ["fail", "fail"])})
        self.assertEqual(v["impossibleOrAmbiguous"], ["c", "h2"])
        v2 = self.make(["fail", "pass", "fail"], ["pass"] * 3)
        self.assertEqual(v2["impossibleOrAmbiguous"], [])

    def test_a_case_with_one_arm_only_is_not_called_impossible(self):
        v = self.make(["fail"] * 3, None, judges=())
        self.assertEqual(v["impossibleOrAmbiguous"], [])

    def test_grader_agreement_is_pooled_over_the_judges_and_null_without_one(self):
        v = self.make(["fail", "pass", "fail"], ["pass"] * 3, judge_extra={"graderAgreement": {"runs": 3, "agreed": 2, "disagreeing": 1}})
        self.assertEqual(v["graderAgreement"], {"runs": 9, "agreed": 6, "disagreeing": 3})
        self.assertIsNone(self.make(["fail", "pass", "fail"], ["pass"] * 3)["graderAgreement"])
        self.assertIsNone(self.make(["fail", "pass", "fail"], ["pass"] * 3, judges=())["graderAgreement"])

    def test_a_judge_that_is_the_worker_model_is_not_independent(self):
        v = self.make(["fail", "pass", "fail"], ["pass"] * 3, judge_extra={"judgeModel": "sonnet", "model": "sonnet"})
        self.assertEqual(v["verdict"], "judge-not-independent")
        v2 = self.make(["fail", "pass", "fail"], ["pass"] * 3, judges=("judge-not-independent",) * 3)
        self.assertEqual(v2["verdict"], "judge-not-independent")
        self.assertEqual(self.make(["fail", "pass", "fail"], ["pass"] * 3)["judge"][0]["judgeModel"], "opus")

    def test_rule_is_absent_without_a_holdout_and_keep_when_both_improve(self):
        self.assertIsNone(self.make(["fail", "pass", "fail"], ["pass"] * 3)["rule"])
        v = self.make(["fail"] * 3, ["pass"] * 3, holdout=["h1"], held={"h1": (["fail", "fail"], ["pass", "fail"])})
        self.assertEqual(v["rule"]["decision"], "keep")
        self.assertEqual(v["rule"]["trainDelta"], 1.0)
        self.assertEqual(v["rule"]["heldOutDelta"], 0.5)

    def test_rule_overfit_suspected_when_train_is_up_and_held_out_is_flat_or_down(self):
        flat = self.make(["fail"] * 3, ["pass"] * 3, holdout=["h1"], held={"h1": (["fail", "pass"], ["fail", "pass"])})
        self.assertEqual(flat["rule"]["decision"], "overfit-suspected")
        down = self.make(["fail"] * 3, ["pass"] * 3, holdout=["h1"], held={"h1": (["pass", "pass"], ["pass", "fail"])})
        self.assertEqual(down["rule"]["decision"], "overfit-suspected")
        self.assertEqual(down["verdict"], "SHIP")   # informational: the rule never changes the verdict

    def test_rule_revert_on_any_regression(self):
        v = self.make(["fail", "fail", "pass"], ["pass"] * 3, cases="PASS  x\nFAIL  y\n", holdout=["h1"], held={"h1": (["fail"], ["pass"])})
        self.assertEqual(v["rule"]["decision"], "revert")
        worse = self.make(["pass", "fail", "fail"], ["fail"] * 3, holdout=["h1"], held={"h1": (["fail"], ["pass"])})
        self.assertEqual(worse["rule"]["decision"], "revert")

    def test_rule_has_no_decision_while_the_held_out_arm_is_unrun(self):
        v = self.make(["fail"] * 3, ["pass"] * 3, holdout=["h1"], held={"h1": (["fail"], None)})
        self.assertIsNone(v["rule"]["decision"])
        self.assertIn("not run", v["rule"]["note"])

    def test_pack_embeds_failure_warns_by_default_and_blocks_on_request(self):
        diff = ("diff --git a/harness/pack/x.md b/harness/pack/x.md\n+++ b/harness/pack/x.md\n"
                "+Never write c as a case id here\n"
                "+Docstring edit puts the new text inside the unclosed 0 minutes example which breaks docs\n")
        case_extra = {"hits": [{"text": "Docstring edit puts the new text inside the unclosed '0 minutes' example, which breaks the docs"}]}
        warn = self.make(["fail", "pass", "fail"], ["pass"] * 3, case_extra=case_extra, pack_diff=diff)
        self.assertEqual(warn["verdict"], "SHIP")
        self.assertEqual({l["kind"] for l in warn["leaks"]}, {"failure-quote", "case-id"})
        self.assertTrue(all(l["check"] == "pack-embeds-failure" for l in warn["leaks"]))
        self.assertIn("leak (pack-embeds-failure)", proof.table(warn))
        block = self.make(["fail", "pass", "fail"], ["pass"] * 3, case_extra=case_extra, pack_diff=diff, block_on_leak=True)
        self.assertEqual(block["verdict"], "pack-embeds-failure")

    def test_a_clean_pack_diff_has_no_leaks(self):
        v = self.make(["fail", "pass", "fail"], ["pass"] * 3, pack_diff="+++ b/harness/hooks/stop-checks.sh\n+ruff check --no-fix src tests\n", block_on_leak=True)
        self.assertEqual(v["leaks"], [])
        self.assertEqual(v["verdict"], "SHIP")

    def test_cost_at_parity_is_cost_not_lower_when_the_candidate_costs_the_same(self):
        v = self.make(["pass"] * 3, ["pass"] * 3, objective="cost-at-parity")
        self.assertEqual(v["objective"], "cost-at-parity")
        self.assertEqual(v["verdict"], "cost-not-lower")
        self.assertIn("cost-not-lower", v["reasons"][0])

    def test_cost_at_parity_with_a_cheaper_candidate_ships_even_when_the_case_never_failed(self):
        self.make(["pass"] * 3, ["pass"] * 3, objective="cost-at-parity")
        self.put_cost("candidate", 0.2)
        v = proof.build(Path(self.tmp.name), "c", "harness/x", "PASS  x\n", objective="cost-at-parity", pack_diff="")
        self.assertEqual(v["verdict"], "SHIP")
        self.assertEqual(v["costPerTrial"]["before"], 0.4)
        self.assertEqual(v["costPerTrial"]["after"], 0.2)

    def test_cost_at_parity_needs_the_saving_to_exceed_the_control_cost_spread(self):
        root = Path(self.tmp.name)
        self.make(["pass"] * 3, ["pass"] * 3, control=["pass"] * 3)
        self.put_cost("current", 0.4)
        self.put_cost("control", 0.5)
        self.put_cost("candidate", 0.35)   # saves 0.05; the spread is 0.1
        v = proof.build(root, "c", "harness/x", "PASS  x\n", objective="cost-at-parity", pack_diff="")
        self.assertEqual(v["costPerTrial"]["spread"], 0.1)
        self.assertEqual(v["verdict"], "cost-not-lower")
        self.put_cost("candidate", 0.25)   # saves 0.15, more than the spread
        v = proof.build(root, "c", "harness/x", "PASS  x\n", objective="cost-at-parity", pack_diff="")
        self.assertEqual(v["verdict"], "SHIP")

    def test_cost_at_parity_still_fails_when_accuracy_falls_outside_the_noise_floor(self):
        v = self.make(["pass"] * 3, ["pass", "fail", "fail"], objective="cost-at-parity")
        self.assertEqual(v["verdict"], "NO-SHIP")
        self.assertTrue(any(r.startswith("accuracy fell outside the noise floor") for r in v["reasons"]))

    def test_the_default_objective_is_performance(self):
        v = self.make(["fail", "pass", "fail"], ["pass"] * 3)
        self.assertEqual(v["objective"], "performance")

    def test_a_gate_verdict_does_not_change_the_case_status_on_write(self):
        v = self.make(["fail", "pass", "fail"], ["pass"] * 3, control=["pass"] * 3)
        case = json.loads(proof.write_case(Path(self.tmp.name), v).read_text(encoding="utf-8"))
        self.assertNotIn("status", case)
        self.assertEqual(case["proof"]["verdict"], "noise-too-high")

    def test_table_and_case_write(self):
        v = self.make(["fail", "pass", "fail"], ["pass", "pass", "pass"])
        text = proof.table(v)
        self.assertIn("verdict: SHIP", text)
        self.assertIn("pass^k", text)
        p = proof.write_case(Path(self.tmp.name), v)
        case = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(case["proof"]["verdict"], "SHIP")
        self.assertEqual(case["status"], "proven")
        self.assertEqual(case["provenAt"], v["at"])
        self.assertEqual([j["verdict"] for j in case["proof"]["judge"]], ["earned"] * 3)


if __name__ == "__main__":
    unittest.main()
