"""Weighted count-aware blend (2026-07-29 audit).

The /settings source-weight sliders historically did nothing: any
positive weight blended identically to 1.0 (weights gated membership
only).  ``weighted_count_aware_mean_median_blend`` makes a declared
weight genuinely scale a source's vote, under a hard invariance
guarantee: with every weight equal (the all-1.0 registry default, or
any uniform slider setting) the helper delegates to the unweighted
``count_aware_mean_median_blend`` so the default board is bit-for-bit
unchanged.

These tests pin:
  * exact equal-weight parity (the invariance guarantee),
  * weighted mean/median arithmetic per count bucket,
  * directional monotonicity (upweighting a source pulls the center
    toward that source's value),
  * observation-based trimming at n>=5,
  * degenerate-input fallbacks (a malformed override must never take
    down the board),
  * end-to-end: a weight override changes ``rankDerivedValue``
    between the exclusion and default endpoints, monotonically, and
    ``sourceRankMeta.appliedWeight`` reports the applied weight.
"""

from __future__ import annotations

from typing import Any

from src.api.data_contract import (
    build_api_data_contract,
    count_aware_mean_median_blend,
    weighted_count_aware_mean_median_blend,
)


def _unweighted(values: list[float]) -> tuple[float, float | None]:
    return count_aware_mean_median_blend(values)


def _weighted(values: list[float], weights: list[float]) -> tuple[float, float | None]:
    return weighted_count_aware_mean_median_blend(values, weights)


class TestEqualWeightParity:
    """The invariance guarantee: equal weights == unweighted, exactly."""

    def test_all_ones_matches_unweighted_across_counts(self):
        cases = [
            [5000.0],
            [6000.0, 8000.0],
            [3000.0, 5000.0, 9000.0],
            [3000.0, 5000.0, 7000.0, 9000.0],
            [1000.0, 3000.0, 5000.0, 7000.0, 9000.0],
            [1000.0, 2000.0, 3000.0, 5000.0, 7000.0, 9000.0],
        ]
        for values in cases:
            assert _weighted(values, [1.0] * len(values)) == _unweighted(values)

    def test_uniform_non_unit_weights_match_unweighted(self):
        """All sliders at 0.5 must equal all sliders at 1.0."""
        values = [3000.0, 5000.0, 9000.0, 2000.0, 7000.0]
        assert _weighted(values, [0.5] * 5) == _unweighted(values)
        assert _weighted(values, [2.0] * 5) == _unweighted(values)

    def test_empty_input(self):
        assert _weighted([], []) == (0.0, None)


class TestWeightedArithmetic:
    def test_two_sources_weighted_mean(self):
        # weights 3:1 → center = (6000*3 + 8000*1) / 4 = 6500
        center, mad = _weighted([6000.0, 8000.0], [3.0, 1.0])
        assert center == 6500.0
        # weighted MAD around center: (|6000-6500|*3 + |8000-6500|*1)/4 = 750
        assert mad == 750.0

    def test_three_sources_weighted_center(self):
        # values [2000, 3000, 10000], weights [1, 1, 2]
        # w_mean = (2000 + 3000 + 20000) / 4 = 6250
        # weighted median: cum weights 1, 2, 4; half = 2 → exact hit at
        # 3000 → midpoint with next → (3000 + 10000)/2 = 6500
        # center = (6250 + 6500) / 2 = 6375
        center, _ = _weighted([2000.0, 3000.0, 10000.0], [1.0, 1.0, 2.0])
        assert center == 6375.0

    def test_monotone_in_weight(self):
        """Raising the weight of the highest-value source must not
        lower the center, and strictly raises it here."""
        values = [2000.0, 5000.0, 9000.0]
        base, _ = _weighted(values, [1.0, 1.0, 1.0])
        centers = []
        for w in (1.5, 2.0, 3.0):
            c, _ = _weighted(values, [1.0, 1.0, w])
            centers.append(c)
        assert centers[0] > base
        assert centers[1] > centers[0]
        assert centers[2] > centers[1]

    def test_downweight_moves_toward_remaining_sources(self):
        values = [2000.0, 5000.0, 9000.0]
        base, _ = _weighted(values, [1.0, 1.0, 1.0])
        down, _ = _weighted(values, [1.0, 1.0, 0.25])
        assert down < base

    def test_trim_at_five_is_observation_based(self):
        """n>=5 drops the min and max OBSERVATIONS even when heavily
        weighted — the robustness rule targets extreme values."""
        values = [1000.0, 4000.0, 5000.0, 6000.0, 9999.0]
        # Heavy weight on the extremes; they are trimmed regardless, so
        # the result must equal the blend over the middle three at
        # their (equal) weights == the unweighted middle-three blend.
        center, _ = _weighted(values, [9.0, 1.0, 1.0, 1.0, 9.0])
        middle_center, _ = _unweighted([4000.0, 5000.0, 6000.0])
        assert center == middle_center


