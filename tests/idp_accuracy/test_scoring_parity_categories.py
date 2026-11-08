"""Hand-computable scoring-category tests for BOTH scorers (scoring-parity taxonomy).

Owner master directive 2026-11-08 section 7 Priority 2.  Record:
``docs/league-intelligence/SCORING_PARITY_TAXONOMY_2026-11-08.md``.

Every expected value below is a LITERAL computed by hand from the pinned
``dynasty_main`` card (fingerprint ``sf1:9e51824690d091f9``) - never derived from the
card inside the test - so a wrong rate, a dropped rule or a double-paid rule is caught
by arithmetic the production code did not write.

Two scorers, each tested where it claims the category:

* host-native  ``compute_weekly_points(..., source="sleeper")`` over Sleeper's own keys;
* nflverse     ``compute_weekly_points(...)`` over ``stats_player_week`` columns, with the
               play-by-play supplement (``pbp_derived``) for the keys the weekly feed lacks.

Where the nflverse path lacks the evidence it must REPORT it (``unscored``) rather than
score a quiet 0; the two findings that still silently score 0 are strict ``xfail`` and
name the taxonomy.  The four defects PR #1938 repairs are already pinned in
``test_scoring_events.py`` and are deliberately not repeated here, and no case below
touches the behaviour #1938 changes, so this file passes before and after it.

No network, no live board.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.league_comparison.sleeper_scoring import scoring_fingerprint
from src.nfl_data.realized_points import (
    PBP_SUPPLEMENT_KEYS,
    PBP_SUPPLEMENT_ROW_KEY,
    compute_weekly_points,
)

REPO = Path(__file__).resolve().parents[2]
MANIFEST = json.loads(
    (REPO / "docs/valuation/idp_accuracy/MANIFEST.json").read_text(encoding="utf-8")
)
CARD: dict[str, float] = MANIFEST["scoringCard"]["nonZeroRules"]
ABS = 1e-6

#: nonzero card keys that are TEAM-defense / team-special-teams rules, never paid to an
#: individual player entry (the host refuses a team entry; players carry no such keys).
TEAM_ONLY_KEYS = frozenset(
    {
        "blk_kick", "def_2pt", "def_3_and_out", "def_4_and_stop", "def_forced_punts",
        "def_kr_yd", "def_pr_yd", "def_st_ff", "def_st_fum_rec", "def_st_td", "def_td",
        "fg_ret_yd", "fum_rec", "fum_rec_td", "fum_ret_yd", "int", "int_ret_yd",
        "pts_allow", "pts_allow_0", "pts_allow_1_6", "pts_allow_7_13", "pts_allow_14_20",
        "pts_allow_21_27", "pts_allow_28_34", "pts_allow_35p", "sack_yd", "safe",
        "yds_allow",
    }
)  # fmt: skip

# (case id, card key it proves, Sleeper-keyed line, expected points)
HOST_CASES = [
    ("pass_yd", "pass_yd", {"pass_yd": 250}, 10.0),
    ("pass_td", "pass_td", {"pass_td": 2}, 12.0),
    ("pass_cmp", "pass_cmp", {"pass_cmp": 20}, 7.4),
    ("pass_inc", "pass_inc", {"pass_inc": 10}, -6.7),
    ("pass_int", "pass_int", {"pass_int": 2}, -8.0),
    ("pass_sack", "pass_sack", {"pass_sack": 3}, -3.0),
    ("pass_2pt", "pass_2pt", {"pass_2pt": 1}, 2.0),
    ("pass_int_td", "pass_int_td", {"pass_int_td": 1}, -2.0),
    ("bonus_fd_qb", "bonus_fd_qb", {"bonus_fd_qb": 5}, 2.0),
    ("rush_att", "rush_att", {"rush_att": 10}, 0.1),
    ("rush_yd", "rush_yd", {"rush_yd": 80}, 8.0),
    ("rush_td", "rush_td", {"rush_td": 1}, 6.0),
    ("rush_2pt", "rush_2pt", {"rush_2pt": 1}, 2.0),
    ("bonus_fd_rb", "bonus_fd_rb", {"bonus_fd_rb": 4}, 4.0),
    ("rec", "rec", {"rec": 5}, 0.5),
    ("rec_yd", "rec_yd", {"rec_yd": 60}, 6.0),
    ("rec_td", "rec_td", {"rec_td": 1}, 6.0),
    ("rec_2pt", "rec_2pt", {"rec_2pt": 1}, 2.0),
    ("bonus_rec_wr", "bonus_rec_wr", {"bonus_rec_wr": 5}, 0.1),
    ("bonus_fd_wr", "bonus_fd_wr", {"bonus_fd_wr": 3}, 3.0),
    ("bonus_fd_te", "bonus_fd_te", {"bonus_fd_te": 3}, 3.0),
    ("rec_0_4", "rec_0_4", {"rec_0_4": 3}, 0.75),
    ("rec_5_9", "rec_5_9", {"rec_5_9": 2}, 1.0),
    ("rec_10_19", "rec_10_19", {"rec_10_19": 2}, 1.5),
    ("rec_20_29", "rec_20_29", {"rec_20_29": 1}, 1.0),
    ("rec_30_39", "rec_30_39", {"rec_30_39": 1}, 1.25),
    ("rec_40p", "rec_40p", {"rec_40p": 1}, 2.0),
    ("fum_lost", "fum_lost", {"fum_lost": 1}, -4.0),
    ("kr_yd", "kr_yd", {"kr_yd": 60}, 2.0),
    ("pr_yd", "pr_yd", {"pr_yd": 30}, 1.0),
    ("st_td", "st_td", {"st_td": 1}, 6.0),
    ("st_tkl_solo", "st_tkl_solo", {"st_tkl_solo": 2}, 2.66),
    ("st_ff", "st_ff", {"st_ff": 1}, 4.25),
    ("st_fum_rec", "st_fum_rec", {"st_fum_rec": 1}, 3.19),
    ("xpm", "xpm", {"xpm": 3}, 6.93),
    ("xpmiss", "xpmiss", {"xpmiss": 1}, -3.15),
    ("fgm_yds", "fgm_yds", {"fgm_yds": 47}, 3.29),
    ("fgmiss_0_19", "fgmiss_0_19", {"fgmiss_0_19": 1}, -4.55),
    ("fgmiss_20_29", "fgmiss_20_29", {"fgmiss_20_29": 1}, -3.85),
    ("fgmiss_30_39", "fgmiss_30_39", {"fgmiss_30_39": 1}, -3.15),
    ("fgmiss_40_49", "fgmiss_40_49", {"fgmiss_40_49": 1}, -2.45),
    ("fgmiss_50_59", "fgmiss_50_59", {"fgmiss_50_59": 1}, -1.75),
    ("fgmiss_60p", "fgmiss_60p", {"fgmiss_60p": 1}, -1.05),
    ("idp_tkl_solo", "idp_tkl_solo", {"idp_tkl_solo": 3}, 3.99),
    ("idp_tkl_ast", "idp_tkl_ast", {"idp_tkl_ast": 2}, 1.6),
    ("idp_tkl_loss", "idp_tkl_loss", {"idp_tkl_loss": 2}, 8.48),
    ("idp_sack", "idp_sack", {"idp_sack": 1}, 2.92),
    ("idp_sack_yd", "idp_sack_yd", {"idp_sack_yd": 9}, 1.0),
    ("idp_qb_hit", "idp_qb_hit", {"idp_qb_hit": 2}, 4.24),
    ("idp_hit_alias", "idp_qb_hit", {"idp_hit": 2}, 4.24),
    ("idp_pass_def", "idp_pass_def", {"idp_pass_def": 1}, 5.3),
    ("idp_pd_alias", "idp_pass_def", {"idp_pd": 1}, 5.3),
    ("idp_int", "idp_int", {"idp_int": 1}, 5.3),
    ("idp_int_ret_yd", "idp_int_ret_yd", {"idp_int_ret_yd": 18}, 2.0),
    ("idp_ff", "idp_ff", {"idp_ff": 1}, 4.24),
    ("idp_fum_rec", "idp_fum_rec", {"idp_fum_rec": 1}, 3.19),
    ("idp_fum_ret_yd", "idp_fum_ret_yd", {"idp_fum_ret_yd": 9}, 1.0),
    ("idp_def_td", "idp_def_td", {"idp_def_td": 1}, 6.36),
    ("idp_safe", "idp_safe", {"idp_safe": 1}, 5.3),
    ("idp_blk_kick", "idp_blk_kick", {"idp_blk_kick": 1}, 5.3),
]

# (case id, card key it proves, position, nflverse row columns, pbp supplement | None, expected)
NFLV_CASES = [
    ("pass_yd", "pass_yd", "QB", {"passing_yards": 250}, None, 10.0),
    ("pass_td", "pass_td", "QB", {"passing_tds": 2}, None, 12.0),
    ("pass_cmp", "pass_cmp", "QB", {"completions": 20}, None, 7.4),
    # 30 attempts, 20 completions: 20 x 0.37 + (30 - 20) x -0.67
    ("pass_inc", "pass_inc", "QB", {"attempts": 30, "completions": 20}, None, 0.7),
    ("pass_int", "pass_int", "QB", {"passing_interceptions": 2}, None, -8.0),
    ("pass_sack", "pass_sack", "QB", {"sacks_suffered": 3}, None, -3.0),
    ("pass_2pt", "pass_2pt", "QB", {"passing_2pt_conversions": 1}, None, 2.0),
    ("pass_int_td", "pass_int_td", "QB", {}, {"pass_int_td": 1}, -2.0),
    # 6 first downs, 1 of them the TD itself: 1 x 6 (TD) + (6 - 1) x 0.4
    ("bonus_fd_qb", "bonus_fd_qb", "QB", {"passing_first_downs": 6, "passing_tds": 1}, None, 8.0),
    ("rush_att", "rush_att", "RB", {"carries": 10}, None, 0.1),
    ("rush_yd", "rush_yd", "RB", {"rushing_yards": 80}, None, 8.0),
    ("rush_td", "rush_td", "RB", {"rushing_tds": 1}, None, 6.0),
    ("rush_2pt", "rush_2pt", "RB", {"rushing_2pt_conversions": 1}, None, 2.0),
    ("bonus_fd_rb", "bonus_fd_rb", "RB", {"rushing_first_downs": 4}, None, 4.0),
    ("rec_te", "rec", "TE", {"receptions": 5}, None, 0.5),  # no TE reception premium
    ("rec_wr_bonus", "bonus_rec_wr", "WR", {"receptions": 5}, None, 0.6),  # 0.50 + 5 x 0.02
    ("rec_yd", "rec_yd", "WR", {"receiving_yards": 60}, None, 6.0),
    ("rec_td", "rec_td", "WR", {"receiving_tds": 1}, None, 6.0),
    ("rec_2pt", "rec_2pt", "WR", {"receiving_2pt_conversions": 1}, None, 2.0),
    ("bonus_fd_wr", "bonus_fd_wr", "WR", {"receiving_first_downs": 3}, None, 3.0),
    ("bonus_fd_te", "bonus_fd_te", "TE", {"receiving_first_downs": 3}, None, 3.0),
    ("rec_0_4", "rec_0_4", "WR", {}, {"rec_0_4": 3}, 0.75),
    ("rec_5_9", "rec_5_9", "WR", {}, {"rec_5_9": 2}, 1.0),
    ("rec_10_19", "rec_10_19", "WR", {}, {"rec_10_19": 2}, 1.5),
    ("rec_20_29", "rec_20_29", "WR", {}, {"rec_20_29": 1}, 1.0),
    ("rec_30_39", "rec_30_39", "WR", {}, {"rec_30_39": 1}, 1.25),
    ("rec_40p", "rec_40p", "WR", {}, {"rec_40p": 1}, 2.0),
    ("fum_lost", "fum_lost", "RB", {"fumbles_lost": 1}, None, -4.0),
    ("kr_yd", "kr_yd", "WR", {"kickoff_return_yards": 60}, None, 2.0),
    ("pr_yd", "pr_yd", "WR", {"punt_return_yards": 30}, None, 1.0),
    ("st_td", "st_td", "WR", {"special_teams_tds": 1}, None, 6.0),
    ("st_tkl_solo", "st_tkl_solo", "RB", {}, {"st_tkl_solo": 2}, 2.66),
    ("st_ff", "st_ff", "RB", {}, {"st_ff": 1}, 4.25),
    ("st_fum_rec", "st_fum_rec", "RB", {}, {"st_fum_rec": 1}, 3.19),
    ("xpm", "xpm", "K", {"pat_made": 3}, None, 6.93),
    ("xpmiss", "xpmiss", "K", {"pat_missed": 1}, None, -3.15),
    ("fgm_yds", "fgm_yds", "K", {"fg_made_distance": 47}, None, 3.29),
    ("fgmiss_0_19", "fgmiss_0_19", "K", {"fg_missed_0_19": 1}, None, -4.55),
    ("fgmiss_20_29", "fgmiss_20_29", "K", {"fg_missed_20_29": 1}, None, -3.85),
    ("fgmiss_30_39", "fgmiss_30_39", "K", {"fg_missed_30_39": 1}, None, -3.15),
    ("fgmiss_40_49", "fgmiss_40_49", "K", {"fg_missed_40_49": 1}, None, -2.45),
    ("fgmiss_50_59", "fgmiss_50_59", "K", {"fg_missed_50_59": 1}, None, -1.75),
    ("fgmiss_60p", "fgmiss_60p", "K", {"fg_missed_60_": 1}, None, -1.05),
    # this schema's solo = def_tackles_solo + def_tackles_with_assist
    ("idp_tkl_solo", "idp_tkl_solo", "LB", {"def_tackles_solo": 3}, None, 3.99),
    ("idp_tkl_ast", "idp_tkl_ast", "LB", {"def_tackle_assists": 2}, None, 1.6),
    ("idp_tkl_loss", "idp_tkl_loss", "DL", {"def_tackles_for_loss": 2}, None, 8.48),
    ("idp_sack", "idp_sack", "DL", {"def_sacks": 1}, None, 2.92),
    ("idp_sack_yd", "idp_sack_yd", "DL", {"def_sack_yards": 9}, None, 1.0),
    ("idp_qb_hit", "idp_qb_hit", "DL", {"def_qb_hits": 2}, None, 4.24),
    ("idp_pass_def", "idp_pass_def", "DB", {"def_pass_defended": 1}, None, 5.3),
    ("idp_int", "idp_int", "DB", {"def_interceptions": 1}, None, 5.3),
    ("idp_int_ret_yd", "idp_int_ret_yd", "DB", {"def_interception_yards": 18}, None, 2.0),
    ("idp_ff", "idp_ff", "LB", {"def_fumbles_forced": 1}, None, 4.24),
    ("idp_fum_rec", "idp_fum_rec", "LB", {"def_fumble_recovery_opp": 1}, None, 3.19),
    ("idp_fum_ret_yd", "idp_fum_ret_yd", "LB", {"def_fumble_recovery_yards_opp": 9}, None, 1.0),
    ("idp_def_td", "idp_def_td", "DB", {"def_tds": 1}, None, 6.36),
    ("idp_safe", "idp_safe", "DL", {"def_safeties": 1}, None, 5.3),
    ("idp_blk_kick", "idp_blk_kick", "DL", {"def_fg_blocks": 1}, None, 5.3),
]


def _host(line: dict, sid: str = "9999") -> float:
    res = compute_weekly_points(
        {**line, "player_id": sid, "season": 2026, "week": 1}, CARD, source="sleeper"
    )
    assert res is not None
    return res.fantasy_points


def _nflv(cols: dict, pos: str, supplement: dict | None) -> float:
    row = {**cols, "season": 2026, "week": 1, "position": pos}
    if supplement is not None:
        row[PBP_SUPPLEMENT_ROW_KEY] = supplement
    res = compute_weekly_points(row, CARD, position=pos)
    assert res is not None
    return res.fantasy_points


def test_the_card_is_the_pinned_dynasty_main_card():
    assert scoring_fingerprint(CARD) == "sf1:9e51824690d091f9"


def test_every_nonzero_card_key_has_a_case_or_is_team_only():
    """A key added to the card without a hand-computed case here fails loudly."""
    host_keys = {k for _i, k, _l, _p in HOST_CASES}
    nflv_keys = {c[1] for c in NFLV_CASES}
    assert set(CARD) - TEAM_ONLY_KEYS == host_keys
    assert host_keys == nflv_keys
    assert not (TEAM_ONLY_KEYS - set(CARD)), "stale TEAM_ONLY_KEYS entry"


@pytest.mark.parametrize("case,key,line,expected", HOST_CASES, ids=[c[0] for c in HOST_CASES])
def test_host_native_scorer_category(case, key, line, expected):
    assert _host(line) == pytest.approx(expected, abs=ABS)


@pytest.mark.parametrize(
    "case,key,pos,cols,supplement,expected", NFLV_CASES, ids=[c[0] for c in NFLV_CASES]
)
def test_nflverse_scorer_category(case, key, pos, cols, supplement, expected):
    assert _nflv(cols, pos, supplement) == pytest.approx(expected, abs=ABS)


def test_a_host_wr_line_with_a_reception_pays_rate_bonus_and_band_exactly_once():
    # 5 rec x 0.10 + bonus_rec_wr 5 x 0.02 + 5 x rec_5_9 0.50 = 0.5 + 0.1 + 2.5
    line = {"rec": 5, "bonus_rec_wr": 5, "rec_5_9": 5}
    assert _host(line) == pytest.approx(3.1, abs=ABS)


def test_both_scorers_agree_on_a_mixed_offense_line():
    # QB: 300 yd (12.0) + 3 TD (18.0) + 1 INT (-4.0) + 25 cmp (9.25) + 15 inc (-10.05)
    host = {"pass_yd": 300, "pass_td": 3, "pass_int": 1, "pass_cmp": 25, "pass_inc": 15}
    cols = {
        "passing_yards": 300, "passing_tds": 3, "passing_interceptions": 1,
        "completions": 25, "attempts": 40,
    }  # fmt: skip
    want = 12.0 + 18.0 - 4.0 + 9.25 - 10.05
    assert _host(host) == pytest.approx(want, abs=ABS)
    assert _nflv(cols, "QB", None) == pytest.approx(want, abs=ABS)


def test_team_defense_entry_is_refused_by_the_host_scorer_not_scored_zero():
    team = {"player_id": "PHI", "season": 2026, "week": 1, "int": 2}
    assert compute_weekly_points(team, CARD, source="sleeper") is None


# -- fails closed: missing evidence is REPORTED, never a quiet zero ---------------

_NONZERO_PBP_KEYS = frozenset(k for k in PBP_SUPPLEMENT_KEYS if CARD.get(k))


def test_nflverse_without_the_pbp_supplement_reports_every_rule_it_cannot_score():
    res = compute_weekly_points(
        {"season": 2026, "week": 1, "receptions": 5, "position": "WR"}, CARD, position="WR"
    )
    assert res is not None
    assert {k for k, _rate in res.unscored} == _NONZERO_PBP_KEYS
    assert _NONZERO_PBP_KEYS == {
        "pass_int_td", "rec_0_4", "rec_5_9", "rec_10_19", "rec_20_29", "rec_30_39",
        "rec_40p", "st_ff", "st_fum_rec", "st_tkl_solo",
    }  # fmt: skip
    # the partial total is only the rules the weekly feed CAN score: 5 x (0.10 + 0.02)
    assert res.fantasy_points == pytest.approx(0.6, abs=ABS)


def test_nflverse_with_the_supplement_attached_reports_nothing_unscored():
    row = {"season": 2026, "week": 1, "position": "WR", PBP_SUPPLEMENT_ROW_KEY: {}}
    res = compute_weekly_points(row, CARD, position="WR")
    assert res is not None and res.unscored == ()


def test_host_native_path_refuses_a_pbp_supplement_rather_than_double_counting():
    row = {"player_id": "9999", "season": 2026, "week": 1, PBP_SUPPLEMENT_ROW_KEY: {"rec_0_4": 1}}
    with pytest.raises(ValueError):
        compute_weekly_points(row, CARD, source="sleeper")


def test_an_unknown_stat_source_is_refused():
    with pytest.raises(ValueError):
        compute_weekly_points({"season": 2026, "week": 1}, CARD, source="espn")


# -- strict xfail findings (do NOT fix served behaviour; see the taxonomy doc) ----


@pytest.mark.xfail(
    strict=True,
    reason="SCORING-PARITY-TAXONOMY F1: nflverse def_tackle_assists includes special-teams "
    "assists the host pays nothing for, and the pbp supplement has no st_tkl_ast key "
    "(16-23 player-weeks, 2026 wk1-6; "
    "docs/league-intelligence/SCORING_PARITY_TAXONOMY_2026-11-08.md). Closing it needs an "
    "st_tkl_ast supplement key (schema bump + artifact rebuild): owner-reserved with #1938.",
)
def test_special_teams_assists_are_not_paid_as_defensive_assists():
    # two weekly-feed assists, one of which pbp says was a special-teams assist
    got = _nflv({"def_tackle_assists": 2}, "LB", {"st_tkl_ast": 1})
    assert got == pytest.approx(0.8, abs=ABS)  # only the one defensive assist: 1 x 0.80


@pytest.mark.xfail(
    strict=True,
    reason="SCORING-PARITY-TAXONOMY F2: a row with no position silently drops every def_* "
    "stat to 0 with nothing in `unscored` (MISSING IS NEVER ZERO). The 6 position-less rows of "
    "6,488 (2026 wk1-6) are nameless and skipped upstream, so measured impact is nil: latent.",
)
def test_a_row_with_no_position_does_not_silently_score_defensive_stats_as_zero():
    row = {"season": 2026, "week": 1, "def_tackles_solo": 3, PBP_SUPPLEMENT_ROW_KEY: {}}
    res = compute_weekly_points(row, CARD)  # supplement attached: nothing else is "unscored"
    assert res is None or bool(res.unscored) or res.fantasy_points == pytest.approx(3.99, abs=ABS)
