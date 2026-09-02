"""Requests, availability, coverage, fairness, and how RuleSet turns amounts into cost."""

from __future__ import annotations

import unittest

from roster.rules import DEFAULT_HARD_WEIGHT, REGISTRY, RuleSet, build
from roster.schema import Demand, Employee, Scope

from .helpers import DSG, LSG, MTS, amount, instance, lay_out, messages, rule


class TestAvailabilityAndRequests(unittest.TestCase):
    def setUp(self):
        self.inst = instance(days=14)

    def amount_for(self, rule_obj, row, emp="A"):
        state = lay_out(self.inst, {emp: row})
        return amount(self.inst, rule_obj, state, emp)

    def test_unavailable_blocks_the_whole_day(self):
        r = rule("leave", "unavailable", days=["2026-09-09", "2026-09-10"])
        self.assertEqual(self.amount_for(r, "." * 14), 0)
        self.assertEqual(self.amount_for(r, "..M..........."), 1)
        self.assertEqual(self.amount_for(r, "..MM.........."), 2)
        self.assertEqual(self.amount_for(r, "M............."), 0)

    def test_unavailable_can_block_only_some_shifts(self):
        """Evening class on the 9th: mornings are still fine."""
        r = rule("class", "unavailable", days=["2026-09-09"], shifts=["E", "N"])
        self.assertEqual(self.amount_for(r, "..E..........."), 1)
        self.assertEqual(self.amount_for(r, "..M..........."), 0)

    def test_unavailable_accepts_day_offsets_as_well_as_dates(self):
        r = rule("leave", "unavailable", days=[2, 3])
        self.assertEqual(self.amount_for(r, "..MM.........."), 2)

    def test_day_off_request(self):
        r = rule("req", "day_off_request", severity="soft", weight=4.0,
                 days=["2026-09-14"])
        self.assertEqual(self.amount_for(r, "." * 14), 0)
        self.assertEqual(self.amount_for(r, ".......M......"), 1)

    def test_fixed_assignment_wants_that_exact_duty(self):
        r = rule("fix", "fixed_assignment", day="2026-09-09", shift="M", role=DSG)
        self.assertEqual(self.amount_for(r, "..M..........."), 0)
        self.assertEqual(self.amount_for(r, "..E..........."), 1)
        self.assertEqual(self.amount_for(r, ".............."), 1)

    def test_shift_request_and_shift_off_request_are_opposites(self):
        want = rule("w", "shift_request", severity="soft", day=3, shift="N")
        avoid = rule("a", "shift_off_request", severity="soft", day=3, shift="N")
        self.assertEqual(self.amount_for(want, "...N.........."), 0)
        self.assertEqual(self.amount_for(avoid, "...N.........."), 1)
        self.assertEqual(self.amount_for(want, "...M.........."), 1)
        self.assertEqual(self.amount_for(avoid, "...M.........."), 0)

    def test_shift_preference_avoid_counts_every_assignment(self):
        r = rule("p", "shift_preference", severity="soft", shift="N", direction="avoid")
        self.assertEqual(self.amount_for(r, "NN.N.........."), 3)
        self.assertEqual(self.amount_for(r, "MM.E.........."), 0)

    def test_shift_preference_prefer_counts_everything_else(self):
        r = rule("p", "shift_preference", severity="soft", shift="M", direction="prefer")
        self.assertEqual(self.amount_for(r, "MMM..........."), 0)
        self.assertEqual(self.amount_for(r, "MME.N........."), 2)

    def test_scope_limits_a_rule_to_named_people(self):
        r = rule("r", "max_night_shifts", max=0,
                 scope={"kind": "employees", "ids": ["B"]})
        state = lay_out(self.inst, {"A": "NN............", "B": "NNN..........."})
        self.assertEqual(amount(self.inst, r, state), 3)      # only B is in scope

    def test_scope_by_role_picks_up_cross_qualified_staff(self):
        r = rule("r", "max_night_shifts", max=0, scope={"kind": "roles", "ids": [LSG]})
        state = lay_out(self.inst, {"A": "N.............",     # DSG only, out of scope
                                    "B": "N.............",     # DSG+LSG, in scope
                                    "C": "N............."})    # LSG+MTS, in scope
        self.assertEqual(amount(self.inst, r, state), 2)


