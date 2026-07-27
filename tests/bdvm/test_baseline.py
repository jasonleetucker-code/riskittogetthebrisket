"""Reconstructed-baseline builder: normalization, history, rookie priors."""

from __future__ import annotations

import unittest

from src.bdvm.baseline import (
    build_baseline_records,
    build_rookie_prior_records,
    normalize_weekly_row,
    positional_means,
    realized_ppg_history,
)
from src.bdvm.context import PlayerContext
from src.bdvm.projections import RealizedSeason

_norm = lambda s: s.lower()  # noqa: E731

PPR = {
    "rec": 1.0,
    "rec_yd": 0.1,
    "rec_td": 6.0,
    "pass_yd": 0.04,
    "pass_td": 4.0,
    "pass_int": -2.0,
    "idp_tkl_solo": 1.0,
    "idp_tkl": 0.5,
}


def wr_week(name, season, week, rec, yd, td=0.0, season_type="REG"):
    return {
        "player_display_name": name,
        "position": "WR",
        "season": season,
        "week": week,
        "season_type": season_type,
        "receptions": rec,
        "receiving_yards": yd,
        "receiving_tds": td,
    }


class TestNormalization(unittest.TestCase):
    def test_raw_aliases_fill_missing_keys(self):
        row = normalize_weekly_row(
            {
                "passing_interceptions": 2,
                "sacks_suffered": 3,
                "fumbles_lost_total": 1,
            }
        )
        self.assertEqual(row["interceptions"], 2)
        self.assertEqual(row["sacks"], 3)
        self.assertEqual(row["fumbles_lost"], 1)

    def test_existing_canonical_keys_win(self):
        row = normalize_weekly_row({"interceptions": 1, "passing_interceptions": 9})
        self.assertEqual(row["interceptions"], 1)

    def test_combined_tackles_never_synthesized(self):
        """A published ``def_tackles`` means gamebook SOLO to the scoring
        path (pre-2025 schema) — the normalizer must not fabricate one."""
        row = normalize_weekly_row({"def_tackles_solo": 4, "def_tackle_assists": 2})
        self.assertNotIn("def_tackles", row)


class TestHistory(unittest.TestCase):
    def test_ppg_math_and_position_mapping(self):
        weeks = [
            wr_week("Alpha", 2025, 1, 5, 70),  # 12 pts
            wr_week("Alpha", 2025, 2, 7, 90, td=1.0),  # 22 pts
            wr_week("Alpha", 2025, 19, 9, 150, td=2.0, season_type="POST"),  # excluded
            {
                "player_display_name": "Edge Dude",
                "position": "DE",
                "season": 2025,
                "week": 1,
                "season_type": "REG",
                "def_tackles_solo": 5,
                "def_tackle_assists": 1,
            },
        ]
        hist = realized_ppg_history(weeks, PPR, name_normalizer=_norm)
        pos, seasons = hist["alpha"]
        self.assertEqual(pos, "WR")
        self.assertEqual(len(seasons), 1)
        self.assertEqual(seasons[0].games, 2.0)
        self.assertAlmostEqual(seasons[0].ppg, 17.0)  # (12+22)/2, playoffs excluded
        # DE maps to EDGE; solo 5*1.0 + combined 6*0.5 = 8.0
        pos_e, seasons_e = hist["edge dude"]
        self.assertEqual(pos_e, "EDGE")
        self.assertAlmostEqual(seasons_e[0].ppg, 8.0)

    def test_positional_means_filters_thin_seasons(self):
        hist = {
            "a": ("WR", [RealizedSeason(2025, 15.0, 16.0)]),
            "b": ("WR", [RealizedSeason(2025, 9.0, 16.0)]),
            "thin": ("WR", [RealizedSeason(2025, 30.0, 3.0)]),  # < min games
            "zero": ("WR", [RealizedSeason(2025, 0.2, 16.0)]),  # < floor
        }
        means = positional_means(hist)
        self.assertAlmostEqual(means["WR"], 12.0)

    def test_build_baseline_records_end_to_end(self):
        weeks = [
            wr_week("Alpha", s, w, 6, 80, td=0.5) for s in (2023, 2024, 2025) for w in range(1, 11)
        ]
        records, summary = build_baseline_records(
            season=2026,
            as_of="2026-07-27",
            weekly_rows=weeks,
            scoring_settings=PPR,
            name_normalizer=_norm,
        )
        self.assertEqual(summary["recordsBuilt"], 1)
        r = records[0]
        self.assertTrue(r.is_proxy)
        # constant 17 PPG history, positional mean == own PPG → mu == 17
        self.assertAlmostEqual(r.fpg, 17.0, places=6)


