"""Data model for a rostering instance."""

from __future__ import annotations

from dataclasses import dataclass, field

from .horizon import Horizon

HARD = "hard"
SOFT = "soft"
SEVERITIES = (HARD, SOFT)

MINUTES_PER_DAY = 1440


@dataclass(frozen=True)
class Role:
    """A qualification an employee holds and a demand line asks for (DSG, LSG, ...)."""

    id: str
    name: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name or self.id}

    @classmethod
    def from_dict(cls, d: dict | str) -> "Role":
        if isinstance(d, str):
            return cls(id=d, name=d)
        return cls(id=d["id"], name=d.get("name", d["id"]))


@dataclass(frozen=True)
class ShiftType:
    """A shift described by wall-clock start and length."""

    id: str
    name: str = ""
    start_min: int = 0
    duration_min: int = 480
    counts_as_night: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.start_min < MINUTES_PER_DAY:
            raise ValueError(f"shift {self.id}: start_min must be in 0..1439")
        if not 1 <= self.duration_min <= MINUTES_PER_DAY:
            raise ValueError(f"shift {self.id}: duration_min must be in 1..1440")

    @property
    def end_min(self) -> int:
        return self.start_min + self.duration_min

    @property
    def crosses_midnight(self) -> bool:
        return self.end_min > MINUTES_PER_DAY

    @property
    def hours(self) -> float:
        return self.duration_min / 60.0

    @property
    def clock(self) -> str:
        def hhmm(m: int) -> str:
            return f"{(m // 60) % 24:02d}:{m % 60:02d}"

        return f"{hhmm(self.start_min)}-{hhmm(self.end_min)}"

    def rest_gap_to(self, other: "ShiftType", day_delta: int = 1) -> int:
        """Rest minutes between the end of this shift and the start of ``other``."""
        return day_delta * MINUTES_PER_DAY + other.start_min - self.end_min

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name or self.id,
            "start_min": self.start_min,
            "duration_min": self.duration_min,
            "counts_as_night": self.counts_as_night,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ShiftType":
        return cls(
            id=d["id"],
            name=d.get("name", d["id"]),
            start_min=_as_minutes(d.get("start_min", d.get("start", 0))),
            duration_min=_as_minutes(d.get("duration_min", d.get("duration", 480))),
            counts_as_night=bool(d.get("counts_as_night", False)),
        )


def _as_minutes(value) -> int:
    """Accept 480, "08:00", or "8:00" and return minutes."""
    if isinstance(value, str):
        parts = value.split(":")
        if len(parts) != 2:
            raise ValueError(f"cannot read {value!r} as a time or minute count")
        return int(parts[0]) * 60 + int(parts[1])
    return int(value)


@dataclass
class Employee:
    """One rosterable person."""

    id: str
    name: str = ""
    roles: tuple[str, ...] = ()
    contract: str = ""
    attributes: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.roles = tuple(dict.fromkeys(self.roles))  # dedupe, keep order
        if not self.roles:
            raise ValueError(f"employee {self.id} holds no roles")

    def can_fill(self, role_id: str) -> bool:
        return role_id in self.roles

    def to_dict(self) -> dict:
        out = {
            "id": self.id,
            "name": self.name or self.id,
            "roles": list(self.roles),
            "contract": self.contract,
        }
        if self.attributes:
            out["attributes"] = dict(self.attributes)
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "Employee":
        roles = d.get("roles")
        if roles is None:
            roles = [d["role"]] if "role" in d else []
        return cls(
            id=d["id"],
            name=d.get("name", d["id"]),
            roles=tuple(roles),
            contract=d.get("contract", ""),
            attributes=dict(d.get("attributes", {})),
        )


SCOPE_ALL = "all"
SCOPE_EMPLOYEES = "employees"
SCOPE_ROLES = "roles"
SCOPE_CONTRACTS = "contracts"
SCOPE_KINDS = (SCOPE_ALL, SCOPE_EMPLOYEES, SCOPE_ROLES, SCOPE_CONTRACTS)


@dataclass
class Scope:
    """Who a rule applies to."""

    kind: str = SCOPE_ALL
    ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in SCOPE_KINDS:
            raise ValueError(f"scope kind must be one of {SCOPE_KINDS}, got {self.kind!r}")
        self.ids = tuple(self.ids)
        if self.kind != SCOPE_ALL and not self.ids:
            raise ValueError(f"scope kind {self.kind!r} needs at least one id")

    def resolve(self, employees: list[Employee]) -> list[str]:
        wanted = set(self.ids)
        if self.kind == SCOPE_ALL:
            return [e.id for e in employees]
        if self.kind == SCOPE_EMPLOYEES:
            return [e.id for e in employees if e.id in wanted]
        if self.kind == SCOPE_ROLES:
            return [e.id for e in employees if wanted & set(e.roles)]
        return [e.id for e in employees if e.contract in wanted]

    def to_dict(self) -> dict:
        return {"kind": self.kind, "ids": list(self.ids)}

    @classmethod
    def from_dict(cls, d: dict | None) -> "Scope":
        if not d:
            return cls()
        return cls(kind=d.get("kind", SCOPE_ALL), ids=tuple(d.get("ids", ())))


