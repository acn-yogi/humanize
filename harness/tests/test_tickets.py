"""The ticket filter, the approver rule and the one-issue-one-task dedupe."""

from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import tickets  # noqa: E402

CONFIG = {"triggers": {"ticket": {"enabled": True, "label": "priority:high", "approvers": ["acn-yogi"]}}}


def issue(n, title="x", state="open", labels=("priority:high",), pr=False):
    d = {"number": n, "title": title, "state": state, "html_url": f"https://github.com/acn-yogi/humanize/issues/{n}",
         "labels": [{"name": lb} for lb in labels]}
    if pr:
        d["pull_request"] = {"url": "..."}
    return d


def ev(event, at, actor=None, label=None):
    d = {"event": event, "created_at": at}
    if actor:
        d["actor"] = {"login": actor}
    if label:
        d["label"] = {"name": label}
    return d


class FilterTests(unittest.TestCase):
    def test_pull_requests_and_closed_and_unlabeled_are_skipped(self):
        rows = tickets.evaluate(CONFIG, [issue(1, pr=True), issue(2, state="closed"), issue(3, labels=("bug",))], {}, {})
        self.assertEqual([r["action"] for r in rows], ["skip"] * 3)
        self.assertIn("pull request", rows[0]["reason"])
        self.assertIn("not open", rows[1]["reason"])
        self.assertIn("no priority:high label", rows[2]["reason"])

    def test_label_by_an_approver_starts_work(self):
        tl = {5: [ev("labeled", "2026-10-13T10:00:00Z", "acn-yogi", "priority:high")]}
        rows = tickets.evaluate(CONFIG, [issue(5)], tl, {})
        self.assertEqual(rows[0]["action"], "start")
        self.assertTrue(rows[0]["matched"])
        self.assertEqual(rows[0]["approver"], "acn-yogi")
        self.assertEqual(rows[0]["trigger"], "ticket:5")
        self.assertIn("approver", rows[0]["reason"])

    def test_label_by_someone_else_is_a_request_not_an_approval(self):
        tl = {5: [ev("labeled", "2026-10-13T10:00:00Z", "somebody", "priority:high")]}
        rows = tickets.evaluate(CONFIG, [issue(5)], tl, {})
        self.assertEqual(rows[0]["action"], "skip")
        self.assertIn("somebody", rows[0]["reason"])
        self.assertIn("not in approvers", rows[0]["reason"])

    def test_the_last_labeling_counts(self):
        tl = {5: [ev("labeled", "2026-10-13T10:00:00Z", "acn-yogi", "priority:high"),
                  ev("unlabeled", "2026-10-13T10:05:00Z", "acn-yogi", "priority:high"),
                  ev("labeled", "2026-10-13T10:10:00Z", "somebody", "priority:high")]}
        rows = tickets.evaluate(CONFIG, [issue(5)], tl, {})
        self.assertEqual(rows[0]["action"], "skip")
        self.assertIn("somebody", rows[0]["reason"])

    def test_other_labels_in_the_timeline_do_not_count(self):
        tl = {5: [ev("labeled", "2026-10-13T10:00:00Z", "acn-yogi", "bug"), ev("labeled", "2026-10-13T10:01:00Z", "somebody", "priority:high")]}
        rows = tickets.evaluate(CONFIG, [issue(5)], tl, {})
        self.assertEqual(rows[0]["action"], "skip")

    def test_missing_timeline_starts_nothing(self):
        rows = tickets.evaluate(CONFIG, [issue(5)], {}, {})
        self.assertEqual(rows[0]["action"], "skip")
        self.assertIn("who added it", rows[0]["reason"])

    def test_no_approvers_listed_starts_nothing(self):
        cfg = {"triggers": {"ticket": {"label": "priority:high", "approvers": []}}}
        tl = {5: [ev("labeled", "2026-10-13T10:00:00Z", "acn-yogi", "priority:high")]}
        self.assertEqual(tickets.evaluate(cfg, [issue(5)], tl, {})[0]["action"], "skip")


