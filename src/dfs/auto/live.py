"""The real fetchers behind ``refresh.refresh_nfl`` (and the ``dfs_auto_refresh`` job).

Each one goes through the Calculator's existing owner for that data — nothing
here opens a second downloader:

* schedule → ``src.nfl_data.ingest.fetch_schedules`` (cached, flag ``nfl_data_ingest``);
* salaries/pool → ``src.dfs.sources_dff`` (owner-authorised seed A-020; 15-minute
  page cache, descriptive User-Agent, no retries in a loop);
* projections → ``src.ros.sleeper_weekly_projections.fetch_weekly_projection_rows``
  (flag ``sleeper_weekly_projections``);
* identity/status → the Sleeper directory the app already keeps on disk
  (``consensus_edge.identity_join.load_player_directory``) — read-only here.

NBA / NHL (DFS-AUTO-19):

* salaries/pool → the same DFF adapter, per sport;
* schedule → ``src.dfs.auto.league_schedule`` (ESPN scoreboard, cached 30 min).
"""

from __future__ import annotations

from typing import Any

from src.dfs import jobs


class LiveSourceError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def get_schedule(season: int) -> list[dict[str, Any]]:
    from src.nfl_data.ingest import fetch_schedules

    rows = fetch_schedules([season])
    if not rows:
        raise LiveSourceError("SCHEDULE_UNAVAILABLE", "No schedule rows (flag off or source down).")
    return rows


def get_dff(platform: str) -> dict[str, Any]:
    from src.dfs import sources_dff

    page = sources_dff.fetch("nfl", platform)
    rows = sources_dff.parse(page["html"])
    if not rows:
        raise sources_dff.SourceError("SOURCE_EMPTY", "The salary page listed no players.")
    return {
        "rows": rows,
        "url": page["url"],
        "fetchedAt": page["fetchedAt"],
        "updatedAt": sources_dff.page_updated_at(page["html"]),
        "sha256": page["sha256"],
    }


def get_daily_dff(sport: str, platform: str) -> dict[str, Any]:
    """A daily sport's DFF page.  An EMPTY page is returned as such (no slate is
    listed today — an off day or preseason), not raised: it is not a failure."""
    from src.dfs import sources_dff

    page = sources_dff.fetch(sport, platform)
    return {
        "rows": sources_dff.parse(page["html"]),
        "url": page["url"],
        "fetchedAt": page["fetchedAt"],
        "updatedAt": sources_dff.page_updated_at(page["html"]),
        "sha256": page["sha256"],
    }


def get_daily_schedule(sport: str, day: str) -> dict[str, Any]:
    from src.dfs.auto import league_schedule

    raw = league_schedule.fetch(sport, day)
    games, dropped = league_schedule.parse(sport, raw["payload"])
    return {
        "games": games,
        "dropped": dropped,
        "url": raw["url"],
        "fetchedAt": raw["fetchedAt"],
        "sha256": raw["sha256"],
    }


def get_sleeper_rows(season: int, week: int) -> tuple[list[Any], str] | None:
    from src.ros.sleeper_weekly_projections import fetch_weekly_projection_rows

    res = fetch_weekly_projection_rows(season, week)
    if res.status != "ok" or not res.rows:
        return None
    return list(res.rows), res.observed_at


def get_directory() -> dict[str, Any] | None:
    from src.consensus_edge.identity_join import load_player_directory

    return load_player_directory()


def enabled() -> bool:
    """Literal flag name on purpose: the reachability audit reads literals only."""
    try:
        from src.api.feature_flags import is_enabled

        return is_enabled("dfs_auto_slates")
    except Exception:  # noqa: BLE001
        return False


def sport_approved(sport: str) -> bool:
    """NBA / NHL automatic slates need the owner's recorded approval of their
    schedule source (``config/dfs/auto_sources.json``); NFL does not read it."""
    if sport == "nfl":
        return True
    from src.dfs.auto import approval

    return approval.sport_status(sport)["approved"]


def refresh_nfl_live(force: bool = False) -> dict[str, Any]:
    from src.dfs.auto import refresh

    if not enabled():
        return {"outcome": "not_due", "reason": "feature flag dfs_auto_slates is off"}

    return refresh.refresh_nfl(
        get_schedule=get_schedule,
        get_dff=get_dff,
        get_sleeper_rows=get_sleeper_rows,
        get_directory=get_directory,
        force=force,
    )


def refresh_live(sport: str, force: bool = False) -> dict[str, Any]:
    """One sport's refresh with the real fetchers (``nfl`` | ``nba`` | ``nhl``)."""
    from src.dfs.auto import refresh

    if sport == "nfl":
        return refresh_nfl_live(force=force)
    if not enabled():
        return {
            "outcome": "not_due",
            "sport": sport,
            "reason": "feature flag dfs_auto_slates is off",
        }
    if not sport_approved(sport):
        # Built and ready, but the schedule source awaits the owner's decision
        # (ADR-DFS-025): nothing is fetched, nothing is built.
        return {"outcome": "awaiting_approval", "sport": sport, "reason": "schedule_source_pending"}
    return refresh.refresh_daily(
        sport, get_dff=get_daily_dff, get_schedule=get_daily_schedule, force=force
    )


def refresh_all_live(force: bool = False) -> dict[str, dict[str, Any]]:
    """Every automatic sport, each deciding for itself whether it is due.  One
    sport's failure never stops another's refresh."""
    from src.dfs.auto import refresh

    out: dict[str, dict[str, Any]] = {}
    for sport in refresh.AUTO_SPORTS:
        try:
            out[sport] = refresh_live(sport, force=force)
        except Exception as exc:  # noqa: BLE001 - recorded, never raised into the timer
            out[sport] = {"outcome": "source_error", "sport": sport, "error": type(exc).__name__}
    return out


@jobs.register("dfs_auto_refresh")
def _job(owner: str, params: dict[str, Any]) -> dict[str, Any]:
    """Queued by a page view that finds a sport's slates stale; same code as the timer."""
    sport = str((params or {}).get("sport") or "nfl")
    from src.dfs.auto import refresh

    if sport not in refresh.AUTO_SPORTS:
        return {"outcome": "unavailable", "reason": f"no automatic path for {sport}"}
    return refresh_live(sport, force=False)
