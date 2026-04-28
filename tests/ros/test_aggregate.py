"""Aggregator unit tests.

Pin the rank → score conversion, weighted-average behavior, confidence
math, and tier assignment.  Inputs are entirely synthetic so these
tests don't depend on a live scrape.
"""
from __future__ import annotations

import math
import unittest
from datetime import datetime, timezone

from src.ros.aggregate import (
    RankedRow,
    SourceSnapshot,
    aggregate,
)
from src.ros.parse import (
    rank_to_score,
    format_match_multiplier,
    freshness_multiplier,
)


_LEAGUE = {
    "is_superflex": True,
    "is_2qb": False,
    "is_te_premium": True,
    "idp_enabled": True,
}

_NOW = datetime(2026, 4, 28, 12, 0, 0, tzinfo=timezone.utc)
_FRESH = "2026-04-28T11:00:00+00:00"


def _snapshot(key: str, base_weight: float, rows: list[tuple[str, str, int]], total: int) -> SourceSnapshot:
    return SourceSnapshot(
        source_key=key,
        base_weight=base_weight,
        is_ros=True,
        is_dynasty=False,
        is_te_premium=False,
        is_superflex=True,
        is_2qb=False,
        is_idp=False,
        status="ok",
        scraped_at=_FRESH,
        player_count=total,
        has_valid_cache=True,
        rows=[
            RankedRow(canonical_name=name, position=pos, rank=rank, total_ranked=total)
            for name, pos, rank in rows
        ],
    )


class TestRankToScore(unittest.TestCase):
    def test_top_rank_yields_near_max(self):
        # rank 1 of 100 should be near 100.
        self.assertGreater(rank_to_score(1, 100), 95)

    def test_bottom_rank_yields_near_zero(self):
        # Per spec: 100 * (ln(N+1) - ln(r)) / ln(N+1).  At r=N this is
        # tiny but positive (~0.2 for N=100), not exactly zero — the
        # log curve never crosses 0 except at r=N+1.
        self.assertLess(rank_to_score(100, 100), 1.0)

    def test_invalid_inputs_return_zero(self):
        self.assertEqual(rank_to_score(0, 100), 0.0)
        self.assertEqual(rank_to_score(101, 100), 0.0)
        self.assertEqual(rank_to_score(-1, 100), 0.0)
        self.assertEqual(rank_to_score(50, 0), 0.0)

    def test_top_heavy(self):
        # rank 5 should be much closer to rank 1 than rank 50.
        s1 = rank_to_score(1, 100)
        s5 = rank_to_score(5, 100)
        s50 = rank_to_score(50, 100)
        self.assertGreater(s1 - s5, 0)
        self.assertGreater(s5 - s50, s1 - s5)


class TestFreshnessMultiplier(unittest.TestCase):
    def test_fresh_today(self):
        self.assertAlmostEqual(freshness_multiplier(_FRESH, now=_NOW), 1.0)

    def test_one_day_old(self):
        when = "2026-04-27T12:00:00+00:00"
        self.assertAlmostEqual(freshness_multiplier(when, now=_NOW), 0.90)

    def test_three_days_old(self):
        when = "2026-04-25T12:00:00+00:00"
        self.assertAlmostEqual(freshness_multiplier(when, now=_NOW), 0.75)

    def test_eight_days_old(self):
        when = "2026-04-20T12:00:00+00:00"
        self.assertAlmostEqual(freshness_multiplier(when, now=_NOW), 0.25)

    def test_missing_timestamp(self):
        self.assertEqual(freshness_multiplier(None), 0.0)


