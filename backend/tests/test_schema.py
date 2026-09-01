"""The JSON contract: shift arithmetic, demand expansion, validation, round trips."""

from __future__ import annotations

import json
import unittest

from roster.horizon import Horizon
from roster.schema import (
    Demand, Employee, Instance, Role, Rule, Scope, ShiftType, _as_minutes, expand_demand,
)

from .helpers import DSG, LSG, MONDAY, SHIFTS, instance


class TestShiftType(unittest.TestCase):
    def test_clock_and_end_time(self):
        m = ShiftType(id="M", start_min=6 * 60, duration_min=8 * 60)
        self.assertEqual(m.end_min, 14 * 60)
        self.assertEqual(m.clock, "06:00-14:00")
        self.assertEqual(m.hours, 8.0)
        self.assertFalse(m.crosses_midnight)

    def test_night_shift_crosses_midnight(self):
        n = ShiftType(id="N", start_min=22 * 60, duration_min=8 * 60)
        self.assertTrue(n.crosses_midnight)
        self.assertEqual(n.end_min, 30 * 60)          # 06:00 the next day
        self.assertEqual(n.clock, "22:00-06:00")

    def test_rest_gap_between_consecutive_days(self):
        """A night finishing at 06:00 leaves no rest before a 06:00 morning."""
        m, e, n = SHIFTS
        self.assertEqual(n.rest_gap_to(m), 0)
        self.assertEqual(n.rest_gap_to(e), 8 * 60)
        self.assertEqual(e.rest_gap_to(m), 8 * 60)
        self.assertEqual(m.rest_gap_to(m), 16 * 60)
        self.assertEqual(m.rest_gap_to(n), 32 * 60)

    def test_minutes_accept_clock_strings(self):
        self.assertEqual(_as_minutes(480), 480)
        self.assertEqual(_as_minutes("08:00"), 480)
        self.assertEqual(_as_minutes("8:30"), 510)
        with self.assertRaises(ValueError):
            _as_minutes("half eight")

    def test_rejects_impossible_clock_values(self):
        with self.assertRaises(ValueError):
            ShiftType(id="X", start_min=1500)
        with self.assertRaises(ValueError):
            ShiftType(id="X", duration_min=0)


class TestScopeAndRule(unittest.TestCase):
    def test_scope_resolves_by_role_and_contract(self):
        staff = [
            Employee(id="A", roles=(DSG,), contract="permanent"),
            Employee(id="B", roles=(DSG, LSG), contract="contract"),
            Employee(id="C", roles=(LSG,), contract="permanent"),
        ]
        self.assertEqual(Scope("all").resolve(staff), ["A", "B", "C"])
        self.assertEqual(Scope("roles", ("LSG",)).resolve(staff), ["B", "C"])
        self.assertEqual(Scope("contracts", ("contract",)).resolve(staff), ["B"])
        self.assertEqual(Scope("employees", ("C", "A")).resolve(staff), ["A", "C"])

    def test_scope_needs_ids_when_it_is_not_all(self):
        with self.assertRaises(ValueError):
            Scope("employees", ())
        with self.assertRaises(ValueError):
            Scope("nonsense", ("A",))

    def test_rule_severity_and_weight_are_checked(self):
        with self.assertRaises(ValueError):
            Rule(id="r", type="coverage", severity="advisory")
        with self.assertRaises(ValueError):
            Rule(id="r", type="coverage", weight=-1.0)
        self.assertTrue(Rule(id="r", type="coverage").is_hard)
        self.assertFalse(Rule(id="r", type="coverage", severity="soft").is_hard)


class TestDemandExpansion(unittest.TestCase):
    def setUp(self):
        self.h = Horizon(start=MONDAY, num_days=14)   # Mon, two full weeks

    def test_all_days_by_default(self):
        lines = expand_demand([{"shift": "M", "role": DSG, "required": 2}], self.h)
        self.assertEqual(len(lines), 14)
        self.assertTrue(all(l.required == 2 for l in lines))

    def test_weekday_and_weekend_selectors_partition_the_month(self):
        lines = expand_demand([
            {"shift": "M", "role": DSG, "required": 6, "days": "weekday"},
            {"shift": "M", "role": DSG, "required": 4, "days": "weekend"},
        ], self.h)
        self.assertEqual(len(lines), 14)
        self.assertEqual(sum(l.required for l in lines), 10 * 6 + 4 * 4)

    def test_named_weekdays(self):
        lines = expand_demand(
            [{"shift": "N", "role": LSG, "required": 1, "days": ["Mon", "Sat"]}], self.h)
        self.assertEqual(sorted(l.day for l in lines), [0, 5, 7, 12])

    def test_explicit_iso_dates(self):
        lines = expand_demand(
            [{"shift": "E", "role": DSG, "required": 3,
              "days": ["2026-09-08", "2026-09-09"]}], self.h)
        self.assertEqual(sorted(l.day for l in lines), [1, 2])

    def test_holiday_selector(self):
        h = Horizon(start=MONDAY, num_days=7, holidays=frozenset({"2026-09-09"}))
        lines = expand_demand(
            [{"shift": "M", "role": DSG, "required": 1, "days": "holiday"}], h)
        self.assertEqual([l.day for l in lines], [2])

    def test_later_pattern_overrides_earlier_for_the_same_cell(self):
        """How an admin says 'two a day, but three on the Wednesday'."""
        lines = expand_demand([
            {"shift": "M", "role": DSG, "required": 2},
            {"shift": "M", "role": DSG, "required": 3, "days": ["2026-09-09"]},
        ], self.h)
        by_day = {l.day: l.required for l in lines}
        self.assertEqual(len(lines), 14)
        self.assertEqual(by_day[2], 3)
        self.assertEqual(by_day[1], 2)

    def test_unknown_selector_is_rejected(self):
        with self.assertRaises(ValueError):
            expand_demand([{"shift": "M", "role": DSG, "required": 1,
                            "days": "every other Tuesday"}], self.h)