class TestCoverage(unittest.TestCase):
    def setUp(self):
        self.inst = instance(days=3, demand=[
            Demand(day=0, shift="M", role=DSG, required=2),
            Demand(day=1, shift="N", role=LSG, required=1),
        ])
        self.M, self.N = self.inst.shift_index["M"], self.inst.shift_index["N"]
        self.dsg, self.lsg = self.inst.role_index[DSG], self.inst.role_index[LSG]

    def test_under_coverage_only(self):
        r = rule("c", "coverage", direction="under")
        state = lay_out(self.inst, {"A": "M..", "B": ".N."})
        # day 0 needs 2 DSG mornings and has 1; day 1 needs an LSG night and B is DSG
        self.assertEqual(amount(self.inst, r, state), 1 + 1)

    def test_over_coverage_counts_surplus_and_undemanded_cells(self):
        r = rule("c", "coverage", direction="over")
        state = lay_out(self.inst, {"A": "MM.", "B": "M.."})
        # day 0: 2 of 2, fine. day 1: one DSG morning nobody asked for
        self.assertEqual(amount(self.inst, r, state), 1)

    def test_undemanded_cells_can_be_ignored(self):
        r = rule("c", "coverage", direction="over", count_undemanded=False)
        state = lay_out(self.inst, {"A": "MM.", "B": "M.."})
        self.assertEqual(amount(self.inst, r, state), 0)

    def test_direction_both_with_separate_weights(self):
        r = rule("c", "coverage", direction="both", under_weight=10.0, over_weight=1.0)
        state = lay_out(self.inst, {"A": "MM.", "B": "M.."})
        # short one LSG night on day 1 (10) plus one undemanded morning (1)
        self.assertEqual(amount(self.inst, r, state), 11)

    def test_cell_amount_sums_to_total_amount(self):
        """The annealing delta depends on this identity holding exactly."""
        r = rule("c", "coverage", direction="both", under_weight=3.0, over_weight=2.0)
        ev = build(r, self.inst)
        state = lay_out(self.inst, {"A": "MM.", "B": "M.N", "C": ".NN"})
        by_cell = sum(
            ev.cell_amount(state, d, s, role)
            for d in range(self.inst.num_days)
            for s in range(self.inst.num_shifts)
            for role in range(self.inst.num_roles)
        )
        self.assertAlmostEqual(by_cell, ev.total_amount(state))

    def test_violation_messages_name_the_cell(self):
        r = rule("c", "coverage", direction="under")
        state = lay_out(self.inst, {"A": "M.."})
        self.assertIn("2026-09-07 M/DSG: 1 rostered, 2 needed (short 1)",
                      messages(self.inst, r, state))


class TestHeadcountPerShift(unittest.TestCase):
    def setUp(self):
        self.inst = instance(days=3)

    def test_minimum_bodies_on_site_regardless_of_role(self):
        """A night floor is about presence, not about which grade is present."""
        r = rule("floor", "headcount_per_shift", shift="N", min=2)
        state = lay_out(self.inst, {"A": "N..", "B": "NN.", "C": "..."})
        # day 0 has 2, day 1 has 1, day 2 has 0
        self.assertEqual(amount(self.inst, r, state), 1 + 2)

    def test_maximum_bodies_on_site(self):
        r = rule("cap", "headcount_per_shift", shift="M", max=1)
        state = lay_out(self.inst, {"A": "MM.", "B": "M..", "C": "M.."})
        self.assertEqual(amount(self.inst, r, state), 2)

    def test_can_be_limited_to_named_days(self):
        r = rule("floor", "headcount_per_shift", shift="N", min=2, days=[0])
        state = lay_out(self.inst, {"A": "N..", "B": "..."})
        self.assertEqual(amount(self.inst, r, state), 1)
        r_all = rule("floor", "headcount_per_shift", shift="N", min=2)
        self.assertEqual(amount(self.inst, r_all, state), 1 + 2 + 2)


