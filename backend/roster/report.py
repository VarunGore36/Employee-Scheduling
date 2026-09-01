"""Turning a solved roster into something a human will actually read."""

from __future__ import annotations

import csv
import io
from collections import defaultdict

from .horizon import WEEKDAY_NAMES
from .rules import Evaluation, RuleSet, Violation
from .schema import HARD, Instance
from .state import OFF, RosterState

OFF_MARK = "."


def shift_letter(inst: Instance, s: int, r: int, show_role: bool = False) -> str:
    """One cell of the grid. Role is only worth showing for cross-covering staff."""
    if s == OFF:
        return OFF_MARK
    letter = inst.shifts[s].id
    if show_role:
        return f"{letter}/{inst.roles[r].id}"
    return letter


def roster_grid(state: RosterState, show_role: bool = False) -> str:
    """The month as a table: one row per employee, one column per day."""
    inst = state.inst
    horizon = inst.horizon
    days = list(range(inst.num_days))
    width = 2
    if show_role:
        width = max((len(f"{s.id}/{r.id}") for s in inst.shifts for r in inst.roles),
                    default=2)

    name_w = max(len(e.id) for e in inst.employees)
    name_w = max(name_w, len("Employee"))

    head_day = " ".join(f"{horizon.date_of(d).day:>{width}}" for d in days)
    head_dow = " ".join(f"{WEEKDAY_NAMES[horizon.day(d).weekday][0]:>{width}}" for d in days)
    mark = " ".join(f"{('~' if horizon.day(d).is_weekend else ' '):>{width}}" for d in days)

    lines = [
        f"{'':{name_w}}  {head_day}   duty nights",
        f"{'Employee':{name_w}}  {head_dow}",
        f"{'':{name_w}}  {mark}",
    ]
    for e, emp in enumerate(inst.employees):
        stats = state.row_stats(e)
        cells = " ".join(
            f"{shift_letter(inst, state.shift_of[e][d], state.role_of[e][d], show_role):>{width}}"
            for d in days
        )
        roles = ",".join(sorted(emp.roles))
        lines.append(f"{emp.id:{name_w}}  {cells}   {stats.total:>4} {stats.nights:>6}  {roles}")
    return "\n".join(lines)


def coverage_table(state: RosterState) -> str:
    """Required against rostered, per day and shift, with shortfalls flagged."""
    inst = state.inst
    lines = ["day        date        shift  role   need  have"]
    for (d, s, r) in inst.demand_cells:
        need = inst.required[(d, s, r)]
        have = state.cov[d][s][r]
        flag = "" if have == need else ("  SHORT" if have < need else "  extra")
        lines.append(
            f"{d:>3} {WEEKDAY_NAMES[inst.horizon.day(d).weekday]}  "
            f"{inst.horizon.date_of(d)}  {inst.shifts[s].id:>5}  "
            f"{inst.roles[r].id:>4}  {need:>4}  {have:>4}{flag}"
        )
    return "\n".join(lines)


def workload_rows(state: RosterState) -> list[dict]:
    """Per-employee totals - the fairness evidence, one row each."""
    inst = state.inst
    rows = []
    for e, emp in enumerate(inst.employees):
        stats = state.row_stats(e)
        rows.append({
            "employee": emp.id,
            "name": emp.name or emp.id,
            "roles": sorted(emp.roles),
            "duties": stats.total,
            "hours": round(stats.minutes / 60.0, 1),
            "nights": stats.nights,
            "weekends": stats.weekends_worked,
            "by_shift": {inst.shifts[s].id: stats.by_shift[s] for s in range(inst.num_shifts)},
            "longest_run": max((length for _start, length in stats.work_blocks), default=0),
        })
    return rows


def workload_table(state: RosterState) -> str:
    inst = state.inst
    shift_ids = [s.id for s in inst.shifts]
    head = "employee   duties  hours  nights  wkends  " + "  ".join(f"{i:>3}" for i in shift_ids)
    lines = [head, "-" * len(head)]
    for row in workload_rows(state):
        per_shift = "  ".join(f"{row['by_shift'][i]:>3}" for i in shift_ids)
        lines.append(
            f"{row['employee']:<9} {row['duties']:>6} {row['hours']:>6.0f} "
            f"{row['nights']:>7} {row['weekends']:>7}  {per_shift}"
        )
    spread = _spread(state)
    lines.append("-" * len(head))
    lines.append(
        f"spread (max-min): duties {spread['duties']}, nights {spread['nights']}, "
        f"weekends {spread['weekends']}"
    )
    return "\n".join(lines)


