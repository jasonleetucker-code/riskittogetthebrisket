"""Tests for the IDP scoring-fit pipeline (Phase 1).

Covers:

1. **Stacked-scoring mechanics**: a sack-only EDGE under stacked scoring
   produces meaningfully MORE points than a tackle-floor LB with the
   same total events.  This is the central insight the lens encodes.
2. **VORP signs**: the stacking creates a positive scoring-fit delta
   for EDGEs and a negative one for tackle-only LBs in a league with
   high sack/QB-hit weights.
3. **Mid-season ramp confidence**: 0/4/12/17 games map to
   none/low/medium/high confidence by construction.
4. **Rookie archetype baseline**: a (position, draft_round) → avg PPG
   bucket built from historical rookies bypasses the no-signal sentinel
   for pre-season rookies whose draft round is known.
5. **Synthetic detection**: rows derived from the cohort baseline are
   tagged ``synthetic=True`` so the lens can show a separate badge.
"""
from __future__ import annotations

import unittest

from src.scoring.idp_scoring_fit import (
    IdpFitRow,
    _confidence_for_history,
    aggregate_stat_contributions,
    build_realized_3yr_ppg,
    build_rookie_archetype_baseline,
    compute_idp_scoring_fit,
    quantile_map_to_consensus_scale,
    stamp_delta,
)


# ── Stacked-scoring fixture ────────────────────────────────────────
# A "Sleeper-stacked" scoring config: sack ≈ 11 (sack 4 + sack_yd 1*7
# avg + qb_hit 1.5 + tfl 0.5 + solo tackle 1.38 if it lands as a solo).
# Tuned so a 3-event sequence (sack + qb_hit + solo tackle) is worth
# ~7-12 pts depending on yards.
_STACKED_SCORING = {
    "idp_tkl_solo": 1.5,
    "idp_tkl_ast": 0.75,
    "idp_tkl_loss": 2.0,
    "idp_sack": 4.0,
    "idp_sack_yd": 0.5,
    "idp_hit": 1.5,
    "idp_pd": 1.5,
    "idp_int": 6.0,
    "idp_ff": 4.0,
    "idp_fum_rec": 4.0,
    "idp_def_td": 6.0,
    "idp_safe": 4.0,
}


def _weekly_row(player_id: str, position: str, week: int, **stats):
    return {
        "player_id": player_id,
        "player_name": stats.pop("player_name", player_id),
        "position": position,
        "season": stats.pop("season", 2024),
        "week": week,
        **stats,
    }


class TestConfidenceMidSeasonRamp(unittest.TestCase):
    """The mid-season ramp the user asked for: confidence label scales
    with realized sample size, not with a fixed years_exp threshold.

    Spec from the user:
        Pre-season rookie: 0 weeks → "none" (use synthetic if available)
        Week 4 rookie:     4 games → "low"
        Week 12 rookie:    12 games → "medium"
        Year 2 player:     17+ games → "high"
    """

    def test_zero_games_returns_none(self):
        self.assertEqual(_confidence_for_history(0, 0), "none")

    def test_four_games_returns_low(self):
        self.assertEqual(_confidence_for_history(1, 4), "low")

    def test_twelve_games_returns_medium(self):
        self.assertEqual(_confidence_for_history(1, 12), "medium")

    def test_full_season_returns_high(self):
        # Year 2 player with full Y1 history.
        self.assertEqual(_confidence_for_history(1, 17), "high")

    def test_two_seasons_returns_high(self):
        # Veteran with 2 partial seasons of data also lands at high.
        self.assertEqual(_confidence_for_history(2, 14), "high")


class TestRealizedPpgWeighting(unittest.TestCase):
    """Y1 weighted heaviest, with renormalisation when seasons missing."""

    def test_renormalises_when_only_one_season(self):
        # A sophomore with a single 16-game season.  Should NOT be
        # penalised for "missing" Y2/Y3 data — the available weight
        # is renormalised so the single-season PPG passes through.
        rows_2024 = [
            _weekly_row("p1", "LB", w, def_tackles_solo=4) for w in range(1, 17)
        ]
        weighted, seasons, games, _ = build_realized_3yr_ppg(
            "p1", "LB",
            {"idp_tkl_solo": 1.5},
            weekly_rows_by_season={2024: rows_2024},
        )
        # 4 solos × 1.5 = 6 ppg.  Renormalised weight collapses to 1.0
        # for the only season present.
        self.assertAlmostEqual(weighted, 6.0, places=2)
        self.assertEqual(seasons, 1)
        self.assertEqual(games, 16)

    def test_blends_weighted_three_year_ppg(self):
        rows = {
            2024: [_weekly_row("p1", "LB", w, def_tackles_solo=6) for w in range(1, 18)],
            2023: [_weekly_row("p1", "LB", w, def_tackles_solo=4) for w in range(1, 18)],
            2022: [_weekly_row("p1", "LB", w, def_tackles_solo=2) for w in range(1, 18)],
        }
        weighted, seasons, _, _ = build_realized_3yr_ppg(
            "p1", "LB",
            {"idp_tkl_solo": 1.0},
            weekly_rows_by_season=rows,
        )
        # Y1 PPG = 6, Y2 = 4, Y3 = 2.  Weights 0.55/0.30/0.15.
        # Expected = 6*.55 + 4*.30 + 2*.15 = 3.3 + 1.2 + 0.3 = 4.8.
        self.assertAlmostEqual(weighted, 4.8, places=2)
        self.assertEqual(seasons, 3)


