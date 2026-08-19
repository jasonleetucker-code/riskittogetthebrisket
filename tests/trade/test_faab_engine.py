"""Unit tests for the FAAB engine's mechanics.

Structural properties only — the numeric calibration against the human
anchors and the real board lives in ``test_faab_calibration.py``.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.trade import faab_engine as FE


BOARD = [9999 - i * 12 for i in range(700)]


def _league(**kw) -> FE.LeagueContext:
    base = dict(original_budget=100, team_count=12, starters_per_team=20)
    base.update(kw)
    return FE.LeagueContext(**base)


def _anchors(league: FE.LeagueContext | None = None, **kw) -> FE.Anchors:
    return FE.resolve_anchors(BOARD, league or _league(), **kw)


def _rivals(n=11, remaining=100, need="neutral"):
    return [
        FE.RivalTeam(owner_id=f"r{i}", faab_remaining=remaining, need_level=need) for i in range(n)
    ]


# ── Season clock ─────────────────────────────────────────────────────


class TestSeasonClock:
    @pytest.mark.parametrize(
        "day,expected_week",
        [
            (date(2026, 9, 10), 1),  # Thursday after Labor Day (Sept 7)
            (date(2026, 9, 16), 1),  # Wednesday still inside week 1
            (date(2026, 9, 17), 2),
            (date(2026, 12, 24), 16),
        ],
    )
    def test_regular_season_weeks(self, day, expected_week):
        week, in_season = FE.current_nfl_week(day)
        assert in_season is True
        assert week == expected_week

    @pytest.mark.parametrize("day", [date(2026, 8, 4), date(2026, 6, 1), date(2027, 3, 1)])
    def test_outside_the_season_reports_no_week(self, day):
        assert FE.current_nfl_week(day) == (None, False)

    def test_week_never_exceeds_eighteen(self):
        week, in_season = FE.current_nfl_week(date(2027, 2, 20))
        assert (week, in_season) == (None, False)


# ── Anchors ──────────────────────────────────────────────────────────


class TestAnchors:
    def test_allin_anchor_is_the_league_wide_starter_line(self):
        """The all-in threshold is derived from league FORMAT, not
        hard-coded: it is the board value at (teams x starter slots)."""
        a = _anchors()
        assert a.starter_slots == 240
        assert a.v_allin == BOARD[239]

    def test_a_shallower_league_sets_a_higher_bar(self):
        """Fewer starting slots means a better waiver wire, so the
        value at which going all-in is rational must be higher."""
        deep = _anchors(_league(team_count=12, starters_per_team=20))
        shallow = _anchors(_league(team_count=10, starters_per_team=10))
        assert shallow.v_allin > deep.v_allin

    def test_replacement_sits_below_the_allin_line(self):
        a = _anchors()
        assert a.v_repl < a.v_allin
        assert a.band > 0

    def test_live_pool_sharpens_the_replacement_estimate(self):
        without = _anchors()
        with_pool = _anchors(available_values=[3000] * 30)
        assert with_pool.live_pool_repl == 3000
        assert with_pool.v_repl != without.v_repl

    def test_a_compressed_board_is_widened_rather_than_left_vertical(self):
        """A near-vertical curve would make a 10-point value change
        swing the bid by tens of dollars.  A board that is flat through
        the starter region would produce exactly that, so the band is
        widened downward instead (V_allin is the well-anchored end)."""
        flat = [5000 - i * 0.5 for i in range(700)]
        a = FE.resolve_anchors(flat, _league())
        assert a.widened is True
        assert a.band >= FE.FaabConfig().num("anchors", "minBandWidth", 700)

    def test_an_empty_board_falls_back_to_configured_priors(self):
        a = FE.resolve_anchors([], _league())
        assert a.source == "fallback"
        assert a.v_allin > a.v_repl

    def test_anchors_serialize(self):
        d = _anchors().to_dict()
        assert set(d) >= {"vAllIn", "vReplacement", "band", "starterSlots", "source"}


# ── Startable-depth need ─────────────────────────────────────────────


STARTERS = {
    "QB": 1,
    "RB": 2,
    "WR": 3,
    "TE": 2,
    "FLEX": 2,
    "SFLEX": 1,
    "K": 1,
    "DL": 3,
    "LB": 3,
    "DB": 3,
}


class TestStarterSlots:
    def test_direct_slots_are_counted(self):
        assert FE.starter_slots_for_position("DL", STARTERS) == 3.0

    def test_flex_slots_are_shared_among_eligible_positions(self):
        """A 2-FLEX + 1-SFLEX league genuinely needs more RB depth than
        its two direct RB slots suggest."""
        rb = FE.starter_slots_for_position("RB", STARTERS)
        assert rb == pytest.approx(2 + 2 / 3 + 1 / 4)

    def test_idp_variants_roll_up_to_their_family(self):
        assert FE.starter_slots_for_position("EDGE", STARTERS) == FE.starter_slots_for_position(
            "DL", STARTERS
        )
        assert FE.starter_slots_for_position("CB", STARTERS) == FE.starter_slots_for_position(
            "DB", STARTERS
        )

    def test_a_position_the_lineup_never_starts_needs_nothing(self):
        # ``LS``, not ``P``.  The family roll-up is now ``POSITION_ALIASES``
        # rather than this module's private copy, and the canonical table maps
        # ``P -> K`` — so a punter DOES have a slot in a league that starts a
        # kicker.  (It does not map ``PK``, which ``src/ros/lineup.py`` does:
        # the two vocabularies disagree in opposite directions on the two
        # kicker spellings.  Reported, not reconciled here — ``name_clean``
        # owns one and the lineup module owns the other.)
        assert FE.starter_slots_for_position("LS", STARTERS) == 0.0

    def test_missing_settings_are_survivable(self):
        assert FE.starter_slots_for_position("RB", None) == 0.0
        assert FE.starter_slots_for_position(None, STARTERS) == 0.0


class TestClassifyNeed:
    """Startable depth, not trade surplus.

    ``src.trade.suggestions.analyze_roster`` answers a different
    question and, measured on this platform's real 58-man best-ball
    rosters, returns ``surplus`` for 68 of 84 team/position pairs and
    ``need`` exactly once — a factor that cannot discriminate.
    """

    def test_fewer_startable_bodies_than_slots_is_a_hole(self):
        a = _anchors()
        assert classify(a, "DL", [a.v_repl + 500]) == "starterHole"

    def test_exactly_enough_bodies_is_thin(self):
        a = _anchors()
        assert classify(a, "DL", [a.v_repl + 500] * 3) == "need"

    def test_a_spare_body_or_two_is_neutral(self):
        a = _anchors()
        assert classify(a, "DL", [a.v_repl + 500] * 5) == "neutral"

    def test_plenty_of_spares_is_surplus(self):
        a = _anchors()
        assert classify(a, "DL", [a.v_repl + 500] * 8) == "surplus"

    def test_below_replacement_bodies_do_not_count_as_depth(self):
        """Twenty players who are worse than the wire is not depth."""
        a = _anchors()
        assert classify(a, "DL", [a.v_repl - 100] * 20) == "starterHole"

    def test_a_position_with_no_lineup_slot_is_neutral(self):
        a = _anchors()
        # ``LS`` rather than ``P`` — see the note in TestStarterSlots.
        assert classify(a, "LS", [a.v_repl + 500] * 9) == "neutral"


def classify(anchors, position, values):
    return FE.classify_need(values, position, STARTERS, anchors)


# ── Ceiling curve ────────────────────────────────────────────────────


class TestCeilingCurve:
    def test_below_replacement_is_worth_nothing(self):
        a = _anchors()
        assert FE.objective_ceiling(a.v_repl - 1, a)[0] == 0.0
        assert FE.objective_ceiling(1, a)[0] == 0.0

    def test_saturates_at_the_allin_line(self):
        a = _anchors()
        assert FE.objective_ceiling(a.v_allin, a)[0] == pytest.approx(1.0)

    def test_never_exceeds_the_full_budget(self):
        a = _anchors()
        for v in (a.v_allin, a.v_allin * 2, 9999):
            assert FE.objective_ceiling(v, a)[0] <= 1.0

    def test_raw_ceiling_keeps_growing_past_saturation(self):
        """Otherwise the market layer could not tell a marginal
        starter from a top-5 dynasty asset — both would read 100%."""
        a = _anchors()
        _, raw_at_line = FE.objective_ceiling(a.v_allin, a)
        _, raw_elite = FE.objective_ceiling(9999, a)
        assert raw_elite > raw_at_line

    def test_raw_ceiling_is_bounded(self):
        a = _anchors()
        cap = FE.FaabConfig().num("ceilingCurve", "rawCeilingCap", 6.0)
        assert FE.objective_ceiling(9999, a)[1] <= cap

    def test_is_monotonic_in_value(self):
        a = _anchors()
        prev = -1.0
        for v in range(0, 10000, 25):
            cur = FE.objective_ceiling(v, a)[0]
            assert cur >= prev - 1e-9, f"non-monotonic at {v}"
            prev = cur

    def test_small_value_changes_never_cause_extreme_jumps(self):
        """Requirement: the curve must be stable around thresholds."""
        a = _anchors()
        worst = 0.0
        for v in range(0, 10000, 10):
            step = abs(FE.objective_ceiling(v + 10, a)[0] - FE.objective_ceiling(v, a)[0])
            worst = max(worst, step)
        # No 10-point value change may move the ceiling more than 3
        # percentage points of the budget.
        assert worst < 0.03, f"largest 10-point jump was {worst:.3%}"

    def test_the_relationship_is_not_a_fixed_cents_per_point_conversion(self):
        a = _anchors()
        ratios = [FE.objective_ceiling(v, a)[0] / v for v in (2000, 3000, 5000, 9000)]
        assert max(ratios) > 2 * min(ratios)

    def test_5000_value_does_not_mean_fifty_dollars(self):
        a = _anchors()
        assert FE.objective_ceiling(5000, a)[0] * 100 != pytest.approx(50, abs=1)


# ── Season option value ──────────────────────────────────────────────


class TestSeasonOptionValue:
    def test_budget_is_held_back_early_and_released_late(self):
        team = FE.TeamContext()
        early, _ = FE.season_option_value(_league(current_week=1), team)
        late, _ = FE.season_option_value(_league(current_week=14), team)
        assert early < late
        assert late == pytest.approx(1.0, abs=0.01)

    def test_an_eliminated_team_should_spend_everything(self):
        factor, reason = FE.season_option_value(
            _league(current_week=5), FE.TeamContext(competitive_status="eliminated")
        )
        assert factor == pytest.approx(1.0)
        assert "eliminated" in reason

    def test_a_contender_converts_budget_more_readily_than_a_rebuilder(self):
        contender, _ = FE.season_option_value(
            _league(current_week=8), FE.TeamContext(competitive_status="contender")
        )
        rebuilder, _ = FE.season_option_value(
            _league(current_week=8), FE.TeamContext(competitive_status="rebuilder")
        )
        assert contender > rebuilder

    def test_offseason_preserves_budget(self):
        factor, reason = FE.season_option_value(
            _league(current_week=None, in_season=False), FE.TeamContext()
        )
        assert factor < 1.0
        assert "offseason" in reason

    def test_carryover_damps_the_late_season_release(self):
        plain, _ = FE.season_option_value(_league(current_week=14), FE.TeamContext())
        carry, _ = FE.season_option_value(
            _league(current_week=14, faab_carries_over=True), FE.TeamContext()
        )
        assert carry < plain


# ── Market model ─────────────────────────────────────────────────────


class TestMarketModel:
    def test_no_rivals_means_a_certain_win_at_any_price(self):
        p = FE.rival_bid_cdf(0.0, [], demand_signal=1.0, league=_league(), config=FE.FaabConfig())
        assert p == 1.0

    def test_win_probability_is_monotonic_in_the_bid(self):
        cfg = FE.FaabConfig()
        rivals = _rivals()
        prev = -1.0
        for b in range(0, 101):
            p = FE.rival_bid_cdf(float(b), rivals, demand_signal=0.6, league=_league(), config=cfg)
            assert p >= prev - 1e-9
            prev = p

    def test_rivals_with_unknown_balances_are_excluded(self):
        """An unverifiable rival who might be broke must never raise
        the user's bid."""
        cfg = FE.FaabConfig()
        known = FE.rival_bid_cdf(10.0, _rivals(3), demand_signal=0.8, league=_league(), config=cfg)
        unknown = FE.rival_bid_cdf(
            10.0,
            [FE.RivalTeam(owner_id=f"r{i}", faab_remaining=None) for i in range(3)],
            demand_signal=0.8,
            league=_league(),
            config=cfg,
        )
        assert unknown == 1.0
        assert known < 1.0

    def test_a_broke_rival_cannot_contest(self):
        cfg = FE.FaabConfig()
        p = FE.rival_bid_cdf(
            1.0,
            _rivals(5, remaining=0),
            demand_signal=1.0,
            league=_league(),
            config=cfg,
        )
        assert p == pytest.approx(1.0)

    def test_positional_need_raises_the_chance_a_rival_contests(self):
        cfg = FE.FaabConfig()
        kw = dict(demand_signal=0.7, league=_league(), config=cfg)
        hungry = FE.rival_bid_cdf(10.0, _rivals(need="starterHole"), **kw)
        stocked = FE.rival_bid_cdf(10.0, _rivals(need="surplus"), **kw)
        assert hungry < stocked

    def test_expected_bids_report_price_and_probability_separately(self):
        rows = FE.rival_expected_bids(_rivals(3), demand_signal=0.8, league=_league())
        assert len(rows) == 3
        for row in rows:
            assert 0.0 <= row["contestProbability"] <= 1.0
            assert row["expBid"] >= 0