def _spread(state: RosterState) -> dict:
    """``max - min`` across staff, the equity measure both source papers use."""
    rows = workload_rows(state)
    out = {}
    for key in ("duties", "nights", "weekends", "hours"):
        values = [r[key] for r in rows] or [0]
        out[key] = round(max(values) - min(values), 1)
    return out


def _group(violations: list[Violation], key) -> dict:
    out: dict = defaultdict(list)
    for v in violations:
        out[key(v)].append(v)
    return dict(out)


def violation_report(evaluation: Evaluation, rules: RuleSet | None = None,
                     limit_per_rule: int = 6) -> str:
    """Breaches grouped by rule, hard first, with the admin's own label quoted."""
    if not evaluation.violations:
        return "No rule was broken."

    labels = {}
    if rules is not None:
        labels = {ev.rule.id: ev.describe() for ev in rules.evaluators}

    lines = []
    verdict = "LEGAL" if evaluation.feasible else "NOT LEGAL"
    lines.append(
        f"{verdict}: {evaluation.hard_count} hard and {evaluation.soft_count} soft "
        f"breaches, total penalty {evaluation.cost:,.1f}"
    )
    for severity, title in ((HARD, "Hard rules broken (the roster is invalid)"),
                            ("soft", "Soft rules bent (the trade-offs made)")):
        group = _group([v for v in evaluation.violations if v.severity == severity],
                       lambda v: v.rule_id)
        if not group:
            continue
        lines.append("")
        lines.append(title)
        ordered = sorted(group.items(), key=lambda kv: -sum(v.cost for v in kv[1]))
        for rule_id, items in ordered:
            cost = sum(v.cost for v in items)
            label = labels.get(rule_id, items[0].rule_type)
            lines.append(f"  [{rule_id}] {label}")
            lines.append(f"      {len(items)} breach(es), penalty {cost:,.1f}")
            for v in items[:limit_per_rule]:
                who = f"{v.employee}: " if v.employee else ""
                lines.append(f"      - {who}{v.message}")
            if len(items) > limit_per_rule:
                lines.append(f"      - ... and {len(items) - limit_per_rule} more")
    return "\n".join(lines)


def violations_by_employee(evaluation: Evaluation) -> dict[str, list[dict]]:
    """The same breaches, re-sorted for the person-by-person conversation."""
    out: dict[str, list[dict]] = defaultdict(list)
    for v in evaluation.violations:
        if v.employee:
            out[v.employee].append(v.to_dict())
    return {k: out[k] for k in sorted(out)}


def roster_csv(state: RosterState) -> str:
    """Dates across the top, staff down the side - the shape a rota gets printed in."""
    inst = state.inst
    buf = io.StringIO()
    out = csv.writer(buf, lineterminator="\n")
    dates = [inst.horizon.date_of(d).isoformat() for d in range(inst.num_days)]
    out.writerow(["employee", "name", "roles"] + dates + ["duties", "nights"])
    for e, emp in enumerate(inst.employees):
        stats = state.row_stats(e)
        cells = []
        for d in range(inst.num_days):
            s = state.shift_of[e][d]
            cells.append("" if s == OFF
                         else f"{inst.shifts[s].id}/{inst.roles[state.role_of[e][d]].id}")
        out.writerow([emp.id, emp.name or emp.id, "|".join(sorted(emp.roles))]
                     + cells + [stats.total, stats.nights])
    return buf.getvalue()


def assignments_csv(state: RosterState) -> str:
    """One row per duty - the long format, for pivot tables and payroll imports."""
    inst = state.inst
    buf = io.StringIO()
    out = csv.writer(buf, lineterminator="\n")
    out.writerow(["date", "weekday", "shift", "start", "end", "role", "employee", "name"])
    for d in range(inst.num_days):
        day = inst.horizon.day(d)
        for e, emp in enumerate(inst.employees):
            s = state.shift_of[e][d]
            if s == OFF:
                continue
            shift = inst.shifts[s]
            out.writerow([
                day.iso, WEEKDAY_NAMES[day.weekday], shift.id,
                shift.clock.split("-")[0], shift.clock.split("-")[1],
                inst.roles[state.role_of[e][d]].id, emp.id, emp.name or emp.id,
            ])
    return buf.getvalue()


