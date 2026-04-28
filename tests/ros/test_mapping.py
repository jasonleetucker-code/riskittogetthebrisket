"""Player-mapping resolver tests.

Cover the four resolution paths (override / exact / alias / fuzzy) +
the quarantine fallback.  Inputs are pure strings so these tests
don't depend on a live player pool.
"""
from __future__ import annotations

import unittest

from src.ros.mapping import resolve_player


class TestResolvePlayer(unittest.TestCase):
    def test_override_wins(self):
        result = resolve_player(
            "M. Williams (TE)",
            overrides={"M. Williams (TE)": "Mike Williams TE"},
        )
        self.assertEqual(result.canonical_name, "Mike Williams TE")
        self.assertEqual(result.method, "override")
        self.assertAlmostEqual(result.confidence, 1.0)

    def test_exact_match_against_universe(self):
        # Pre-normalize the canonical entry so the input lands on it.
        from src.utils.name_clean import normalize_player_name
        target = normalize_player_name("Justin Jefferson")
        universe = {target}
        result = resolve_player("Justin Jefferson", canonical_universe=universe, overrides={})
        self.assertEqual(result.canonical_name, target)
        self.assertEqual(result.method, "exact")
        self.assertAlmostEqual(result.confidence, 1.0)

    def test_fuzzy_picks_closest_match(self):
        from src.utils.name_clean import normalize_player_name
        universe = {normalize_player_name("Marvin Harrison Jr.")}
        # Source typo: "Marvin Harrison J" — single-character edit.
        result = resolve_player(
            "Marvin Harrison J", canonical_universe=universe, overrides={}
        )
        self.assertEqual(result.method, "fuzzy")
        self.assertEqual(result.canonical_name, normalize_player_name("Marvin Harrison Jr."))

    def test_quarantine_when_no_match(self):
        result = resolve_player(
            "ZzImaginaryPlayer", canonical_universe={"justin jefferson"}, overrides={}
        )
        self.assertIsNone(result.canonical_name)
        self.assertEqual(result.method, "quarantine")
        self.assertEqual(result.confidence, 0.0)

    def test_empty_input_quarantines(self):
        result = resolve_player("", overrides={})
        self.assertIsNone(result.canonical_name)
        self.assertEqual(result.method, "empty")

    def test_no_universe_returns_normalized_input(self):
        # Tests + scripts that don't have a live pool fall through to
        # the normalize-only path with confidence 1.0 and method
        # "exact-no-universe".
        result = resolve_player("Josh Allen", overrides={})
        self.assertIsNotNone(result.canonical_name)
        self.assertEqual(result.method, "exact-no-universe")


if __name__ == "__main__":
    unittest.main()
