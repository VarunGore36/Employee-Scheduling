"""The calendar layer: arbitrary start dates, weekends, weeks, windows."""

from __future__ import annotations

import unittest
from datetime import date

from roster.horizon import DEFAULT_WEEKEND, Horizon


class TestHorizon(unittest.TestCase):
    def test_arbitrary_start_date_mid_month(self):
        """The whole point: a month that starts on the 12th, not the 1st."""
        h = Horizon(start="2026-09-12", num_days=31)
        self.assertEqual(h.date_of(0), date(2026, 9, 12))
        self.assertEqual(h.date_of(30), date(2026, 10, 12))
        self.assertEqual(len(h), 31)

    def test_index_of_round_trips_and_rejects_outsiders(self):
        h = Horizon(start="2026-09-12", num_days=31)
        for d in (0, 7, 30):
            self.assertEqual(h.index_of(h.date_of(d)), d)
        self.assertEqual(h.index_of("2026-09-13"), 1)
        with self.assertRaises(ValueError):
            h.index_of("2026-09-11")
        with self.assertRaises(ValueError):
            h.index_of("2026-10-13")

    def test_weekday_and_weekend_flags(self):
        h = Horizon(start="2026-09-07", num_days=14)   # a Monday
        self.assertEqual(h.day(0).weekday_name, "Mon")
        self.assertEqual([d.index for d in h.days if d.is_weekend], [5, 6, 12, 13])
        self.assertEqual(DEFAULT_WEEKEND, (5, 6))

    def test_weekend_blocks_group_saturday_with_sunday(self):
        h = Horizon(start="2026-09-07", num_days=14)
        self.assertEqual(h.weekend_blocks(), [[5, 6], [12, 13]])

    def test_partial_weekend_at_the_horizon_edge_is_kept(self):
        """Starting on a Sunday leaves a one-day weekend; it still counts as one."""
        h = Horizon(start="2026-09-13", num_days=8)    # Sun .. next Sun
        self.assertEqual(h.weekend_blocks(), [[0], [6, 7]])

    def test_calendar_weeks_include_the_partial_ones(self):
        h = Horizon(start="2026-09-10", num_days=10)   # Thu .. Sat
        weeks = h.calendar_weeks()
        self.assertEqual(weeks[0], [0, 1, 2, 3])       # Thu Fri Sat Sun
        self.assertEqual(weeks[1], [4, 5, 6, 7, 8, 9])
        self.assertEqual(sorted(i for w in weeks for i in w), list(range(10)))

    def test_calendar_weeks_partition_the_horizon_exactly(self):
        for start in ("2026-09-07", "2026-09-12", "2026-02-26", "2027-01-01"):
            h = Horizon(start=start, num_days=31)
            flat = [i for w in h.calendar_weeks() for i in w]
            self.assertEqual(flat, list(range(31)), start)

    def test_rolling_windows(self):
        h = Horizon(start="2026-09-07", num_days=10)
        windows = h.rolling_windows(7)
        self.assertEqual(len(windows), 4)              # 10 - 7 + 1
        self.assertEqual(windows[0], list(range(7)))
        self.assertEqual(windows[-1], list(range(3, 10)))
        self.assertEqual(h.rolling_windows(20), [])

    def test_holidays_are_flagged_without_becoming_weekends(self):
        h = Horizon(start="2026-09-07", num_days=7, holidays=frozenset({date(2026, 9, 9)}))
        self.assertTrue(h.day(2).is_holiday)
        self.assertFalse(h.day(2).is_weekend)
        self.assertFalse(h.day(3).is_holiday)

    def test_month_boundary_and_leap_year_arithmetic(self):
        h = Horizon(start="2028-02-25", num_days=6)     # 2028 is a leap year
        self.assertEqual([d.date.isoformat() for d in h.days],
                         ["2028-02-25", "2028-02-26", "2028-02-27", "2028-02-28",
                          "2028-02-29", "2028-03-01"])

    def test_custom_weekend_for_a_friday_saturday_week(self):
        h = Horizon(start="2026-09-07", num_days=7, weekend_days=(4, 5))
        self.assertEqual([d.index for d in h.days if d.is_weekend], [4, 5])

    def test_dict_round_trip(self):
        h = Horizon(start="2026-09-12", num_days=31,
                    holidays=frozenset({date(2026, 10, 2)}))
        back = Horizon.from_dict(h.to_dict())
        self.assertEqual(back.start, h.start)
        self.assertEqual(back.num_days, h.num_days)
        self.assertEqual(back.holidays, h.holidays)
        self.assertEqual(back.weekend_days, h.weekend_days)

    def test_rejects_an_empty_horizon(self):
        with self.assertRaises(ValueError):
            Horizon(start="2026-09-12", num_days=0)


if __name__ == "__main__":
    unittest.main()
