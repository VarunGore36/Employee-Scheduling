"""Planning horizon: an arbitrary start date plus a run of consecutive days."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

# Monday=0 .. Sunday=6, matching date.weekday()
WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DEFAULT_WEEKEND = (5, 6)  # Sat, Sun


@dataclass(frozen=True)
class Day:
    """One day in the horizon."""

    index: int
    date: date
    is_weekend: bool
    is_holiday: bool

    @property
    def weekday(self) -> int:
        return self.date.weekday()

    @property
    def weekday_name(self) -> str:
        return WEEKDAY_NAMES[self.weekday]

    @property
    def iso(self) -> str:
        return self.date.isoformat()

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Day({self.index}, {self.iso}, {self.weekday_name})"


@dataclass
class Horizon:
    """The scheduling window."""

    start: date
    num_days: int
    weekend_days: tuple[int, ...] = DEFAULT_WEEKEND
    holidays: frozenset[date] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.num_days < 1:
            raise ValueError("num_days must be >= 1")
        if isinstance(self.start, str):
            self.start = date.fromisoformat(self.start)
        self.weekend_days = tuple(sorted(set(self.weekend_days)))
        if any(d < 0 or d > 6 for d in self.weekend_days):
            raise ValueError("weekend_days must be in 0..6 (Mon..Sun)")
        self.holidays = frozenset(
            date.fromisoformat(h) if isinstance(h, str) else h for h in self.holidays
        )

    @property
    def days(self) -> list[Day]:
        return [self.day(i) for i in range(self.num_days)]

    def day(self, index: int) -> Day:
        if not 0 <= index < self.num_days:
            raise IndexError(f"day index {index} outside horizon 0..{self.num_days - 1}")
        d = self.start + timedelta(days=index)
        return Day(
            index=index,
            date=d,
            is_weekend=d.weekday() in self.weekend_days,
            is_holiday=d in self.holidays,
        )

    def date_of(self, index: int) -> date:
        return self.start + timedelta(days=index)

    def index_of(self, d: date | str) -> int:
        """Day offset for a real date. Raises if outside the horizon."""
        if isinstance(d, str):
            d = date.fromisoformat(d)
        offset = (d - self.start).days
        if not 0 <= offset < self.num_days:
            raise ValueError(f"{d.isoformat()} is outside the horizon")
        return offset

    def __len__(self) -> int:
        return self.num_days

    def __iter__(self):
        return iter(self.days)

    def weekend_indices(self) -> list[int]:
        return [i for i in range(self.num_days) if self.date_of(i).weekday() in self.weekend_days]

    def weekend_blocks(self) -> list[list[int]]:
        """Consecutive weekend day-runs, e.g. [[5,6],[12,13],...]."""
        blocks: list[list[int]] = []
        for i in self.weekend_indices():
            if blocks and i == blocks[-1][-1] + 1:
                blocks[-1].append(i)
            else:
                blocks.append([i])
        return blocks

    def calendar_weeks(self) -> list[list[int]]:
        """Day indices grouped into ISO calendar weeks (partial weeks included)."""
        weeks: list[list[int]] = []
        current_key = None
        for i in range(self.num_days):
            key = self.date_of(i).isocalendar()[:2]
            if key != current_key:
                weeks.append([])
                current_key = key
            weeks[-1].append(i)
        return weeks

    def rolling_windows(self, size: int) -> list[list[int]]:
        """Every window of ``size`` consecutive days that fits in the horizon."""
        if size < 1:
            raise ValueError("window size must be >= 1")
        return [list(range(i, i + size)) for i in range(0, self.num_days - size + 1)]

    def to_dict(self) -> dict:
        return {
            "start": self.start.isoformat(),
            "num_days": self.num_days,
            "weekend_days": list(self.weekend_days),
            "holidays": sorted(h.isoformat() for h in self.holidays),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Horizon":
        return cls(
            start=date.fromisoformat(data["start"]),
            num_days=int(data["num_days"]),
            weekend_days=tuple(data.get("weekend_days", DEFAULT_WEEKEND)),
            holidays=frozenset(data.get("holidays", ())),
        )
