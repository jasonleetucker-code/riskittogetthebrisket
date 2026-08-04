"""Calibration tests — the FAAB model against real anchors.

These are the tests that would catch a recalibration going wrong.  They
run against the REAL exported board rather than a synthetic one, and
they pin:

* the four human calibration anchors reaching a 100% objective CEILING
  while their recommended BIDS stay well below the full budget
* every value point the redesign brief called out (500 … 9,999)
* the scenario matrix (season phase, roster need, drop cost, budget
  distribution, competition) moving the bid in the right direction
* the invariants that must hold no matter how the config is tuned

The two human anchors that motivated the model:

  * the site owner named **Josh Jacobs** as a player he would spend his
    whole budget on
  * another manager named **De'Zhaun Stribling**, **J.K. Dobbins** and
    **Jaylen Warren**

Neither name is hard-coded into the model.  The all-in region is the
board value at the league-wide starter-slot count, and it lands on
those players by itself — which is exactly what these tests check.
"""

from __future__ import annotations

import glob
import json
import os

import pytest

from src.trade import faab_engine as FE


# ── Real board fixture ───────────────────────────────────────────────

EXCLUDED = {"PICK", "K", "DEF"}

# The brief's required calibration points.
REQUIRED_VALUE_POINTS = [500, 1000, 1500, 2500, 3000, 3500, 4000, 5000, 6000, 7500, 9000, 9999]

# Measured on the 2026-08-04 board.  Stored as approximate values with
# a tolerance so a board refresh does not break the suite — what is
# pinned is the RELATIONSHIP, not the exact number.
ANCHOR_PLAYERS = {
    "Josh Jacobs": 3901,
    "Jaylen Warren": 2938,
    "De'Zhaun Stribling": 2680,
    "J.K. Dobbins": 2661,
}


@pytest.fixture(scope="module")
def board():
    """Every rankable non-pick value from the freshest real export.

    Skips rather than fails when no export is present — CI clones
    without the data directory should not report a red calibration
    suite for a missing fixture.
    """
    paths = sorted(glob.glob("exports/latest/dynasty_data_*.json"))
    if not paths:
        pytest.skip("no exported board available")
    raw = json.loads(open(paths[-1], encoding="utf-8").read())

    from src.api.data_contract import build_api_data_contract

    contract = build_api_data_contract(raw)
    rows = [
        r
        for r in contract.get("playersArray") or []
        if isinstance(r.get("rankDerivedValue"), (int, float))
        and r["rankDerivedValue"] > 0
        and str(r.get("position") or "").upper() not in EXCLUDED
    ]
    if not rows:
        pytest.skip("exported board has no valued rows")
    return rows


@pytest.fixture(scope="module")
def values(board):
    return [float(r["rankDerivedValue"]) for r in board]


@pytest.fixture(scope="module")
def league():
    # dynasty_main: 12 teams, 20 valued starter slots (K excluded).
    return FE.LeagueContext(
        original_budget=100,
        team_count=12,
        starters_per_team=20,
        current_week=1,
        playoff_week_start=15,
        in_season=True,
    )


@pytest.fixture(scope="module")
def anchors(values, league):
    return FE.resolve_anchors(values, league)


def _rivals(n=11, remaining=100, need="neutral", aggression=1.0):
    return [
        FE.RivalTeam(
            owner_id=f"r{i}", faab_remaining=remaining, need_level=need, aggression=aggression
        )
        for i in range(n)
    ]


def _recommend(value, anchors, league, *, team=None, rivals=None, **player_kw):
    return FE.recommend(
        FE.PlayerInput(name=player_kw.pop("name", "Target"), value=float(value), **player_kw),
        league,
        team or FE.TeamContext(faab_remaining=100),
        anchors=anchors,
        rivals=_rivals() if rivals is None else rivals,
    )


# ── The all-in saturation region ─────────────────────────────────────


