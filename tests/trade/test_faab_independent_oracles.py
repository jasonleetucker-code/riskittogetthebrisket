"""Independent oracles for FAAB anchors, team layer and market layer (CW-49).

Every expected value below is produced by the small ``_o_*`` functions in this
file, written from the documented model (``docs/faab-model.md``, CLAUDE.md
"FAAB recommendations") with ``statistics.NormalDist`` for the normal CDF and
plain loops for the argmax.  No expectation is obtained by calling the engine
function under test.  Spec constants are pinned literally and the shipped
config is asserted equal to them, so a recalibration fails loudly instead of
shifting an expectation silently.

Complements (does not repeat) ``test_faab_curve_oracle.py`` (curve endpoints,
slope, scaling) and ``test_faab_crowd.py`` (crowd never moves objective).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import NormalDist

import pytest

from src.trade import faab_engine as FE
from src.trade.faab_recommender import build_rivals, recommend_faab

_NORM = NormalDist()
CONFIG = json.loads(
    (Path(__file__).resolve().parents[2] / "config" / "trade" / "faab.json").read_text(
        encoding="utf-8"
    )
)

# ---- spec constants (docs/faab-model.md) -----------------------------------
ALLIN_MULT, REPL_MULT = 1.0, 2.0
LIVE_RANK, LIVE_W, MIN_BAND = 12, 0.5, 700.0
TOE, SLOPE, CAP = 2.2, 0.5, 6.0
OPT_EARLY, OPT_LATE, OPT_EXP = 0.55, 1.0, 1.6
ENG_BASE, ENG_TOP, ENG_EXP = 0.05, 0.70, 0.9
SH_BASE, SH_MAX, SH_EXP = 0.015, 0.45, 1.3
SIGMA, MIN_MEDIAN, SAT = 1.1, 0.25, 2.5
CROWD_W, CROWD_TO_RIVAL, CROWD_LIFT = 0.6, 0.53, 5.0
MIN_EDGE = 0.02


def test_shipped_config_equals_the_documented_spec():
    a, m, s = CONFIG["anchors"], CONFIG["market"], CONFIG["seasonPhase"]
    assert (a["allinSlotMultiple"], a["replacementSlotMultiple"]) == (ALLIN_MULT, REPL_MULT)
    assert (a["replacementLivePoolRank"], a["replacementLivePoolWeight"]) == (LIVE_RANK, LIVE_W)
    assert a["minBandWidth"] == MIN_BAND
    assert (s["optionValueEarly"], s["optionValueLate"], s["optionValueExponent"]) == (
        OPT_EARLY,
        OPT_LATE,
        OPT_EXP,
    )
    assert (m["engagementBaseRate"], m["engagementMaxRate"], m["engagementExponent"]) == (
        ENG_BASE,
        ENG_TOP,
        ENG_EXP,
    )
    assert (m["rivalBaseSharePct"], m["rivalMaxSharePct"], m["rivalShareExponent"]) == (
        SH_BASE * 100,
        SH_MAX * 100,
        SH_EXP,
    )
    assert (m["rivalSigma"], m["demandSaturationBudgets"]) == (SIGMA, SAT)
    assert (m["crowdBlendWeight"], m["crowdWinningBidToRivalMedian"]) == (
        CROWD_W,
        CROWD_TO_RIVAL,
    )
    assert m["crowdEngagementLift"] == CROWD_LIFT
    assert CONFIG["bidPolicy"]["minEdge"] == MIN_EDGE


# ---- independent oracle implementations ------------------------------------


def _o_value_at_rank(vals_desc, rank):
    if rank <= len(vals_desc):
        return vals_desc[rank - 1]
    return vals_desc[-1] * max(0.0, 1.0 - (rank - len(vals_desc)) / len(vals_desc))


def _o_anchors(board, teams, starters, available=None):
    vals = sorted((v for v in board if v > 0), reverse=True)
    slots = teams * starters
    v_allin = _o_value_at_rank(vals, round(slots * ALLIN_MULT))
    fmt = _o_value_at_rank(vals, round(slots * REPL_MULT))
    if available is not None:
        av = sorted((v for v in available if v > 0), reverse=True)
        live = av[min(LIVE_RANK, len(av)) - 1]
        v_repl = LIVE_W * live + (1 - LIVE_W) * fmt
    else:
        v_repl = fmt
    if v_allin - v_repl < MIN_BAND:
        v_repl = v_allin - MIN_BAND
    v_repl = max(0.0, v_repl)
    return v_allin, v_repl


def _o_curve(value, v_allin, v_repl):
    """(displayed, raw) in budget units."""
    s = max(0.0, value - v_repl) / (v_allin - v_repl)
    if s == 0:
        return 0.0, 0.0
    x = min(1.0, s**TOE)
    disp = 10 * x**3 - 15 * x**4 + 6 * x**5
    raw = disp if s <= 1 else 1 + (s - 1) * SLOPE
    return disp, min(raw, CAP)


def _o_option(week, playoff_start=15, status="bubble"):
    last = max(1, playoff_start - 1)
    if status == "eliminated":
        return 1.0
    progress = 1.0 if week >= last else (max(1, week) - 1) / max(1, last - 1)
    f = OPT_EARLY + (OPT_LATE - OPT_EARLY) * progress**OPT_EXP
    return min(1.0, f * {"contender": 1.15, "bubble": 1.0, "rebuilder": 0.8}[status])


NEED_ENG = {"starterHole": 1.8, "need": 1.35, "neutral": 1.0, "surplus": 0.35}


def _o_engagement(demand, need="neutral", crowd_share=None):
    s = min(1.0, max(0.0, demand))
    p = (ENG_BASE + (ENG_TOP - ENG_BASE) * s**ENG_EXP) * NEED_ENG[need]
    if crowd_share:
        p = max(p, min(ENG_TOP, ENG_BASE + CROWD_LIFT * crowd_share))
    return min(1.0, max(0.0, p))


def _o_median_bid(budget, demand, aggression=1.0, remaining=100, crowd_pct=None):
    share = SH_BASE + (SH_MAX - SH_BASE) * min(1.0, max(0.0, demand)) ** SH_EXP
    if crowd_pct is not None:
        share = (1 - CROWD_W) * share + CROWD_W * (crowd_pct / 100.0 * CROWD_TO_RIVAL)
    return min(max(MIN_MEDIAN, budget * share * aggression), remaining)


def _o_win(bid, rivals, budget, demand, crowd_pct=None, crowd_share=None):
    """P(we win at bid); rivals = [(remaining, need, aggression)]."""
    win = 1.0
    for remaining, need, aggression in rivals:
        p = _o_engagement(demand, need, crowd_share)
        if p <= 0:
            continue
        med = _o_median_bid(budget, demand, aggression, remaining, crowd_pct)
        if bid <= 0:
            beat = 0.0
        elif bid > remaining:
            beat = 1.0
        else:
            beat = _NORM.cdf((math.log(bid) - math.log(med)) / SIGMA)
            if bid == remaining:
                beat = max(beat, 0.5)
        win *= (1 - p) + p * beat
    return win


# ---- 1. anchors -------------------------------------------------------------

LINEAR = [10000.0 - 5.0 * i for i in range(900)]  # strictly descending
LEAGUE = FE.LeagueContext


@pytest.mark.parametrize(
    "teams,starters", [(12, 20), (10, 10), (14, 12), (8, 15)], ids=lambda x: str(x)
)
def test_anchors_match_independent_rank_lookup(teams, starters):
    a = FE.resolve_anchors(LINEAR, LEAGUE(team_count=teams, starters_per_team=starters))
    o_allin, o_repl = _o_anchors(LINEAR, teams, starters)
    assert a.v_allin == pytest.approx(o_allin, abs=1e-9)
    assert a.v_repl == pytest.approx(o_repl, abs=1e-9)
    assert a.starter_slots == teams * starters
    assert a.band == pytest.approx(o_allin - o_repl, abs=1e-9)


def test_anchor_is_literally_the_board_value_at_teams_times_starters():
    # 10 x 10 = rank 100 -> LINEAR[99]; independent of any helper.
    a = FE.resolve_anchors(LINEAR, LEAGUE(team_count=10, starters_per_team=10))
    assert a.v_allin == LINEAR[99]
    assert a.format_repl == LINEAR[199]


def test_live_pool_blend_is_midpoint_of_nth_best_available_and_format_line():
    avail = [6000.0 - 40.0 * i for i in range(60)]
    a = FE.resolve_anchors(
        LINEAR, LEAGUE(team_count=10, starters_per_team=10), available_values=avail
    )
    o_allin, o_repl = _o_anchors(LINEAR, 10, 10, avail)
    assert a.live_pool_repl == avail[LIVE_RANK - 1]  # 12th best, NOT the best
    assert a.v_repl == pytest.approx(o_repl, abs=1e-9)
    assert a.v_repl == pytest.approx(0.5 * avail[11] + 0.5 * LINEAR[199], abs=1e-9)
    assert a.source == "board+pool"


def test_adding_the_single_best_free_agent_does_not_move_the_anchor_much():
    # The anchor reads the 12th best, so a new top free agent shifts it by one rank step only.
    avail = [6000.0 - 40.0 * i for i in range(60)]
    base = FE.resolve_anchors(
        LINEAR, LEAGUE(team_count=10, starters_per_team=10), available_values=avail
    )
    plus = FE.resolve_anchors(
        LINEAR, LEAGUE(team_count=10, starters_per_team=10), available_values=[9000.0, *avail]
    )
    assert plus.v_repl - base.v_repl == pytest.approx(0.5 * 40.0, abs=1e-9)


def test_anchors_recompute_per_league_and_differ_with_format():
    a = FE.resolve_anchors(LINEAR, LEAGUE(team_count=12, starters_per_team=20))
    b = FE.resolve_anchors(LINEAR, LEAGUE(team_count=10, starters_per_team=10))
    assert a.v_allin != b.v_allin and a.v_repl != b.v_repl
    # deeper league (more starters) -> all-in line lower on the same board
    assert a.v_allin < b.v_allin


def test_no_player_is_hardcoded_anchors_follow_the_values_not_identities():
    rev = list(reversed(LINEAR))  # order of input rows is irrelevant
    a = FE.resolve_anchors(LINEAR, LEAGUE(team_count=10, starters_per_team=10))
    b = FE.resolve_anchors(rev, LEAGUE(team_count=10, starters_per_team=10))
    assert (a.v_allin, a.v_repl) == (b.v_allin, b.v_repl)
    # translating the whole board translates both anchors identically
    shifted = [v + 1000.0 for v in LINEAR]
    c = FE.resolve_anchors(shifted, LEAGUE(team_count=10, starters_per_team=10))
    assert c.v_allin == pytest.approx(a.v_allin + 1000.0)
    assert c.v_repl == pytest.approx(a.v_repl + 1000.0)
    # the shipped fallbacks (2400 / 1400) are not what a real board produces
    assert a.source == "board" and a.v_allin not in (2400.0, 1400.0)


def test_non_positive_and_non_numeric_rows_are_ignored():
    dirty = [*LINEAR, 0.0, -5.0, None, "x"]  # type: ignore[list-item]
    a = FE.resolve_anchors(dirty, LEAGUE(team_count=10, starters_per_team=10))
    o_allin, o_repl = _o_anchors(LINEAR, 10, 10)
    assert (a.v_allin, a.v_repl) == (pytest.approx(o_allin), pytest.approx(o_repl))


def test_past_the_end_of_the_board_decays_toward_zero_not_clamped():
    board = [3000.0 - 10.0 * i for i in range(100)]  # 100 players
    a = FE.resolve_anchors(board, LEAGUE(team_count=12, starters_per_team=10))  # slots 120, 2x=240
    o_allin, o_repl = _o_anchors(board, 12, 10)
    assert o_allin == pytest.approx(board[-1] * (1 - 20 / 100))
    assert a.v_allin == pytest.approx(o_allin)
    assert a.v_repl == pytest.approx(o_repl)
    assert a.v_repl < board[-1]  # clamping to the worst ranked player would equal it


def test_compressed_board_widens_downward_to_the_minimum_band():
    flat = [2000.0 - 0.1 * i for i in range(600)]
    a = FE.resolve_anchors(flat, LEAGUE(team_count=10, starters_per_team=10))
    o_allin, o_repl = _o_anchors(flat, 10, 10)
    assert a.widened and a.v_allin == pytest.approx(o_allin)  # V_allin is the fixed end
    assert a.v_repl == pytest.approx(o_allin - MIN_BAND) == pytest.approx(o_repl)
    assert a.band == pytest.approx(MIN_BAND)


def test_empty_board_is_labelled_fallback_not_zero():
    a = FE.resolve_anchors([], LEAGUE())
    assert a.source == "fallback" and a.v_allin > 0 and a.v_repl > 0


# ---- 2. ceiling curve end to end -------------------------------------------


def _recommend(value, anchors, *, remaining=100, budget=100, week=8, rivals=(), **team_kw):
    return FE.recommend(
        FE.PlayerInput(name="P", value=value),
        FE.LeagueContext(original_budget=budget, in_season=True, current_week=week),
        FE.TeamContext(faab_remaining=remaining, **team_kw),
        anchors=anchors,
        rivals=rivals,
    )


ANCH = FE.resolve_anchors(LINEAR, LEAGUE(team_count=10, starters_per_team=10))
O_ALLIN, O_REPL = _o_anchors(LINEAR, 10, 10)


@pytest.mark.parametrize("budget", [100, 250, 1000])
@pytest.mark.parametrize("frac", [0.0, 0.2, 0.5, 0.8, 1.0])
def test_objective_dollars_match_oracle_and_scale_with_original_budget(budget, frac):
    value = O_REPL + frac * (O_ALLIN - O_REPL)
    rec = _recommend(value, ANCH, budget=budget, remaining=budget)
    disp, _ = _o_curve(value, O_ALLIN, O_REPL)
    assert rec["objective"]["dollars"] == round(disp * budget)
    assert rec["objective"]["originalBudget"] == budget


def test_objective_is_the_whole_original_budget_at_all_in_whatever_is_left():
    for remaining in (100, 40, 7, 0):
        rec = _recommend(O_ALLIN, ANCH, remaining=remaining)
        assert rec["objective"]["dollars"] == 100  # worth the whole season's allowance
        assert rec["bids"]["recommended"] <= remaining


def test_raw_ceiling_keeps_growing_above_all_in_through_max_rational():
    # maxRational = min(balance, floor(rawCeiling dollars)) with a full balance
    # team-layer factors fixed at neutral/late-season (option 1.0, need 1.0)
    cap_pre = None
    for mult in (1.0, 1.5, 2.5):
        value = O_ALLIN + mult * (O_ALLIN - O_REPL) * 0.2
        _, raw = _o_curve(value, O_ALLIN, O_REPL)
        rec = _recommend(value, ANCH, remaining=1000, budget=100, week=14)
        assert rec["bids"]["maxRational"] == min(1000, math.floor(raw * 100))
        assert cap_pre is None or rec["bids"]["maxRational"] > cap_pre
        cap_pre = rec["bids"]["maxRational"]


# ---- 3. team layer ----------------------------------------------------------


@pytest.mark.parametrize("status", ["contender", "bubble", "rebuilder"])
@pytest.mark.parametrize("playoff_start", [15, 13])
def test_season_option_factor_matches_independent_formula(status, playoff_start):
    for week in range(1, 18):
        f, _ = FE.season_option_value(
            FE.LeagueContext(in_season=True, current_week=week, playoff_week_start=playoff_start),
            FE.TeamContext(competitive_status=status),
        )
        assert f == pytest.approx(_o_option(week, playoff_start, status), abs=1e-12), week


def test_ceiling_relaxes_monotonically_toward_one_late_in_the_season():
    factors = [
        FE.season_option_value(FE.LeagueContext(in_season=True, current_week=w), FE.TeamContext())[
            0
        ]
        for w in range(1, 17)
    ]
    assert factors == sorted(factors)
    assert factors[0] == pytest.approx(OPT_EARLY) and factors[-1] == 1.0
    # end-to-end: the team ceiling in dollars follows the same factor
    value = O_REPL + 0.7 * (O_ALLIN - O_REPL)
    disp, _ = _o_curve(value, O_ALLIN, O_REPL)
    for w in (1, 5, 10, 14):
        rec = _recommend(value, ANCH, week=w)
        assert rec["teamCeilingDollars"] == round(min(100.0, disp * 100 * _o_option(w)))


def test_eliminated_team_has_no_future_use_for_budget():
    f, _ = FE.season_option_value(
        FE.LeagueContext(in_season=True, current_week=1),
        FE.TeamContext(competitive_status="eliminated"),
    )
    assert f == _o_option(1, status="eliminated") == 1.0


@pytest.mark.parametrize("drop", [0.0, O_REPL - 500.0, O_REPL])
def test_dropping_a_below_or_at_replacement_player_is_free(drop):
    value = O_REPL + 0.75 * (O_ALLIN - O_REPL)
    rec = FE.recommend(
        FE.PlayerInput(name="P", value=value, drop_name="D", drop_value=drop),
        FE.LeagueContext(in_season=True, current_week=14),
        FE.TeamContext(faab_remaining=100, open_roster_spots=0),
        anchors=ANCH,
    )
    free = _recommend(value, ANCH, week=14)
    assert rec["teamCeilingDollars"] == free["teamCeilingDollars"]


def test_dropping_a_valuable_player_subtracts_surplus_exactly():
    add = O_REPL + 0.9 * (O_ALLIN - O_REPL)
    drop = O_REPL + 0.4 * (O_ALLIN - O_REPL)
    rec = FE.recommend(
        FE.PlayerInput(name="P", value=add, drop_name="D", drop_value=drop),
        FE.LeagueContext(in_season=True, current_week=14),
        FE.TeamContext(faab_remaining=100, open_roster_spots=0),
        anchors=ANCH,
    )
    net_value = O_REPL + (add - O_REPL) - (drop - O_REPL)
    disp, _ = _o_curve(net_value, O_ALLIN, O_REPL)
    assert rec["teamCeilingDollars"] == round(min(100.0, disp * 100))
    # the objective (what he is worth) is untouched by the roster consequence
    assert rec["objective"]["dollars"] == round(_o_curve(add, O_ALLIN, O_REPL)[0] * 100)


def test_recommended_never_exceeds_balance_across_a_grid():
    rivals = [FE.RivalTeam(owner_id=f"r{i}", faab_remaining=100) for i in range(11)]
    for value in (O_REPL + 5, O_ALLIN, O_ALLIN * 1.4):
        for remaining in (0, 1, 9, 33, 100):
            for posture in ("conservative", "balanced", "aggressive"):
                b = _recommend(
                    value, ANCH, remaining=remaining, rivals=rivals, risk_posture=posture
                )["bids"]
                assert b["recommended"] <= remaining
                assert b["conservative"] <= b["recommended"] <= b["aggressive"] <= b["maxRational"]
                assert b["maxRational"] <= remaining


# ---- 4. market layer --------------------------------------------------------

RIVAL_FIELDS = {
    "homogeneous": [(100, "neutral", 1.0)] * 11,
    "mixed": [
        (100, "neutral", 1.0),
        (100, "starterHole", 1.4),
        (100, "need", 0.7),
        (60, "surplus", 1.0),
        (25, "neutral", 2.0),
        (100, "need", 1.0),
    ],
}


def _engine_rivals(field):
    return [
        FE.RivalTeam(owner_id=f"r{i}", faab_remaining=r, need_level=n, aggression=a)
        for i, (r, n, a) in enumerate(field)
    ]


@pytest.mark.parametrize("field", RIVAL_FIELDS)
@pytest.mark.parametrize("frac", [0.35, 0.6, 0.9, 1.0, 1.6, 3.0])
@pytest.mark.parametrize("remaining", [100, 45])
def test_recommended_bid_equals_brute_force_expected_surplus_optimum(field, frac, remaining):
    value = O_REPL + frac * (O_ALLIN - O_REPL)
    week = 14  # option factor 1.0 -> team raw ceiling == objective raw ceiling
    rec = _recommend(
        value, ANCH, remaining=remaining, week=week, rivals=_engine_rivals(RIVAL_FIELDS[field])
    )
    _, raw = _o_curve(value, O_ALLIN, O_REPL)
    raw_dollars = raw * 100
    demand = min(1.0, raw / SAT)
    hard_cap = min(remaining, math.floor(raw_dollars))
    grid = range(0, hard_cap + 1)  # <= 400 points -> the engine's grid is every integer
    assert hard_cap <= 400
    ev = [_o_win(b, RIVAL_FIELDS[field], 100, demand) * max(0.0, raw_dollars - b) for b in grid]
    best = max(ev)
    expect = next((b for b, e in zip(grid, ev) if best > 0 and e >= best * (1 - MIN_EDGE)), 0)
    got = rec["bids"]["recommended"]
    assert got == expect
    if best > 0:
        # cheapest bid within minEdge of the true argmax, never above it
        argmax = max(range(len(ev)), key=lambda i: ev[i])
        assert got <= argmax
        assert ev[got] >= best * (1 - MIN_EDGE) - 1e-12
        assert got < raw_dollars  # bidding the ceiling captures zero surplus
    # win probability is reported at the recommended bid
    if rec["winProbability"] is not None:
        assert rec["winProbability"] == pytest.approx(
            _o_win(got, RIVAL_FIELDS[field], 100, demand), abs=1e-3
        )


@pytest.mark.parametrize("field", RIVAL_FIELDS)
def test_expected_surplus_at_the_ceiling_is_exactly_zero(field):
    raw_dollars = 40.0
    for b in (raw_dollars,):
        assert _o_win(b, RIVAL_FIELDS[field], 100, 0.5) * max(0.0, raw_dollars - b) == 0.0


@pytest.mark.parametrize("field", RIVAL_FIELDS)
def test_clearing_price_quantiles_match_independent_scan(field):
    value = O_REPL + 0.9 * (O_ALLIN - O_REPL)
    rec = _recommend(value, ANCH, week=14, rivals=_engine_rivals(RIVAL_FIELDS[field]))
    _, raw = _o_curve(value, O_ALLIN, O_REPL)
    demand = min(1.0, raw / SAT)
    cdf = [_o_win(b, RIVAL_FIELDS[field], 100, demand) for b in range(0, 101)]

    def q(t):
        return next((b for b, p in enumerate(cdf) if p >= t), 100)

    assert (rec["bids"]["clearingLow"], rec["bids"]["clearing"], rec["bids"]["clearingHigh"]) == (
        q(0.25),
        q(0.5),
        q(0.75),
    )


@pytest.mark.parametrize("bid", [0.5, 1.0, 3.0, 8.0, 20.0, 55.0])
@pytest.mark.parametrize("demand", [0.0, 0.3, 0.8, 1.0])
def test_engine_win_probability_equals_zero_inflated_lognormal_oracle(bid, demand):
    field = RIVAL_FIELDS["mixed"]
    got = FE.rival_bid_cdf(
        bid,
        _engine_rivals(field),
        demand_signal=demand,
        league=FE.LeagueContext(),
        config=FE.FaabConfig(),
    )
    assert got == pytest.approx(_o_win(bid, field, 100, demand), abs=1e-12)


def test_a_rival_with_unknown_balance_never_raises_our_bid_or_price():
    known = _engine_rivals(RIVAL_FIELDS["mixed"])
    unknown = [*known, FE.RivalTeam(owner_id="ghost", faab_remaining=None, aggression=2.0)]
    value = O_REPL + 0.9 * (O_ALLIN - O_REPL)
    a = _recommend(value, ANCH, week=14, rivals=known)["bids"]
    b = _recommend(value, ANCH, week=14, rivals=unknown)["bids"]
    assert a == b


# crowd ----------------------------------------------------------------------


@pytest.mark.parametrize("pct", [0.0, 2.0, 10.0, 40.0])
@pytest.mark.parametrize("demand", [0.05, 0.4, 0.9])
def test_crowd_winning_bid_is_converted_to_a_per_rival_level_exactly_once(pct, demand):
    """Single rival, bid placed AT the oracle's per-rival median: P(beat) is
    exactly 1/2 there, so win = 1 - p/2.  A double order-statistic correction
    (or none) would move the median away from the oracle's and break this."""
    p = _o_engagement(demand)
    med = _o_median_bid(100, demand, 1.0, 100, crowd_pct=pct)
    if med >= 100:
        pytest.skip("median clipped by balance")
    got = FE.rival_bid_cdf(
        med,
        [FE.RivalTeam(owner_id="r", faab_remaining=100)],
        demand_signal=demand,
        league=FE.LeagueContext(),
        config=FE.FaabConfig(),
        crowd_median_pct=pct,
    )
    assert got == pytest.approx(1 - p / 2, abs=1e-9)
    # and the conversion is the documented blend: (1-w)*modelled + w*pct*0.53
    modelled = SH_BASE + (SH_MAX - SH_BASE) * demand**SH_EXP
    assert med == pytest.approx(
        max(MIN_MEDIAN, 100 * ((1 - CROWD_W) * modelled + CROWD_W * pct / 100 * CROWD_TO_RIVAL))
    )


