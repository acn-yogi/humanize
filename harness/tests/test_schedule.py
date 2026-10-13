"""Schedule entries: due or not, and the recurring spec an entry enqueues."""

from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import schedule  # noqa: E402
from cron import CronError  # noqa: E402

UTC = dt.timezone.utc
CONFIG = {"triggers": {"schedule": [
    {"cron": "*/30 * * * *", "tz": "UTC", "take": "queue"},
    {"cron": "0 6 * * 1", "tz": "UTC", "spec": "flaky-test-hunt"},
]}}
TEMPLATE = '+++\ntitle = "Flaky test hunt"\nclass = "maintenance"\nstatus = "draft"\napproved_by = "yogi.aradhye"\nscope = ["tests/**"]\n\n[checks]\nquick = ["python {harness}/checks/suite_repeat.py --times 2"]\n+++\n\n# Flaky test hunt\n\nBody.\n'


class EntryTests(unittest.TestCase):
    def test_default_entry_when_none_configured(self):
        self.assertEqual(schedule.load_entries({}), [{"cron": "*/30 * * * *", "tz": "UTC", "take": "queue"}])

    def test_entries_need_take_or_spec(self):
        with self.assertRaises(CronError):
            schedule.load_entries({"triggers": {"schedule": [{"cron": "* * * * *"}]}})
        with self.assertRaises(CronError):
            schedule.load_entries({"triggers": {"schedule": [{"cron": "* * * * *", "take": "queue", "spec": "x"}]}})

    def test_evaluate_due_and_next(self):
        rows = schedule.evaluate(CONFIG, dt.datetime(2026, 10, 12, 6, 0, tzinfo=UTC))  # a Monday, 06:00
        self.assertEqual([r["due"] for r in rows], [True, True])
        self.assertEqual(rows[0]["what"], "take the approved queue")
        self.assertEqual(rows[1]["what"], "enqueue recurring spec flaky-test-hunt")
        self.assertEqual(rows[1]["next"], ["2026-10-19T06:00+00:00", "2026-10-26T06:00+00:00"])
        rows = schedule.evaluate(CONFIG, dt.datetime(2026, 10, 13, 9, 7, tzinfo=UTC))
        self.assertEqual([r["due"] for r in rows], [False, False])
        self.assertEqual(rows[0]["next"][0], "2026-10-13T09:30+00:00")


class EnqueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.harness = root / "harness"
        (self.harness / "recurring").mkdir(parents=True)
        (self.harness / "recurring/flaky-test-hunt.md").write_text(TEMPLATE, encoding="utf-8")
        self.specs = root / "specs"
        self.specs.mkdir()
        (self.specs / "0010-docs-x.md").write_text('+++\nid = "0010-docs-x"\n+++\n# x\n', encoding="utf-8")
        self.ledger = root / "ledger.jsonl"
        self.day = dt.date(2026, 10, 12)

    def tearDown(self):
        self.tmp.cleanup()

    def test_enqueue_writes_a_dated_approved_spec(self):
        r = schedule.enqueue(self.harness, self.specs, "flaky-test-hunt", self.ledger, self.day, dry_run=False)
        self.assertTrue(r["written"])
        self.assertEqual(r["id"], "0011-flaky-test-hunt-20261012")
        self.assertEqual(r["trigger"], "schedule:flaky-test-hunt:2026-10-12")
        self.assertEqual(r["status"], "approved")
        text = (self.specs / "0011-flaky-test-hunt-20261012.md").read_text(encoding="utf-8")
        meta, _, body = schedule.read_front_matter(self.specs / "0011-flaky-test-hunt-20261012.md")
        self.assertEqual(meta["id"], "0011-flaky-test-hunt-20261012")
        self.assertEqual(meta["status"], "approved")
        self.assertEqual(meta["approved_by"], "yogi.aradhye")
        self.assertEqual(meta["trigger"], "schedule:flaky-test-hunt:2026-10-12")
        self.assertEqual(meta["class"], "maintenance")
        self.assertEqual(text.count('status = "'), 1)
        self.assertIn("# Flaky test hunt", body)

    def test_one_per_day(self):
        schedule.enqueue(self.harness, self.specs, "flaky-test-hunt", self.ledger, self.day, dry_run=False)
        r = schedule.enqueue(self.harness, self.specs, "flaky-test-hunt", self.ledger, self.day, dry_run=False)
        self.assertFalse(r["written"])
        self.assertIn("already enqueued", r["reason"])
        r = schedule.enqueue(self.harness, self.specs, "flaky-test-hunt", self.ledger, self.day + dt.timedelta(days=7), dry_run=False)
        self.assertTrue(r["written"])
        self.assertEqual(r["id"], "0012-flaky-test-hunt-20261019")

    def test_ledger_row_dedupes_too(self):
        self.ledger.write_text(json.dumps({"spec": "0011-flaky-test-hunt-20261012", "trigger": "schedule:flaky-test-hunt:2026-10-12", "costUsd": 0.3}) + "\n", encoding="utf-8")
        r = schedule.enqueue(self.harness, self.specs, "flaky-test-hunt", self.ledger, self.day, dry_run=False)
        self.assertFalse(r["written"])

    def test_dry_run_writes_nothing(self):
        r = schedule.enqueue(self.harness, self.specs, "flaky-test-hunt", self.ledger, self.day, dry_run=True)
        self.assertFalse(r["written"])
        self.assertEqual(r["id"], "0011-flaky-test-hunt-20261012")
        self.assertEqual(sorted(p.name for p in self.specs.iterdir()), ["0010-docs-x.md"])

    def test_unknown_template_and_bad_names(self):
        self.assertFalse(schedule.enqueue(self.harness, self.specs, "nope", self.ledger, self.day, False)["written"])
        self.assertFalse(schedule.enqueue(self.harness, self.specs, "../x", self.ledger, self.day, False)["written"])

    def test_template_without_approver_stays_a_draft(self):
        (self.harness / "recurring/sweep.md").write_text('+++\ntitle = "x"\nclass = "maintenance"\n+++\n# x\n', encoding="utf-8")
        r = schedule.enqueue(self.harness, self.specs, "sweep", self.ledger, self.day, False)
        self.assertEqual(r["status"], "draft")

    def test_template_with_an_id_is_refused(self):
        (self.harness / "recurring/bad.md").write_text('+++\nid = "0001-bad"\nclass = "maintenance"\n+++\n# x\n', encoding="utf-8")
        r = schedule.enqueue(self.harness, self.specs, "bad", self.ledger, self.day, False)
        self.assertFalse(r["written"])
        self.assertIn("no id", r["reason"])


if __name__ == "__main__":
    unittest.main()