def violations_csv(evaluation: Evaluation) -> str:
    buf = io.StringIO()
    out = csv.writer(buf, lineterminator="\n")
    out.writerow(["rule_id", "rule_type", "severity", "employee", "days", "amount",
                  "cost", "message"])
    for v in evaluation.violations:
        out.writerow([v.rule_id, v.rule_type, v.severity, v.employee,
                      " ".join(str(d) for d in v.days), v.amount, round(v.cost, 4),
                      v.message])
    return buf.getvalue()


def summary_lines(state: RosterState, evaluation: Evaluation) -> list[str]:
    inst = state.inst
    spread = _spread(state)
    return [
        f"Instance      {inst.name}",
        f"Horizon       {inst.horizon.start} for {inst.num_days} days "
        f"({inst.horizon.date_of(inst.num_days - 1)} inclusive)",
        f"Staff         {inst.num_employees} across {inst.num_roles} roles, "
        f"{inst.num_shifts} shifts a day",
        f"Demand        {inst.total_required} person-shifts; "
        f"rostered {state.assignments()}",
        f"Coverage      {state.under_coverage()} short, {state.over_coverage()} surplus",
        f"Verdict       {'legal' if evaluation.feasible else 'NOT legal'} - "
        f"{evaluation.hard_count} hard, {evaluation.soft_count} soft breaches",
        f"Penalty       {evaluation.cost:,.1f} "
        f"(hard {evaluation.hard_cost:,.1f}, soft {evaluation.soft_cost:,.1f})",
        f"Fairness      duty spread {spread['duties']}, night spread {spread['nights']}, "
        f"weekend spread {spread['weekends']}",
    ]


def text_report(state: RosterState, evaluation: Evaluation,
                rules: RuleSet | None = None, show_role: bool = False,
                sections: tuple[str, ...] = ("summary", "grid", "workload", "violations"),
                ) -> str:
    """The whole thing, in the order a reader wants it: verdict, grid, then why."""
    blocks = []
    if "summary" in sections:
        blocks.append("\n".join(summary_lines(state, evaluation)))
    if "grid" in sections:
        legend = ", ".join(f"{s.id}={s.name or s.id} {s.clock}" for s in state.inst.shifts)
        blocks.append(f"ROSTER  ({legend}, {OFF_MARK}=off, ~=weekend)\n"
                      + roster_grid(state, show_role))
    if "workload" in sections:
        blocks.append("WORKLOAD\n" + workload_table(state))
    if "coverage" in sections:
        blocks.append("COVERAGE\n" + coverage_table(state))
    if "violations" in sections:
        blocks.append("RULES\n" + violation_report(evaluation, rules))
    return "\n\n".join(blocks)


def report_dict(state: RosterState, evaluation: Evaluation,
                rules: RuleSet | None = None) -> dict:
    """The JSON the frontend renders - same numbers as :func:`text_report`."""
    inst = state.inst
    return {
        "instance": {
            "name": inst.name,
            "start": inst.horizon.start.isoformat(),
            "num_days": inst.num_days,
            "employees": inst.num_employees,
            "roles": [r.id for r in inst.roles],
            "shifts": [{"id": s.id, "name": s.name, "clock": s.clock,
                        "night": s.counts_as_night} for s in inst.shifts],
            "required": inst.total_required,
        },
        "roster": state.to_dict(),
        "score": evaluation.to_dict(),
        "coverage": {
            "under": state.under_coverage(),
            "over": state.over_coverage(),
            "gaps": [
                {"date": inst.horizon.date_of(d).isoformat(),
                 "shift": inst.shifts[s].id, "role": inst.roles[r].id,
                 "have": have, "required": need}
                for (d, s, r), have, need in state.coverage_gaps()
            ],
        },
        "workload": workload_rows(state),
        "spread": _spread(state),
        "violations_by_employee": violations_by_employee(evaluation),
        "rules": rules.describe_rules() if rules is not None else [],
    }
