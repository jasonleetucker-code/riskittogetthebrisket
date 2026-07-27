"""Player-context builder: identity, draft capital, career loads."""

from __future__ import annotations

import unittest

from src.bdvm.context import (
    PlayerContext,
    build_player_context,
    draft_capital_score,
)

_norm = lambda s: s.lower()  # noqa: E731

ID_ROWS = [
    {
        "display_name": "Star Receiver",
        "position": "WR",
        "birth_date": "2001-03-15",
        "draft_year": 2023,
        "draft_round": 1,
        "draft_pick": 8,
        "rookie_season": 2023,
        "last_season": 2025,
    },
    {
        "display_name": "Late Rounder",
        "position": "DE",
        "birth_date": "1999-01-01",
        "draft_year": 2021,
        "draft_round": 7,
        "draft_pick": 250,
        "rookie_season": 2021,
        "last_season": 2025,
    },
    {
        "display_name": "Udfa Guy",
        "position": "OLB",
        "birth_date": "2000-06-01",
        "draft_year": "",
        "draft_round": "",
        "draft_pick": "",
        "rookie_season": 2024,
        "last_season": 2025,
    },
    {
        "display_name": "Box Hitter",
        "position": "SAF",
        "birth_date": "1998-11-20",
        "draft_year": 2020,
        "draft_round": 2,
        "draft_pick": 45,
        "rookie_season": 2020,
        "last_season": 2025,
    },
]

WEEKLY_ROWS = [
    {
        "player_display_name": "Star Receiver",
        "targets": 10,
        "receptions": 7,
        "carries": 1,
        "attempts": 0,
        "sacks_suffered": 0,
    },
    {
        "player_display_name": "Star Receiver",
        "targets": 8,
        "receptions": 5,
        "carries": 0,
        "attempts": 0,
        "sacks_suffered": 0,
    },
    {
        "player_display_name": "Some Qb",
        "targets": 0,
        "receptions": 0,
        "carries": 4,
        "attempts": 35,
        "sacks_suffered": 3,
    },
]

SNAP_ROWS = [
    {"player": "Late Rounder", "defense_snaps": 55},
    {"player": "Late Rounder", "defense_snaps": 61},
]


class TestDraftCapitalScore(unittest.TestCase):
    def test_top_ten_is_full(self):
        self.assertEqual(draft_capital_score(1), 1.0)
        self.assertEqual(draft_capital_score(10), 1.0)

    def test_decays_and_floors(self):
        self.assertGreater(draft_capital_score(11), draft_capital_score(50))
        self.assertGreater(draft_capital_score(50), draft_capital_score(150))
        self.assertEqual(draft_capital_score(262), 0.0)

    def test_udfa_unknown_is_zero(self):
        self.assertEqual(draft_capital_score(None), 0.0)
        self.assertEqual(draft_capital_score(0), 0.0)


class TestBuildContext(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = build_player_context(
            id_map_rows=ID_ROWS,
            weekly_rows=WEEKLY_ROWS,
            snap_rows=SNAP_ROWS,
            name_normalizer=_norm,
        )

    def test_identity_and_age(self):
        c = self.ctx["star receiver"]
        self.assertEqual(c.true_position, "WR")
        self.assertAlmostEqual(c.age_at_season_start(2026), 25.5, delta=0.1)
        self.assertEqual(c.nfl_season_for(2026), 4)
        self.assertEqual(c.draft_overall, 8)
        self.assertEqual(c.draft_capital_score, 1.0)
        self.assertFalse(c.position_ambiguous)

    def test_career_loads_by_unit(self):
        c = self.ctx["star receiver"]
        self.assertEqual(c.career_load_for("targets"), 18.0)
        self.assertEqual(c.career_load_for("touches"), 13.0)  # carries + receptions
        qb_free = self.ctx.get("some qb")
        # weekly-only players (not in the id map) don't get context rows,
        # but their loads never crash the build
        self.assertIsNone(qb_free)

    def test_idp_snaps_and_udfa(self):
        late = self.ctx["late rounder"]
        self.assertEqual(late.true_position, "EDGE")
        self.assertEqual(late.career_load_for("snaps"), 116.0)
        self.assertAlmostEqual(late.draft_capital_score, 0.0, places=3)
        udfa = self.ctx["udfa guy"]
        self.assertEqual(udfa.draft_capital_score, 0.0)
        self.assertTrue(udfa.position_ambiguous)  # OLB is ambiguous by policy
        self.assertEqual(udfa.true_position, "LB")

    def test_saf_listing_maps_to_s(self):
        self.assertEqual(self.ctx["box hitter"].true_position, "S")

    def test_overall_pick_is_used_verbatim(self):
        """players.csv draft_pick is the OVERALL selection (Purdy 262)."""
        self.assertEqual(self.ctx["box hitter"].draft_overall, 45)

    def test_bad_birth_date_degrades_to_none(self):
        c = PlayerContext(player_key="x", birth_date="not-a-date")
        self.assertIsNone(c.age_at_season_start(2026))


if __name__ == "__main__":
    unittest.main()
