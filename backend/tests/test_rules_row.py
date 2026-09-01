"""One test per registered rule type, with every expected amount counted by hand."""

from __future__ import annotations

import unittest

from roster.rules import REGISTRY, build
from roster.schema import Demand

from .helpers import DSG, LSG, MTS, amount, instance, lay_out, messages, rule


class RuleCase(unittest.TestCase):
    days = 14

    def setUp(self):
        self.inst = instance(days=self.days)

    def check(self, rule_obj, row: str, expected: float, emp: str = "A"):
        state = lay_out(self.inst, {emp: row})
        got = amount(self.inst, rule_obj, state, emp)
        self.assertEqual(got, expected, f"{rule_obj.type} on {row!r}")
        return state


# Consecutive-day rules
class TestConsecutiveRules(RuleCase):
    def test_max_consecutive_working_days(self):
        r = rule("r", "max_consecutive_working_days", max=3)
        self.check(r, "." * 14, 0)
        self.check(r, ".MMM..........", 0)
        self.check(r, ".MMMM.........", 1)          # one day over
        self.check(r, ".MMMMM...MMMM.", 2 + 1)      # two runs, 5 and 4
        state = self.check(r, ".MMMMM........", 2)
        self.assertIn("A works 5 days in a row from 2026-09-08 (limit 3)",
                      messages(self.inst, r, state))

    def test_min_consecutive_working_days_exempts_the_horizon_edges(self):
        """A single day at day 0 may be the tail of last month's run."""
        r = rule("r", "min_consecutive_working_days", min=2)
        self.check(r, "M.............", 0)          # clipped at the start
        self.check(r, ".............M", 0)          # clipped at the end
        self.check(r, ".M............", 1)          # genuinely isolated
        self.check(r, ".M...M........", 2)
        self.check(r, ".MM...........", 0)

    def test_max_consecutive_days_off(self):
        r = rule("r", "max_consecutive_days_off", max=3)
        self.check(r, "M" * 14, 0)
        self.check(r, "M...MMMMMMMMMM", 0)          # exactly 3 off
        self.check(r, "M....MMMMMMMMM", 1)
        self.check(r, "MMMMM.....MMMM", 2)

    def test_min_consecutive_days_off_exempts_the_horizon_edges(self):
        r = rule("r", "min_consecutive_days_off", min=2)
        self.check(r, ".MMMMMMMMMMMMM", 0)          # clipped at the start
        self.check(r, "MMMMMMMMMMMMM.", 0)          # clipped at the end
        self.check(r, "M.MMMMMMMMMMMM", 1)
        self.check(r, "M.MM.MMMMMMMMM", 2)
        self.check(r, "M..MMMMMMMMMMM", 0)

    def test_max_consecutive_same_shift_for_one_shift_type(self):
        r = rule("r", "max_consecutive_same_shift", max=2, shift="N")
        self.check(r, "NN............", 0)
        self.check(r, "NNN...........", 1)
        self.check(r, "MMMMM.........", 0)          # mornings are unrestricted
        state = self.check(r, "NNNN..NNN.....", 2 + 1)
        self.assertIn("A works 4 N shifts in a row from 2026-09-07 (limit 2)",
                      messages(self.inst, r, state))

    def test_max_consecutive_same_shift_for_every_shift(self):
        r = rule("r", "max_consecutive_same_shift", max=2)
        self.check(r, "MMMEEE........", 1 + 1)
        self.check(r, "MMEEMM........", 0)


# Succession and rest
class TestSuccessionAndRest(RuleCase):
    def test_forbidden_shift_sequence(self):
        r = rule("r", "forbidden_shift_sequence", **{"from": ["N"], "to": ["M", "E"]})
        self.check(r, "NM............", 1)
        self.check(r, "NE............", 1)
        self.check(r, "NN............", 0)
        self.check(r, "N.M...........", 0)          # a day off breaks the pair
        self.check(r, "NMNE..........", 2)

    def test_min_rest_hours_is_derived_from_the_clock(self):
        """12h rest bans E->M, N->M and N->E; nothing was named in the rule."""
        r = rule("r", "min_rest_hours", hours=12)
        self.check(r, "EM............", 1)
        self.check(r, "NM............", 1)
        self.check(r, "NE............", 1)
        self.check(r, "MM............", 0)          # 16h gap
        self.check(r, "ME............", 0)          # 24h gap
        self.check(r, "NN............", 0)          # 24h gap
        state = self.check(r, "NM............", 1)
        self.assertIn("A gets only 0.0h rest between N on 2026-09-07 and M the "
                      "next day (needs 12.0h)", messages(self.inst, r, state))

    def test_tighter_rest_bans_more_pairs(self):
        r = rule("r", "min_rest_hours", hours=17)
        self.check(r, "MM............", 1)          # only 16h
        self.check(r, "ME............", 0)          # 24h


