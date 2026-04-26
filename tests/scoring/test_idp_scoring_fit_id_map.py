"""Tests for the id_map helpers — covers both schemas (``nfl_data_py``
``import_ids`` and the leaner ``nflverse_direct`` players.csv).

Regression target: production logs showed ``name=0`` in the cross-walk
fallback because the live id_map (from ``nfl_data_py.import_ids``)
uses field ``name`` while the test fixture used ``display_name``.
These tests pin both schemas going forward.
"""
from __future__ import annotations

import unittest

from src.scoring.idp_scoring_fit import (
    _build_gsis_to_draft,
    _build_name_to_gsis,
    _id_map_name,
    _id_map_rookie_season,
    _id_map_sleeper_id,
    build_rookie_archetype_baseline,
    build_sleeper_to_gsis_from_id_map,
)


class TestIdMapNameExtraction(unittest.TestCase):
    """Both ``name`` (nfl_data_py) and ``display_name`` (nflverse_direct)
    schemas must produce the same canonical name."""

    def test_prefers_name_field(self):
        self.assertEqual(
            _id_map_name({"name": "Micah Parsons", "display_name": "OVERRIDE"}),
            "Micah Parsons",
        )

    def test_falls_back_to_display_name(self):
        self.assertEqual(
            _id_map_name({"display_name": "Micah Parsons"}),
            "Micah Parsons",
        )

    def test_empty_when_neither_present(self):
        self.assertEqual(_id_map_name({}), "")


class TestIdMapSleeperId(unittest.TestCase):
    """Sleeper id can be int, float (pandas), string, or NaN."""

    def test_int_passes_through(self):
        self.assertEqual(_id_map_sleeper_id({"sleeper_id": 7651}), "7651")

    def test_float_strips_trailing_zero(self):
        self.assertEqual(_id_map_sleeper_id({"sleeper_id": 7651.0}), "7651")

    def test_nan_returns_empty(self):
        # NaN comparison: nan != nan
        self.assertEqual(_id_map_sleeper_id({"sleeper_id": float("nan")}), "")

    def test_missing_returns_empty(self):
        self.assertEqual(_id_map_sleeper_id({}), "")

    def test_string_nan_returns_empty(self):
        self.assertEqual(_id_map_sleeper_id({"sleeper_id": "nan"}), "")


class TestIdMapRookieSeason(unittest.TestCase):
    """Both ``rookie_season`` (nflverse_direct) and ``draft_year``
    (nfl_data_py) resolve to the rookie season."""

    def test_prefers_rookie_season(self):
        self.assertEqual(
            _id_map_rookie_season({"rookie_season": 2021, "draft_year": 2020}),
            2021,
        )

    def test_falls_back_to_draft_year(self):
        self.assertEqual(
            _id_map_rookie_season({"draft_year": 2021}),
            2021,
        )

    def test_handles_float_draft_year(self):
        # nfl_data_py returns numeric columns as floats.
        self.assertEqual(
            _id_map_rookie_season({"draft_year": 2021.0}),
            2021,
        )

    def test_rejects_nan(self):
        self.assertIsNone(
            _id_map_rookie_season({"draft_year": float("nan")}),
        )

    def test_rejects_out_of_range(self):
        self.assertIsNone(_id_map_rookie_season({"draft_year": 1850}))
        self.assertIsNone(_id_map_rookie_season({"draft_year": 2999}))


