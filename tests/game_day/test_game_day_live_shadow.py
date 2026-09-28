"""Game Day collector — BALLDONTLIE SHADOW capture (never selected).

Runs the REAL collector tick over the captured TNF halftime replay world.
The BALLDONTLIE side is SYNTHETIC — ``games`` rows generated from the
captured ESPN slate in the provider's documented shape; no live BALLDONTLIE
response exists in this repository.  No network.

Pinned: the shadow read never changes the selected provider, the lineage,
the input fingerprint or the generation; ineligible (flag off / no key)
costs no request; each tick appends one comparison record naming the
provider actually selected; a failing shadow backs off on its own health
entry and never fails the tick.
"""

from __future__ import annotations

import json

from src.nfl_data import balldontlie_live_game_state as bdl
from src.nfl_data import live_game_state as lgs
from src.ros import game_day_live as live
from tests.game_day.test_game_day_live_collector import (
    SEASON,
    WEEK,
    FixtureWorld,
    _hermetic_sim_cache,  # noqa: F401 — autouse fixture, re-used
)
from tests.nfl_data.test_balldontlie_live_game_state import _payload, _row, _team


class _Cap:
    def __init__(self, eligible: bool, reasons=()):
        self.eligible = eligible
        self.reasons = tuple(reasons)


class ShadowWorld(FixtureWorld):
    def __init__(self, scenario: str = "real_halftime", **kw):
        super().__init__(scenario, **kw)
        self.shadow_eligible = True
        self.shadow_error: str | None = None
        self.shadow_calls = 0

    def _shadow(self, season, week):
        self.shadow_calls += 1
        from datetime import datetime, timezone

        observed = datetime.fromtimestamp(self.clock(), tz=timezone.utc)
        if self.shadow_error:
            return lgs.ScoreboardSnapshot(
                observed_at=observed,
                enabled=True,
                source_url="https://api.balldontlie.io/nfl/v1/games",
                http_status=429,
                error=self.shadow_error,
                provider=lgs.PROVIDER_BALLDONTLIE,
            )
        espn = lgs.parse_scoreboard(self.sc["espn"], observed_at=observed)
        rows = []
        for i, g in enumerate(espn.games):
            state = {"pre": "scheduled", "in": "in_progress", "post": "final"}.get(
                g.lifecycle_state or "", "unknown"
            )
            rows.append(
                _row(
                    id=700 + i,
                    season=SEASON,
                    week=WEEK,
                    home_team=_team(g.home_team_raw),
                    visitor_team=_team(g.away_team_raw),
                    date=g.kickoff.isoformat() if g.kickoff else None,
                    status_state=state,
                    home_team_score=g.home_score,
                    visitor_team_score=g.away_score,
                )
            )
        return bdl.parse_games(
            _payload(*rows), observed_at=observed, season=season, week=week, season_type=2
        )

    def clients(self) -> live.Clients:
        base = super().clients()
        base.shadow_scoreboard = self._shadow
        base.shadow_capability = lambda: _Cap(
            self.shadow_eligible,
            () if self.shadow_eligible else ("credential_missing:BALLDONTLIE_API_KEY",),
        )
        return base


def _shadow_records() -> list[dict]:
    path = live.shadow_log_path(SEASON, WEEK)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_shadow_never_changes_the_generation(monkeypatch, tmp_path):
    fingerprints = {}
    for label, shadow in (("without", False), ("with", True)):
        monkeypatch.setattr(live, "LIVE_ROOT", tmp_path / label)
        live._generation_cache.clear()
        world = ShadowWorld() if shadow else FixtureWorld("real_halftime")
        report = world.tick()
        assert report.outcome == "ran" and report.exit_code == 0
        gen = live.load_generation("dynasty_main", SEASON, WEEK)
        fingerprints[label] = (
            gen["inputFingerprint"],
            report.sources[live.SOURCE_LIVE_SELECTION]["provider"],
            # Volatile cache stamps (``cached`` / ``cacheComputedAt``) differ
            # because both runs share one sim cache; the fingerprint ignores
            # them the same way.
            json.dumps(
                live._strip_volatile(gen["render"].get("lineage")), sort_keys=True, default=str
            ),
        )
        if shadow:
            assert world.shadow_calls == 1
            stamp = report.sources[live.SOURCE_BDL]
            assert stamp["role"] == "shadow" and stamp["status"] == "ok"
            assert stamp["referenceProvider"] == "espn" and stamp["gamesCompared"] > 0
            assert "balldontlie" not in fingerprints[label][2]
    assert fingerprints["with"] == fingerprints["without"]
    assert fingerprints["with"][1] == "espn", "ESPN healthy: shadow is never selected"


