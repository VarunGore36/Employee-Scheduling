"""A synthetic university instance, close enough to the real thing to test on."""

from __future__ import annotations

import random

from .horizon import Horizon
from .schema import Employee, Instance, Role, Rule, ShiftType, expand_demand

DSG, LSG, MTS = "DSG", "LSG", "MTS"

SHIFTS = [
    ShiftType(id="M", name="Morning", start_min=6 * 60, duration_min=8 * 60),
    ShiftType(id="E", name="Evening", start_min=14 * 60, duration_min=8 * 60),
    ShiftType(id="N", name="Night", start_min=22 * 60, duration_min=8 * 60,
              counts_as_night=True),
]

# (shift, role): (weekday headcount, weekend headcount)
STAFFING = {
    ("M", DSG): (6, 4),
    ("M", LSG): (3, 2),
    ("M", MTS): (2, 1),
    ("E", DSG): (5, 3),
    ("E", LSG): (2, 1),
    ("E", MTS): (1, 1),
    ("N", DSG): (2, 2),
    ("N", LSG): (1, 1),
}


def _demand_patterns() -> list[dict]:
    patterns = []
    for (shift, role), (weekday, weekend) in STAFFING.items():
        patterns.append({"shift": shift, "role": role, "required": weekday, "days": "weekday"})
        patterns.append({"shift": shift, "role": role, "required": weekend, "days": "weekend"})
    return patterns


def _staff(rng: random.Random, count: int) -> list[Employee]:
    """Role mix: mostly single-grade, a minority cross-qualified for cover."""
    plan: list[tuple[str, ...]] = []
    plan += [(DSG,)] * round(count * 0.50)
    plan += [(LSG,)] * round(count * 0.18)
    plan += [(MTS,)] * round(count * 0.14)
    plan += [(DSG, LSG)] * round(count * 0.11)
    plan += [(LSG, MTS)] * round(count * 0.07)
    while len(plan) < count:
        plan.append((DSG,))
    plan = plan[:count]
    rng.shuffle(plan)
    return [
        Employee(
            id=f"E{i:02d}",
            name=f"Staff {i:02d}",
            roles=roles,
            contract="permanent" if i % 5 else "contract",
        )
        for i, roles in enumerate(plan, start=1)
    ]


def _policy_rules() -> list[Rule]:
    """The standing policy - the part that does not change month to month."""
    def rule(rid, rtype, severity="hard", weight=1.0, scope=None, label="", **params):
        return Rule(id=rid, type=rtype, severity=severity, weight=weight,
                    scope=scope or {}, params=params, label=label)

    return [
        rule("cover_short", "coverage", label="Every duty must be staffed",
             direction="under"),
        rule("cover_extra", "coverage", severity="soft", weight=2.0,
             label="Avoid rostering more people than needed", direction="over"),
        rule("max_run", "max_consecutive_working_days", max=6,
             label="No more than 6 consecutive working days"),
        rule("rest", "min_rest_hours", hours=12,
             label="At least 12 hours between two duties"),
        rule("night_run", "max_consecutive_same_shift", max=3, shift="N",
             label="No more than 3 nights in a row"),
        rule("weekly_off", "min_days_off_per_window", min=1, window="calendar",
             label="At least one day off every week"),
        rule("weekly_max", "max_working_days_per_window", max=6, window="calendar",
             label="At most 6 working days in a week"),
        rule("weekly_hours", "hours_per_window", max_hours=48, window="calendar",
             label="At most 48 hours of work in a week"),
        rule("month_load", "total_shifts_range", min=8, max=22,
             label="Between 8 and 22 duties in the month"),
        rule("nights_cap", "max_night_shifts", max=8,
             label="At most 8 night duties a month"),
        rule("night_floor", "headcount_per_shift", shift="N", min=3,
             label="Never fewer than 3 people on site at night"),
        rule("weekends", "max_weekends_worked", severity="soft", weight=5.0, max=3,
             label="Try to keep staff to 3 weekends or fewer"),
        rule("whole_weekend", "complete_weekends", severity="soft", weight=2.0,
             label="Prefer whole weekends worked rather than single days"),
        rule("rest_block", "min_consecutive_days_off", severity="soft", weight=3.0, min=2,
             label="Prefer days off to come in pairs"),
        rule("work_block", "min_consecutive_working_days", severity="soft", weight=2.0, min=2,
             label="Avoid isolated single working days"),
        rule("fair_total", "balance_workload", severity="soft", weight=10.0,
             measure="shifts", tolerance=2,
             label="Spread total duties evenly across staff"),
        rule("fair_nights", "balance_workload", severity="soft", weight=8.0,
             measure="nights", tolerance=1,
             label="Share night duty evenly"),
        rule("fair_weekends", "balance_workload", severity="soft", weight=6.0,
             measure="weekends", tolerance=1,
             label="Share weekend duty evenly"),
    ]


