"""Rule taxonomy: one evaluator class per kind of policy, in a registry."""

from __future__ import annotations

from dataclasses import dataclass, field

from .horizon import Horizon
from .schema import HARD, SOFT, Instance, Rule
from .state import OFF, RosterState, RowStats


@dataclass
class Violation:
    """One concrete breach, phrased for the admin rather than the solver."""

    rule_id: str
    rule_type: str
    severity: str
    message: str
    amount: float = 1.0
    cost: float = 0.0
    employee: str = ""
    days: tuple[int, ...] = ()

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "rule_type": self.rule_type,
            "severity": self.severity,
            "message": self.message,
            "amount": self.amount,
            "cost": round(self.cost, 4),
            "employee": self.employee,
            "days": list(self.days),
        }


# ``kind`` picks the frontend widget and drives validation here.
INT = "int"
FLOAT = "float"
BOOL = "bool"
SHIFT = "shift"
SHIFTS = "shifts"
ROLE = "role"
DAY = "day"
DAYS = "days"
CHOICE = "choice"


def param(name: str, kind: str, label: str, default=None, **extra) -> dict:
    """One form field / one JSON param. Required exactly when it has no default."""
    spec = {"name": name, "kind": kind, "label": label, "required": default is None}
    if default is not None:
        spec["default"] = default
    spec.update(extra)
    return spec


def resolve_days(value, horizon: Horizon) -> tuple[int, ...]:
    """Accept day offsets, ISO dates, or a mix, and return day offsets."""
    if value is None:
        return ()
    if isinstance(value, (int, str)):
        value = [value]
    out = []
    for item in value:
        out.append(horizon.index_of(item) if isinstance(item, str) else int(item))
    return tuple(sorted(set(out)))


def over(value: float, limit: float) -> float:
    return value - limit if value > limit else 0.0


def under(value: float, limit: float) -> float:
    return limit - value if value < limit else 0.0


REGISTRY: dict[str, type["RuleEvaluator"]] = {}


def register(cls: type["RuleEvaluator"]) -> type["RuleEvaluator"]:
    if not cls.type:
        raise ValueError(f"{cls.__name__} has no type name")
    if cls.type in REGISTRY:
        raise ValueError(f"duplicate rule type {cls.type!r}")
    REGISTRY[cls.type] = cls
    return cls


class RuleEvaluator:
    """Base class. Subclasses declare ``type``/``params_spec`` and one method."""

    type: str = ""
    label: str = ""
    help: str = ""
    eval_kind: str = "row"  # row | coverage | global
    granularity: str = "cell"  # coverage rules only: cell (day,shift,role) or shift (day,shift)
    params_spec: list[dict] = []
    example: str = ""

    def __init__(self, rule: Rule, inst: Instance) -> None:
        self.rule = rule
        self.inst = inst
        self.params = self._read_params(rule.params)
        self.members: tuple[int, ...] = tuple(inst.scope_employees(rule))
        self.member_set = set(self.members)
        self.setup()

    def setup(self) -> None:
        """Precompute anything derived from params (called once)."""

    def _read_params(self, given: dict) -> dict:
        out = {}
        for spec in self.params_spec:
            name = spec["name"]
            if name in given:
                out[name] = given[name]
            elif "default" in spec:
                out[name] = spec["default"]
            elif spec.get("required", True):
                raise ValueError(
                    f"rule {self.rule.id} ({self.type}) is missing parameter {name!r}"
                )
            else:
                out[name] = None
        unknown = set(given) - {s["name"] for s in self.params_spec}
        if unknown:
            raise ValueError(f"rule {self.rule.id} ({self.type}) has unknown params {sorted(unknown)}")
        return out

    def row_amount(self, state: RosterState, e: int, stats: RowStats) -> float:
        return 0.0

    def row_violations(self, state: RosterState, e: int, stats: RowStats) -> list[Violation]:
        amount = self.row_amount(state, e, stats)
        if amount <= 0:
            return []
        return [self.violation(amount, employee=self.inst.employees[e].id)]

    def total_amount(self, state: RosterState) -> float:
        return 0.0

    def cell_amount(self, state: RosterState, d: int, s: int, r: int) -> float:
        """Coverage rules with ``granularity == 'cell'``: this cell's contribution."""
        return 0.0

    def shift_amount(self, state: RosterState, d: int, s: int) -> float:
        """Coverage rules with ``granularity == 'shift'``: this day/shift's share."""
        return 0.0

    def violations(self, state: RosterState) -> list[Violation]:
        """Every breach of this rule, whatever kind of rule it is."""
        if self.eval_kind == "row":
            out: list[Violation] = []
            for e in self.members:
                out.extend(self.row_violations(state, e, state.row_stats(e)))
            return out
        amount = self.total_amount(state)
        return [self.violation(amount)] if amount > 0 else []

    def shift_id(self, s: int) -> str:
        return self.inst.shifts[s].id

    def violation(self, amount: float, message: str = "", employee: str = "",
                  days: tuple[int, ...] = ()) -> Violation:
        return Violation(
            rule_id=self.rule.id,
            rule_type=self.type,
            severity=self.rule.severity,
            message=message or self.describe(),
            amount=amount,
            employee=employee,
            days=days,
        )

    def describe(self) -> str:
        """Human phrasing of the rule; the admin's own words win if given."""
        if self.rule.label:
            return self.rule.label
        bits = ", ".join(f"{k}={v}" for k, v in self.params.items() if v is not None)
        return f"{self.label or self.type} ({bits})" if bits else (self.label or self.type)


