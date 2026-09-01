"""Shared fixtures. Deliberately tiny so every expected number can be counted by hand."""

from __future__ import annotations

from roster.horizon import Horizon
from roster.schema import Employee, Instance, Role, Rule, ShiftType
from roster.state import OFF, RosterState

DSG, LSG, MTS = "DSG", "LSG", "MTS"

# 2026-09-07 is a Monday, so day 0 is a Monday and days 5-6 are the first weekend.
MONDAY = "2026-09-07"

SHIFTS = [
    ShiftType(id="M", name="Morning", start_min=6 * 60, duration_min=8 * 60),
    ShiftType(id="E", name="Evening", start_min=14 * 60, duration_min=8 * 60),
    ShiftType(id="N", name="Night", start_min=22 * 60, duration_min=8 * 60,
              counts_as_night=True),
]


def horizon(days: int = 14, start: str = MONDAY, holidays=()) -> Horizon:
    return Horizon(start=start, num_days=days, holidays=frozenset(holidays))


def instance(days: int = 14, employees=None, demand=(), rules=(), start: str = MONDAY,
             holidays=()) -> Instance:
    """A three-person, three-shift instance with no demand and no rules by default."""
    if employees is None:
        employees = [
            Employee(id="A", roles=(DSG,)),
            Employee(id="B", roles=(DSG, LSG)),
            Employee(id="C", roles=(LSG, MTS)),
        ]
    return Instance(
        horizon=horizon(days, start, holidays),
        roles=[Role(DSG), Role(LSG), Role(MTS)],
        shifts=list(SHIFTS),
        employees=list(employees),
        demand=list(demand),
        rules=list(rules),
        name="fixture",
    )


def rule(rid: str, rtype: str, severity: str = "hard", weight: float = 1.0,
         scope=None, label: str = "", **params) -> Rule:
    return Rule(id=rid, type=rtype, severity=severity, weight=weight,
                scope=scope or {}, params=params, label=label)


def lay_out(inst: Instance, pattern: dict[str, str]) -> RosterState:
    """Build a roster from one string per employee, e.g. ``{"A": "MME..NN"}``."""
    state = RosterState(inst)
    for emp_id, row in pattern.items():
        e = inst.emp_index[emp_id]
        default_role = min(inst.role_index[r] for r in inst.employees[e].roles)
        if len(row) != inst.num_days:
            raise AssertionError(
                f"pattern for {emp_id} is {len(row)} long, horizon is {inst.num_days}")
        for d, ch in enumerate(row):
            if ch == ".":
                continue
            state.assign(e, d, inst.shift_index[ch], default_role)
    return state


def amount(inst: Instance, rule_obj: Rule, state: RosterState, emp: str | None = None) -> float:
    """The raw violation amount for one rule, before any weighting."""
    from roster.rules import build

    ev = build(rule_obj, inst)
    if ev.eval_kind == "row":
        if emp is not None:
            e = inst.emp_index[emp]
            return ev.row_amount(state, e, state.row_stats(e))
        return sum(ev.row_amount(state, e, state.row_stats(e)) for e in ev.members)
    if ev.eval_kind == "coverage":
        return ev.total_amount(state)
    return ev.total_amount(state)


def messages(inst: Instance, rule_obj: Rule, state: RosterState) -> list[str]:
    from roster.rules import build

    return [v.message for v in build(rule_obj, inst).violations(state)]


__all__ = ["DSG", "LSG", "MTS", "MONDAY", "OFF", "SHIFTS", "amount", "horizon",
           "instance", "lay_out", "messages", "rule"]
