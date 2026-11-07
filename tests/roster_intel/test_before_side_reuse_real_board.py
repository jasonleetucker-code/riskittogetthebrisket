"""Before-roster reuse is exact on a REAL board (five-point review, 2026-10-20).

``test_best_ball_utility_reuse`` proves the reuse on synthetic rosters.  This
runs the trade simulator's roster utility over the newest complete archived
board — real 58-man rosters, real starter slots, real IDP — for the scenario
shapes Analyze Trade serves (a simple 1-for-1, a large multi-asset package,
several picks, IDP-heavy, cross-position) and asserts the content-addressed
reuse answers byte-identically to computing everything fresh.

Projections are the one input the archive does not carry (the ensemble reads
box-local snapshots), so a deterministic per-player points table stands in for
``league_scored_ppg_by_id``; the property under test — reuse equals fresh —
does not depend on which numbers the table holds.  No network: the players DB
read used for availability is stubbed out.
"""

from __future__ import annotations

import json
import random
import zlib
from pathlib import Path

import pytest

from src.api import trade_simulator
from src.roster_intel import best_ball_utility as bbu
from src.trade import roster_capacity
from tests.archive_fixtures import newest_complete_raw_payload

IDP = {"DL", "LB", "DB", "DE", "DT", "CB", "S", "EDGE"}
_REGISTRY = Path(__file__).resolve().parents[2] / "config" / "leagues" / "registry.json"


def _league_roster_settings() -> list[tuple[str, dict]]:
    """Every configured league's roster settings, read straight from the
    committed registry (the test process points the registry loader at a
    nonexistent path).  Two real configurations: a 58-man IDP superflex and
    a 27-man taxi league with a WR/RB flex, so the same archived rosters are
    also exercised over the cap (forced drops / cleanup roster)."""
    try:
        doc = json.loads(_REGISTRY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    leagues = doc.get("leagues", doc)
    rows = leagues if isinstance(leagues, list) else list(leagues.values())
    return [
        (str(r.get("key")), dict(r.get("rosterSettings") or {}))
        for r in rows
        if isinstance(r, dict) and r.get("rosterSettings")
    ]


@pytest.fixture(scope="module")
def board():
    raw, _name = newest_complete_raw_payload()
    if raw is None:
        pytest.skip("no complete archived board in exports/archive")
    from src.api.data_contract import build_api_data_contract

    contract = build_api_data_contract(raw)
    teams = [t for t in (contract.get("sleeper") or {}).get("teams") or [] if t.get("players")]
    if len(teams) < 2:
        pytest.skip("archived board carries no league rosters")
    return contract, teams


@pytest.fixture
def deterministic_projections(monkeypatch):
    def ppg(player_ids, *, season, scoring_settings):
        out = {}
        for pid in player_ids:
            h = zlib.crc32(str(pid).encode())
            if h % 9 == 0:
                continue  # some players unprojected: UNKNOWN, never 0
            out[str(pid)] = round(2.0 + (h % 2200) / 100.0, 2)
        return out, {"state": "available", "source": "test-deterministic"}

    monkeypatch.setattr(bbu, "league_scored_ppg_by_id", ppg)
    monkeypatch.setattr(roster_capacity, "_players_meta_for", lambda _ids: {})
    bbu.clear_before_side_cache()
    yield
    bbu.clear_before_side_cache()


def _scenarios(contract, teams):
    rng = random.Random(1828)
    pos = {
        (r.get("displayName") or r.get("canonicalName")): str(r.get("position") or "").upper()
        for r in contract.get("playersArray") or []
    }

    def take(team, n, ok=lambda p: True):
        names = [p for p in team["players"] if p in pos and ok(pos[p])]
        rng.shuffle(names)
        return names[:n]

    offense = lambda p: p in ("QB", "RB", "WR", "TE")  # noqa: E731
    me, other = teams[0], teams[len(teams) // 2]
    return [
        (
            "simple_1v1",
            me,
            {"players_out": take(me, 1, offense), "players_in": take(other, 1, offense)},
        ),
        (
            "large_multi",
            me,
            {
                "players_out": take(me, 4),
                "players_in": take(other, 3),
                "picks_in": list((other.get("picks") or [])[:1]),
            },
        ),
        (
            "multi_picks",
            me,
            {"players_out": take(me, 1, offense), "picks_in": list((other.get("picks") or [])[:4])},
        ),
        (
            "idp_heavy",
            me,
            {
                "players_out": take(me, 3, IDP.__contains__),
                "players_in": take(other, 3, IDP.__contains__),
            },
        ),
        (
            "cross_position",
            other,
            {
                "players_out": take(other, 1, lambda p: p == "QB"),
                "players_in": take(me, 1, IDP.__contains__) + take(me, 1, offense),
            },
        ),
    ]


def _utility(contract, team, trade, *, reuse: bool, roster_settings: dict, league: str):
    real = bbu.evaluate_trade_utility

    def no_reuse(**kw):
        return real(**{**kw, "cache_scope": None})

    if not reuse:
        bbu.evaluate_trade_utility = no_reuse
    try:
        out = trade_simulator.simulate_trade(
            contract,
            resolved_team=team,
            league_key=league,
            roster_settings=roster_settings,
            include_roster_utility=True,
            competitive_posture=None,
            **trade,
        )
    finally:
        bbu.evaluate_trade_utility = real
    return json.dumps(out.get("rosterUtility"), sort_keys=True, default=str)


@pytest.mark.parametrize(
    "league,roster_settings",
    _league_roster_settings() or [pytest.param("none", {}, marks=pytest.mark.skip("no registry"))],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_reused_before_side_equals_fresh_on_the_real_board(
    board, deterministic_projections, league, roster_settings
):
    contract, teams = board
    measured = 0
    kw = {"roster_settings": roster_settings, "league": league}
    for kind, team, trade in _scenarios(contract, teams):
        cold = _utility(contract, team, trade, reuse=True, **kw)  # computes + stores
        warm = _utility(contract, team, trade, reuse=True, **kw)  # reuses the entry
        fresh = _utility(contract, team, trade, reuse=False, **kw)  # never reuses
        assert cold == warm == fresh, kind
        measured += json.loads(fresh).get("available") is True
    if measured == 0:
        pytest.skip("roster utility unavailable on this board (no starter slots resolved)")
    # Every scenario was actually simulated, not degraded to "unavailable".
    assert measured == len(_scenarios(contract, teams))
    assert bbu.before_side_stats["reused"] > 0
