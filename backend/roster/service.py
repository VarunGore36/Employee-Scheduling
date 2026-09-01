"""JSON in, JSON out - the layer the HTTP API will be a thin shell over."""

from __future__ import annotations

import time

from . import report
from .rules import REGISTRY, RuleSet
from .ruleinfo import form_schema
from .schema import Instance
from .search import Solver, SolverOptions
from .state import RosterState


class ServiceError(Exception):
    """Malformed request. Maps to HTTP 400, never to a 500."""

    def __init__(self, message: str, field: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.field = field

    def to_dict(self) -> dict:
        return {"error": self.message, "field": self.field}


def _instance_from(payload: dict) -> Instance:
    if not isinstance(payload, dict):
        raise ServiceError("request body must be a JSON object")
    data = payload.get("instance", payload)
    if not isinstance(data, dict):
        raise ServiceError("'instance' must be an object", "instance")
    try:
        return Instance.from_dict(data)
    except (ValueError, KeyError, TypeError) as exc:
        raise ServiceError(f"instance rejected: {exc}", "instance") from exc


_OPTION_TYPES = {
    "seed": int, "max_seconds": float, "max_iterations": int,
    "start_temperature": float, "end_temperature": float, "cooling": float,
    "iterations_per_level": int, "reheat_after_levels": int,
    "polish_iterations": int, "construct_candidates": int,
    "hard_weight": float, "verbose": bool,
}

MAX_SECONDS_CAP = 600.0


def _options_from(payload: dict) -> SolverOptions:
    """Only known keys, only sane values - the time budget is a public endpoint."""
    raw = payload.get("options") or {}
    if not isinstance(raw, dict):
        raise ServiceError("'options' must be an object", "options")
    unknown = set(raw) - set(_OPTION_TYPES)
    if unknown:
        raise ServiceError(f"unknown option(s) {sorted(unknown)}", "options")
    kwargs = {}
    for key, value in raw.items():
        caster = _OPTION_TYPES[key]
        try:
            kwargs[key] = caster(value)
        except (TypeError, ValueError) as exc:
            raise ServiceError(f"option {key!r} must be {caster.__name__}", f"options.{key}") from exc
    seconds = kwargs.get("max_seconds", SolverOptions.max_seconds)
    if seconds <= 0 or seconds > MAX_SECONDS_CAP:
        raise ServiceError(
            f"max_seconds must be between 0 and {MAX_SECONDS_CAP:g}", "options.max_seconds")
    if kwargs.get("hard_weight", 1.0) <= 0:
        raise ServiceError("hard_weight must be positive", "options.hard_weight")
    return SolverOptions(**kwargs)


def _roster_from(inst: Instance, payload: dict) -> RosterState:
    data = payload.get("roster")
    if not isinstance(data, dict) or "rows" not in data:
        raise ServiceError("'roster' must be an object with a 'rows' list", "roster")
    rows = data["rows"]
    if not isinstance(rows, list):
        raise ServiceError("'roster.rows' must be a list", "roster.rows")
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or "employee" not in row or "days" not in row:
            raise ServiceError(
                f"roster.rows[{i}] needs 'employee' and 'days'", f"roster.rows.{i}")
        if row["employee"] not in inst.emp_index:
            raise ServiceError(
                f"roster names unknown employee {row['employee']!r}", f"roster.rows.{i}")
        if len(row["days"]) != inst.num_days:
            raise ServiceError(
                f"roster.rows[{i}] has {len(row['days'])} days, horizon has {inst.num_days}",
                f"roster.rows.{i}")
    try:
        return RosterState.from_dict(inst, data)
    except (KeyError, ValueError, TypeError) as exc:
        raise ServiceError(f"roster rejected: {exc}", "roster") from exc


def solve_payload(payload: dict) -> dict:
    """``POST /solve``. Build the instance, search, return roster plus verdict."""
    inst = _instance_from(payload)
    options = _options_from(payload)
    started = time.perf_counter()
    solver = Solver(inst, options)
    result = solver.solve()
    out = report.report_dict(result.state, result.evaluation, solver.rules)
    out["search"] = {
        "cost": round(result.cost, 4),
        "construction_cost": round(result.construction_cost, 4),
        "iterations": result.iterations,
        "accepted": result.accepted,
        "seconds": round(result.seconds, 3),
        "wall_seconds": round(time.perf_counter() - started, 3),
        "options": options.to_dict(),
        "engine": "construct+anneal",
    }
    if payload.get("include_history"):
        out["search"]["history"] = result.history
    return out


def evaluate_payload(payload: dict) -> dict:
    """``POST /evaluate``. Score a roster somebody else wrote, without changing it."""
    inst = _instance_from(payload)
    rules = RuleSet(inst, _options_from(payload).hard_weight)
    state = _roster_from(inst, payload)
    evaluation = rules.evaluate(state)
    return report.report_dict(state, evaluation, rules)


def repair_payload(payload: dict) -> dict:
    """``POST /repair``. Start from a submitted roster and improve it in place."""
    inst = _instance_from(payload)
    options = _options_from(payload)
    solver = Solver(inst, options)
    start = _roster_from(inst, payload)
    before = solver.rules.evaluate(start)
    started = time.perf_counter()
    state = solver.construct(start)
    construction_cost = solver.rules.total_cost(state)
    state, cost, iterations, accepted, _history = solver.anneal(state, started)
    evaluation = solver.rules.evaluate(state)
    out = report.report_dict(state, evaluation, solver.rules)
    out["search"] = {
        "cost": round(cost, 4),
        "construction_cost": round(construction_cost, 4),
        "iterations": iterations,
        "accepted": accepted,
        "seconds": round(time.perf_counter() - started, 3),
        "options": options.to_dict(),
        "engine": "repair",
    }
    out["before"] = {
        "cost": round(before.cost, 4),
        "hard_violations": before.hard_count,
        "soft_violations": before.soft_count,
    }
    return out


def schema_payload(payload: dict | None = None) -> dict:
    """``GET /schema``. Everything the questionnaire needs to draw itself."""
    inst = None
    if payload and payload.get("instance"):
        inst = _instance_from(payload)
    out = form_schema(inst)
    out["rule_type_count"] = len(REGISTRY)
    return out


def validate_payload(payload: dict) -> dict:
    """``POST /validate``. Cheap sanity check before the admin waits on a solve."""
    inst = _instance_from(payload)
    try:
        rules = RuleSet(inst)
    except ValueError as exc:
        raise ServiceError(f"rule rejected: {exc}", "instance.rules") from exc

    problems = []
    warnings = []
    per_role_demand: dict[str, int] = {r.id: 0 for r in inst.roles}
    for (d, s, r), need in inst.required.items():
        per_role_demand[inst.roles[r].id] += need

    capacity = {}
    for role in inst.roles:
        qualified = len(inst.eligible[inst.role_index[role.id]])
        capacity[role.id] = {
            "qualified_staff": qualified,
            "person_days_available": qualified * inst.num_days,
            "person_days_demanded": per_role_demand[role.id],
        }
        if per_role_demand[role.id] and not qualified:
            problems.append(f"role {role.id} is rostered but nobody holds it")
        elif qualified and per_role_demand[role.id] > qualified * inst.num_days:
            problems.append(
                f"role {role.id} needs {per_role_demand[role.id]} person-days but "
                f"{qualified} qualified staff can supply at most {qualified * inst.num_days}")

    # per day and shift, is there anyone at all who could be there?
    for (d, s, r), need in sorted(inst.required.items()):
        if need > len(inst.eligible[r]):
            problems.append(
                f"{inst.horizon.date_of(d)} {inst.shifts[s].id}/{inst.roles[r].id} "
                f"needs {need} but only {len(inst.eligible[r])} staff hold that role")

    demanded = inst.total_required
    available = inst.num_employees * inst.num_days
    load = demanded / available if available else 0.0
    if load > 0.85:
        warnings.append(
            f"demand is {load:.0%} of every person's every day; expect hard rules "
            f"about rest and days off to fight coverage")

    hard_rules = [r for r in inst.rules if r.is_hard]
    return {
        "ok": not problems,
        "problems": problems,
        "warnings": warnings,
        "instance": {
            "name": inst.name,
            "start": inst.horizon.start.isoformat(),
            "num_days": inst.num_days,
            "employees": inst.num_employees,
            "demand_person_shifts": demanded,
            "capacity_person_days": available,
            "utilisation": round(load, 4),
            "hard_rules": len(hard_rules),
            "soft_rules": len(inst.rules) - len(hard_rules),
        },
        "capacity_by_role": capacity,
        "rules": rules.describe_rules(),
    }


ENDPOINTS = {
    "solve": solve_payload,
    "evaluate": evaluate_payload,
    "repair": repair_payload,
    "schema": schema_payload,
    "validate": validate_payload,
}


def handle(endpoint: str, payload: dict) -> dict:
    """Dispatch by name, with errors already shaped for a JSON response."""
    fn = ENDPOINTS.get(endpoint)
    if fn is None:
        raise ServiceError(f"unknown endpoint {endpoint!r}; expected one of "
                           f"{sorted(ENDPOINTS)}")
    return fn(payload)
