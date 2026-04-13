"""Unit tests for the IDP ranking backbone and position-rank translation.

These tests pin the math in `src/canonical/idp_backbone.py`:
    * backbone construction from ranked entries and from raw rows
    * exact / interpolated / extrapolated / fallback translation
    * coverage-aware weight scaling

They are intentionally pure-Python (no contract fixtures) so regressions
here are isolated from the full pipeline.
"""
from __future__ import annotations

import unittest

from src.canonical.idp_backbone import (
    IDP_POSITION_GROUPS,
    IdpBackbone,
    MIN_FULL_COVERAGE_DEPTH,
    SOURCE_SCOPE_OVERALL_IDP,
    SOURCE_SCOPE_OVERALL_OFFENSE,
    SOURCE_SCOPE_POSITION_IDP,
    TRANSLATION_DIRECT,
    TRANSLATION_EXACT,
    TRANSLATION_EXTRAPOLATED,
    TRANSLATION_FALLBACK,
    TRANSLATION_INTERPOLATED,
    VALID_SOURCE_SCOPES,
    build_backbone_from_ranked_entries,
    build_backbone_from_rows,
    coverage_weight,
    translate_position_rank,
)


class TestScopeConstants(unittest.TestCase):
    def test_all_three_scopes_in_valid_set(self):
        self.assertEqual(
            VALID_SOURCE_SCOPES,
            frozenset(
                {
                    SOURCE_SCOPE_OVERALL_OFFENSE,
                    SOURCE_SCOPE_OVERALL_IDP,
                    SOURCE_SCOPE_POSITION_IDP,
                }
            ),
        )

    def test_idp_position_groups_are_the_three_families(self):
        self.assertEqual(set(IDP_POSITION_GROUPS), {"DL", "LB", "DB"})


class TestBackboneConstruction(unittest.TestCase):
    def test_builds_per_position_ladders_from_ranked_entries(self):
        # Ordered overall IDP board: DL, LB, DL, DB, LB, DL, DB, LB
        entries = [
            ("DL", "dl1"),
            ("LB", "lb1"),
            ("DL", "dl2"),
            ("DB", "db1"),
            ("LB", "lb2"),
            ("DL", "dl3"),
            ("DB", "db2"),
            ("LB", "lb3"),
        ]
        bb = build_backbone_from_ranked_entries(entries)
        self.assertEqual(bb.ladder_for("DL"), [1, 3, 6])
        self.assertEqual(bb.ladder_for("LB"), [2, 5, 8])
        self.assertEqual(bb.ladder_for("DB"), [4, 7])
        self.assertEqual(bb.depth, 8)
        self.assertFalse(bb.is_empty())

    def test_build_backbone_from_rows_sorts_by_source_value(self):
        rows = [
            {"canonicalName": "lb2", "position": "LB",
             "canonicalSiteValues": {"idpTC": 40}},
            {"canonicalName": "dl1", "position": "DL",
             "canonicalSiteValues": {"idpTC": 90}},
            {"canonicalName": "dl2", "position": "DL",
             "canonicalSiteValues": {"idpTC": 70}},
            {"canonicalName": "lb1", "position": "LB",
             "canonicalSiteValues": {"idpTC": 60}},
            {"canonicalName": "db1", "position": "DB",
             "canonicalSiteValues": {"idpTC": 50}},
            # Row with missing value is skipped
            {"canonicalName": "dl_ghost", "position": "DL",
             "canonicalSiteValues": {"idpTC": None}},
            # Non-IDP row is skipped
            {"canonicalName": "josh", "position": "QB",
             "canonicalSiteValues": {"idpTC": 1000}},
        ]
        bb = build_backbone_from_rows(rows, source_key="idpTC")
        # Desc order: dl1(90), dl2(70), lb1(60), db1(50), lb2(40)
        self.assertEqual(bb.ladder_for("DL"), [1, 2])
        self.assertEqual(bb.ladder_for("LB"), [3, 5])
        self.assertEqual(bb.ladder_for("DB"), [4])
        self.assertEqual(bb.depth, 5)

    def test_empty_rows_builds_empty_backbone(self):
        bb = build_backbone_from_rows([], source_key="idpTC")
        self.assertTrue(bb.is_empty())
        self.assertEqual(bb.depth, 0)

    def test_ladder_for_accepts_lowercase(self):
        bb = IdpBackbone(ladders={"DL": [1, 2, 3]}, depth=3)
        self.assertEqual(bb.ladder_for("dl"), [1, 2, 3])


