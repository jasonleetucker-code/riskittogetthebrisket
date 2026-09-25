"""ESPN scoreboard → observed live game state.  Offline: fixtures + a fake opener."""

from __future__ import annotations

import io
import json
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.api import feature_flags
from src.nfl_data import live_game_state as lgs
from src.utils import circuit_breaker

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "game_day" / "espn"
OBSERVED = datetime(2026, 9, 25, 0, 58, 24, tzinfo=timezone.utc)


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _parse(name: str) -> lgs.ScoreboardSnapshot:
    return lgs.parse_scoreboard(_load(name), observed_at=OBSERVED)


def _only_game(name: str) -> lgs.ObservedGameState:
    snap = _parse(name)
    assert len(snap.games) == 1
    return snap.games[0]


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv("RISKIT_FEATURE_GAME_DAY_LIVE_GAME_STATE", raising=False)
    feature_flags.reload()
    circuit_breaker.reset_all_for_tests()
    yield
    feature_flags.reload()
    circuit_breaker.reset_all_for_tests()


# ── Real capture ─────────────────────────────────────────────────────


def test_real_capture_parses_every_event_with_metadata():
    snap = _parse("real_2026w3_thu_end_q1_scoreboard.json")
    assert snap.ok
    assert (snap.season, snap.season_type, snap.week) == (2026, 2, 3)
    assert snap.event_count == 3 and snap.skipped_events == 0
    assert {g.espn_event_id for g in snap.games} == {"401872948", "401872953", "401872955"}
    assert all(g.observed_at == OBSERVED for g in snap.games)


def test_real_end_of_first_quarter():
    snap = _parse("real_2026w3_thu_end_q1_scoreboard.json")
    game = next(g for g in snap.games if g.espn_event_id == "401872948")
    assert (game.home_team, game.away_team) == ("GB", "ATL")
    assert game.phase == lgs.PHASE_END_PERIOD
    assert game.espn_state == "in"
    assert game.status_name == "STATUS_END_PERIOD"
    assert game.period == 1 and game.clock_seconds == 0.0
    assert game.completed is False
    assert (game.home_score, game.away_score) == (7, 7)
    assert game.kickoff == datetime(2026, 9, 25, 0, 15, tzinfo=timezone.utc)
    # (4 - 1) * 900 / 3600
    assert lgs.regulation_fraction_remaining(game) == lgs.RegulationRemaining(0.75, None)


def test_real_scheduled_game_has_all_regulation_left():
    snap = _parse("real_2026w3_thu_end_q1_scoreboard.json")
    game = next(g for g in snap.games if g.espn_event_id == "401872953")
    assert game.phase == lgs.PHASE_SCHEDULED and game.espn_state == "pre"
    assert lgs.regulation_fraction_remaining(game) == lgs.RegulationRemaining(1.0, None)


def test_espn_wsh_normalizes_to_sleeper_was():
    snap = _parse("real_2026w3_thu_end_q1_scoreboard.json")
    game = next(g for g in snap.games if g.espn_event_id == "401872955")
    assert game.home_team_raw == "WSH"
    assert game.home_team == "WAS"
    assert game.away_team == "SEA"


# ── Synthetic status cases ───────────────────────────────────────────


def test_in_progress_uses_observed_clock():
    game = _only_game("synthetic_in_progress_scoreboard.json")
    assert game.phase == lgs.PHASE_IN_PROGRESS
    assert game.period == 3 and game.clock_seconds == 452.0
    result = lgs.regulation_fraction_remaining(game)
    assert result.reason is None
    assert result.fraction == pytest.approx((900 + 452) / 3600)


def test_halftime_is_half():
    game = _only_game("synthetic_halftime_scoreboard.json")
    assert game.phase == lgs.PHASE_HALFTIME
    assert lgs.regulation_fraction_remaining(game) == lgs.RegulationRemaining(0.5, None)


@pytest.mark.parametrize(
    "name", ["synthetic_final_scoreboard.json", "synthetic_final_overtime_scoreboard.json"]
)
def test_final_and_final_overtime_have_nothing_left(name):
    game = _only_game(name)
    assert game.phase == lgs.PHASE_FINAL
    assert game.completed is True
    assert lgs.regulation_fraction_remaining(game) == lgs.RegulationRemaining(0.0, None)


def test_final_overtime_keeps_raw_status_and_period():
    game = _only_game("synthetic_final_overtime_scoreboard.json")
    assert game.status_name == "STATUS_FINAL_OVERTIME"
    assert game.is_overtime


def test_overtime_in_progress_is_refused_not_invented():
    game = _only_game("synthetic_overtime_scoreboard.json")
    assert game.phase == lgs.PHASE_IN_PROGRESS and game.is_overtime
    assert lgs.regulation_fraction_remaining(game) == lgs.RegulationRemaining(None, "overtime")