def test_crowd_share_only_lifts_engagement_by_the_documented_floor():
    demand, share = 0.0, 0.2
    p = _o_engagement(demand, crowd_share=share)
    assert p == pytest.approx(min(ENG_TOP, ENG_BASE + CROWD_LIFT * share))
    got = FE.rival_bid_cdf(
        0.0,
        [FE.RivalTeam(owner_id="r", faab_remaining=100)],
        demand_signal=demand,
        league=FE.LeagueContext(),
        config=FE.FaabConfig(),
        crowd_share=share,
    )
    assert got == pytest.approx(1 - p)  # a $0 claim wins only if nobody contests


def test_crowd_and_trending_move_the_market_and_never_the_ceiling():
    value = O_REPL + 0.5 * (O_ALLIN - O_REPL)
    rivals = _engine_rivals(RIVAL_FIELDS["homogeneous"])
    kw = dict(
        player=FE.PlayerInput(name="P", value=value),
        league=FE.LeagueContext(in_season=True, current_week=14),
        team=FE.TeamContext(faab_remaining=100),
        anchors=ANCH,
        rivals=rivals,
    )
    base = FE.recommend(**kw)
    hot = FE.recommend(
        **kw,
        crowd={"medianPct": 40.0, "claims": 20, "shareOfClaims": 0.3},
        trending={"share": 0.9},
    )
    assert hot["objective"] == base["objective"]
    assert hot["teamCeilingDollars"] == base["teamCeilingDollars"]
    assert hot["bids"]["maxRational"] == base["bids"]["maxRational"]
    assert hot["bids"]["clearing"] > base["bids"]["clearing"]  # price expectation rises
    assert hot["bids"]["recommended"] <= hot["bids"]["maxRational"]


