"""Construction plus simulated annealing."""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

from .rules import DEFAULT_HARD_WEIGHT, Evaluation, RuleSet
from .schema import Instance
from .state import OFF, RosterState


@dataclass
class SolverOptions:
    """Search settings. Defaults are tuned for a month-long, few-dozen-people roster."""

    seed: int = 12345
    max_seconds: float = 20.0
    max_iterations: int = 0            # 0 = bounded by time only
    start_temperature: float = 0.0     # 0 = calibrate from sampled moves
    end_temperature: float = 0.05
    cooling: float = 0.985
    iterations_per_level: int = 0       # 0 = 20 x employees
    reheat_after_levels: int = 15
    polish_iterations: int = 4000
    construct_candidates: int = 0        # 0 = try every free qualified person
    hard_weight: float = DEFAULT_HARD_WEIGHT
    verbose: bool = False

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class SolveResult:
    state: RosterState
    evaluation: Evaluation
    cost: float
    iterations: int
    accepted: int
    seconds: float
    construction_cost: float
    history: list[tuple[float, float, float]] = field(default_factory=list)

    @property
    def feasible(self) -> bool:
        return self.evaluation.feasible

    def to_dict(self) -> dict:
        return {
            "roster": self.state.to_dict(),
            "score": self.evaluation.to_dict(),
            "search": {
                "cost": round(self.cost, 4),
                "construction_cost": round(self.construction_cost, 4),
                "iterations": self.iterations,
                "accepted": self.accepted,
                "seconds": round(self.seconds, 3),
            },
        }


