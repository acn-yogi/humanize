"""The five-field cron matcher behind the schedule trigger."""

from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import cron  # noqa: E402

UTC = dt.timezone.utc


def at(y, mo, d, h, mi, tz=UTC):
    return dt.datetime(y, mo, d, h, mi, tzinfo=tz)


class ParseTests(unittest.TestCase):
    def test_star_and_steps(self):
        minute, hour, dom, month, dow = cron.parse("*/30 * * * *")
        self.assertEqual(minute, {0, 30})
        self.assertEqual(hour, set(range(24)))
        self.assertEqual(dom, set(range(1, 32)))
        self.assertEqual(month, set(range(1, 13)))
        self.assertEqual(dow, set(range(7)))

    def test_ranges_lists_and_sunday_as_seven(self):
        minute, hour, _, _, dow = cron.parse("0,15 9-17/4 * * 1-5,7")
        self.assertEqual(minute, {0, 15})
        self.assertEqual(hour, {9, 13, 17})
        self.assertEqual(dow, {0, 1, 2, 3, 4, 5})

    def test_bad_expressions_are_refused(self):
        for bad in ("* * * *", "60 * * * *", "* 24 * * *", "* * 0 * *", "* * * 13 *", "* * * * 8", "mon * * * *", "5-1 * * * *", "*/0 * * * *"):
            with self.subTest(bad=bad):
                with self.assertRaises(cron.CronError):
                    cron.parse(bad)


class MatchTests(unittest.TestCase):
    def test_every_thirty_minutes(self):
        self.assertTrue(cron.matches("*/30 * * * *", at(2026, 10, 13, 9, 0)))
        self.assertTrue(cron.matches("*/30 * * * *", at(2026, 10, 13, 9, 30)))
        self.assertFalse(cron.matches("*/30 * * * *", at(2026, 10, 13, 9, 31)))

    def test_monday_six_am(self):
        monday = at(2026, 10, 12, 6, 0)
        self.assertEqual(monday.weekday(), 0)
        self.assertTrue(cron.matches("0 6 * * 1", monday))
        self.assertFalse(cron.matches("0 6 * * 1", monday + dt.timedelta(days=1)))
        self.assertFalse(cron.matches("0 6 * * 1", monday.replace(hour=7)))

    def test_first_of_month(self):
        self.assertTrue(cron.matches("0 6 1 * *", at(2026, 11, 1, 6, 0)))
        self.assertFalse(cron.matches("0 6 1 * *", at(2026, 11, 2, 6, 0)))

    def test_dom_and_dow_both_restricted_is_either(self):
        # 2026-10-13 is a Tuesday (cron dow 2) and the 13th: either field matching is enough.
        self.assertTrue(cron.matches("0 0 13 * 5", at(2026, 10, 13, 0, 0)))
        self.assertTrue(cron.matches("0 0 20 * 2", at(2026, 10, 13, 0, 0)))
        self.assertFalse(cron.matches("0 0 20 * 5", at(2026, 10, 13, 0, 0)))

    def test_timezone_wall_clock(self):
        # 06:00 in Zurich on 2026-10-13 (CEST, UTC+2) is 04:00 UTC.
        self.assertTrue(cron.is_due("0 6 * * *", "Europe/Zurich", at(2026, 10, 13, 4, 0)))
        self.assertFalse(cron.is_due("0 6 * * *", "Europe/Zurich", at(2026, 10, 13, 6, 0)))
        self.assertTrue(cron.is_due("0 6 * * *", "UTC", at(2026, 10, 13, 6, 0)))

    def test_seconds_do_not_matter(self):
        self.assertTrue(cron.is_due("*/30 * * * *", "UTC", at(2026, 10, 13, 9, 30).replace(second=59)))


class NextFireTests(unittest.TestCase):
    def test_next_half_hour(self):
        n = cron.next_fire("*/30 * * * *", "UTC", at(2026, 10, 13, 9, 7))
        self.assertEqual(n.isoformat(timespec="minutes"), "2026-10-13T09:30+00:00")

    def test_next_is_strictly_after(self):
        n = cron.next_fire("*/30 * * * *", "UTC", at(2026, 10, 13, 9, 30))
        self.assertEqual(n.isoformat(timespec="minutes"), "2026-10-13T10:00+00:00")

    def test_next_monday_and_first_of_month(self):
        self.assertEqual(cron.next_fire("0 6 * * 1", "UTC", at(2026, 10, 13, 9, 0)).isoformat(timespec="minutes"), "2026-10-19T06:00+00:00")
        self.assertEqual(cron.next_fire("0 6 1 * *", "UTC", at(2026, 10, 13, 9, 0)).isoformat(timespec="minutes"), "2026-11-01T06:00+00:00")

    def test_next_fires_count(self):
        fires = cron.next_fires("0 6 1 * *", "UTC", at(2026, 10, 13, 9, 0), 3)
        self.assertEqual([f.strftime("%Y-%m-%d") for f in fires], ["2026-11-01", "2026-12-01", "2027-01-01"])

    def test_never_within_limit(self):
        # 30 February never comes.
        self.assertIsNone(cron.next_fire("0 0 30 2 *", "UTC", at(2026, 10, 13, 9, 0)))


if __name__ == "__main__":
    unittest.main()