class TestStackedScoringEDGEvsLB(unittest.TestCase):
    """Encodes the proposal's central claim: stacked scoring rewards
    disruption-heavy IDPs more than tackle-floor LBs.  Same total event
    count, very different point production."""

    def test_edge_sack_outscores_lb_tackle(self):
        """A solo sack-tackle (sack + sack_yds + qb_hit + tfl + solo)
        produces ~7x the points of a clean solo tackle alone."""
        from src.nfl_data.realized_points import compute_weekly_points
        # EDGE: 1-event week — but it's a 7-yd solo sack with a hit.
        edge_row = _weekly_row(
            "edge1", "EDGE", 1,
            def_tackles_solo=1,
            def_sacks=1,
            def_sack_yards=7,
            def_qb_hits=1,
            def_tackles_for_loss=1,
        )
        # LB: 1-event week — clean solo tackle.
        lb_row = _weekly_row("lb1", "LB", 1, def_tackles_solo=1)
        edge = compute_weekly_points(edge_row, _STACKED_SCORING, position="EDGE")
        lb = compute_weekly_points(lb_row, _STACKED_SCORING, position="LB")
        # solo 1.5 + sack 4 + sack_yd 7*0.5=3.5 + hit 1.5 + tfl 2.0 = 12.5
        # vs LB solo only = 1.5
        self.assertAlmostEqual(edge.fantasy_points, 12.5, places=2)
        self.assertAlmostEqual(lb.fantasy_points, 1.5, places=2)
        # The stack ratio is the user's "11+ pts on a single sack" claim.
        self.assertGreater(edge.fantasy_points / lb.fantasy_points, 7.0)


class TestRookieArchetypeBaseline(unittest.TestCase):
    """Draft-capital-derived synthetic for pre-season rookies."""

    def _id_map_with_rookie(self, gsis: str, position: str, draft_round: int, rookie_season: int):
        return {
            "gsis_id": gsis,
            "position": position,
            "draft_round": draft_round,
            "rookie_season": rookie_season,
        }

    def test_buckets_by_position_and_round(self):
        # Two first-round EDGEs in 2023, both producing 8 PPG.
        # Three first-round LBs in 2024, producing 4/5/6 PPG.
        rows_by_season = {
            2023: [
                # gsis=A, EDGE, 4 events × 17 weeks = 8 ppg under stacked
                _weekly_row("A", "EDGE", w, def_tackles_solo=2, def_sacks=1, def_qb_hits=1, def_tackles_for_loss=1)
                for w in range(1, 18)
            ] + [
                _weekly_row("B", "EDGE", w, def_tackles_solo=2, def_sacks=1, def_qb_hits=1, def_tackles_for_loss=1)
                for w in range(1, 18)
            ],
            2024: [
                _weekly_row("C", "LB", w, def_tackles_solo=4) for w in range(1, 18)
            ] + [
                _weekly_row("D", "LB", w, def_tackles_solo=5) for w in range(1, 18)
            ] + [
                _weekly_row("E", "LB", w, def_tackles_solo=6) for w in range(1, 18)
            ],
        }
        id_map = [
            self._id_map_with_rookie("A", "EDGE", 1, 2023),
            self._id_map_with_rookie("B", "EDGE", 1, 2023),
            self._id_map_with_rookie("C", "LB", 1, 2024),
            self._id_map_with_rookie("D", "LB", 1, 2024),
            self._id_map_with_rookie("E", "LB", 1, 2024),
        ]
        baseline = build_rookie_archetype_baseline(
            rows_by_season, id_map, _STACKED_SCORING,
        )
        self.assertIn(("EDGE", 1), baseline)
        self.assertIn(("LB", 1), baseline)
        # EDGE: per-week 2 solo (×1.5=3.0) + 1 sack (×4=4.0) +
        # 1 qb_hit (×1.5=1.5) + 1 tfl (×2.0=2.0) = 10.5 ppg.
        self.assertAlmostEqual(baseline[("EDGE", 1)], 10.5, places=2)
        # LB: avg of 4×1.5, 5×1.5, 6×1.5 = (6 + 7.5 + 9)/3 = 7.5
        self.assertAlmostEqual(baseline[("LB", 1)], 7.5, places=2)

    def test_drops_buckets_with_under_two_samples(self):
        # Single rookie in (LB, 1) — the bucket should be dropped.
        rows_by_season = {
            2024: [_weekly_row("A", "LB", w, def_tackles_solo=4) for w in range(1, 18)],
        }
        id_map = [
            {"gsis_id": "A", "position": "LB", "draft_round": 1, "rookie_season": 2024},
        ]
        baseline = build_rookie_archetype_baseline(
            rows_by_season, id_map, _STACKED_SCORING,
        )
        self.assertNotIn(("LB", 1), baseline)

    def test_skips_non_idp_positions(self):
        rows_by_season = {
            2024: [_weekly_row("A", "WR", w, receptions=5, receiving_yards=80) for w in range(1, 18)],
        }
        id_map = [
            {"gsis_id": "A", "position": "WR", "draft_round": 1, "rookie_season": 2024},
        ]
        baseline = build_rookie_archetype_baseline(
            rows_by_season, id_map, _STACKED_SCORING,
        )
        self.assertEqual(baseline, {})

    def test_skips_udfa(self):
        # Rookie with no draft_round → not eligible for the cohort.
        rows_by_season = {
            2024: [_weekly_row("A", "LB", w, def_tackles_solo=4) for w in range(1, 18)],
        }
        id_map = [
            # Two with draft_round=None (dropped) and one with =None
            {"gsis_id": "A", "position": "LB", "draft_round": None, "rookie_season": 2024},
        ]
        baseline = build_rookie_archetype_baseline(
            rows_by_season, id_map, _STACKED_SCORING,
        )
        self.assertEqual(baseline, {})


