"""Route tests for ``POST /api/waiver/streaming`` (Weekly IDP Streaming).

Pins the route posture it shares with ``/api/waiver/advisor``: private (401
anonymous, from the default-deny API gate), both flags checked FIRST and the
switched-off one named, 400 ``team_required`` (never guessed), stable
``bad_<field>`` codes from the request parser, the composer's ``ValueError``
codes mapped to stable statuses, and no exception text in any response.  The
composer itself is ``tests/waivers/test_streaming.py``'s; here it is
monkeypatched so the tests pin the HANDLER.
"""

from __future__ import annotations

import logging

import pytest

import server
from src.api import feature_flags
from src.waivers import streaming
from tests.api.test_waiver_perfect_endpoint import AS, env  # noqa: F401 - fixture import

URL = "/api/waiver/streaming"


def _flags(monkeypatch, **on):
    real = feature_flags.is_enabled

    def fake(name, *a, **k):
        if name in on:
            return on[name]
        return real(name, *a, **k)

    monkeypatch.setattr(feature_flags, "is_enabled", fake)


@pytest.fixture()
def flags_on(monkeypatch):
    _flags(monkeypatch, waiver_advisor=True, idp_streaming=True)


def test_flag_is_on_by_owner_decision():
    # Owner decision 1 (2026-10-29): ON for the private, signed-in Waiver
    # Advisor; the route stays auth-gated (see test_anonymous_is_401).
    assert feature_flags._DEFAULTS["idp_streaming"] is True


def test_anonymous_is_401(env, flags_on):  # noqa: F811
    res = env.client.post(URL, json={"teamOwnerId": "me"})
    assert res.status_code == 401
    assert res.json()["error"] == "auth_required"


@pytest.mark.parametrize(
    "advisor, streaming_on, named",
    [
        (False, True, "waiver_advisor"),
        (True, False, "idp_streaming"),
        (False, False, "waiver_advisor"),
    ],
)
def test_flags_are_checked_first(env, monkeypatch, advisor, streaming_on, named):  # noqa: F811
    _flags(monkeypatch, waiver_advisor=advisor, idp_streaming=streaming_on)
    # No team, a bad field, no contract: the gate still answers first.
    monkeypatch.setattr(server, "latest_contract_data", {})
    res = env.client.post(URL, json={"position": "QB"}, headers=AS)
    assert res.status_code == 503
    assert res.json() == {"error": "feature_disabled", "flag": named}


def test_team_is_required_and_never_guessed(env, flags_on):  # noqa: F811
    res = env.client.post(URL, json={"leagueKey": "main"}, headers=AS)
    assert res.status_code == 400
    assert res.json() == {"error": "team_required", "leagueKey": "main"}


@pytest.mark.parametrize(
    "field, value, code",
    [
        ("position", "QB", "bad_position"),
        ("horizonWeeks", 9, "bad_horizonWeeks"),
        ("capacity", -1, "bad_capacity"),
        ("week", "soon", "bad_week"),
        ("dynastyBudget", -5, "bad_dynastyBudget"),
        ("capacityCurve", "yes", "bad_capacityCurve"),
    ],
)
def test_bad_field_is_a_stable_400(env, flags_on, field, value, code):  # noqa: F811
    res = env.client.post(
        URL, json={"leagueKey": "main", "teamOwnerId": "me", field: value}, headers=AS
    )
    assert res.status_code == 400
    assert res.json() == {"error": code, "leagueKey": "main"}


def test_unreadable_config_is_a_stable_503(env, flags_on, monkeypatch, caplog):  # noqa: F811
    def broken(*_a, **_k):
        raise streaming.StreamingConfigError("streaming config unreadable: /SECRET/PATH")

    monkeypatch.setattr(streaming, "load_streaming_config", broken)
    with caplog.at_level(logging.ERROR):
        res = env.client.post(URL, json={"leagueKey": "main", "teamOwnerId": "me"}, headers=AS)
    assert res.status_code == 503
    assert res.json() == {
        "error": "idp_streaming_unavailable",
        "reason": "config_unreadable",
        "leagueKey": "main",
    }
    assert "SECRET" not in res.text


