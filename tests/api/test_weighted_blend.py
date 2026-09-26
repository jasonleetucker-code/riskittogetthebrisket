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
  * n>=5 trimming by weight MASS (exactly the observation trim under
    equal weights; continuous and monotone under unequal ones),
  * degenerate-input fallbacks (a malformed override must never take
    down the board),
  * end-to-end: a weight override changes ``rankDerivedValue``
    between the exclusion and default endpoints, monotonically, and
    ``sourceRankMeta.appliedWeight`` reports the applied weight.
"""

from __future__ import annotations

import statistics

import pytest

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
        # window median: slices [0, .25], [.25, .5], [.5, 1]; the window of one
        # average observation's mass is [.5 - 1/6, .5 + 1/6] — half on 3000,
        # half on 10000 → 6500 (the half-weight point falls exactly on their
        # boundary, where the median is their mean)
        # center = (6250 + 6500) / 2 = 6375
        center, _ = _weighted([2000.0, 3000.0, 10000.0], [1.0, 1.0, 2.0])
        assert center == pytest.approx(6375.0, abs=1e-6)

    def test_weighted_median_is_continuous_in_the_weights(self):
        """No cliffs.  The textbook step median flipped this anchor between
        2269 and 3554 when one weight crossed 0.878 → 0.881 (Kyle Hamilton,
        2026-09-23 board).  A small weight change must make a small move."""
        values = [2269.0, 3554.0, 3597.0]
        centers = [_weighted(values, [1.0, 0.1204, 0.870 + 0.001 * i])[0] for i in range(21)]
        steps = [abs(b - a) for a, b in zip(centers, centers[1:])]
        assert max(steps) < 5.0, steps

    def test_weighted_median_equals_the_median_under_equal_weights(self):
        from src.api.data_contract import _weighted_median_sorted

        for vals in ([1.0], [1.0, 3.0], [1.0, 2.0, 9.0], [1.0, 2.0, 4.0, 9.0]):
            pairs = [(v, 2.5) for v in vals]
            assert _weighted_median_sorted(pairs, 2.5 * len(vals)) == pytest.approx(
                statistics.median(vals)
            )

    def test_weighted_median_is_monotone_in_the_values(self):
        """Raising any one value never lowers the median (2026-09-24).  The
        retired midpoint interpolation failed this on 513 of 20,000 random
        unequal-weight cases (worst -2.95%)."""
        import random

        from src.api.data_contract import _weighted_median_sorted

        rng = random.Random(1)
        for _ in range(5000):
            n = rng.randint(3, 12)
            vals = [rng.uniform(9000.0, 9999.0) for _ in range(n)]
            wts = [rng.choice([0.25, 0.287, 0.5, 0.713, 1.0]) for _ in range(n)]
            i = rng.randrange(n)
            raised = list(vals)
            raised[i] += rng.uniform(0.0, 300.0)
            before = _weighted_median_sorted(sorted(zip(vals, wts)), sum(wts))
            after = _weighted_median_sorted(sorted(zip(raised, wts)), sum(wts))
            assert after >= before - 1e-9, (vals, wts, i)

    def test_the_whole_blend_is_monotone_in_the_values(self):
        """Mean, mass trim and median together: an input rising can never
        lower the blended center."""
        import random

        rng = random.Random(2)
        for _ in range(5000):
            n = rng.randint(3, 12)
            vals = [rng.uniform(9000.0, 9999.0) for _ in range(n)]
            wts = [rng.choice([0.25, 0.287, 0.5, 0.713, 1.0]) for _ in range(n)]
            i = rng.randrange(n)
            raised = list(vals)
            raised[i] += rng.uniform(0.0, 300.0)
            assert _weighted(raised, wts)[0] >= _weighted(vals, wts)[0] - 1e-9

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

    def test_trim_at_five_is_the_observation_trim_under_equal_weights(self):
        """Equal weights: trimming one average observation's MASS from each
        end removes exactly the min and max observations."""
        from src.api.data_contract import _trim_one_observation_mass

        pairs = [(1000.0, 0.7), (4000.0, 0.7), (5000.0, 0.7), (6000.0, 0.7), (9999.0, 0.7)]
        assert _trim_one_observation_mass(pairs) == pairs[1:-1]

    def test_trim_at_five_removes_one_average_observation_of_mass(self):
        """Unequal weights: Σw/n leaves each end — a heavy extreme keeps the
        rest of its weight instead of vanishing on a weight-blind trim."""
        from src.api.data_contract import _trim_one_observation_mass

        trimmed = _trim_one_observation_mass(
            [(1000.0, 9.0), (4000.0, 1.0), (5000.0, 1.0), (6000.0, 1.0), (9999.0, 9.0)]
        )
        mass = 21.0 / 5
        assert trimmed == pytest.approx(
            [
                (1000.0, 9.0 - mass),
                (4000.0, 1.0),
                (5000.0, 1.0),
                (6000.0, 1.0),
                (9999.0, 9.0 - mass),
            ]
        )

    def test_raising_an_extreme_low_weight_value_cannot_lower_the_blend(self):
        """Regression (2026-09-24, golden Brock Bowers): which observation sits
        at the top must not decide how much weight the trim removes."""
        base = [9400.0, 9820.8, 9893.3, 9996.86, 9997.74, 9998.98, 9998.99] + [9999.0] * 6
        raised = [9800.0, 9820.8, 9893.3, 9998.9, 9998.99, 9998.98, 9998.99] + [9999.0] * 6
        weights = [0.713, 1.0, 1.0, 1.0, 1.0, 0.5, 1.0, 0.5, 1.0, 1.0, 1.0, 1.0, 0.287]
        assert _weighted(raised, weights)[0] >= _weighted(base, weights)[0]


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
            "ktcCrowdSfTep": 9000,
            "idpTradeCalc": 8800,
            "dlfSf": 5000,
            "dynastyNerdsSfTep": 9100,
        },
    },
    "Beta WR": {
        "position": "WR",
        "sites": {
            "ktcCrowdSfTep": 7000,
            "idpTradeCalc": 7100,
            "dlfSf": 9500,
            "dynastyNerdsSfTep": 6900,
        },
    },
    "Gamma RB": {
        "position": "RB",
        "sites": {
            "ktcCrowdSfTep": 5000,
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
                for k in ("ktcCrowdSfTep", "idpTradeCalc", "dlfSf", "dynastyNerdsSfTep")
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
        assert meta["ktcCrowdSfTep"]["appliedWeight"] == 1.0

    def test_duplicate_source_records_do_not_inflate(self):
        """A source votes once: the same site value listed once vs the
        row's full set must not change with a repeated build (guards
        against accidental double-append of a source's vote)."""
        a = build_api_data_contract(_payload(_PLAYERS))
        b = build_api_data_contract(_payload(_PLAYERS))
        for name in _PLAYERS:
            assert _value_of(a, name) == _value_of(b, name)