@dataclass
class Rule:
    """One policy the officials imposed."""

    id: str
    type: str
    severity: str = HARD
    weight: float = 1.0
    scope: Scope = field(default_factory=Scope)
    params: dict = field(default_factory=dict)
    label: str = ""

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}, got {self.severity!r}")
        if self.weight < 0:
            raise ValueError(f"rule {self.id}: weight must be >= 0")
        if isinstance(self.scope, dict):
            self.scope = Scope.from_dict(self.scope)

    @property
    def is_hard(self) -> bool:
        return self.severity == HARD

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "severity": self.severity,
            "weight": self.weight,
            "scope": self.scope.to_dict(),
            "params": dict(self.params),
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Rule":
        return cls(
            id=str(d.get("id", "")) or f"{d['type']}#auto",
            type=d["type"],
            severity=d.get("severity", HARD),
            weight=float(d.get("weight", 1.0)),
            scope=Scope.from_dict(d.get("scope")),
            params=dict(d.get("params", {})),
            label=d.get("label", ""),
        )


@dataclass(frozen=True)
class Demand:
    """How many people of one role are needed on one day/shift."""

    day: int
    shift: str
    role: str
    required: int
    max_allowed: int | None = None

    def __post_init__(self) -> None:
        if self.required < 0:
            raise ValueError("demand.required must be >= 0")
        if self.max_allowed is not None and self.max_allowed < self.required:
            raise ValueError(
                f"demand {self.day}/{self.shift}/{self.role}: max_allowed < required"
            )

    def to_dict(self) -> dict:
        out = {
            "day": self.day,
            "shift": self.shift,
            "role": self.role,
            "required": self.required,
        }
        if self.max_allowed is not None:
            out["max_allowed"] = self.max_allowed
        return out

    @classmethod
    def from_dict(cls, d: dict, horizon: Horizon | None = None) -> "Demand":
        day = d.get("day", d.get("date"))
        if isinstance(day, str):
            if horizon is None:
                raise ValueError("demand given as a date needs a horizon to resolve")
            day = horizon.index_of(day)
        max_allowed = d.get("max_allowed", d.get("max"))
        return cls(
            day=int(day),
            shift=d["shift"],
            role=d["role"],
            required=int(d["required"]),
            max_allowed=None if max_allowed is None else int(max_allowed),
        )


def expand_demand(patterns: list[dict], horizon: Horizon) -> list[Demand]:
    """Turn compact staffing patterns into one :class:`Demand` per day."""
    from .horizon import WEEKDAY_NAMES

    resolved: dict[tuple[int, str, str], Demand] = {}
    for p in patterns:
        selector = p.get("days", "all")
        if selector == "all":
            days = list(range(horizon.num_days))
        elif selector == "weekday":
            days = [i for i, d in enumerate(horizon.days) if not d.is_weekend]
        elif selector == "weekend":
            days = horizon.weekend_indices()
        elif selector == "holiday":
            days = [i for i, d in enumerate(horizon.days) if d.is_holiday]
        elif isinstance(selector, (list, tuple)):
            days = []
            for item in selector:
                if isinstance(item, int):
                    days.append(item)
                elif item in WEEKDAY_NAMES:
                    wanted = WEEKDAY_NAMES.index(item)
                    days.extend(i for i in range(horizon.num_days)
                                if horizon.date_of(i).weekday() == wanted)
                else:
                    days.append(horizon.index_of(item))
        else:
            raise ValueError(f"unrecognised days selector {selector!r}")

        for day in sorted(set(days)):
            line = Demand.from_dict({**p, "day": day}, horizon)
            resolved[(line.day, line.shift, line.role)] = line

    return [resolved[k] for k in sorted(resolved)]


