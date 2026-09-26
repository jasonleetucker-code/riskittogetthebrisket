"""Trade War Room wiring — #1173 utility on the #843 final legal roster, #842 mode.

Uses the synthetic league of ``tests/api/test_trade_nfl_exposure`` (an 8-man
roster cap, 7 rostered: one open spot).  Projections are injected at the
projection-basis seam (``league_scored_ppg_by_id``) so the tests pin the
WIRING — which rosters are evaluated, what is named unavailable, what the
endpoint does with ``useTeamContext`` — not the projection data.
"""

from __future__ import annotations

import pytest

from src.api import trade_simulator
from src.roster_intel import best_ball_utility as bbu
from tests.api.test_league_routing import two_league_registry  # noqa: F401 — fixture
from tests.api.test_trade_nfl_exposure import _SETTINGS, _contract, _post, _us

PPG = {
    "qb min": 20.0,
    "rb min": 12.0,
    "wr kc": 14.0,
    "wr phi": 8.0,
    "te free": 6.0,
    "wr buf star": 19.0,
    "rb buf depth": 4.0,
}


@pytest.fixture(autouse=True)
def _projections(monkeypatch):
    seen: list[list[str]] = []

    def fake(ids, season, scoring_settings):
        seen.append(list(ids))
        return (
            {i: PPG[i.lower()] for i in ids if i.lower() in PPG},
            {"state": "available", "source": "TEST_PROJECTIONS", "season": season},
        )

    monkeypatch.setattr(bbu, "league_scored_ppg_by_id", fake)
    monkeypatch.setattr("src.bdvm.actuals.current_nfl_season", lambda today=None: 2026)
    return seen


def _sim(players_in=(), players_out=(), picks_in=(), picks_out=(), **kw):
    c = _contract()
    return trade_simulator.simulate_trade(
        c,
        resolved_team=kw.pop("team", _us(c)),
        players_in=list(players_in),
        players_out=list(players_out),
        picks_in=list(picks_in),
        picks_out=list(picks_out),
        roster_settings=_SETTINGS,
        **kw,
    )


def test_plain_simulate_does_not_run_the_utility():
    r = _sim(["WR Buf Star"], ["WR Kc"])
    assert "rosterUtility" not in r


def test_consolidation_fits_and_is_evaluated_on_the_landed_roster():
    r = _sim(["WR Buf Star"], ["WR Kc", "WR Phi"], include_roster_utility=True)
    u = r["rosterUtility"]
    assert u["available"] is True
    assert u["cleanup"]["state"] == "none"
    assert u["shape"]["label"] == "consolidation"
    roles = {p["name"]: p["role"] for p in u["players"]}
    assert roles["WR Buf Star"] == "incoming"
    assert roles["WR Kc"] == roles["WR Phi"] == "outgoing"


def test_forced_cleanup_uses_the_capacity_owners_own_drops():
    # 2 in, 0 out on a 7/8 roster: one release required.
    r = _sim(["WR Buf Star", "RB Buf Depth"], [], include_roster_utility=True)
    cap = r["rosterCapacity"]
    assert cap["requiresDrops"] is True
    u = r["rosterUtility"]
    assert u["cleanup"]["state"] == "applied"
    # No second cut selection: exactly the capacity answer's drops.
    assert u["cleanup"]["forcedDropIds"] == [d["playerId"] for d in cap["forcedDrops"]]
    dropped = {p["playerId"] for p in u["players"] if p["role"] == "forcedDrop"}
    assert dropped == set(u["cleanup"]["forcedDropIds"])
    # The apparent gain and the gain once legal are both published.
    assert u["impact"]["ppgBeforeCleanup"] is not None
    assert u["afterBeforeCleanup"] is not None
    # The same cleanup Team Strength was re-solved against.
    frs = r["finalRosterSimulation"]
    assert [d["playerId"] for d in frs["cleanupApplied"]] == u["cleanup"]["forcedDropIds"]


def test_picks_never_reach_the_roster_utility(_projections):
    r = _sim(["WR Buf Star"], ["WR Kc"], picks_out=["2027 Round 1"], include_roster_utility=True)
    priced_ids = {i.lower() for call in _projections for i in call}
    assert "2027 round 1" not in priced_ids
    assert all(
        p["role"] != "outgoing" or p["name"] != "2027 Round 1"
        for p in r["rosterUtility"]["players"]
    )
    assert r["rosterCapacity"]["sizeAfter"] == r["rosterCapacity"]["sizeBefore"]


