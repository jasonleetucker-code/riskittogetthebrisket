"""Game Day U5 — the shared live collector, its persistence and generations.

Every tick here runs the REAL collector (``src/ros/game_day_live.py``) and
the real assembly (``src/api/matchup_intel.py``) with only the network
clients replaced by the captured 2026-09-25 TNF replay fixtures
(``tests/fixtures/game_day/replay/``).  No test touches the network, and
every write lands in the per-test isolated root
(``tests/runtime_data_isolation.py`` redirects ``LIVE_ROOT``).

What is pinned: cadence decisions per phase; append-only observations that
survive a restart (the pre-kickoff weekly baseline in particular); a
generation recomputed only when input CONTENT changes; out-of-order
publication refused; atomic writes; the API serving the generation with a
truthful freshness block (current / partial / degraded / stale,
refreshInProgress); and the non-blocking cold path (Game Day G) — a
PENDING payload inside the cold budget, exactly ONE background compute per
league-week, the next poll served, a failure named and bounded.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

from src.api import matchup_intel
from src.nfl_data.live_game_state import parse_scoreboard
from src.nfl_data.sleeper_live_stats import parse_week_stats
from src.ros import game_day_live as live
from src.ros import game_day_sim
from src.ros.sleeper_weekly_projections import FetchResult
from tests.game_day.test_game_day_replay import (
    PLAYERS,
    PRE_KICKOFF_FETCH,
    REAL_FETCH,
    REPLAY,
    SEASON,
    WEEK,
    _json,
    _scenario,
    _schedule_rows,
)

DRAWS = 200
SEED = game_day_sim.DEFAULT_SEED
TNF_KICKOFF = datetime(2026, 9, 25, 0, 15, tzinfo=timezone.utc).timestamp()
LEAGUES = {
    "dynasty_main": _json(REPLAY / "shared" / "dynasty_main_league.json"),
    "dynasty_new": _json(REPLAY / "shared" / "dynasty_new_league.json"),
}
SID_TO_KEY = {str(v["league_id"]): k for k, v in LEAGUES.items()}


@pytest.fixture(autouse=True)
def _hermetic_sim_cache():
    tmp = tempfile.mkdtemp(prefix="game_day_live_sim_cache_")
    original = game_day_sim._SIM_CACHE_ROOT
    game_day_sim._SIM_CACHE_ROOT = Path(tmp)
    live._generation_cache.clear()
    yield
    game_day_sim._SIM_CACHE_ROOT = original
    live._generation_cache.clear()
    shutil.rmtree(tmp, ignore_errors=True)


class Clock:
    def __init__(self, ts: float):
        self.ts = float(ts)

    def __call__(self) -> float:
        return self.ts


def _pregame_espn(espn: dict) -> dict:
    """The capture's ESPN payload with every game rewritten to SCHEDULED
    (labelled synthetic: no capture predates the TNF kickoff)."""
    out = json.loads(json.dumps(espn))
    for event in out["events"]:
        comp = event["competitions"][0]
        for c in comp["competitors"]:
            c["score"] = "0"
        comp["status"] = {
            "clock": 0.0,
            "displayClock": "0:00",
            "period": 0,
            "type": {
                "completed": False,
                "name": "STATUS_SCHEDULED",
                "shortDetail": "scheduled",
                "state": "pre",
            },
        }
    return out


class FixtureWorld:
    """A mutable fake of every external source the collector reads."""

    def __init__(self, scenario: str, *, now: float | None = None):
        self.set_scenario(scenario)
        self.clock = Clock(now if now is not None else self.captured_at)
        self.weekly_result: FetchResult = REAL_FETCH
        self.espn_error: str | None = None
        self.espn_override: dict | None = None
        self.calls: list[str] = []
        self.matchup_edits: dict[tuple[str, int], float] = {}

    def set_scenario(self, name: str) -> None:
        self.sc = _scenario(name)
        self.captured_at = datetime.fromisoformat(self.sc["meta"]["capturedAt"]).timestamp()

    def _matchups(self, key: str) -> list[dict]:
        rows = json.loads(json.dumps(self.sc["matchups"].get(key) or []))
        for row in rows:
            bump = self.matchup_edits.get((key, int(row["roster_id"])))
            if bump is not None:
                row["points"] = float(row.get("points") or 0.0) + bump
        return rows

    def clients(self) -> live.Clients:
        def league(sid):
            self.calls.append(f"league:{sid}")
            return LEAGUES[SID_TO_KEY[sid]]

        def rosters(sid):
            self.calls.append(f"rosters:{sid}")
            return [
                {
                    "roster_id": m["roster_id"],
                    "owner_id": f"owner-{m['roster_id']}",
                    "players": m["players"],
                }
                for m in self._matchups(SID_TO_KEY[sid])
            ]

        def matchups(sid, week):
            self.calls.append(f"matchups:{sid}")
            return self._matchups(SID_TO_KEY[sid])

        def scoreboard(season, week):
            self.calls.append("espn")
            now_dt = datetime.fromtimestamp(self.clock(), tz=timezone.utc)
            if self.espn_error:
                return parse_scoreboard(None, observed_at=now_dt, error=self.espn_error)
            espn = self.espn_override if self.espn_override is not None else self.sc["espn"]
            return parse_scoreboard(espn, observed_at=now_dt - timedelta(seconds=5))

        def live_stats(season, week):
            self.calls.append("live_stats")
            # Labelled synthetic: the captures hold host matchup points, not
            # the v1 stat dump, so a small stat line per scored player stands in.
            payload = {
                pid: {"pts_ppr": float(pts)}
                for m in self._matchups("dynasty_main")
                for pid, pts in (m.get("players_points") or {}).items()
            }
            return parse_week_stats(
                payload,
                season=season,
                week=week,
                observed_at=datetime.fromtimestamp(self.clock(), tz=timezone.utc),
            )

        def weekly(season, week):
            self.calls.append("weekly")
            return self.weekly_result

        def schedule(season):
            return _schedule_rows(self.sc["espn"]), self.captured_at - 3600.0, self.clock()

        return live.Clients(
            nfl_state=lambda: {"season": str(SEASON), "week": WEEK, "season_type": "regular"},
            league=league,
            users=lambda sid: [],
            rosters=rosters,
            matchups=matchups,
            nfl_players=lambda: PLAYERS,
            scoreboard=scoreboard,
            live_stats=live_stats,
            weekly=weekly,
            schedule=schedule,
            preseason=lambda season, card: ({}, None, (), ()),
            leagues=lambda: [
                live.LeagueTarget(k, str(v["league_id"]), {}) for k, v in LEAGUES.items()
            ],
        )

    def tick(self, **kw) -> live.TickReport:
        return live.run_tick(
            clients=self.clients(), clock=self.clock, force=True, draws=DRAWS, seed=SEED, **kw
        )


def _restart() -> None:
    """What a process restart loses: every in-process cache."""
    live._generation_cache.clear()
    live._weekly_history_cache.clear()
    matchup_intel._weekly_memo.clear()
    matchup_intel._live_state_memo.clear()


def _serve(key="dynasty_main", owner="owner-4", *, now=None, fetch_error=True):
    """build_matchup_intel with the request-path network seams made to fail
    loudly, so any payload returned was SERVED, not computed."""
    league = LEAGUES[key]
    patches = []
    if fetch_error:
        patches.append(
            mock.patch.object(
                matchup_intel, "_fetch_league_week", side_effect=AssertionError("network")
            )
        )
    if now is not None:
        patches.append(mock.patch.object(live.time, "time", return_value=now))
    for p in patches:
        p.start()
    try:
        return matchup_intel.build_matchup_intel(
            league_key=key,
            sleeper_league_id=str(league["league_id"]),
            owner_id=owner,
            season=SEASON,
            week=WEEK,
            draws=DRAWS,
            seed=SEED,
        )
    finally:
        for p in reversed(patches):
            p.stop()


# ── Cadence ──────────────────────────────────────────────────────────────


def _w(gid, kickoff, state):
    return live.GameWindow(game_id=gid, kickoff_at=kickoff, state=state)


class TestCadence:
    NOW = 1_800_000_000.0

    def test_a_live_game_ticks_every_minute_and_goes_stale_after_three(self):
        d = live.decide_cadence([_w("g", self.NOW - 600, "in_progress")], self.NOW)
        assert (d.phase, d.interval_seconds) == ("live", 60.0)
        assert d.stale_after_seconds == 180.0
        assert d.next_due_at == self.NOW + 60.0

    def test_a_passed_kickoff_with_no_observed_final_is_treated_live(self):
        d = live.decide_cadence([_w("g", self.NOW - 60, "unknown")], self.NOW)
        assert d.phase == "live"

    def test_near_kickoff_is_every_few_minutes(self):
        d = live.decide_cadence([_w("g", self.NOW + 1800, "not_started")], self.NOW)
        assert (d.phase, d.interval_seconds) == ("near_kickoff", 180.0)

    def test_idle_is_hourly_but_wakes_for_the_near_window_and_the_kickoff(self):
        kick = self.NOW + 3 * 3600
        d = live.decide_cadence([_w("g", kick, "not_started")], self.NOW)
        assert (d.phase, d.interval_seconds) == ("idle", 3600.0)
        assert d.next_due_at == self.NOW + 3600.0
        kick = self.NOW + 7000  # the near window opens in 1600 s, before the hour
        d = live.decide_cadence([_w("g", kick, "not_started")], self.NOW)
        assert d.next_due_at == kick - live.NEAR_KICKOFF_WINDOW_SECONDS

    def test_a_finished_week_is_idle(self):
        d = live.decide_cadence([_w("g", self.NOW - 20000, "completed")], self.NOW)
        assert d.phase == "idle" and d.next_kickoff_at is None

    def test_no_observed_windows_is_unknown_not_idle(self):
        """Schedule cache AND scoreboard unavailable: games may be live
        unobserved, so the collector keeps polling and keeps collecting
        projections rather than going hourly."""
        d = live.decide_cadence([], self.NOW)
        assert (d.phase, d.interval_seconds) == ("unknown", 180.0)
        assert live.weekly_projection_due(None, [], self.NOW) == (True, "kickoffs_unknown")
        assert live.weekly_projection_due(self.NOW - 60, [], self.NOW)[0] is False
        assert live.live_stats_due(self.NOW - 30, [], self.NOW)[0] is True

    def test_weekly_projections_only_while_a_kickoff_is_ahead(self):
        now = self.NOW
        assert live.weekly_projection_due(None, [_w("g", now - 1, "in_progress")], now) == (
            False,
            "no_upcoming_kickoff",
        )
        kick = now + 5 * 3600
        ahead = [_w("g", kick, "not_started")]
        assert live.weekly_projection_due(None, ahead, now)[0] is True
        assert live.weekly_projection_due(now - 3600, ahead, now)[0] is False
        assert live.weekly_projection_due(now - 3 * 3600, ahead, now)[0] is True

    def test_one_fetch_is_forced_inside_the_final_window_before_kickoff(self):
        kick = self.NOW + 300  # 5 min out
        ahead = [_w("g", kick, "not_started")]
        # Last fetch 9 min ago is recent by the near-kickoff interval, but it
        # predates the final window, so one more is forced.
        due, why = live.weekly_projection_due(self.NOW - 540, ahead, self.NOW)
        assert (due, why) == (True, "pre_kickoff_final_window")
        # Once one is inside the window, no more are forced.
        assert live.weekly_projection_due(self.NOW - 60, ahead, self.NOW)[0] is False

    def test_live_stats_every_tick_while_live_hourly_after(self):
        now = self.NOW
        assert live.live_stats_due(now - 30, [_w("g", now - 600, "in_progress")], now)[0]
        done = [_w("g", now - 20000, "completed")]
        assert live.live_stats_due(now - 600, done, now)[0] is False
        assert live.live_stats_due(now - 4000, done, now)[0] is True
        assert live.live_stats_due(None, [_w("g", now + 600, "not_started")], now)[0] is False


# ── Observation log ──────────────────────────────────────────────────────


class TestKeyedObservationLog:
    def _log(self):
        return live.observation_log("_t", 2026, 1, "src")

    def test_every_appended_observation_reconstructs_exactly(self):
        log = self._log()
        contents = [
            {"a": 1, "b": {"x": 1}},
            {"a": 1, "b": {"x": 1}},  # unchanged
            {"a": 2, "b": {"x": 1}, "c": 3},  # delta set
            {"a": 2, "c": 3},  # delta drop
        ]
        kinds = [
            log.append(fetched_at=f"t{i}", status="ok", meta={"i": i}, content=c)["kind"]
            for i, c in enumerate(contents)
        ]
        log.append(fetched_at="t4", status="error", meta={"error": "boom"}, content=None)
        assert kinds == ["keyframe", "unchanged", "delta", "delta"]
        got = log.observations()
        assert [dict(o.content) for o in got] == contents
        assert [o.fetched_at for o in got] == ["t0", "t1", "t2", "t3"]
        failures = [o for o in log.observations(ok_only=False) if o.status != "ok"]
        assert failures[0].meta["error"] == "boom" and failures[0].content is None
        # The head survives a failure with the last good content.
        head = log.head()
        assert head["content"] == contents[-1] and head["lastOkFetchedAt"] == "t3"

    def test_the_log_is_append_only(self):
        log = self._log()
        log.append(fetched_at="t0", status="ok", meta={}, content={"a": 1})
        first = log.log_path.read_bytes()
        log.append(fetched_at="t1", status="ok", meta={}, content={"a": 2})
        assert log.log_path.read_bytes().startswith(first)

    def test_a_lost_head_is_rebuilt_from_the_log(self):
        log = self._log()
        for i in range(3):
            log.append(fetched_at=f"t{i}", status="ok", meta={}, content={"a": i})
        log.head_path.unlink()
        assert log.head()["content"] == {"a": 2}
        # A head that lags the log (crash between append and head write) too.
        log.append(fetched_at="t3", status="ok", meta={}, content={"a": 3})
        live._atomic_write_json(log.head_path, {"seq": 1, "content": {"a": 0}})
        assert log.head()["content"] == {"a": 3}
        info = log.append(fetched_at="t4", status="ok", meta={}, content={"a": 3, "b": 1})
        assert info["kind"] == "delta"
        assert dict(log.observations()[-1].content) == {"a": 3, "b": 1}

    def test_a_torn_trailing_write_is_cut_back_not_glued_onto(self):
        log = self._log()
        log.append(fetched_at="t0", status="ok", meta={}, content={"a": 1})
        with log.log_path.open("a", encoding="utf-8") as fh:
            fh.write('{"v":1,"seq":2,"kind":"del')  # crash mid-line
        log.append(fetched_at="t1", status="ok", meta={}, content={"a": 2})
        assert [dict(o.content) for o in log.observations()] == [{"a": 1}, {"a": 2}]

    def test_a_keyframe_larger_than_any_read_block_is_still_the_head(self):
        """Measured on the real projections feed: one keyframe line is
        several MB.  The head must still be found (a missed head made every
        tick look like the first and re-fetch)."""
        log = self._log()
        big = {f"p{i}": {"stat": i, "pad": "x" * 200} for i in range(8000)}  # ~2 MB line
        log.append(fetched_at="t0", status="ok", meta={}, content=big)
        log.head_path.unlink()
        head = log.head()
        assert head is not None and head["seq"] == 1 and head["lastOkFetchedAt"] == "t0"
        assert log.append(fetched_at="t1", status="ok", meta={}, content=big)["kind"] == (
            "unchanged"
        )

    def test_a_damaged_delta_breaks_only_its_segment(self, monkeypatch):
        monkeypatch.setattr(live, "KEYFRAME_EVERY", 3)
        log = self._log()
        for i in range(6):
            log.append(fetched_at=f"t{i}", status="ok", meta={}, content={"a": i})
        lines = log.log_path.read_text(encoding="utf-8").splitlines()
        lines[1] = "{not json"
        log.log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        got = [dict(o.content)["a"] for o in log.observations()]
        # seq 2 lost; seq 3 (a delta on the lost base) refused; the keyframe
        # at seq 4 restores the chain.
        assert got == [0, 3, 4, 5]


# ── Collector ticks ──────────────────────────────────────────────────────


class TestCollectorTick:
    def test_a_tick_publishes_one_generation_per_league_week(self):
        world = FixtureWorld("real_halftime")
        report = world.tick()
        assert report.outcome == "ran" and report.exit_code == 0, report
        for key in LEAGUES:
            assert report.leagues[key]["outcome"] == "generation_written"
            gen = live.load_generation(key, SEASON, WEEK)
            assert gen["producer"] == live.PRODUCER
            assert gen["modelVersion"] == game_day_sim.MODEL_VERSION
            assert gen["inputFingerprint"] and gen["generationId"]
            assert set(gen["inputs"]["sources"]) >= {
                "espnScoreboard",
                "sleeperLeague",
                "weeklyProjections",
                "nflverseSchedule",
                "sleeperLiveStats",
            }
            assert gen["resolved"]["mode"] == "live"
            assert gen["render"]["sides"]
        # Bounded: every request is counted, and within the cap.
        assert 0 < len(report.requests) <= live.MAX_REQUESTS_PER_TICK
        assert report.cadence["phase"] == "live"

    def test_the_served_payload_equals_a_direct_request_build(self):
        """A generation is the SAME answer the request path computes from the
        same inputs — one assembly, two producers."""
        world = FixtureWorld("real_halftime")
        world.tick()
        gen = live.load_generation("dynasty_main", SEASON, WEEK)
        served = matchup_intel.compose_team_payload(gen["render"], owner_id="owner-4")

        # The same inputs through the request-path assembly.
        clients = world.clients()
        fetched = matchup_intel._LeagueFetch(
            league=LEAGUES["dynasty_main"],
            users=[],
            rosters=clients.rosters(str(LEAGUES["dynasty_main"]["league_id"])),
            matchups=clients.matchups(str(LEAGUES["dynasty_main"]["league_id"]), WEEK),
            players=live.load_players_meta(lambda: {}, set(), now=world.clock())[0],
            fetched_at=world.clock(),
        )
        weekly = [
            live.weekly_from_observation(o)
            for o in live.observation_log(
                live.NFL_KEY, SEASON, WEEK, live.SOURCE_WEEKLY
            ).observations()
        ]
        head = live.observation_log(live.NFL_KEY, SEASON, WEEK, live.SOURCE_ESPN).head()
        inputs = matchup_intel.LiveInputs(
            fetched=fetched,
            schedule_rows=_schedule_rows(world.sc["espn"]),
            schedule_observed_at=world.captured_at - 3600.0,
            now=world.clock(),
            live_snapshot=live.scoreboard_from_observation(head["meta"], head["content"]),
            weekly_fetches=tuple(weekly),
            weekly_state="ok",
            weekly_reason=None,
            preseason=({}, None, (), ()),
        )
        assembly = matchup_intel.assemble_league_week(
            inputs, league_key="dynasty_main", season=SEASON, week=WEEK
        )
        matchup_intel.run_league_simulation(assembly, draws=DRAWS, seed=SEED)
        direct = matchup_intel.compose_team_payload(
            matchup_intel.render_league(assembly), owner_id="owner-4"
        )
        strip = live._strip_volatile
        assert strip(served) == strip(direct)

    def test_an_unchanged_poll_recomputes_nothing(self):
        world = FixtureWorld("real_halftime")
        world.tick()
        path = live.generation_path("dynasty_main", SEASON, WEEK)
        before = path.read_bytes()
        world.clock.ts += 60
        with mock.patch.object(
            matchup_intel,
            "get_cached_league_week_simulation",
            side_effect=AssertionError("simulated an unchanged league-week"),
        ):
            report = world.tick()
        assert {v["outcome"] for v in report.leagues.values()} == {"inputs_unchanged"}
        assert path.read_bytes() == before
        state = live.load_league_state("dynasty_main", SEASON, WEEK)
        assert live._epoch(state["lastVerifiedAt"]) == world.clock()

    def test_a_scored_point_publishes_a_new_generation(self):
        world = FixtureWorld("real_halftime")
        world.tick()
        first = live.load_generation("dynasty_main", SEASON, WEEK)["generationId"]
        world.clock.ts += 60
        world.set_scenario("real_q3_in_progress")
        report = world.tick()
        assert report.leagues["dynasty_main"]["outcome"] == "generation_written"
        gen = live.load_generation("dynasty_main", SEASON, WEEK)
        assert gen["generationId"] != first
        assert gen["sequence"] == world.clock()

    def test_restart_after_kickoff_keeps_the_pre_kickoff_baseline(self):
        """U4's gap: the weekly memo lived in memory, so a restart after
        kickoff dropped every TNF player to the preseason fallback.  The
        pre-kickoff fetch is now an observation on disk."""
        world = FixtureWorld("real_halftime", now=TNF_KICKOFF - 300)
        world.espn_override = _pregame_espn(world.sc["espn"])
        world.weekly_result = PRE_KICKOFF_FETCH
        world.tick()

        _restart()
        world.clock.ts = world.captured_at
        world.espn_override = None
        world.weekly_result = REAL_FETCH
        world.tick()

        gen = live.load_generation("dynasty_main", SEASON, WEEK)
        payload = matchup_intel.compose_team_payload(gen["render"], owner_id="owner-4")
        tnf = [
            p
            for side in ("team", "opponent")
            for p in payload[side]["players"]
            if p["nflGameId"] and "ATL" in p["nflGameId"]
        ]
        assert tnf, "fixture must hold a TNF player in this matchup"
        weekly = {
            p["playerId"] for p in tnf if p["projectionBasis"] == "weekly:rotowire_via_sleeper"
        }
        # The restarted collector locks exactly the baselines an
        # uninterrupted process holding both fetches in memory locks (the
        # U4 replay path), and no TNF player falls back to a guess.
        from tests.game_day.test_game_day_replay import _run

        uninterrupted = _run("real_halftime", fetches=(PRE_KICKOFF_FETCH, REAL_FETCH)).payload
        expected = {
            p["playerId"]
            for side in ("team", "opponent")
            for p in uninterrupted[side]["players"]
            if p["nflGameId"]
            and "ATL" in p["nflGameId"]
            and p["projectionBasis"] == "weekly:rotowire_via_sleeper"
        }
        assert weekly and weekly == expected
        cov = gen["inputs"]["preKickoffCoverage"]
        tnf_game = next(g for g in cov["games"] if "ATL" in g)
        assert cov["games"][tnf_game]["leadSeconds"] == pytest.approx(300.0, abs=10.0)

    def test_without_a_pre_kickoff_observation_tnf_players_have_no_weekly_baseline(self):
        world = FixtureWorld("real_halftime")
        world.tick()
        gen = live.load_generation("dynasty_main", SEASON, WEEK)
        payload = matchup_intel.compose_team_payload(gen["render"], owner_id="owner-4")
        tnf = [
            p
            for side in ("team", "opponent")
            for p in payload[side]["players"]
            if p["nflGameId"] and "ATL" in p["nflGameId"]
        ]
        assert tnf and all(p["projectionBasis"] is None for p in tnf)
        assert "ATL" in " ".join(
            gen["inputs"]["preKickoffCoverage"]["gamesWithoutPreKickoffObservation"]
        )

    def test_a_failed_scoreboard_read_uses_the_last_good_one_at_its_true_age(self):
        world = FixtureWorld("real_halftime")
        world.tick()
        world.clock.ts += 400  # older than LIVE_STATE_MAX_AGE_SECONDS
        world.espn_error = "fetch_failed:TimeoutError"
        world.matchup_edits[("dynasty_main", 4)] = 0.5  # force a new generation
        report = world.tick()
        assert report.sources[live.SOURCE_ESPN]["status"] == "stale_last_good"
        gen = live.load_generation("dynasty_main", SEASON, WEEK)
        assert gen["inputs"]["sources"]["espnScoreboard"]["status"] == "stale_last_good"
        # The resolver saw it as stale evidence, never as a fresh read.
        assert gen["render"]["lineage"]["liveGameState"]["stale"] is True

    def test_repeated_failures_back_off_across_runs(self):
        world = FixtureWorld("real_halftime")
        world.espn_error = "fetch_failed:TimeoutError"
        for _ in range(live.BACKOFF_FAILURE_THRESHOLD):
            world.tick()
            world.clock.ts += 10
        world.calls.clear()
        world.tick()
        assert "espn" not in world.calls
        health = live.load_collector_state()["sourceHealth"][live.SOURCE_ESPN]
        assert health["consecutiveFailures"] == live.BACKOFF_FAILURE_THRESHOLD

    def test_not_due_and_locked_ticks_do_nothing(self):
        world = FixtureWorld("real_halftime")
        world.tick()
        report = live.run_tick(clients=world.clients(), clock=world.clock, draws=DRAWS, seed=SEED)
        assert (report.outcome, report.exit_code) == ("not_due", 2)
        assert live._acquire_lock(world.clock())
        try:
            report = world.tick()
            assert (report.outcome, report.exit_code) == ("locked", 2)
        finally:
            live._release_lock()

    def test_an_abandoned_lock_is_taken_over(self):
        world = FixtureWorld("real_halftime")
        assert live._acquire_lock(world.clock() - live.LOCK_STALE_SECONDS - 5)
        assert world.tick().outcome == "ran"

    def test_one_league_failing_does_not_sink_the_other(self):
        world = FixtureWorld("real_halftime")
        clients = world.clients()
        real_rosters = clients.rosters
        new_sid = str(LEAGUES["dynasty_new"]["league_id"])
        clients.rosters = lambda sid: [] if sid == new_sid else real_rosters(sid)
        report = live.run_tick(
            clients=clients, clock=world.clock, force=True, draws=DRAWS, seed=SEED
        )
        assert report.exit_code == 1
        assert report.leagues["dynasty_main"]["outcome"] == "generation_written"
        assert report.leagues["dynasty_new"]["outcome"] == "error"
        state = live.load_league_state("dynasty_new", SEASON, WEEK)
        assert state["lastTickOk"] is False and state["refreshStartedAt"] is None

    def test_out_of_season_is_nothing_to_do(self):
        world = FixtureWorld("real_halftime")
        clients = world.clients()
        clients.nfl_state = lambda: {"season": "2026", "week": 1, "season_type": "pre"}
        report = live.run_tick(clients=clients, clock=world.clock, force=True)
        assert (report.outcome, report.exit_code) == ("out_of_season", 2)


# ── Generation publication ───────────────────────────────────────────────


class TestGenerationWrites:
    def _gen(self, seq: float, marker: str = "x") -> dict:
        return {
            "schemaVersion": live.GENERATION_SCHEMA_VERSION,
            "generationId": f"g-{seq}-{marker}",
            "leagueKey": "lk",
            "season": 2026,
            "week": 1,
            "sequence": seq,
            "render": {"shared": {"mode": "live"}, "sides": {}},
        }

    def test_an_older_tick_never_replaces_a_newer_generation(self):
        assert live.write_generation(self._gen(200.0, "new"))
        assert not live.write_generation(self._gen(100.0, "old"))
        assert not live.write_generation(self._gen(200.0, "same-seq"))
        assert live.load_generation("lk", 2026, 1)["generationId"] == "g-200.0-new"
        index = live._generation_index_path("lk", 2026, 1).read_text().splitlines()
        assert len(index) == 1

    def test_a_failed_publication_keeps_the_previous_generation_and_no_tempfile(self):
        live.write_generation(self._gen(100.0, "kept"))
        path = live.generation_path("lk", 2026, 1)
        before = path.read_bytes()
        with mock.patch.object(Path, "replace", side_effect=OSError("disk failure")):
            with pytest.raises(OSError):
                live.write_generation(self._gen(200.0, "lost"))
        assert path.read_bytes() == before
        assert not list(path.parent.glob("*.tmp"))


# ── Serving (the API path) ───────────────────────────────────────────────


class TestServing:
    def test_the_api_serves_the_generation_without_any_network(self):
        world = FixtureWorld("real_halftime")
        world.tick()
        payload = _serve(now=world.clock() + 20)
        fresh = payload["freshness"]
        assert fresh["servedFrom"] == "collector_generation"
        assert fresh["state"] == "current", fresh["reasons"]
        assert (
            fresh["generationId"]
            == live.load_generation("dynasty_main", SEASON, WEEK)["generationId"]
        )
        assert fresh["payloadAgeSeconds"] == pytest.approx(20.0, abs=1.0)
        assert fresh["phase"] == "live" and fresh["staleAfterSeconds"] == 180.0
        assert fresh["refreshInProgress"] is False
        espn = fresh["sources"]["espnScoreboard"]
        assert espn["status"] == "ok" and espn["fetchedAt"] and espn["observedAt"]
        assert fresh["sources"]["sleeperLeague"]["fetchedAt"]
        assert payload["team"]["rosterId"] == "4"

    def test_a_stale_generation_is_served_with_its_true_age_while_the_collector_runs(self):
        world = FixtureWorld("real_halftime")
        world.tick()
        gen_id = live.load_generation("dynasty_main", SEASON, WEEK)["generationId"]
        later = world.clock() + 600  # collector ticked 10 min ago: still active
        payload = _serve(now=later)
        fresh = payload["freshness"]
        assert fresh["state"] == "stale"
        assert fresh["generationId"] == gen_id
        assert fresh["payloadAgeSeconds"] == pytest.approx(600.0, abs=1.0)
        assert payload["team"]["players"], "stale is served, never blanked"

    def test_refresh_in_progress_is_reported(self):
        world = FixtureWorld("real_halftime")
        world.tick()
        state = live.load_league_state("dynasty_main", SEASON, WEEK)
        state["refreshStartedAt"] = live._iso(world.clock() + 5)
        live._save_league_state("dynasty_main", SEASON, WEEK, state)
        assert live._acquire_lock(world.clock() + 5)
        try:
            with mock.patch.object(live.time, "time", return_value=world.clock() + 10):
                fresh = live._generation_freshness(
                    live.load_generation("dynasty_main", SEASON, WEEK),
                    live.load_league_state("dynasty_main", SEASON, WEEK),
                    world.clock() + 10,
                )
        finally:
            live._release_lock()
        assert fresh["refreshInProgress"] is True and fresh["refreshStartedAt"]

    def test_collector_absent_and_stale_is_served_at_once_and_refreshed_in_background(self):
        world = FixtureWorld("real_halftime")
        world.tick()
        gen_id = live.load_generation("dynasty_main", SEASON, WEEK)["generationId"]
        much_later = world.clock() + live.COLLECTOR_ABSENT_AFTER_SECONDS + 60
        # The background refresh fails (the network seam raises): the stale
        # generation is served immediately both times, never a blank, and
        # the second read names the failure.
        with mock.patch.object(
            matchup_intel, "_fetch_league_week", side_effect=RuntimeError("network down")
        ):
            first = _serve(now=much_later, fetch_error=False)
            assert live.wait_for_background(timeout=60)
            second = _serve(now=much_later, fetch_error=False)
        fresh = first["freshness"]
        assert fresh["state"] == "stale" and fresh["generationId"] == gen_id
        assert fresh["refreshInProgress"] is True
        assert "background_refresh_running" in fresh["reasons"]
        assert fresh["backgroundCompute"]["reason"] == "collector_absent_generation_stale"
        fresh = second["freshness"]
        assert fresh["state"] == "stale" and fresh["generationId"] == gen_id
        assert "background_refresh_failed:RuntimeError: network down" in fresh["reasons"]
        assert fresh["backgroundCompute"]["outcome"] == "failed"
        assert second["team"]["players"] and second["team"]["outcome"], "stale, never blanked"

    def test_partial_when_the_live_feed_is_unavailable_during_games(self):
        world = FixtureWorld("real_halftime")
        world.espn_error = "http_error:503"
        world.tick()
        fresh = _serve(now=world.clock() + 5)["freshness"]
        assert fresh["state"] == "partial"
        assert any(r.startswith("live_game_state:") for r in fresh["reasons"])

    def test_a_different_owner_reads_the_same_generation(self):
        world = FixtureWorld("real_halftime")
        world.tick()
        a = _serve(owner="owner-4", now=world.clock() + 5)
        b = _serve(owner=f"owner-{a['opponent']['rosterId']}", now=world.clock() + 5)
        assert a["freshness"]["generationId"] == b["freshness"]["generationId"]
        assert a["team"]["outcome"]["winMatchupPct"] + a["opponent"]["outcome"]["winMatchupPct"] + (
            a["team"]["outcome"]["tieMatchupPct"] or 0.0
        ) == pytest.approx(100.0, abs=0.01)
        assert b["team"]["rosterId"] == a["opponent"]["rosterId"]

    def test_an_owner_not_in_the_generation_is_refused(self):
        world = FixtureWorld("real_halftime")
        world.tick()
        with pytest.raises(matchup_intel.TeamNotInLeague):
            _serve(owner="nobody", now=world.clock() + 5)


#: The endpoint's cold budget: docs/GLOBAL_PERFORMANCE_STANDARD.md §2
#: ("cold/uncached supported path: <=3 seconds"; no route-specific budget
#: exists for /api/matchup-intel).  The pending path measures ~0.1 s on the
#: real replay; the full simulation it no longer waits for is 24-45 s.
COLD_BUDGET_SECONDS = 3.0


@contextmanager
def _replay_seams(scenario: str = "real_halftime", *, clock_offset: float = 1.0, held=True):
    """The request path's network seams replaced by the REAL replay capture
    (as ``test_game_day_replay._run`` does), the wall clock pinned just after
    the capture, and — when ``held`` — that capture's scoreboard as the
    observation already held (memo / collector), so the pending payload and
    the background compute read the same game states."""
    from tests.game_day.test_game_day_replay import REPLAY, _scenario

    sc = _scenario(scenario)
    league = LEAGUES["dynasty_main"]
    matchups = sc["matchups"]["dynasty_main"]
    now_dt = datetime.fromisoformat(sc["meta"]["capturedAt"])
    now = now_dt.timestamp()
    fetched = matchup_intel._LeagueFetch(
        league=league,
        users=[],
        rosters=[
            {
                "roster_id": m["roster_id"],
                "owner_id": f"owner-{m['roster_id']}",
                "players": m["players"],
            }
            for m in matchups
        ],
        matchups=matchups,
        players=PLAYERS,
        fetched_at=now,
    )
    snapshot = parse_scoreboard(sc["espn"], observed_at=now_dt - timedelta(seconds=30))
    assert (REPLAY / scenario).is_dir()
    with (
        mock.patch.object(matchup_intel, "_fetch_league_week", return_value=fetched),
        mock.patch.object(
            matchup_intel,
            "_schedule_context",
            return_value=(_schedule_rows(sc["espn"]), now - 3600.0, now),
        ),
        mock.patch.object(matchup_intel, "_observe_live_state", return_value=snapshot),
        mock.patch.object(
            matchup_intel, "peek_live_state", return_value=snapshot if held else None
        ),
        mock.patch.object(
            matchup_intel,
            "_weekly_projection_fetches",
            return_value=((PRE_KICKOFF_FETCH, REAL_FETCH), "ok", None),
        ),
        mock.patch.object(matchup_intel, "_resolve_estimates", return_value=({}, None, (), ())),
        mock.patch.object(live.time, "time", return_value=now + clock_offset),
    ):
        yield league


def _cold_build(league: dict, *, week: int = WEEK, owner: str = "owner-4") -> dict:
    return matchup_intel.build_matchup_intel(
        league_key="dynasty_main",
        sleeper_league_id=str(league["league_id"]),
        owner_id=owner,
        season=SEASON,
        week=week,
        draws=DRAWS,
        seed=SEED,
    )


def _slots(side: dict) -> list[tuple]:
    return [(s["slotIndex"], s["playerId"], s["points"]) for s in side["actualLineup"]["slots"]]


class TestColdRequest:
    """Game Day G: no usable generation never blocks a request on the
    simulation — PENDING now, ONE background compute, the next poll serves."""

    def test_a_cold_request_answers_pending_inside_the_budget_without_simulating(self):
        gate = threading.Event()
        sim_threads: list[threading.Thread] = []
        real_sim = matchup_intel.get_cached_league_week_simulation

        def gated(**kwargs):
            sim_threads.append(threading.current_thread())
            assert gate.wait(timeout=120)
            return real_sim(**kwargs)

        with (
            _replay_seams() as league,
            mock.patch.object(
                matchup_intel, "get_cached_league_week_simulation", side_effect=gated
            ),
        ):
            started = time.perf_counter()
            try:
                pending = _cold_build(league)
                elapsed = time.perf_counter() - started
            finally:
                gate.set()
            assert live.wait_for_background(timeout=300)
            served = _cold_build(league)

        assert elapsed < COLD_BUDGET_SECONDS, elapsed
        fresh = pending["freshness"]
        assert fresh["state"] == "pending"
        assert fresh["reasons"][0] == "generation_pending"
        assert fresh["servedFrom"] == "pending_factual"
        assert fresh["generationId"] is None and fresh["simulationComputedAt"] is None
        assert fresh["refreshInProgress"] is True
        assert fresh["backgroundCompute"]["triggered"] is True
        assert fresh["backgroundCompute"]["reason"] == "no_collector_generation"
        # Forecast WITHHELD — named, never zero, never "unpriced".
        assert pending["probabilityState"] == "PENDING"
        for side in ("team", "opponent"):
            s = pending[side]
            assert s["outcome"] is None and s["expectedLineup"] is None
            assert s["unpricedPlayerIds"] is None and s["uncoveredScoringKeys"] is None
            assert all(p["projectedRemaining"] is None for p in s["players"])
            assert all(p["finalLineupPct"] is None for p in s["players"])
        assert pending["lineage"]["estimateCoverage"] is None
        assert pending["lineage"]["projectionFamiliesContributing"] is None
        assert any(n.startswith("PENDING:") for n in pending["notes"])
        # The FACTS are there: league/team/opponent context, host scores and
        # the banked best-ball lineup from the exact lineup owner — identical
        # to what the computed generation then says.
        assert pending["team"]["rosterId"] == "4" and pending["opponent"]["rosterId"]
        for side in ("team", "opponent"):
            assert pending[side]["actualScore"] == served[side]["actualScore"]
            assert pending[side]["scoreNow"] == served[side]["scoreNow"]
            assert _slots(pending[side]) == _slots(served[side])
            assert pending[side]["actualLineup"]["owner"] == "src/ros/lineup.py"
        # The simulation ran, once, and never on the request thread.
        assert sim_threads and all(t is not threading.main_thread() for t in sim_threads)
        assert all(t.name.startswith("game-day-compute:") for t in sim_threads)
        # The next poll serves the generation the background compute wrote.
        fresh = served["freshness"]
        assert fresh["servedFrom"] == "request_generation"
        assert fresh["state"] == "degraded"
        assert "no_collector_generation" in fresh["reasons"]
        gen = live.load_generation("dynasty_main", SEASON, WEEK)
        assert fresh["generationId"] == gen["generationId"]
        assert gen["producer"] == live.PRODUCER_REQUEST
        assert served["probabilityState"] == "AVAILABLE"
        assert served["team"]["outcome"]["winMatchupPct"] is not None

    def test_nothing_held_still_answers_pending_with_the_banked_facts(self):
        """No scoreboard observation held at all: the pending payload says so
        (liveGameState unavailable) and makes no scoreboard request."""
        with (
            _replay_seams(held=False) as league,
            mock.patch.object(
                matchup_intel, "_observe_live_state", side_effect=AssertionError("network")
            ) as observe,
            mock.patch.object(live, "ensure_background_compute", return_value={"state": "running"}),
        ):
            pending = _cold_build(league)
        assert observe.call_count == 0
        assert pending["freshness"]["state"] == "pending"
        assert pending["lineage"]["liveGameState"]["state"] == "unavailable"
        assert pending["team"]["scoreNow"]["hostReportedTotal"] is not None

    def test_concurrent_cold_requests_start_exactly_one_background_compute(self):
        gate = threading.Event()
        calls: list[int] = []
        real = live.compute_request_generation

        def gated(**kwargs):
            calls.append(1)
            assert gate.wait(timeout=120)
            return real(**kwargs)

        barrier = threading.Barrier(6)

        def request(owner):
            barrier.wait(timeout=10)
            return _cold_build(league, owner=owner)

        with (
            _replay_seams() as league,
            mock.patch.object(live, "compute_request_generation", side_effect=gated),
            ThreadPoolExecutor(max_workers=6) as pool,
        ):
            try:
                owners = ["owner-4", "owner-1", "owner-4", "owner-2", "owner-4", "owner-1"]
                payloads = list(pool.map(request, owners))
            finally:
                gate.set()
            assert live.wait_for_background(timeout=300)
            served = [_cold_build(league, owner=o) for o in ("owner-4", "owner-1")]
        assert len(calls) == 1
        assert all(p["freshness"]["state"] == "pending" for p in payloads)
        assert sum(bool(p["freshness"]["backgroundCompute"]["triggered"]) for p in payloads) == 1
        assert {p["team"]["ownerId"] for p in payloads} == {"owner-4", "owner-1", "owner-2"}
        assert len({s["freshness"]["generationId"] for s in served}) == 1

    def test_a_failed_background_compute_is_a_named_state_never_a_number(self):
        with (
            _replay_seams() as league,
            mock.patch.object(
                matchup_intel, "prepare_league_week", side_effect=RuntimeError("feed exploded")
            ),
        ):
            first = _cold_build(league)
            assert live.wait_for_background(timeout=60)
            second = _cold_build(league)
        assert first["freshness"]["state"] == "pending"
        fresh = second["freshness"]
        assert fresh["state"] == "failed"
        assert fresh["reasons"][0] == "generation_failed:RuntimeError: feed exploded"
        assert fresh["backgroundCompute"]["outcome"] == "failed"
        assert fresh["backgroundCompute"]["triggered"] is False
        assert fresh["refreshInProgress"] is False
        assert second["probabilityState"] == "PENDING"
        assert second["team"]["outcome"] is None and second["opponent"]["outcome"] is None
        assert live.load_generation("dynasty_main", SEASON, WEEK) is None
        # Past the retry window the next poll tries again, naming the failure.
        with (
            _replay_seams(clock_offset=1.0 + live.BACKGROUND_RETRY_AFTER_SECONDS + 1) as league,
            mock.patch.object(
                matchup_intel, "prepare_league_week", side_effect=RuntimeError("still down")
            ),
        ):
            third = _cold_build(league)
            assert live.wait_for_background(timeout=60)
        fresh = third["freshness"]
        assert fresh["state"] == "pending" and fresh["backgroundCompute"]["triggered"] is True
        assert "previous_attempt_failed:RuntimeError: feed exploded" in fresh["reasons"]

    def test_background_computes_are_bounded_across_league_weeks(self, monkeypatch):
        monkeypatch.setattr(live, "MAX_BACKGROUND_COMPUTES", 1)
        gate = threading.Event()
        real = live.compute_request_generation

        def gated(**kwargs):
            assert gate.wait(timeout=120)
            return real(**kwargs)

        with (
            _replay_seams() as league,
            mock.patch.object(live, "compute_request_generation", side_effect=gated),
        ):
            try:
                week3 = _cold_build(league, week=WEEK)
                week4 = _cold_build(league, week=WEEK + 1)
            finally:
                gate.set()
            assert live.wait_for_background(timeout=300)
        assert week3["freshness"]["backgroundCompute"]["triggered"] is True
        fresh = week4["freshness"]
        assert fresh["state"] == "pending"
        assert "background_compute_capacity_exhausted" in fresh["reasons"]
        assert fresh["refreshInProgress"] is False

    def test_the_request_seam_merges_the_collectors_persisted_pre_kickoff_fetch(self, monkeypatch):
        """Even the on-demand (no generation) path survives a restart: the
        request seam merges the collector's stored observations with its memo."""
        from src.api import feature_flags

        world = FixtureWorld("real_halftime", now=TNF_KICKOFF - 300)
        world.espn_override = _pregame_espn(world.sc["espn"])
        world.weekly_result = PRE_KICKOFF_FETCH
        world.tick()
        _restart()

        monkeypatch.setenv("RISKIT_FEATURE_SLEEPER_WEEKLY_PROJECTIONS", "1")
        feature_flags.reload()
        try:
            with mock.patch(
                "src.ros.sleeper_weekly_projections.fetch_weekly_projection_rows",
                return_value=REAL_FETCH,
            ):
                fetches, state, _ = matchup_intel._weekly_projection_fetches(
                    SEASON, WEEK, [TNF_KICKOFF]
                )
        finally:
            monkeypatch.undo()
            feature_flags.reload()
        assert state == "ok"
        stamps = sorted(live._epoch(f.observed_at) for f in fetches)
        assert stamps == sorted(live._epoch(f.observed_at) for f in (PRE_KICKOFF_FETCH, REAL_FETCH))


