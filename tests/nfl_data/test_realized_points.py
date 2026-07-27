"""Tests for realized fantasy points math.  These pin the scoring
rules we actually implement — they're the source of truth for
the 'value vs realized' feature in the upgraded player popup."""

from __future__ import annotations

from src.nfl_data import realized_points as rp


def _half_ppr():
    return {
        "pass_yd": 0.04,
        "pass_td": 4,
        "pass_int": -2,
        "rush_yd": 0.1,
        "rush_td": 6,
        "rec": 0.5,
        "rec_yd": 0.1,
        "rec_td": 6,
        "fum_lost": -2,
    }


def _ppr():
    return {**_half_ppr(), "rec": 1.0}


def _te_premium():
    return {**_ppr(), "bonus_rec_te": 0.5}


def test_no_stats_returns_none():
    out = rp.compute_weekly_points(None, _ppr())
    assert out is None


def test_no_scoring_settings_returns_zero_with_reason():
    out = rp.compute_weekly_points({"season": 2025, "week": 1}, None)
    assert out is not None
    assert out.fantasy_points == 0.0


def test_passing_qb_ppr_math():
    # 250 yards, 2 TDs, 1 INT → 250*0.04 + 2*4 + -2*1 = 10 + 8 - 2 = 16
    stat = {
        "season": 2025,
        "week": 1,
        "position": "QB",
        "passing_yards": 250,
        "passing_tds": 2,
        "interceptions": 1,
    }
    out = rp.compute_weekly_points(stat, _ppr())
    assert out is not None
    assert round(out.fantasy_points, 2) == 16.00


def test_rb_receiving_ppr_math():
    # 80 rush yds (8) + 1 rush TD (6) + 3 rec (3) + 30 rec yds (3) = 20
    stat = {
        "season": 2025,
        "week": 1,
        "position": "RB",
        "rushing_yards": 80,
        "rushing_tds": 1,
        "receptions": 3,
        "receiving_yards": 30,
    }
    out = rp.compute_weekly_points(stat, _ppr())
    assert round(out.fantasy_points, 2) == 20.00


def test_half_ppr_scales_rec_but_not_other():
    stat = {
        "season": 2025,
        "week": 1,
        "position": "RB",
        "receptions": 4,
        "receiving_yards": 40,
    }
    ppr_out = rp.compute_weekly_points(stat, _ppr())
    half_out = rp.compute_weekly_points(stat, _half_ppr())
    # PPR: 4*1.0 + 40*0.1 = 8.0
    # Half: 4*0.5 + 40*0.1 = 6.0
    assert round(ppr_out.fantasy_points, 2) == 8.0
    assert round(half_out.fantasy_points, 2) == 6.0


def test_te_premium_only_applies_to_tes():
    stat_te = {"season": 2025, "week": 1, "position": "TE", "receptions": 6}
    stat_wr = {"season": 2025, "week": 1, "position": "WR", "receptions": 6}
    te_out = rp.compute_weekly_points(stat_te, _te_premium(), position="TE")
    wr_out = rp.compute_weekly_points(stat_wr, _te_premium(), position="WR")
    # TE: 6*1.0 + 6*0.5 (te bonus) = 9
    # WR: 6*1.0 only = 6
    assert round(te_out.fantasy_points, 2) == 9.0
    assert round(wr_out.fantasy_points, 2) == 6.0


def test_threshold_bonus_applies_once():
    stat = {
        "season": 2025,
        "week": 1,
        "position": "QB",
        "passing_yards": 350,
        "passing_tds": 2,
    }
    scoring = {**_ppr(), "bonus_pass_yd_300": 3, "bonus_pass_yd_400": 5}
    out = rp.compute_weekly_points(stat, scoring)
    # base: 350*0.04 + 2*4 = 14 + 8 = 22. +3 for 300 bonus. 400 doesn't fire.
    assert round(out.fantasy_points, 2) == 25.0


def test_breakdown_structure():
    stat = {"season": 2025, "week": 1, "position": "RB", "rushing_yards": 100, "rushing_tds": 1}
    scoring = {"rush_yd": 0.1, "rush_td": 6, "bonus_rush_yd_100": 3}
    out = rp.compute_weekly_points(stat, scoring)
    assert out.fantasy_points == 10 + 6 + 3
    labels = [b[0] for b in out.breakdown]
    assert "Rush Yds" in labels
    assert "Rush TD" in labels
    assert "100+ Rush" in labels


def test_negative_scoring_counts_correctly():
    stat = {"season": 2025, "week": 1, "position": "QB", "interceptions": 3, "fumbles_lost": 2}
    out = rp.compute_weekly_points(stat, _ppr())
    # 3 INT * -2 + 2 FL * -2 = -10
    assert out.fantasy_points == -10.0