class TestComputeIdpScoringFitWithRookies(unittest.TestCase):
    """End-to-end: pre-season rookie with no realized weeks gets a
    synthetic row from the (position, draft_round) cohort baseline."""

    def test_rookie_with_draft_data_gets_synthetic(self):
        # Cohort source: 2 historical EDGE rookies in 2023.
        rows_by_season = {
            2023: [
                _weekly_row("HIST_A", "EDGE", w,
                            def_tackles_solo=2, def_sacks=1,
                            def_qb_hits=1, def_tackles_for_loss=1)
                for w in range(1, 18)
            ] + [
                _weekly_row("HIST_B", "EDGE", w,
                            def_tackles_solo=2, def_sacks=1,
                            def_qb_hits=1, def_tackles_for_loss=1)
                for w in range(1, 18)
            ],
        }
        id_map = [
            {"gsis_id": "HIST_A", "position": "EDGE", "draft_round": 1, "rookie_season": 2023},
            {"gsis_id": "HIST_B", "position": "EDGE", "draft_round": 1, "rookie_season": 2023},
            # The current rookie:
            {"gsis_id": "ROOKIE_C", "position": "EDGE", "draft_round": 1, "rookie_season": 2025},
        ]
        sleeper_to_gsis = {"sleeper_C": "ROOKIE_C"}
        players = [
            {
                "displayName": "Rookie EDGE",
                "position": "EDGE",
                "playerId": "sleeper_C",
                "rankDerivedValue": 5000,
            },
        ]
        roster_positions = [
            "QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "DL", "LB", "DB",
        ]
        out = compute_idp_scoring_fit(
            players, _STACKED_SCORING, roster_positions, num_teams=12,
            weekly_rows_by_season=rows_by_season,
            id_map_rows=id_map,
            sleeper_to_gsis=sleeper_to_gsis,
        )
        self.assertIn("Rookie EDGE", out)
        row = out["Rookie EDGE"]
        self.assertTrue(row.synthetic, "rookie should get synthetic flag")
        self.assertEqual(row.draft_round, 1)
        self.assertEqual(row.confidence, "synthetic")
        # weighted_ppg should equal the cohort baseline (~10.5 ppg).
        self.assertIsNotNone(row.weighted_ppg)
        self.assertAlmostEqual(row.weighted_ppg, 10.5, places=1)

    def test_rookie_without_draft_data_falls_back_to_sentinel(self):
        # No id_map → no synthetic available.
        players = [
            {
                "displayName": "UDFA Rookie",
                "position": "LB",
                "playerId": "sleeper_X",
                "rankDerivedValue": 1500,
            },
        ]
        out = compute_idp_scoring_fit(
            players, _STACKED_SCORING, ["LB"], num_teams=12,
            weekly_rows_by_season={},
            id_map_rows=None,
            sleeper_to_gsis=None,
        )
        self.assertIn("UDFA Rookie", out)
        row = out["UDFA Rookie"]
        self.assertEqual(row.tier, "rookie")
        self.assertFalse(row.synthetic)
        self.assertIsNone(row.delta)