# Totals
class TestTotals(RuleCase):
    def test_total_shifts_range(self):
        r = rule("r", "total_shifts_range", min=3, max=5)
        self.check(r, "MMM...........", 0)
        self.check(r, "MM............", 1)
        self.check(r, "MMMMMMM.......", 2)
        self.check(r, "..............", 3)

    def test_total_hours_range(self):
        """Eight-hour shifts, so 4 shifts is 32 hours; the amount is in hours."""
        r = rule("r", "total_hours_range", min_hours=24, max_hours=40)
        self.check(r, "MMM...........", 0)
        self.check(r, "MM............", 8)
        self.check(r, "MMMMMM........", 8)

    def test_shift_type_count_range(self):
        r = rule("r", "shift_type_count_range", shift="N", min=1, max=2)
        self.check(r, "NN............", 0)
        self.check(r, "NNN...........", 1)
        self.check(r, "MMMM..........", 1)          # no nights at all

    def test_max_night_shifts(self):
        r = rule("r", "max_night_shifts", max=2)
        self.check(r, "NN............", 0)
        self.check(r, "NNNN..........", 2)
        self.check(r, "MMMMMMMM......", 0)


# Windows and weekends
class TestWindowsAndWeekends(RuleCase):
    def test_max_working_days_per_calendar_week(self):
        r = rule("r", "max_working_days_per_window", max=4, window="calendar")
        self.check(r, "MMMM...MMMM...", 0)
        self.check(r, "MMMMM..MMMM...", 1)
        self.check(r, "MMMMMMM MMMMMM".replace(" ", "M"), 3 + 3)

    def test_rolling_window_catches_the_week_straddling_trick(self):
        """Seven straight days that a calendar week never sees as more than four."""
        calendar = rule("c", "max_working_days_per_window", max=4, window="calendar")
        rolling = rule("r", "max_working_days_per_window", max=4, window="rolling",
                       window_days=7)
        row = "...MMMMMMM...."          # days 3..9, spanning the Sun/Mon boundary
        self.check(calendar, row, 0)
        # the eight rolling windows hold 4,5,6,7,6,5,4,3 days: 1+2+3+2+1 over the cap
        self.check(rolling, row, 9)

    def test_min_days_off_per_week_skips_part_weeks_by_default(self):
        r = rule("r", "min_days_off_per_window", min=2, window="calendar")
        self.check(r, "MMMMM..MMMMM..", 0)
        self.check(r, "MMMMMM.MMMMM..", 1)
        self.check(r, "MMMMMMMMMMMMMM", 2 + 2)

    def test_min_days_off_per_week_on_a_horizon_with_part_weeks(self):
        """A four-day stub at the start cannot owe a full week's rest."""
        inst = instance(days=11, start="2026-09-10")   # Thu: a 4-day stub, then a full week
        self.assertEqual([len(w) for w in inst.horizon.calendar_weeks()], [4, 7])
        state = lay_out(inst, {"A": "M" * 11})
        r = rule("r", "min_days_off_per_window", min=2, window="calendar")
        self.assertEqual(amount(inst, r, state, "A"), 2)      # the full week only
        r_all = rule("r", "min_days_off_per_window", min=2, window="calendar",
                     include_partial=True)
        self.assertEqual(amount(inst, r_all, state, "A"), 4)  # the stub as well

    def test_max_weekends_worked(self):
        r = rule("r", "max_weekends_worked", max=1)
        self.check(r, ".....M........", 0)
        self.check(r, ".....M......M.", 1)
        self.check(r, ".....MM.....MM", 1)

    def test_complete_weekends(self):
        r = rule("r", "complete_weekends")
        self.check(r, ".....MM.....MM", 0)
        self.check(r, ".....M........", 1)
        self.check(r, ".....M.......M", 2)
        self.check(r, "..............", 0)
        state = self.check(r, ".....M........", 1)
        self.assertIn("A works only part of the weekend starting 2026-09-12",
                      messages(self.inst, r, state))


if __name__ == "__main__":
    unittest.main()