class DedupeTests(unittest.TestCase):
    TL = [ev("labeled", "2026-10-13T10:00:00Z", "acn-yogi", "priority:high")]

    def test_an_issue_that_ran_is_skipped(self):
        seen = {"ticket:5": dt.datetime(2026, 10, 13, 11, 0, tzinfo=dt.timezone.utc)}
        rows = tickets.evaluate(CONFIG, [issue(5)], {5: self.TL}, seen)
        self.assertEqual(rows[0]["action"], "skip")
        self.assertIn("already ran as ticket:5", rows[0]["reason"])

    def test_seen_without_a_time_still_dedupes(self):
        rows = tickets.evaluate(CONFIG, [issue(5)], {5: self.TL}, {"ticket:5": None})
        self.assertEqual(rows[0]["action"], "skip")

    def test_a_reopened_issue_counts_again(self):
        seen = {"ticket:5": dt.datetime(2026, 10, 13, 11, 0, tzinfo=dt.timezone.utc)}
        tl = self.TL + [ev("closed", "2026-10-13T12:00:00Z", "acn-yogi"), ev("reopened", "2026-10-14T09:00:00Z", "acn-yogi")]
        rows = tickets.evaluate(CONFIG, [issue(5)], {5: tl}, seen)
        self.assertEqual(rows[0]["action"], "start")
        self.assertIn("counts again", rows[0]["reason"])

    def test_a_reopen_before_the_run_does_not_count(self):
        seen = {"ticket:5": dt.datetime(2026, 10, 13, 11, 0, tzinfo=dt.timezone.utc)}
        tl = self.TL + [ev("reopened", "2026-10-13T10:30:00Z", "acn-yogi")]
        self.assertEqual(tickets.evaluate(CONFIG, [issue(5)], {5: tl}, seen)[0]["action"], "skip")

    def test_seen_triggers_read_specs_and_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            specs = Path(d) / "specs"
            specs.mkdir()
            (specs / "0011-ticket-5-x.md").write_text('+++\nid = "0011-ticket-5-x"\ntrigger = "ticket:5"\ntriggered_at = "2026-10-13T11:00:00Z"\n+++\n# x\n', encoding="utf-8")
            (specs / "0001-plain.md").write_text('+++\nid = "0001-plain"\n+++\n# x\n', encoding="utf-8")
            ledger = Path(d) / "ledger.jsonl"
            ledger.write_text(json.dumps({"spec": "0012-y", "trigger": "ticket:7", "at": "2026-10-13T12:00:00Z", "costUsd": 0.5}) + "\n"
                              + json.dumps({"spec": "0013-z", "trigger": "schedule:flaky-test-hunt:2026-10-12", "at": "2026-10-12T06:00:00Z"}) + "\nbad\n", encoding="utf-8")
            seen = tickets.seen_triggers(specs, ledger)
            self.assertEqual(set(seen), {"ticket:5", "ticket:7", "schedule:flaky-test-hunt:2026-10-12"})
            self.assertEqual(seen["ticket:5"].isoformat(), "2026-10-13T11:00:00+00:00")
            self.assertEqual(seen["ticket:7"].isoformat(), "2026-10-13T12:00:00+00:00")


class CliTests(unittest.TestCase):
    def test_evaluate_from_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "harness").mkdir()
            (root / "harness/config.toml").write_text('[triggers.ticket]\nlabel = "priority:high"\napprovers = ["acn-yogi"]\n', encoding="utf-8")
            (root / "specs").mkdir()
            (root / "tl").mkdir()
            (root / "issues.json").write_text(json.dumps([issue(5), issue(6, pr=True)]), encoding="utf-8")
            (root / "tl/5.json").write_text(json.dumps([ev("labeled", "2026-10-13T10:00:00Z", "acn-yogi", "priority:high")]), encoding="utf-8")
            import io
            from contextlib import redirect_stdout
            out = io.StringIO()
            with redirect_stdout(out):
                rc = tickets.main(["evaluate", str(root / "harness"), str(root / "specs"), str(root / "ledger.jsonl"),
                                   "--issues", str(root / "issues.json"), "--timelines", str(root / "tl")])
            self.assertEqual(rc, 0)
            rows = json.loads(out.getvalue())
            self.assertEqual([r["action"] for r in rows], ["start", "skip"])


if __name__ == "__main__":
    unittest.main()