class TestInstance(unittest.TestCase):
    def test_indexes_and_eligibility(self):
        inst = instance()
        self.assertEqual(inst.num_employees, 3)
        self.assertEqual(inst.emp_index["B"], 1)
        self.assertEqual(list(inst.eligible[inst.role_index[DSG]]), [0, 1])
        self.assertEqual(list(inst.eligible[inst.role_index[LSG]]), [1, 2])
        self.assertEqual(inst.roles_of[1], {inst.role_index[DSG], inst.role_index[LSG]})

    def test_required_table_and_totals(self):
        inst = instance(days=3, demand=[
            Demand(day=0, shift="M", role=DSG, required=2),
            Demand(day=1, shift="N", role=LSG, required=1),
        ])
        self.assertEqual(inst.total_required, 3)
        self.assertEqual(len(inst.demand_cells), 2)
        self.assertEqual(inst.required[(0, inst.shift_index["M"], inst.role_index[DSG])], 2)

    def test_forbidden_rest_pairs_derive_from_the_clock(self):
        """12 hours' rest bans E->M, N->M and N->E without naming any of them."""
        inst = instance()
        pairs = set(inst.forbidden_rest_pairs(12 * 60))
        idx = inst.shift_index
        self.assertEqual(pairs, {
            (idx["E"], idx["M"]),
            (idx["N"], idx["M"]),
            (idx["N"], idx["E"]),
        })

    def test_validation_catches_the_mistakes_an_admin_makes(self):
        h = Horizon(start=MONDAY, num_days=7)
        base = dict(horizon=h, roles=[Role(DSG)], shifts=list(SHIFTS))
        with self.assertRaisesRegex(ValueError, "unknown role"):
            Instance(**base, employees=[Employee(id="A", roles=("LSG",))])
        with self.assertRaisesRegex(ValueError, "duplicate employee"):
            Instance(**base, employees=[Employee(id="A", roles=(DSG,)),
                                        Employee(id="A", roles=(DSG,))])
        with self.assertRaisesRegex(ValueError, "outside the horizon"):
            Instance(**base, employees=[Employee(id="A", roles=(DSG,))],
                     demand=[Demand(day=99, shift="M", role=DSG, required=1)])
        with self.assertRaisesRegex(ValueError, "unknown shift"):
            Instance(**base, employees=[Employee(id="A", roles=(DSG,))],
                     demand=[Demand(day=0, shift="Z", role=DSG, required=1)])
        with self.assertRaisesRegex(ValueError, "duplicate rule id"):
            Instance(**base, employees=[Employee(id="A", roles=(DSG,))],
                     rules=[Rule(id="r", type="coverage"), Rule(id="r", type="coverage")])
        with self.assertRaisesRegex(ValueError, "unknown employee"):
            Instance(**base, employees=[Employee(id="A", roles=(DSG,))],
                     rules=[Rule(id="r", type="coverage",
                                 scope=Scope("employees", ("Z",)))])

    def test_employee_needs_at_least_one_role(self):
        with self.assertRaises(ValueError):
            Employee(id="A", roles=())

    def test_json_round_trip_is_exact(self):
        from roster.generate import university_instance

        a = university_instance(num_days=10, num_employees=12)
        b = Instance.from_dict(json.loads(json.dumps(a.to_dict())))
        self.assertEqual(a.num_employees, b.num_employees)
        self.assertEqual([r.id for r in a.rules], [r.id for r in b.rules])
        self.assertEqual([r.params for r in a.rules], [r.params for r in b.rules])
        self.assertEqual(a.required, b.required)
        self.assertEqual(a.demand_cells, b.demand_cells)
        self.assertEqual(a.eligible, b.eligible)
        self.assertEqual(a.total_required, b.total_required)

    def test_from_dict_accepts_demand_patterns(self):
        data = {
            "horizon": {"start": MONDAY, "num_days": 7},
            "roles": [DSG],
            "shifts": [{"id": "M", "start_min": 360, "duration_min": 480}],
            "employees": [{"id": "A", "roles": [DSG]}],
            "demand_patterns": [{"shift": "M", "role": DSG, "required": 1,
                                 "days": "weekend"}],
        }
        inst = Instance.from_dict(data)
        self.assertEqual(inst.total_required, 2)


if __name__ == "__main__":
    unittest.main()