def test_cumulative_aggregates_across_weeks():
    rows = [
        {"season": 2025, "week": 1, "position": "WR", "receptions": 5, "receiving_yards": 50},
        {"season": 2025, "week": 2, "position": "WR", "receptions": 7, "receiving_yards": 100},
    ]
    out = rp.compute_cumulative_points(rows, _ppr())
    assert out["weekCount"] == 2
    # week1: 5 + 5 = 10; week2: 7 + 10 = 17; total 27
    assert round(out["totalPoints"], 2) == 27.0
    assert out["bestWeek"]["week"] == 2
    assert out["worstWeek"]["week"] == 1
    assert round(out["averagePoints"], 2) == 13.5


def test_cumulative_empty_returns_zeros():
    out = rp.compute_cumulative_points([], _ppr())
    assert out["weekCount"] == 0
    assert out["totalPoints"] == 0.0
    assert out["bestWeek"] is None


def test_value_vs_realized_delta():
    got = rp.value_vs_realized_delta(12.0, 60.0, 4)  # avg 15
    assert got["realized"] == 15.0
    assert got["expected"] == 12.0
    assert got["delta"] == 3.0
    assert got["deltaPct"] == 25.0


def test_value_vs_realized_handles_no_expected():
    got = rp.value_vs_realized_delta(None, 60.0, 4)
    assert got["expected"] is None
    assert got["delta"] is None


def test_rounding_stable_across_dict_serialization():
    """RealizedPoints.to_dict must not expose long floats from the
    simple multiplication — UI consumers expect 2 decimals."""
    stat = {"season": 2025, "week": 1, "position": "QB", "passing_yards": 333}
    out = rp.compute_weekly_points(stat, _ppr())
    d = out.to_dict()
    # Reproducible rounding, not something like 13.320000000000002.
    assert d["fantasyPoints"] == 13.32


# ── Sleeper scoring-key aliases + nflverse-direct column fallbacks ──
#
# The live dynasty_main league dump publishes passes-defended as
# ``idp_pass_def`` (not the canonical ``idp_pd`` this module was
# written against — src/scoring/sleeper_ingest.KEY_ALIASES documents
# the alias), and the nflverse-direct weekly file carries fumble
# recoveries in ``fumble_recovery_own`` with no ``def_`` prefix.
# Both used to score silently as 0.


def test_idp_pass_def_alias_scores_pd():
    stat = {"season": 2025, "week": 1, "position": "CB", "def_pass_defended": 3}
    out = rp.compute_weekly_points(stat, {"idp_pass_def": 5.32}, position="CB")
    assert out.fantasy_points == 3 * 5.32


def test_alias_never_double_counts_when_both_keys_present():
    stat = {"season": 2025, "week": 1, "position": "CB", "def_pass_defended": 3}
    out = rp.compute_weekly_points(
        stat, {"idp_pd": 1.5, "idp_pass_def": 5.32}, position="CB"
    )
    # canonical key wins; the alias must not add a second contribution
    assert out.fantasy_points == 3 * 1.5


def test_fumble_recovery_column_fallback_for_direct_rows():
    stat = {"season": 2025, "week": 1, "position": "LB", "fumble_recovery_own": 1}
    out = rp.compute_weekly_points(stat, {"idp_fum_rec": 3.19}, position="LB")
    assert out.fantasy_points == 3.19


def test_prefixed_fumble_recovery_column_still_wins():
    stat = {
        "season": 2025,
        "week": 1,
        "position": "LB",
        "def_fumble_recovery_own": 2,
        "fumble_recovery_own": 9,
    }
    out = rp.compute_weekly_points(stat, {"idp_fum_rec": 3.19}, position="LB")
    assert out.fantasy_points == 2 * 3.19
# ── IDP scoring ───────────────────────────────────────────────────────
#
# This path had no coverage at all before 2026-07-27, which is how it
# came to be scoring three columns that the current nflverse release
# does not have.  Every assertion below pins a NON-ZERO point total onto
# a column whose name changed or vanished — the only shape of assertion
# a silent-zero defect can fail.  "the call returned a RealizedPoints"
# passes against the bug.


def _idp_scoring():
    """A representative IDP scoring block, tackle-heavy the way real
    IDP leagues are."""
    return {
        "idp_tkl_solo": 1.0,
        "idp_tkl_ast": 0.5,
        "idp_tkl": 0.0,
        "idp_sack": 4.0,
        "idp_int": 6.0,
        "idp_pd": 1.5,
        "idp_ff": 4.0,
        "idp_fum_rec": 3.0,
        "idp_safe": 8.0,
        "idp_tkl_loss": 2.0,
    }


