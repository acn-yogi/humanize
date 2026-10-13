"""Pool accounting from ledger rows: what was spent in the window, how many tasks still fit."""

from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import pool  # noqa: E402

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 14, 12, 0, tzinfo=UTC)  # a Wednesday


def config(pool_usd=100, window="run", cap=3.0):
    return {"caps": {"max_budget_usd": cap}, "triggers": {"budget": {"pool_usd": pool_usd, "window": window}}}


def row(at, cost, **extra):
    return {"at": at, "taskId": "t-x", "spec": "0001-x", "path": "per_pr", "costUsd": cost, **extra}


ROWS = [
    row("2026-09-30T23:59:00Z", 2.0),   # last month
    row("2026-10-05T10:00:00Z", 1.5),   # last week (Monday 2026-10-05 to Sunday 2026-10-11)
    row("2026-10-13T09:00:00Z", 0.9),   # yesterday, this week
    row("2026-10-14T08:00:00Z", 0.6),   # today, before this run
    row("2026-10-14T11:30:00Z", 0.64),  # today, in this run
    {"event": "budget-exhausted", "pool": 1, "spent": 0.64, "window": "run", "leftInQueue": 2, "at": "2026-10-14T11:40:00Z"},
]
RUN_START = dt.datetime(2026, 10, 14, 11, 0, tzinfo=UTC)


class WindowTests(unittest.TestCase):
    def test_run_counts_rows_since_the_start(self):
        st = pool.status(config(100, "run"), ROWS, None, RUN_START, NOW)
        self.assertEqual(st["spent"], 0.64)
        self.assertEqual(st["rows"], 1)

    def test_run_with_no_start_counts_everything(self):
        st = pool.status(config(100, "run"), ROWS, None, None, NOW)
        self.assertAlmostEqual(st["spent"], 5.64)

    def test_day_week_month(self):
        self.assertAlmostEqual(pool.status(config(100, "day"), ROWS, None, RUN_START, NOW)["spent"], 1.24)
        self.assertAlmostEqual(pool.status(config(100, "week"), ROWS, None, RUN_START, NOW)["spent"], 2.14)
        self.assertAlmostEqual(pool.status(config(100, "month"), ROWS, None, RUN_START, NOW)["spent"], 3.64)

    def test_week_starts_on_monday(self):
        self.assertEqual(pool.window_start("week", NOW, None).isoformat(), "2026-10-12T00:00:00+00:00")
        self.assertEqual(pool.window_start("month", NOW, None).isoformat(), "2026-10-01T00:00:00+00:00")

    def test_unknown_window_is_refused(self):
        with self.assertRaises(ValueError):
            pool.status(config(100, "year"), ROWS, None, None, NOW)

    def test_exhausted_rows_carry_no_cost(self):
        st = pool.status(config(100, "run"), [ROWS[-1]], None, None, NOW)
        self.assertEqual(st["spent"], 0)
        self.assertEqual(st["rows"], 0)


class FitTests(unittest.TestCase):
    def test_fits_is_whole_caps_left(self):
        st = pool.status(config(10, "run", cap=3.0), [row("2026-10-14T11:30:00Z", 2.5)], None, RUN_START, NOW)
        self.assertEqual(st["left"], 7.5)
        self.assertEqual(st["fits"], 2)
        self.assertTrue(st["canStart"])
        self.assertFalse(st["exhausted"])

    def test_one_dollar_pool_cannot_start_a_three_dollar_task(self):
        st = pool.status(config(100, "run"), [], 1.0, RUN_START, NOW)
        self.assertEqual(st["pool"], 1.0)
        self.assertEqual(st["fits"], 0)
        self.assertTrue(st["exhausted"])
        self.assertFalse(st["canStart"])

    def test_override_beats_config(self):
        self.assertEqual(pool.status(config(100, "run"), [], 7.0, None, NOW)["pool"], 7.0)

    def test_exactly_one_cap_left_still_starts(self):
        st = pool.status(config(6, "run"), [row("2026-10-14T11:30:00Z", 3.0)], None, RUN_START, NOW)
        self.assertEqual(st["fits"], 1)
        self.assertTrue(st["canStart"])

    def test_overshoot_leaves_nothing_negative(self):
        st = pool.status(config(1, "run"), [row("2026-10-14T11:30:00Z", 1.4)], None, RUN_START, NOW)
        self.assertEqual(st["left"], 0)
        self.assertTrue(st["exhausted"])

    def test_zero_pool_is_unlimited(self):
        st = pool.status(config(0, "run"), ROWS, None, None, NOW)
        self.assertTrue(st["unlimited"])
        self.assertTrue(st["canStart"])
        self.assertIsNone(st["fits"])

    def test_negative_pool_is_refused(self):
        with self.assertRaises(ValueError):
            pool.status(config(100, "run"), [], -1.0, None, NOW)


class ExhaustedRowTests(unittest.TestCase):
    def test_row_shape(self):
        st = pool.status(config(100, "day"), ROWS, 1.0, RUN_START, NOW, queued=2)
        r = pool.exhausted_row(st, NOW)
        self.assertEqual(r["event"], "budget-exhausted")
        self.assertEqual(r["pool"], 1.0)
        self.assertEqual(r["window"], "day")
        self.assertEqual(r["leftInQueue"], 2)
        self.assertAlmostEqual(r["spent"], 1.24)
        self.assertEqual(r["at"], "2026-10-14T12:00:00Z")
        # No spec and no pr: preroute.ts and verdict.py skip it as a task row.
        self.assertNotIn("spec", r)
        self.assertNotIn("pr", r)


class CliTests(unittest.TestCase):
    def test_status_from_files(self):
        with tempfile.TemporaryDirectory() as d:
            harness = Path(d)
            (harness / "config.toml").write_text('[caps]\nmax_budget_usd = 3.0\n[triggers.budget]\npool_usd = 100\nwindow = "run"\n', encoding="utf-8")
            ledger = harness / "ledger.jsonl"
            ledger.write_text("\n".join(json.dumps(r) for r in ROWS) + "\nnot json\n", encoding="utf-8")
            import io
            from contextlib import redirect_stdout
            out = io.StringIO()
            with redirect_stdout(out):
                rc = pool.main(["status", str(harness), str(ledger), "--pool-usd", "1", "--since", RUN_START.isoformat(), "--now", NOW.isoformat(), "--queued", "3"])
            self.assertEqual(rc, 0)
            st = json.loads(out.getvalue())
            self.assertEqual(st["pool"], 1.0)
            self.assertEqual(st["spent"], 0.64)
            self.assertTrue(st["exhausted"])
            self.assertEqual(st["queued"], 3)


if __name__ == "__main__":
    unittest.main()
