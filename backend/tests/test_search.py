"""The search: exact move deltas, honest construction, and no backward steps."""

from __future__ import annotations

import time
import unittest

from roster.generate import small_instance
from roster.rules import RuleSet
from roster.schema import Demand, Rule
from roster.search import Solver, SolverOptions, solve
from roster.state import OFF, RosterState

from .helpers import DSG, LSG, MTS, instance, lay_out, rule


def fixed(**kw) -> SolverOptions:
    """Options whose result does not depend on how fast this machine is."""
    base = dict(seed=4242, max_seconds=120.0, max_iterations=4000,
                iterations_per_level=200, polish_iterations=0)
    base.update(kw)
    return SolverOptions(**base)


class TestMoveDeltas(unittest.TestCase):
    """Incremental costing against a full recomputation, move by move."""

    def setUp(self):
        self.inst = instance(days=10, demand=[
            Demand(day=d, shift="M", role=DSG, required=1) for d in range(10)
        ] + [
            Demand(day=d, shift="N", role=LSG, required=1) for d in range(0, 10, 2)
        ], rules=[
            rule("under", "coverage", direction="under"),
            rule("over", "coverage", severity="soft", weight=2.0, direction="over"),
            rule("run", "max_consecutive_working_days", max=3),
            rule("rest", "min_rest_hours", hours=12),
            rule("fair", "balance_workload", severity="soft", weight=5.0,
                 measure="shifts", tolerance=1),
        ])
        self.solver = Solver(self.inst, fixed())
        self.rules = self.solver.rules

    def test_delta_matches_full_recomputation_for_a_single_change(self):
        state = lay_out(self.inst, {"A": "MMM.......", "B": "N.N.......",
                                   "C": "..........",})
        before = self.rules.total_cost(state)
        delta, undo = self.solver.try_move(
            state, [(0, 3, self.inst.shift_index["M"], self.inst.role_index[DSG])])
        self.assertAlmostEqual(self.rules.total_cost(state), before + delta)
        self.solver.revert(state, undo)
        self.assertAlmostEqual(self.rules.total_cost(state), before)

    def test_revert_restores_the_roster_exactly(self):
        state = lay_out(self.inst, {"A": "MMM.......", "B": "N.N.......", "C": "...MM....."})
        snapshot = ([row[:] for row in state.shift_of], [row[:] for row in state.role_of])
        _delta, undo = self.solver.try_move(state, [(0, 0, OFF, OFF),
                                                    (2, 0, self.inst.shift_index["N"],
                                                     self.inst.role_index[LSG])])
        self.solver.revert(state, undo)
        self.assertEqual(state.shift_of, snapshot[0])
        self.assertEqual(state.role_of, snapshot[1])

    def test_every_move_generator_reports_an_exact_delta(self):
        """Each of the eight move kinds, driven directly rather than sampled."""
        state = self.solver.construct()
        for fn in self.solver._move_fns:
            for _attempt in range(40):
                changes = fn(state)
                if not changes:
                    continue
                before = self.rules.total_cost(state)
                delta, undo = self.solver.try_move(state, changes)
                self.assertAlmostEqual(self.rules.total_cost(state), before + delta,
                                       places=6, msg=fn.__name__)
                self.solver.revert(state, undo)
                self.assertAlmostEqual(self.rules.total_cost(state), before, places=6,
                                       msg=fn.__name__)

    def test_no_drift_over_a_long_run_of_mixed_accept_and_reject(self):
        """What the annealing loop actually does: keep some, undo others."""
        state = self.solver.construct()
        cost = self.rules.total_cost(state)
        rng = self.solver.rng
        for step in range(4000):
            changes = self.solver.random_move(state)
            if not changes:
                continue
            delta, undo = self.solver.try_move(state, changes)
            if delta <= 0 or rng.random() < 0.3:
                cost += delta
            else:
                self.solver.revert(state, undo)
            if step % 500 == 0:
                self.assertAlmostEqual(cost, self.rules.total_cost(state), places=6,
                                       msg=f"drift at step {step}")
        self.assertAlmostEqual(cost, self.rules.total_cost(state), places=6)

    def test_moves_never_produce_an_illegal_state_shape(self):
        """One shift per person per day is structural; the moves must respect it."""
        state = self.solver.construct()
        for _ in range(2000):
            changes = self.solver.random_move(state)
            if not changes:
                continue
            self.solver.try_move(state, changes)
        for e in range(self.inst.num_employees):
            for d in range(self.inst.num_days):
                s, r = state.shift_of[e][d], state.role_of[e][d]
                if s == OFF:
                    self.assertEqual(r, OFF)
                else:
                    self.assertIn(r, self.inst.roles_of[e],
                                  f"{e} given a role they do not hold")

    def test_coverage_counters_stay_in_step_with_the_grid(self):
        state = self.solver.construct()
        for _ in range(1500):
            changes = self.solver.random_move(state)
            if changes:
                self.solver.try_move(state, changes)
        rebuilt = RosterState.from_dict(self.inst, state.to_dict())
        self.assertEqual(state.cov, rebuilt.cov)
        self.assertEqual(state.headcount, rebuilt.headcount)