# ── The bid ladder ───────────────────────────────────────────────────


class TestBidLadder:
    def _rec(self, value, **kw):
        league = _league(**{k: v for k, v in kw.items() if k in FE.LeagueContext.__annotations__})
        team_kw = {k: v for k, v in kw.items() if k in FE.TeamContext.__annotations__}
        team_kw.setdefault("faab_remaining", 100)
        return FE.recommend(
            FE.PlayerInput(name="X", value=value),
            league,
            FE.TeamContext(**team_kw),
            anchors=_anchors(league),
            rivals=kw.get("rivals", _rivals()),
        )

    def test_the_recommended_bid_is_below_the_max_rational_bid(self):
        """Bidding the ceiling captures zero surplus by construction,
        so the optimum is always strictly below it when contested."""
        rec = self._rec(BOARD[239])
        assert rec["bids"]["recommended"] < rec["bids"]["maxRational"]

    def test_an_allin_ceiling_does_not_force_an_allin_bid(self):
        """The headline requirement: worth $100, bid far less."""
        rec = self._rec(BOARD[239])
        assert rec["objective"]["dollars"] == 100
        assert rec["bids"]["recommended"] < 100

    def test_less_competition_means_a_cheaper_bid(self):
        contested = self._rec(BOARD[200], rivals=_rivals(need="need"))
        quiet = self._rec(BOARD[200], rivals=_rivals(need="surplus"))
        assert quiet["bids"]["recommended"] < contested["bids"]["recommended"]

    def test_an_uncontested_claim_costs_nothing(self):
        rec = self._rec(BOARD[200], rivals=[])
        assert rec["bids"]["recommended"] == 0

    def test_risk_posture_shifts_the_bid_but_not_the_worth(self):
        base = self._rec(BOARD[220])
        bold = self._rec(BOARD[220], risk_posture="aggressive")
        shy = self._rec(BOARD[220], risk_posture="conservative")
        assert shy["bids"]["recommended"] <= base["bids"]["recommended"]
        assert bold["bids"]["recommended"] >= base["bids"]["recommended"]
        assert bold["objective"]["dollars"] == shy["objective"]["dollars"]

    def test_risk_posture_cannot_breach_the_ceiling(self):
        bold = self._rec(BOARD[300], risk_posture="aggressive")
        assert bold["bids"]["recommended"] <= bold["bids"]["maxRational"]

    def test_a_team_with_no_budget_bids_nothing(self):
        rec = self._rec(9999, faab_remaining=0)
        assert rec["bids"]["recommended"] == 0
        assert any("no FAAB left" in w for w in rec["warnings"])

    def test_the_clearing_estimate_survives_a_broke_team(self):
        """The clearing price is a statement about the MARKET.  A team
        with $0 still needs to know what the player will cost."""
        rec = self._rec(BOARD[200], faab_remaining=0)
        assert rec["bids"]["clearing"] > 0

    def test_win_probability_is_reported_when_supportable(self):
        rec = self._rec(BOARD[220])
        assert rec["winProbability"] is None or 0.0 <= rec["winProbability"] <= 1.0

    def test_percentages_use_the_right_denominators(self):
        league = _league()
        rec = FE.recommend(
            FE.PlayerInput(name="X", value=BOARD[200]),
            league,
            FE.TeamContext(faab_remaining=50),
            anchors=_anchors(league),
            rivals=_rivals(),
        )
        bid = rec["bids"]["recommended"]
        assert rec["pctOfOriginalBudget"] == pytest.approx(100 * bid / 100, abs=0.1)
        assert rec["pctOfRemaining"] == pytest.approx(100 * bid / 50, abs=0.1)


# ── Explanations ─────────────────────────────────────────────────────


class TestExplanations:
    def test_a_below_replacement_player_is_explained_as_free(self):
        league = _league()
        rec = FE.recommend(
            FE.PlayerInput(name="Scrub", value=100),
            league,
            FE.TeamContext(faab_remaining=100),
            anchors=_anchors(league),
        )
        assert "free-agent baseline" in rec["explanation"]

    def test_an_allin_player_explains_the_worth_versus_bid_gap(self):
        league = _league()
        rec = FE.recommend(
            FE.PlayerInput(name="Stud", value=9999),
            league,
            FE.TeamContext(faab_remaining=100),
            anchors=_anchors(league),
            rivals=_rivals(),
        )
        assert "entire" in rec["explanation"] or "worth up to" in rec["explanation"]

    def test_the_drop_side_is_named_when_it_costs_something(self):
        league = _league()
        rec = FE.recommend(
            FE.PlayerInput(name="Add", value=BOARD[200], drop_name="Keeper", drop_value=BOARD[210]),
            league,
            FE.TeamContext(faab_remaining=100),
            anchors=_anchors(league),
            rivals=_rivals(),
        )
        assert "Keeper" in rec["explanation"]
