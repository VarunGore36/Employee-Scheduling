"""The roster itself, plus the incremental bookkeeping the search relies on."""

from __future__ import annotations

from .schema import Instance

OFF = -1


class RowStats:
    """Everything the employee-scoped rules need about one employee's month."""

    __slots__ = (
        "shifts", "roles", "work", "total", "minutes", "day_minutes", "by_shift",
        "nights", "work_blocks", "off_blocks", "same_blocks", "pairs",
        "weekends_worked", "weekends_partial", "work_per_week", "off_per_week",
        "minutes_per_week",
    )

    def __init__(self, state: "RosterState", e: int) -> None:
        inst = state.inst
        num_days = inst.num_days
        shifts = state.shift_of[e]
        durations = state.shift_minutes

        self.shifts = shifts
        self.roles = state.role_of[e]
        self.work = [s != OFF for s in shifts]

        self.total = 0
        self.minutes = 0
        self.by_shift = [0] * inst.num_shifts
        self.nights = 0
        self.day_minutes = [0] * num_days
        for d, s in enumerate(shifts):
            if s != OFF:
                self.total += 1
                self.minutes += durations[s]
                self.day_minutes[d] = durations[s]
                self.by_shift[s] += 1
                if state.is_night[s]:
                    self.nights += 1

        # consecutive-day runs of work and of rest
        self.work_blocks: list[tuple[int, int]] = []
        self.off_blocks: list[tuple[int, int]] = []
        run_start = 0
        run_working = self.work[0] if num_days else False
        for d in range(1, num_days + 1):
            here = self.work[d] if d < num_days else not run_working
            if here != run_working:
                block = (run_start, d - run_start)
                (self.work_blocks if run_working else self.off_blocks).append(block)
                run_start = d
                run_working = here

        # runs of the *same* shift type, and every consecutive-day shift pair
        self.same_blocks: list[tuple[int, int, int]] = []
        self.pairs: list[tuple[int, int, int]] = []
        d = 0
        while d < num_days:
            s = shifts[d]
            if s == OFF:
                d += 1
                continue
            run = d + 1
            while run < num_days and shifts[run] == s:
                run += 1
            self.same_blocks.append((s, d, run - d))
            d = run
        for day in range(num_days - 1):
            a, b = shifts[day], shifts[day + 1]
            if a != OFF and b != OFF:
                self.pairs.append((day, a, b))

        # weekends: worked at all, and worked only in part
        self.weekends_worked = 0
        self.weekends_partial = 0
        for block in state.weekend_blocks:
            worked = sum(1 for i in block if self.work[i])
            if worked:
                self.weekends_worked += 1
                if worked < len(block):
                    self.weekends_partial += 1

        # per calendar week (partial weeks at the horizon edges included)
        self.work_per_week = []
        self.off_per_week = []
        self.minutes_per_week = []
        for week in state.calendar_weeks:
            worked = sum(1 for i in week if self.work[i])
            self.work_per_week.append(worked)
            self.off_per_week.append(len(week) - worked)
            self.minutes_per_week.append(sum(self.day_minutes[i] for i in week))

    def windows_worked(self, windows: list[list[int]]) -> list[int]:
        """Working-day count in each of the given day windows."""
        work = self.work
        return [sum(1 for i in w if work[i]) for w in windows]

    def windows_minutes(self, windows: list[list[int]]) -> list[int]:
        """Rostered minutes in each of the given day windows."""
        day_minutes = self.day_minutes
        return [sum(day_minutes[i] for i in w) for w in windows]


