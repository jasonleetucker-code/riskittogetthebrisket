"""SportsDataIO ``ScoresByWeek`` → observed live game state.  Offline.

EVERY payload in this file is SYNTHETIC — shaped from SportsDataIO's
published NFL v3 Scores OpenAPI (schema ``Score``), its NFL data dictionary
and its game-status FAQ (retrieved 2026-09-25).  No live SportsDataIO
response has been captured in this repository; nothing here is a claim
about what the live feed returned on any date.  No test touches the
network: the HTTP getter is injected and the credential comes from an
explicit env mapping, never ``os.environ``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest

from src.api import feature_flags
from src.nfl_data import live_game_state as lgs
from src.nfl_data import sportsdataio_live_game_state as sdio
from src.utils import circuit_breaker
from src.utils.secret_credentials import SecretCredential, read_credential, redact

OBSERVED = datetime(2026, 9, 28, 18, 30, tzinfo=timezone.utc)
KEY = "sdio-SECRET-0123456789abcdef"
ENV = {"SPORTSDATAIO_API_KEY": KEY}


def _row(**over) -> dict:
    """One SYNTHETIC ``Score`` row (2026 REG week 4, NYG @ DAL), overridable."""
    row = {
        "GameKey": "202610428",
        "GameID": 19001,
        "ScoreID": 19001,
        "SeasonType": 1,
        "Season": 2026,
        "Week": 4,
        "Date": "2026-09-28T13:00:00",
        "DateTime": "2026-09-28T13:00:00",
        "DateTimeUTC": "2026-09-28T17:00:00",
        "AwayTeam": "NYG",
        "HomeTeam": "DAL",
        "AwayScore": None,
        "HomeScore": None,
        "Status": "Scheduled",
        "Quarter": None,
        "TimeRemaining": None,
        "QuarterDescription": None,
        "HasStarted": False,
        "IsInProgress": False,
        "IsOver": False,
        "IsOvertime": False,
        "Canceled": False,
        "Closed": False,
        "LastUpdated": "2026-09-28T14:29:55",
    }
    row.update(over)
    return row


def _live(**over) -> dict:
    base = dict(
        Status="InProgress",
        HasStarted=True,
        IsInProgress=True,
        AwayScore=10,
        HomeScore=14,
    )
    base.update(over)
    return _row(**base)


def _game(row: dict) -> lgs.ObservedGameState:
    snap = sdio.parse_scores([row], observed_at=OBSERVED, season=2026, week=4, season_type=2)
    assert snap.ok, snap.error
    assert len(snap.games) == 1
    return snap.games[0]


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_GAME_DAY_LIVE_GAME_STATE", "1")
    monkeypatch.setenv("RISKIT_FEATURE_SPORTSDATAIO_LIVE_GAME_STATE", "1")
    feature_flags.reload()
    circuit_breaker.reset_all_for_tests()
    yield
    feature_flags.reload()
    circuit_breaker.reset_all_for_tests()


# ── Status × quarter mapping ─────────────────────────────────────────


def test_scheduled():
    g = _game(_row())
    assert g.phase == lgs.PHASE_SCHEDULED and g.phase_reason is None
    assert g.provider == lgs.PROVIDER_SPORTSDATAIO
    assert g.espn_event_id is None and g.espn_state is None
    assert g.provider_game_id == "19001" and g.game_key == "sportsdataio:19001"
    assert g.lifecycle_state == "pre"
    assert (g.period, g.clock_seconds) == (None, None)
    assert (g.home_team, g.away_team) == ("DAL", "NYG")
    assert g.kickoff == datetime(2026, 9, 28, 17, 0, tzinfo=timezone.utc)
    # LastUpdated is US Eastern (EDT, UTC-4) → 18:29:55Z.
    assert g.provider_timestamp == datetime(2026, 9, 28, 18, 29, 55, tzinfo=timezone.utc)
    assert g.provider_timestamp_source == "sportsdataio_last_updated"
    assert g.source_label == "sportsdataio:scores"


def test_in_progress_quarter_and_clock():
    g = _game(_live(Quarter="2", TimeRemaining="7:30"))
    assert g.phase == lgs.PHASE_IN_PROGRESS
    assert (g.period, g.clock_seconds, g.display_clock) == (2, 450.0, "7:30")
    assert (g.home_score, g.away_score) == (14, 10)
    assert g.lifecycle_state == "in" and g.is_overtime is False


def test_end_of_quarter_is_end_period():
    g = _game(_live(Quarter="1", TimeRemaining="0:00"))
    assert g.phase == lgs.PHASE_END_PERIOD and g.period == 1


def test_halftime():
    g = _game(_live(Quarter="Half", TimeRemaining=None))
    assert g.phase == lgs.PHASE_HALFTIME
    assert (g.period, g.clock_seconds) == (2, None)


def test_overtime_in_progress():
    g = _game(
        _live(Quarter="OT", TimeRemaining="8:12", IsOvertime=True, AwayScore=24, HomeScore=24)
    )
    assert g.phase == lgs.PHASE_IN_PROGRESS
    assert (g.period, g.clock_seconds) == (5, 492.0)
    assert g.is_overtime is True


def test_final_and_final_overtime():
    final = _game(
        _row(Status="Final", Quarter="F", HasStarted=True, IsOver=True, AwayScore=17, HomeScore=20)
    )
    assert final.phase == lgs.PHASE_FINAL and final.completed is True
    assert final.lifecycle_state == "post" and final.is_overtime is False
    fot = _game(
        _row(
            Status="F/OT",
            Quarter="F/OT",
            HasStarted=True,
            IsOver=True,
            IsOvertime=True,
            AwayScore=23,
            HomeScore=20,
        )
    )
    assert fot.phase == lgs.PHASE_FINAL and fot.is_overtime is True
    assert fot.clock_seconds is None


@pytest.mark.parametrize(
    ("status", "phase"),
    [
        ("Delayed", lgs.PHASE_DELAYED),
        ("Suspended", lgs.PHASE_DELAYED),
        ("Postponed", lgs.PHASE_POSTPONED),
        ("Canceled", lgs.PHASE_CANCELED),
    ],
)
def test_delay_postponement_cancellation(status, phase):
    g = _game(_row(Status=status, Canceled=status == "Canceled"))
    assert g.phase == phase and g.phase_reason is None
    assert g.lifecycle_state == "pre"


def test_a_mid_game_delay_is_still_in_game():
    g = _game(_live(Status="Delayed", Quarter="3", TimeRemaining="4:10", IsInProgress=False))
    assert g.phase == lgs.PHASE_DELAYED
    assert g.lifecycle_state == "in" and g.period == 3


def test_canceled_flag_contradicting_status_is_unknown():
    g = _game(_row(Canceled=True))
    assert g.phase == lgs.PHASE_UNKNOWN
    assert g.phase_reason == "status_flag_conflict:Scheduled/Canceled=true"


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        (_row(HasStarted=True), "status_flag_conflict:Scheduled/HasStarted=true"),
        (_row(Status="Final", IsOver=False), "status_flag_conflict:Final/IsOver=false"),
        (
            _live(Quarter="2", TimeRemaining="1:00", IsOver=True),
            "status_flag_conflict:InProgress/IsOver=true",
        ),
        (_live(Quarter="F"), "status_quarter_conflict:InProgress/F"),
        (_live(Quarter="Q9"), "unmapped_quarter:Q9"),
        (_row(Status="Forfeit"), "unmapped_status_name:Forfeit"),
        (_row(Status=None), "status_name_missing"),
    ],
)
def test_contradictions_and_unmapped_values_are_unknown(row, reason):
    g = _game(row)
    assert g.phase == lgs.PHASE_UNKNOWN
    assert g.phase_reason == reason


def test_team_codes_go_through_the_existing_normalizer():
    g = _game(_row(HomeTeam="LA", AwayTeam="WSH"))
    assert (g.home_team, g.away_team) == ("LAR", "WAS")
    assert (g.home_team_raw, g.away_team_raw) == ("LA", "WSH")


def test_kickoff_falls_back_to_eastern_datetime():
    g = _game(_row(DateTimeUTC=None, DateTime="2026-09-28T20:25:00"))
    assert g.kickoff == datetime(2026, 9, 29, 0, 25, tzinfo=timezone.utc)


# ── regulation_fraction_remaining, unchanged, on SportsDataIO states ──


@pytest.mark.parametrize(
    ("row", "fraction", "reason"),
    [
        (_row(), 1.0, None),
        (_live(Quarter="2", TimeRemaining="7:30"), 0.625, None),
        (_live(Quarter="3", TimeRemaining="0:00"), 0.25, None),
        (_live(Quarter="Half"), 0.5, None),
        (_live(Quarter="OT", TimeRemaining="5:00"), None, "overtime"),
        (_row(Status="Final", Quarter="F", HasStarted=True, IsOver=True), 0.0, None),
        (_row(Status="Delayed"), None, "delayed"),
        (_row(Status="Postponed"), None, "postponed"),
        (_row(Status="Canceled", Canceled=True), None, "canceled"),
        (_live(Quarter=None), None, "period_missing"),
    ],
)
def test_regulation_fraction_remaining_on_sportsdataio_states(row, fraction, reason):
    rr = lgs.regulation_fraction_remaining(_game(row))
    assert rr.fraction == (pytest.approx(fraction) if fraction is not None else None)
    assert rr.reason == reason


# ── Snapshot-level parsing ───────────────────────────────────────────


def test_snapshot_metadata_uses_the_snapshot_season_type_convention():
    rows = [
        _live(Quarter="2", TimeRemaining="7:30", LastUpdated="2026-09-28T14:31:00"),
        _row(GameID=19002, ScoreID=19002, HomeTeam="PHI", AwayTeam="KC"),
        _row(GameKey=None, GameID=None, ScoreID=None, HomeTeam=None, AwayTeam=None),  # bye row
    ]
    snap = sdio.parse_scores(rows, observed_at=OBSERVED, season=2026, week=4, season_type=2)
    assert snap.ok and snap.provider == lgs.PROVIDER_SPORTSDATAIO
    # SportsDataIO SeasonType 1 (regular) is season_type 2 in the snapshot.
    assert (snap.season, snap.week, snap.season_type) == (2026, 4, 2)
    assert (snap.event_count, snap.skipped_events, len(snap.games)) == (3, 1, 2)
    assert snap.provider_timestamp == datetime(2026, 9, 28, 18, 31, tzinfo=timezone.utc)
    assert snap.provider_timestamp_source == "sportsdataio_last_updated_max"


def test_payload_for_another_week_is_carried_so_it_is_refused_downstream():
    snap = sdio.parse_scores(
        [_row(Week=5)], observed_at=OBSERVED, season=2026, week=4, season_type=2
    )
    assert snap.ok and snap.week == 5  # observed_game_evidence → week_mismatch


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ([], "empty_slate"),
        (None, "missing_payload"),
        ({"Scores": []}, "unrecognized_payload_shape"),
        ([_row(), _row(GameID=2, Week=5)], "mixed_season_week_in_payload"),
        ([{"nothing": 1}], "no_parseable_games"),
    ],
)
def test_malformed_payloads_are_errors_never_empty_slates(payload, error):
    snap = sdio.parse_scores(payload, observed_at=OBSERVED, season=2026, week=4, season_type=2)
    assert snap.error == error and not snap.games


# ── Fetch: flags, credential, transport, redaction ───────────────────


class _Getter:
    def __init__(self, payload=None, exc: Exception | None = None):
        self.payload = payload if payload is not None else [_row()]
        self.exc = exc
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, dict(headers)))
        if self.exc is not None:
            raise self.exc
        import json

        return sdio.HttpResponse(status=200, body=json.dumps(self.payload).encode("utf-8"))


def _fetch(getter, env=ENV, **kw):
    return sdio.fetch_scores_by_week(
        season=kw.get("season", 2026),
        week=kw.get("week", 4),
        now=lambda: OBSERVED,
        http_get=getter,
        env=env,
    )


def test_request_shape_key_in_header_only():
    getter = _Getter()
    snap = _fetch(getter)
    assert snap.ok and len(snap.games) == 1
    url, headers = getter.calls[0]
    assert url == "https://api.sportsdata.io/v3/nfl/scores/json/ScoresByWeek/2026REG/4"
    assert headers == {"Ocp-Apim-Subscription-Key": KEY}
    assert KEY not in url and KEY not in (snap.source_url or "")


def test_credential_missing_is_a_refusal_with_no_request():
    getter = _Getter()
    snap = _fetch(getter, env={})
    assert getter.calls == []
    assert snap.enabled is True and not snap.ok and not snap.games
    assert snap.error == "credential_missing:SPORTSDATAIO_API_KEY"
    blank = _fetch(getter, env={"SPORTSDATAIO_API_KEY": "   "})
    assert blank.error == "credential_missing:SPORTSDATAIO_API_KEY" and getter.calls == []


@pytest.mark.parametrize(
    ("flag", "error"),
    [
        (
            "RISKIT_FEATURE_SPORTSDATAIO_LIVE_GAME_STATE",
            "flag_disabled:sportsdataio_live_game_state",
        ),
        ("RISKIT_FEATURE_GAME_DAY_LIVE_GAME_STATE", "flag_disabled:game_day_live_game_state"),
    ],
)
def test_either_flag_off_is_disabled_with_no_request(monkeypatch, flag, error):
    monkeypatch.setenv(flag, "0")
    feature_flags.reload()
    getter = _Getter()
    snap = _fetch(getter)
    assert getter.calls == [] and snap.enabled is False and snap.error == error


def test_the_new_flag_defaults_off():
    assert feature_flags._DEFAULTS["sportsdataio_live_game_state"] is False


def test_http_error_carries_the_status_only():
    snap = _fetch(_Getter(exc=sdio.HttpStatusError(401)))
    assert (snap.http_status, snap.error) == (401, "http_error:401")


def test_the_key_never_reaches_errors_logs_or_reprs(caplog):
    caplog.set_level(logging.DEBUG)
    leaky = RuntimeError(f"connect failed for key={KEY} header Ocp-Apim-Subscription-Key: {KEY}")
    snap = _fetch(_Getter(exc=leaky))
    assert snap.error == "fetch_failed:RuntimeError"
    assert KEY not in repr(snap) and KEY not in caplog.text
    cred = read_credential("SPORTSDATAIO_API_KEY", ENV)
    assert isinstance(cred, SecretCredential)
    assert KEY not in repr(cred) and KEY not in str(cred)
    with pytest.raises(TypeError):
        import pickle

        pickle.dumps(cred)
    assert KEY not in redact(f"GET /x?key={KEY}", [cred])
    assert KEY not in redact(f"Ocp-Apim-Subscription-Key: {KEY}")
    ok = _fetch(_Getter())
    assert KEY not in repr(ok) and KEY not in caplog.text


def test_invalid_query_makes_no_request():
    getter = _Getter()
    snap = _fetch(getter, week=99)
    assert snap.error.startswith("invalid_query:") and getter.calls == []


def test_dispatch_through_the_one_owner():
    getter = _Getter([_live(Quarter="4", TimeRemaining="2:00")])
    snap = lgs.fetch_live_game_state(
        provider=lgs.PROVIDER_SPORTSDATAIO,
        season=2026,
        week=4,
        now=lambda: OBSERVED,
        _http_get=getter,
        _env=ENV,
    )
    assert snap.provider == "sportsdataio" and snap.games[0].phase == lgs.PHASE_IN_PROGRESS
    refused = lgs.fetch_live_game_state(
        provider=lgs.PROVIDER_SPORTSDATAIO, dates="20260928", now=lambda: OBSERVED, _env=ENV
    )
    assert refused.error.startswith("invalid_query:")
    unknown = lgs.fetch_live_game_state(provider="nope", now=lambda: OBSERVED)
    assert unknown.error == "unknown_provider:nope"


def test_capability_is_flags_and_key_and_health():
    cap = sdio.capability(last_healthy=True, env=ENV)
    assert cap.eligible and cap.available and cap.health_state == "healthy"
    unknown = sdio.capability(last_healthy=None, env=ENV)
    assert unknown.eligible and not unknown.available
    nokey = sdio.capability(last_healthy=True, env={})
    assert not nokey.eligible and "credential_missing:SPORTSDATAIO_API_KEY" in nokey.reasons


def test_espn_states_are_unchanged_by_the_provider_fields():
    """An ESPN-built state keeps its bare event id as its key and its own state."""
    g = lgs.ObservedGameState(
        espn_event_id="401",
        home_team="GB",
        away_team="ATL",
        home_team_raw="GB",
        away_team_raw="ATL",
        kickoff=None,
        espn_state="in",
        status_name="STATUS_IN_PROGRESS",
        phase=lgs.PHASE_IN_PROGRESS,
        phase_reason=None,
        period=5,
        clock_seconds=100.0,
        display_clock="1:40",
        status_detail=None,
        completed=False,
        home_score=20,
        away_score=20,
        observed_at=OBSERVED,
    )
    assert g.provider == "espn" and g.game_key == "401" and g.lifecycle_state == "in"
    assert g.is_overtime is True and g.source_label == "espn:scoreboard"
