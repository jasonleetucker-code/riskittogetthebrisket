"""BALLDONTLIE NFL ``games`` → observed live game state.  Offline.

EVERY BALLDONTLIE payload in this file is SYNTHETIC — shaped from the
provider's published NFL API reference (https://nfl.balldontlie.io/, read
2026-09-27: the ``games`` example object, the documented ``status_state``
values and the error table).  No live BALLDONTLIE response has been captured
in this repository — no credential exists yet — so nothing here claims what
the live feed returned on any date.  The ESPN side of the shadow comparison
is the REAL week-3 halftime replay capture.  No test touches the network.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import pytest

from src.api import feature_flags
from src.nfl_data import balldontlie_live_game_state as bdl
from src.nfl_data import live_game_state as lgs
from src.nfl_data import sportsdataio_live_game_state as sdio
from src.utils import circuit_breaker

OBSERVED = datetime(2026, 9, 27, 18, 30, tzinfo=timezone.utc)
KEY = "bdl-SECRET-0123456789abcdef"
ENV = {"BALLDONTLIE_API_KEY": KEY}


def _team(abbr: str, tid: int = 1) -> dict:
    return {
        "id": tid,
        "conference": "NFC",
        "division": "EAST",
        "location": "X",
        "name": "Y",
        "full_name": "X Y",
        "abbreviation": abbr,
    }


def _row(**over) -> dict:
    """One SYNTHETIC ``games`` row (2026 week 3, NYG @ DAL), overridable."""
    row = {
        "id": 424001,
        "visitor_team": _team("NYG", 20),
        "home_team": _team("DAL", 9),
        "summary": None,
        "venue": "AT&T Stadium",
        "week": 3,
        "date": "2026-09-27T17:00:00.000Z",
        "season": 2026,
        "postseason": False,
        "status": "Scheduled",
        "status_state": "scheduled",
        "home_team_score": None,
        "home_team_q1": None,
        "home_team_q2": None,
        "home_team_q3": None,
        "home_team_q4": None,
        "home_team_ot": None,
        "visitor_team_score": None,
        "visitor_team_q1": None,
        "visitor_team_q2": None,
        "visitor_team_q3": None,
        "visitor_team_q4": None,
        "visitor_team_ot": None,
    }
    row.update(over)
    return row


def _payload(*rows, next_cursor=None) -> dict:
    return {"data": list(rows), "meta": {"next_cursor": next_cursor, "per_page": 100}}


def _snap(*rows, **kw) -> lgs.ScoreboardSnapshot:
    return bdl.parse_games(
        _payload(*rows, **kw), observed_at=OBSERVED, season=2026, week=3, season_type=2
    )


def _game(row: dict) -> lgs.ObservedGameState:
    snap = _snap(row)
    assert snap.ok, snap.error
    assert len(snap.games) == 1
    return snap.games[0]


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_GAME_DAY_LIVE_GAME_STATE", "1")
    monkeypatch.setenv("RISKIT_FEATURE_BALLDONTLIE_LIVE_GAME_STATE", "1")
    feature_flags.reload()
    circuit_breaker.reset_all_for_tests()
    yield
    feature_flags.reload()
    circuit_breaker.reset_all_for_tests()


# ── 1-7: lifecycle mapping ───────────────────────────────────────────


def test_scheduled():
    g = _game(_row())
    assert (g.phase, g.lifecycle_state, g.completed) == (lgs.PHASE_SCHEDULED, "pre", False)
    assert g.kickoff == datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc)
    assert lgs.regulation_fraction_remaining(g).fraction == 1.0


def test_in_progress_has_no_period_or_clock_and_no_remaining_time():
    g = _game(
        _row(
            status="In Progress",
            status_state="in_progress",
            home_team_score=14,
            visitor_team_score=10,
        )
    )
    assert (g.phase, g.lifecycle_state, g.completed) == (lgs.PHASE_IN_PROGRESS, "in", False)
    assert (g.home_score, g.away_score) == (14, 10)
    assert g.period is None and g.clock_seconds is None and g.display_clock is None
    # Never inferred from wall time since kickoff.
    rem = lgs.regulation_fraction_remaining(g)
    assert (rem.fraction, rem.reason) == (None, "period_missing")


def test_halftime_is_not_mapped_without_evidence():
    # No documented halftime value exists; the raw text is kept, not trusted.
    g = _game(
        _row(status="Halftime", status_state="in_progress", home_team_score=7, visitor_team_score=3)
    )
    assert g.phase == lgs.PHASE_IN_PROGRESS and g.phase != lgs.PHASE_HALFTIME
    assert g.status_name == "Halftime" and g.status_detail == "Halftime"
    assert g.period is None


def test_fourth_quarter_is_in_progress_without_a_period():
    g = _game(
        _row(
            status="4th Quarter",
            status_state="in_progress",
            home_team_q4=7,
            home_team_score=24,
            visitor_team_score=17,
        )
    )
    assert g.phase == lgs.PHASE_IN_PROGRESS and g.period is None
    assert lgs.regulation_fraction_remaining(g).fraction is None


def test_final():
    g = _game(_row(status="Final", status_state="final", home_team_score=27, visitor_team_score=20))
    assert (g.phase, g.lifecycle_state, g.completed) == (lgs.PHASE_FINAL, "post", True)
    assert (g.home_score, g.away_score) == (27, 20)
    assert lgs.regulation_fraction_remaining(g).fraction == 0.0
    assert g.overtime is None and not g.is_overtime


def test_overtime_only_when_an_overtime_line_score_is_published():
    g = _game(
        _row(
            status="Final/OT",
            status_state="final",
            home_team_ot=3,
            visitor_team_ot=0,
            home_team_score=30,
            visitor_team_score=27,
        )
    )
    assert g.overtime is True and g.is_overtime and g.phase == lgs.PHASE_FINAL
    live_ot = _game(_row(status_state="in_progress", visitor_team_ot=0))
    assert live_ot.overtime is True and live_ot.period is None


@pytest.mark.parametrize(
    ("state", "phase"),
    [
        ("postponed", lgs.PHASE_POSTPONED),
        ("canceled", lgs.PHASE_CANCELED),
        ("delayed", lgs.PHASE_DELAYED),
        ("suspended", lgs.PHASE_DELAYED),
    ],
)
def test_postponed_canceled_delayed(state, phase):
    g = _game(_row(status=state.title(), status_state=state))
    assert g.phase == phase and g.completed is None and g.lifecycle_state is None
    assert lgs.regulation_fraction_remaining(g).fraction is None


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        ("abandoned", "unmapped_status_state:abandoned"),
        ("unknown", "unmapped_status_state:unknown"),
        ("something_new", "unmapped_status_state:something_new"),
        (None, "status_state_missing"),
    ],
)
def test_unmapped_or_missing_status_state_is_unknown(state, reason):
    g = _game(_row(status_state=state))
    assert (g.phase, g.phase_reason) == (lgs.PHASE_UNKNOWN, reason)


# ── 8-11, 15-16: missing values, malformed payloads, team codes ───────


def test_missing_clock_stays_missing_for_every_state():
    for state in ("scheduled", "in_progress", "final"):
        g = _game(_row(status_state=state))
        assert g.clock_seconds is None and g.display_clock is None and g.period is None


def test_missing_score_is_none_never_zero():
    g = _game(_row(status_state="in_progress", home_team_score=None, visitor_team_score=""))
    assert g.home_score is None and g.away_score is None


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        (None, "missing_payload"),
        ([], "unrecognized_payload_shape"),
        ({"data": "nope"}, "unrecognized_payload_shape"),
        ({"data": []}, "empty_slate"),
        ({"data": [{"id": 1}]}, "no_parseable_games"),
        (_payload(_row(), next_cursor=99), "unexpected_pagination"),
    ],
)
def test_malformed_payloads_are_errors_never_empty_slates(payload, error):
    snap = bdl.parse_games(payload, observed_at=OBSERVED, season=2026, week=3, season_type=2)
    assert not snap.ok and snap.error == error and not snap.games


def test_rows_stating_different_weeks_fail_the_snapshot():
    snap = _snap(_row(), _row(id=2, week=4, home_team=_team("PHI"), visitor_team=_team("WAS")))
    assert snap.error == "mixed_season_week_in_payload" and not snap.games


def test_unknown_team_code_skips_the_row():
    snap = _snap(_row(), _row(id=2, home_team=_team("XXX"), visitor_team=_team("PHI")))
    assert snap.ok and len(snap.games) == 1 and snap.skipped_events == 1


def test_team_codes_go_through_the_existing_normalizer():
    g = _game(_row(home_team=_team("WSH"), visitor_team=_team("LA")))
    assert (g.home_team, g.away_team) == ("WAS", "LAR")
    assert (g.home_team_raw, g.away_team_raw) == ("WSH", "LA")


def test_postseason_rows_carry_the_postseason_type():
    snap = _snap(_row(postseason=True))
    assert snap.season_type == 3 and snap.week == 3 and snap.season == 2026


# ── 12-14: transport refusals and errors ─────────────────────────────


class _Getter:
    def __init__(self, payload=None, exc=None):
        self.payload = payload if payload is not None else _payload(_row())
        self.exc = exc
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, dict(headers)))
        if self.exc is not None:
            raise self.exc
        return bdl.HttpResponse(status=200, body=json.dumps(self.payload).encode("utf-8"))


def _fetch(getter, env=ENV, **kw):
    return bdl.fetch_games_by_week(
        season=kw.get("season", 2026),
        week=kw.get("week", 3),
        now=lambda: OBSERVED,
        http_get=getter,
        env=env,
    )


def test_request_shape_key_in_authorization_header_only():
    getter = _Getter()
    snap = _fetch(getter)
    assert snap.ok and len(snap.games) == 1
    url, headers = getter.calls[0]
    assert url == (
        "https://api.balldontlie.io/nfl/v1/games?seasons%5B%5D=2026&weeks%5B%5D=3"
        "&season_types%5B%5D=2&per_page=100"
    )
    assert headers == {"Authorization": KEY}
    assert KEY not in url and KEY not in (snap.source_url or "")


def test_credential_absent_is_a_refusal_with_no_request():
    getter = _Getter()
    for env in ({}, {"BALLDONTLIE_API_KEY": "  "}):
        snap = _fetch(getter, env=env)
        assert snap.enabled is True and not snap.ok and not snap.games
        assert snap.error == "credential_missing:BALLDONTLIE_API_KEY"
    assert getter.calls == []


@pytest.mark.parametrize("code", [401, 404, 500, 503])
def test_http_error_carries_the_status_only(code):
    snap = _fetch(_Getter(exc=bdl.HttpStatusError(code)))
    assert (snap.http_status, snap.error) == (code, f"http_error:{code}") and not snap.games


def test_rate_limit_response_is_an_explicit_error():
    snap = _fetch(_Getter(exc=bdl.HttpStatusError(429)))
    assert (snap.http_status, snap.error, snap.games) == (429, "http_error:429", ())


def test_repeated_failures_open_the_breaker_without_more_requests():
    getter = _Getter(exc=bdl.HttpStatusError(500))
    for _ in range(3):
        _fetch(getter)
    snap = _fetch(getter)
    assert snap.error == "circuit_open" and len(getter.calls) == 3


@pytest.mark.parametrize(
    ("flag", "error"),
    [
        ("RISKIT_FEATURE_BALLDONTLIE_LIVE_GAME_STATE", "flag_disabled:balldontlie_live_game_state"),
        ("RISKIT_FEATURE_GAME_DAY_LIVE_GAME_STATE", "flag_disabled:game_day_live_game_state"),
    ],
)
def test_either_flag_off_is_disabled_with_no_request(monkeypatch, flag, error):
    monkeypatch.setenv(flag, "0")
    feature_flags.reload()
    getter = _Getter()
    snap = _fetch(getter)
    assert getter.calls == [] and snap.enabled is False and snap.error == error


def test_the_flag_defaults_off():
    assert feature_flags._DEFAULTS["balldontlie_live_game_state"] is False


def test_the_key_never_reaches_errors_logs_or_reprs(caplog):
    caplog.set_level(logging.DEBUG)
    leaky = RuntimeError(f"connect failed Authorization: {KEY}")
    snap = _fetch(_Getter(exc=leaky))
    assert snap.error == "fetch_failed:RuntimeError"
    assert KEY not in repr(snap) and KEY not in caplog.text
    ok = _fetch(_Getter())
    assert KEY not in repr(ok) and KEY not in caplog.text


def test_invalid_query_makes_no_request():
    getter = _Getter()
    snap = _fetch(getter, week=99)
    assert snap.error.startswith("invalid_query:") and getter.calls == []


# ── 17: lineage, dispatch and capability ─────────────────────────────


def test_provider_lineage():
    g = _game(_row(status_state="in_progress"))
    assert g.provider == "balldontlie" and g.provider_game_id == "424001"
    assert g.game_key == "balldontlie:424001" and g.espn_event_id is None
    assert g.source_label == "balldontlie:games"
    assert lgs.PROVIDER_FLAGS["balldontlie"] == "balldontlie_live_game_state"
    snap = _snap(_row())
    assert snap.provider == "balldontlie" and snap.source_label == "balldontlie:games"
    # No provider-side data timestamp is published; fetch time is the basis.
    assert snap.provider_timestamp is None and g.provider_timestamp is None


def test_dispatch_through_the_one_owner():
    getter = _Getter(_payload(_row(status_state="final", home_team_score=3, visitor_team_score=0)))
    snap = lgs.fetch_live_game_state(
        provider=lgs.PROVIDER_BALLDONTLIE,
        season=2026,
        week=3,
        now=lambda: OBSERVED,
        _http_get=getter,
        _env=ENV,
    )
    assert snap.provider == "balldontlie" and snap.games[0].phase == lgs.PHASE_FINAL
    refused = lgs.fetch_live_game_state(
        provider=lgs.PROVIDER_BALLDONTLIE, dates="20260927", now=lambda: OBSERVED, _env=ENV
    )
    assert refused.error.startswith("invalid_query:")


def test_capability_is_flags_and_key():
    assert bdl.capability(env=ENV).eligible
    nokey = bdl.capability(env={})
    assert not nokey.eligible and "credential_missing:BALLDONTLIE_API_KEY" in nokey.reasons


# ── Contract parity across every provider ────────────────────────────


def _espn_snapshot() -> lgs.ScoreboardSnapshot:
    from tests.game_day.test_game_day_replay import _scenario

    return lgs.parse_scoreboard(_scenario("real_halftime")["espn"], observed_at=OBSERVED)


def _sdio_snapshot() -> lgs.ScoreboardSnapshot:
    row = {
        "GameID": 19001,
        "SeasonType": 1,
        "Season": 2026,
        "Week": 3,
        "DateTimeUTC": "2026-09-27T17:00:00",
        "AwayTeam": "NYG",
        "HomeTeam": "DAL",
        "AwayScore": 10,
        "HomeScore": 14,
        "Status": "InProgress",
        "Quarter": "2",
        "TimeRemaining": "5:00",
        "HasStarted": True,
        "IsInProgress": True,
        "IsOver": False,
    }
    return sdio.parse_scores([row], observed_at=OBSERVED, season=2026, week=3, season_type=2)


def test_every_provider_satisfies_the_same_canonical_contract():
    snaps = {
        "espn": _espn_snapshot(),
        "sportsdataio": _sdio_snapshot(),
        "balldontlie": _snap(
            _row(status_state="in_progress", home_team_score=14, visitor_team_score=10)
        ),
    }
    assert set(snaps) == set(lgs.PROVIDERS)
    for name, snap in snaps.items():
        assert isinstance(snap, lgs.ScoreboardSnapshot) and snap.ok and snap.provider == name
        assert name in lgs.PROVIDER_SOURCE_LABELS and name in lgs.PROVIDER_FLAGS
        for g in snap.games:
            assert isinstance(g, lgs.ObservedGameState) and g.provider == name
            assert g.phase in lgs.PHASES
            assert g.lifecycle_state in ("pre", "in", "post", None)
            assert g.home_team != g.away_team and g.home_team and g.away_team
            assert isinstance(lgs.regulation_fraction_remaining(g), lgs.RegulationRemaining)
            if name != "espn":
                assert g.game_key.startswith(f"{name}:")


# ── Shadow comparison against the REAL ESPN halftime capture ──────────


def _bdl_mirror_of(espn: lgs.ScoreboardSnapshot, **mutate) -> lgs.ScoreboardSnapshot:
    """A SYNTHETIC BALLDONTLIE payload stating the same games as ``espn``."""
    rows = []
    for i, g in enumerate(espn.games):
        state = {"pre": "scheduled", "in": "in_progress", "post": "final"}.get(
            g.lifecycle_state or "", "unknown"
        )
        rows.append(
            _row(
                id=900 + i,
                home_team=_team(g.home_team_raw),
                visitor_team=_team(g.away_team_raw),
                date=g.kickoff.isoformat() if g.kickoff else None,
                status_state=state,
                home_team_score=g.home_score,
                visitor_team_score=g.away_score,
            )
        )
    for key, value in mutate.items():
        rows[0][key] = value
    return bdl.parse_games(
        _payload(*rows), observed_at=OBSERVED, season=2026, week=3, season_type=2
    )


def test_shadow_comparison_matches_on_teams_and_names_every_difference():
    espn = _espn_snapshot()
    shadow = _bdl_mirror_of(espn)
    cmp = lgs.compare_snapshots(shadow, espn)
    assert cmp["referenceProvider"] == "espn" and cmp["candidateProvider"] == "balldontlie"
    assert not cmp["unmatchedCandidate"] and not cmp["unmatchedReference"]
    assert len(cmp["games"]) == len(espn.games)
    live = [g for g in cmp["games"] if g["reference"]["lifecycle"] == "in"]
    assert live, "the halftime capture has a live game"
    for g in cmp["games"]:
        f = g["fields"]
        assert f["lifecycle"] is True
        assert f["homeScore"] in (True, "both_missing") and f["awayScore"] in (True, "both_missing")
        assert f["kickoffDiffSeconds"] in (0.0, None)
        assert f["clockDiffSeconds"] is None  # only one side states a clock
    for g in live:
        assert g["fields"]["period"] == "candidate_missing"  # never counted as agreement

    moved = _bdl_mirror_of(espn, home_team_score=999)
    first = lgs.compare_snapshots(moved, espn)["games"]
    assert any(g["fields"]["homeScore"] is False for g in first), "a disagreement is visible"


def test_shadow_comparison_without_a_reference_records_the_candidate_alone():
    shadow = _snap(_row(status_state="in_progress"))
    cmp = lgs.compare_snapshots(shadow, None)
    assert cmp["referenceOk"] is False and cmp["referenceError"] == "none"
    assert cmp["games"][0]["reference"] is None and not cmp["unmatchedCandidate"]
    self_cmp = lgs.compare_snapshots(shadow, shadow)
    assert self_cmp["games"][0]["reference"] is None, "a provider is never its own reference"