class TestBalanceWorkload(unittest.TestCase):
    def setUp(self):
        self.inst = instance(days=14)

    def test_spread_of_total_shifts_beyond_tolerance(self):
        r = rule("f", "balance_workload", severity="soft", measure="shifts", tolerance=1)
        state = lay_out(self.inst, {"A": "MMMMM.........",
                                    "B": "MM............",
                                    "C": "MMM..........."})
        # 5, 2, 3 -> spread 3, tolerance 1
        self.assertEqual(amount(self.inst, r, state), 2)

    def test_within_tolerance_costs_nothing(self):
        r = rule("f", "balance_workload", severity="soft", measure="shifts", tolerance=2)
        state = lay_out(self.inst, {"A": "MMM...........",
                                    "B": "M.............",
                                    "C": "MM............"})
        self.assertEqual(amount(self.inst, r, state), 0)

    def test_nights_hours_and_weekends_measures(self):
        state = lay_out(self.inst, {"A": "NNN...........",
                                    "B": "..............",
                                    "C": ".....MM......."})
        nights = rule("n", "balance_workload", severity="soft", measure="nights",
                      tolerance=0)
        hours = rule("h", "balance_workload", severity="soft", measure="hours",
                     tolerance=0)
        weekends = rule("w", "balance_workload", severity="soft", measure="weekends",
                        tolerance=0)
        self.assertEqual(amount(self.inst, nights, state), 3)
        self.assertEqual(amount(self.inst, hours, state), 24)
        self.assertEqual(amount(self.inst, weekends, state), 1)

    def test_named_shift_measure(self):
        r = rule("s", "balance_workload", severity="soft", measure="shift_type",
                 shift="E", tolerance=0)
        state = lay_out(self.inst, {"A": "EE............",
                                    "B": "..............",
                                    "C": "E............."})
        self.assertEqual(amount(self.inst, r, state), 2)

    def test_message_quotes_both_ends(self):
        r = rule("f", "balance_workload", severity="soft", measure="shifts", tolerance=1)
        state = lay_out(self.inst, {"A": "MMMMM.........",
                                    "B": "MM............",
                                    "C": "MMM..........."})
        self.assertIn("shifts: busiest person has 5, lightest 2 (spread 3, tolerance 1)",
                      messages(self.inst, r, state))