class TestConstruction(unittest.TestCase):
    def test_construction_covers_demand_when_there_are_enough_people(self):
        inst = instance(days=5, demand=[
            Demand(day=d, shift="M", role=DSG, required=1) for d in range(5)
        ], rules=[rule("under", "coverage", direction="under")])
        state = Solver(inst, fixed()).construct()
        self.assertEqual(state.under_coverage(), 0)

    def test_construction_places_fixed_assignments_first(self):
        inst = instance(days=5, demand=[
            Demand(day=0, shift="M", role=DSG, required=2),
        ], rules=[
            rule("under", "coverage", direction="under"),
            rule("fix", "fixed_assignment", day=0, shift="E", role=LSG,
                 scope={"kind": "employees", "ids": ["C"]}),
        ])
        state = Solver(inst, fixed()).construct()
        self.assertEqual(state.shift_of[inst.emp_index["C"]][0], inst.shift_index["E"])
        self.assertEqual(state.role_of[inst.emp_index["C"]][0], inst.role_index[LSG])
        self.assertEqual(state.under_coverage(), 0)

    def test_construction_leaves_impossible_demand_short_rather_than_cheating(self):
        """Two DSG mornings wanted, one DSG-qualified person free: stay honest."""
        inst = instance(days=1, demand=[
            Demand(day=0, shift="M", role=MTS, required=2),
        ], rules=[rule("under", "coverage", direction="under")])
        state = Solver(inst, fixed()).construct()
        self.assertEqual(state.under_coverage(), 1)     # only C holds MTS
        self.assertEqual(state.cov[0][inst.shift_index["M"]][inst.role_index[MTS]], 1)

    def test_construction_can_start_from_a_partly_written_roster(self):
        inst = instance(days=3, demand=[
            Demand(day=d, shift="M", role=DSG, required=1) for d in range(3)
        ], rules=[rule("under", "coverage", direction="under")])
        start = lay_out(inst, {"B": "MMM"})
        state = Solver(inst, fixed()).construct(start)
        self.assertIs(state, start)
        self.assertEqual(state.under_coverage(), 0)
        # B's duties were already there, so nobody else was needed
        self.assertEqual(state.assignments(), 3)

    def test_construction_spreads_work_rather_than_loading_one_person(self):
        inst = instance(days=6, demand=[
            Demand(day=d, shift="M", role=DSG, required=1) for d in range(6)
        ], rules=[rule("under", "coverage", direction="under")])
        state = Solver(inst, fixed()).construct()
        loads = sorted(state.working_days(e) for e in range(inst.num_employees))
        self.assertEqual(loads, [0, 3, 3])              # only A and B hold DSG


    def test_an_instance_with_rules_but_no_demand_table_still_searches(self):
        """A regression: the gap-seeking move used to crash with nothing to fill."""
        inst = instance(days=7, rules=[
            rule("floor", "headcount_per_shift", shift="M", min=1),
            rule("run", "max_consecutive_working_days", max=3),
        ])
        result = Solver(inst, fixed(max_iterations=2000)).solve()
        self.assertEqual(result.state.under_coverage(), 0)   # nothing was demanded
        self.assertAlmostEqual(result.cost,
                               RuleSet(inst, fixed().hard_weight).total_cost(result.state))


