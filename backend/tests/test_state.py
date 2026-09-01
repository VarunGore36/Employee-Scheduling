"""The roster representation and the incremental caches the search depends on."""

from __future__ import annotations

import unittest

from roster.schema import Demand
from roster.state import OFF, RosterState

from .helpers import DSG, LSG, MTS, instance, lay_out


class TestAssignment(unittest.TestCase):
    def setUp(self):
        self.inst = instance(days=7)
        self.M = self.inst.shift_index["M"]
        self.N = self.inst.shift_index["N"]
        self.dsg = self.inst.role_index[DSG]
        self.lsg = self.inst.role_index[LSG]

    def test_assign_updates_coverage_and_headcount(self):
        st = RosterState(self.inst)
        st.assign(0, 3, self.M, self.dsg)
        self.assertEqual(st.shift_of[0][3], self.M)
        self.assertEqual(st.cov[3][self.M][self.dsg], 1)
        self.assertEqual(st.headcount[3][self.M], 1)
        self.assertTrue(st.is_working(0, 3))

    def test_reassigning_the_same_day_moves_the_coverage(self):
        """One slot per employee-day makes 'at most one shift' structural."""
        st = RosterState(self.inst)
        st.assign(1, 2, self.M, self.dsg)
        st.assign(1, 2, self.N, self.lsg)
        self.assertEqual(st.cov[2][self.M][self.dsg], 0)
        self.assertEqual(st.cov[2][self.N][self.lsg], 1)
        self.assertEqual(st.headcount[2][self.M], 0)
        self.assertEqual(sum(1 for d in range(7) if st.is_working(1, d)), 1)

    def test_unassign_is_a_no_op_on_a_free_day(self):
        st = RosterState(self.inst)
        st.unassign(0, 0)
        self.assertEqual(st.assignments(), 0)
        self.assertEqual(st.headcount[0][self.M], 0)

    def test_set_day_routes_off_to_unassign(self):
        st = RosterState(self.inst)
        st.set_day(0, 0, self.M, self.dsg)
        st.set_day(0, 0, OFF, OFF)
        self.assertEqual(st.shift_of[0][0], OFF)
        self.assertEqual(st.cov[0][self.M][self.dsg], 0)

    def test_workers_on_a_cell(self):
        st = lay_out(self.inst, {"A": "MM.....", "B": "M......", "C": "......."})
        self.assertEqual(st.workers_on(0, self.M, self.dsg), [0, 1])


class TestRowStats(unittest.TestCase):
    """Every number here is counted off the pattern string by hand."""

    def setUp(self):
        self.inst = instance(days=14)          # day 0 is a Monday

    def stats(self, row: str):
        st = lay_out(self.inst, {"A": row})
        return st, st.row_stats(0)

    def test_totals_minutes_and_nights(self):
        _st, s = self.stats("MENMEN........")
        self.assertEqual(s.total, 6)
        self.assertEqual(s.nights, 2)
        self.assertEqual(s.minutes, 6 * 480)
        self.assertEqual(s.by_shift[self.inst.shift_index["M"]], 2)

    def test_work_and_off_blocks(self):
        _st, s = self.stats("MM..MMM...M...")
        self.assertEqual(s.work_blocks, [(0, 2), (4, 3), (10, 1)])
        self.assertEqual(s.off_blocks, [(2, 2), (7, 3), (11, 3)])

    def test_blocks_clipped_by_the_horizon_are_visible_as_edge_blocks(self):
        """A run touching day 0 or the last day continues outside the month."""
        _st, s = self.stats("M............M")
        self.assertEqual(s.work_blocks, [(0, 1), (13, 1)])
        self.assertEqual(s.off_blocks, [(1, 12)])

    def test_same_shift_runs(self):
        _st, s = self.stats("NNN.MM.NN....M")
        n, m = self.inst.shift_index["N"], self.inst.shift_index["M"]
        self.assertEqual(s.same_blocks, [(n, 0, 3), (m, 4, 2), (n, 7, 2), (m, 13, 1)])

    def test_consecutive_day_pairs_only_span_worked_days(self):
        _st, s = self.stats("NM.EN.........")
        n, m, e = (self.inst.shift_index[k] for k in "NME")
        self.assertEqual(s.pairs, [(0, n, m), (3, e, n)])

    def test_weekends_worked_and_partial(self):
        # days 5,6 and 12,13 are the weekends
        _st, s = self.stats(".....MM.....M.")
        self.assertEqual(s.weekends_worked, 2)
        self.assertEqual(s.weekends_partial, 1)

    def test_per_calendar_week_counts(self):
        _st, s = self.stats("MMMMM..MM.....")
        self.assertEqual(s.work_per_week, [5, 2])
        self.assertEqual(s.off_per_week, [2, 5])

    def test_windows_worked(self):
        _st, s = self.stats("MM..MMM...M...")
        self.assertEqual(s.windows_worked([[0, 1, 2], [4, 5, 6], [10, 11]]), [2, 3, 1])

    def test_cache_is_rebuilt_after_a_change(self):
        st = lay_out(self.inst, {"A": "M" * 14})
        self.assertEqual(st.row_stats(0).total, 14)
        st.unassign(0, 0)
        self.assertEqual(st.row_stats(0).total, 13)
        st.assign(0, 0, self.inst.shift_index["N"], self.inst.role_index[DSG])
        self.assertEqual(st.row_stats(0).nights, 1)


