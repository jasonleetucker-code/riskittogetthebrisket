"""Game Day collector — schedule-result refresh while a final is missing.

Production 2026-09-28: with the live game feed unavailable, a game's FINAL
comes only from the nflverse schedule's published result.  Game Day read the
schedule cache (24 h TTL) and nothing refreshed it for Game Day, so Sunday
night's LA @ DEN final stayed "status unknown" ~20 h after it ended and
paused every forecast involving its players.

Pinned: the collector refreshes the schedule through its one owner ONLY while
a kicked-off game this week has no result, at most every
``SCHEDULE_RESULT_REFRESH_SECONDS``, under the tick budget and a persisted
backoff; a refreshed result makes that game final in the published
generation; nothing is inferred from wall time.
"""

from __future__ import annotations

import json

from src.nfl_data import ingest
from src.ros import game_day_live as live
from tests.game_day.test_game_day_live_collector import (
    SEASON,
    WEEK,
    FixtureWorld,
    _hermetic_sim_cache,  # noqa: F401 — autouse fixture, re-used
)
from tests.game_day.test_game_day_replay import _schedule_rows


def _row(away, home, day, time, score=None):
    return {
        "season": SEASON,
        "week": WEEK,
        "game_type": "REG",
        "gameday": day,
        "gametime": time,
        "home_team": home,
        "away_team": away,
        "home_score": None if score is None else score[1],
        "away_score": None if score is None else score[0],
        "result": None if score is None else score[1] - score[0],
    }


class _Clients:
    def __init__(self, refresh=None):
        self.schedule_refresh = refresh


def _decide(rows, *, observed_at, now, refresh=None, health=None, budget=None):
    return live.maybe_refresh_schedule(
        _Clients(refresh),
        {} if health is None else health,
        budget or live.RequestBudget(),
        rows,
        observed_at,
        season=SEASON,
        week=WEEK,
        now=now,
    )


# 2026-09-27 20:20 ET (00:20Z Sep 28) is well in the past at this "now".
NOW = 1790630000.0  # 2026-09-28T19:13:20Z


def test_a_kicked_off_game_without_a_result_triggers_a_refresh():
    calls = []
    rows = [_row("LA", "DEN", "2026-09-27", "20:20")]
    refreshed, stamp = _decide(
        rows, observed_at=NOW - 3600, now=NOW, refresh=lambda s, age: calls.append((s, age)) or True
    )
    assert refreshed is True and stamp["status"] == "refreshed"
    assert calls == [(SEASON, live.SCHEDULE_RESULT_REFRESH_SECONDS)]
    # nflverse "LA" is normalized to "LAR", as the page shows it.
    assert stamp["resultsPending"] == [f"{SEASON}_{WEEK}_LAR_DEN"]


def test_no_refresh_when_every_started_game_has_a_result():
    rows = [
        _row("LA", "DEN", "2026-09-27", "20:20", score=(26, 30)),
        _row("PHI", "CHI", "2026-09-28", "20:15"),
    ]
    calls = []
    refreshed, stamp = _decide(
        rows, observed_at=NOW - 86000, now=NOW, refresh=lambda *a: calls.append(a) or True
    )
    # PHI @ CHI kicks off later tonight: an unplayed game is not a missing result.
    assert (refreshed, stamp["status"], calls) == (False, "not_needed", [])


def test_a_recent_copy_is_not_refetched():
    rows = [_row("LA", "DEN", "2026-09-27", "20:20")]
    calls = []
    refreshed, stamp = _decide(
        rows,
        observed_at=NOW - live.SCHEDULE_RESULT_REFRESH_SECONDS + 5,
        now=NOW,
        refresh=lambda *a: calls.append(a) or True,
    )
    assert (refreshed, stamp["status"], calls) == (False, "recent_enough", [])


def test_a_failed_refresh_is_reported_backs_off_and_never_raises():
    rows = [_row("LA", "DEN", "2026-09-27", "20:20")]
    health: dict = {}

    def boom(*_a):
        raise RuntimeError("network down")

    for _ in range(live.BACKOFF_FAILURE_THRESHOLD):
        refreshed, stamp = _decide(
            rows, observed_at=NOW - 3600, now=NOW, refresh=boom, health=health
        )
        assert (
            refreshed is False and stamp["status"] == "error" and stamp["error"] == "RuntimeError"
        )
    assert health[live.SOURCE_SCHEDULE]["backoffUntil"]
    refreshed, stamp = _decide(rows, observed_at=NOW - 3600, now=NOW, refresh=boom, health=health)
    assert stamp["status"] == "skipped_backoff"
    empty, stamp = _decide(
        rows, observed_at=NOW - 3600, now=NOW + 10_000, refresh=lambda *a: False, health={}
    )
    assert (empty, stamp["status"], stamp["error"]) == (False, "error", "no_rows")