class TestRookiePriors(unittest.TestCase):
    def _history(self):
        # ten first-round WR rookies from past classes at ~10 PPG,
        # ten day-3 WR rookies at ~4 PPG
        hist = {}
        ctx = {}
        for i in range(10):
            key = f"r1 wr {i}"
            hist[key] = ("WR", [RealizedSeason(2024, 10.0 + i * 0.1, 14.0)])
            ctx[key] = PlayerContext(
                player_key=key,
                rookie_season=2024,
                draft_overall=5 + i,
                true_position="WR",
                draft_capital_score=1.0,
            )
        for i in range(10):
            key = f"r3 wr {i}"
            hist[key] = ("WR", [RealizedSeason(2024, 4.0, 14.0)])
            ctx[key] = PlayerContext(
                player_key=key,
                rookie_season=2024,
                draft_overall=110 + i,
                true_position="WR",
                draft_capital_score=0.4,
            )
        # incoming 2026 rookies
        ctx["new stud"] = PlayerContext(
            player_key="new stud",
            rookie_season=2026,
            draft_overall=3,
            true_position="WR",
            draft_capital_score=1.0,
        )
        ctx["new dart"] = PlayerContext(
            player_key="new dart",
            rookie_season=2026,
            draft_overall=120,
            true_position="WR",
            draft_capital_score=0.3,
        )
        ctx["new udfa"] = PlayerContext(
            player_key="new udfa", rookie_season=2026, draft_overall=None, true_position="WR"
        )
        return hist, ctx

    def test_bucket_means_flow_to_incoming_class(self):
        hist, ctx = self._history()
        records, summary = build_rookie_prior_records(
            season=2026,
            as_of="2026-07-27",
            history=hist,
            context=ctx,
        )
        by_key = {r.player_key: r for r in records}
        stud = by_key["new stud"]
        dart = by_key["new dart"]
        self.assertAlmostEqual(stud.fpg, 10.45, places=2)  # r1 bucket mean
        self.assertAlmostEqual(dart.fpg, 4.0, places=2)  # r3plus bucket mean
        self.assertGreater(stud.fpg, dart.fpg)
        self.assertTrue(stud.is_proxy)
        self.assertEqual(summary["undraftedRookiesSkipped"], 1)
        self.assertNotIn("new udfa", by_key)  # honestly unpriced

    def test_thin_bucket_falls_back_to_position_mean(self):
        hist, ctx = self._history()
        # one lone 2nd-rounder in history — below min bucket N
        hist["lone r2"] = ("WR", [RealizedSeason(2024, 7.0, 14.0)])
        ctx["lone r2"] = PlayerContext(
            player_key="lone r2", rookie_season=2024, draft_overall=40, true_position="WR"
        )
        ctx["new r2"] = PlayerContext(
            player_key="new r2", rookie_season=2026, draft_overall=45, true_position="WR"
        )
        records, _ = build_rookie_prior_records(
            season=2026,
            as_of="2026-07-27",
            history=hist,
            context=ctx,
        )
        by_key = {r.player_key: r for r in records}
        pos_mean = (sum(10.0 + i * 0.1 for i in range(10)) + 40.0 + 7.0) / 21.0
        self.assertAlmostEqual(by_key["new r2"].fpg, pos_mean, places=2)


if __name__ == "__main__":
    unittest.main()
