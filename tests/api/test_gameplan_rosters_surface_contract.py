"""Pins the ``GET /api/gameplan`` fields the /rosters "Team Gameplan" section reads.

Owner decision 2026-11-07 (W20-F001): ``/rosters`` is the primary frontend consumer of
the Team Gameplan.  ``frontend/lib/gameplan-view.js`` reads exactly the fields below and
nothing else, so a rename here must fail loudly rather than silently blank the section.

Deliberately NOT surfaced (and so not pinned as a contract): ``roster.values.market`` /
``consensus`` / ``leagueAdjusted`` -- on current code they are still ``0.0`` for every
team (master audit W20-F010: a fake zero, and ``leagueAdjusted`` is a withdrawn lens) --
and ``partners`` / ``packages`` (engine scores with declared evidence ceilings).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import server
from src.api import gameplan
from src.roster_intel.window import COMPETITIVE_STATES, POSTURE_LABELS
from tests.api.test_gameplan_endpoint import _install_contract, _payload, league  # noqa: F401


def test_posture_is_attached_from_the_canonical_owner(league, monkeypatch):  # noqa: F811
    body = _payload(monkeypatch)
    posture = body["competitivePosture"]
    assert posture["available"] is True
    assert posture["label"] in POSTURE_LABELS
    assert posture["evidence"] in ("measured", "none")
    assert posture["isVerdict"] is False
    assert posture["owner"].startswith("src/roster_intel/window.py")
    if posture["evidence"] == "none":
        assert posture["confidence"] is None  # never a fake 100%
    else:
        assert 0.0 <= posture["confidence"] <= 1.0


def test_posture_matches_the_trade_surface_owner_for_the_same_team(league, monkeypatch):  # noqa: F811
    body = _payload(monkeypatch)
    postures, _meta = gameplan.league_competitive_postures(
        "main", "prof_a", server.latest_contract_data
    )
    assert body["competitivePosture"]["label"] == postures["owner0"].label


def test_posture_unavailable_is_explicit_not_omitted(league, monkeypatch):  # noqa: F811
    def boom(*a, **k):
        raise gameplan.GameplanUnavailable("league_bundle_not_warm", "x")

    monkeypatch.setattr(gameplan, "league_competitive_postures", boom)
    body = _payload(monkeypatch)
    assert body["competitivePosture"] == {
        "available": False,
        "unavailableReason": "league_bundle_not_warm",
    }


def test_surfaced_roster_fields_exist(league, monkeypatch):  # noqa: F811
    body = _payload(monkeypatch)
    roster = body["roster"]
    window = roster["competitiveWindow"]
    assert window["mostLikely"] in COMPETITIVE_STATES
    assert "confidence" in window and "affinities" in window
    weakness = roster["weakness"]
    assert isinstance(weakness["available"], bool)
    assert isinstance(weakness["needs"], list)
    assert isinstance(weakness["urgentPositions"], list)
    assert roster["positions"], "fixture produced no positional profiles"
    for pos in roster["positions"].values():
        assert "position" in pos
        assert "tradeableSurplus" in pos
        assert isinstance(pos["surplusPlayers"], list)
    assert "oddsSource" in roster
    assert "championshipOdds" in roster  # may be null = unmeasured


def test_surfaced_opportunity_fields_exist(league, monkeypatch):  # noqa: F811
    body = _payload(monkeypatch)
    assert body["targetPositions"]
    for t in body["targetPositions"]:
        assert {"position", "viability", "reason"} <= set(t)
    assert body["targetPlayers"]
    for t in body["targetPlayers"]:
        assert {"playerId", "name", "position", "recommended", "reason"} <= set(t)


def test_withheld_values_block_is_still_the_audited_fake_zero_shape(league, monkeypatch):  # noqa: F811
    """Documents WHY the UI withholds ``roster.values``: the market / consensus /
    leagueAdjusted lanes are not measured by this endpoint.  If this starts failing the
    lanes were repaired -- revisit the withhold decision, do not just delete the test."""
    values = _payload(monkeypatch)["roster"]["values"]
    assert values["market"] == 0.0 and values["consensus"] == 0.0
    assert values["leagueAdjusted"] == 0.0
    assert values["pickValue"] is None and values["pickValueState"] == "unavailable"


def test_route_still_returns_posture_over_http(league, monkeypatch):  # noqa: F811
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        res = c.get("/api/gameplan?team=owner0")
    assert res.status_code == 200
    assert "competitivePosture" in res.json()
