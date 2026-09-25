"""V1-25 — league-config consistency: the suggestion engine's starter
demand follows the LEAGUE, never the ``dynasty_main`` constant.

Residual drift behind W18-F005/W18-F011 (finding W30-F006): the entry
point threaded ``starter_needs_for_league`` into ``analyze_roster`` and
nothing else.  Every generator, both rank scorers and the
balancer-candidate picker read ``DEFAULT_STARTER_NEEDS`` — dynasty_main's
lineup — unconditionally, so in the 1-TE league the engine flagged a TE
surplus and then never offered the TE2 it had just called surplus
(``players[2:]`` with the other league's ``need = 2``).

The repair stores the resolved demand on ``RosterAnalysis.starter_needs``
and every consumer reads it from there.  These tests go RED if any of the
historical hardcodes is reintroduced:

* behavioral — a 1-TE-demand league's sell-high offers the TE2;
  ``rank_score`` grades need severity against the league's own demand;
* structural — there is no default lineup to fall back to at all
  (canonical-need-priority, 2026-09-24).  This file used to pin the
  ``dynasty_main`` constant as a declared FALLBACK; the fallback itself was
  the defect — every opponent analysis and both FAAB need paths reached it
  by passing nothing — so it is gone and an absent demand fails closed.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.trade.suggestions import (
    PlayerAsset,
    RosterAnalysis,
    TradeSuggestion,
    _generate_sell_high,
    _identity_key,
    _analyze_opponent_rosters,
    _roster_balancer_candidates,
    analyze_roster,
    generate_suggestions_from_pool,
    rank_score_breakdown,
)

REPO = Path(__file__).resolve().parents[2]
SUGGESTIONS_PATH = REPO / "src" / "trade" / "suggestions.py"

#: dynasty_new's derived demand (host truth, W18-F011: 10-team, 1 TE,
#: FLEX + WR/RB-only WRRB_FLEX, superflex, no IDP).  Passed explicitly so
#: these tests stay hermetic — the threading is what is under test, not
#: the registry read (that is pinned in
#: tests/league_intel/test_registry_consumers.py).
ONE_TE_NEEDS = {"QB": 2, "RB": 4, "WR": 3, "TE": 1}


def _player(name: str, pos: str, value: int) -> PlayerAsset:
    return PlayerAsset(
        name=name,
        position=pos,
        display_value=value,
        calibrated_value=value,
        source_count=3,
    )


def _one_te_league_pool() -> tuple[list[str], list[PlayerAsset]]:
    """A roster with a genuine TE surplus under 1-TE demand, plus an
    unrostered QB target priced inside FAIRNESS_TOLERANCE of the TE2."""
    rostered = [
        _player("Te One", "TE", 7000),
        _player("Te Two", "TE", 6800),
        _player("Te Three", "TE", 6600),
        _player("Qb One", "QB", 5000),
        _player("Rb One", "RB", 4000),
        _player("Wr One", "WR", 4000),
    ]
    pool = rostered + [
        _player("Qb Target", "QB", 6700),
        _player("Wr Target", "WR", 6500),
    ]
    roster_names = [p.name for p in rostered]
    return roster_names, pool


class TestSellHighFollowsLeagueDemand:
    def test_te2_is_a_sell_candidate_when_the_league_starts_one_te(self):
        """The exact W30-F006 numeric proof: under 1-TE demand the sell
        window is ``players[1:]``, so the TE2 must be offerable.  The
        retired hardcode sliced ``players[2:]`` (dynasty_main's TE 2) and
        the TE2 could never be offered in the league that starts one."""
        roster_names, pool = _one_te_league_pool()
        roster = analyze_roster(roster_names, pool, ONE_TE_NEEDS)
        assert "TE" in roster.surplus_positions  # premise, not the claim
        suggestions = _generate_sell_high(roster, pool, {_identity_key(n) for n in roster_names})
        given = {p.name for s in suggestions for p in s.give}
        assert "Te Two" in given, (
            "TE2 not offered from a surplus room in a 1-TE league — the "
            "generator is slicing with a demand model that is not this "
            "league's (W30-F006 reintroduced)"
        )

    def test_end_to_end_entry_point_threads_the_league_demand(self):
        roster_names, pool = _one_te_league_pool()
        out = generate_suggestions_from_pool(
            roster_names=roster_names,
            pool=pool,
            starter_needs=ONE_TE_NEEDS,
            board_top_n=0,
        )
        assert out["metadata"]["starterNeeds"] == ONE_TE_NEEDS
        given = {p["name"] for s in out["sellHigh"] for p in s["give"]}
        assert "Te Two" in given


class TestRankScoreFollowsLeagueDemand:
    def test_need_severity_is_graded_on_the_leagues_own_demand(self):
        """A roster holding its league's ONE required TE starter has no
        TE need severity.  Grading it against dynasty_main's TE 2 (the
        retired hardcode) manufactures severity 1.0."""
        te = _player("Te Incoming", "TE", 6000)
        suggestion = TradeSuggestion(
            type="buy_low",
            give=[_player("Rb Out", "RB", 6000)],
            receive=[te],
            give_total=6000,
            receive_total=6000,
            gap=0,
            fairness="even",
            rationale="",
            why_this_helps="",
            confidence="high",
            strategy="neutral",
        )
        roster = RosterAnalysis(
            roster_size=10,
            by_position={},
            surplus_positions=[],
            need_positions=["TE"],
            starter_counts={"TE": 1},
            depth_counts={},
            starter_needs=dict(ONE_TE_NEEDS),
        )
        breakdown = rank_score_breakdown(suggestion, roster)
        assert breakdown["need_severity"] == 0.0

    def test_an_analysis_without_league_demand_is_refused(self):
        """There is no default lineup.  The retired fallback silently
        measured the roster against ``dynasty_main``'s demand."""
        roster_names, pool = _one_te_league_pool()
        with pytest.raises(ValueError, match="no default lineup"):
            analyze_roster(roster_names, pool)
        with pytest.raises(ValueError):
            analyze_roster(roster_names, pool, {})


