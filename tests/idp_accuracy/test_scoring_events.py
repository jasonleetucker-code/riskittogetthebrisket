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

Genuine scorer defects found by the reconciliation (``IDPA-DEFECT-*``) were first
pinned here as ``xfail(strict=True)`` by the research lane, which fixed nothing.
They are fixed in ``src/nfl_data/realized_points.py`` (01, 02, 03) and the markers
are gone: each test below now asserts the corrected behaviour.  IDPA-DEFECT-04 is
NOT a scorer defect (a provider position-listing disagreement) and is pinned at the
bottom of the nflverse section as the boundary of what the scorer can know.

No network, no live board.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.league_comparison.sleeper_scoring import scoring_fingerprint
from src.nfl_data.realized_points import (
    PBP_SUPPLEMENT_ROW_KEY,
    compute_weekly_points,
    sleeper_stat_line_from_row,
)
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
FIX = json.loads(
    (REPO / "docs/valuation/idp_accuracy/evidence/scorer_fix_measure.json").read_text()
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


def nflv_pbp(line: dict, *, pos: str, **supplement: float) -> float:
    """``nflv`` with the play-by-play supplement attached, as ``bdvm_api`` runs it."""
    row = {**line, PBP_SUPPLEMENT_ROW_KEY: dict(supplement)}
    return nflv(row, pos=pos)


def stat_line(line: dict, *, pos: str) -> dict:
    return sleeper_stat_line_from_row({**line, "season": 2026, "week": 1}, position=pos)


# IDPA-DEFECT-01 — defensive events are paid whoever records them ──────────────


def test_nflverse_pays_idp_stats_to_an_offensive_player():
    row = {"receiving_tds": 1, "def_tackles_solo": 1, "def_fumbles_forced": 1}
    assert nflv(row, pos="WR") == pytest.approx(
        _rate("rec_td") + _rate("idp_tkl_solo") + _rate("idp_ff")
    )


def test_the_listed_position_no_longer_decides_whether_a_defensive_stat_counts():
    row = {"def_sacks": 1, "def_qb_hits": 1, "def_pass_defended": 1, "def_interceptions": 1}
    want = nflv(row, pos="DE")
    assert want > 0
    for pos in ("QB", "RB", "WR", "TE", "K", "LB", "DB"):
        assert nflv(row, pos=pos) == pytest.approx(want), pos


def test_a_blocked_punt_by_a_non_idp_player_is_paid_idp_blk_kick():
    # Simi Fehoko (WR) wk1 and Julius Chestnut (RB) wk6, 2026: both carry
    # idp_blk_kick 1 on Sleeper's own line and were awarded 5.30.
    assert nflv({"def_punt_blocks": 1}, pos="WR") == pytest.approx(_rate("idp_blk_kick"))
    assert nflv({"def_punt_blocks": 1}, pos="LB") == pytest.approx(_rate("idp_blk_kick"))


def test_special_teams_tackle_is_not_paid_twice_to_an_idp_listed_player():
    # nflverse charts a punt-coverage tackle in def_tackles_solo; Sleeper pays it as
    # st_tkl_solo and NOT as idp_tkl_solo.  3 charted = 2 defensive + 1 special-teams
    # (440 IDP player-weeks in the wide 2026 wk1-6 sample were double-paid before).
    row = {"def_tackles_solo": 3}
    got = nflv_pbp(row, pos="LB", st_tkl_solo=1)
    assert got == pytest.approx(2 * _rate("idp_tkl_solo") + _rate("st_tkl_solo"))
    # without the supplement the split is unknown: the whole count is paid as before
    assert nflv(row, pos="LB") == pytest.approx(3 * _rate("idp_tkl_solo"))


def test_special_teams_tackle_by_a_non_idp_player_scores_once():
    row = {"def_tackles_solo": 1}
    assert nflv_pbp(row, pos="WR", st_tkl_solo=1) == pytest.approx(_rate("st_tkl_solo"))
    # a defensive tackle alongside a special-teams one is paid on top
    row = {"def_tackles_solo": 2}
    assert nflv_pbp(row, pos="TE", st_tkl_solo=1) == pytest.approx(
        _rate("idp_tkl_solo") + _rate("st_tkl_solo")
    )


def test_special_teams_subtraction_never_goes_negative_and_skips_host_split_rows():
    # supplement larger than the charted count (a charting difference): clamp at 0
    assert nflv_pbp({"def_tackles_solo": 1}, pos="LB", st_tkl_solo=2) == pytest.approx(
        2 * _rate("st_tkl_solo")
    )
    # a row that already carries the HOST's defensive split is not reduced again
    row = {"idp_tkl_solo": 2, "def_tackles_solo": 2}
    assert nflv_pbp(row, pos="LB", st_tkl_solo=1) == pytest.approx(
        2 * _rate("idp_tkl_solo") + _rate("st_tkl_solo")
    )


def test_assisted_tackles_stay_idp_only_because_special_teams_assists_cannot_be_separated():
    """The documented RESIDUAL of IDPA-DEFECT-01.

    nflverse lumps special-teams assists into ``def_tackle_assists``; the host pays
    them nothing and the supplement has no ``st_tkl_ast``.  For a non-IDP player
    that column is special-teams on 162 of 175 player-weeks (wk1-6), so it is not
    paid; an IDP-listed player keeps being paid (his residual over-pay is measured
    in the doc and needs a ``st_tkl_ast`` supplement key to close).
    """
    assert nflv({"def_tackle_assists": 1}, pos="WR") == pytest.approx(0.0)
    assert nflv({"def_tackle_assists": 1}, pos="LB") == pytest.approx(_rate("idp_tkl_ast"))


def test_forced_fumble_is_defensive_only_and_not_reduced_by_special_teams():
    # nflverse def_fumbles_forced equals Sleeper idp_ff on 26/26 player-weeks, including
    # three where the same player also forced a special-teams fumble (st_ff): no overlap
    # to remove, so the supplement's st_ff must NOT be subtracted.
    got = nflv_pbp({"def_fumbles_forced": 1}, pos="DB", st_ff=1)
    assert got == pytest.approx(_rate("idp_ff") + _rate("st_ff"))


# IDPA-DEFECT-02 — a blocked kick is a MISS ───────────────────────────────────


def test_nflverse_blocked_field_goal_scores_as_a_miss():
    row = {"fg_att": 1, "fg_blocked": 1, "fg_blocked_distance": 47, "fg_blocked_list": 47}
    assert nflv(row, pos="K") == pytest.approx(_rate("fgmiss_40_49"))


def test_nflverse_blocked_pat_scores_as_a_miss():
    row = {"pat_att": 1, "pat_blocked": 1}
    assert nflv(row, pos="K") == pytest.approx(_rate("xpmiss"))


@pytest.mark.parametrize(
    "distance,band,wide",
    [
        (23, "fgmiss_20_29", None),  # Cairo Santos wk2 2026
        (49, "fgmiss_40_49", None),  # Tyler Loop wk2
        (54, "fgmiss_50_59", "fgmiss_50p"),  # Eddy Pineiro wk4
        (59, "fgmiss_50_59", "fgmiss_50p"),  # Brandon Aubrey wk3
        (62, "fgmiss_60p", "fgmiss_50p"),  # Brandon Aubrey wk4
    ],
)
def test_blocked_field_goal_lands_in_the_band_sleeper_assigns(distance, band, wide):
    line = stat_line({"fg_blocked": 1, "fg_blocked_list": distance}, pos="K")
    assert line[band] == 1.0
    assert line["fgmiss"] == 1.0
    assert (line.get(wide) == 1.0) if wide else ("fgmiss_50p" not in line)
    assert nflv({"fg_blocked": 1, "fg_blocked_list": distance}, pos="K") == pytest.approx(
        _rate(band)
    )


def test_blocked_and_missed_field_goals_both_count_and_the_string_list_parses():
    # Aubrey wk4: fg_missed 1 (65 yd) AND fg_blocked 1 (62 yd) -> Sleeper fgmiss_60p 2
    row = {"fg_missed": 1, "fg_missed_60_": 1, "fg_blocked": 1, "fg_blocked_list": "62"}
    assert stat_line(row, pos="K")["fgmiss_60p"] == 2.0
    # two blocked kicks written as a ';' list, as the feed does for fg_made_list
    line = stat_line({"fg_blocked": 2, "fg_blocked_list": "47;52"}, pos="K")
    assert line["fgmiss_40_49"] == 1.0 and line["fgmiss_50_59"] == 1.0 and line["fgmiss"] == 2.0


def test_blocked_field_goal_with_an_unplaceable_distance_is_not_put_in_a_guessed_band():
    # count says 2, list says 1: the band cannot be established, so none is invented --
    # but the (unbanded) miss total is still the observed 2.
    line = stat_line({"fg_blocked": 2, "fg_blocked_list": "47"}, pos="K")
    assert not [k for k in line if k.startswith("fgmiss_")]
    assert line["fgmiss"] == 2.0
    # a lone blocked kick may be banded from fg_blocked_distance when the list is absent
    assert stat_line({"fg_blocked": 1, "fg_blocked_distance": 38}, pos="K")["fgmiss_30_39"] == 1.0


# IDPA-DEFECT-03 — a defensive fumble-return TD is a defensive TD ──────────────


def test_nflverse_fumble_return_td_is_a_defensive_td():
    row = {"def_tackles_solo": 1, "fumble_recovery_opp": 1, "fumble_recovery_yards_opp": 27,
           "fumble_recovery_tds": 1}  # fmt: skip
    want = (
        _rate("idp_tkl_solo") + _rate("idp_fum_rec") + 27 * _rate("idp_fum_ret_yd")
        + _rate("idp_def_td")
    )  # fmt: skip
    assert nflv(row, pos="LB") == pytest.approx(want)


def test_fumble_return_td_is_capped_at_defensive_recoveries():
    base = {"fumble_recovery_tds": 1}
    # the player's own team's fumble recovered in the end zone is not a defensive TD
    assert stat_line({**base, "fumble_recovery_own": 1}, pos="LB").get("idp_def_td") is None
    # a special-teams recovery (the supplement says so) is not a defensive TD either
    row = {**base, "fumble_recovery_opp": 1, PBP_SUPPLEMENT_ROW_KEY: {"st_fum_rec": 1}}
    assert "idp_def_td" not in stat_line(row, pos="LB")
    # but a defensive one beside a special-teams one is
    row = {**base, "fumble_recovery_opp": 2, PBP_SUPPLEMENT_ROW_KEY: {"st_fum_rec": 1}}
    assert stat_line(row, pos="LB")["idp_def_td"] == 1.0


def test_fumble_return_td_is_never_paid_twice_with_def_tds():
    # a feed that already folds fumble-return TDs into def_tds must not be paid twice
    row = {"def_tds": 1, "fumble_recovery_opp": 1, "fumble_recovery_tds": 1}
    assert stat_line(row, pos="LB")["idp_def_td"] == 1.0
    # and the interception-return TD (def_tds only) is unchanged
    assert stat_line({"def_tds": 1, "def_interceptions": 1}, pos="DB")["idp_def_td"] == 1.0


# IDPA-DEFECT-04 — NOT a scorer defect: the boundary of what the scorer knows ──


def test_first_down_bonus_follows_the_position_it_is_given():
    """Hunter Luepke (nflverse RB, Sleeper FB), 3 player-weeks, +3.0 points.

    ``sleeper_stat_line_from_row`` is faithful: handed ``"FB"`` it pays no
    ``bonus_fd_*`` (the host prices no FB first down), handed ``"RB"`` it pays the RB
    rate.  nflverse says RB; the Sleeper listing is not an input on the in-season
    path, so this is two stat providers listing one player differently, not a
    scoring error.  Fixing it means bringing Sleeper's position into
    ``weekly_points_from_rows`` -- a new cross-provider input, not a scorer repair.
    """
    row = {"rushing_first_downs": 1}
    assert stat_line(row, pos="RB")["bonus_fd_rb"] == 1.0
    assert not [k for k in stat_line(row, pos="FB") if k.startswith("bonus_fd_")]


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


# ── scorer-fix evidence pins (scripts/idp_accuracy/scorer_fix_measure.py) ─────


def test_fix_evidence_reruns_the_lane_a_reconciliation_on_the_pinned_rows():
    assert FIX["inputs"]["matchesPinnedLaneAHash"] is True
    assert (
        FIX["inputs"]["nflverseRowsCanonicalSha256"]
        == EVIDENCE["nflverse"]["nflverseRowsCanonicalSha256"]
    )
    before, stage1, final = (
        FIX["rostered"][k] for k in ("before", "stage1_defects_01_02_03_only", "final")
    )
    # "before" is the committed Lane A evidence verbatim
    assert before["withinTol"] == EVIDENCE["nflverse"]["distribution"]["withinTol"] == 2832
    assert before["n"] == stage1["n"] == final["n"] == 3095
    assert before["withinTol"] < stage1["withinTol"] < final["withinTol"] == 2976
    for group, v in final["byGroup"].items():  # no position gets worse
        assert v["withinTol"] >= before["byGroup"][group]["withinTol"], group
    # what is left of the pinned defects, and why: 01 is the deliberately-unpaid
    # non-IDP assists, 04 is the providers disagreeing on a position listing
    assert {k: v["playerWeeks"] for k, v in final["defects"].items()} == {
        "IDPA-DEFECT-01": 5,
        "IDPA-DEFECT-04": 3,
    }
    assert {e["name"] for e in final["exceptions"] if "IDPA-DEFECT-01" in e.get("attribution", [])} == {
        "Kyle Pitts Sr.", "Drake London", "Jakobi Meyers", "Justin Herbert", "Kimani Vidal",
    }  # fmt: skip


def test_fix_evidence_wide_sample_shows_no_regression_against_the_base_scorer():
    w = FIX["wideSample"]
    assert w["joinedPlayerWeeks"] == 6387
    assert w["newlyWrongVsBase_stage1"] == 0 and w["newlyWrongVsBase_final"] == 0
    assert w["base"]["withinTol"] < w["stage1_defects_01_02_03_only"]["withinTol"]
    assert w["stage1_defects_01_02_03_only"]["withinTol"] < w["final"]["withinTol"]
    for group, v in w["final"]["byGroup"].items():
        assert v["withinTol"] >= w["base"]["byGroup"][group]["withinTol"], group


def test_special_teams_tackle_rule_is_backed_by_the_count_census():
    c = FIX["tackleCensus"]["idpListed"]
    assert c["equalOnlyAfterRemovingPbpSpecialTeams"] == 440
    # the supplement's special-teams count is the host's on all but 2 player-weeks
    assert c["pbpSpecialTeamsEqualsHostSt"] >= c["playerWeeksWithSoloData"] - 2
    assert FIX["tackleCensus"]["otherListed"]["equalOnlyAfterRemovingPbpSpecialTeams"] == 162
    # and the stated residual: special-teams ASSISTS cannot be removed
    a = FIX["assistCensus"]
    assert a["other/stSnaps"]["nflverseExceedsHost"] == 161
    assert a["idp/stSnaps"]["nflverseExceedsHost"] == 411
    assert a["idp/noStSnaps"]["nflverseExceedsHost"] == 16
