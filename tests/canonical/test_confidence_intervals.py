"""Tests for the source-consensus value-band engine.

These pin:
  * The weighted-quantile math.
  * The "bracket contains canonical" invariant.
  * The three fallback branches.
  * The stamp helper's non-destructiveness.
"""
from __future__ import annotations

from src.canonical import confidence_intervals as ci


def _rank_to_value():
    # Simple monotonic: rank 1 = 10000, rank 500 = 0.
    return {r: 10000 - (r - 1) * 20 for r in range(1, 501)}


def test_weighted_percentile_matches_known_values():
    vals = [10.0, 20.0, 30.0, 40.0, 50.0]
    weights = [1.0] * 5
    # p50 of evenly-spaced data ≈ 30 (type-7 interpolation).
    p50 = ci._weighted_percentile(vals, weights, 50.0)  # noqa: SLF001
    assert 29.0 <= p50 <= 31.0
    # p10 at or near 10; p90 at or near 50.
    assert ci._weighted_percentile(vals, weights, 10.0) <= 15  # noqa: SLF001
    assert ci._weighted_percentile(vals, weights, 90.0) >= 45  # noqa: SLF001


def test_weighted_percentile_with_single_value():
    assert ci._weighted_percentile([42.0], [1.0], 50.0) == 42.0  # noqa: SLF001


def test_empty_values_return_zero():
    assert ci._weighted_percentile([], [], 50.0) == 0.0  # noqa: SLF001


def test_bracket_method_when_sources_agree():
    """All 6 sources rank the player near #10 → 9820 area →
    band should bracket the canonical value."""
    source_ranks = {s: 10 for s in ["ktc", "dlf", "fc", "dd", "idp", "dn"]}
    band = ci.compute_value_band(
        canonical_value=9820.0,
        source_ranks=source_ranks,
        rank_to_value=_rank_to_value(),
    )
    assert band.method == "bracket"
    assert band.p10 <= 9820 <= band.p90
    assert band.source_count == 6


def test_insufficient_sources_uses_15pct_fallback():
    band = ci.compute_value_band(
        canonical_value=5000.0,
        source_ranks={"ktc": 100},
        rank_to_value=_rank_to_value(),
    )
    assert band.method == "insufficient_sources"
    assert band.p50 == 5000.0
    assert band.p10 == 5000 * 0.85
    assert band.p90 == 5000 * 1.15


def test_fallback_narrow_when_canonical_out_of_bracket():
    """Sources all say the player is a 500-value pick; canonical
    says 9000.  The raw percentile band would sit near 500 and
    NOT contain 9000 — so the fallback recenters on 9000 with a
    20% band."""
    source_ranks = {s: 400 for s in ["ktc", "dlf", "fc", "dd", "idp", "dn"]}
    band = ci.compute_value_band(
        canonical_value=9000.0,
        source_ranks=source_ranks,
        rank_to_value=_rank_to_value(),
    )
    assert band.method == "fallback_narrow"
    assert band.p10 == 9000 * 0.80
    assert band.p90 == 9000 * 1.20
    assert band.p50 == 9000.0


def test_none_source_ranks_safe():
    band = ci.compute_value_band(canonical_value=1000.0, source_ranks=None)
    assert band.method == "insufficient_sources"
    assert band.p50 == 1000.0


def test_zero_canonical_value_is_safe():
    # Picks with canonical_value=0 should not divide-by-zero.
    band = ci.compute_value_band(canonical_value=0.0, source_ranks={})
    assert band.p10 == 0
    assert band.p50 == 0


def test_band_monotonic_across_p10_p50_p90():
    """For any valid bracket, p10 ≤ p50 ≤ p90."""
    ranks = [10, 15, 20, 25, 30, 35, 40, 50]
    source_ranks = {f"src{i}": r for i, r in enumerate(ranks)}
    band = ci.compute_value_band(
        canonical_value=9700.0,
        source_ranks=source_ranks,
        rank_to_value=_rank_to_value(),
    )
    assert band.p10 <= band.p50 <= band.p90


def test_stamp_bands_on_players_adds_field_without_mutation():
    players = [
        {
            "name": "Stub A",
            "rankDerivedValue": 8000,
            "sourceRanks": {"a": 10, "b": 12, "c": 11, "d": 13, "e": 14},
        },
        {
            "name": "Stub B",
            "rankDerivedValue": 1000,
            "sourceRanks": {},
        },
    ]
    out = ci.stamp_bands_on_players(players, rank_to_value=_rank_to_value())
    assert out is not players
    assert out[0]["valueBand"]["method"] in ("bracket", "fallback_narrow", "insufficient_sources")
    assert out[1]["valueBand"]["method"] == "insufficient_sources"
    # Input is unchanged.
    assert "valueBand" not in players[0]
    assert "valueBand" not in players[1]


def test_stamp_tolerates_non_dict_entries():
    players = [{"name": "A", "rankDerivedValue": 1000, "sourceRanks": {}}, None, "garbage"]
    out = ci.stamp_bands_on_players(players)
    assert len(out) == 3
    assert out[0]["valueBand"] is not None


def test_to_dict_fields_rounded():
    band = ci.compute_value_band(
        canonical_value=1234.567,
        source_ranks={},
    )
    d = band.to_dict()
    # Rounding to 1 decimal.
    assert d["p50"] == 1234.6
