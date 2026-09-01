from __future__ import annotations

import datetime as dt
import unittest

from roster.generate import university_instance
from roster.search import SolverOptions, solve
from roster.service import solve_payload


class Audit:
    """Re-derives the facts about a roster from the response payload only."""

    def __init__(self, instance: dict, roster: dict) -> None:
        self.inst = instance
        self.shifts = {s["id"]: s for s in instance["shifts"]}
        self.roles = {r["id"] for r in instance["roles"]}
        self.staff = {e["id"]: e for e in instance["employees"]}
        self.num_days = instance["horizon"]["num_days"]
        self.start = dt.date.fromisoformat(instance["horizon"]["start"])
        self.weekend = set(instance["horizon"]["weekend_days"])

        # grid[employee id] -> list of (shift id, role id) or None, one per day
        self.grid = {}
        for row in roster["rows"]:
            cells = []
            for cell in row["days"]:
                cells.append(None if cell is None else (cell["shift"], cell["role"]))
            self.grid[row["employee"]] = cells

        self.rules = {r["id"]: r for r in instance["rules"]}
        self.hard = [r for r in instance["rules"] if r["severity"] == "hard"]

    def date_of(self, d: int) -> dt.date:
        return self.start + dt.timedelta(days=d)

    def day_index(self, iso: str) -> int:
        return (dt.date.fromisoformat(iso) - self.start).days

    def is_weekend(self, d: int) -> bool:
        return self.date_of(d).weekday() in self.weekend

    def members(self, rule: dict) -> list[str]:
        scope = rule.get("scope") or {}
        kind, ids = scope.get("kind", "all"), scope.get("ids", [])
        if kind == "all":
            return list(self.staff)
        if kind == "employees":
            return [e for e in self.staff if e in ids]
        if kind == "roles":
            return [e for e, emp in self.staff.items()
                    if set(emp["roles"]) & set(ids)]
        if kind == "contracts":
            return [e for e, emp in self.staff.items() if emp["contract"] in ids]
        raise AssertionError(f"unknown scope kind {kind!r}")

    def worked(self, e: str) -> list[int]:
        return [d for d, c in enumerate(self.grid[e]) if c is not None]

    def runs(self, flags: list[bool]):
        """(start, length) for every maximal run of True."""
        out, start = [], None
        for i, flag in enumerate(flags + [False]):
            if flag and start is None:
                start = i
            elif not flag and start is not None:
                out.append((start, i - start))
                start = None
        return out

    def end_min(self, shift_id: str) -> int:
        s = self.shifts[shift_id]
        return s["start_min"] + s["duration_min"]

    def rest_gap(self, first: str, second: str) -> int:
        """Minutes between the end of ``first`` and the start of ``second`` next day."""
        return (24 * 60 + self.shifts[second]["start_min"]) - self.end_min(first)

    def calendar_weeks(self) -> list[list[int]]:
        weeks, current = [], []
        for d in range(self.num_days):
            if self.date_of(d).weekday() == 0 and current:
                weeks.append(current)
                current = []
            current.append(d)
        if current:
            weeks.append(current)
        return weeks

    def weekend_blocks(self) -> list[list[int]]:
        blocks, current = [], []
        for d in range(self.num_days):
            if self.is_weekend(d):
                current.append(d)
            elif current:
                blocks.append(current)
                current = []
        if current:
            blocks.append(current)
        return blocks

    def structural_faults(self) -> list[str]:
        """Things no roster may contain whatever the rules say."""
        bad = []
        for e, cells in self.grid.items():
            if len(cells) != self.num_days:
                bad.append(f"{e} has {len(cells)} days, horizon has {self.num_days}")
            for d, cell in enumerate(cells):
                if cell is None:
                    continue
                shift, role = cell
                if shift not in self.shifts:
                    bad.append(f"{e} day {d}: unknown shift {shift!r}")
                if role not in self.roles:
                    bad.append(f"{e} day {d}: unknown role {role!r}")
                elif role not in self.staff[e]["roles"]:
                    bad.append(f"{e} day {d}: not qualified for {role}")
        missing = set(self.staff) - set(self.grid)
        if missing:
            bad.append(f"no roster row for {sorted(missing)}")
        return bad

    def shortfalls(self) -> list[str]:
        have: dict[tuple[int, str, str], int] = {}
        for e, cells in self.grid.items():
            for d, cell in enumerate(cells):
                if cell is not None:
                    have[(d, cell[0], cell[1])] = have.get((d, cell[0], cell[1]), 0) + 1
        out = []
        for line in self.inst["demand"]:
            key = (line["day"], line["shift"], line["role"])
            got = have.get(key, 0)
            if got < line["required"]:
                out.append(f"{self.date_of(line['day'])} {line['shift']}/{line['role']}: "
                           f"{got} of {line['required']}")
        return out

    def breaches(self) -> list[str]:
        """Every hard rule in the instance, re-checked from first principles."""
        out = []
        for rule in self.hard:
            out.extend(f"[{rule['id']}] {msg}" for msg in self.check(rule))
        return out

    def check(self, rule: dict) -> list[str]:
        rtype, p = rule["type"], rule["params"]
        out = []

        if rtype == "coverage":
            if p.get("direction", "both") in ("under", "both"):
                out.extend(self.shortfalls())

        elif rtype == "headcount_per_shift":
            floor, cap = p.get("min", 0), p.get("max")
            days = p.get("days") or list(range(self.num_days))
            days = [self.day_index(d) if isinstance(d, str) else d for d in days]
            for d in days:
                n = sum(1 for cells in self.grid.values()
                        if cells[d] is not None and cells[d][0] == p["shift"])
                if n < floor:
                    out.append(f"{self.date_of(d)} {p['shift']}: {n} on site, {floor} needed")
                if cap is not None and n > cap:
                    out.append(f"{self.date_of(d)} {p['shift']}: {n} on site, max {cap}")

        elif rtype == "max_consecutive_working_days":
            for e in self.members(rule):
                for start, length in self.runs([c is not None for c in self.grid[e]]):
                    if length > p["max"]:
                        out.append(f"{e}: {length} days from {self.date_of(start)}")

        elif rtype == "max_consecutive_same_shift":
            want = p.get("shift") or ""
            for e in self.members(rule):
                cells = self.grid[e]
                targets = [want] if want else sorted(self.shifts)
                for shift in targets:
                    for start, length in self.runs(
                            [c is not None and c[0] == shift for c in cells]):
                        if length > p["max"]:
                            out.append(f"{e}: {length} {shift} from {self.date_of(start)}")

        elif rtype == "min_rest_hours":
            need = p["hours"] * 60
            for e in self.members(rule):
                cells = self.grid[e]
                for d in range(self.num_days - 1):
                    a, b = cells[d], cells[d + 1]
                    if a and b and self.rest_gap(a[0], b[0]) < need:
                        out.append(f"{e}: {a[0]} then {b[0]} on {self.date_of(d + 1)}")

        elif rtype == "min_days_off_per_window":
            weeks = self.calendar_weeks()
            for e in self.members(rule):
                for week in weeks:
                    if len(week) < 7 and not p.get("include_partial", False):
                        continue
                    off = sum(1 for d in week if self.grid[e][d] is None)
                    if off < p["min"]:
                        out.append(f"{e}: {off} days off in the week of "
                                   f"{self.date_of(week[0])}")

        elif rtype == "max_working_days_per_window":
            if p.get("window", "calendar") == "calendar":
                windows = self.calendar_weeks()
                if not p.get("include_partial", True):
                    windows = [w for w in windows if len(w) == 7]
            else:
                size = p.get("window_days", 7)
                windows = [list(range(i, min(i + size, self.num_days)))
                           for i in range(self.num_days - size + 1)]
            for e in self.members(rule):
                for window in windows:
                    worked = sum(1 for d in window if self.grid[e][d] is not None)
                    if worked > p["max"]:
                        out.append(f"{e}: {worked} days worked from "
                                   f"{self.date_of(window[0])}")

        elif rtype == "total_shifts_range":
            for e in self.members(rule):
                n = len(self.worked(e))
                if n < p.get("min", 0):
                    out.append(f"{e}: {n} duties, at least {p['min']} wanted")
                if p.get("max") is not None and n > p["max"]:
                    out.append(f"{e}: {n} duties, at most {p['max']} allowed")

        elif rtype == "max_night_shifts":
            nights = {s["id"] for s in self.inst["shifts"] if s["counts_as_night"]}
            for e in self.members(rule):
                n = sum(1 for c in self.grid[e] if c and c[0] in nights)
                if n > p["max"]:
                    out.append(f"{e}: {n} nights, at most {p['max']} allowed")

        elif rtype == "max_weekends_worked":
            for e in self.members(rule):
                n = sum(1 for block in self.weekend_blocks()
                        if any(self.grid[e][d] is not None for d in block))
                if n > p["max"]:
                    out.append(f"{e}: {n} weekends, at most {p['max']} allowed")

        elif rtype == "complete_weekends":
            for e in self.members(rule):
                for block in self.weekend_blocks():
                    on = [d for d in block if self.grid[e][d] is not None]
                    if on and len(on) != len(block):
                        out.append(f"{e}: part of the weekend of {self.date_of(block[0])}")

        elif rtype == "unavailable":
            blocked = {self.day_index(d) if isinstance(d, str) else d
                       for d in p["days"]}
            only = set(p.get("shifts") or ())
            for e in self.members(rule):
                for d in sorted(blocked):
                    cell = self.grid[e][d]
                    if cell and (not only or cell[0] in only):
                        out.append(f"{e}: rostered on {self.date_of(d)} while unavailable")

        elif rtype == "fixed_assignment":
            d = p["day"]
            d = self.day_index(d) if isinstance(d, str) else d
            for e in self.members(rule):
                cell = self.grid[e][d]
                ok = cell is not None and cell[0] == p["shift"] and (
                    not p.get("role") or cell[1] == p["role"])
                if not ok:
                    out.append(f"{e}: missing the fixed {p['shift']} on {self.date_of(d)}")

        elif rtype in ("min_consecutive_working_days", "min_consecutive_days_off",
                       "max_consecutive_days_off", "shift_type_count_range",
                       "total_hours_range", "forbidden_shift_sequence"):
            pass          # not hard in this instance; covered by the unit tests

        else:
            raise AssertionError(f"the auditor does not know rule type {rtype!r}")
        return out