class TestRuleSetCosting(unittest.TestCase):
    """Amounts are counted by the evaluators; RuleSet decides what they cost."""

    def setUp(self):
        self.rules = [
            rule("hard_run", "max_consecutive_working_days", max=2),
            rule("soft_fair", "balance_workload", severity="soft", weight=5.0,
                 measure="shifts", tolerance=0),
        ]
        self.inst = instance(days=14, rules=self.rules)
        self.state = lay_out(self.inst, {"A": "MMMM..........",
                                         "B": "..............",
                                         "C": ".............."})

    def test_hard_rules_are_scaled_by_hard_weight(self):
        rs = RuleSet(self.inst)
        hard, soft = rs.evaluators[0], rs.evaluators[1]
        self.assertEqual(rs.weight_of(hard), DEFAULT_HARD_WEIGHT)
        self.assertEqual(rs.weight_of(soft), 5.0)

    def test_rule_weight_multiplies_on_top_of_the_severity_weight(self):
        inst = instance(days=14, rules=[
            rule("r", "max_consecutive_working_days", weight=3.0, max=2)])
        rs = RuleSet(inst)
        self.assertEqual(rs.weight_of(rs.evaluators[0]), 3.0 * DEFAULT_HARD_WEIGHT)

    def test_hard_weight_is_configurable(self):
        rs = RuleSet(self.inst, hard_weight=50.0)
        self.assertEqual(rs.weight_of(rs.evaluators[0]), 50.0)

    def test_total_cost_is_the_weighted_sum_of_the_amounts(self):
        rs = RuleSet(self.inst)
        # A works 4 in a row against a limit of 2 -> amount 2, at hard weight.
        self.assertEqual(rs.total_cost(self.state), 2 * DEFAULT_HARD_WEIGHT + 4 * 5.0)

    def test_row_and_global_costs_partition_the_total(self):
        rs = RuleSet(self.inst)
        rows = sum(rs.row_cost(self.state, e) for e in range(self.inst.num_employees))
        parts = rows + rs.coverage_cost(self.state) + rs.global_cost(self.state)
        self.assertAlmostEqual(parts, rs.total_cost(self.state))

    def test_evaluation_separates_hard_from_soft(self):
        rs = RuleSet(self.inst)
        ev = rs.evaluate(self.state)
        self.assertFalse(ev.feasible)
        self.assertEqual(ev.hard_count, 1)          # one run of 4 days
        self.assertEqual(ev.soft_count, 1)          # one spread report
        self.assertEqual(ev.hard_cost, 2 * DEFAULT_HARD_WEIGHT)
        self.assertEqual(ev.soft_cost, 4 * 5.0)
        self.assertEqual(ev.cost, ev.hard_cost + ev.soft_cost)
        self.assertEqual(ev.cost, rs.total_cost(self.state))

    def test_by_rule_is_keyed_by_rule_id(self):
        rs = RuleSet(self.inst)
        ev = rs.evaluate(self.state)
        self.assertEqual(set(ev.by_rule), {"hard_run", "soft_fair"})
        self.assertEqual(sum(ev.by_rule.values()), ev.cost)

    def test_hard_violations_sort_ahead_of_soft_ones(self):
        rs = RuleSet(self.inst)
        ev = rs.evaluate(self.state)
        self.assertEqual([v.severity for v in ev.violations], ["hard", "soft"])

    def test_a_legal_roster_is_feasible_and_free(self):
        inst = instance(days=14, rules=[
            rule("hard_run", "max_consecutive_working_days", max=2)])
        state = lay_out(inst, {"A": "MM............",
                               "B": "..MM..........",
                               "C": "....MM........"})
        ev = RuleSet(inst).evaluate(state)
        self.assertTrue(ev.feasible)
        self.assertEqual(ev.cost, 0.0)
        self.assertEqual(ev.violations, [])

    def test_hard_violation_amount_ignores_soft_rules(self):
        rs = RuleSet(self.inst)
        self.assertEqual(rs.hard_violation_amount(self.state), 2)

    def test_hard_violation_amount_is_zero_exactly_when_feasible(self):
        rs = RuleSet(self.inst)
        legal = lay_out(self.inst, {"A": "MM............"})
        self.assertEqual(rs.hard_violation_amount(legal), 0.0)
        self.assertTrue(rs.evaluate(legal).feasible)

    def test_local_coverage_cost_matches_the_full_sweep(self):
        """The move delta trusts this: whole grid via cells == coverage_cost."""
        inst = instance(days=3, demand=[
            Demand(day=0, shift="M", role=DSG, required=2),
            Demand(day=1, shift="N", role=LSG, required=1),
        ], rules=[
            rule("under", "coverage", direction="under", weight=2.0),
            rule("over", "coverage", severity="soft", direction="over"),
            rule("floor", "headcount_per_shift", shift="N", min=1),
        ])
        rs = RuleSet(inst)
        state = lay_out(inst, {"A": "MM.", "B": "M.N", "C": ".NN"})
        cells = [(d, s, r)
                 for d in range(inst.num_days)
                 for s in range(inst.num_shifts)
                 for r in range(inst.num_roles)]
        day_shifts = [(d, s) for d in range(inst.num_days)
                      for s in range(inst.num_shifts)]
        self.assertAlmostEqual(rs.local_coverage_cost(state, cells, day_shifts),
                               rs.coverage_cost(state))

    def test_every_registered_type_declares_a_parameter_spec(self):
        """The spec is what validates JSON and draws the admin's form."""
        for rtype, cls in REGISTRY.items():
            self.assertEqual(cls.type, rtype)
            self.assertIn(cls.eval_kind, ("row", "coverage", "global"), rtype)
            for spec in cls.params_spec:
                self.assertIn("name", spec, rtype)
                self.assertIn("kind", spec, rtype)

    def test_an_unknown_rule_type_names_the_ones_that_exist(self):
        with self.assertRaisesRegex(ValueError, "unknown rule type"):
            build(rule("r", "make_everyone_happy"), self.inst)