# ── Retention ────────────────────────────────────────────────────────────


def test_retention_prunes_raw_observations_but_keeps_generations():
    old = live.league_week_dir("lk", 2026, 1)
    keep = live.league_week_dir("lk", 2026, 8)
    for d in (old, keep):
        (d / "observations").mkdir(parents=True)
        (d / "observations" / "x.jsonl").write_text("{}\n")
        (d / "generation.json").write_text("{}")
    live.prune_retention(2026, 8)
    assert not (old / "observations").exists()
    assert (old / "generation.json").exists()
    assert (keep / "observations" / "x.jsonl").exists()


def test_the_live_root_never_lives_under_data_ros():
    from tests.runtime_data_isolation import REAL_GAME_DAY_LIVE_DIR

    real = str(REAL_GAME_DAY_LIVE_DIR).replace("\\", "/")
    assert "data/ros" not in real and real.endswith("data/game_day/live")


def test_the_script_exits_two_before_heavy_imports_when_not_due():
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "scripts" / "run_game_day_live.py"
    spec = importlib.util.spec_from_file_location("run_game_day_live", path)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    live._atomic_write_json(
        live.collector_state_path(), {"nextDueAt": live._iso(time.time() + 3600)}
    )
    with mock.patch.object(live, "run_tick", side_effect=AssertionError("ran")):
        assert script.main([]) == 2
