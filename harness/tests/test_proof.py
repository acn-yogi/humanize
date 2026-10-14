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
             control=None, holdout=None, held=None):
        d = Path(self.tmp.name)
        (d / "harness/cases").mkdir(parents=True, exist_ok=True)
        case = {"id": "c", "kind": "trajectory", "spec": "0002-bugfix-precisedelta-sign", "k": 3, "failureClass": "REVIEW_REJECTED", "reasonCode": "lint", "fixBranch": "harness/x"}
        if holdout:
            case["holdout"] = holdout
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
                    (p / "candidate" / T[i] / "judge.json").write_text(json.dumps({"verdict": verdict, "quote": "ruff check", "reasons": ["ran ruff"], "quoteFound": True, "model": "opus", "costUsd": 0.05}), encoding="utf-8")
        return proof.build(d, "c", "harness/x", cases)

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
        v = self.make(["fail", "pass", "fail"], ["pass", "pass", "pass"], control=["pass", "pass", "pass"])
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
