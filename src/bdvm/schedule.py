"""NFL schedule → per-team ROS week structures (byes, playoff weeks).

Derives each team's regular-season week list with byes marked and stamps
the league's fantasy-playoff weeks so the ROS module can weight them.

**This module no longer downloads anything.**  It used to fetch the
nflverse schedules dataset with its own ``urllib.request.urlopen`` — a
SECOND nflverse downloader beside ``src.nfl_data.ingest``, with no TTL
cache, no single-flight and no feature gate — and it was reachable from
the live ``/api/bdvm/*`` request path.  Acquisition now belongs to the
canonical ingestion owner; this module only shapes what that owner
returns.  ``tests/bdvm/test_request_path_is_local.py`` asserts
structurally that the downloader cannot come back.

Pure builders are separated from the fetch so tests use fixture rows.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping

from src.bdvm.ros import RosWeek

_LOGGER = logging.getLogger(__name__)

# Sleeper-style default: fantasy playoffs in NFL weeks 15-17.
DEFAULT_PLAYOFF_WEEKS = (15, 16, 17)


def fetch_schedule_rows(
    season: int, *, timeout: float = 60.0, cache_only: bool = False
) -> list[dict[str, Any]]:
    """Raw schedule rows for one season; [] on any failure (degrade soft).

    Delegates to ``src.nfl_data.ingest.fetch_schedules``, which owns the
    URLs, the per-season → combined-file fallback, the 24h disk cache,
    the cold-cache single-flight and the ``nfl_data_ingest`` gate.

    ``timeout`` is accepted and unused: the canonical owner applies its
    own.  It is kept so existing callers and tests do not break on a
    signature change that has nothing to do with what they are testing.

    ``cache_only=True`` is the REQUEST-PATH mode and never fetches.

    SECOND CONSUMER, named because the reroute changes what it inherits:
    ``src/playerctx/asof.py::_default_fetch_rows`` calls this WITHOUT
    ``cache_only`` and always did — it fetched before this change too, so
    that is not a regression, and it now gains the 24h cache and the
    cold-cache single-flight it never had.  What is genuinely new is the
    ``nfl_data_ingest`` feature gate: with that flag OFF this returns
    ``[]`` where the raw downloader would still have fetched.  That is the
    correct coupling — bypassing the nflverse flag was part of what made
    the private downloader a second owner — and ``asof.py`` already
    degrades softly on empty rows.  Recorded rather than changed here;
    switching that caller to a materialised read belongs to playerctx.
    """
    from src.nfl_data import ingest  # noqa: PLC0415

    try:
        return list(ingest.fetch_schedules([int(season)], cache_only=cache_only) or [])
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("bdvm schedule: rows unavailable for %s: %s", season, exc)
        return []


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
    season: int,
    *,
    playoff_weeks: Iterable[int] = DEFAULT_PLAYOFF_WEEKS,
    cache_only: bool = False,
) -> dict[str, list[RosWeek]]:
    """Per-team ROS weeks, or ``{}`` when the schedule is unavailable.

    ``cache_only=True`` is the request-path mode.  An empty result is the
    SAME degraded state this function already returned on a failed fetch:
    the ROS enrichment is reduced, never fabricated, and playoff weighting
    is untouched.
    """
    rows = fetch_schedule_rows(season, cache_only=cache_only)
    if not rows:
        return {}
    return team_weeks_from_schedule(rows, playoff_weeks=playoff_weeks)
