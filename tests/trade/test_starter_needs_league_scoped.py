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
* structural — ``DEFAULT_STARTER_NEEDS`` is private to the declared
  fallback sites (the W30-F006 required repair, stated as an AST guard
  in the same style as ``test_finder_va_is_not_bypassable``).
"""

from __future__ import annotations

import ast
from pathlib import Path

from src.trade.suggestions import (
    DEFAULT_STARTER_NEEDS,
    PlayerAsset,
    RosterAnalysis,
    TradeSuggestion,
    _generate_sell_high,
    _identity_key,
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

    def test_default_analysis_still_carries_the_dynasty_main_fallback(self):
        """No-op guard for the live league: an analysis built without
        explicit needs must behave exactly as before the threading —
        ``RosterAnalysis.starter_needs`` IS the constant then."""
        roster_names, pool = _one_te_league_pool()
        roster = analyze_roster(roster_names, pool)
        assert roster.starter_needs == DEFAULT_STARTER_NEEDS


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


class TestDefaultNeedsPrivateToFallback:
    """The W30-F006 required repair, structurally: ``DEFAULT_STARTER_NEEDS``
    may be read only where the FALLBACK is decided.  Any new read inside a
    generator, scorer or balancer helper is the historical drift coming
    back, whatever it is named at that point."""

    ALLOWED_SCOPES = {
        None,  # module level: the definition itself
        "starter_needs_for_league",  # registry-empty fallback
        "analyze_roster",  # caller-passed-nothing fallback
        "RosterAnalysis",  # dataclass default_factory
    }

    def test_default_starter_needs_is_read_only_at_fallback_sites(self):
        tree = ast.parse(SUGGESTIONS_PATH.read_text(encoding="utf-8"))

        offenders: list[str] = []

        def walk(node: ast.AST, scope: str | None) -> None:
            for child in ast.iter_child_nodes(node):
                child_scope = scope
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    child_scope = child.name
                if (
                    isinstance(child, ast.Name)
                    and child.id == "DEFAULT_STARTER_NEEDS"
                    and scope not in self.ALLOWED_SCOPES
                ):
                    offenders.append(f"{scope}:{child.lineno}")
                walk(child, child_scope)

        walk(tree, None)
        assert offenders == [], (
            "DEFAULT_STARTER_NEEDS (dynasty_main's demand model) is read "
            f"outside its declared fallback sites: {offenders}. Consumers "
            "must read RosterAnalysis.starter_needs — the league's own "
            "demand — instead (W30-F006 / V1-25)."
        )