@dataclass
class Instance:
    """A complete rostering problem: who, when, what is needed, and the rules."""

    horizon: Horizon
    roles: list[Role]
    shifts: list[ShiftType]
    employees: list[Employee]
    demand: list[Demand] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    name: str = "instance"

    def __post_init__(self) -> None:
        self.role_index = {r.id: i for i, r in enumerate(self.roles)}
        self.shift_index = {s.id: i for i, s in enumerate(self.shifts)}
        self.emp_index = {e.id: i for i, e in enumerate(self.employees)}
        self.validate()

        # employee -> role indexes held; role -> employee indexes qualified
        self.roles_of = [
            frozenset(self.role_index[r] for r in e.roles) for e in self.employees
        ]
        self.eligible = [
            tuple(e for e in range(self.num_employees) if r in self.roles_of[e])
            for r in range(self.num_roles)
        ]

        self.required: dict[tuple[int, int, int], int] = {}
        self.max_allowed: dict[tuple[int, int, int], int] = {}
        for line in self.demand:
            key = (line.day, self.shift_index[line.shift], self.role_index[line.role])
            self.required[key] = line.required
            if line.max_allowed is not None:
                self.max_allowed[key] = line.max_allowed
        self.demand_cells = sorted(self.required)
        self.total_required = sum(self.required.values())

    @property
    def num_days(self) -> int:
        return self.horizon.num_days

    @property
    def num_roles(self) -> int:
        return len(self.roles)

    @property
    def num_shifts(self) -> int:
        return len(self.shifts)

    @property
    def num_employees(self) -> int:
        return len(self.employees)

    def validate(self) -> None:
        """Fail loudly on any inconsistency the admin could plausibly submit."""
        if not self.roles:
            raise ValueError("instance has no roles")
        if not self.shifts:
            raise ValueError("instance has no shifts")
        if not self.employees:
            raise ValueError("instance has no employees")
        if len(self.role_index) != len(self.roles):
            raise ValueError("duplicate role ids")
        if len(self.shift_index) != len(self.shifts):
            raise ValueError("duplicate shift ids")
        if len(self.emp_index) != len(self.employees):
            raise ValueError("duplicate employee ids")

        for e in self.employees:
            unknown = [r for r in e.roles if r not in self.role_index]
            if unknown:
                raise ValueError(f"employee {e.id} holds unknown role(s) {unknown}")

        for line in self.demand:
            if not 0 <= line.day < self.num_days:
                raise ValueError(f"demand day {line.day} outside the horizon")
            if line.shift not in self.shift_index:
                raise ValueError(f"demand names unknown shift {line.shift!r}")
            if line.role not in self.role_index:
                raise ValueError(f"demand names unknown role {line.role!r}")

        seen: set[str] = set()
        for rule in self.rules:
            if rule.id in seen:
                raise ValueError(f"duplicate rule id {rule.id!r}")
            seen.add(rule.id)
            if rule.scope.kind == SCOPE_EMPLOYEES:
                unknown = [i for i in rule.scope.ids if i not in self.emp_index]
                if unknown:
                    raise ValueError(f"rule {rule.id} scopes unknown employee(s) {unknown}")
            if rule.scope.kind == SCOPE_ROLES:
                unknown = [i for i in rule.scope.ids if i not in self.role_index]
                if unknown:
                    raise ValueError(f"rule {rule.id} scopes unknown role(s) {unknown}")

    def role_of(self, r: int) -> Role:
        return self.roles[r]

    def shift_of(self, s: int) -> ShiftType:
        return self.shifts[s]

    def employee_of(self, e: int) -> Employee:
        return self.employees[e]

    def scope_employees(self, rule: Rule) -> list[int]:
        """Employee *indexes* a rule applies to."""
        ids = rule.scope.resolve(self.employees)
        return [self.emp_index[i] for i in ids]

    def is_qualified(self, e: int, r: int) -> bool:
        return r in self.roles_of[e]

    def required_at(self, day: int, s: int, r: int) -> int:
        return self.required.get((day, s, r), 0)

    def roles_needed_on(self, day: int, s: int) -> list[int]:
        return [r for (d, ss, r) in self.demand_cells if d == day and ss == s]

    def forbidden_rest_pairs(self, min_rest_min: int, day_delta: int = 1) -> list[tuple[int, int]]:
        """Shift pairs (s1 on day d, s2 on day d+day_delta) that break a rest gap."""
        pairs = []
        for i, s1 in enumerate(self.shifts):
            for j, s2 in enumerate(self.shifts):
                if s1.rest_gap_to(s2, day_delta) < min_rest_min:
                    pairs.append((i, j))
        return pairs

    def summary(self) -> str:
        hard = sum(1 for r in self.rules if r.is_hard)
        return (
            f"{self.name}: {self.num_employees} employees, {self.num_roles} roles, "
            f"{self.num_shifts} shifts, {self.num_days} days from "
            f"{self.horizon.start.isoformat()}, {self.total_required} person-shifts "
            f"of demand, {len(self.rules)} rules ({hard} hard)"
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "horizon": self.horizon.to_dict(),
            "roles": [r.to_dict() for r in self.roles],
            "shifts": [s.to_dict() for s in self.shifts],
            "employees": [e.to_dict() for e in self.employees],
            "demand": [d.to_dict() for d in self.demand],
            "rules": [r.to_dict() for r in self.rules],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Instance":
        horizon = Horizon.from_dict(data["horizon"])
        demand_spec = data.get("demand", [])
        if "demand_patterns" in data:
            demand = expand_demand(data["demand_patterns"], horizon)
            demand += [Demand.from_dict(d, horizon) for d in demand_spec]
        else:
            demand = [Demand.from_dict(d, horizon) for d in demand_spec]
        return cls(
            horizon=horizon,
            roles=[Role.from_dict(r) for r in data["roles"]],
            shifts=[ShiftType.from_dict(s) for s in data["shifts"]],
            employees=[Employee.from_dict(e) for e in data["employees"]],
            demand=demand,
            rules=[Rule.from_dict(r) for r in data.get("rules", [])],
            name=data.get("name", "instance"),
        )
