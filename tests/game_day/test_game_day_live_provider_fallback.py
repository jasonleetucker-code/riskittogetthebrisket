"""Game Day collector — live-game-state provider selection (ESPN → SportsDataIO).

Runs the REAL collector tick over the captured 2026-09-25 TNF replay world
(``test_game_day_live_collector.FixtureWorld``).  The SportsDataIO side is
SYNTHETIC: its ``Score`` rows are generated from the captured ESPN slate
(same games, teams and kickoffs, halftime of ATL@GB) in the shape
SportsDataIO documents — no live SportsDataIO response exists in this
repository.  No network: both providers are injected clients.

Pinned: ESPN healthy → SportsDataIO is never called; ESPN failing (403) and
SportsDataIO eligible → SportsDataIO supplies the tick, recorded with its
reason; SportsDataIO ineligible → no request, and the freshness block is
``partial`` naming each provider's own reason; one provider per tick, never
a merge; the last good observation is the NEWEST across providers.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.nfl_data import live_game_state as lgs
from src.nfl_data import sportsdataio_live_game_state as sdio
from src.ros import game_day_live as live
from tests.game_day.test_game_day_live_collector import (
    DRAWS,
    SEASON,
    SEED,
    WEEK,
    FixtureWorld,
    _hermetic_sim_cache,  # noqa: F401 — autouse fixture, re-used
)

_QUARTER = {1: "1", 2: "2", 3: "3", 4: "4", 5: "OT"}


def _sdio_rows_from(espn_snapshot: lgs.ScoreboardSnapshot) -> list[dict]:
    """SYNTHETIC SportsDataIO ``Score`` rows for the same games as ESPN's."""
    rows = []
    for i, g in enumerate(espn_snapshot.games):
        started = g.phase != lgs.PHASE_SCHEDULED
        over = g.phase == lgs.PHASE_FINAL
        row = {
            "GameID": 50_000 + i,
            "ScoreID": 50_000 + i,
            "GameKey": f"2026103{i:02d}",
            "Season": SEASON,
            "SeasonType": 1,
            "Week": WEEK,
            "HomeTeam": g.home_team,
            "AwayTeam": g.away_team,
            "DateTimeUTC": g.kickoff.astimezone(timezone.utc).replace(tzinfo=None).isoformat()
            if g.kickoff
            else None,
            "HomeScore": g.home_score if started else None,
            "AwayScore": g.away_score if started else None,
            "HasStarted": started,
            "IsInProgress": started and not over,
            "IsOver": over,
            "IsOvertime": False,
            "Canceled": False,
            "Status": "Scheduled",
            "Quarter": None,
            "TimeRemaining": None,
        }
        if g.phase == lgs.PHASE_HALFTIME:
            row.update(Status="InProgress", Quarter="Half")
        elif g.phase in (lgs.PHASE_IN_PROGRESS, lgs.PHASE_END_PERIOD):
            secs = int(g.clock_seconds or 0)
            row.update(
                Status="InProgress",
                Quarter=_QUARTER[g.period],
                TimeRemaining=f"{secs // 60}:{secs % 60:02d}",
            )
        elif over:
            row.update(Status="Final", Quarter="F")
        rows.append(row)
    return rows


class ProviderWorld(FixtureWorld):
    """The replay world plus an injectable SportsDataIO fallback."""

    def __init__(self, scenario: str = "real_halftime", **kw):
        super().__init__(scenario, **kw)
        self.sdio_eligible = True
        self.sdio_error: str | None = None
        self.sdio_rows: list[dict] | None = None

    def _sdio(self, season, week):
        self.calls.append("sdio")
        now_dt = datetime.fromtimestamp(self.clock(), tz=timezone.utc)
        if self.sdio_error:
            return lgs.ScoreboardSnapshot(
                observed_at=now_dt,
                enabled=True,
                source_url=sdio.scores_by_week_url(SEASON, WEEK),
                http_status=None,
                error=self.sdio_error,
                provider=lgs.PROVIDER_SPORTSDATAIO,
            )
        rows = self.sdio_rows
        if rows is None:
            rows = _sdio_rows_from(lgs.parse_scoreboard(self.sc["espn"], observed_at=now_dt))
        return sdio.parse_scores(rows, observed_at=now_dt, season=season, week=week, season_type=2)

    def _capability(self, last_healthy):
        reasons = () if self.sdio_eligible else ("credential_missing:SPORTSDATAIO_API_KEY",)
        state = "unknown" if last_healthy is None else ("healthy" if last_healthy else "unhealthy")
        return sdio.ProviderCapability(
            provider="sportsdataio",
            eligible=self.sdio_eligible,
            available=self.sdio_eligible and state == "healthy",
            flag_on=True,
            credential_present=self.sdio_eligible,
            health_state=state,
            reasons=reasons,
        )

    def clients(self) -> live.Clients:
        base = super().clients()
        base.fallback_scoreboard = self._sdio
        base.fallback_capability = self._capability
        return base

    def tick(self, **kw) -> live.TickReport:
        return live.run_tick(
            clients=self.clients(), clock=self.clock, force=True, draws=DRAWS, seed=SEED, **kw
        )