class TestSleeperToGsisFromIdMap(unittest.TestCase):
    """Build the direct sleeper_id → gsis cross-walk from the rich
    id_map.  Empty when the id_map source is the leaner schema with
    no sleeper_id column."""

    def test_builds_from_rich_schema(self):
        id_map = [
            {"gsis_id": "00-0036915", "sleeper_id": 7651.0},
            {"gsis_id": "00-0030506", "sleeper_id": 4017.0},
        ]
        out = build_sleeper_to_gsis_from_id_map(id_map)
        self.assertEqual(out, {"7651": "00-0036915", "4017": "00-0030506"})

    def test_empty_when_no_sleeper_id_field(self):
        id_map = [
            {"gsis_id": "00-0036915", "display_name": "Jeremiah Owusu-Koramoah"},
        ]
        self.assertEqual(build_sleeper_to_gsis_from_id_map(id_map), {})

    def test_filters_nan_sleeper_id(self):
        id_map = [
            {"gsis_id": "00-0036915", "sleeper_id": float("nan")},
            {"gsis_id": "00-0030506", "sleeper_id": 4017.0},
        ]
        out = build_sleeper_to_gsis_from_id_map(id_map)
        self.assertEqual(out, {"4017": "00-0030506"})


class TestBuildNameToGsis(unittest.TestCase):
    """Name fallback uses both ``name`` and ``display_name`` fields,
    keyed by position to avoid cross-position collisions."""

    def test_position_qualified_key_present(self):
        id_map = [
            {"gsis_id": "G1", "name": "Micah Parsons", "position": "LB"},
        ]
        out = _build_name_to_gsis(id_map)
        self.assertIn("micah parsons|LB", out)
        self.assertEqual(out["micah parsons|LB"], "G1")

    def test_handles_punctuation_in_name(self):
        id_map = [
            {"gsis_id": "G1", "name": "T.J. Watt", "position": "LB"},
        ]
        out = _build_name_to_gsis(id_map)
        self.assertIn("tj watt|LB", out)

    def test_works_with_legacy_display_name_schema(self):
        # nflverse_direct shape — no ``name`` field, has ``display_name``.
        id_map = [
            {"gsis_id": "G1", "display_name": "Micah Parsons", "position": "LB"},
        ]
        out = _build_name_to_gsis(id_map)
        self.assertIn("micah parsons|LB", out)


class TestRookieArchetypeWithRichSchema(unittest.TestCase):
    """The rookie cohort baseline must work with the live id_map
    schema (``draft_year`` instead of ``rookie_season``)."""

    def test_builds_cohort_from_draft_year(self):
        rows_by_season = {
            2023: [
                # Two rookie EDGEs, draft_year=2023.  Same per-week stats.
                {"player_id": "G_A", "season": 2023, "week": w,
                 "def_tackles_solo": 3, "def_sacks": 1}
                for w in range(1, 18)
            ] + [
                {"player_id": "G_B", "season": 2023, "week": w,
                 "def_tackles_solo": 3, "def_sacks": 1}
                for w in range(1, 18)
            ],
        }
        id_map_rich = [
            # Live id_map shape: ``name`` + ``draft_year``, no rookie_season.
            {"gsis_id": "G_A", "name": "Player A",
             "position": "EDGE", "draft_year": 2023.0, "draft_round": 1.0},
            {"gsis_id": "G_B", "name": "Player B",
             "position": "EDGE", "draft_year": 2023.0, "draft_round": 1.0},
        ]
        scoring = {"idp_tkl_solo": 1.5, "idp_sack": 4.0}
        baseline = build_rookie_archetype_baseline(
            rows_by_season, id_map_rich, scoring,
        )
        self.assertIn(("EDGE", 1), baseline)
        # 3 solos × 1.5 + 1 sack × 4.0 = 8.5 ppg
        self.assertAlmostEqual(baseline[("EDGE", 1)], 8.5, places=2)


class TestGsisToDraftWithRichSchema(unittest.TestCase):
    """The draft-round lookup index must accept either schema."""

    def test_builds_from_draft_year(self):
        id_map = [
            {"gsis_id": "G1", "name": "Player A",
             "position": "LB", "draft_year": 2023.0, "draft_round": 1.0},
        ]
        out = _build_gsis_to_draft(id_map)
        self.assertIn("G1", out)
        position, draft_round, rookie_season = out["G1"]
        self.assertEqual(position, "LB")
        self.assertEqual(draft_round, 1)
        self.assertEqual(rookie_season, 2023)


if __name__ == "__main__":
    unittest.main()