def _personal_rules(rng: random.Random, employees: list[Employee],
                    horizon: Horizon) -> list[Rule]:
    """Leave, requests and pre-assigned duties - the part that changes monthly."""
    rules: list[Rule] = []
    ids = [e.id for e in employees]
    num_days = horizon.num_days

    # a few people on leave for a block of days
    for n, emp in enumerate(rng.sample(ids, k=max(1, len(ids) // 9)), start=1):
        length = rng.randint(3, 7)
        start = rng.randrange(0, num_days - length)
        days = [horizon.date_of(d).isoformat() for d in range(start, start + length)]
        rules.append(Rule(
            id=f"leave{n}", type="unavailable", severity="hard",
            scope={"kind": "employees", "ids": [emp]}, params={"days": days},
            label=f"{emp} is on leave {days[0]} to {days[-1]}",
        ))

    # requested days off - honoured when possible, reported when not
    for n, emp in enumerate(rng.sample(ids, k=max(1, len(ids) // 5)), start=1):
        day = horizon.date_of(rng.randrange(num_days)).isoformat()
        rules.append(Rule(
            id=f"req{n}", type="day_off_request", severity="soft", weight=4.0,
            scope={"kind": "employees", "ids": [emp]}, params={"days": [day]},
            label=f"{emp} asked for {day} off",
        ))

    # a couple of people who would rather not do nights
    for n, emp in enumerate(rng.sample(ids, k=2), start=1):
        rules.append(Rule(
            id=f"nopref{n}", type="shift_preference", severity="soft", weight=3.0,
            scope={"kind": "employees", "ids": [emp]},
            params={"shift": "N", "direction": "avoid"},
            label=f"{emp} would rather avoid night duty",
        ))

    # one duty fixed by hand
    emp = next(e for e in employees if DSG in e.roles)
    day = horizon.date_of(min(4, num_days - 1)).isoformat()
    rules.append(Rule(
        id="fixed1", type="fixed_assignment", severity="hard",
        scope={"kind": "employees", "ids": [emp.id]},
        params={"day": day, "shift": "M", "role": DSG},
        label=f"{emp.id} is already committed to the morning shift on {day}",
    ))
    return rules


def university_instance(start: str = "2026-09-12", num_days: int = 31,
                        num_employees: int = 44, seed: int = 7,
                        holidays: list[str] | None = None) -> Instance:
    """The realistic test case: an arbitrary start date and a month of duty."""
    rng = random.Random(seed)
    horizon = Horizon(start=start, num_days=num_days, holidays=frozenset(holidays or ()))
    employees = _staff(rng, num_employees)
    return Instance(
        horizon=horizon,
        roles=[Role(DSG, "Daily Support Grade"), Role(LSG, "Lower Support Grade"),
               Role(MTS, "Multi-Tasking Staff")],
        shifts=list(SHIFTS),
        employees=employees,
        demand=expand_demand(_demand_patterns(), horizon),
        rules=_policy_rules() + _personal_rules(rng, employees, horizon),
        name=f"university-{start}-{num_days}d",
    )


def small_instance(seed: int = 1) -> Instance:
    """A two-week, twelve-person cut-down of the same shape, for fast tests."""
    rng = random.Random(seed)
    horizon = Horizon(start="2026-09-01", num_days=14)
    employees = _staff(rng, 12)
    patterns = [
        {"shift": "M", "role": DSG, "required": 2},
        {"shift": "E", "role": DSG, "required": 1},
        {"shift": "N", "role": LSG, "required": 1},
    ]
    return Instance(
        horizon=horizon,
        roles=[Role(DSG), Role(LSG), Role(MTS)],
        shifts=list(SHIFTS),
        employees=employees,
        demand=expand_demand(patterns, horizon),
        rules=[
            Rule(id="cover", type="coverage", params={"direction": "under"},
                 label="Every duty must be staffed"),
            Rule(id="cover_extra", type="coverage", severity="soft", weight=2.0,
                 params={"direction": "over"},
                 label="Avoid rostering more people than needed"),
            Rule(id="run", type="max_consecutive_working_days", params={"max": 5},
                 label="No more than 5 consecutive working days"),
            Rule(id="rest", type="min_rest_hours", params={"hours": 12},
                 label="At least 12 hours between two duties"),
            Rule(id="fair", type="balance_workload", severity="soft", weight=5.0,
                 params={"measure": "shifts", "tolerance": 1},
                 label="Spread duties evenly across staff"),
        ],
        name="small",
    )
