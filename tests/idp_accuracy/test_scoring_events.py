"""Event-level scoring tests for ``dynasty_main`` (IDP accuracy Deliverable A).

Owner directive ``docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md`` §6B.

Every expectation is DERIVED from the pinned 2026 card recorded in
``docs/valuation/idp_accuracy/MANIFEST.json`` (fetched from Sleeper, never typed
in here) — except the owner-checklist facts, which are asserted literally because
the checklist is what is being verified.  Stacking is not assumed: the stacking
test cites the awarded-points evidence that established it.

Two production scorer paths are tested, because both are live:

* host-native — ``compute_weekly_points(..., source="sleeper")`` on Sleeper's own
  stat vocabulary (the path verified 3,710 / 3,710 against awarded points);
* nflverse — ``compute_weekly_points(...)`` (default source) on nflverse
  ``stats_player_week`` columns, the in-season BDVM path.

Genuine scorer defects found by the reconciliation are ``xfail(strict=True)`` with
an ``IDPA-DEFECT-*`` reason: they document the defect without fixing production
code in this research lane, and the strict flag fails the suite the moment a fix
lands so the marker is removed deliberately.

No network, no live board.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.league_comparison.sleeper_scoring import scoring_fingerprint
from src.nfl_data.realized_points import compute_weekly_points
from src.ros.lineup import (
    OBJECTIVE_REALIZED_POINTS,
    RosterPlayer,
    player_eligible_for_slot,
    solve_optimal_assignment,
)

REPO = Path(__file__).resolve().parents[2]
MANIFEST = json.loads((REPO / "docs/valuation/idp_accuracy/MANIFEST.json").read_text())
EVIDENCE = json.loads(
    (REPO / "docs/valuation/idp_accuracy/evidence/scorer_reconciliation.json").read_text()
)
CARD: dict[str, float] = MANIFEST["scoringCard"]["nonZeroRules"]
SLOTS: list[str] = MANIFEST["rosterFormat"]["starterSlots"]


def _rate(key: str) -> float:
    return float(CARD.get(key, 0.0))


def host(line: dict, *, pos: str = "LB", sid: str = "9999") -> float:
    res = compute_weekly_points(
        {**line, "player_id": sid, "season": 2026, "week": 1}, CARD, position=pos, source="sleeper"
    )
    assert res is not None
    return res.fantasy_points


def nflv(line: dict, *, pos: str) -> float:
    res = compute_weekly_points({**line, "season": 2026, "week": 1, "position": pos}, CARD,
                                position=pos)  # fmt: skip
    assert res is not None
    return res.fantasy_points


# ── the pinned card itself ────────────────────────────────────────────────────


def test_manifest_fingerprint_is_the_fingerprint_of_the_recorded_card():
    assert scoring_fingerprint(CARD) == MANIFEST["scoringCard"]["scoringFingerprint"]
    assert MANIFEST["league"]["sleeperLeagueId"] == "1312006700437352448"
    assert MANIFEST["league"]["key"] == "dynasty_main"
    assert MANIFEST["league"]["registryMatches"] is True


def test_owner_checklist_verified_from_snapshot_has_no_discrepancy():
    items = {c["item"]: c for c in MANIFEST["ownerChecklist"]["items"]}
    assert MANIFEST["ownerChecklist"]["discrepancies"] == []
    assert items["12 teams"]["observed"] == 12
    assert items["58 roster spots"]["observed"] == 58
    assert items["21 starters"]["observed"] == 21
    assert items["9 IDP starters (108 league-wide)"]["observed"] == 9
    assert "IDP_FLEX" not in SLOTS
    assert SLOTS.count("DL") == SLOTS.count("LB") == SLOTS.count("DB") == 3


def test_card_has_no_te_reception_premium():
    assert _rate("bonus_rec_te") == 0.0
    assert _rate("bonus_fd_te") == _rate("bonus_fd_wr") == _rate("bonus_fd_rb")


# ── IDP events, host-native vocabulary ────────────────────────────────────────


def test_solo_and_assisted_tackles():
    assert host({"idp_tkl_solo": 1}) == pytest.approx(_rate("idp_tkl_solo"))
    assert host({"idp_tkl_ast": 1}) == pytest.approx(_rate("idp_tkl_ast"))
    # Sleeper also publishes combined idp_tkl; the card prices it at 0, so the
    # combined count must not add anything on top of solo + assist.
    assert _rate("idp_tkl") == 0.0
    got = host({"idp_tkl_solo": 3, "idp_tkl_ast": 2, "idp_tkl": 5})
    assert got == pytest.approx(3 * _rate("idp_tkl_solo") + 2 * _rate("idp_tkl_ast"))


def test_tackle_for_loss_is_enhanced():
    assert host({"idp_tkl_loss": 1}) == pytest.approx(_rate("idp_tkl_loss"))
    assert _rate("idp_tkl_loss") > _rate("idp_tkl_solo")


def test_sack_and_sack_yards():
    got = host({"idp_sack": 1.5, "idp_sack_yd": 12})
    assert got == pytest.approx(1.5 * _rate("idp_sack") + 12 * _rate("idp_sack_yd"))
    assert _rate("idp_sack_yd") == pytest.approx(1 / 9)


def test_qb_hit_and_its_alias_pay_exactly_once():
    assert host({"idp_qb_hit": 2}) == pytest.approx(2 * _rate("idp_qb_hit"))
    # a line carrying BOTH spellings must not pay twice
    assert host({"idp_qb_hit": 1, "idp_hit": 1}) == pytest.approx(_rate("idp_qb_hit"))


def test_pass_defended_is_enhanced_and_alias_pays_once():
    assert host({"idp_pass_def": 1}) == pytest.approx(_rate("idp_pass_def"))
    assert host({"idp_pass_def": 1, "idp_pd": 1}) == pytest.approx(_rate("idp_pass_def"))
    assert _rate("idp_pass_def") > _rate("idp_tkl_solo")
    # the 3+ PD bonus key exists on the card at 0 — a 3-PD game earns no bonus
    assert _rate("idp_pass_def_3p") == 0.0
    assert host({"idp_pass_def": 3, "idp_pass_def_3p": 1}) == pytest.approx(
        3 * _rate("idp_pass_def")
    )


def test_interception_forced_fumble_and_recovery():
    got = host({"idp_int": 1, "idp_int_ret_yd": 27, "idp_ff": 1, "idp_fum_rec": 1,
                "idp_fum_ret_yd": 9})  # fmt: skip
    want = (
        _rate("idp_int") + 27 * _rate("idp_int_ret_yd") + _rate("idp_ff") + _rate("idp_fum_rec")
        + 9 * _rate("idp_fum_ret_yd")
    )  # fmt: skip
    assert got == pytest.approx(want)


def test_pick_six_stacks_int_return_yards_and_defensive_td():
    got = host({"idp_int": 1, "idp_int_ret_yd": 45, "idp_def_td": 1,
                "bonus_def_int_td_50p": 0})  # fmt: skip
    want = _rate("idp_int") + 45 * _rate("idp_int_ret_yd") + _rate("idp_def_td")
    assert got == pytest.approx(want)


def test_safety_and_blocked_kick():
    assert host({"idp_safe": 1}) == pytest.approx(_rate("idp_safe"))
    assert host({"idp_blk_kick": 1}) == pytest.approx(_rate("idp_blk_kick"))


def test_special_teams_individual_plays_and_return_td():
    got = host({"st_tkl_solo": 1, "st_ff": 1, "st_fum_rec": 1}, pos="WR")
    assert got == pytest.approx(_rate("st_tkl_solo") + _rate("st_ff") + _rate("st_fum_rec"))
    got = host({"kr_yd": 98, "st_td": 1}, pos="WR")
    assert got == pytest.approx(98 * _rate("kr_yd") + _rate("st_td"))


def test_sack_stacks_with_tfl_and_qb_hit():
    """Sleeper pays every key on the line — derived from awarded data, not assumed."""
    s = EVIDENCE["stacking"]
    assert s["playerWeeksWithSackAndTflOrHit"] > 100
    assert s["matchUnderStackingHypothesis"] == s["playerWeeksWithSackAndTflOrHit"]
    assert s["matchUnderNoStackingHypothesis"] == 0
    line = {"idp_sack": 1, "idp_sack_yd": 7, "idp_tkl_loss": 1, "idp_qb_hit": 1,
            "idp_tkl_solo": 1}  # fmt: skip
    want = (
        _rate("idp_sack") + 7 * _rate("idp_sack_yd") + _rate("idp_tkl_loss")
        + _rate("idp_qb_hit") + _rate("idp_tkl_solo")
    )  # fmt: skip
    assert host(line) == pytest.approx(want)


def test_idp_stats_are_paid_to_an_offensive_player_on_the_host_path():
    # A WR's tackle after his own interception: Sleeper pays idp_* to anyone.
    assert host({"idp_tkl_solo": 1, "idp_ff": 1}, pos="WR") == pytest.approx(
        _rate("idp_tkl_solo") + _rate("idp_ff")
    )


# ── offense events ────────────────────────────────────────────────────────────


def test_six_point_passing_td_and_yardage():
    assert _rate("pass_td") == 6.0
    got = host({"pass_td": 2, "pass_yd": 250, "pass_cmp": 20, "pass_inc": 10,
                "pass_int": 1}, pos="QB")  # fmt: skip
    want = (
        2 * 6.0 + 250 * _rate("pass_yd") + 20 * _rate("pass_cmp") + 10 * _rate("pass_inc")
        + _rate("pass_int")
    )  # fmt: skip
    assert got == pytest.approx(want)


@pytest.mark.parametrize(
    "tier,yards",
    [
        ("rec_0_4", 3),
        ("rec_5_9", 7),
        ("rec_10_19", 15),
        ("rec_20_29", 25),
        ("rec_30_39", 33),
        ("rec_40p", 55),
    ],  # fmt: skip
)
def test_tiered_reception_pays_flat_rate_plus_length_tier(tier, yards):
    assert _rate(tier) > 0
    got = host({"rec": 1, tier: 1, "rec_yd": yards}, pos="TE")
    assert got == pytest.approx(_rate("rec") + _rate(tier) + yards * _rate("rec_yd"))


def test_wr_reception_bonus_is_paid_and_te_reception_bonus_is_zero():
    assert host({"rec": 1, "bonus_rec_wr": 1}, pos="WR") == pytest.approx(
        _rate("rec") + _rate("bonus_rec_wr")
    )
    assert host({"rec": 1, "bonus_rec_te": 1}, pos="TE") == pytest.approx(_rate("rec"))


def test_fumble_lost_is_negative_and_precomputed_totals_are_never_scored():
    assert host({"fum_lost": 1}, pos="RB") == pytest.approx(_rate("fum_lost"))
    assert _rate("fum_lost") < 0
    assert host({"rush_yd": 10, "pts_ppr": 99.0, "pts_std": 50.0, "pos_rank_std": 3},
                pos="RB") == pytest.approx(10 * _rate("rush_yd"))  # fmt: skip


def test_team_defense_entry_is_refused_not_zeroed():
    res = compute_weekly_points({"player_id": "PHI", "season": 2026, "week": 1, "int": 2},
                                CARD, source="sleeper")  # fmt: skip
    assert res is None


# ── nflverse vocabulary (in-season BDVM path) ─────────────────────────────────


def test_nflverse_idp_row_stacks_the_same_way():
    row = {"def_tackles_solo": 2, "def_tackle_assists": 1, "def_tackles_for_loss": 1,
           "def_sacks": 1, "def_sack_yards": 9, "def_qb_hits": 1, "def_pass_defended": 1}  # fmt: skip
    want = (
        2 * _rate("idp_tkl_solo") + _rate("idp_tkl_ast") + _rate("idp_tkl_loss")
        + _rate("idp_sack") + 9 * _rate("idp_sack_yd") + _rate("idp_qb_hit")
        + _rate("idp_pass_def")
    )  # fmt: skip
    assert nflv(row, pos="DE") == pytest.approx(want)


@pytest.mark.xfail(
    strict=True,
    reason="IDPA-DEFECT-01: nflverse normalization drops def_* stats for a non-IDP "
    "listed position; Sleeper pays idp_* to any player (80 player-weeks, 2026 wk1-6, "
    "-117.8 pts; docs/valuation/idp_accuracy/A_SCORING_ACCURACY.md)",
)
def test_nflverse_pays_idp_stats_to_an_offensive_player():
    row = {"receiving_tds": 1, "def_tackles_solo": 1, "def_fumbles_forced": 1}
    assert nflv(row, pos="WR") == pytest.approx(
        _rate("rec_td") + _rate("idp_tkl_solo") + _rate("idp_ff")
    )


@pytest.mark.xfail(
    strict=True,
    reason="IDPA-DEFECT-02: a blocked FG (fg_blocked) is not scored as a miss in its "
    "distance band; Sleeper counts it as fgmiss_<band> (6 kicker-weeks + 1 blocked PAT)",
)
def test_nflverse_blocked_field_goal_scores_as_a_miss():
    row = {"fg_att": 1, "fg_blocked": 1, "fg_blocked_distance": 47, "fg_blocked_list": 47}
    assert nflv(row, pos="K") == pytest.approx(_rate("fgmiss_40_49"))


@pytest.mark.xfail(
    strict=True,
    reason="IDPA-DEFECT-02: a blocked PAT (pat_blocked) is not scored as xpmiss",
)
def test_nflverse_blocked_pat_scores_as_a_miss():
    row = {"pat_att": 1, "pat_blocked": 1}
    assert nflv(row, pos="K") == pytest.approx(_rate("xpmiss"))


@pytest.mark.xfail(
    strict=True,
    reason="IDPA-DEFECT-03: a defensive fumble-return TD (fumble_recovery_tds on an IDP "
    "row) is not mapped to idp_def_td (2 player-weeks, -12.72 pts)",
)
def test_nflverse_fumble_return_td_is_a_defensive_td():
    row = {"def_tackles_solo": 1, "fumble_recovery_opp": 1, "fumble_recovery_yards_opp": 27,
           "fumble_recovery_tds": 1}  # fmt: skip
    want = (
        _rate("idp_tkl_solo") + _rate("idp_fum_rec") + 27 * _rate("idp_fum_ret_yd")
        + _rate("idp_def_td")
    )  # fmt: skip
    assert nflv(row, pos="LB") == pytest.approx(want)


# ── Sleeper multi-position eligibility ────────────────────────────────────────


def _p(pid, pos, fps=(), pts=10.0):
    return RosterPlayer(player_id=pid, canonical_name=pid, position=pos, ros_value=pts,
                        fantasy_positions=tuple(fps))  # fmt: skip


def test_dl_lb_hybrid_is_eligible_at_both_and_nowhere_else():
    p = _p("x", "DE", ("DL", "LB"))
    assert player_eligible_for_slot("DL", p) and player_eligible_for_slot("LB", p)
    assert not player_eligible_for_slot("DB", p)
    assert not player_eligible_for_slot("FLEX", p)
    assert not player_eligible_for_slot("SUPER_FLEX", p)


def test_single_position_lb_cannot_start_at_dl():
    assert not player_eligible_for_slot("DL", _p("y", "LB", ("LB",)))


def test_db_wr_two_way_player_is_eligible_on_both_sides():
    p = _p("z", "CB", ("DB", "WR"))
    for slot in ("DB", "WR", "FLEX", "SUPER_FLEX"):
        assert player_eligible_for_slot(slot, p), slot
    assert not player_eligible_for_slot("LB", p)


def test_exact_solver_moves_a_hybrid_to_the_slot_that_maximizes_the_lineup():
    # 3 DL-only players, 2 LB-only, 1 DL/LB hybrid: the optimum starts the hybrid at LB.
    pool = [_p(f"dl{i}", "DT", ("DL",), 20 - i) for i in range(3)]
    pool += [_p(f"lb{i}", "LB", ("LB",), 15 - i) for i in range(2)]
    pool.append(_p("hyb", "DE", ("DL", "LB"), 30))
    idp_slots = ["DL", "DL", "DL", "LB", "LB", "LB"]
    sol = solve_optimal_assignment(pool, idp_slots, objective=OBJECTIVE_REALIZED_POINTS)
    assigned = {i: p.player_id for i, p in sol.items()}
    assert len(assigned) == 6
    assert sum(p.ros_value for p in sol.values()) == pytest.approx(30 + 19 + 18 + 20 + 15 + 14)
    hyb_slot = next(idp_slots[i] for i, pid in assigned.items() if pid == "hyb")
    assert hyb_slot == "LB"


def test_sleepers_own_starters_were_all_legal_under_our_eligibility_rule():
    lu = EVIDENCE["lineups"]
    assert lu["sleeperStarterSlotsChecked"] > 1000
    assert lu["sleeperStartersIneligibleUnderOurRule"] == []
    # Sleeper really does use the second fantasy position (not just the listed one)
    assert lu["startsOutsidePrimaryPosition"].get("LB->DL", 0) > 0
    assert lu["startsOutsidePrimaryPosition"].get("DL->LB", 0) > 0


def test_exact_solver_reproduces_every_sleeper_best_ball_team_total():
    lu = EVIDENCE["lineups"]
    a = lu["optimalTotalFromAwardedPlayerPoints"]
    assert a["matchWithin0.015"] == lu["teamWeeks"] == 72
    assert a["dist"]["maxAbs"] == 0.0


# ── reconciliation evidence pins (host-native path) ───────────────────────────


def test_host_native_reconciliation_has_no_unexplained_exception():
    h = EVIDENCE["hostNative"]
    assert h["exceptions"] == []
    assert set(h["census"]) <= {"match", "no_stat_line_awarded_zero"}
    assert h["distribution"]["maxAbs"] <= 0.005  # Sleeper's own 2-decimal rounding
    b = h["reproduceInvestigationB"]["reproduced"]
    assert b == {"playerWeeks": 3299, "exactWithin0.01": 3299, "maxAbsDiff": 0.0044}