# The month
BUDGET = SolverOptions(seed=20260901, max_seconds=25.0, polish_iterations=4000)


class TestMonthLongRoster(unittest.TestCase):
    """A 31-day roster from an arbitrary start date, 44 staff, 32 rules."""

    @classmethod
    def setUpClass(cls):
        cls.inst = university_instance()
        cls.result = solve(cls.inst, BUDGET)
        cls.payload = {"instance": cls.inst.to_dict(),
                       "roster": cls.result.state.to_dict()}
        cls.audit = Audit(cls.payload["instance"], cls.payload["roster"])

    def test_the_instance_is_the_realistic_one(self):
        self.assertEqual(self.inst.num_days, 31)
        self.assertEqual(self.inst.horizon.start.isoformat(), "2026-09-12")
        self.assertNotEqual(self.inst.horizon.start.day, 1)   # arbitrary start date
        self.assertEqual(self.inst.num_employees, 44)
        self.assertEqual(self.inst.num_shifts, 3)
        self.assertGreaterEqual(len(self.inst.rules), 30)
        self.assertGreaterEqual(self.inst.total_required, 500)

    def test_the_solver_calls_it_legal(self):
        ev = self.result.evaluation
        self.assertTrue(ev.feasible, f"hard breaches: {ev.hard_count}")
        self.assertEqual(ev.hard_cost, 0.0)

    def test_the_roster_is_structurally_sound(self):
        self.assertEqual(self.audit.structural_faults(), [])

    def test_every_demanded_duty_is_staffed(self):
        self.assertEqual(self.audit.shortfalls(), [])
        self.assertEqual(self.result.state.under_coverage(), 0)

    def test_an_independent_audit_finds_no_hard_breach(self):
        """The claim that matters: two implementations, same verdict."""
        self.assertEqual(self.audit.breaches(), [])

    def test_the_audit_actually_examined_every_hard_rule(self):
        """Guard against the audit passing because it checked nothing."""
        checked = {r["type"] for r in self.audit.hard}
        self.assertGreaterEqual(len(self.audit.hard), 14)
        for rtype in ("coverage", "max_consecutive_working_days", "min_rest_hours",
                      "headcount_per_shift", "total_shifts_range", "unavailable"):
            self.assertIn(rtype, checked)

    def test_the_audit_would_notice_a_broken_roster(self):
        """Break one thing on purpose; the auditor must say so."""
        broken = {"rows": [dict(row, days=list(row["days"]))
                           for row in self.payload["roster"]["rows"]]}
        # take the whole first week off the first person
        for d in range(7):
            broken["rows"][0]["days"][d] = None
        audit = Audit(self.payload["instance"], broken)
        self.assertTrue(audit.shortfalls() or audit.breaches())

    def test_leave_and_fixed_duties_were_honoured(self):
        leave = [r for r in self.inst.rules if r.type == "unavailable"]
        fixed = [r for r in self.inst.rules if r.type == "fixed_assignment"]
        self.assertTrue(leave)
        self.assertTrue(fixed)
        for rule in leave + fixed:
            self.assertEqual(self.audit.check(rule.to_dict()), [], rule.label)

    def test_the_workload_is_shared_rather_than_dumped_on_a_few(self):
        loads = [len(self.audit.worked(e)) for e in self.audit.grid]
        self.assertGreaterEqual(min(loads), 8)         # the month_load floor
        self.assertLessEqual(max(loads), 22)           # and its ceiling
        self.assertLessEqual(max(loads) - min(loads), 14)

    def test_the_search_improved_on_the_greedy_starting_point(self):
        self.assertLessEqual(self.result.cost, self.result.construction_cost + 1e-9)
        self.assertGreater(self.result.iterations, 1000)

    def test_the_reported_cost_is_the_cost_of_the_roster_returned(self):
        from roster.rules import RuleSet
        fresh = RuleSet(self.inst, BUDGET.hard_weight)
        self.assertAlmostEqual(fresh.total_cost(self.result.state), self.result.cost,
                               places=6)