# Consecutive-day rules
@register
class MaxConsecutiveWorkingDays(RuleEvaluator):
    type = "max_consecutive_working_days"
    label = "Maximum consecutive working days"
    help = "Nobody may work more than this many days in a row without a day off."
    example = "No one works more than 6 days in a row."
    params_spec = [param("max", INT, "Maximum days in a row", minimum=1)]

    def setup(self) -> None:
        self.limit = int(self.params["max"])

    def row_amount(self, state, e, stats) -> float:
        return float(sum(over(length, self.limit) for _, length in stats.work_blocks))

    def row_violations(self, state, e, stats):
        out = []
        emp = self.inst.employees[e].id
        for start, length in stats.work_blocks:
            excess = over(length, self.limit)
            if excess:
                out.append(self.violation(
                    excess,
                    f"{emp} works {length} days in a row from "
                    f"{self.inst.horizon.date_of(start).isoformat()} (limit {self.limit})",
                    employee=emp,
                    days=tuple(range(start, start + length)),
                ))
        return out


@register
class MinConsecutiveWorkingDays(RuleEvaluator):
    type = "min_consecutive_working_days"
    label = "Minimum consecutive working days"
    help = ("Once someone starts a stretch of work it must last at least this "
            "long, which stops the roster scattering isolated single days. "
            "Stretches cut short by the start or end of the horizon are exempt.")
    example = "Nobody works just one day between two days off."
    params_spec = [param("min", INT, "Minimum days in a row", minimum=1)]

    def setup(self) -> None:
        self.limit = int(self.params["min"])

    def row_amount(self, state, e, stats) -> float:
        last = self.inst.num_days
        return float(sum(
            under(length, self.limit)
            for start, length in stats.work_blocks
            if start > 0 and start + length < last
        ))

    def row_violations(self, state, e, stats):
        out = []
        emp = self.inst.employees[e].id
        last = self.inst.num_days
        for start, length in stats.work_blocks:
            if start == 0 or start + length >= last:
                continue
            short = under(length, self.limit)
            if short:
                day = self.inst.horizon.date_of(start).isoformat()
                spell = "a single day" if length == 1 else f"only {length} days"
                out.append(self.violation(
                    short,
                    f"{emp} works {spell} from {day} between two breaks "
                    f"(prefer {self.limit} in a row)",
                    employee=emp,
                    days=tuple(range(start, start + length)),
                ))
        return out


@register
class MaxConsecutiveDaysOff(RuleEvaluator):
    type = "max_consecutive_days_off"
    label = "Maximum consecutive days off"
    help = "Caps how long a person can sit idle - useful when leave must be spread out."
    example = "No one is off for more than 4 days together."
    params_spec = [param("max", INT, "Maximum days off in a row", minimum=1)]

    def setup(self) -> None:
        self.limit = int(self.params["max"])

    def row_amount(self, state, e, stats) -> float:
        return float(sum(over(length, self.limit) for _, length in stats.off_blocks))

    def row_violations(self, state, e, stats):
        out = []
        emp = self.inst.employees[e].id
        for start, length in stats.off_blocks:
            excess = over(length, self.limit)
            if excess:
                out.append(self.violation(
                    excess,
                    f"{emp} is off {length} days running from "
                    f"{self.inst.horizon.date_of(start).isoformat()} (limit {self.limit})",
                    employee=emp,
                    days=tuple(range(start, start + length)),
                ))
        return out


@register
class MinConsecutiveDaysOff(RuleEvaluator):
    type = "min_consecutive_days_off"
    label = "Minimum consecutive days off"
    help = ("A break must be at least this long, so rest days come in usable "
            "blocks instead of single days sprinkled through the month. Breaks "
            "clipped by the start or end of the horizon are exempt.")
    example = "Days off always come at least two at a time."
    params_spec = [param("min", INT, "Minimum days off in a row", minimum=1)]

    def setup(self) -> None:
        self.limit = int(self.params["min"])

    def row_amount(self, state, e, stats) -> float:
        last = self.inst.num_days
        return float(sum(
            under(length, self.limit)
            for start, length in stats.off_blocks
            if start > 0 and start + length < last
        ))

    def row_violations(self, state, e, stats):
        out = []
        emp = self.inst.employees[e].id
        last = self.inst.num_days
        for start, length in stats.off_blocks:
            if start == 0 or start + length >= last:
                continue
            short = under(length, self.limit)
            if short:
                day = self.inst.horizon.date_of(start).isoformat()
                if length == 1:
                    text = (f"{emp} gets a single day off on {day} rather than "
                            f"{self.limit} together")
                else:
                    text = (f"{emp} gets only {length} days off from {day} "
                            f"(prefer {self.limit} together)")
                out.append(self.violation(
                    short, text,
                    employee=emp,
                    days=tuple(range(start, start + length)),
                ))
        return out