def test_the_refresh_is_counted_against_the_tick_budget():
    budget = live.RequestBudget(limit=0)
    calls = []
    refreshed, stamp = _decide(
        [_row("LA", "DEN", "2026-09-27", "20:20")],
        observed_at=None,
        now=NOW,
        refresh=lambda *a: calls.append(a) or True,
        budget=budget,
    )
    assert (refreshed, stamp["status"], calls) == (False, "budget_exhausted", [])


class RefreshWorld(FixtureWorld):
    """The replay world with no live feed and a schedule whose result arrives on refresh."""

    def __init__(self):
        super().__init__("real_halftime")
        self.espn_error = "http_error:403"  # production's ESPN posture
        self.rows = _schedule_rows(self.sc["espn"])
        self.final_after_refresh: dict | None = None
        self.refreshes = 0

    def clients(self) -> live.Clients:
        base = super().clients()

        def schedule(season):
            return [dict(r) for r in self.rows], self.captured_at - 3600.0, self.clock()

        def refresh(season, max_age):
            self.refreshes += 1
            if self.final_after_refresh:
                # A refresh rewrites the cache: NEW rows, never an in-place edit
                # of rows the tick already holds (that would hide a missing
                # re-read).
                fresh = []
                for r in self.rows:
                    r = dict(r)
                    key = (r["away_team"], r["home_team"])
                    if key in self.final_after_refresh:
                        away, home = self.final_after_refresh[key]
                        r.update(away_score=away, home_score=home, result=home - away)
                    fresh.append(r)
                self.rows = fresh
            return True

        base.schedule = schedule
        base.schedule_refresh = refresh
        return base


def test_a_refreshed_result_makes_the_game_final_in_the_generation():
    world = RefreshWorld()
    started = [r for r in world.rows if r["gameday"] <= "2026-09-25"]
    assert started, "the capture has a kicked-off game"
    target = (started[0]["away_team"], started[0]["home_team"])
    world.final_after_refresh = {target: (17, 20)}
    world.clock.ts = world.captured_at + 6 * 3600  # hours after kickoff, no live feed
    report = world.tick()
    assert world.refreshes == 1
    assert report.sources[live.SOURCE_SCHEDULE]["status"] == "refreshed"
    gen = live.load_generation("dynasty_main", SEASON, WEEK)
    evidence = gen["render"]["lineage"]["gameEvidence"]
    assert evidence[target[1]]["state"] == "completed"
    assert evidence[target[0]]["state"] == "completed"


def test_without_a_published_result_the_game_stays_unknown():
    world = RefreshWorld()  # refresh succeeds but nflverse has not published yet
    world.clock.ts = world.captured_at + 6 * 3600
    world.tick()
    gen = live.load_generation("dynasty_main", SEASON, WEEK)
    states = {v["state"] for v in gen["render"]["lineage"]["gameEvidence"].values()}
    assert "completed" not in states and "unknown" in states  # never a wall-clock final


# ── The ingest owner: a caller may shorten, never extend, the TTL ─────


def test_fetch_schedules_max_age_only_shortens_the_ttl(monkeypatch, tmp_path):
    fetches = []
    monkeypatch.setattr(ingest, "_gated", lambda: True)

    def provider(years):
        fetches.append(list(years))
        return [{"season": SEASON, "week": WEEK}]

    monkeypatch.setattr(ingest, "_try_fetch_with_fallback", lambda years, _p, **kw: provider(years))
    first = ingest.fetch_schedules([SEASON], cache_dir=tmp_path)
    assert first and len(fetches) == 1
    # Fresh cache: default TTL and a generous max age both reuse it.
    ingest.fetch_schedules([SEASON], cache_dir=tmp_path)
    ingest.fetch_schedules([SEASON], cache_dir=tmp_path, max_age_seconds=10 * 86400)
    assert len(fetches) == 1
    # Age the artifact past a short max age (the cache ages entries by the
    # ``fetched_at`` it records, not file times): that caller refetches.
    key = ingest.cache_key("schedules", [SEASON])
    import time as _t

    aged = 0
    for f in tmp_path.rglob("*"):
        if not f.is_file():
            continue
        try:
            meta = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(meta, dict) and "fetched_at" in meta:
            meta["fetched_at"] = _t.time() - 1000
            f.write_text(json.dumps(meta), encoding="utf-8")
            aged += 1
    assert aged == 1
    ingest.fetch_schedules([SEASON], cache_dir=tmp_path, max_age_seconds=900)
    assert len(fetches) == 2, key
    # cache_only never fetches, whatever the max age.
    ingest.fetch_schedules([SEASON], cache_dir=tmp_path, cache_only=True, max_age_seconds=1)
    assert len(fetches) == 2
    assert json.dumps(first)