class TestThroughTheApiBoundary(unittest.TestCase):
    """The same month, but every byte passing through the JSON contract."""

    @classmethod
    def setUpClass(cls):
        inst = university_instance(start="2026-11-19", num_days=30, num_employees=46,
                                   seed=3)
        cls.body = {"instance": inst.to_dict(),
                    "options": {"seed": 99, "max_seconds": 25.0}}
        cls.out = solve_payload(cls.body)
        cls.audit = Audit(cls.body["instance"], cls.out["roster"])

    def test_a_different_month_and_headcount_also_comes_back_legal(self):
        self.assertTrue(self.out["score"]["feasible"], self.out["score"]["by_rule"])
        self.assertEqual(self.out["coverage"]["under"], 0)

    def test_the_audit_agrees_with_the_response(self):
        self.assertEqual(self.audit.structural_faults(), [])
        self.assertEqual(self.audit.breaches(), [])

    def test_the_horizon_spans_a_month_boundary(self):
        dates = self.out["roster"]["dates"]
        self.assertEqual(dates[0], "2026-11-19")
        self.assertEqual(dates[-1], "2026-12-18")
        self.assertEqual(len({d[:7] for d in dates}), 2)

    def test_the_response_is_json_and_self_consistent(self):
        import json
        again = json.loads(json.dumps(self.out))
        self.assertEqual(again["score"]["by_rule"], self.out["score"]["by_rule"])
        self.assertEqual(len(again["workload"]), len(self.body["instance"]["employees"]))

    def test_only_soft_rules_were_traded_away(self):
        score = self.out["score"]
        self.assertEqual(score["hard_violations"], 0)
        self.assertEqual(score["hard_cost"], 0.0)
        self.assertGreater(score["soft_violations"], 0)   # a perfect month is unlikely
        self.assertAlmostEqual(score["cost"], score["soft_cost"], places=3)


if __name__ == "__main__":
    unittest.main()