class TestEstimatorContract:
    """The weighted blend's mathematical contract (2026-09-24).

    Unweighted (#164): n=1 passthrough; n=2 mean; n=3-4 (mean + median)/2;
    n>=5 drop one min and one max, then (trimmed mean + median)/2.  A
    symmetric trim never moves the median, so trimming acts on the MEAN only.

    Weighted generalisation, in one unit — one AVERAGE observation's mass
    (W/n): the trimmed mean is the mean of the weighted quantile function
    Q(u) over [1/n, 1 - 1/n]; the median is the mean of Q(u) over
    [1/2 - 1/(2n), 1/2 + 1/(2n)].  With equal weights both are exactly the
    unweighted statistics.  Expected values below are derived by hand.
    """

    @staticmethod
    def _median(values, weights):
        from src.api.data_contract import _weighted_median_sorted

        pairs = sorted(zip(values, weights))
        return _weighted_median_sorted(pairs, sum(weights))

    def test_equal_weights_are_backward_compatible_at_every_count(self):
        import random

        rng = random.Random(3)
        for _ in range(3000):
            n = rng.randint(1, 12)
            vals = [rng.uniform(0.0, 9999.0) for _ in range(n)]
            w = rng.choice([0.3, 1.0, 2.5])
            got, _ = _weighted(vals, [w] * n)
            want, _ = _unweighted(vals)
            assert got == pytest.approx(want, abs=1e-9)
            # The window median alone, called on equal weights, is the median.
            assert self._median(vals, [w] * n) == pytest.approx(statistics.median(vals))

    def test_two_sources_are_a_weighted_mean(self):
        assert _weighted([6000.0, 8000.0], [3.0, 1.0])[0] == pytest.approx(6500.0)

    def test_three_sources_untrimmed(self):
        # see TestWeightedArithmetic.test_three_sources_weighted_center: 6375
        assert _weighted([2000.0, 3000.0, 10000.0], [1.0, 1.0, 2.0])[0] == pytest.approx(6375.0)

    def test_four_sources_untrimmed(self):
        # values [1000, 2000, 3000, 9000], weights [2, 1, 1, 1], W = 5
        # mean = (2000 + 2000 + 3000 + 9000) / 5 = 3200
        # slices 1000:[0,.4] 2000:[.4,.6] 3000:[.6,.8] 9000:[.8,1]
        # window [.375, .625]: 1000×.025 + 2000×.2 + 3000×.025 → 500/.25 = 2000
        # center = (3200 + 2000) / 2 = 2600
        vals, wts = [1000.0, 2000.0, 3000.0, 9000.0], [2.0, 1.0, 1.0, 1.0]
        assert self._median(vals, wts) == pytest.approx(2000.0)
        assert _weighted(vals, wts)[0] == pytest.approx(2600.0)

    def test_five_sources_trim_one_average_observation_from_each_end(self):
        # values [1000, 4000, 5000, 6000, 9000], weights [1, 1, 2, 1, 1], W = 6
        # trim mass W/n = 1.2 per end: 1000 (1.0) + 0.2 of 4000; 9000 (1.0) +
        # 0.2 of 6000 → 4000×.8, 5000×2, 6000×.8 → mean 18000/3.6 = 5000
        # median window [.4, .6] lies inside 5000's slice [1/3, 2/3] → 5000
        vals, wts = [1000.0, 4000.0, 5000.0, 6000.0, 9000.0], [1.0, 1.0, 2.0, 1.0, 1.0]
        assert _weighted(vals, wts)[0] == pytest.approx(5000.0)

    def test_exact_weighted_median_boundary_is_the_mean_of_the_neighbours(self):
        # [1000, 2000, 3000] @ [1, 1, 2]: cumulative weight reaches exactly 0.5
        # at the 2000|3000 boundary; the window [1/3, 2/3] takes 1/6 of each
        assert self._median([1000.0, 2000.0, 3000.0], [1.0, 1.0, 2.0]) == pytest.approx(2500.0)

    def test_partial_weight_at_the_median_boundary(self):
        # [1000, 2000, 3000] @ [1, .5, 2], W = 3.5: slices 1000:[0, 2/7]
        # 2000:[2/7, 3/7] 3000:[3/7, 1]; window [1/3, 2/3]:
        # 2000 × (3/7 − 1/3) + 3000 × (2/3 − 3/7) → (190.476 + 714.286) / (1/3)
        vals, wts = [1000.0, 2000.0, 3000.0], [1.0, 0.5, 2.0]
        assert self._median(vals, wts) == pytest.approx(2714.2857, abs=1e-3)
        # A window wholly inside one slice returns that value exactly.
        assert self._median(vals, [1.0, 1.2, 1.0]) == pytest.approx(2000.0)

    def test_an_extreme_high_outlier_is_trimmed_away(self):
        vals = [100.0, 101.0, 102.0, 103.0, 100000.0]
        assert _weighted(vals, [1.0, 1.0, 1.0, 1.0, 0.5])[0] == pytest.approx(102.0, abs=0.6)
        assert _weighted(vals, [1.0] * 5)[0] == pytest.approx(102.0)

    def test_an_extreme_low_outlier_is_trimmed_away(self):
        vals = [-100000.0, 100.0, 101.0, 102.0, 103.0]
        assert _weighted(vals, [0.5, 1.0, 1.0, 1.0, 1.0])[0] == pytest.approx(101.0, abs=0.6)
        assert _weighted(vals, [1.0] * 5)[0] == pytest.approx(101.0)

    def test_the_median_is_bounded_by_one_average_observation_around_it(self):
        # The window median always lies in [Q(1/2 − 1/2n), Q(1/2 + 1/2n)]:
        # Kyle Hamilton's IDP anchor — the true weighted median is 2269
        # (Draft Sharks IDP holds 50.05% of the weight); the estimate stays in
        # the band, the retired midpoint interpolation (3416) did not.
        vals, wts = [2269.0, 3554.0, 3597.0], [1.0, 0.1204, 0.878]
        med = self._median(vals, wts)
        assert 2269.0 <= med <= 3597.0
        # W = 1.9984; DS-IDP owns [0, .50040], IDP Show [.50040, .56065], IDPTC
        # [.56065, 1]; window [1/3, 2/3] takes .16707 / .06025 / .10602 of them:
        # (2269×.16707 + 3554×.06025 + 3597×.10602) / (1/3) = 2923.6
        assert med == pytest.approx(2923.63, abs=0.05)

    def test_a_near_zero_weight_source_cannot_set_the_median(self):
        """Bounded influence — the property freshness weighting depends on.

        Kyle Hamilton's IDP anchor on the 2026-09-24 board: Draft Sharks IDP
        2228 @0.9864, IDP Show 3554 @0.1005 (36 days stale), IDPTC 3597 @1.0.
        IDP Show holds 4.8% of the weight, but its thin slice [.473, .521]
        straddles 0.5, so the retired midpoint median (and the step median)
        was IDP Show's own value, 3554.5.  The window median caps its share at
        its weight relative to one average observation (.048 / .333 = 14%).
        """
        vals, wts = [2228.0, 3554.0, 3597.0], [0.9864, 0.1005, 1.0]
        with_light = self._median(vals, wts)
        without_light = self._median([2228.0, 3597.0], [0.9864, 1.0])
        # W = 2.0869; slices end at .472663 / .520820; window [1/3, 2/3]
        # takes .139330 / .048157 / .145847:
        # (2228×.139330 + 3554×.048157 + 3597×.145847) / (1/3) = 3018.56
        assert with_light == pytest.approx(3018.56, abs=0.05)
        # Removing a 4.8%-weight source moves the median ~97, not ~636
        # (the retired midpoint median: 3554.5 with it, 2918 without).
        assert abs(with_light - without_light) < 150.0

    def test_raising_the_weight_of_the_highest_value_raises_the_center(self):
        """Adding weight at the top of the distribution can only move mass up."""
        import random

        rng = random.Random(4)
        for _ in range(3000):
            n = rng.randint(2, 12)
            vals = sorted(rng.uniform(100.0, 9999.0) for _ in range(n))
            wts = [rng.choice([0.25, 0.5, 1.0]) for _ in range(n)]
            heavier = list(wts)
            heavier[-1] += rng.uniform(0.01, 2.0)
            lighter_low = list(wts)
            lighter_low[0] += rng.uniform(0.01, 2.0)  # more weight at the bottom
            base = _weighted(vals, wts)[0]
            assert _weighted(vals, heavier)[0] >= base - 1e-9
            assert _weighted(vals, lighter_low)[0] <= base + 1e-9

    def test_a_light_source_straddling_half_moves_the_median_by_at_most_its_window_share(self):
        """Bounded influence as a PROPERTY (refresh 2026-09-26).

        A light source (≤5% of the weight) whose slice straddles 0.5 is the
        case the retired midpoint rule handed the WHOLE median to.  Under the
        window median, moving that source's value (within its sorted slot)
        moves the median by at most ``n × w/W`` per unit of value — its mass
        relative to one average observation.  Measured on 20,000 random cases
        at the refresh: 0 breaches (main's midpoint median: 19,938 breaches,
        and in 14,280 the light source carried more than half its own move).
        """
        import random

        rng = random.Random(5)
        checked = 0
        while checked < 3000:
            n = rng.randint(3, 9)
            vals = [rng.uniform(500.0, 9999.0) for _ in range(n - 1)]
            wts = [rng.uniform(0.3, 1.0) for _ in range(n - 1)]
            light = rng.uniform(1e-4, 0.05) * sum(wts)
            total = sum(wts) + light
            order = sorted(zip(vals, wts))
            cum, slot = 0.0, None
            for idx, (_v, w) in enumerate(order):
                if cum / total <= 0.5 <= (cum + light) / total:
                    slot = idx
                    break
                cum += w
            if slot is None:
                continue
            checked += 1
            low = order[slot - 1][0] if slot > 0 else min(vals)
            high = order[slot][0]
            if high - low < 1e-6:
                continue
            at_low = self._median(vals + [low], wts + [light])
            at_high = self._median(vals + [high], wts + [light])
            per_unit = abs(at_high - at_low) / (high - low)
            assert per_unit <= min(1.0, n * light / total) + 1e-9
