"""A snapshot whose CURRENT season came back half-fetched is a failure.

**Observed, then reproduced from live Sleeper data (2026-09-23).** The owner's
League Power Rankings share card showed 10 of 12 teams, a "Preseason" label
in Week 3 and NEW on every row. ``sleeper_client`` answers every failed GET
with ``[]``, so a blip on ``/league/<id>/rosters`` produced a snapshot that
had seasons and managers (from the older seasons) while the current season
had no rosters. ``_rebuild_public_snapshot`` refused only a ZERO-season
snapshot, so this one was cached, served for the TTL plus
stale-while-revalidate, and persisted to disk.

Built from the real 2026-09-23 league with the 2026 rosters blanked, the
Power engine reproduced the card exactly: the same ten names in the same
order, ranked on the 2025 season's results, ``asOfWeek == 0``.

These tests pin the ingestion half of the repair: the partial snapshot is
never cached, the last good snapshot keeps serving, and the failure is
counted. The engine half is pinned in
``tests/ros/test_power_current_season_integrity.py``.
"""

from __future__ import annotations

import time

import pytest

import server
from src.public_league.identity import build_manager_registry
from src.public_league.snapshot import (
    PublicLeagueSnapshot,
    SeasonSnapshot,
    current_season_integrity_error,
)


