"""The negatives (must_not_change): refused at intake when they fail on the base; shown in the packet."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "harness/lib"))
sys.path.insert(0, str(ROOT / "harness/checks"))
_cwd = os.getcwd()
os.chdir(ROOT)  # shape_output reads the repository root from the working directory
import shape_output  # noqa: E402
import evidence  # noqa: E402
os.chdir(_cwd)

RECORDED = sorted((ROOT / "demo/recordings").glob("t-*"))


class IntakeNegativesTests(unittest.TestCase):
    def plan(self, negatives):
        return {"id": "0107-feat", "checks": {"mustNotChange": negatives}}

    def test_negatives_that_hold_on_the_base_pass(self):
        lines = shape_output.negatives_on_base(self.plan(["python -c 'import humanize'"]), lambda c: 0)
        self.assertEqual([ok for _, ok in lines], [True])
        self.assertIn("holds on today's code", lines[0][0])

    def test_a_negative_that_fails_on_the_base_refuses_the_spec_with_the_reason(self):
        ran = []

        def run(c):
            ran.append(c)
            return 1 if "intcomma" in c else 0
        lines = shape_output.negatives_on_base(self.plan(["python -m pytest -q -k intcomma", "python -m pytest -q -k naturalsize"]), run)
        self.assertEqual(ran, ["python -m pytest -q -k intcomma", "python -m pytest -q -k naturalsize"])
        self.assertEqual([ok for _, ok in lines], [False, True])
        self.assertIn("refused", lines[0][0])
        self.assertIn("describes a bug, not an invariant", lines[0][0])
        self.assertIn("(exit 1)", lines[0][0])

    def test_no_negatives_is_fine(self):
        self.assertEqual(shape_output.negatives_on_base(self.plan([]), lambda c: 1), [])


class EvidenceTests(unittest.TestCase):
    def packet(self, **extra):
        p = json.loads((RECORDED[0] / "packet.json").read_text(encoding="utf-8"))
        p.update(extra)
        return p

    def test_a_recorded_packet_still_renders(self):
        text = evidence.render(self.packet())
        self.assertIn("### Provenance", text)
        self.assertNotIn("Must not change", text)
        self.assertNotIn("### Halt", text)

    def test_negatives_are_shown_base_and_result(self):
        neg = {"baseChecks": [{"cmd": "python -m pytest -q -k intcomma", "exit": 0}], "checks": [{"cmd": "python -m pytest -q -k intcomma", "exit": 0, "runs": 1, "flaky": False}], "ok": True, "reasons": []}
        text = evidence.render(self.packet(negatives=neg))
        self.assertIn("**Must not change.**", text)
        self.assertIn("| `python -m pytest -q -k intcomma` | exit 0 (passes, as it must) | exit 0 (still passes) |", text)

    def test_a_broken_negative_is_named(self):
        neg = {"baseChecks": [{"cmd": "x", "exit": 0}], "checks": [{"cmd": "x", "exit": 1, "runs": 1, "flaky": False}], "ok": False, "reasons": ["must-not-change: x fails on the result"]}
        self.assertIn("exit 1 (FAILS: the change broke it)", evidence.render(self.packet(negatives=neg)))

    def test_the_halt_and_the_served_model_are_shown(self):
        p = self.packet(halt={"reason": "stall-structural", "failureClass": "genuine", "stall": "structural", "evidence": "e", "stallEvidence": "scope denials on paths the change needs: tests/test_time.py"},
                        fingerprint={"packId": "pack-x", "claudeCodeVersion": "2.1.296 (Claude Code)", "servedModel": {"author": "claude-sonnet-5-5", "reviewer": "claude-opus-5-5"}})
        text = evidence.render(p)
        self.assertIn("### Halt", text)
        self.assertIn("failure class `genuine`, stall `structural`", text)
        self.assertIn("Served model: author `claude-sonnet-5-5`, reviewer `claude-opus-5-5` (configured `sonnet` / `opus`)", text)


if __name__ == "__main__":
    unittest.main()