class TestTranslatePositionRank(unittest.TestCase):
    def test_exact_anchor_maps_to_ladder_entry(self):
        ladder = [2, 5, 9, 14]
        syn, method = translate_position_rank(3, ladder)
        self.assertEqual(syn, 9)
        self.assertEqual(method, TRANSLATION_EXACT)

    def test_first_anchor_is_exact(self):
        syn, method = translate_position_rank(1, [3, 7, 11])
        self.assertEqual(syn, 3)
        self.assertEqual(method, TRANSLATION_EXACT)

    def test_fractional_rank_interpolates_linearly(self):
        ladder = [2, 10]  # DL1 → 2, DL2 → 10
        syn, method = translate_position_rank(1.5, ladder)
        # Midpoint between 2 and 10 = 6 (round half-up = 6)
        self.assertEqual(syn, 6)
        self.assertEqual(method, TRANSLATION_INTERPOLATED)

    def test_extrapolation_beyond_tail_is_monotonic(self):
        ladder = [1, 4, 7, 10, 13]  # constant step = 3
        syn, method = translate_position_rank(6, ladder)
        self.assertEqual(method, TRANSLATION_EXTRAPOLATED)
        self.assertEqual(syn, 16)  # 13 + 3

    def test_extrapolation_never_regresses_past_last_anchor(self):
        # Ladder whose tail step rounds to <= 0; the guardrail should
        # force the synthetic rank strictly past the last anchor.
        ladder = [5, 5]  # Degenerate flat ladder (unlikely but defensive)
        syn, method = translate_position_rank(3, ladder)
        self.assertGreater(syn, 5)
        self.assertEqual(method, TRANSLATION_EXTRAPOLATED)

    def test_empty_ladder_falls_back_to_passthrough(self):
        syn, method = translate_position_rank(7, [])
        self.assertEqual(syn, 7)
        self.assertEqual(method, TRANSLATION_FALLBACK)

    def test_negative_or_zero_rank_clamps_to_first_anchor(self):
        ladder = [4, 9, 14]
        syn, method = translate_position_rank(0, ladder)
        self.assertEqual(method, TRANSLATION_EXACT)
        self.assertEqual(syn, 4)

    def test_single_anchor_ladder_extrapolates_with_defensive_step(self):
        ladder = [3]
        syn, method = translate_position_rank(4, ladder)
        self.assertGreater(syn, 3)
        self.assertEqual(method, TRANSLATION_EXTRAPOLATED)