class TestAllInRegion:
    def test_the_allin_line_is_derived_from_league_format(self, anchors):
        """Not a hard-coded value: the board value at (teams x starter
        slots).  For dynasty_main that is rank 240."""
        assert anchors.starter_slots == 240
        assert 1800 < anchors.v_allin < 3200, anchors.v_allin

    def test_every_human_anchor_reaches_a_full_ceiling(self, board, anchors):
        """Both managers said they would spend their ENTIRE budget on
        these players.  The model must agree — without knowing their
        names."""
        by_name = {r.get("displayName"): r for r in board}
        missing = [n for n in ANCHOR_PLAYERS if n not in by_name]
        if missing:
            pytest.skip(f"anchor players absent from this board: {missing}")
        for name, approx_value in ANCHOR_PLAYERS.items():
            value = float(by_name[name]["rankDerivedValue"])
            assert value == pytest.approx(approx_value, rel=0.35), f"{name} moved a lot"
            ceiling, _ = FE.objective_ceiling(value, anchors)
            assert ceiling == pytest.approx(1.0), f"{name} ({value}) should be an all-in ceiling"

    def test_a_player_need_not_grade_near_9999_for_a_full_ceiling(self, anchors):
        """The whole point of the human calibration exercise."""
        assert FE.objective_ceiling(anchors.v_allin, anchors)[0] == pytest.approx(1.0)
        assert anchors.v_allin < 4000

    def test_a_full_ceiling_does_not_produce_a_full_bid(self, anchors, league):
        """A player can be worth $100 while the right bid is far less —
        the separation the brief demanded."""
        for name, value in ANCHOR_PLAYERS.items():
            rec = _recommend(value, anchors, league)
            assert rec["objective"]["dollars"] == 100, name
            assert rec["bids"]["recommended"] < 100, f"{name} should not auto-bid the budget"

    def test_a_shallower_league_moves_the_allin_line_up(self, values):
        """dynasty_new is 10 teams x 10 starters, so its wire is much
        better and the bar for going all-in must be higher."""
        deep = FE.resolve_anchors(
            values, FE.LeagueContext(team_count=12, starters_per_team=20)
        )
        shallow = FE.resolve_anchors(
            values, FE.LeagueContext(team_count=10, starters_per_team=10)
        )
        assert shallow.v_allin > deep.v_allin


# ── The required value points ────────────────────────────────────────


class TestRequiredValuePoints:
    def test_every_required_point_produces_a_sane_ceiling(self, anchors):
        for v in REQUIRED_VALUE_POINTS:
            ceiling, _ = FE.objective_ceiling(v, anchors)
            assert 0.0 <= ceiling <= 1.0, v

    def test_replacement_level_players_are_worth_nothing(self, anchors):
        """500 / 1000 / 1500 are at or barely above what the wire
        offers for free, so all three must price at $0.  Asserted in
        DOLLARS rather than on the raw curve: the smootherstep toe
        leaves a vanishing non-zero fraction just above the
        replacement line, which is the point of a smooth curve and
        rounds to nothing.""" 
        for v in (500, 1000, 1500):
            assert round(FE.objective_ceiling(v, anchors)[0] * 100) == 0, v

    def test_ordinary_waiver_players_are_not_inflated(self, anchors, league):
        """The complaint that started this: ordinary players were
        getting 14-21% of the budget.  They must now be cheap."""
        for v in (500, 1000, 1500):
            rec = _recommend(v, anchors, league)
            assert rec["bids"]["recommended"] <= 1, v

    def test_5000_does_not_mean_fifty_dollars(self, anchors):
        assert FE.objective_ceiling(5000, anchors)[0] * 100 != pytest.approx(50, abs=2)

    def test_the_top_of_the_scale_is_a_full_ceiling(self, anchors):
        for v in (9000, 9999):
            assert FE.objective_ceiling(v, anchors)[0] == pytest.approx(1.0)

    def test_the_mapping_is_nonlinear(self, anchors):
        """Ceiling per value point must vary by more than 2x across the
        board — a linear cents-per-point conversion would be flat."""
        ratios = [FE.objective_ceiling(v, anchors)[0] / v for v in (2500, 4000, 9999)]
        assert max(ratios) > 2 * min(ratios)

    def test_the_curve_is_monotonic_across_the_required_points(self, anchors):
        seen = [FE.objective_ceiling(v, anchors)[0] for v in REQUIRED_VALUE_POINTS]
        assert seen == sorted(seen)


# ── Scenario matrix ──────────────────────────────────────────────────


