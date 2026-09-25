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
refreshInProgress); single-flighted on-demand compute.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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

    def test_collector_absent_and_stale_refreshes_on_demand_else_serves_stale(self):
        world = FixtureWorld("real_halftime")
        world.tick()
        much_later = world.clock() + live.COLLECTOR_ABSENT_AFTER_SECONDS + 60
        # On-demand refresh fails (the network seam raises): the stale
        # generation is served, never a blank, and says the refresh failed.
        payload = _serve(now=much_later)
        assert payload["freshness"]["state"] == "stale"
        assert "on_demand_refresh_failed" in payload["freshness"]["reasons"]

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


class TestOnDemand:
    def test_no_generation_computes_on_request_labelled_degraded(self):
        from tests.api.test_matchup_intel import _build, _patch_estimates, _patch_fetch

        with _patch_fetch(), _patch_estimates():
            payload = _build()
        fresh = payload["freshness"]
        assert fresh["servedFrom"] == "request_compute"
        assert fresh["state"] == "degraded"
        assert "no_collector_generation" in fresh["reasons"]
        assert fresh["generationId"] is None

    def test_concurrent_viewers_share_one_on_demand_compute(self):
        from tests.api.test_matchup_intel import _build, _patch_estimates, _patch_fetch

        original = matchup_intel.compute_league_render
        start = threading.Barrier(5)

        def slow(**kwargs):
            time.sleep(0.2)
            return original(**kwargs)

        def request(owner):
            start.wait(timeout=5)
            return _build(owner_id=owner)

        with (
            _patch_fetch(),
            _patch_estimates(),
            mock.patch.object(matchup_intel, "compute_league_render", side_effect=slow) as spy,
            ThreadPoolExecutor(max_workers=5) as pool,
        ):
            owners = ["own-A", "own-B", "own-A", "own-B", "own-A"]
            payloads = list(pool.map(request, owners))
        assert spy.call_count == 1
        assert {p["team"]["ownerId"] for p in payloads} == {"own-A", "own-B"}

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