def test_an_unpriced_traded_player_makes_coverage_partial_not_zero():
    r = _sim(["WR Buf Star"], ["RB Unpriced"], include_roster_utility=True)
    u = r["rosterUtility"]
    assert u["coverage"]["state"] == "partial"
    row = next(p for p in u["players"] if p["name"] == "RB Unpriced")
    assert row["projectedPpg"] is None
    assert row["lineupEntryPctBefore"] is None


def test_no_team_is_named_unavailable():
    r = _sim(["WR Buf Star"], ["WR Kc"], team=None, include_roster_utility=True)
    assert r["rosterUtility"] == {"available": False, "unavailableReason": "no_team_selected"}


def test_unresolved_season_is_named_unavailable(monkeypatch):
    monkeypatch.setattr("src.bdvm.actuals.current_nfl_season", lambda today=None: None)
    r = _sim(["WR Buf Star"], ["WR Kc"], include_roster_utility=True)
    assert r["rosterUtility"]["available"] is False
    assert r["rosterUtility"]["unavailableReason"] == "season_unresolved"


def test_missing_projection_snapshot_is_named_unavailable(monkeypatch):
    monkeypatch.setattr(
        bbu,
        "league_scored_ppg_by_id",
        lambda ids, season, scoring_settings: (
            {},
            {"state": "unavailable", "reason": "no_projection_snapshot"},
        ),
    )
    r = _sim(["WR Buf Star"], ["WR Kc"], include_roster_utility=True)
    assert r["rosterUtility"]["unavailableReason"] == "projection_basis_no_projection_snapshot"


def test_resolved_assets_carry_canonical_identity_and_confidence_stamps():
    r = _sim(["WR Buf Star"], ["WR Kc"])
    for asset in (*r["receiving"], *r["sending"]):
        assert {"playerId", "confidenceBucket", "hasSourceDisagreement"} <= set(asset)


# ── Endpoint: /api/trade/analyze and Use Team Context ────────────────────


_BODY = {"leagueKey": "main", "team": "o1", "playersIn": ["WR Buf Star"], "playersOut": ["WR Kc"]}


def test_analyze_defaults_to_team_context(two_league_registry, monkeypatch):  # noqa: F811
    res = _post(monkeypatch, "/api/trade/analyze", _BODY)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["teamContext"] == {"applied": True, "mode": "team"}
    # The utility RAN (Team Context on).  This shared test registry declares no
    # starting slots, so it names that instead of solving — the solved path is
    # pinned by the direct simulate tests above.
    assert body["rosterUtility"] == {
        "available": False,
        "unavailableReason": "starter_slots_unresolved",
    }
    assert body["analysis"]["lenses"]["roster"]["unavailableReason"] == "starter_slots_unresolved"
    assert body["analysis"]["version"] == "analyze_trade_v2"
    assert body["analysis"]["lenses"]["roster"]["lineage"] == "league_scored_projection"
    assert body["leagueKey"] == "main"


def test_analyze_asset_only_skips_roster_and_keeps_values(two_league_registry, monkeypatch):  # noqa: F811
    on = _post(monkeypatch, "/api/trade/analyze", _BODY).json()
    off = _post(monkeypatch, "/api/trade/analyze", {**_BODY, "useTeamContext": False}).json()
    assert off["teamContext"] == {"applied": False, "mode": "asset_only"}
    assert "rosterUtility" not in off
    assert off["analysis"]["lenses"]["roster"]["unavailableReason"] == "asset_only_mode"
    assert off["receiving"] == on["receiving"] and off["sending"] == on["sending"]
    assert off["analysis"]["lenses"]["market"] == on["analysis"]["lenses"]["market"]


@pytest.mark.parametrize("raw", ["false", 0, None, "off"])
def test_only_a_boolean_false_turns_context_off(two_league_registry, monkeypatch, raw):  # noqa: F811
    body = _post(monkeypatch, "/api/trade/analyze", {**_BODY, "useTeamContext": raw}).json()
    assert body["teamContext"]["applied"] is True


def test_simulate_endpoint_is_unchanged_by_the_war_room(two_league_registry, monkeypatch):  # noqa: F811
    body = _post(monkeypatch, "/api/trade/simulate", _BODY).json()
    assert "rosterUtility" not in body
    assert "teamContext" not in body