@register
class MaxConsecutiveSameShift(RuleEvaluator):
    type = "max_consecutive_same_shift"
    label = "Maximum consecutive days on the same shift"
    help = ("Limits how long someone stays on one shift before rotating. Leave "
            "the shift blank to apply the limit to every shift type.")
    example = "Nobody does more than 3 night shifts in a row."
    params_spec = [
        param("max", INT, "Maximum days in a row", minimum=1),
        param("shift", SHIFT, "Shift type (blank = all)", default="", required=False),
    ]

    def setup(self) -> None:
        self.limit = int(self.params["max"])
        chosen = self.params.get("shift") or ""
        self.only = self.inst.shift_index[chosen] if chosen else None

    def row_amount(self, state, e, stats) -> float:
        total = 0.0
        for s, _start, length in stats.same_blocks:
            if self.only is None or s == self.only:
                total += over(length, self.limit)
        return total

    def row_violations(self, state, e, stats):
        out = []
        emp = self.inst.employees[e].id
        for s, start, length in stats.same_blocks:
            if self.only is not None and s != self.only:
                continue
            excess = over(length, self.limit)
            if excess:
                out.append(self.violation(
                    excess,
                    f"{emp} works {length} {self.inst.shifts[s].id} shifts in a row from "
                    f"{self.inst.horizon.date_of(start).isoformat()} (limit {self.limit})",
                    employee=emp,
                    days=tuple(range(start, start + length)),
                ))
        return out


# Shift-to-shift succession
@register
class ForbiddenShiftSequence(RuleEvaluator):
    type = "forbidden_shift_sequence"
    label = "Forbidden shift succession"
    help = ("Bans one shift following another. Both fields accept several "
            "shifts, so 'night then anything but night' style bans need one rule.")
    example = "No night shift followed by a morning shift."
    params_spec = [
        param("from", SHIFTS, "Shift worked first"),
        param("to", SHIFTS, "Shift that may not follow"),
        param("day_delta", INT, "Days later", default=1, minimum=1),
    ]

    def setup(self) -> None:
        idx = self.inst.shift_index
        self.first = frozenset(idx[s] for s in _as_list(self.params["from"]))
        self.second = frozenset(idx[s] for s in _as_list(self.params["to"]))
        self.delta = int(self.params["day_delta"])

    def row_amount(self, state, e, stats) -> float:
        shifts = stats.shifts
        delta = self.delta
        count = 0
        for d in range(self.inst.num_days - delta):
            if shifts[d] in self.first and shifts[d + delta] in self.second:
                count += 1
        return float(count)

    def row_violations(self, state, e, stats):
        out = []
        emp = self.inst.employees[e].id
        shifts = stats.shifts
        for d in range(self.inst.num_days - self.delta):
            a, b = shifts[d], shifts[d + self.delta]
            if a in self.first and b in self.second:
                out.append(self.violation(
                    1.0,
                    f"{emp} works {self.shift_id(a)} on "
                    f"{self.inst.horizon.date_of(d).isoformat()} then "
                    f"{self.shift_id(b)} on "
                    f"{self.inst.horizon.date_of(d + self.delta).isoformat()}",
                    employee=emp,
                    days=(d, d + self.delta),
                ))
        return out


def _as_list(value) -> list:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple, set)) else [value]


@register
class MinRestHours(RuleEvaluator):
    type = "min_rest_hours"
    label = "Minimum rest between shifts"
    help = ("Stated once, in hours. The forbidden shift pairs are worked out "
            "from the shift clock times, so adding a new shift automatically "
            "gets the right restrictions instead of needing new rules.")
    example = "At least 12 hours off between two shifts."
    params_spec = [param("hours", FLOAT, "Minimum rest (hours)", minimum=0)]

    def setup(self) -> None:
        self.minutes = int(round(float(self.params["hours"]) * 60))
        self.forbidden = frozenset(self.inst.forbidden_rest_pairs(self.minutes, 1))

    def row_amount(self, state, e, stats) -> float:
        forbidden = self.forbidden
        return float(sum(1 for _d, a, b in stats.pairs if (a, b) in forbidden))

    def row_violations(self, state, e, stats):
        out = []
        emp = self.inst.employees[e].id
        for d, a, b in stats.pairs:
            if (a, b) in self.forbidden:
                gap = self.inst.shifts[a].rest_gap_to(self.inst.shifts[b], 1)
                out.append(self.violation(
                    1.0,
                    f"{emp} gets only {gap / 60:.1f}h rest between "
                    f"{self.shift_id(a)} on {self.inst.horizon.date_of(d).isoformat()} "
                    f"and {self.shift_id(b)} the next day "
                    f"(needs {self.minutes / 60:.1f}h)",
                    employee=emp,
                    days=(d, d + 1),
                ))
        return out


# Counting rules over the whole horizon
@register
class TotalShiftsRange(RuleEvaluator):
    type = "total_shifts_range"
    label = "Total shifts in the period"
    help = "How many days a person may work across the whole roster period."
    example = "Everyone works between 20 and 24 days this month."
    params_spec = [
        param("min", INT, "Fewest shifts", default=0, minimum=0),
        param("max", INT, "Most shifts", default=None, minimum=0, required=False),
    ]

    def setup(self) -> None:
        self.low = int(self.params.get("min") or 0)
        high = self.params.get("max")
        self.high = None if high is None else int(high)

    def row_amount(self, state, e, stats) -> float:
        amount = under(stats.total, self.low)
        if self.high is not None:
            amount += over(stats.total, self.high)
        return float(amount)

    def row_violations(self, state, e, stats):
        emp = self.inst.employees[e].id
        amount = self.row_amount(state, e, stats)
        if not amount:
            return []
        window = f"{self.low}" if self.high is None else f"{self.low}-{self.high}"
        return [self.violation(
            amount, f"{emp} works {stats.total} shifts (allowed {window})", employee=emp)]