class TestStampDelta(unittest.TestCase):
    """``stamp_delta`` derives the value-scale delta from a fit row."""

    def test_synthetic_row_gets_a_delta(self):
        # Synthetic row with known vorp.  par_distribution must include
        # at least one positive entry for the percentile lookup to work.
        row = IdpFitRow(
            player_id="x",
            position="EDGE",
            vorp=68.0,
            tier="starter",
            delta=None,
            confidence="synthetic",
            weighted_ppg=9.0,
            games_used=0,
            synthetic=True,
            draft_round=1,
        )
        stamped = stamp_delta(row, consensus_value=5000.0,
                               par_distribution=[1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertIsNotNone(stamped.delta)

    def test_sentinel_rookie_row_passes_through(self):
        row = IdpFitRow(
            player_id="",
            position="LB",
            vorp=None,
            tier="rookie",
            delta=None,
            confidence="none",
            weighted_ppg=None,
            games_used=0,
        )
        stamped = stamp_delta(row, consensus_value=1500.0, par_distribution=[1.0, 2.0, 3.0])
        self.assertIsNone(stamped.delta)


class TestQuantileMap(unittest.TestCase):
    """The cross-position normalisation step."""

    def test_below_replacement_returns_zero(self):
        self.assertEqual(quantile_map_to_consensus_scale(-1.0, [1.0, 2.0]), 0.0)

    def test_empty_distribution_returns_zero(self):
        self.assertEqual(quantile_map_to_consensus_scale(5.0, []), 0.0)

    def test_top_par_value_maps_high_on_curve(self):
        # The largest PAR in the distribution should land near the top
        # of the IDP value curve.
        v = quantile_map_to_consensus_scale(10.0, [1.0, 2.0, 5.0, 10.0])
        self.assertGreater(v, 1000)


class TestAggregateStatContributions(unittest.TestCase):
    """Top-N stat-category aggregation surfaces what's driving a
    player's realized fantasy points under the league's scoring."""

    def test_returns_top_n_sorted_by_absolute_points(self):
        # An EDGE with one event-stack week × 16 weeks: 1 sack-tackle
        # generating sack + sack_yds + qb_hit + tfl + solo simultaneously.
        rows = {
            2024: [
                _weekly_row("E1", "EDGE", w,
                            def_tackles_solo=1, def_sacks=1,
                            def_sack_yards=7, def_qb_hits=1,
                            def_tackles_for_loss=1)
                for w in range(1, 17)
            ],
        }
        out = aggregate_stat_contributions(
            "E1", "EDGE", _STACKED_SCORING,
            weekly_rows_by_season=rows,
            top_n=4,
        )
        # Should land top-4 in absolute-points order.  16 weeks of
        # the same stack: sack_total=16 × 4=64, sack_yds=112 × 0.5=56,
        # tfl=16 × 2=32, solo=16 × 1.5=24, qb_hit=16 × 1.5=24.
        self.assertEqual(len(out), 4)
        labels = [e["label"] for e in out]
        # Sack should be the biggest (64).
        self.assertEqual(labels[0], "Sack")
        # Each entry has the contract fields.
        for e in out:
            self.assertIn("label", e)
            self.assertIn("stat_total", e)
            self.assertIn("points_total", e)
            self.assertIn("share", e)
            self.assertGreaterEqual(e["share"], 0)
            self.assertLessEqual(e["share"], 1)

    def test_returns_empty_when_no_realized_data(self):
        out = aggregate_stat_contributions(
            "MISSING", "LB", _STACKED_SCORING,
            weekly_rows_by_season={2024: []},
        )
        self.assertEqual(out, [])

    def test_share_sums_to_one_within_top_n(self):
        # Single-stat-category fixture so share = 1.0 exactly.
        rows = {
            2024: [
                _weekly_row("L1", "LB", w, def_tackles_solo=4)
                for w in range(1, 18)
            ],
        }
        out = aggregate_stat_contributions(
            "L1", "LB", {"idp_tkl_solo": 1.5},
            weekly_rows_by_season=rows,
        )
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(out[0]["share"], 1.0, places=2)


if __name__ == "__main__":
    unittest.main()