class TestScenarioMatrix:
    @pytest.fixture
    def mid(self, anchors):
        """A value inside the growth region, where the scenario levers
        have room to move the answer."""
        return anchors.v_repl + 0.75 * anchors.band

    def test_severe_positional_need_raises_the_bid(self, mid, anchors, league):
        hole = _recommend(
            mid, anchors, league, team=FE.TeamContext(faab_remaining=100, need_level="starterHole")
        )
        stocked = _recommend(
            mid, anchors, league, team=FE.TeamContext(faab_remaining=100, need_level="surplus")
        )
        assert hole["bids"]["recommended"] > stocked["bids"]["recommended"]

    def test_need_never_pushes_a_bid_above_the_ceiling(self, mid, anchors, league):
        hole = _recommend(
            mid, anchors, league, team=FE.TeamContext(faab_remaining=100, need_level="starterHole")
        )
        assert hole["bids"]["recommended"] <= hole["bids"]["maxRational"]

    def test_a_valuable_drop_lowers_the_bid(self, mid, anchors, league):
        free = _recommend(mid, anchors, league, drop_name="Scrub", drop_value=anchors.v_repl - 200)
        costly = _recommend(mid, anchors, league, drop_name="Starter", drop_value=mid)
        assert costly["bids"]["recommended"] < free["bids"]["recommended"]

    def test_an_open_roster_spot_beats_a_forced_drop(self, mid, anchors, league):
        forced = _recommend(
            mid,
            anchors,
            league,
            team=FE.TeamContext(faab_remaining=100, open_roster_spots=0),
            drop_name="Starter",
            drop_value=mid,
        )
        roomy = _recommend(
            mid,
            anchors,
            league,
            team=FE.TeamContext(faab_remaining=100, open_roster_spots=3),
            drop_name="Starter",
            drop_value=mid,
        )
        assert roomy["bids"]["recommended"] >= forced["bids"]["recommended"]

    def test_a_contender_commits_more_readily_than_a_rebuilder(self, mid, anchors, league):
        contender = _recommend(
            mid,
            anchors,
            league,
            team=FE.TeamContext(faab_remaining=100, competitive_status="contender"),
        )
        rebuilder = _recommend(
            mid,
            anchors,
            league,
            team=FE.TeamContext(faab_remaining=100, competitive_status="rebuilder"),
        )
        assert contender["bids"]["maxRational"] >= rebuilder["bids"]["maxRational"]

    def test_the_ceiling_opens_up_as_the_season_runs_out(self, mid, anchors, values):
        week1 = FE.LeagueContext(team_count=12, starters_per_team=20, current_week=1)
        week14 = FE.LeagueContext(team_count=12, starters_per_team=20, current_week=14)
        early = _recommend(mid, anchors, week1)["bids"]["maxRational"]
        late = _recommend(mid, anchors, week14)["bids"]["maxRational"]
        assert late > early

    def test_late_season_does_not_inflate_ordinary_players(self, anchors, values):
        """Requirement: do not automatically make every player more
        expensive later in the season."""
        low = anchors.v_repl + 0.15 * anchors.band
        week1 = FE.LeagueContext(team_count=12, starters_per_team=20, current_week=1)
        week14 = FE.LeagueContext(team_count=12, starters_per_team=20, current_week=14)
        assert (
            _recommend(low, anchors, week14)["bids"]["recommended"]
            <= _recommend(low, anchors, week1)["bids"]["recommended"] + 2
        )

    def test_many_interested_opponents_raise_the_price(self, mid, anchors, league):
        crowded = _recommend(mid, anchors, league, rivals=_rivals(need="starterHole"))
        quiet = _recommend(mid, anchors, league, rivals=_rivals(need="surplus"))
        assert crowded["bids"]["recommended"] > quiet["bids"]["recommended"]

    def test_broke_opponents_cannot_drive_the_price_up(self, mid, anchors, league):
        flush = _recommend(mid, anchors, league, rivals=_rivals(remaining=100))
        skint = _recommend(mid, anchors, league, rivals=_rivals(remaining=1))
        assert skint["bids"]["recommended"] < flush["bids"]["recommended"]

    def test_richer_opponents_never_trigger_unbounded_escalation(self, mid, anchors, league):
        """Requirement: do not simply raise the recommendation because
        another team has more FAAB.

        Escalation is bounded by the player's worth, not by the rival
        field's depth: however rich the opposition gets, the bid stays
        under the max rational bid and stops climbing.
        """
        bids = []
        for remaining in (50, 100, 200, 500):
            rec = _recommend(
                mid,
                anchors,
                league,
                team=FE.TeamContext(faab_remaining=100),
                rivals=_rivals(remaining=remaining),
            )
            assert rec["bids"]["recommended"] <= rec["bids"]["maxRational"]
            bids.append(rec["bids"]["recommended"])
        # Once rivals can already outbid us, more rival money changes
        # nothing — we decline to chase rather than escalating.
        assert max(bids) - min(bids) <= 2, bids

    def test_a_capped_rival_field_is_beaten_cheaply(self, mid, anchors, league):
        """The flip side, and the behaviour that makes the model worth
        having: when every rival is nearly broke, the right move is the
        smallest bid that clears them — not the EV-optimal bid against
        a field that does not exist.
        """
        poor = _recommend(
            mid, anchors, league, team=FE.TeamContext(faab_remaining=100), rivals=_rivals(remaining=5)
        )
        assert poor["bids"]["recommended"] <= 8
        assert poor["winProbability"] == pytest.approx(1.0, abs=0.01)


# ── Invariants ───────────────────────────────────────────────────────