@register
class TotalHoursRange(RuleEvaluator):
    type = "total_hours_range"
    label = "Total hours in the period"
    help = ("Same idea as the shift count but measured in hours, for when shifts "
            "have different lengths. Violation size is counted in hours.")
    example = "Nobody exceeds 192 hours in the month."
    params_spec = [
        param("min_hours", FLOAT, "Fewest hours", default=0, minimum=0),
        param("max_hours", FLOAT, "Most hours", default=None, minimum=0, required=False),
    ]

    def setup(self) -> None:
        self.low = float(self.params.get("min_hours") or 0)
        high = self.params.get("max_hours")
        self.high = None if high is None else float(high)

    def row_amount(self, state, e, stats) -> float:
        hours = stats.minutes / 60.0
        amount = under(hours, self.low)
        if self.high is not None:
            amount += over(hours, self.high)
        return amount


@register
class ShiftTypeCountRange(RuleEvaluator):
    type = "shift_type_count_range"
    label = "How often one shift type may be worked"
    help = ("Limits or guarantees the number of a particular shift per person "
            "over the period. Leave either bound blank to skip it.")
    example = "At most 8 night shifts per person per month."
    params_spec = [
        param("shift", SHIFT, "Shift type"),
        param("min", INT, "Fewest", default=0, minimum=0),
        param("max", INT, "Most", default=None, minimum=0, required=False),
    ]

    def setup(self) -> None:
        self.s = self.inst.shift_index[self.params["shift"]]
        self.low = int(self.params.get("min") or 0)
        high = self.params.get("max")
        self.high = None if high is None else int(high)

    def row_amount(self, state, e, stats) -> float:
        count = stats.by_shift[self.s]
        amount = under(count, self.low)
        if self.high is not None:
            amount += over(count, self.high)
        return float(amount)

    def row_violations(self, state, e, stats):
        amount = self.row_amount(state, e, stats)
        if not amount:
            return []
        emp = self.inst.employees[e].id
        count = stats.by_shift[self.s]
        bound = f"{self.low}+" if self.high is None else f"{self.low}-{self.high}"
        return [self.violation(
            amount,
            f"{emp} works {count} {self.params['shift']} shifts (allowed {bound})",
            employee=emp,
        )]


@register
class MaxNightShifts(RuleEvaluator):
    type = "max_night_shifts"
    label = "Maximum night shifts"
    help = ("Counts every shift flagged as a night shift, so it keeps working "
            "when night cover is split across more than one shift type.")
    example = "No more than 7 nights a month."
    params_spec = [param("max", INT, "Maximum nights", minimum=0)]

    def setup(self) -> None:
        self.limit = int(self.params["max"])

    def row_amount(self, state, e, stats) -> float:
        return float(over(stats.nights, self.limit))


# Weekly windows
class _WindowRule(RuleEvaluator):
    """Shared plumbing for per-week limits."""

    def setup(self) -> None:
        self.mode = (self.params.get("window") or "calendar").lower()
        self.size = int(self.params.get("window_days") or 7)
        if self.mode == "calendar":
            self.windows = self.inst.horizon.calendar_weeks()
        elif self.mode == "rolling":
            self.windows = self.inst.horizon.rolling_windows(self.size)
        else:
            raise ValueError(f"window must be 'calendar' or 'rolling', got {self.mode!r}")
        self.full_only = not bool(self.params.get("include_partial"))
        self.lengths = [len(w) for w in self.windows]
        self.expected = 7 if self.mode == "calendar" else self.size


@register
class MaxWorkingDaysPerWindow(_WindowRule):
    type = "max_working_days_per_window"
    label = "Maximum working days per week"
    help = "Caps working days inside each week (or each rolling run of days)."
    example = "No more than 5 working days in any week."
    params_spec = [
        param("max", INT, "Maximum working days", minimum=0),
        param("window", CHOICE, "Window", default="calendar",
              options=["calendar", "rolling"]),
        param("window_days", INT, "Window length (rolling only)", default=7, minimum=1),
        param("include_partial", BOOL, "Also apply to part-weeks at the edges",
              default=True),
    ]

    def setup(self) -> None:
        super().setup()
        self.limit = int(self.params["max"])

    def row_amount(self, state, e, stats) -> float:
        counts = (stats.work_per_week if self.mode == "calendar"
                  else stats.windows_worked(self.windows))
        total = 0.0
        for i, count in enumerate(counts):
            if self.full_only and self.lengths[i] < self.expected:
                continue
            total += over(count, self.limit)
        return total


