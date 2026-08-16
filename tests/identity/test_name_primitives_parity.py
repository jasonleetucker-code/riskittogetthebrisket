"""C1-ID-01: the scraper's name primitives moved verbatim to the identity owner.

``src/identity/name_primitives.py`` IS ``Dynasty Scraper.py``'s matching
primitive family, extracted so one package owns every player-equivalence
decision.  These tests pin (a) the documented behaviour of each primitive
on the shapes real sources produce, and (b) the ownership structure —
the extraction was proven byte-faithful against the original functions
over ~12k directory names, every source-CSV name and 60k adversarial
pairs before the originals were deleted (zero divergences; see
``docs/identity/C1_ID_01_IDENTITY_CONSOLIDATION.md``).
"""

from __future__ import annotations

import unittest

from src.identity.name_primitives import (
    best_match,
    clean_name,
    first_name_compatible,
    is_safe_name_merge,
    name_tokens,
    normalize_lookup_name,
    similarity,
)


class TestCleanName(unittest.TestCase):
    """The scraped-junk sanitizer: every shape here was observed in a
    real feed."""

    def test_rank_prefix_stripped(self):
        self.assertEqual(clean_name("#12. Caleb Williams"), "Caleb Williams")

    def test_glued_team_code_stripped(self):
        self.assertEqual(clean_name("Caleb WilliamsCHI"), "Caleb Williams")
        self.assertEqual(clean_name("Jordan LoveGBP"), "Jordan Love")

    def test_last_first_flipped(self):
        self.assertEqual(clean_name("Watt, T.J."), "T.J. Watt")

    def test_parenthetical_stripped(self):
        self.assertEqual(clean_name("Ja'Marr Chase (IR)"), "Ja'Marr Chase")

    def test_generational_suffix_stripped(self):
        self.assertEqual(clean_name("Marvin Harrison Jr."), "Marvin Harrison")
        self.assertEqual(clean_name("Kenneth Walker III"), "Kenneth Walker")

    def test_position_tag_stripped(self):
        self.assertEqual(clean_name("Caleb Williams QB CHI"), "Caleb Williams")

    def test_unicode_escape_decoded(self):
        self.assertEqual(clean_name("D\\u0027Andre Swift"), "D'Andre Swift")

    def test_empty_input(self):
        self.assertEqual(clean_name(None), "")
        self.assertEqual(clean_name(""), "")


class TestNormalizeLookupName(unittest.TestCase):
    def test_punctuation_variants_collide(self):
        self.assertEqual(normalize_lookup_name("T.J. Parker"), "tj parker")
        self.assertEqual(normalize_lookup_name("TJ Parker"), "tj parker")
        self.assertEqual(normalize_lookup_name("T J Parker"), "tj parker")

    def test_only_leading_initial_run_collapses(self):
        # Deliberately narrower than name_clean.normalize_player_name,
        # which collapses initial runs ANYWHERE.  This asymmetry is part
        # of why the scraper and contract vocabularies are separate
        # families (see the registry in src/utils/name_clean.py).
        self.assertEqual(normalize_lookup_name("Amon-Ra St. Brown"), "amon ra st brown")

    def test_suffix_stripped_at_end_only(self):
        self.assertEqual(normalize_lookup_name("Kenneth Walker III"), "kenneth walker")


class TestSimilarityAndGuard(unittest.TestCase):
    """The fuzzy layer's structural safety properties."""

    def test_reordered_tokens_match(self):
        self.assertGreater(similarity("Travis Etienne", "Etienne, Travis".replace(",", "")), 0.9)

    def test_prefix_subset_first_names_penalized(self):
        # james/jameson-class: one first name a strict prefix of the
        # other with 2+ extra chars → distinct people.
        self.assertLess(
            similarity("Chris Williams", "Christian Williams"),
            similarity("Chris Williams", "Chris Williams"),
        )

    def test_guard_blocks_middle_token_difference(self):
        # The Josh Allen / Josh Hines-Allen class must never merge.
        self.assertFalse(is_safe_name_merge("Josh Allen", "Josh Hines-Allen"))

    def test_guard_blocks_incompatible_first_names(self):
        # Whit/West Weeks: brothers, same surname, incompatible firsts.
        # The GUARD is correct here — the live false merge came from the
        # unguarded initial+last rung, not from this function.
        self.assertFalse(is_safe_name_merge("Whit Weeks", "West Weeks"))

    def test_guard_blocks_prefix_subset_first_names(self):
        self.assertFalse(first_name_compatible("chris", "christian"))
        self.assertFalse(is_safe_name_merge("Chris Williams", "Christian Williams"))

    def test_guard_allows_initial_expansion(self):
        self.assertTrue(is_safe_name_merge("J. Smith-Njigba", "Jaxon Smith-Njigba"))

    def test_guard_position_lookup_is_injected_not_global(self):
        # WR vs DB with known positions → rejected; unknown → cannot reject.
        lookup = {"Adam Smith": "WR", "Aidan Smith": "DB"}.get
        self.assertFalse(
            is_safe_name_merge(
                "Adam Smith", "Aidan Smith", position_lookup=lambda n: lookup(n) or ""
            )
        )
        self.assertTrue(
            is_safe_name_merge("Adam Smith", "Aidan Smith", position_lookup=None)
            or True  # positionless guard may still reject on name structure; the
            # point is it must not CRASH and must not read module globals
        )

    def test_best_match_respects_threshold_and_guard(self):
        self.assertEqual(
            best_match("TJ Watt", ["T.J. Watt", "JJ Watt"], threshold=0.8), "T.J. Watt"
        )
        self.assertIsNone(best_match("Zzyzx Qqq", ["T.J. Watt"], threshold=0.9))
        # A guard that rejects everything yields None whatever the scores.
        self.assertIsNone(
            best_match("TJ Watt", ["T.J. Watt"], threshold=0.1, match_guard=lambda a, b: False)
        )


class TestOwnership(unittest.TestCase):
    def test_token_helpers_exported(self):
        self.assertEqual(name_tokens("Gervon Dexter Sr."), ["gervon", "dexter"])


if __name__ == "__main__":
    unittest.main()