class TestParameterGuards(unittest.TestCase):
    """A typo the admin cannot see through must be refused, not silently rostered."""

    def setUp(self):
        self.inst = instance(days=14)

    def refuses(self, rule_obj, wanted: str):
        with self.assertRaises(ValueError) as caught:
            build(rule_obj, self.inst)
        self.assertIn(wanted, str(caught.exception))

    def test_a_floor_above_a_ceiling_is_refused_in_every_range_rule(self):
        self.refuses(rule("r", "total_shifts_range", min=20, max=4),
                     "min 20 is above max 4")
        self.refuses(rule("r", "total_hours_range", min_hours=100, max_hours=40),
                     "min_hours 100 is above max_hours 40")
        self.refuses(rule("r", "shift_type_count_range", shift="N", min=9, max=2),
                     "min 9 is above max 2")
        self.refuses(rule("r", "headcount_per_shift", shift="N", min=9, max=2),
                     "min 9 is above max 2")
        self.refuses(rule("r", "hours_per_window", min_hours=50, max_hours=48),
                     "min_hours 50 is above max_hours 48")

    def test_every_range_rule_declares_its_pairs(self):
        """A range rule that forgets ``ranges`` would let the typo back in."""
        for rtype, cls in REGISTRY.items():
            names = {spec["name"] for spec in cls.params_spec}
            for low, high in (("min", "max"), ("min_hours", "max_hours")):
                if {low, high} <= names:
                    self.assertIn((low, high), cls.ranges, rtype)

    def test_equal_bounds_mean_exactly_that_many(self):
        r = rule("r", "total_shifts_range", min=4, max=4)
        self.assertEqual(self.worked(r, "MMMM.........."), 0)
        self.assertEqual(self.worked(r, "MMMMM........."), 1)
        self.assertEqual(self.worked(r, "MMM..........."), 1)

    def worked(self, rule_obj, row: str) -> float:
        state = lay_out(self.inst, {"A": row})
        return amount(self.inst, rule_obj, state, "A")

    def test_an_open_ceiling_leaves_the_floor_alone(self):
        r = rule("r", "total_shifts_range", min=6)
        self.assertEqual(build(r, self.inst).high, None)

    def test_a_number_below_its_declared_floor_is_refused(self):
        self.refuses(rule("r", "max_consecutive_working_days", max=0),
                     "max is 0 but the least it may be is 1")
        self.refuses(rule("r", "min_rest_hours", hours=-1),
                     "hours is -1 but the least it may be is 0")
        self.refuses(rule("r", "max_night_shifts", max=-2),
                     "max is -2 but the least it may be is 0")
        self.refuses(rule("r", "balance_workload", tolerance=-0.5),
                     "tolerance is -0.5 but the least it may be is 0")

    def test_a_number_that_is_not_a_number_is_refused(self):
        self.refuses(rule("r", "max_night_shifts", max="lots"),
                     "max must be a number")

    def test_the_floor_check_only_reads_numeric_params(self):
        """Shift ids and day lists are checked elsewhere, by name."""
        every = [spec for cls in REGISTRY.values() for spec in cls.params_spec]
        for spec in every:
            if "minimum" in spec:
                self.assertIn(spec["kind"], ("int", "float"), spec["name"])


class TestScopedCosting(unittest.TestCase):
    def test_contract_scope(self):
        staff = [
            Employee(id="A", roles=(DSG,), contract="permanent"),
            Employee(id="B", roles=(DSG, LSG), contract="casual"),
            Employee(id="C", roles=(LSG, MTS), contract="casual"),
        ]
        r = rule("cap", "total_shifts_range", max=1,
                 scope={"kind": "contracts", "ids": ["casual"]})
        inst = instance(days=7, employees=staff, rules=[r])
        state = lay_out(inst, {"A": "MMM....", "B": "MMM....", "C": "M......"})
        ev = RuleSet(inst).evaluate(state)
        # only B breaches: 3 duties against a cap of 1
        self.assertEqual(ev.hard_count, 1)
        self.assertEqual(ev.by_rule["cap"], 2 * DEFAULT_HARD_WEIGHT)
        self.assertEqual(ev.violations[0].employee, "B")


if __name__ == "__main__":
    unittest.main()