def test_delays_are_refused():
    snap = _parse("synthetic_delayed_scoreboard.json")
    assert [g.phase for g in snap.games] == [lgs.PHASE_DELAYED, lgs.PHASE_DELAYED]
    assert [g.status_name for g in snap.games] == ["STATUS_DELAYED", "STATUS_RAIN_DELAY"]
    for game in snap.games:
        assert lgs.regulation_fraction_remaining(game) == lgs.RegulationRemaining(None, "delayed")


def test_postponed_and_canceled_are_refused():
    snap = _parse("synthetic_postponed_scoreboard.json")
    results = {g.phase: lgs.regulation_fraction_remaining(g) for g in snap.games}
    assert results == {
        lgs.PHASE_POSTPONED: lgs.RegulationRemaining(None, "postponed"),
        lgs.PHASE_CANCELED: lgs.RegulationRemaining(None, "canceled"),
    }


def test_unknown_names_conflicts_and_missing_names_are_explicit_unknown():
    snap = _parse("synthetic_unknown_status_scoreboard.json")
    by_id = {g.espn_event_id: g for g in snap.games}

    unmapped = by_id["900010"]
    assert unmapped.phase == lgs.PHASE_UNKNOWN
    assert unmapped.phase_reason == "unmapped_status_name:STATUS_SUSPENDED"

    conflict = by_id["900011"]  # STATUS_FINAL but ESPN state "in"
    assert conflict.phase == lgs.PHASE_UNKNOWN
    assert conflict.phase_reason == "status_state_conflict:STATUS_FINAL/in"

    missing = by_id["900012"]
    assert missing.phase == lgs.PHASE_UNKNOWN
    assert missing.phase_reason == "status_name_missing"

    for game in snap.games:
        result = lgs.regulation_fraction_remaining(game)
        assert result.fraction is None
        assert result.reason.startswith("unknown_status:")


def test_malformed_events_are_skipped_and_counted_never_raised():
    snap = _parse("synthetic_malformed_scoreboard.json")
    assert snap.event_count == 6
    assert snap.skipped_events == 5
    assert [g.espn_event_id for g in snap.games] == ["900020"]
    assert lgs.regulation_fraction_remaining(snap.games[0]) == lgs.RegulationRemaining(1.0, None)


# ── regulation_fraction_remaining edge cases ─────────────────────────


def _state(**overrides) -> lgs.ObservedGameState:
    base = dict(
        espn_event_id="1",
        home_team="DAL",
        away_team="PHI",
        home_team_raw="DAL",
        away_team_raw="PHI",
        kickoff=None,
        espn_state="in",
        status_name="STATUS_IN_PROGRESS",
        phase=lgs.PHASE_IN_PROGRESS,
        phase_reason=None,
        period=2,
        clock_seconds=300.0,
        display_clock="5:00",
        status_detail=None,
        completed=False,
        home_score=None,
        away_score=None,
        observed_at=OBSERVED,
    )
    base.update(overrides)
    return lgs.ObservedGameState(**base)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"period": 1, "clock_seconds": 900.0}, lgs.RegulationRemaining(1.0, None)),
        ({"period": 4, "clock_seconds": 0.0}, lgs.RegulationRemaining(0.0, None)),
        ({"period": 2, "clock_seconds": 300.0}, lgs.RegulationRemaining((1800 + 300) / 3600, None)),
        ({"period": None}, lgs.RegulationRemaining(None, "period_missing")),
        ({"period": 0}, lgs.RegulationRemaining(None, "period_missing")),
        ({"clock_seconds": None}, lgs.RegulationRemaining(None, "clock_missing")),
        ({"clock_seconds": 901.0}, lgs.RegulationRemaining(None, "clock_out_of_range")),
        ({"clock_seconds": -1.0}, lgs.RegulationRemaining(None, "clock_out_of_range")),
        (
            {"phase": lgs.PHASE_END_PERIOD, "period": 3, "clock_seconds": None},
            lgs.RegulationRemaining(900 / 3600, None),
        ),
        (
            {"phase": lgs.PHASE_END_PERIOD, "period": 4},
            lgs.RegulationRemaining(0.0, None),
        ),
        (
            {"phase": lgs.PHASE_END_PERIOD, "period": 5},
            lgs.RegulationRemaining(None, "overtime"),
        ),
    ],
)
def test_regulation_fraction_edges(overrides, expected):
    result = lgs.regulation_fraction_remaining(_state(**overrides))
    assert result.reason == expected.reason
    if expected.fraction is None:
        assert result.fraction is None
    else:
        assert result.fraction == pytest.approx(expected.fraction)


def test_display_clock_used_when_numeric_clock_absent():
    payload = _load("synthetic_in_progress_scoreboard.json")
    status = payload["events"][0]["competitions"][0]["status"]
    del status["clock"]
    status["displayClock"] = "7:32"
    game = lgs.parse_scoreboard(payload, observed_at=OBSERVED).games[0]
    assert game.clock_seconds == 452.0