@register
class MinDaysOffPerWindow(_WindowRule):
    type = "min_days_off_per_window"
    label = "Minimum days off per week"
    help = ("Guarantees rest days inside each week. Part-weeks at the start and "
            "end of the period are skipped by default, since a two-day stub "
            "cannot owe a full week's rest.")
    example = "At least one day off every week."
    params_spec = [
        param("min", INT, "Minimum days off", minimum=0),
        param("window", CHOICE, "Window", default="calendar",
              options=["calendar", "rolling"]),
        param("window_days", INT, "Window length (rolling only)", default=7, minimum=1),
        param("include_partial", BOOL, "Also apply to part-weeks at the edges",
              default=False),
    ]

    def setup(self) -> None:
        super().setup()
        self.limit = int(self.params["min"])

    def row_amount(self, state, e, stats) -> float:
        if self.mode == "calendar":
            offs = stats.off_per_week
        else:
            worked = stats.windows_worked(self.windows)
            offs = [self.lengths[i] - worked[i] for i in range(len(worked))]
        total = 0.0
        for i, count in enumerate(offs):
            if self.full_only and self.lengths[i] < self.expected:
                continue
            total += under(count, self.limit)
        return total

    def row_violations(self, state, e, stats):
        amount = self.row_amount(state, e, stats)
        if not amount:
            return []
        emp = self.inst.employees[e].id
        return [self.violation(
            amount,
            f"{emp} is short {amount:g} rest day(s) against a minimum of "
            f"{self.limit} per {self.mode} week",
            employee=emp,
        )]


# Weekends
@register
class MaxWeekendsWorked(RuleEvaluator):
    type = "max_weekends_worked"
    label = "Maximum weekends worked"
    help = ("A weekend counts as worked if any of its days is worked, so this "
            "counts weekends touched rather than weekend days.")
    example = "No one works more than 2 weekends a month."
    params_spec = [param("max", INT, "Maximum weekends", minimum=0)]

    def setup(self) -> None:
        self.limit = int(self.params["max"])

    def row_amount(self, state, e, stats) -> float:
        return float(over(stats.weekends_worked, self.limit))

    def row_violations(self, state, e, stats):
        amount = self.row_amount(state, e, stats)
        if not amount:
            return []
        emp = self.inst.employees[e].id
        return [self.violation(
            amount,
            f"{emp} works {stats.weekends_worked} weekends (limit {self.limit})",
            employee=emp,
        )]


@register
class CompleteWeekends(RuleEvaluator):
    type = "complete_weekends"
    label = "Weekends worked whole or not at all"
    help = ("Stops someone being called in for a single weekend day. Either "
            "they work the whole weekend or none of it.")
    example = "If you work Saturday you also work Sunday."
    params_spec = []

    def row_amount(self, state, e, stats) -> float:
        return float(stats.weekends_partial)

    def row_violations(self, state, e, stats):
        if not stats.weekends_partial:
            return []
        emp = self.inst.employees[e].id
        out = []
        for block in state.weekend_blocks:
            worked = [i for i in block if stats.work[i]]
            if worked and len(worked) < len(block):
                out.append(self.violation(
                    1.0,
                    f"{emp} works only part of the weekend starting "
                    f"{self.inst.horizon.date_of(block[0]).isoformat()}",
                    employee=emp,
                    days=tuple(block),
                ))
        return out


# Availability, fixed assignments and requests
@register
class Unavailable(RuleEvaluator):
    type = "unavailable"
    label = "Not available on these days"
    help = ("Leave, training, deputation - the person cannot be rostered. Give "
            "specific shifts to block only part of a day.")
    example = "E14 is on leave from the 3rd to the 9th."
    default_severity = HARD
    params_spec = [
        param("days", DAYS, "Days"),
        param("shifts", SHIFTS, "Shifts (blank = the whole day)", default=[],
              required=False),
    ]

    def setup(self) -> None:
        self.days = resolve_days(self.params["days"], self.inst.horizon)
        wanted = _as_list(self.params.get("shifts"))
        self.shifts = frozenset(self.inst.shift_index[s] for s in wanted) if wanted else None

    def row_amount(self, state, e, stats) -> float:
        shifts = stats.shifts
        if self.shifts is None:
            return float(sum(1 for d in self.days if shifts[d] != OFF))
        return float(sum(1 for d in self.days if shifts[d] in self.shifts))

    def row_violations(self, state, e, stats):
        out = []
        emp = self.inst.employees[e].id
        for d in self.days:
            s = stats.shifts[d]
            if s != OFF and (self.shifts is None or s in self.shifts):
                out.append(self.violation(
                    1.0,
                    f"{emp} is rostered {self.shift_id(s)} on "
                    f"{self.inst.horizon.date_of(d).isoformat()} but is unavailable",
                    employee=emp,
                    days=(d,),
                ))
        return out


@register
class DayOffRequest(Unavailable):
    type = "day_off_request"
    label = "Requested day off"
    help = ("A preference, not an entitlement - normally soft, so the solver "
            "grants it when it can and reports it when it cannot.")
    example = "E07 would like the 15th off."
    default_severity = SOFT


@register
class FixedAssignment(RuleEvaluator):
    type = "fixed_assignment"
    label = "Pre-assigned duty"
    help = ("Locks one person onto one shift on one day - a duty already "
            "committed, or a slot the officials fixed by hand. Leave the role "
            "blank to accept any role they are qualified for."
            )
    example = "E02 takes the night shift on the 21st."
    params_spec = [
        param("day", DAY, "Day"),
        param("shift", SHIFT, "Shift"),
        param("role", ROLE, "Role (blank = any)", default="", required=False),
    ]

    def setup(self) -> None:
        self.day = resolve_days(self.params["day"], self.inst.horizon)[0]
        self.s = self.inst.shift_index[self.params["shift"]]
        role = self.params.get("role") or ""
        self.r = self.inst.role_index[role] if role else None

    def row_amount(self, state, e, stats) -> float:
        if stats.shifts[self.day] != self.s:
            return 1.0
        if self.r is not None and stats.roles[self.day] != self.r:
            return 1.0
        return 0.0

    def row_violations(self, state, e, stats):
        if not self.row_amount(state, e, stats):
            return []
        emp = self.inst.employees[e].id
        return [self.violation(
            1.0,
            f"{emp} is not on the pre-assigned {self.params['shift']} duty on "
            f"{self.inst.horizon.date_of(self.day).isoformat()}",
            employee=emp,
            days=(self.day,),
        )]


