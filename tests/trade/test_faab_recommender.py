"""Tests for the FAAB recommender adapter.

This file used to pin the OLD recommender, which WAS the model: a
pool-relative baseline multiplied by a value-gain modifier, a Sleeper
trending kicker, a league-historical position blend, a budget-
environment scale and a rival-contention raise.  Those mechanisms are
gone by design — they compounded without bound, they read one demand
signal four separate times, and every one of them moved the BID when
most of them described the player's VALUE or the market's PRICE.

What is pinned now is the contract the adapter must honour:

* the legacy response keys still exist and still mean something
* ``max`` is the MAX RATIONAL bid, not merely the team's balance
* demand signals are reported as evidence, never multiplied into the bid
* aggression falls back from fitted history to the live analytics block
* missing inputs lower confidence instead of silently changing the answer

The model itself is tested in ``tests/trade/test_faab_engine.py`` and
calibrated against human + historical anchors in
``tests/trade/test_faab_calibration.py``.
"""

from __future__ import annotations

import pytest

from src.trade import faab_engine as engine
from src.trade.faab_recommender import (
    _aggression_from_league_summary,
    build_rivals,
    compute_confidence,
    recommend_faab,
)


# A synthetic board with the same shape as the real one (dense at the
# top, long tail) so anchor resolution has something to bite on.
BOARD = [9999 - i * 12 for i in range(700)]


def _rivals(n: int = 11, remaining: int = 100):
    return [engine.RivalTeam(owner_id=f"r{i}", faab_remaining=remaining) for i in range(n)]


def _rec(**overrides):
    # A realistic rival field by default.  With NO rivals the
    # expected-surplus optimum is correctly $0 for every player (an
    # uncontested claim costs nothing), which is right but makes the
    # team-layer assertions degenerate.
    kwargs = dict(
        add_player_value=6000.0,
        add_player_name="Target",
        add_player_position="WR",
        league_budget=100,
        board_values=BOARD,
        team_faab_remaining=100,
        rivals=_rivals(),
    )
    kwargs.update(overrides)
    return recommend_faab(**kwargs)


# ── Response contract ────────────────────────────────────────────────


class TestResponseContract:
    def test_minimal_inputs_return_the_full_shape(self):
        out = recommend_faab(add_player_value=4000)
        assert set(out.keys()) >= {
            "conservative",
            "standard",
            "aggressive",
            "max",
            "confidence",
            "factors",
            "warnings",
            "explanation",
            "objective",
            "bids",
        }

    def test_legacy_keys_survive(self):
        rec = _rec()
        for key in ("conservative", "standard", "aggressive", "max", "confidence"):
            assert key in rec, key
        assert isinstance(rec["factors"], list)
        assert isinstance(rec["warnings"], list)
        assert isinstance(rec["explanation"], str)

    def test_new_keys_separate_worth_from_bid(self):
        rec = _rec()
        assert set(rec["objective"]) >= {"dollars", "pctOfOriginalBudget", "originalBudget"}
        assert set(rec["bids"]) == {
            "recommended",
            "conservative",
            "aggressive",
            "maxRational",
            "clearing",
        }

    def test_standard_is_the_recommended_bid(self):
        rec = _rec()
        assert rec["standard"] == rec["bids"]["recommended"]

    def test_max_is_a_value_ceiling_not_just_the_balance(self):
        """The old ``max`` was literally ``faabRemaining``, which made
        it useless as a ceiling: it said what you could afford, never
        what the player was worth.  A marginal player must now cap
        below a full balance."""
        marginal = _rec(add_player_value=1500.0, team_faab_remaining=100)
        assert marginal["max"] < 100

    def test_recommendation_never_exceeds_the_balance(self):
        for remaining in (0, 1, 7, 43):
            rec = _rec(add_player_value=9999.0, team_faab_remaining=remaining)
            assert rec["bids"]["recommended"] <= remaining
            assert rec["bids"]["aggressive"] <= remaining
            assert rec["bids"]["maxRational"] <= remaining

    def test_bid_ladder_is_ordered(self):
        for value in (1200, 1900, 2400, 4000, 9999):
            rec = _rec(add_player_value=float(value))
            b = rec["bids"]
            assert b["conservative"] <= b["recommended"] <= b["aggressive"] <= b["maxRational"]


