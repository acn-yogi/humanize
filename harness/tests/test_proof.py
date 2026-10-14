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
    def make(self, before, after, judges=("earned", "earned", "earned"), cases="PASS  x\nPASS  y\n", before_fp=None, after_fp=None):
        d = Path(self.tmp.name)
        (d / "harness/cases").mkdir(parents=True, exist_ok=True)
        (d / "harness/cases/c.json").write_text(json.dumps({"id": "c", "kind": "trajectory", "spec": "0002-bugfix-precisedelta-sign", "k": 3, "failureClass": "REVIEW_REJECTED", "reasonCode": "lint", "fixBranch": "harness/x"}), encoding="utf-8")
        p = d / "runs/proofs/c"
        (p / "current").mkdir(parents=True, exist_ok=True)
        (p / "candidate").mkdir(parents=True, exist_ok=True)
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