class RosterState:
    """A candidate roster, mutated in place by the search."""

    def __init__(self, inst: Instance) -> None:
        self.inst = inst
        D, E, S, R = inst.num_days, inst.num_employees, inst.num_shifts, inst.num_roles
        self.shift_of = [[OFF] * D for _ in range(E)]
        self.role_of = [[OFF] * D for _ in range(E)]
        self.cov = [[[0] * R for _ in range(S)] for _ in range(D)]
        self.headcount = [[0] * S for _ in range(D)]

        self.shift_minutes = [s.duration_min for s in inst.shifts]
        self.is_night = [s.counts_as_night for s in inst.shifts]
        self.weekend_blocks = inst.horizon.weekend_blocks()
        self.calendar_weeks = inst.horizon.calendar_weeks()

        self._stats: list[RowStats | None] = [None] * E

    def assign(self, e: int, d: int, s: int, r: int) -> None:
        """Put ``e`` on shift ``s`` covering role ``r`` on day ``d``."""
        old = self.shift_of[e][d]
        if old != OFF:
            self.cov[d][old][self.role_of[e][d]] -= 1
            self.headcount[d][old] -= 1
        self.shift_of[e][d] = s
        self.role_of[e][d] = r
        self.cov[d][s][r] += 1
        self.headcount[d][s] += 1
        self._stats[e] = None

    def unassign(self, e: int, d: int) -> None:
        old = self.shift_of[e][d]
        if old == OFF:
            return
        self.cov[d][old][self.role_of[e][d]] -= 1
        self.headcount[d][old] -= 1
        self.shift_of[e][d] = OFF
        self.role_of[e][d] = OFF
        self._stats[e] = None

    def set_day(self, e: int, d: int, s: int, r: int) -> None:
        """``assign`` when ``s`` is a shift, ``unassign`` when it is ``OFF``."""
        if s == OFF:
            self.unassign(e, d)
        else:
            self.assign(e, d, s, r)

    def invalidate(self, e: int) -> None:
        self._stats[e] = None

    def is_working(self, e: int, d: int) -> bool:
        return self.shift_of[e][d] != OFF

    def row_stats(self, e: int) -> RowStats:
        stats = self._stats[e]
        if stats is None:
            stats = RowStats(self, e)
            self._stats[e] = stats
        return stats

    def working_days(self, e: int) -> int:
        return self.row_stats(e).total

    def assignments(self) -> int:
        return sum(1 for row in self.shift_of for s in row if s != OFF)

    def workers_on(self, d: int, s: int, r: int) -> list[int]:
        return [
            e for e in range(self.inst.num_employees)
            if self.shift_of[e][d] == s and self.role_of[e][d] == r
        ]

    def coverage_gaps(self) -> list[tuple[tuple[int, int, int], int, int]]:
        """``((day, shift, role), have, required)`` for every cell that is off target."""
        out = []
        for key in self.inst.demand_cells:
            d, s, r = key
            have = self.cov[d][s][r]
            need = self.inst.required[key]
            if have != need:
                out.append((key, have, need))
        return out

    def under_coverage(self) -> int:
        return sum(
            max(self.inst.required[k] - self.cov[k[0]][k[1]][k[2]], 0)
            for k in self.inst.demand_cells
        )

    def over_coverage(self) -> int:
        total = 0
        for k in self.inst.demand_cells:
            d, s, r = k
            total += max(self.cov[d][s][r] - self.inst.required[k], 0)
        # people rostered onto a role nobody asked for that day count as excess
        for d in range(self.inst.num_days):
            for s in range(self.inst.num_shifts):
                for r in range(self.inst.num_roles):
                    if (d, s, r) not in self.inst.required:
                        total += self.cov[d][s][r]
        return total

    def copy(self) -> "RosterState":
        clone = RosterState.__new__(RosterState)
        clone.inst = self.inst
        clone.shift_of = [row[:] for row in self.shift_of]
        clone.role_of = [row[:] for row in self.role_of]
        clone.cov = [[cell[:] for cell in day] for day in self.cov]
        clone.headcount = [day[:] for day in self.headcount]
        clone.shift_minutes = self.shift_minutes
        clone.is_night = self.is_night
        clone.weekend_blocks = self.weekend_blocks
        clone.calendar_weeks = self.calendar_weeks
        clone._stats = [None] * self.inst.num_employees
        return clone

    def to_dict(self) -> dict:
        """Roster as ids and ISO dates - what the API returns to the frontend."""
        inst = self.inst
        rows = []
        for e, emp in enumerate(inst.employees):
            days = []
            for d in range(inst.num_days):
                s = self.shift_of[e][d]
                days.append(
                    None if s == OFF
                    else {
                        "shift": inst.shifts[s].id,
                        "role": inst.roles[self.role_of[e][d]].id,
                    }
                )
            rows.append({"employee": emp.id, "days": days})
        return {
            "start": inst.horizon.start.isoformat(),
            "num_days": inst.num_days,
            "dates": [inst.horizon.date_of(d).isoformat() for d in range(inst.num_days)],
            "rows": rows,
        }

    @classmethod
    def from_dict(cls, inst: Instance, data: dict) -> "RosterState":
        state = cls(inst)
        for row in data["rows"]:
            e = inst.emp_index[row["employee"]]
            for d, cell in enumerate(row["days"]):
                if cell:
                    state.assign(e, d, inst.shift_index[cell["shift"]],
                                 inst.role_index[cell["role"]])
        return state