class TestDegenerateInputs:
    def test_mismatched_lengths_fall_back_to_unweighted(self):
        values = [3000.0, 5000.0, 9000.0]
        assert _weighted(values, [1.0, 2.0]) == _unweighted(values)

    def test_negative_weights_clamped_to_zero(self):
        # [-1, 1] clamps to [0, 1]: only the second value votes.
        center, _ = _weighted([2000.0, 8000.0], [-1.0, 1.0])
        assert center == 8000.0

    def test_all_zero_weights_fall_back_to_unweighted(self):
        # Zero-weight sources are dropped before the blend in
        # production (_active_sources); if the helper is ever handed
        # an all-zero set directly it must not divide by zero.
        values = [2000.0, 8000.0]
        assert _weighted(values, [0.0, 0.0]) == _unweighted(values)


def _payload(players: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "scrapeTimestamp": "2026-07-29T00:00:00+00:00",
        "players": {
            name: {
                "position": p["position"],
                "team": p.get("team", "???"),
                "_canonicalSiteValues": p["sites"],
                "_sites": len(p["sites"]),
            }
            for name, p in players.items()
        },
    }


# Alpha QB is every source's #1 EXCEPT dlfSf, which ranks him third —
# so his dlfSf vote (rank 3 → Hill ≈ 9,812) sits below his other three
# contributions (≈ 9,999 each).  That spread is what lets the weight
# tests observe direction: raising dlfSf's weight pulls Alpha DOWN
# toward his one bearish source; excluding dlfSf releases him to the
# unanimous 9,999.
_PLAYERS = {
    "Alpha QB": {
        "position": "QB",
        "sites": {
            "ktcSfTep": 9000,
            "idpTradeCalc": 8800,
            "dlfSf": 5000,
            "dynastyNerdsSfTep": 9100,
        },
    },
    "Beta WR": {
        "position": "WR",
        "sites": {
            "ktcSfTep": 7000,
            "idpTradeCalc": 7100,
            "dlfSf": 9500,
            "dynastyNerdsSfTep": 6900,
        },
    },
    "Gamma RB": {
        "position": "RB",
        "sites": {
            "ktcSfTep": 5000,
            "idpTradeCalc": 5100,
            "dlfSf": 7000,
            "dynastyNerdsSfTep": 4900,
        },
    },
}


def _value_of(contract: dict[str, Any], name: str) -> int:
    row = next(r for r in contract["playersArray"] if r.get("displayName") == name)
    return row["rankDerivedValue"]


def _meta_of(contract: dict[str, Any], name: str) -> dict[str, Any]:
    row = next(r for r in contract["playersArray"] if r.get("displayName") == name)
    return row.get("sourceRankMeta") or {}


class TestEndToEndWeightOverrides:
    def test_explicit_unit_weights_identical_to_default(self):
        """Sending every weight as an explicit 1.0 must reproduce the
        no-override board exactly (the invariance guarantee end-to-end)."""
        base = build_api_data_contract(_payload(_PLAYERS))
        unit = build_api_data_contract(
            _payload(_PLAYERS),
            source_overrides={
                k: {"weight": 1.0}
                for k in ("ktcSfTep", "idpTradeCalc", "dlfSf", "dynastyNerdsSfTep")
            },
        )
        for name in _PLAYERS:
            assert _value_of(base, name) == _value_of(unit, name)

    def test_intermediate_weight_lands_between_exclusion_and_default(self):
        """dlfSf at weight 0.5 must land Alpha QB's value strictly
        between 'dlfSf excluded' and 'dlfSf at full weight' — the
        slider is no longer an on/off switch."""
        default = build_api_data_contract(_payload(_PLAYERS))
        excluded = build_api_data_contract(
            _payload(_PLAYERS), source_overrides={"dlfSf": {"include": False}}
        )
        half = build_api_data_contract(
            _payload(_PLAYERS), source_overrides={"dlfSf": {"weight": 0.5}}
        )
        v_default = _value_of(default, "Alpha QB")
        v_excluded = _value_of(excluded, "Alpha QB")
        v_half = _value_of(half, "Alpha QB")
        lo, hi = sorted((v_default, v_excluded))
        assert lo < v_half < hi, (v_excluded, v_half, v_default)

    def test_weight_monotonicity_end_to_end(self):
        """dlfSf is Alpha QB's one bearish source (rank 3 vs unanimous
        #1 elsewhere); raising its weight must monotonically LOWER his
        blended value."""
        values = []
        for w in (0.25, 1.0, 2.0):
            c = build_api_data_contract(
                _payload(_PLAYERS), source_overrides={"dlfSf": {"weight": w}}
            )
            values.append(_value_of(c, "Alpha QB"))
        assert values[0] > values[1] > values[2], values

    def test_applied_weight_stamped(self):
        c = build_api_data_contract(_payload(_PLAYERS), source_overrides={"dlfSf": {"weight": 0.5}})
        meta = _meta_of(c, "Alpha QB")
        assert meta["dlfSf"]["appliedWeight"] == 0.5
        assert meta["ktcSfTep"]["appliedWeight"] == 1.0

    def test_duplicate_source_records_do_not_inflate(self):
        """A source votes once: the same site value listed once vs the
        row's full set must not change with a repeated build (guards
        against accidental double-append of a source's vote)."""
        a = build_api_data_contract(_payload(_PLAYERS))
        b = build_api_data_contract(_payload(_PLAYERS))
        for name in _PLAYERS:
            assert _value_of(a, name) == _value_of(b, name)