@register
class ShiftRequest(RuleEvaluator):
    type = "shift_request"
    label = "Requested shift"
    help = "The person asked to work a particular shift on a particular day."
    example = "E19 asked for the morning shift on the 8th."
    default_severity = SOFT
    params_spec = [param("day", DAY, "Day"), param("shift", SHIFT, "Shift")]

    def setup(self) -> None:
        self.day = resolve_days(self.params["day"], self.inst.horizon)[0]
        self.s = self.inst.shift_index[self.params["shift"]]

    def row_amount(self, state, e, stats) -> float:
        return 0.0 if stats.shifts[self.day] == self.s else 1.0


@register
class ShiftOffRequest(ShiftRequest):
    type = "shift_off_request"
    label = "Shift the person asked not to work"
    help = "The mirror of a shift request - this specific shift on this day is unwanted."
    example = "E19 would rather not take the night shift on the 8th."
    default_severity = SOFT

    def row_amount(self, state, e, stats) -> float:
        return 1.0 if stats.shifts[self.day] == self.s else 0.0


@register
class ShiftPreference(RuleEvaluator):
    type = "shift_preference"
    label = "Standing preference for or against a shift"
    help = ("Applies across the whole period rather than to one day. 'Avoid' "
            "charges once per assignment to that shift; 'prefer' charges once "
            "per assignment to any other shift.")
    example = "The senior LSG staff should avoid night duty where possible."
    default_severity = SOFT
    params_spec = [
        param("shift", SHIFT, "Shift"),
        param("direction", CHOICE, "Direction", default="avoid",
              options=["avoid", "prefer"]),
    ]

    def setup(self) -> None:
        self.s = self.inst.shift_index[self.params["shift"]]
        self.avoid = (self.params.get("direction") or "avoid") == "avoid"

    def row_amount(self, state, e, stats) -> float:
        count = stats.by_shift[self.s]
        return float(count if self.avoid else stats.total - count)

    def row_violations(self, state, e, stats):
        amount = self.row_amount(state, e, stats)
        if amount <= 0:
            return []
        emp = self.inst.employees[e].id
        shift = self.inst.shifts[self.s].id
        days = tuple(d for d in range(self.inst.num_days)
                     if (stats.shifts[d] == self.s) == self.avoid
                     and stats.shifts[d] != OFF)
        if self.avoid:
            text = f"{emp} is on {shift} {int(amount)} time(s) despite preferring not to be"
        else:
            text = f"{emp} works {int(amount)} shift(s) other than the preferred {shift}"
        return [self.violation(amount, text, employee=emp, days=days)]


# Coverage
@register
class Coverage(RuleEvaluator):
    type = "coverage"
    label = "Meet the staffing demand"
    help = ("Compares the headcount rostered against the demand table for every "
            "day, shift and role. Being short and being overstaffed are charged "
            "separately, since a gap in cover usually matters far more than a "
            "spare pair of hands.")
    example = "Every shift is staffed exactly as the demand table says."
    params_spec = [
        param("direction", CHOICE, "Which side to police", default="both",
              options=["both", "under", "over"]),
        param("under_weight", FLOAT, "Cost per missing person", default=1.0, minimum=0),
        param("over_weight", FLOAT, "Cost per extra person", default=1.0, minimum=0),
        param("count_undemanded", BOOL,
              "Charge people rostered to a role nobody asked for", default=True),
    ]
    eval_kind = "coverage"

    def setup(self) -> None:
        self.uw = float(self.params["under_weight"])
        self.ow = float(self.params["over_weight"])
        self.count_undemanded = bool(self.params["count_undemanded"])
        direction = self.params.get("direction") or "both"
        self.do_under = direction in ("both", "under")
        self.do_over = direction in ("both", "over")
        if not self.do_over:
            self.count_undemanded = False

    def total_amount(self, state) -> float:
        inst = self.inst
        cov = state.cov
        total = 0.0
        for key in inst.demand_cells:
            d, s, r = key
            have = cov[d][s][r]
            need = inst.required[key]
            if have < need:
                if self.do_under:
                    total += (need - have) * self.uw
            elif have > need and self.do_over:
                total += (have - need) * self.ow
        if self.count_undemanded:
            required = inst.required
            for d in range(inst.num_days):
                for s in range(inst.num_shifts):
                    row = cov[d][s]
                    for r in range(inst.num_roles):
                        if row[r] and (d, s, r) not in required:
                            total += row[r] * self.ow
        return total

    def cell_amount(self, state, d, s, r) -> float:
        need = self.inst.required.get((d, s, r), 0)
        have = state.cov[d][s][r]
        if have < need:
            return (need - have) * self.uw if self.do_under else 0.0
        if have > need:
            if need == 0 and not self.count_undemanded:
                return 0.0
            return (have - need) * self.ow if self.do_over else 0.0
        return 0.0

    def violations(self, state) -> list[Violation]:
        inst = self.inst
        out = []
        for key, have, need in state.coverage_gaps():
            d, s, r = key
            short = have < need
            if (short and not self.do_under) or (not short and not self.do_over):
                continue
            word = "short" if short else "over"
            gap = abs(have - need)
            out.append(self.violation(
                gap * (self.uw if short else self.ow),
                f"{inst.horizon.date_of(d).isoformat()} {inst.shifts[s].id}/"
                f"{inst.roles[r].id}: {have} rostered, {need} needed ({word} {gap})",
                days=(d,),
            ))
        if self.count_undemanded:
            for d in range(inst.num_days):
                for s in range(inst.num_shifts):
                    for r in range(inst.num_roles):
                        n = state.cov[d][s][r]
                        if n and (d, s, r) not in inst.required:
                            out.append(self.violation(
                                n * self.ow,
                                f"{inst.horizon.date_of(d).isoformat()} "
                                f"{inst.shifts[s].id}/{inst.roles[r].id}: {n} rostered "
                                f"with no demand for that role",
                                days=(d,),
                            ))
        return out


