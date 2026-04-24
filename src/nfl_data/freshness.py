"""Freshness guard — don't fire alerts on mid-week, pre-republish
NFL data.

The NFL stats pipeline (nflverse parquets, PFR snap counts, ESPN
live boxscore) has a lag problem that's easy to miss: between
Sunday evening and Tuesday/Wednesday the data you pull back for
"last week" is provisional.  Fire a signal on Monday morning and
the next refresh moves the stat line, so the alert fires AGAIN on
Wednesday — spam, and worse, noisy data affecting the canonical
weights later.

This module encodes the rule: "don't trust current-week data
until Thursday local NFL day".  Callers ask
``is_fresh_for_alerts(week, year, now=None)`` and skip the alert
evaluation when False.
"""
from __future__ import annotations

import datetime as _dt
from zoneinfo import ZoneInfo

# NFL lives on US Eastern for most schedule purposes.  Using tzinfo
# so DST transitions are automatic.
_NFL_TZ = ZoneInfo("America/New_York")

# Which weekday we consider "safe to trust the previous week".
# Monday=0 ... Sunday=6.  Thursday (3) = after the pfr + nflverse
# republish catches up.
_SAFE_WEEKDAY = 3


def _nfl_now(now: _dt.datetime | None = None) -> _dt.datetime:
    if now is None:
        return _dt.datetime.now(_NFL_TZ)
    if now.tzinfo is None:
        return now.replace(tzinfo=_NFL_TZ)
    return now.astimezone(_NFL_TZ)


def is_fresh_for_alerts(
    stat_week: int,
    stat_year: int,
    *,
    now: _dt.datetime | None = None,
    season_year: int | None = None,
    season_current_week: int | None = None,
) -> bool:
    """Return True iff the caller may safely FIRE alerts using
    data from ``(stat_year, stat_week)``.

    Rules
    -----
    * ``season_year != stat_year`` → True (historical data is
      always fresh — already finalized by nflverse).
    * ``stat_week < season_current_week`` → True (prior completed
      weeks are finalized once the current week rolls).
    * ``stat_week == season_current_week`` → True iff today is
      on or after the safe weekday (Thursday) in NFL-TZ.
    * Any other shape (missing season context) → conservative
      False.
    """
    if season_year is None or stat_year != season_year:
        return True
    if season_current_week is None:
        # Unknown season progress — conservative.
        return False
    if stat_week < season_current_week:
        return True
    if stat_week > season_current_week:
        # Data from a future week should never be trusted.
        return False
    # stat_week == season_current_week — week-in-progress.
    now_n = _nfl_now(now)
    return now_n.weekday() >= _SAFE_WEEKDAY


def week_is_in_flight(
    stat_week: int,
    stat_year: int,
    *,
    now: _dt.datetime | None = None,
    season_year: int | None = None,
    season_current_week: int | None = None,
) -> bool:
    """True iff the stat row is from the week currently being played
    (pre-Thursday safe cutoff).  Used by UI to label data as
    provisional."""
    if season_year is None or stat_year != season_year:
        return False
    if season_current_week is None:
        return False
    if stat_week != season_current_week:
        return False
    now_n = _nfl_now(now)
    return now_n.weekday() < _SAFE_WEEKDAY