def _season(
    year: str,
    league_id: str,
    owners: list[str],
    *,
    last_scored_leg: int | None = 2,
    status: str = "in_season",
    weeks: tuple[int, ...] = (1, 2),
) -> SeasonSnapshot:
    rosters = [{"roster_id": i, "owner_id": oid} for i, oid in enumerate(owners, start=1)]
    users = [{"user_id": oid, "display_name": oid} for oid in owners]
    settings: dict = {"playoff_week_start": 15}
    if last_scored_leg is not None:
        settings["last_scored_leg"] = last_scored_leg
    matchups = {
        wk: [
            {"roster_id": r["roster_id"], "matchup_id": (r["roster_id"] + 1) // 2, "points": 100.0}
            for r in rosters
        ]
        for wk in weeks
    }
    return SeasonSnapshot(
        season=year,
        league_id=league_id,
        league={
            "league_id": league_id,
            "season": year,
            "status": status,
            "total_rosters": len(rosters),
            "settings": settings,
        },
        users=users,
        rosters=rosters,
        matchups_by_week=matchups,
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )


_OWNERS_2025 = [f"vet-{i:02d}" for i in range(1, 11)]
_OWNERS_2026 = [*_OWNERS_2025, "new-blaine", "new-jstuedle"]


def _snapshot(current: SeasonSnapshot) -> PublicLeagueSnapshot:
    prior = _season("2025", "L2025", _OWNERS_2025, last_scored_leg=17, status="complete")
    seasons = [current, prior]
    snap = PublicLeagueSnapshot(
        root_league_id="PARTIALTEST",
        generated_at="2026-09-23T00:00:00Z",
        seasons=seasons,
    )
    snap.managers = build_manager_registry(
        [{"league": s.league, "users": s.users, "rosters": s.rosters} for s in seasons]
    )
    return snap


def _healthy() -> PublicLeagueSnapshot:
    return _snapshot(_season("2026", "L2026", _OWNERS_2026))


def _rosters_failed() -> PublicLeagueSnapshot:
    current = _season("2026", "L2026", _OWNERS_2026)
    current.rosters = []
    return _snapshot(current)


class TestCurrentSeasonIntegrityError:
    def test_a_healthy_snapshot_has_no_error(self):
        assert current_season_integrity_error(_healthy()) is None

    def test_a_failed_rosters_fetch_is_an_error(self):
        assert "no rosters" in current_season_integrity_error(_rosters_failed())

    def test_a_failed_users_fetch_is_an_error(self):
        current = _season("2026", "L2026", _OWNERS_2026)
        current.users = []
        assert "no users" in current_season_integrity_error(_snapshot(current))

    def test_a_short_roster_list_is_an_error(self):
        current = _season("2026", "L2026", _OWNERS_2026)
        current.rosters = current.rosters[:10]
        assert "10 rosters" in current_season_integrity_error(_snapshot(current))

    def test_an_owner_missing_from_the_registry_is_an_error(self):
        snap = _healthy()
        snap.managers.roster_to_owner.pop(("L2026", 12))
        assert "do not resolve" in current_season_integrity_error(snap)

    def test_a_missing_scored_week_is_an_error(self):
        current = _season("2026", "L2026", _OWNERS_2026)
        del current.matchups_by_week[2]
        assert "week(s) [2]" in current_season_integrity_error(_snapshot(current))

    def test_an_unplayed_future_week_is_not_an_error(self):
        """Week 3 missing while the host says only week 2 is scored is the future."""
        current = _season("2026", "L2026", _OWNERS_2026, last_scored_leg=2, weeks=(1, 2))
        assert current_season_integrity_error(_snapshot(current)) is None

    def test_an_orphaned_roster_is_not_an_error(self):
        """Sleeper genuinely leaves ownerless rosters; the registry refuses to invent one."""
        current = _season("2026", "L2026", _OWNERS_2026)
        current.rosters[-1]["owner_id"] = None
        assert current_season_integrity_error(_snapshot(current)) is None

    def test_a_season_less_snapshot_is_left_to_the_zero_season_guard(self):
        snap = PublicLeagueSnapshot(root_league_id="X", generated_at="", seasons=[])
        assert current_season_integrity_error(snap) is None


@pytest.fixture
def cold_cache(monkeypatch):
    saved = dict(server._public_league_cache)
    saved_metrics = dict(server._public_league_metrics)
    monkeypatch.setattr(
        server._league_registry,
        "get_sleeper_league_id",
        lambda *a, **k: "PARTIALTEST",
    )
    # Persisting would write data/public_league/*.json from a test.
    monkeypatch.setattr(server, "_PUBLIC_LEAGUE_PERSIST", False)
    server._public_league_cache.update(
        {
            "snapshot": None,
            "snapshot_league_id": None,
            "fetched_at": 0.0,
            "refreshing": False,
            "last_failure_at": 0.0,
            "last_failure_error": None,
        }
    )
    yield
    server._public_league_cache.clear()
    server._public_league_cache.update(saved)
    server._public_league_metrics.clear()
    server._public_league_metrics.update(saved_metrics)


class TestPartialSnapshotIsRefusedNotCached:
    def test_with_nothing_cached_the_partial_snapshot_is_refused(self, cold_cache, monkeypatch):
        monkeypatch.setattr(server, "build_public_snapshot", lambda *a, **k: _rosters_failed())
        with pytest.raises(server.PublicSnapshotUnavailable, match="no rosters"):
            server._get_public_snapshot(force_refresh=True)
        assert server._public_league_cache["snapshot"] is None

    def test_the_last_good_snapshot_keeps_serving(self, cold_cache, monkeypatch):
        good = _healthy()
        monkeypatch.setattr(server, "build_public_snapshot", lambda *a, **k: good)
        assert server._get_public_snapshot(force_refresh=True) is good

        monkeypatch.setattr(server, "build_public_snapshot", lambda *a, **k: _rosters_failed())
        server._public_league_cache["fetched_at"] = (
            time.time() - server._PUBLIC_LEAGUE_CACHE_TTL_SECONDS - 1
        )
        assert server._get_public_snapshot(force_refresh=True) is good
        assert server._public_league_cache["snapshot"] is good

    def test_the_partial_rebuild_is_counted_and_arms_the_cooldown(self, cold_cache, monkeypatch):
        before = server._public_league_metrics.get("rebuild_failures", 0)
        monkeypatch.setattr(server, "build_public_snapshot", lambda *a, **k: _rosters_failed())
        with pytest.raises(server.PublicSnapshotUnavailable):
            server._get_public_snapshot(force_refresh=True)
        assert server._public_league_metrics["rebuild_failures"] == before + 1
        assert server._public_league_cache["last_failure_at"] > 0
        assert "partial snapshot" in str(server._public_league_cache["last_failure_error"])