class Solver:
    """Greedy construction plus simulated annealing over a :class:`RuleSet`."""

    def __init__(self, inst: Instance, options: SolverOptions | None = None) -> None:
        self.inst = inst
        self.opt = options or SolverOptions()
        self.rules = RuleSet(inst, self.opt.hard_weight)
        self.rng = random.Random(self.opt.seed)

        # every (shift, role) pair each person could legally be given
        self.assign_options = [
            tuple((s, r) for s in range(inst.num_shifts) for r in sorted(inst.roles_of[e]))
            for e in range(inst.num_employees)
        ]
        self.role_options = [tuple(sorted(inst.roles_of[e])) for e in range(inst.num_employees)]
        self.cells = list(inst.demand_cells)

        self._moves = [
            (self.m_change, 30),
            (self.m_fill_gap, 25),
            (self.m_swap_within, 15),
            (self.m_unassign, 10),
            (self.m_change_role, 8),
            (self.m_swap_day, 8),
            (self.m_days_off_block, 3),
            (self.m_swap_block, 1),
        ]
        self._move_fns = [m for m, _w in self._moves]
        self._move_weights = [w for _m, w in self._moves]
        # flattened for O(1) sampling in the inner loop
        self._move_pool = [fn for fn, w in self._moves for _ in range(w)]

    def solve(self) -> SolveResult:
        started = time.perf_counter()
        state = self.construct()
        construction_cost = self.rules.total_cost(state)
        state, cost, iterations, accepted, history = self.anneal(state, started)
        elapsed = time.perf_counter() - started
        evaluation = self.rules.evaluate(state)
        return SolveResult(
            state=state,
            evaluation=evaluation,
            cost=cost,
            iterations=iterations,
            accepted=accepted,
            seconds=elapsed,
            construction_cost=construction_cost,
            history=history,
        )

    def construct(self, state: RosterState | None = None) -> RosterState:
        """Fill the demand table slot by slot with the cheapest qualified person."""
        st = state if state is not None else RosterState(self.inst)
        inst, rules, rng = self.inst, self.rules, self.rng
        pool = self.opt.construct_candidates or inst.num_employees

        # committed duties go on the board first, so the greedy pass fills around them
        for ev in rules.evaluators:
            if ev.type != "fixed_assignment":
                continue
            for e in ev.members:
                if st.shift_of[e][ev.day] != OFF:
                    continue
                r = ev.r if ev.r is not None else min(inst.roles_of[e])
                if r in inst.roles_of[e]:
                    st.assign(e, ev.day, ev.s, r)

        order = sorted(inst.demand_cells, key=lambda k: (k[0], -inst.required[k], k[1], k[2]))
        for d, s, r in order:
            need = inst.required[(d, s, r)]
            while st.cov[d][s][r] < need:
                free = [e for e in inst.eligible[r] if not st.is_working(e, d)]
                if not free:
                    break
                free.sort(key=lambda e: (st.working_days(e), rng.random()))
                best, best_delta = free[0], None
                for e in free[:pool]:
                    before = rules.row_cost(st, e)
                    st.assign(e, d, s, r)
                    delta = rules.row_cost(st, e) - before
                    st.unassign(e, d)
                    if best_delta is None or delta < best_delta:
                        best, best_delta = e, delta
                        if delta <= 0.0:
                            break
                st.assign(best, d, s, r)
        return st

    def try_move(self, state: RosterState, changes: list[tuple[int, int, int, int]]):
        """Apply ``changes`` and return ``(delta, undo)``."""
        rules = self.rules
        emps = {c[0] for c in changes}
        cells: set[tuple[int, int, int]] = set()
        day_shifts: set[tuple[int, int]] = set()
        undo = []
        for e, d, s, r in changes:
            old_s, old_r = state.shift_of[e][d], state.role_of[e][d]
            undo.append((e, d, old_s, old_r))
            if old_s != OFF:
                cells.add((d, old_s, old_r))
                day_shifts.add((d, old_s))
            if s != OFF:
                cells.add((d, s, r))
                day_shifts.add((d, s))

        old = sum(rules.row_cost(state, e) for e in emps)
        old += rules.local_coverage_cost(state, cells, day_shifts)
        if rules.has_globals:
            old += rules.global_cost(state)

        for e, d, s, r in changes:
            state.set_day(e, d, s, r)

        new = sum(rules.row_cost(state, e) for e in emps)
        new += rules.local_coverage_cost(state, cells, day_shifts)
        if rules.has_globals:
            new += rules.global_cost(state)
        return new - old, undo

    def revert(self, state: RosterState, undo) -> None:
        for e, d, s, r in undo:
            state.set_day(e, d, s, r)

    # Each returns (employee, day, shift, role) changes, or None when the draw was useless.
    def m_change(self, state):
        """Give one person a different duty (or a first duty) on one day."""
        e = self.rng.randrange(self.inst.num_employees)
        d = self.rng.randrange(self.inst.num_days)
        s, r = self.rng.choice(self.assign_options[e])
        if state.shift_of[e][d] == s and state.role_of[e][d] == r:
            return None
        return [(e, d, s, r)]

    def m_unassign(self, state):
        """Take one duty away, freeing the person up."""
        e = self.rng.randrange(self.inst.num_employees)
        working = [d for d in range(self.inst.num_days) if state.shift_of[e][d] != OFF]
        if not working:
            return None
        return [(e, self.rng.choice(working), OFF, OFF)]

    def m_change_role(self, state):
        """Keep the shift, cover a different role - cross-cover between DSG and LSG."""
        e = self.rng.randrange(self.inst.num_employees)
        options = self.role_options[e]
        if len(options) < 2:
            return None
        working = [d for d in range(self.inst.num_days) if state.shift_of[e][d] != OFF]
        if not working:
            return None
        d = self.rng.choice(working)
        r = self.rng.choice(options)
        if r == state.role_of[e][d]:
            return None
        return [(e, d, state.shift_of[e][d], r)]

    def m_fill_gap(self, state):
        """Target an actual staffing gap rather than hoping to stumble on one."""
        inst, rng = self.inst, self.rng
        if not self.cells:
            # no demand table means no gaps; the other moves carry the search
            return None
        for _ in range(30):
            d, s, r = rng.choice(self.cells)
            if state.cov[d][s][r] >= inst.required[(d, s, r)]:
                continue
            free = [e for e in inst.eligible[r] if state.shift_of[e][d] == OFF]
            if not free:
                return None
            return [(rng.choice(free), d, s, r)]
        return None

    def m_swap_within(self, state):
        """Move one person's duties between two of their own days."""
        e = self.rng.randrange(self.inst.num_employees)
        d1 = self.rng.randrange(self.inst.num_days)
        d2 = self.rng.randrange(self.inst.num_days)
        if d1 == d2:
            return None
        s1, r1 = state.shift_of[e][d1], state.role_of[e][d1]
        s2, r2 = state.shift_of[e][d2], state.role_of[e][d2]
        if (s1, r1) == (s2, r2):
            return None
        return [(e, d1, s2, r2), (e, d2, s1, r1)]

    def m_swap_day(self, state):
        """Exchange two people's duties on the same day, qualifications permitting."""
        inst, rng = self.inst, self.rng
        e1 = rng.randrange(inst.num_employees)
        e2 = rng.randrange(inst.num_employees)
        if e1 == e2:
            return None
        d = rng.randrange(inst.num_days)
        s1, r1 = state.shift_of[e1][d], state.role_of[e1][d]
        s2, r2 = state.shift_of[e2][d], state.role_of[e2][d]
        if (s1, r1) == (s2, r2):
            return None
        if s2 != OFF and r2 not in inst.roles_of[e1]:
            return None
        if s1 != OFF and r1 not in inst.roles_of[e2]:
            return None
        return [(e1, d, s2, r2), (e2, d, s1, r1)]

    def m_swap_block(self, state):
        """Exchange a run of days between two people."""
        inst, rng = self.inst, self.rng
        e1 = rng.randrange(inst.num_employees)
        e2 = rng.randrange(inst.num_employees)
        if e1 == e2:
            return None
        length = rng.randint(2, min(7, inst.num_days))
        start = rng.randrange(inst.num_days - length + 1)
        changes = []
        for d in range(start, start + length):
            s1, r1 = state.shift_of[e1][d], state.role_of[e1][d]
            s2, r2 = state.shift_of[e2][d], state.role_of[e2][d]
            if (s1, r1) == (s2, r2):
                continue
            if s2 != OFF and r2 not in inst.roles_of[e1]:
                return None
            if s1 != OFF and r1 not in inst.roles_of[e2]:
                return None
            changes.append((e1, d, s2, r2))
            changes.append((e2, d, s1, r1))
        return changes or None

    def m_days_off_block(self, state):
        """Clear a short run of days for one person, creating a proper break."""
        inst, rng = self.inst, self.rng
        e = rng.randrange(inst.num_employees)
        length = rng.randint(2, min(3, inst.num_days))
        start = rng.randrange(inst.num_days - length + 1)
        changes = [
            (e, d, OFF, OFF) for d in range(start, start + length)
            if state.shift_of[e][d] != OFF
        ]
        return changes or None

    def random_move(self, state):
        return self.rng.choice(self._move_pool)(state)

    def calibrate_temperature(self, state: RosterState, samples: int = 250) -> float:
        """Pick a starting temperature from the moves this instance actually offers."""
        deltas = []
        for _ in range(samples):
            changes = self.random_move(state)
            if not changes:
                continue
            delta, undo = self.try_move(state, changes)
            self.revert(state, undo)
            if delta > 0:
                deltas.append(delta)
        if not deltas:
            return 1.0
        return max((sum(deltas) / len(deltas)) / math.log(2.0), 1e-6)

    def anneal(self, state: RosterState, started: float):
        opt, rules, rng = self.opt, self.rules, self.rng
        cost = rules.total_cost(state)
        best = state.copy()
        best_cost = cost
        t0 = opt.start_temperature or self.calibrate_temperature(state)
        t = t0
        per_level = opt.iterations_per_level or max(200, 20 * self.inst.num_employees)
        deadline = started + opt.max_seconds
        iterations = accepted = stale = 0
        history: list[tuple[float, float, float]] = []
        exp, clock, pool = math.exp, time.perf_counter, self._move_pool

        while clock() < deadline:
            if opt.max_iterations and iterations >= opt.max_iterations:
                break
            improved = False
            for _ in range(per_level):
                changes = rng.choice(pool)(state)
                iterations += 1
                if not changes:
                    continue
                delta, undo = self.try_move(state, changes)
                if delta <= 0 or (delta < 60.0 * t and rng.random() < exp(-delta / t)):
                    cost += delta
                    accepted += 1
                    if cost < best_cost - 1e-9:
                        best_cost = cost
                        best = state.copy()
                        improved = True
                else:
                    self.revert(state, undo)

            history.append((round(clock() - started, 3), round(cost, 3), round(best_cost, 3)))
            stale = 0 if improved else stale + 1
            t *= opt.cooling
            if t < opt.end_temperature or stale >= opt.reheat_after_levels:
                # reheat rather than stop; the time budget is the real terminator
                t0 = max(t0 * 0.5, opt.end_temperature)
                t = t0
                stale = 0
                if opt.verbose:
                    print(f"  reheat to t={t:.4g} at {clock() - started:.1f}s, best={best_cost:.2f}")

        polished = self.polish(best, opt.polish_iterations, clock() + min(2.0, opt.max_seconds * 0.2))
        best_cost = rules.total_cost(best)
        if opt.verbose:
            print(f"  polish improved by {polished:.2f}; final cost {best_cost:.2f}")
        return best, best_cost, iterations, accepted, history

    def polish(self, state: RosterState, iterations: int, deadline: float) -> float:
        """Strict descent - accept only improvements. Cleans up the last few cents."""
        gained = 0.0
        clock = time.perf_counter
        for _ in range(iterations):
            if clock() >= deadline:
                break
            changes = self.random_move(state)
            if not changes:
                continue
            delta, undo = self.try_move(state, changes)
            if delta < -1e-12:
                gained += delta
            else:
                self.revert(state, undo)
        return -gained


def solve(inst: Instance, options: SolverOptions | None = None) -> SolveResult:
    """Convenience wrapper - the one call the API layer will make."""
    return Solver(inst, options).solve()