class TestOpponentsShareTheLeaguesDemand:
    """The measured defect: opponent rosters were analysed with NO demand,
    i.e. against ``dynasty_main``'s lineup, whatever league was asking."""

    def test_opponent_analysis_uses_the_requesting_leagues_demand(self):
        roster_names, pool = _one_te_league_pool()
        # One rival holding two TEs: a TE SURPLUS in a 1-TE league, and no
        # surplus at all under dynasty_main's TE 2.
        rival = {"team_name": "Rival", "players": ["Te One", "Te Two", "Te Three"]}
        out = _analyze_opponent_rosters([rival], pool, starter_needs=ONE_TE_NEEDS)
        assert out["Rival"].starter_needs == ONE_TE_NEEDS
        assert "TE" in out["Rival"].surplus_positions

    def test_the_entry_point_hands_opponents_the_same_demand(self, monkeypatch):
        from src.trade import suggestions as S

        seen: list[dict] = []
        real = S._analyze_opponent_rosters

        def spy(rosters, pool, *, starter_needs):
            seen.append(dict(starter_needs))
            return real(rosters, pool, starter_needs=starter_needs)

        monkeypatch.setattr(S, "_analyze_opponent_rosters", spy)
        roster_names, pool = _one_te_league_pool()
        generate_suggestions_from_pool(
            roster_names=roster_names,
            pool=pool,
            starter_needs=ONE_TE_NEEDS,
            league_rosters=[{"team_name": "Rival", "players": ["Qb Target"]}],
            board_top_n=0,
        )
        assert seen == [ONE_TE_NEEDS]


class TestUnresolvedLeagueFailsClosed:
    def test_no_demand_returns_an_explained_empty_result(self):
        """An unresolvable league's lineup is UNKNOWN: say so, with the wire
        keys the endpoint normally returns, rather than suggest trades
        measured against another league's lineup."""
        roster_names, pool = _one_te_league_pool()
        out = generate_suggestions_from_pool(
            roster_names=roster_names, pool=pool, starter_needs=None, board_top_n=0
        )
        assert out["metadata"]["noResultReason"] == "league_lineup_unresolved"
        assert out["metadata"]["starterNeeds"] is None
        for key in ("sellHigh", "buyLow", "consolidation", "positionalUpgrades"):
            assert out[key] == []
        assert out["totalSuggestions"] == 0
        assert out["warnings"]


class TestBalancerCandidatesFollowLeagueDemand:
    def test_te2_is_an_offerable_balancer_in_a_one_te_league(self):
        roster_names, pool = _one_te_league_pool()
        roster = analyze_roster(roster_names, pool, ONE_TE_NEEDS)
        candidates = _roster_balancer_candidates(roster, set())
        names = {c.name for c in candidates}
        assert "Te Two" in names, (
            "balancer eligibility protected a 'starter' slot this league "
            "does not have (W30-F006 reintroduced)"
        )


class TestNoDefaultLineupExists:
    """The W30-F006 structural guard, tightened.  It used to allow the
    ``dynasty_main`` constant at three declared fallback sites; every one of
    those was the silent default this unit removed.  Now the constant may
    not exist at all, and ``analyze_roster`` may not default its demand."""

    def test_the_dynasty_main_constant_is_gone(self):
        from src.trade import suggestions as S

        assert not hasattr(S, "DEFAULT_STARTER_NEEDS")

    def test_analyze_roster_has_no_default_demand(self):
        tree = ast.parse(SUGGESTIONS_PATH.read_text(encoding="utf-8"))
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "analyze_roster"
        )
        src = ast.unparse(fn)
        assert "starter_needs or " not in src, "a fallback demand is back in analyze_roster"
