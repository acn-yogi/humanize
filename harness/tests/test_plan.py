"""plan.py on the classes build and llm-tune, the [eval] table and the negatives (must_not_change)."""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import plan  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "harness"

FRONT = """+++
id = "{id}"
title = "t"
class = "{cls}"
status = "draft"
scope = ["src/humanize/number.py", "tests/test_number.py"]
{extra}
+++

# Body
"""


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "harness").mkdir()
        for f in ("config.toml", "classes.toml"):
            shutil.copy(HARNESS / f, d / "harness" / f)
        (d / "specs").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def spec(self, spec_id: str, cls: str, extra: str = "") -> Path:
        p = Path(self.tmp.name) / "specs" / f"{spec_id}.md"
        p.write_text(FRONT.format(id=spec_id, cls=cls, extra=extra), encoding="utf-8")
        return p

    def build(self, p: Path) -> dict:
        return plan.build_plan(Path(self.tmp.name) / "harness", p)

    def test_build_class_is_per_pr_fail_first_with_no_flag(self):
        row = self.build(self.spec("0101-build", "build", '[checks]\nfail_first = ["python x.py"]\nacceptance = ["python x.py"]'))
        self.assertEqual(row["classRow"]["approval"], "per_pr")
        self.assertIs(row["classRow"]["fail_first"], True)
        self.assertEqual(row["classRow"]["flag"], "none")
        self.assertEqual(row["checks"]["failFirst"], ["python x.py"])
        self.assertIsNone(row["eval"])

    def test_build_class_refuses_a_spec_without_fail_first(self):
        with self.assertRaises(SystemExit):
            self.build(self.spec("0102-build", "build"))

    def test_llm_tune_refuses_a_spec_without_an_eval_table(self):
        with self.assertRaises(SystemExit):
            self.build(self.spec("0103-tune", "llm-tune"))

    def test_llm_tune_refuses_an_eval_table_without_a_holdout(self):
        with self.assertRaises(SystemExit):
            self.build(self.spec("0104-tune", "llm-tune", '[eval]\ncommand = "python evals/run.py"'))

    def test_llm_tune_carries_the_eval_and_the_hillclimb_template(self):
        row = self.build(self.spec("0105-tune", "llm-tune",
                                   '[eval]\ncommand = "python evals/run.py --set {set}"\nholdout = "evals/holdout.jsonl"\ntraining = "evals/train.jsonl"'))
        self.assertEqual(row["eval"], {"command": "python evals/run.py --set {set}", "holdout": "evals/holdout.jsonl", "training": "evals/train.jsonl"})
        self.assertEqual(row["classRow"]["approval"], "per_pr")
        self.assertIn("One lever per round", row["classTemplate"])
        self.assertIn("holdout", row["classTemplate"])

    def test_other_classes_carry_no_template(self):
        row = self.build(self.spec("0106-docs", "docs"))
        self.assertEqual(row["classTemplate"], "")

    def test_negatives_are_exposed_and_optional(self):
        row = self.build(self.spec("0107-feat", "feature", '[checks]\nmust_not_change = ["python -m pytest -q tests/test_number.py -k intcomma"]'))
        self.assertEqual(row["checks"]["mustNotChange"], ["python -m pytest -q tests/test_number.py -k intcomma"])
        self.assertEqual(self.build(self.spec("0108-feat", "feature"))["checks"]["mustNotChange"], [])

    def test_negatives_must_be_a_list_of_strings(self):
        with self.assertRaises(SystemExit):
            self.build(self.spec("0109-feat", "feature", '[checks]\nmust_not_change = "python x.py"'))

    def test_the_committed_specs_still_plan(self):
        for p in sorted((ROOT / "specs").glob("[0-9]*.md")):
            row = plan.build_plan(HARNESS, p)
            self.assertIn("mustNotChange", row["checks"], p.name)


if __name__ == "__main__":
    unittest.main()
