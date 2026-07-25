"""Trimmed percentile spread + depth-aware disagreement thresholds.

Pins the 2026-07-25 caution-saturation fix (see the
``_PERCENTILE_SPREAD_TRIM_MIN_N`` and ``_DISAGREEMENT_BASE_THRESHOLD``
constant docstrings in ``src/api/data_contract.py``):

1. ``_percentile_rank_spread`` ignores the single most extreme
   percentile on each side once 5+ sources contribute, so one
   straggler source cannot flag an otherwise-tight consensus.  Below
   5 sources the untrimmed max-minus-min still applies.
2. ``_disagreement_depth_allowance`` raises the caution/anomaly
   thresholds linearly with the player's consensus percentile
   (capped), so routine deep-board disagreement stops saturating the
   flags while top-of-board splits still fire.

Before the fix, 72% of the top-200 board carried "wide disagreement"
and 41% carried ``suspicious_disagreement`` — a caution firing on
three of four rows carries no information.  After: 4% / 3%, and the
survivors are genuine multi-source splits.
"""

from __future__ import annotations

import unittest

from src.api.data_contract import (
    _DISAGREEMENT_DEPTH_ALLOWANCE_CAP,
    _compute_anomaly_flags,
    _disagreement_depth_allowance,
    _percentile_rank_spread,
)


def _make_sources(raw_ranks: dict[str, int], depth: int = 100):
    """Build (source_ranks, source_meta, pool_sizes) for a uniform pool."""
    source_ranks = dict(raw_ranks)
    source_meta = {k: {"rawRank": v} for k, v in raw_ranks.items()}
    pool_sizes = {k: depth for k in raw_ranks}
    return source_ranks, source_meta, pool_sizes


class TestTrimmedPercentileSpread(unittest.TestCase):
    def test_single_straggler_is_trimmed_at_five_sources(self):
        # Four sources in tight agreement (ranks 10-13 of 100) plus one
        # straggler at 60.  Untrimmed spread would be 0.50; trimmed
        # ignores the straggler (and the low extreme) leaving the
        # tight core.
        ranks, meta, pools = _make_sources({"a": 10, "b": 11, "c": 12, "d": 13, "e": 60})
        spread = _percentile_rank_spread(ranks, meta, pools)
        self.assertIsNotNone(spread)
        # sorted percentiles: .10 .11 .12 .13 .60 → trimmed = .13 - .11
        self.assertAlmostEqual(spread, 0.02, places=6)

    def test_untrimmed_below_five_sources(self):
        # With four sources the straggler still counts — trimming only
        # kicks in at _PERCENTILE_SPREAD_TRIM_MIN_N (5).
        ranks, meta, pools = _make_sources({"a": 10, "b": 11, "c": 12, "d": 60})
        spread = _percentile_rank_spread(ranks, meta, pools)
        self.assertAlmostEqual(spread, 0.50, places=6)

    def test_genuine_split_survives_trimming(self):
        # Two sources on each wing — trimming one per side must still
        # leave a wide spread.  This is the true-positive case the
        # caution exists for.
        ranks, meta, pools = _make_sources({"a": 5, "b": 8, "c": 50, "d": 55, "e": 60, "f": 65})
        spread = _percentile_rank_spread(ranks, meta, pools)
        # sorted: .05 .08 .50 .55 .60 .65 → trimmed = .60 - .08 = .52
        self.assertAlmostEqual(spread, 0.52, places=6)


class TestDepthAllowance(unittest.TestCase):
    def test_none_percentile_means_zero_allowance(self):
        self.assertEqual(_disagreement_depth_allowance(None), 0.0)

    def test_linear_in_consensus_percentile(self):
        self.assertAlmostEqual(_disagreement_depth_allowance(0.05), 0.05)
        self.assertAlmostEqual(_disagreement_depth_allowance(0.20), 0.20)

    def test_capped(self):
        self.assertAlmostEqual(
            _disagreement_depth_allowance(0.90), _DISAGREEMENT_DEPTH_ALLOWANCE_CAP
        )

    def test_negative_clamped_to_zero(self):
        self.assertEqual(_disagreement_depth_allowance(-0.3), 0.0)


class TestAnomalyFlagAllowance(unittest.TestCase):
    def _flags(self, percentile_spread: float, allowance: float) -> list[str]:
        return _compute_anomaly_flags(
            name="Test Player",
            position="WR",
            asset_class="offense",
            source_ranks={"a": 10, "b": 20},
            rank_derived_value=5000,
            canonical_sites={},
            percentile_spread=percentile_spread,
            disagreement_allowance=allowance,
        )

    def test_deep_board_spread_within_allowance_not_flagged(self):
        # 0.30 spread would flag at the 0.20 base, but a deep player
        # with a 0.15 allowance is inside 0.35 — normal for its depth.
        self.assertNotIn("suspicious_disagreement", self._flags(0.30, 0.15))

    def test_same_spread_flags_at_top_of_board(self):
        # The identical spread with zero allowance (top of board) is
        # genuinely suspicious.
        self.assertIn("suspicious_disagreement", self._flags(0.30, 0.0))

    def test_extreme_spread_flags_despite_allowance(self):
        self.assertIn("suspicious_disagreement", self._flags(0.60, 0.25))


