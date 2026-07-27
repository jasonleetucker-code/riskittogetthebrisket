"""NFL schedule → per-team ROS week structures (byes, playoff weeks).

Fetches the nflverse schedules dataset (stdlib urllib, same release
pattern as ``src.nfl_data.nflverse_direct``), derives each team's
regular-season week list with byes marked, and stamps the league's
fantasy-playoff weeks so the ROS module can weight them.

Pure builders are separated from the fetch so tests use fixture rows.
"""

from __future__ import annotations

import csv
import io
import logging
import urllib.error
import urllib.request
from typing import Any, Iterable, Mapping

from src.bdvm.ros import RosWeek

_LOGGER = logging.getLogger(__name__)

_SCHEDULE_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/schedules/sched_{year}.csv"
)
# Combined all-seasons file — the fallback when the per-season file is
# not published yet (observed: sched_2026.csv 404s while games.csv has
# the 2026 slate).
_SCHEDULE_URL_ALL = (
    "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
)
_USER_AGENT = "riskitbrisket-bdvm/1.0 (+https://riskittogetthebrisket.org)"

# Sleeper-style default: fantasy playoffs in NFL weeks 15-17.
DEFAULT_PLAYOFF_WEEKS = (15, 16, 17)


def _get_csv(url: str, timeout: float) -> list[dict[str, Any]]:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        text = resp.read().decode("utf-8", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def fetch_schedule_rows(season: int, *, timeout: float = 60.0) -> list[dict[str, Any]]:
    """Raw schedule rows for one season; [] on any failure (degrade soft).

    Tries the per-season file, then falls back to the combined
    ``games.csv`` filtered to ``season``.
    """
    try:
        return _get_csv(_SCHEDULE_URL.format(year=season), timeout)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        _LOGGER.info("bdvm schedule: per-season file unavailable (%s); trying games.csv", exc)
    try:
        rows = _get_csv(_SCHEDULE_URL_ALL, timeout)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        _LOGGER.warning("bdvm schedule: fetch failed for %s: %s", season, exc)
        return []
    return [r for r in rows if str(r.get("season") or "").strip() == str(season)]


def team_weeks_from_schedule(
    rows: Iterable[Mapping[str, Any]],
    *,
    playoff_weeks: Iterable[int] = DEFAULT_PLAYOFF_WEEKS,
    max_week: int = 18,
) -> dict[str, list[RosWeek]]:
    """Schedule rows → team → [RosWeek(1..max_week)] with byes marked.

    A team's bye weeks are the regular-season weeks with no scheduled
    game.  ``p_active`` starts at 1.0 for every week — availability
    adjustments come from events/injury inputs, not the schedule.
    """
    playing: dict[str, set[int]] = {}
    for row in rows:
        if str(row.get("game_type") or "REG").upper() != "REG":
            continue
        try:
            week = int(float(row.get("week") or 0))
        except (TypeError, ValueError):
            continue
        if week < 1 or week > max_week:
            continue
        for side in ("home_team", "away_team"):
            team = str(row.get(side) or "").upper().strip()
            if team:
                playing.setdefault(team, set()).add(week)

    playoff = {int(w) for w in playoff_weeks}
    out: dict[str, list[RosWeek]] = {}
    for team, weeks_played in playing.items():
        out[team] = [
            RosWeek(
                week=w,
                is_bye=w not in weeks_played,
                p_active=1.0,
                is_league_playoff=w in playoff,
            )
            for w in range(1, max_week + 1)
        ]
    return out


def fetch_team_weeks(
    season: int, *, playoff_weeks: Iterable[int] = DEFAULT_PLAYOFF_WEEKS
) -> dict[str, list[RosWeek]]:
    rows = fetch_schedule_rows(season)
    if not rows:
        return {}
    return team_weeks_from_schedule(rows, playoff_weeks=playoff_weeks)