class TestSharedMarketIdpLadder(unittest.TestCase):
    """The shared-market IDP ladder is the crosswalk that keeps
    IDP-only expert boards (e.g. DLF) from pretending their rank 1 is
    the overall rank 1 of the shared offense+IDP market.

    The ladder is built from the backbone source's combined
    offense+IDP value pool: the i-th entry holds the combined-pool
    rank of the i-th best IDP in the backbone.  These tests pin the
    builder math that ``src/api/data_contract.py`` relies on to
    translate DLF's raw IDP rank through
    ``translate_position_rank(raw_rank, shared_market_idp_ladder)``.
    """

    def test_empty_when_offense_positions_not_supplied(self):
        rows = [
            {"canonicalName": "dl1", "position": "DL",
             "canonicalSiteValues": {"idpTC": 90}},
            {"canonicalName": "qb1", "position": "QB",
             "canonicalSiteValues": {"idpTC": 95}},
        ]
        bb = build_backbone_from_rows(rows, source_key="idpTC")
        self.assertEqual(bb.shared_market_idp_ladder, [])
        self.assertEqual(bb.shared_market_depth, 0)
        self.assertEqual(bb.shared_idp_ladder(), [])

    def test_shared_ladder_reflects_combined_pool_ordering(self):
        # IDPTC combined-pool order: qb(95) > dl1(90) > wr1(85) > lb1(80) > db1(70)
        rows = [
            {"canonicalName": "qb1", "position": "QB",
             "canonicalSiteValues": {"idpTC": 95}},
            {"canonicalName": "dl1", "position": "DL",
             "canonicalSiteValues": {"idpTC": 90}},
            {"canonicalName": "wr1", "position": "WR",
             "canonicalSiteValues": {"idpTC": 85}},
            {"canonicalName": "lb1", "position": "LB",
             "canonicalSiteValues": {"idpTC": 80}},
            {"canonicalName": "db1", "position": "DB",
             "canonicalSiteValues": {"idpTC": 70}},
        ]
        bb = build_backbone_from_rows(
            rows,
            source_key="idpTC",
            offense_positions={"QB", "RB", "WR", "TE", "PICK"},
        )
        # Combined pool has 5 entries, IDPs sit at ranks 2, 4, 5.
        self.assertEqual(bb.shared_market_depth, 5)
        self.assertEqual(bb.shared_market_idp_ladder, [2, 4, 5])
        # The position ladders are also rebuilt but these are built
        # from the IDP-only sort (1..N in IDP order), unchanged.
        self.assertEqual(bb.ladder_for("DL"), [1])
        self.assertEqual(bb.ladder_for("LB"), [2])
        self.assertEqual(bb.ladder_for("DB"), [3])
        self.assertEqual(bb.depth, 3)

    def test_shared_ladder_crosswalks_through_translate_position_rank(self):
        # With the shared-market ladder = [2, 4, 5], translating DLF's
        # raw IDP ranks 1/2/3 must yield 2/4/5 respectively.
        rows = [
            {"canonicalName": "qb1", "position": "QB",
             "canonicalSiteValues": {"idpTC": 95}},
            {"canonicalName": "dl1", "position": "DL",
             "canonicalSiteValues": {"idpTC": 90}},
            {"canonicalName": "wr1", "position": "WR",
             "canonicalSiteValues": {"idpTC": 85}},
            {"canonicalName": "lb1", "position": "LB",
             "canonicalSiteValues": {"idpTC": 80}},
            {"canonicalName": "db1", "position": "DB",
             "canonicalSiteValues": {"idpTC": 70}},
        ]
        bb = build_backbone_from_rows(
            rows,
            source_key="idpTC",
            offense_positions={"QB", "WR"},
        )
        ladder = bb.shared_idp_ladder()
        self.assertEqual(translate_position_rank(1, ladder),
                         (2, TRANSLATION_EXACT))
        self.assertEqual(translate_position_rank(2, ladder),
                         (4, TRANSLATION_EXACT))
        self.assertEqual(translate_position_rank(3, ladder),
                         (5, TRANSLATION_EXACT))
        # Past the ladder extrapolates monotonically.
        syn, method = translate_position_rank(4, ladder)
        self.assertEqual(method, TRANSLATION_EXTRAPOLATED)
        self.assertGreater(syn, 5)

    def test_shared_ladder_is_empty_without_offense_rows(self):
        # Only IDP rows supplied, offense_positions still provided —
        # the combined-pool collapses to the IDP pool, so the ladder
        # is [1,2,3,...].
        rows = [
            {"canonicalName": "dl1", "position": "DL",
             "canonicalSiteValues": {"idpTC": 90}},
            {"canonicalName": "lb1", "position": "LB",
             "canonicalSiteValues": {"idpTC": 80}},
        ]
        bb = build_backbone_from_rows(
            rows,
            source_key="idpTC",
            offense_positions={"QB"},
        )
        self.assertEqual(bb.shared_market_idp_ladder, [1, 2])
        self.assertEqual(bb.shared_market_depth, 2)


class TestCoverageWeight(unittest.TestCase):
    def test_none_depth_returns_declared_weight_unchanged(self):
        self.assertEqual(coverage_weight(1.0, None), 1.0)
        self.assertEqual(coverage_weight(2.0, None), 2.0)

    def test_full_depth_source_is_not_penalized(self):
        self.assertEqual(coverage_weight(1.0, MIN_FULL_COVERAGE_DEPTH), 1.0)
        self.assertEqual(coverage_weight(1.0, MIN_FULL_COVERAGE_DEPTH * 10), 1.0)

    def test_shallow_depth_scales_linearly(self):
        # A top-20 list with declared weight 1.0 contributes 20/60 = 0.333...
        self.assertAlmostEqual(
            coverage_weight(1.0, 20), 20 / MIN_FULL_COVERAGE_DEPTH, places=6
        )

    def test_zero_depth_returns_zero_weight(self):
        self.assertEqual(coverage_weight(1.0, 0), 0.0)

    def test_negative_declared_weight_clamps_to_zero(self):
        self.assertEqual(coverage_weight(-1.0, 60), 0.0)

    def test_custom_min_depth(self):
        # With min_full_depth=30 a depth-15 list yields half the declared weight.
        self.assertAlmostEqual(
            coverage_weight(1.0, 15, min_full_depth=30), 0.5, places=6
        )


if __name__ == "__main__":
    unittest.main()