def _gen_sources(key: str = "dynasty_main") -> dict:
    return live.load_generation(key, SEASON, WEEK)["inputs"]["sources"]


def test_espn_healthy_never_calls_sportsdataio():
    world = ProviderWorld()
    report = world.tick()
    assert report.exit_code == 0, report
    assert "sdio" not in world.calls
    sel = report.sources[live.SOURCE_LIVE_SELECTION]
    assert (sel["provider"], sel["status"], sel["selectionReason"]) == ("espn", "ok", "primary_ok")
    assert report.sources[live.SOURCE_SDIO]["status"] == "not_needed"
    sources = _gen_sources()
    assert sources["liveGameState"]["provider"] == "espn"
    assert sources["sportsDataIoScores"]["status"] == "not_needed"
    assert live.SOURCE_SDIO not in report.requests


def test_espn_403_falls_back_to_sportsdataio_with_the_reason_recorded():
    world = ProviderWorld()
    world.espn_error = "http_error:403"
    report = world.tick()
    assert report.exit_code == 0, report
    assert world.calls.count("espn") == 1 and world.calls.count("sdio") == 1
    sel = report.sources[live.SOURCE_LIVE_SELECTION]
    assert sel["provider"] == "sportsdataio" and sel["status"] == "ok"
    assert sel["selectionReason"] == "espn_unavailable:http_error:403"
    assert sel["source"] == "sportsdataio:scores"
    assert sel["flag"] == "sportsdataio_live_game_state"
    assert report.sources[live.SOURCE_ESPN]["error"] == "http_error:403"

    gen = live.load_generation("dynasty_main", SEASON, WEEK)
    sources = gen["inputs"]["sources"]
    assert sources["liveGameState"]["provider"] == "sportsdataio"
    assert sources["espnScoreboard"]["status"] == "error"
    assert sources["sportsDataIoScores"]["status"] == "ok"
    # A healthy provider supplied the state: not partial on its account.
    assert not [r for r in live._partial_reasons(sources, "live") if r.startswith("live_game")]
    # The resolver consumed SportsDataIO's state, labelled as such.
    lineage = gen["render"]["lineage"]["liveGameState"]
    assert lineage["source"] == "sportsdataio:scores" and lineage["state"] == "observed"
    evidence = gen["render"]["lineage"]["gameEvidence"]
    tnf = [ev for team, ev in evidence.items() if team in ("ATL", "GB")]
    assert tnf and all(ev["source"] == "sportsdataio:scores" for ev in tnf)
    assert all(ev["phase"] == lgs.PHASE_HALFTIME for ev in tnf)
    assert all(ev["remainingFraction"] == pytest.approx(0.5) for ev in tnf)

    health = live.load_collector_state()["sourceHealth"]
    assert health[live.SOURCE_SDIO]["consecutiveFailures"] == 0
    assert health[live.SOURCE_ESPN]["consecutiveFailures"] == 1


def test_one_provider_per_tick_never_a_merge():
    world = ProviderWorld()
    world.espn_error = "http_error:403"
    world.tick()
    head = live.observation_log(live.NFL_KEY, SEASON, WEEK, live.SOURCE_SDIO).head()
    assert head["meta"]["provider"] == "sportsdataio"
    assert head["content"] and all(k.startswith("sportsdataio:") for k in head["content"])
    snap = live.scoreboard_from_observation(head["meta"], head["content"])
    assert {g.provider for g in snap.games} == {"sportsdataio"}
    espn_head = live.observation_log(live.NFL_KEY, SEASON, WEEK, live.SOURCE_ESPN).head()
    assert espn_head["content"] is None  # ESPN never succeeded; nothing of it was used