# ── Objective value is budget-independent ────────────────────────────


class TestObjectiveValueIsIndependent:
    def test_objective_value_ignores_what_the_team_has_spent(self):
        """The headline requirement: a player does not become worth
        less because the manager already spent."""
        flush = _rec(team_faab_remaining=100)["objective"]
        broke = _rec(team_faab_remaining=3)["objective"]
        assert flush["dollars"] == broke["dollars"]
        assert flush["pctOfOriginalBudget"] == broke["pctOfOriginalBudget"]

    def test_objective_value_ignores_the_drop_side(self):
        no_drop = _rec()["objective"]["dollars"]
        with_drop = _rec(drop_player_value=5000.0, drop_player_name="Costly")["objective"][
            "dollars"
        ]
        assert no_drop == with_drop

    def test_objective_value_scales_with_the_original_budget(self):
        at_100 = _rec(league_budget=100)["objective"]["dollars"]
        at_200 = _rec(league_budget=200)["objective"]["dollars"]
        assert at_200 == pytest.approx(2 * at_100, abs=1)


# ── Demand signals are evidence, not multipliers ─────────────────────


class TestDemandSignalsAreNotMultipliers:
    def test_trending_does_not_change_the_objective_value(self):
        """Trending is market demand.  It can raise the price you must
        pay; it must never raise what the player is worth."""
        cold = _rec(sleeper_trending={"count": 0})
        hot = _rec(sleeper_trending={"count": 90000})
        assert cold["objective"]["dollars"] == hot["objective"]["dollars"]

    def test_trending_is_reported_as_a_factor(self):
        rec = _rec(sleeper_trending={"count": 12000, "asOf": _fresh_stamp()})
        row = next(f for f in rec["factors"] if f["label"] == "Trending adds")
        assert not row["missing"]
        assert "12,000" in row["contribution"]

    def test_missing_trending_is_marked_missing(self):
        rec = _rec(sleeper_trending=None)
        row = next(f for f in rec["factors"] if f["label"] == "Trending adds")
        assert row["missing"] is True


def _fresh_stamp(age_s: float = 0.0) -> str:
    import datetime as _dt

    return (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(seconds=age_s)).isoformat()