# ---- 5. missing is never zero ----------------------------------------------


def _opps(n=11):
    return [
        {"ownerId": f"o{i}", "name": f"T{i}", "faabRemaining": 100, "players": []} for i in range(n)
    ]


def test_no_bid_history_falls_back_to_neutral_priors_and_says_so():
    rivals = build_rivals(_opps(), market_priors=None, league_summary=None)
    assert all(r.aggression == 1.0 and r.low_sample for r in rivals)  # prior, flagged
    out = recommend_faab(
        add_player_value=8700.0,
        add_player_name="Target",
        league_budget=100,
        board_values=LINEAR,
        team_faab_remaining=100,
        rivals=rivals,
        current_week=8,
    )
    missing = [f for f in out["factors"] if f["label"] == "League bid history"]
    assert missing and missing[0]["missing"] is True  # the absence is stated
    # A valuable player is not priced at $0 because history is missing.
    assert out["objective"]["dollars"] > 0
    assert out["bids"]["recommended"] > 0
    # the answer equals the one from explicit neutral aggression (the prior), not a degenerate value
    explicit = recommend_faab(
        add_player_value=8700.0,
        add_player_name="Target",
        league_budget=100,
        board_values=LINEAR,
        team_faab_remaining=100,
        rivals=[FE.RivalTeam(owner_id=r.owner_id, faab_remaining=100) for r in rivals],
        current_week=8,
    )
    assert out["bids"] == explicit["bids"]


def test_no_rival_balances_is_reported_missing_not_treated_as_free():
    rec = _recommend(O_ALLIN, ANCH, rivals=[FE.RivalTeam(owner_id="r", faab_remaining=None)])
    comp = next(f for f in rec["factors"] if f["label"] == "Expected competition")
    assert comp["missing"] is True
    assert rec["objective"]["dollars"] == 100  # worth is independent of competition data