def _unified_idp_row():
    """2025 unified-release spellings, measured live 2026-07-27."""
    return {
        "player_id": "00-0032899",
        "position": "LB",
        "season": 2025,
        "week": 1,
        # gamebook: 5 + 2 = 7 solo, 1 assist, 8 combined
        "def_tackles_solo": 5,
        "def_tackles_with_assist": 2,
        "def_tackle_assists": 1,
        "def_sacks": 1.0,
        "def_interceptions": 1,
        "def_pass_defended": 2,
        "def_fumbles_forced": 1,
        "def_fumble_recovery_own": 1,
        "def_tackles_for_loss": 1,
        # RENAMED from def_safety.
        "def_safeties": 1,
    }


def _legacy_idp_row():
    """Retired pre-2025 spellings — a backfill must still score."""
    return {
        "player_id": "00-0022222",
        "position": "LB",
        "season": 2024,
        "week": 4,
        # def_tackles IS the gamebook solo total.
        "def_tackles": 7,
        "def_tackles_solo": 5,
        "def_tackles_with_assist": 2,
        "def_tackle_assists": 1,
        "def_safety": 1,
    }


def test_idp_tackles_use_the_gamebook_solo_total():
    """``def_tackles_solo`` alone under-reports: it excludes
    ``def_tackles_with_assist``.  Gamebook solo is 5 + 2 = 7.

    Reading the raw column would score 5.0 here, so the assertion
    distinguishes the two.
    """
    out = rp.compute_weekly_points(_unified_idp_row(), {"idp_tkl_solo": 1.0}, position="LB")
    assert out is not None
    assert out.fantasy_points == 7.0


def test_idp_combined_tackles_are_scored_at_all():
    """``idp_tkl`` read ``def_tackles``, which the unified release
    removed — the key silently scored zero.  Combined is solo (7) plus
    assists (1) = 8, and no nflverse column carries it."""
    out = rp.compute_weekly_points(_unified_idp_row(), {"idp_tkl": 1.0}, position="LB")
    assert out is not None
    assert out.fantasy_points == 8.0


def test_idp_safety_survives_the_def_safeties_rename():
    out = rp.compute_weekly_points(_unified_idp_row(), {"idp_safe": 8.0}, position="LB")
    assert out is not None
    assert out.fantasy_points == 8.0


def test_idp_tackle_thresholds_fire_on_combined_tackles():
    """The 5+/10+ bonuses read ``def_tackles`` too, so they stopped
    firing entirely.  Combined is 8 here: 5+ fires, 10+ does not."""
    out = rp.compute_weekly_points(
        _unified_idp_row(),
        {"idp_tkl_5p": 2.0, "idp_tkl_10p": 5.0},
        position="LB",
    )
    assert out is not None
    assert out.fantasy_points == 2.0


def test_idp_full_line_stacks_every_category():
    """Sleeper stacks: one play can credit sack + TFL + solo tackle.

    7 solo x 1.0 + 1 ast x 0.5 + 1 sack x 4 + 1 int x 6 + 2 pd x 1.5
    + 1 ff x 4 + 1 fr x 3 + 1 safety x 8 + 1 tfl x 2 = 37.5
    """
    out = rp.compute_weekly_points(_unified_idp_row(), _idp_scoring(), position="LB")
    assert out is not None
    assert out.fantasy_points == 37.5
    labels = {lab for (lab, _s, _p) in out.breakdown}
    assert {"Solo Tkl", "Ast Tkl", "Sack", "INT", "PD", "FF", "FR", "Safety", "TFL"} <= labels


def test_legacy_column_spellings_score_identically():
    """The same gamebook line expressed in pre-2025 columns."""
    out = rp.compute_weekly_points(
        _legacy_idp_row(),
        {"idp_tkl_solo": 1.0, "idp_tkl_ast": 0.5, "idp_tkl": 1.0, "idp_safe": 8.0},
        position="LB",
    )
    assert out is not None
    # 7 solo + 0.5 ast + 8 combined + 8 safety = 23.5
    assert out.fantasy_points == 23.5


def test_offensive_position_never_picks_up_idp_keys():
    """The gate that keeps a WR's zeroed def_ block out of the total.
    Every unified row carries def_* columns for every player."""
    row = {**_unified_idp_row(), "position": "WR"}
    out = rp.compute_weekly_points(row, _idp_scoring(), position="WR")
    assert out is not None
    assert out.fantasy_points == 0.0


def test_tackle_view_matches_the_actuals_store():
    """Two modules derive the same three numbers from the same columns.
    They must not drift apart — a durable log and the scorer disagreeing
    about how many tackles a player made is unresolvable after the fact.
    """
    from src.nfl_data import actuals_store

    row = _unified_idp_row()
    assert rp._tackle_view(row) == actuals_store._tackle_view(row)
    legacy = _legacy_idp_row()
    assert rp._tackle_view(legacy) == actuals_store._tackle_view(legacy)