class TestFormatMatch(unittest.TestCase):
    def test_sf_plus_tep_match(self):
        src = {"is_superflex": True, "is_te_premium": True, "is_ros": True}
        self.assertAlmostEqual(format_match_multiplier(src, _LEAGUE), 1.15)

    def test_sf_only(self):
        src = {"is_superflex": True, "is_te_premium": False, "is_ros": True}
        self.assertAlmostEqual(format_match_multiplier(src, _LEAGUE), 1.10)

    def test_dynasty_proxy_demotion(self):
        src = {"is_superflex": False, "is_dynasty": True, "is_ros": False}
        self.assertAlmostEqual(format_match_multiplier(src, _LEAGUE), 0.85)

    def test_idp_source_idp_player_bonus(self):
        src = {"is_idp": True, "is_ros": True}
        m = format_match_multiplier(src, _LEAGUE, position="DL")
        # 1.05 IDP bonus, no SF/TEP match → 1.05 * 0.95 = 0.9975
        self.assertAlmostEqual(m, 1.05 * 0.95)


class TestAggregate(unittest.TestCase):
    def test_two_sources_blend_correctly(self):
        # Source A has Allen at rank 1 (score ~99); source B has him at
        # rank 2 (score ~95.4).  Both 100-deep.  Aggregate should land
        # between the two scores, weighted by base_weight.
        src_a = _snapshot(
            "draftSharksRosSf", 1.25, [("Josh Allen", "QB", 1), ("Lamar Jackson", "QB", 2)], 100
        )
        src_b = _snapshot(
            "fantasyProsRosSf", 0.85, [("Josh Allen", "QB", 2), ("Lamar Jackson", "QB", 1)], 100
        )
        out = aggregate([src_a, src_b], league=_LEAGUE, now_iso=_NOW.isoformat())
        self.assertEqual(len(out), 2)
        names = {p["canonicalName"] for p in out}
        self.assertEqual(names, {"Josh Allen", "Lamar Jackson"})
        # rosValue is in [0, 100]
        for p in out:
            self.assertGreaterEqual(p["rosValue"], 0)
            self.assertLessEqual(p["rosValue"], 100)
        # Allen (rank 1 in higher-weighted DS) should outrank Jackson.
        ros_by_name = {p["canonicalName"]: p["rosValue"] for p in out}
        self.assertGreater(ros_by_name["Josh Allen"], ros_by_name["Lamar Jackson"])

    def test_overall_rank_assigned(self):
        src = _snapshot(
            "draftSharksRosSf",
            1.0,
            [("A", "QB", 1), ("B", "WR", 2), ("C", "RB", 3)],
            3,
        )
        out = aggregate([src], league=_LEAGUE)
        ranks = sorted((p["canonicalName"], p["rosRankOverall"]) for p in out)
        self.assertEqual(ranks, [("A", 1), ("B", 2), ("C", 3)])

    def test_position_rank_independent(self):
        src = _snapshot(
            "draftSharksRosSf",
            1.0,
            [
                ("QB1", "QB", 1),
                ("QB2", "QB", 2),
                ("RB1", "RB", 3),
                ("RB2", "RB", 4),
            ],
            4,
        )
        out = aggregate([src], league=_LEAGUE)
        by_name = {p["canonicalName"]: p for p in out}
        self.assertEqual(by_name["QB1"]["rosRankPosition"], 1)
        self.assertEqual(by_name["QB2"]["rosRankPosition"], 2)
        self.assertEqual(by_name["RB1"]["rosRankPosition"], 1)
        self.assertEqual(by_name["RB2"]["rosRankPosition"], 2)

    def test_confidence_grows_with_source_count(self):
        rows1 = [("A", "QB", 1)]
        rows3 = [("A", "QB", 1)] * 1  # same player from one source
        # 1-source confidence
        s1 = aggregate(
            [_snapshot("only", 1.0, rows1, 1)], league=_LEAGUE
        )[0]["confidence"]
        # 4-source confidence (saturates at 4)
        agg4 = aggregate(
            [
                _snapshot(f"src{i}", 1.0, rows1, 1) for i in range(4)
            ],
            league=_LEAGUE,
        )[0]["confidence"]
        self.assertGreater(agg4, s1)

    def test_empty_input(self):
        self.assertEqual(aggregate([], league=_LEAGUE), [])


if __name__ == "__main__":
    unittest.main()