def test_status_mapping_table_is_closed_over_phases():
    assert set(lgs.STATUS_NAME_TO_PHASE.values()) <= lgs.PHASES
    assert lgs.PHASE_UNKNOWN not in set(lgs.STATUS_NAME_TO_PHASE.values())


# ── Payload-level degradation ────────────────────────────────────────


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        (None, "missing_payload"),
        ([], "unrecognized_payload_shape"),
        ({"season": {"year": 2026}}, "events_missing"),
    ],
)
def test_bad_payloads_degrade_with_named_error(payload, error):
    snap = lgs.parse_scoreboard(payload, observed_at=OBSERVED)
    assert snap.games == ()
    assert snap.error == error
    assert not snap.ok


# ── URL + fetch ──────────────────────────────────────────────────────


def test_scoreboard_url_variants():
    assert lgs.scoreboard_url() == lgs.ESPN_SCOREBOARD_URL
    assert lgs.scoreboard_url(dates="20260927").endswith("?dates=20260927")
    assert lgs.scoreboard_url(week=3, season_type=2).endswith("?week=3&seasontype=2")
    for bad in ({"dates": "2026-09-27"}, {"week": 0}, {"week": True}, {"season_type": 4}):
        with pytest.raises(ValueError):
            lgs.scoreboard_url(**bad)


class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200, headers: dict | None = None):
        self._body = io.BytesIO(body)
        self.status = status
        self.headers = headers or {}

    def read(self):
        return self._body.read()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _enable(monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_GAME_DAY_LIVE_GAME_STATE", "1")
    feature_flags.reload()


def test_flag_default_is_off_and_fetch_says_so():
    assert feature_flags.is_enabled(lgs.FLAG_NAME) is False
    calls = []
    snap = lgs.fetch_live_game_state(
        now=lambda: OBSERVED, _url_opener=lambda *a, **k: calls.append(a)
    )
    assert calls == []
    assert snap.enabled is False
    assert snap.error == "flag_disabled"
    assert snap.observed_at == OBSERVED


def test_fetch_success_records_status_url_timeout_and_provider_time(monkeypatch):
    _enable(monkeypatch)
    body = (FIXTURES / "real_2026w3_thu_end_q1_scoreboard.json").read_bytes()
    seen = {}

    def opener(req, timeout):
        seen["url"] = req.full_url
        seen["ua"] = req.get_header("User-agent")
        seen["timeout"] = timeout
        return _FakeResponse(body, headers={"Date": "Fri, 25 Sep 2026 00:58:23 GMT"})

    snap = lgs.fetch_live_game_state(
        week=3, season_type=2, now=lambda: OBSERVED, _url_opener=opener
    )
    assert snap.ok and snap.enabled
    assert snap.http_status == 200
    assert seen["url"].endswith("?week=3&seasontype=2")
    assert seen["ua"] == "riskit-live-game-state/1.0"
    assert 0 < seen["timeout"] <= 10
    assert snap.provider_timestamp == datetime(2026, 9, 25, 0, 58, 23, tzinfo=timezone.utc)
    assert snap.provider_timestamp_source == "http_date"
    assert len(snap.games) == 3
    assert snap.games[0].provider_timestamp_source == "http_date"


def test_fetch_http_error_never_raises(monkeypatch):
    _enable(monkeypatch)

    def opener(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, None)

    snap = lgs.fetch_live_game_state(now=lambda: OBSERVED, _url_opener=opener)
    assert snap.error == "http_error:503"
    assert snap.http_status == 503
    assert snap.games == ()


def test_fetch_timeout_and_bad_json_never_raise(monkeypatch):
    _enable(monkeypatch)

    def timeout_opener(req, timeout):
        raise TimeoutError("slow")

    snap = lgs.fetch_live_game_state(now=lambda: OBSERVED, _url_opener=timeout_opener)
    assert snap.error == "fetch_failed:TimeoutError"

    snap = lgs.fetch_live_game_state(
        now=lambda: OBSERVED, _url_opener=lambda req, timeout: _FakeResponse(b"<html>")
    )
    assert snap.error.startswith("fetch_failed:")
    assert snap.http_status == 200


def test_invalid_query_is_reported_without_a_request(monkeypatch):
    _enable(monkeypatch)
    calls = []
    snap = lgs.fetch_live_game_state(
        dates="bad", now=lambda: OBSERVED, _url_opener=lambda *a, **k: calls.append(a)
    )
    assert calls == []
    assert snap.error.startswith("invalid_query:")


def test_breaker_opens_after_repeated_failures(monkeypatch):
    _enable(monkeypatch)
    calls = []

    def opener(req, timeout):
        calls.append(1)
        raise urllib.error.URLError("down")

    for _ in range(3):
        lgs.fetch_live_game_state(now=lambda: OBSERVED, _url_opener=opener)
    snap = lgs.fetch_live_game_state(now=lambda: OBSERVED, _url_opener=opener)
    assert snap.error == "circuit_open"
    assert len(calls) == 3
