"""Exact-scoring tests: hand-scored stat lines under multiple configs.

Phase-1 gate: the same raw stat line must score correctly under
multiple league configs without changing model code.
"""

from __future__ import annotations

import unittest

from src.bdvm.projections import ProjectionRecord
from src.bdvm.scoring import score_stat_line_per_game, season_line_to_per_game

PPR = {
    "rec": 1.0,
    "rec_yd": 0.1,
    "rec_td": 6.0,
    "pass_yd": 0.04,
    "pass_td": 4.0,
    "pass_int": -2.0,
    "rush_yd": 0.1,
    "rush_td": 6.0,
    "fum_lost": -2.0,
}
HALF_PPR = {**PPR, "rec": 0.5}
STANDARD = {**PPR, "rec": 0.0}
TEP = {**PPR, "bonus_rec_te": 0.5}
SIX_PT_PASS = {**PPR, "pass_td": 6.0}
IDP = {
    "idp_tkl_solo": 1.5,
    "idp_tkl_ast": 0.75,
    "idp_sack": 4.0,
    "idp_tkl_loss": 1.0,
    "idp_hit": 0.5,
    "idp_pd": 1.5,
    "idp_int": 4.0,
}
IDP_TKL_BONUS = {**IDP, "idp_tkl_5p": 1.0, "idp_tkl_10p": 2.0}

WR_LINE = {"receptions": 5, "receiving_yards": 70, "receiving_tds": 0.5}
QB_LINE = {"passing_yards": 250, "passing_tds": 2, "interceptions": 1}
LB_LINE = {"def_tackles_solo": 6, "def_tackle_assists": 3, "def_sacks": 0.5}


class TestHandScoredExamples(unittest.TestCase):
    def test_ppr_half_standard(self):
        # 5 rec, 70 yds, 0.5 TD: PPR 5+7+3 = 15; half 12.5; standard 10
        self.assertAlmostEqual(score_stat_line_per_game(WR_LINE, PPR, position="WR"), 15.0)
        self.assertAlmostEqual(score_stat_line_per_game(WR_LINE, HALF_PPR, position="WR"), 12.5)
        self.assertAlmostEqual(score_stat_line_per_game(WR_LINE, STANDARD, position="WR"), 10.0)

    def test_te_premium_is_position_gated(self):
        # TE gets +0.5/rec; the identical WR line does not.
        self.assertAlmostEqual(score_stat_line_per_game(WR_LINE, TEP, position="TE"), 17.5)
        self.assertAlmostEqual(score_stat_line_per_game(WR_LINE, TEP, position="WR"), 15.0)

    def test_six_point_passing_td(self):
        # 250*0.04 + 2*4 - 2 = 16 ; six-point: 10 + 12 - 2 = 20
        self.assertAlmostEqual(score_stat_line_per_game(QB_LINE, PPR, position="QB"), 16.0)
        self.assertAlmostEqual(score_stat_line_per_game(QB_LINE, SIX_PT_PASS, position="QB"), 20.0)

    def test_idp_scoring_and_position_gate(self):
        # 6*1.5 + 3*0.75 + 0.5*4 = 13.25 for an LB; 0 for a WR (keys gated)
        self.assertAlmostEqual(score_stat_line_per_game(LB_LINE, IDP, position="LB"), 13.25)
        self.assertAlmostEqual(score_stat_line_per_game(LB_LINE, IDP, position="WR"), 0.0)

    def test_idp_true_positions_score(self):
        for pos in ("DT", "EDGE", "CB", "S", "DL", "DB"):
            self.assertAlmostEqual(
                score_stat_line_per_game(LB_LINE, IDP, position=pos),
                13.25,
                msg=f"IDP keys must fire for {pos}",
            )

    def test_idp_tackle_volume_thresholds(self):
        line = {"def_tackles": 11}
        # 5+ and 10+ both fire: 1 + 2 = 3
        self.assertAlmostEqual(score_stat_line_per_game(line, IDP_TKL_BONUS, position="LB"), 3.0)
        line5 = {"def_tackles": 6}
        self.assertAlmostEqual(score_stat_line_per_game(line5, IDP_TKL_BONUS, position="LB"), 1.0)

    def test_season_line_to_per_game(self):
        per_game = season_line_to_per_game({"receiving_yards": 170, "receptions": 17}, 17.0)
        self.assertAlmostEqual(per_game["receiving_yards"], 10.0)
        self.assertAlmostEqual(per_game["receptions"], 1.0)
        with self.assertRaises(ValueError):
            season_line_to_per_game({"receptions": 17}, 0.0)

    def test_stat_line_and_direct_points_consistency(self):
        """A stat-line record and an equivalent direct-FPG record resolve
        to the same per-game points (raw-stat / direct-point parity)."""
        stat_rec = ProjectionRecord(
            source="a",
            player_key="x",
            position="WR",
            season=2026,
            as_of="2026-07-01",
            games=17.0,
            stat_line={"receptions": 85, "receiving_yards": 1190, "receiving_tds": 8.5},
            stat_basis="season",
        )
        fpg_from_stats, native = stat_rec.resolve_fpg(PPR)
        direct_rec = ProjectionRecord(
            source="b",
            player_key="x",
            position="WR",
            season=2026,
            as_of="2026-07-01",
            games=17.0,
            fpg=fpg_from_stats,
            scoring_native=True,
        )
        fpg_direct, _ = direct_rec.resolve_fpg(PPR)
        self.assertTrue(native)
        self.assertAlmostEqual(fpg_from_stats, fpg_direct)
        # 85 rec, 1190 yd, 8.5 TD over 17 games = 5 + 7 + 3 = 15/game
        self.assertAlmostEqual(fpg_from_stats, 15.0)

    def test_fpts_fallback(self):
        rec = ProjectionRecord(
            source="c",
            player_key="y",
            position="RB",
            season=2026,
            as_of="2026-07-01",
            games=16.0,
            fpts=240.0,
        )
        fpg, native = rec.resolve_fpg(PPR)
        self.assertAlmostEqual(fpg, 15.0)
        self.assertFalse(native)  # not scored under league rules — flagged


if __name__ == "__main__":
    unittest.main()