def test_each_tick_appends_one_comparison_against_the_selected_provider():
    world = ShadowWorld()
    world.tick()
    world.clock.ts += 60
    world.tick()
    records = _shadow_records()
    assert len(records) == 2
    rec = records[-1]
    assert rec["candidateProvider"] == "balldontlie" and rec["referenceProvider"] == "espn"
    assert rec["referenceOk"] is True and rec["games"]
    live_games = [g for g in rec["games"] if g["reference"] and g["reference"]["lifecycle"] == "in"]
    assert live_games and all(g["fields"]["period"] == "candidate_missing" for g in live_games)
    assert all(g["fields"]["lifecycle"] is True for g in rec["games"] if g["reference"])
    assert "fetchSeconds" in rec and rec["observedAt"]
    stored = live.observation_log(live.NFL_KEY, SEASON, WEEK, live.SOURCE_BDL).head()
    assert stored and stored.get("content"), "the raw shadow observation is kept"


def test_shadow_is_compared_even_when_no_provider_was_selected():
    world = ShadowWorld()
    world.espn_error = "http_error:403"
    report = world.tick()
    assert report.sources[live.SOURCE_LIVE_SELECTION]["provider"] != "balldontlie"
    rec = _shadow_records()[-1]
    assert rec["candidateOk"] is True
    assert (
        all(g["reference"] is None for g in rec["games"])
        or rec["referenceProvider"] != "balldontlie"
    )


def test_ineligible_shadow_makes_no_request_and_records_why():
    world = ShadowWorld()
    world.shadow_eligible = False
    report = world.tick()
    assert world.shadow_calls == 0
    stamp = report.sources[live.SOURCE_BDL]
    assert stamp["status"] == "unavailable"
    assert stamp["reasons"] == ["credential_missing:BALLDONTLIE_API_KEY"]
    assert live.SOURCE_BDL not in report.requests
    assert _shadow_records() == []


def test_not_configured_is_the_default_for_injected_clients():
    report = FixtureWorld("real_halftime").tick()
    assert report.sources[live.SOURCE_BDL]["status"] == "not_configured"


def test_a_failing_shadow_backs_off_alone_and_never_fails_the_tick():
    world = ShadowWorld()
    world.shadow_error = "http_error:429"
    for _ in range(live.BACKOFF_FAILURE_THRESHOLD):
        report = world.tick()
        assert report.exit_code == 0 and report.leagues["dynasty_main"]["ok"]
        world.clock.ts += 1
    health = live.load_collector_state()["sourceHealth"]
    assert health[live.SOURCE_BDL]["consecutiveFailures"] == live.BACKOFF_FAILURE_THRESHOLD
    assert health[live.SOURCE_BDL]["backoffUntil"]
    calls = world.shadow_calls
    report = world.tick()
    assert (
        world.shadow_calls == calls
        and report.sources[live.SOURCE_BDL]["status"] == "skipped_backoff"
    )
    assert (
        live.SOURCE_ESPN not in health
        or health[live.SOURCE_ESPN].get("consecutiveFailures", 0) == 0
    )


def test_default_clients_wire_the_shadow_behind_its_capability(monkeypatch):
    monkeypatch.delenv("BALLDONTLIE_API_KEY", raising=False)
    clients = live.default_clients()
    assert clients.shadow_scoreboard is not None and clients.shadow_capability is not None
    cap = clients.shadow_capability()
    assert not cap.eligible
    assert "credential_missing:BALLDONTLIE_API_KEY" in cap.reasons


def test_the_shadow_report_summarizes_transitions_agreement_and_rate():
    from scripts.balldontlie_shadow_report import summarize

    world = ShadowWorld()
    for _ in range(3):
        world.tick()
        world.clock.ts += 60
    summary = summarize(_shadow_records())
    assert summary["records"] == 3
    assert summary["requestsPerMinuteObserved"] <= summary["freeTierLimitPerMinute"]
    assert summary["referenceProviders"] == {"espn": 3}
    game = next(g for g in summary["games"].values() if "in" in g["lifecycleFirstSeen"])
    assert game["agreement"]["lifecycle"] == {"True": 3}
    assert game["agreement"]["period"] == {"candidate_missing": 3}
    assert game["scoreChanges"] and game["scoreLagSecondsVsReference"] == [0.0]