class TestCoverageSummary(unittest.TestCase):
    def setUp(self):
        self.inst = instance(days=3, demand=[
            Demand(day=0, shift="M", role=DSG, required=2),
            Demand(day=1, shift="M", role=DSG, required=1),
        ])
        self.M = self.inst.shift_index["M"]
        self.N = self.inst.shift_index["N"]
        self.dsg = self.inst.role_index[DSG]
        self.mts = self.inst.role_index[MTS]

    def test_under_coverage_counts_missing_people(self):
        st = RosterState(self.inst)
        self.assertEqual(st.under_coverage(), 3)
        st.assign(0, 0, self.M, self.dsg)
        self.assertEqual(st.under_coverage(), 2)

    def test_over_coverage_counts_surplus_and_undemanded_roles(self):
        st = RosterState(self.inst)
        st.assign(0, 0, self.M, self.dsg)
        st.assign(1, 0, self.M, self.dsg)
        st.assign(2, 0, self.N, self.mts)      # nobody asked for a night MTS
        self.assertEqual(st.over_coverage(), 1)
        st.assign(2, 1, self.M, self.mts)      # nor a morning MTS
        self.assertEqual(st.over_coverage(), 2)

    def test_gaps_list_every_cell_off_target(self):
        st = RosterState(self.inst)
        st.assign(0, 1, self.M, self.dsg)
        gaps = dict(((k, (have, need)) for k, have, need in st.coverage_gaps()))
        self.assertEqual(gaps[(0, self.M, self.dsg)], (0, 2))
        self.assertNotIn((1, self.M, self.dsg), gaps)


class TestCopyAndSerialisation(unittest.TestCase):
    def test_copy_is_independent(self):
        inst = instance(days=5)
        st = lay_out(inst, {"A": "MM...", "B": "..NN.", "C": "....E"})
        clone = st.copy()
        clone.unassign(0, 0)
        clone.assign(2, 0, inst.shift_index["E"], inst.role_index[LSG])
        self.assertTrue(st.is_working(0, 0))
        self.assertFalse(clone.is_working(0, 0))
        self.assertEqual(st.row_stats(0).total, 2)
        self.assertEqual(clone.row_stats(0).total, 1)
        self.assertEqual(st.cov[0][inst.shift_index["E"]][inst.role_index[LSG]], 0)

    def test_dict_round_trip_reproduces_the_roster(self):
        inst = instance(days=6)
        st = lay_out(inst, {"A": "M.E.N.", "B": "NN....", "C": "...EE."})
        back = RosterState.from_dict(inst, st.to_dict())
        self.assertEqual(back.shift_of, st.shift_of)
        self.assertEqual(back.role_of, st.role_of)
        self.assertEqual(back.cov, st.cov)

    def test_to_dict_uses_ids_and_iso_dates(self):
        inst = instance(days=3)
        st = lay_out(inst, {"A": "M.."})
        data = st.to_dict()
        self.assertEqual(data["dates"][0], "2026-09-07")
        self.assertEqual(data["rows"][0], {"employee": "A",
                                           "days": [{"shift": "M", "role": DSG}, None, None]})


if __name__ == "__main__":
    unittest.main()