@register
class HeadcountPerShift(RuleEvaluator):
    type = "headcount_per_shift"
    label = "People on a shift, regardless of role"
    help = ("A floor or ceiling on total bodies present, ignoring which role "
            "they cover - for rules like 'never fewer than two people on site "
            "at night'. Restrict it to particular days if needed.")
    example = "At least 2 people on the night shift, every day."
    eval_kind = "coverage"
    granularity = "shift"
    params_spec = [
        param("shift", SHIFT, "Shift"),
        param("min", INT, "Fewest people", default=0, minimum=0),
        param("max", INT, "Most people", default=None, minimum=0, required=False),
        param("days", DAYS, "Days (blank = every day)", default=[], required=False),
    ]

    def setup(self) -> None:
        self.s = self.inst.shift_index[self.params["shift"]]
        self.low = int(self.params.get("min") or 0)
        high = self.params.get("max")
        self.high = None if high is None else int(high)
        days = resolve_days(self.params.get("days"), self.inst.horizon)
        self.days = days or tuple(range(self.inst.num_days))
        self.day_set = frozenset(self.days)

    def _gap(self, have: int) -> float:
        amount = under(have, self.low)
        if self.high is not None:
            amount += over(have, self.high)
        return float(amount)

    def shift_amount(self, state, d, s) -> float:
        if s != self.s or d not in self.day_set:
            return 0.0
        return self._gap(state.headcount[d][s])

    def total_amount(self, state) -> float:
        return sum(self._gap(state.headcount[d][self.s]) for d in self.days)

    def violations(self, state) -> list[Violation]:
        out = []
        for d in self.days:
            have = state.headcount[d][self.s]
            gap = self._gap(have)
            if gap:
                bound = f"{self.low}+" if self.high is None else f"{self.low}-{self.high}"
                out.append(self.violation(
                    gap,
                    f"{self.inst.horizon.date_of(d).isoformat()} "
                    f"{self.params['shift']}: {have} on duty (allowed {bound})",
                    days=(d,),
                ))
        return out


# Fairness across people
@register
class BalanceWorkload(RuleEvaluator):
    type = "balance_workload"
    label = "Share the load evenly"
    help = ("Measures the spread between the busiest and the least busy person "
            "in scope and charges whatever exceeds the tolerance. This is the "
            "equity measure from Kletzander & Musliu (2020): it is the gap that "
            "is penalised, not each person's deviation, so the cost cannot be "
            "gamed by making everyone slightly unfair.")
    example = "Night duty is split evenly - at most one night's difference between staff."
    eval_kind = "global"
    default_severity = SOFT
    params_spec = [
        param("measure", CHOICE, "What to balance", default="shifts",
              options=["shifts", "hours", "nights", "weekends", "shift_type"]),
        param("shift", SHIFT, "Shift type (for 'shift_type' only)", default="",
              required=False),
        param("tolerance", FLOAT, "Allowed spread", default=0.0, minimum=0),
    ]

    def setup(self) -> None:
        self.measure = self.params.get("measure") or "shifts"
        self.tolerance = float(self.params.get("tolerance") or 0.0)
        chosen = self.params.get("shift") or ""
        if self.measure == "shift_type":
            if not chosen:
                raise ValueError(
                    f"rule {self.rule.id}: measure 'shift_type' needs a shift")
            self.s = self.inst.shift_index[chosen]
        else:
            self.s = None

    def value_for(self, state, e: int) -> float:
        stats = state.row_stats(e)
        if self.measure == "shifts":
            return float(stats.total)
        if self.measure == "hours":
            return stats.minutes / 60.0
        if self.measure == "nights":
            return float(stats.nights)
        if self.measure == "weekends":
            return float(stats.weekends_worked)
        return float(stats.by_shift[self.s])

    def spread(self, state) -> tuple[float, float]:
        values = [self.value_for(state, e) for e in self.members]
        if not values:
            return 0.0, 0.0
        return min(values), max(values)

    def total_amount(self, state) -> float:
        low, high = self.spread(state)
        return float(over(high - low, self.tolerance))

    def violations(self, state) -> list[Violation]:
        low, high = self.spread(state)
        amount = over(high - low, self.tolerance)
        if not amount:
            return []
        what = self.params.get("shift") if self.measure == "shift_type" else self.measure
        return [self.violation(
            amount,
            f"{what}: busiest person has {high:g}, lightest {low:g} "
            f"(spread {high - low:g}, tolerance {self.tolerance:g})",
        )]


