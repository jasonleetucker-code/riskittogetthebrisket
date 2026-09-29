"""Active-time calendar for the rookie auction room.

Every auction clock in the room counts ACTIVE seconds only.  The normal
activity window is 08:00 (inclusive) through 21:00 (exclusive) in the room's
IANA timezone (``America/New_York`` — never a fixed UTC offset), every day.
Outside that window nothing binding happens and no clock runs.

All times are POSIX epoch seconds (floats).  The server's clock (or a mock
room's server-owned virtual clock) is the only input; browser time never
reaches this module.

Deadlines are stored as absolute epochs computed THROUGH this calendar, so a
scheduled overnight pause needs no bookkeeping: one active hour left at 20:30
closes at 08:30 the next morning because ``add_active`` spends the 30 minutes
to 21:00, skips the quiet interval, and spends the remaining 30 minutes from
08:00.  A deadline that lands exactly on 21:00 closes AT 21:00 (it reached
zero at the boundary); it is never pushed to the next morning.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

DEFAULT_TZ = "America/New_York"
DEFAULT_START_SECONDS = 8 * 3600
DEFAULT_END_SECONDS = 21 * 3600

# Guard against a malformed window turning a loop into an infinite one.
_MAX_DAYS_SCANNED = 4000


@dataclass(frozen=True)
class ActiveWindow:
    """The daily active window.  ``enabled=False`` means always active
    (mock rooms with accelerated timing)."""

    enabled: bool = True
    tz: str = DEFAULT_TZ
    start_seconds: int = DEFAULT_START_SECONDS
    end_seconds: int = DEFAULT_END_SECONDS

    def __post_init__(self) -> None:
        if self.enabled:
            if not (0 <= self.start_seconds < self.end_seconds <= 24 * 3600):
                raise ValueError("active window must satisfy 0 <= start < end <= 24h")
            ZoneInfo(self.tz)  # raises on an unknown zone

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "ActiveWindow":
        if not data:
            return cls()
        return cls(
            enabled=bool(data.get("enabled", True)),
            tz=str(data.get("tz", DEFAULT_TZ)),
            start_seconds=int(data.get("start_seconds", DEFAULT_START_SECONDS)),
            end_seconds=int(data.get("end_seconds", DEFAULT_END_SECONDS)),
        )

    @property
    def active_seconds_per_day(self) -> int:
        if not self.enabled:
            return 24 * 3600
        return self.end_seconds - self.start_seconds


@lru_cache(maxsize=4096)
def _day_bounds(tz: str, day: date, start_seconds: int, end_seconds: int) -> tuple[float, float]:
    zone = ZoneInfo(tz)
    # Local wall-clock arithmetic: build the wall times, then let zoneinfo
    # resolve each one's offset independently (DST-correct).
    start_wall = datetime.combine(day, time(0, 0)) + timedelta(seconds=start_seconds)
    end_wall = datetime.combine(day, time(0, 0)) + timedelta(seconds=end_seconds)
    start = start_wall.replace(tzinfo=zone).timestamp()
    end = end_wall.replace(tzinfo=zone).timestamp()
    return start, end


def _local_date(window: ActiveWindow, t: float) -> date:
    return datetime.fromtimestamp(t, ZoneInfo(window.tz)).date()


def window_bounds_for_day(window: ActiveWindow, day: date) -> tuple[float, float]:
    return _day_bounds(window.tz, day, window.start_seconds, window.end_seconds)


def is_active(window: ActiveWindow, t: float) -> bool:
    if not window.enabled:
        return True
    start, end = window_bounds_for_day(window, _local_date(window, t))
    return start <= t < end


def next_active_start(window: ActiveWindow, t: float) -> float:
    """``t`` itself when active, else the start of the next active window."""
    if not window.enabled:
        return t
    day = _local_date(window, t)
    for _ in range(_MAX_DAYS_SCANNED):
        start, end = window_bounds_for_day(window, day)
        if t < start:
            return start
        if t < end:
            return t
        day = day + timedelta(days=1)
    raise RuntimeError("active window scan exceeded bound")


def _window_end_containing(window: ActiveWindow, t: float) -> float:
    start, end = window_bounds_for_day(window, _local_date(window, t))
    if not (start <= t < end):
        raise ValueError("t is not inside an active window")
    return end


def add_active(window: ActiveWindow, t: float, seconds: float) -> float:
    """The epoch at which ``seconds`` of ACTIVE time have elapsed after ``t``.

    ``seconds <= 0`` returns ``t`` unchanged.  A result that exactly exhausts
    a window returns that window's end (21:00), never the next morning.
    """
    if seconds <= 0:
        return t
    if not window.enabled:
        return t + seconds
    remaining = float(seconds)
    cursor = t
    for _ in range(_MAX_DAYS_SCANNED):
        cursor = next_active_start(window, cursor)
        end = _window_end_containing(window, cursor)
        available = end - cursor
        if remaining <= available:
            return cursor + remaining
        remaining -= available
        cursor = end
    raise RuntimeError("add_active exceeded bound")


def active_between(window: ActiveWindow, a: float, b: float) -> float:
    """Seconds of ACTIVE time in ``[a, b)``; 0 when ``b <= a``."""
    if b <= a:
        return 0.0
    if not window.enabled:
        return b - a
    total = 0.0
    day = _local_date(window, a)
    for _ in range(_MAX_DAYS_SCANNED):
        start, end = window_bounds_for_day(window, day)
        if start >= b:
            break
        lo = max(a, start)
        hi = min(b, end)
        if hi > lo:
            total += hi - lo
        day = day + timedelta(days=1)
    else:  # pragma: no cover - guard
        raise RuntimeError("active_between exceeded bound")
    return total


def describe(window: ActiveWindow) -> str:
    if not window.enabled:
        return "Always active (accelerated mock timing — no nightly pause)"

    def fmt(s: int) -> str:
        h, m = divmod(s // 60, 60)
        suffix = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return f"{h12}:{m:02d} {suffix}"

    return f"Active {fmt(window.start_seconds)}–{fmt(window.end_seconds)} {window.tz}, every day"