class TestStaleTrendingIsNotPresentEvidence:
    """``sleeper_trending`` serves the previous snapshot when a fetch fails,
    deliberately and with no absolute cap.  A consumer that ignores the age
    reports a claim about "the last 24h" that can be arbitrarily old, and —
    worse — counts it as realised evidence, so a dead upstream holds the
    reported confidence up.
    """

    @staticmethod
    def _row(trending, **kw):
        from src.trade.faab_recommender import _demand_evidence_factors

        rows = _demand_evidence_factors(trending, "Target", **kw)
        return next(r for r in rows if r["label"] == "Trending adds")

    def test_a_fresh_observation_still_states_the_count(self):
        row = self._row({"count": 1200, "asOf": _fresh_stamp(60)})
        assert row.get("missing") is not True
        assert "1,200 adds in the last 24h" == row["contribution"]

    def test_a_stale_observation_is_missing_evidence(self):
        from src.trade.faab_contention import STALENESS_MAX_AGE_S

        row = self._row({"count": 1200, "asOf": _fresh_stamp(STALENESS_MAX_AGE_S["trending"] + 60)})
        assert row["missing"] is True
        assert "last 24h" not in row["contribution"]

    def test_a_stale_observation_says_when_it_was_observed(self):
        """Naming the observation time is the honest replacement for an
        assertion about a window that has passed."""
        row = self._row({"count": 1200, "asOf": _fresh_stamp(36 * 3600)})
        assert "36h ago" in row["contribution"]

    def test_an_unmeasurable_age_is_stale_not_fresh(self):
        assert self._row({"count": 1200})["missing"] is True
        assert self._row({"count": 1200, "asOf": None})["missing"] is True
        assert self._row({"count": 1200, "asOf": "not-a-date"})["missing"] is True

    def test_the_boundary_is_the_shared_ceiling_not_a_local_literal(self):
        from src.trade.faab_contention import STALENESS_MAX_AGE_S

        budget = STALENESS_MAX_AGE_S["trending"]
        assert self._row({"count": 1, "asOf": _fresh_stamp(budget - 60)}).get("missing") is not True
        assert self._row({"count": 1, "asOf": _fresh_stamp(budget + 60)})["missing"] is True

    def test_the_ceiling_is_not_duplicated_in_the_recommender(self):
        """One owner for the budget.  A literal copied into the recommender
        is how the factor row and ``stale_inputs`` came to disagree in the
        first place, so the absence of one is asserted structurally."""
        import ast

        from src.utils.config_loader import repo_root

        src = (repo_root() / "src" / "trade" / "faab_recommender.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_demand_evidence_factors"
        )
        numbers = {
            n.value
            for n in ast.walk(fn)
            # ``bool`` is an ``int`` subclass — ``missing: True`` is a flag,
            # not a tunable.
            if isinstance(n, ast.Constant)
            and isinstance(n.value, (int, float))
            and not isinstance(n.value, bool)
        }
        # 0.08 is the factor weight, which is not a staleness budget.
        assert not (numbers - {0.08}), f"unexpected numeric literal(s) in the row: {numbers}"

    def test_zero_adds_is_a_real_observation_when_fresh(self):
        """Not-trending is signal.  Only an unusable OBSERVATION is missing,
        never a real count of zero."""
        row = self._row({"count": 0, "asOf": _fresh_stamp(60)})
        assert row.get("missing") is not True
        assert "0 adds" in row["contribution"]

    def test_the_dead_crowd_input_is_not_reachable(self):
        """The recommender's ``ktc_crowd_bids`` parameter was a SECOND
        crowd input, fed from a ``ktcCrowd`` contract block that never
        shipped in 173 archives.  The live crowd signal reaches the FAAB
        engine as ``recommend(crowd=...)`` and carries its own
        explanation row with a claim count.

        Retired 2026-08-18.  Pinned so it cannot be re-threaded without
        a decision — two crowd inputs is how the dead one stayed
        invisible.
        """
        import inspect

        from src.trade.faab_recommender import _demand_evidence_factors, recommend_faab

        assert "ktc_crowd_bids" not in inspect.signature(recommend_faab).parameters
        assert "ktc_crowd_bids" not in inspect.signature(_demand_evidence_factors).parameters


# ── Drop cost ────────────────────────────────────────────────────────


class TestDropCost:
    def test_a_valuable_drop_lowers_the_bid(self):
        cheap = _rec(drop_player_value=800.0, drop_player_name="Scrub")
        costly = _rec(drop_player_value=5500.0, drop_player_name="Starter")
        assert costly["bids"]["recommended"] < cheap["bids"]["recommended"]

    def test_a_below_replacement_drop_is_free(self):
        """Dropping someone you could re-add off the wire costs
        nothing, so it must not move the bid at all."""
        none_dropped = _rec()
        scrub_dropped = _rec(drop_player_value=600.0, drop_player_name="Scrub")
        assert scrub_dropped["bids"]["recommended"] == none_dropped["bids"]["recommended"]

    def test_an_open_roster_spot_removes_the_drop_cost(self):
        squeezed = _rec(drop_player_value=5500.0, drop_player_name="Starter", open_roster_spots=0)
        roomy = _rec(drop_player_value=5500.0, drop_player_name="Starter", open_roster_spots=1)
        assert roomy["bids"]["recommended"] >= squeezed["bids"]["recommended"]


# ── Season phase ─────────────────────────────────────────────────────


class TestSeasonPhase:
    def test_ceiling_relaxes_as_waiver_periods_run_out(self):
        early = _rec(current_week=1, in_season=True)["teamCeilingDollars"]
        late = _rec(current_week=14, in_season=True)["teamCeilingDollars"]
        assert late > early

    def test_late_season_does_not_automatically_raise_the_bid(self):
        """Relaxing the ceiling must not, by itself, make an ordinary
        player more expensive — the bid still comes from the market."""
        early = _rec(add_player_value=1800.0, current_week=1)["bids"]["recommended"]
        late = _rec(add_player_value=1800.0, current_week=14)["bids"]["recommended"]
        assert late <= early + 2

    def test_offseason_is_handled_explicitly(self):
        rec = _rec(in_season=False, current_week=None)
        assert any("offseason" in f["contribution"].lower() for f in rec["factors"])