def test_sportsdataio_ineligible_makes_no_request_and_is_partial_with_named_reasons():
    world = ProviderWorld()
    world.espn_error = "http_error:403"
    world.sdio_eligible = False
    report = world.tick()
    assert "sdio" not in world.calls
    sdio_src = report.sources[live.SOURCE_SDIO]
    assert sdio_src["status"] == "unavailable"
    assert sdio_src["reasons"] == ["credential_missing:SPORTSDATAIO_API_KEY"]
    sel = report.sources[live.SOURCE_LIVE_SELECTION]
    assert sel["status"] == "unavailable" and sel["provider"] is None
    assert sel["selectionReason"] == (
        "no_fresh_provider:espn=http_error:403;"
        "sportsdataio=credential_missing:SPORTSDATAIO_API_KEY"
    )
    reasons = live._partial_reasons(_gen_sources(), "live")
    assert "live_game_state:unavailable" in reasons
    assert "live_game_state.espn:http_error:403" in reasons
    assert "live_game_state.sportsdataio:credential_missing:SPORTSDATAIO_API_KEY" in reasons


def test_both_providers_failing_is_partial_with_both_errors():
    world = ProviderWorld()
    world.espn_error = "http_error:403"
    world.sdio_error = "http_error:401"
    report = world.tick()
    assert world.calls.count("sdio") == 1
    assert report.sources[live.SOURCE_LIVE_SELECTION]["status"] == "unavailable"
    reasons = live._partial_reasons(_gen_sources(), "live")
    assert "live_game_state.espn:http_error:403" in reasons
    assert "live_game_state.sportsdataio:http_error:401" in reasons
    health = live.load_collector_state()["sourceHealth"]
    assert health[live.SOURCE_SDIO]["consecutiveFailures"] == 1


def test_stale_last_good_is_the_newest_across_providers():
    world = ProviderWorld()
    world.espn_error = "http_error:403"
    world.tick()  # SportsDataIO supplies this tick
    world.clock.ts += 120
    world.espn_error = None
    world.tick()  # ESPN recovers: newer good observation is ESPN's
    world.clock.ts += 400
    world.espn_error = "http_error:403"
    world.sdio_error = "fetch_failed:TimeoutError"
    world.matchup_edits[("dynasty_main", 4)] = 0.5  # force a new generation
    report = world.tick()
    sel = report.sources[live.SOURCE_LIVE_SELECTION]
    assert sel["status"] == "stale_last_good" and sel["provider"] == "espn"
    assert report.sources[live.SOURCE_ESPN]["status"] == "stale_last_good"
    gen = live.load_generation("dynasty_main", SEASON, WEEK)
    assert gen["render"]["lineage"]["liveGameState"]["stale"] is True


def test_sportsdataio_backoff_is_persisted_across_runs():
    world = ProviderWorld()
    world.espn_error = "http_error:403"
    world.sdio_error = "http_error:500"
    for _ in range(live.BACKOFF_FAILURE_THRESHOLD):
        world.tick()
        world.clock.ts += 10
    world.calls.clear()
    report = world.tick()
    assert "sdio" not in world.calls
    assert report.sources[live.SOURCE_SDIO]["status"] == "skipped_backoff"


class _MasterOffWorld(ProviderWorld):
    """ESPN answers as the fetcher does with the master flag off."""

    def clients(self) -> live.Clients:
        base = super().clients()

        def disabled(season, week):
            self.calls.append("espn")
            return lgs.ScoreboardSnapshot(
                observed_at=datetime.fromtimestamp(self.clock(), tz=timezone.utc),
                enabled=False,
                source_url=None,
                http_status=None,
                error="flag_disabled",
            )

        base.scoreboard = disabled
        return base


def test_master_flag_off_never_tries_the_fallback():
    world = _MasterOffWorld()
    report = world.tick()
    assert "sdio" not in world.calls
    sel = report.sources[live.SOURCE_LIVE_SELECTION]
    assert (sel["status"], sel["selectionReason"]) == ("disabled", "master_flag_off")
    assert report.sources[live.SOURCE_SDIO]["status"] == "disabled"