class TestRankSignalEncodingGuard(unittest.TestCase):
    """Audit F-3 structural guard: the rank-signal key set is derivable
    and the synthetic encoding stays clearly distinguishable from real
    0-9999 values, so arithmetic consumers of ``canonicalSiteValues``
    have an authoritative set to guard against."""

    def test_rank_signal_keys_match_csv_signals(self):
        from src.api.data_contract import (
            _SOURCE_CSV_PATHS,
            _RANKING_SOURCES,
            rank_signal_source_keys,
        )

        voting = {str(s.get("key") or "") for s in _RANKING_SOURCES}
        expected = {
            key
            for key, cfg in _SOURCE_CSV_PATHS.items()
            if key in voting
            and isinstance(cfg, dict)
            and str(cfg.get("signal") or "value").lower() == "rank"
        }
        self.assertEqual(rank_signal_source_keys(), frozenset(expected))
        # Sanity: the two value-direct sources are never in the set.
        self.assertNotIn("ktcSfTep", rank_signal_source_keys())
        self.assertNotIn("idpTradeCalc", rank_signal_source_keys())

    def test_synthetic_encoding_cannot_collide_with_real_values(self):
        # The encoding ``(10000 − rank) × 100`` stays far above the
        # 0-9999 value scale for every realistic rank — the deepest
        # pool any source ships is ~900 rows, and even a hypothetical
        # 2,000-deep source encodes to 800,000.  (It is NOT
        # structurally collision-proof: rank ≥ 9,901 would encode
        # below 9,999 — this pin exists so a future ultra-deep source
        # forces a conscious decision instead of a silent collision.)
        from src.api.data_contract import _RANK_TO_SYNTHETIC_VALUE_OFFSET

        deepest_plausible_rank = 2000
        worst = (_RANK_TO_SYNTHETIC_VALUE_OFFSET * 100) - (deepest_plausible_rank * 100)
        self.assertGreater(worst, 9999)


class TestAnchorKeySets(unittest.TestCase):
    """PR #530 review: anchor membership must require a positive
    effective weight — an enabled-but-weight-0 source cannot anchor."""

    def _srcs(self, ktc_weight=1.0, idptc_weight=1.0):
        return [
            {"key": "idpTradeCalc", "is_cross_market": True, "weight": idptc_weight},
            {"key": "ktcSfTep", "is_cross_market": False, "weight": ktc_weight},
            {"key": "dlfSf", "is_cross_market": False, "weight": 1.0},
        ]

    def test_default_membership(self):
        from src.api.data_contract import _anchor_key_sets

        cross, pick = _anchor_key_sets(self._srcs())
        self.assertEqual(cross, {"idpTradeCalc"})
        self.assertEqual(pick, {"idpTradeCalc", "ktcSfTep"})

    def test_zero_weight_ktc_never_anchors_picks(self):
        from src.api.data_contract import _anchor_key_sets

        cross, pick = _anchor_key_sets(self._srcs(ktc_weight=0.0))
        self.assertEqual(pick, {"idpTradeCalc"})
        self.assertNotIn("ktcSfTep", pick)

    def test_zero_weight_cross_market_never_anchors(self):
        from src.api.data_contract import _anchor_key_sets

        cross, pick = _anchor_key_sets(self._srcs(idptc_weight=0.0))
        self.assertEqual(cross, set())
        self.assertEqual(pick, {"ktcSfTep"})


class TestActiveSourcesWeightGate(unittest.TestCase):
    """PR #530 review: a non-positive weight override must drop the
    source from voting entirely — the blend is unweighted, so
    "enabled with weight 0" can only coherently mean "no vote"."""

    def test_zero_weight_override_drops_source(self):
        from src.api.data_contract import _active_sources

        out = _active_sources({"ktcSfTep": {"weight": 0}})
        self.assertNotIn("ktcSfTep", {s.get("key") for s in out})

    def test_positive_weight_override_retained_with_new_weight(self):
        from src.api.data_contract import _active_sources

        out = _active_sources({"ktcSfTep": {"weight": 2.5}})
        ktc = next(s for s in out if s.get("key") == "ktcSfTep")
        self.assertEqual(float(ktc["weight"]), 2.5)

    def test_no_overrides_returns_full_registry(self):
        from src.api.data_contract import _RANKING_SOURCES, _active_sources

        self.assertEqual(len(_active_sources(None)), len(_RANKING_SOURCES))


if __name__ == "__main__":
    unittest.main()