class TestInvariants:
    @pytest.mark.parametrize("remaining", [0, 1, 5, 17, 50, 100])
    def test_no_recommendation_ever_exceeds_the_balance(self, remaining, anchors, league):
        for v in REQUIRED_VALUE_POINTS:
            rec = _recommend(v, anchors, league, team=FE.TeamContext(faab_remaining=remaining))
            for key in ("recommended", "conservative", "aggressive", "maxRational"):
                assert rec["bids"][key] <= remaining, (v, remaining, key)

    def test_objective_value_is_invariant_to_spent_budget(self, anchors, league):
        for v in REQUIRED_VALUE_POINTS:
            a = _recommend(v, anchors, league, team=FE.TeamContext(faab_remaining=100))
            b = _recommend(v, anchors, league, team=FE.TeamContext(faab_remaining=6))
            assert a["objective"]["dollars"] == b["objective"]["dollars"], v

    def test_objective_value_is_the_same_for_every_team(self, anchors, league):
        """It is a property of the player and the league, not of who is
        asking."""
        teams = [
            FE.TeamContext(owner_id="a", faab_remaining=100, need_level="starterHole"),
            FE.TeamContext(owner_id="b", faab_remaining=40, need_level="surplus"),
            FE.TeamContext(owner_id="c", faab_remaining=90, competitive_status="rebuilder"),
        ]
        seen = {
            _recommend(anchors.v_allin, anchors, league, team=t)["objective"]["dollars"]
            for t in teams
        }
        assert len(seen) == 1

    def test_different_teams_can_receive_different_bids(self, anchors, league):
        mid = anchors.v_repl + 0.7 * anchors.band
        bids = {
            _recommend(
                mid,
                anchors,
                league,
                team=FE.TeamContext(owner_id=o, faab_remaining=rem, need_level=need),
            )["bids"]["recommended"]
            for o, rem, need in (("a", 100, "starterHole"), ("b", 12, "surplus"))
        }
        assert len(bids) > 1

    def test_budgets_other_than_100_are_supported(self, values):
        for budget in (50, 100, 200, 1000):
            lg = FE.LeagueContext(original_budget=budget, team_count=12, starters_per_team=20)
            a = FE.resolve_anchors(values, lg)
            rec = _recommend(9999, a, lg, team=FE.TeamContext(faab_remaining=budget))
            assert rec["objective"]["dollars"] == budget
            assert rec["objective"]["pctOfOriginalBudget"] == pytest.approx(100.0)

    def test_small_value_changes_do_not_produce_unreasonable_jumps(self, anchors, league):
        prev = None
        for v in range(int(anchors.v_repl) - 100, int(anchors.v_allin) + 400, 25):
            rec = _recommend(v, anchors, league)["bids"]["recommended"]
            if prev is not None:
                assert abs(rec - prev) <= 8, f"jump of {abs(rec - prev)} at value {v}"
            prev = rec

    def test_the_bid_ladder_is_always_ordered(self, anchors, league):
        for v in REQUIRED_VALUE_POINTS:
            b = _recommend(v, anchors, league)["bids"]
            assert b["conservative"] <= b["recommended"] <= b["aggressive"] <= b["maxRational"], v

    def test_every_response_explains_itself(self, anchors, league):
        for v in REQUIRED_VALUE_POINTS:
            rec = _recommend(v, anchors, league)
            assert rec["explanation"].strip()
            assert rec["confidence"] in ("low", "medium", "high")


# ── Player archetypes ────────────────────────────────────────────────


class TestArchetypes:
    """The brief's archetype list, expressed as board positions rather
    than named players so the suite survives a board refresh."""

    def test_archetypes_price_in_the_expected_order(self, anchors, league):
        archetypes = {
            "replacement": anchors.v_repl - 300,
            "low_upside_vet": anchors.v_repl,
            "handcuff": anchors.v_repl + 0.3 * anchors.band,
            "injury_fill_in": anchors.v_repl + 0.45 * anchors.band,
            "breakout": anchors.v_repl + 0.8 * anchors.band,
            "starter": anchors.v_allin,
            "elite": 9999,
        }
        bids = {k: _recommend(v, anchors, league)["objective"]["dollars"] for k, v in archetypes.items()}
        ordered = list(archetypes)
        for earlier, later in zip(ordered, ordered[1:]):
            assert bids[earlier] <= bids[later], f"{earlier} priced above {later}"

    def test_replacement_level_is_a_zero_dollar_claim(self, anchors, league):
        rec = _recommend(anchors.v_repl - 300, anchors, league)
        assert rec["bids"]["recommended"] == 0
        assert rec["objective"]["dollars"] == 0

    @pytest.mark.parametrize("position", ["QB", "TE", "DL", "LB", "DB", "WR", "RB"])
    def test_position_does_not_change_the_objective_value(self, position, anchors, league):
        """Positional scarcity, superflex QB premium and TE premium are
        already inside the canonical 1-9999 value.  Applying them again
        here would be the double-count the brief warned about."""
        rec = _recommend(anchors.v_allin, anchors, league, position=position)
        assert rec["objective"]["dollars"] == 100