# ── Aggression sourcing ──────────────────────────────────────────────


class TestAggressionSourcing:
    def test_league_summary_supplies_aggression_when_no_history_file(self):
        summary = {
            "leagueMedianWinningBid": 10.0,
            "teamAggression": {"o1": {"avgBid": 20.0, "winningCount": 5}},
        }
        assert _aggression_from_league_summary(summary, "o1") == (2.0, False)

    def test_undersampled_owner_defaults_to_neutral(self):
        summary = {
            "leagueMedianWinningBid": 10.0,
            "teamAggression": {"o1": {"avgBid": 90.0, "winningCount": 1}},
        }
        assert _aggression_from_league_summary(summary, "o1") == (1.0, True)

    def test_aggression_is_clamped(self):
        summary = {
            "leagueMedianWinningBid": 1.0,
            "teamAggression": {"o1": {"avgBid": 500.0, "winningCount": 9}},
        }
        factor, _ = _aggression_from_league_summary(summary, "o1")
        assert factor == 2.0

    def test_missing_summary_is_neutral_and_low_sample(self):
        assert _aggression_from_league_summary(None, "o1") == (1.0, True)


# ── Rival construction ───────────────────────────────────────────────


class TestBuildRivals:
    def test_unknown_balance_is_preserved_as_none(self):
        """An unverifiable rival must never raise the user's bid, so
        the balance stays ``None`` and the engine excludes them."""
        rivals = build_rivals([{"ownerId": "a", "faabRemaining": None}])
        assert rivals[0].faab_remaining is None

    def test_rows_without_an_owner_id_are_dropped(self):
        assert build_rivals([{"name": "ghost"}]) == []

    def test_open_roster_spots_are_derived_from_roster_size(self):
        rivals = build_rivals(
            [{"ownerId": "a", "faabRemaining": 50, "players": ["x", "y"]}],
            roster_size=10,
        )
        assert rivals[0].open_roster_spots == 8


# ── Confidence ───────────────────────────────────────────────────────


class TestConfidence:
    def test_all_inputs_present_is_high(self):
        assert compute_confidence([{"weight": 1.0, "missing": False}]) == "high"

    def test_all_inputs_missing_is_low(self):
        assert compute_confidence([{"weight": 1.0, "missing": True}]) == "low"

    def test_partial_inputs_is_medium(self):
        assert (
            compute_confidence(
                [{"weight": 0.7, "missing": False}, {"weight": 0.3, "missing": True}]
            )
            == "medium"
        )

    def test_unparseable_rows_are_ignored(self):
        assert compute_confidence([{"weight": "nonsense"}, {"weight": 1.0}]) == "high"

    def test_missing_rival_data_does_not_raise_confidence(self):
        with_rivals = _rec(
            rivals=[engine.RivalTeam(owner_id=f"r{i}", faab_remaining=50) for i in range(11)]
        )
        without = _rec(rivals=[])
        order = {"low": 0, "medium": 1, "high": 2}
        assert order[without["confidence"]] <= order[with_rivals["confidence"]]


# ── Warnings ─────────────────────────────────────────────────────────


class TestWarnings:
    def test_zero_balance_is_called_out(self):
        rec = _rec(team_faab_remaining=0)
        assert any("no FAAB left" in w for w in rec["warnings"])

    def test_a_swap_that_does_not_improve_the_roster_is_called_out(self):
        rec = _rec(add_player_value=3000.0, drop_player_value=3200.0, drop_player_name="Better")
        assert any("does not improve" in w for w in rec["warnings"])

    def test_value_above_balance_explains_which_constraint_binds(self):
        rec = _rec(add_player_value=9999.0, team_faab_remaining=10)
        assert any("capped by the balance" in w for w in rec["warnings"])