def test_unreadable_league_settings_503_carries_no_exception_text(
    env,  # noqa: F811
    flags_on,
    monkeypatch,
):
    async def broken_inputs(league_cfg, team_owner_id):
        return {"input_error": ValueError("SECRET-DETAIL")}

    monkeypatch.setattr(server, "_waiver_engine_inputs", broken_inputs)
    res = env.client.post(URL, json={"leagueKey": "main", "teamOwnerId": "me"}, headers=AS)
    assert res.status_code == 503
    assert res.json() == {
        "error": "idp_streaming_unavailable",
        "reason": "league_settings_unreadable",
        "leagueKey": "main",
    }
    assert "SECRET-DETAIL" not in res.text


@pytest.mark.parametrize(
    "code, status",
    [
        ("no_rosters_loaded", 503),
        ("unknown_team", 400),
        ("starter_slots_unknown", 503),
        ("not_in_season", 400),
        ("projections_refused", 503),
        ("drop_policy_unreadable", 503),
        ("league_mismatch", 503),
    ],
)
def test_composer_codes_map_to_stable_statuses(env, flags_on, monkeypatch, code, status):  # noqa: F811
    def raise_code(*_a, **_k):
        raise ValueError(code)

    monkeypatch.setattr(streaming, "compute_streaming", raise_code)
    res = env.client.post(URL, json={"leagueKey": "main", "teamOwnerId": "me"}, headers=AS)
    assert res.status_code == status
    assert res.json() == {"error": code, "leagueKey": "main"}


def test_unexpected_failure_never_leaks_text(env, flags_on, monkeypatch):  # noqa: F811
    def boom(*_a, **_k):
        raise ValueError("invalid literal SECRET-DETAIL")

    monkeypatch.setattr(streaming, "compute_streaming", boom)
    res = env.client.post(URL, json={"leagueKey": "main", "teamOwnerId": "me"}, headers=AS)
    assert res.status_code == 503
    assert res.json() == {"error": "idp_streaming_unavailable", "leagueKey": "main"}

    def crash(*_a, **_k):
        raise RuntimeError("SECRET-DETAIL")

    monkeypatch.setattr(streaming, "compute_streaming", crash)
    res = env.client.post(URL, json={"leagueKey": "main", "teamOwnerId": "me"}, headers=AS)
    assert res.status_code == 503
    assert "SECRET" not in res.text


def test_happy_path_passes_the_parsed_request_and_stamps_roster_source(
    env,  # noqa: F811
    flags_on,
    monkeypatch,
):
    seen = {}

    def fake_compute(plan_contract, *, league_key, owner_id, inputs, constraints, request, cfg):
        seen.update(
            league_key=league_key,
            owner_id=owner_id,
            request=request,
            cfg=cfg,
            teams=plan_contract["sleeper"]["teams"],
        )
        return {
            "contractVersion": streaming.CONTRACT_VERSION,
            "leagueKey": league_key,
            "team": {"ownerId": owner_id},
            "recommendMove": False,
            "noMoveReason": "below_materiality",
        }

    monkeypatch.setattr(streaming, "compute_streaming", fake_compute)
    res = env.client.post(
        URL,
        json={
            "leagueKey": "main",
            "teamOwnerId": "me",
            "week": 9,
            "horizonWeeks": 2,
            "position": "lb",
            "capacity": 2,
            "dynastyBudget": 150,
        },
        headers=AS,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["recommendMove"] is False
    assert body["advisoryOnly"] is True
    assert body["rosterSource"] == "contract"
    assert "rostersAsOf" in body
    assert body["valuationMode"] == "market"
    assert seen["league_key"] == "main" and seen["owner_id"] == "me"
    assert seen["request"]["position"] == "LB"
    assert seen["request"]["week"] == 9 and seen["request"]["horizonWeeks"] == 2
    assert seen["request"]["dynastyBudget"] == 150.0
    assert isinstance(seen["cfg"], streaming.StreamingConfig)
    assert [t["ownerId"] for t in seen["teams"]] == ["me", "them"]
