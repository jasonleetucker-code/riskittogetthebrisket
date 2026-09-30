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


@jobs.register("dfs_auto_refresh")
def _job(owner: str, params: dict[str, Any]) -> dict[str, Any]:
    """Queued by a page view that finds the slates stale; same code as the timer."""
    return refresh_nfl_live(force=False)