class TestAnnealAndPolish(unittest.TestCase):
    def test_polish_never_worsens_the_roster(self):
        inst = small_instance()
        solver = Solver(inst, fixed())
        state = solver.construct()
        before = solver.rules.total_cost(state)
        gained = solver.polish(state, 3000, time.perf_counter() + 30.0)
        after = solver.rules.total_cost(state)
        self.assertLessEqual(after, before + 1e-9)
        self.assertAlmostEqual(gained, before - after, places=6)
        self.assertGreaterEqual(gained, 0.0)

    def test_anneal_returns_the_best_roster_it_saw_and_costs_it_correctly(self):
        inst = small_instance()
        solver = Solver(inst, fixed())
        start = solver.construct()
        before = solver.rules.total_cost(start)
        state, cost, iterations, accepted, history = solver.anneal(
            start, time.perf_counter())
        self.assertAlmostEqual(cost, solver.rules.total_cost(state), places=6)
        self.assertLessEqual(cost, before + 1e-9)
        self.assertGreater(iterations, 0)
        self.assertGreater(accepted, 0)
        self.assertTrue(history)
        self.assertEqual(len(history[0]), 3)

    def test_calibrated_temperature_is_positive_and_scales_with_the_weights(self):
        light = instance(days=10, rules=[
            rule("run", "max_consecutive_working_days", weight=1.0, max=2)])
        heavy = instance(days=10, rules=[
            rule("run", "max_consecutive_working_days", weight=10.0, max=2)])
        state_l = lay_out(light, {"A": "MMMM......"})
        state_h = lay_out(heavy, {"A": "MMMM......"})
        t_light = Solver(light, fixed()).calibrate_temperature(state_l, samples=400)
        t_heavy = Solver(heavy, fixed()).calibrate_temperature(state_h, samples=400)
        self.assertGreater(t_light, 0.0)
        self.assertGreater(t_heavy, t_light)

    def test_calibration_leaves_the_roster_untouched(self):
        inst = small_instance()
        solver = Solver(inst, fixed())
        state = solver.construct()
        snapshot = [row[:] for row in state.shift_of]
        solver.calibrate_temperature(state, samples=200)
        self.assertEqual(state.shift_of, snapshot)

    def test_iteration_cap_is_respected(self):
        inst = small_instance()
        solver = Solver(inst, fixed(max_iterations=600, iterations_per_level=200))
        _state, _cost, iterations, _acc, _hist = solver.anneal(
            solver.construct(), time.perf_counter())
        self.assertEqual(iterations, 600)


class TestDeterminismAndResult(unittest.TestCase):
    def test_same_seed_and_iteration_cap_give_the_same_roster(self):
        inst = small_instance()
        a = Solver(inst, fixed()).solve()
        b = Solver(inst, fixed()).solve()
        self.assertEqual(a.state.shift_of, b.state.shift_of)
        self.assertEqual(a.state.role_of, b.state.role_of)
        self.assertAlmostEqual(a.cost, b.cost)

    def test_a_different_seed_explores_differently(self):
        inst = small_instance()
        a = Solver(inst, fixed(seed=1)).solve()
        b = Solver(inst, fixed(seed=999)).solve()
        self.assertNotEqual(a.state.shift_of, b.state.shift_of)

    def test_result_cost_agrees_with_an_independent_evaluation(self):
        inst = small_instance()
        result = Solver(inst, fixed()).solve()
        fresh = RuleSet(inst, fixed().hard_weight)
        self.assertAlmostEqual(result.cost, fresh.total_cost(result.state), places=6)
        self.assertAlmostEqual(result.evaluation.cost, result.cost, places=6)

    def test_search_improves_on_the_greedy_construction(self):
        inst = small_instance()
        result = Solver(inst, fixed(max_iterations=20000)).solve()
        self.assertLessEqual(result.cost, result.construction_cost + 1e-9)

    def test_the_roster_only_holds_duties_people_are_qualified_for(self):
        inst = small_instance()
        result = Solver(inst, fixed()).solve()
        for e in range(inst.num_employees):
            for d in range(inst.num_days):
                s = result.state.shift_of[e][d]
                if s != OFF:
                    self.assertIn(result.state.role_of[e][d], inst.roles_of[e])

    def test_module_level_solve_is_the_same_as_using_the_class(self):
        inst = small_instance()
        a = solve(inst, fixed())
        b = Solver(inst, fixed()).solve()
        self.assertEqual(a.state.shift_of, b.state.shift_of)
        self.assertIn("roster", a.to_dict())
        self.assertIn("score", a.to_dict())
        self.assertIn("search", a.to_dict())

    def test_small_instance_is_solved_legally(self):
        result = solve(small_instance(), fixed(max_iterations=40000))
        self.assertTrue(result.feasible, result.evaluation.by_rule)
        self.assertEqual(result.state.under_coverage(), 0)


if __name__ == "__main__":
    unittest.main()