# Aggregation
DEFAULT_HARD_WEIGHT = 1000.0


def build(rule: Rule, inst: Instance) -> RuleEvaluator:
    cls = REGISTRY.get(rule.type)
    if cls is None:
        known = ", ".join(sorted(REGISTRY))
        raise ValueError(f"unknown rule type {rule.type!r}. Known types: {known}")
    return cls(rule, inst)


@dataclass
class Evaluation:
    """The verdict on one roster."""

    cost: float = 0.0
    hard_cost: float = 0.0
    soft_cost: float = 0.0
    hard_count: int = 0
    soft_count: int = 0
    violations: list[Violation] = field(default_factory=list)
    by_rule: dict[str, float] = field(default_factory=dict)

    @property
    def feasible(self) -> bool:
        return self.hard_count == 0

    def to_dict(self) -> dict:
        return {
            "feasible": self.feasible,
            "cost": round(self.cost, 4),
            "hard_cost": round(self.hard_cost, 4),
            "soft_cost": round(self.soft_cost, 4),
            "hard_violations": self.hard_count,
            "soft_violations": self.soft_count,
            "by_rule": {k: round(v, 4) for k, v in self.by_rule.items()},
            "violations": [v.to_dict() for v in self.violations],
        }


class RuleSet:
    """All of an instance's rules, compiled and grouped for fast re-evaluation."""

    def __init__(self, inst: Instance, hard_weight: float = DEFAULT_HARD_WEIGHT) -> None:
        self.inst = inst
        self.hard_weight = hard_weight
        self.evaluators = [build(r, inst) for r in inst.rules]

        self.row_for: list[list[tuple[RuleEvaluator, float]]] = [
            [] for _ in range(inst.num_employees)
        ]
        self.coverage: list[tuple[RuleEvaluator, float]] = []
        self.globals: list[tuple[RuleEvaluator, float]] = []
        for ev in self.evaluators:
            w = self.weight_of(ev)
            if ev.eval_kind == "row":
                for e in ev.members:
                    self.row_for[e].append((ev, w))
            elif ev.eval_kind == "coverage":
                self.coverage.append((ev, w))
            else:
                self.globals.append((ev, w))

        self.hard_row_for = [
            [(ev, w) for ev, w in row if ev.rule.is_hard] for row in self.row_for
        ]

    def weight_of(self, ev: RuleEvaluator) -> float:
        return (self.hard_weight if ev.rule.is_hard else 1.0) * ev.rule.weight

    def row_cost(self, state: RosterState, e: int) -> float:
        rules = self.row_for[e]
        if not rules:
            return 0.0
        stats = state.row_stats(e)
        return sum(w * ev.row_amount(state, e, stats) for ev, w in rules)

    def row_hard_amount(self, state: RosterState, e: int) -> float:
        rules = self.hard_row_for[e]
        if not rules:
            return 0.0
        stats = state.row_stats(e)
        return sum(ev.row_amount(state, e, stats) for ev, _w in rules)

    def coverage_cost(self, state: RosterState) -> float:
        return sum(w * ev.total_amount(state) for ev, w in self.coverage)

    def local_coverage_cost(self, state: RosterState, cells, day_shifts) -> float:
        """Coverage cost of just the cells a move touches."""
        total = 0.0
        for ev, w in self.coverage:
            if ev.granularity == "cell":
                for d, s, r in cells:
                    total += w * ev.cell_amount(state, d, s, r)
            else:
                for d, s in day_shifts:
                    total += w * ev.shift_amount(state, d, s)
        return total

    @property
    def has_globals(self) -> bool:
        return bool(self.globals)

    def global_cost(self, state: RosterState) -> float:
        return sum(w * ev.total_amount(state) for ev, w in self.globals)

    def total_cost(self, state: RosterState) -> float:
        total = self.coverage_cost(state) + self.global_cost(state)
        for e in range(self.inst.num_employees):
            total += self.row_cost(state, e)
        return total

    def evaluate(self, state: RosterState) -> Evaluation:
        """Cost plus every individual violation, for the report and the tests."""
        result = Evaluation()
        for ev in self.evaluators:
            w = self.weight_of(ev)
            found = ev.violations(state)
            if not found:
                continue
            rule_cost = 0.0
            for v in found:
                v.cost = w * v.amount
                rule_cost += v.cost
            result.violations.extend(found)
            result.by_rule[ev.rule.id] = result.by_rule.get(ev.rule.id, 0.0) + rule_cost
            if ev.rule.is_hard:
                result.hard_cost += rule_cost
                result.hard_count += len(found)
            else:
                result.soft_cost += rule_cost
                result.soft_count += len(found)
        result.cost = result.hard_cost + result.soft_cost
        result.violations.sort(key=lambda v: (v.severity != HARD, -v.cost, v.rule_id))
        return result

    def hard_violation_amount(self, state: RosterState) -> float:
        """Total hard breach magnitude - zero means the roster is legal."""
        total = 0.0
        for e in range(self.inst.num_employees):
            total += self.row_hard_amount(state, e)
        for ev, _w in self.coverage + self.globals:
            if ev.rule.is_hard:
                total += ev.total_amount(state)
        return total

    def describe_rules(self) -> list[str]:
        return [f"[{ev.rule.severity}] {ev.describe()}" for ev in self.evaluators]
