"""A quantile is not a board value, and a constant is not a consensus.

Two defects in the Monte Carlo trade simulator, both of which nothing
in the repository was capable of disagreeing with.

1. THE 9999 CEILING ON A QUANTILE
=================================
``build_trade_player`` clamped every band endpoint to ``[0, 9999]``.
9999 is where the BOARD's normalization tops out — it is assigned to
whatever today's #1 asset is — and it is not a statement about how much
a player might turn out to be worth.

``_triangular_draw`` is otherwise EXACTLY unbiased: for a symmetric
band its analytic mean is p50 to the last decimal. So the clamp was the
only source of bias in the whole simulator, and it applied to exactly
the twelve most valuable assets on the board. Measured on the pinned
2026-07-30 contract, feeding the UI's own +-15% band:

    Josh Allen      board 9988  ->  E[draw] 9468   (-520, -5.2%)
    Brock Bowers    board 9961  ->  E[draw] 9451   (-510, -5.1%)
    Bijan Robinson  board 9699  ->  E[draw] 9295   (-404, -4.2%)
    Ja'Marr Chase   board 9682  ->  E[draw] 9285   (-397, -4.1%)
    ... 8 more, down to -23         12 of 812 priced rows

Every trade involving an elite asset was simulated against the side
holding it, and only that side. The clamp was not even enforcing an
invariant the module respects: ``_triangular_draw`` extrapolates ABOVE
p90 with no ceiling, so draws past 9999 were always reachable. It
clamped the endpoint but not the draw, which distorts the shape without
bounding anything.

2. "CONSENSUS" THAT IS A CONSTANT
=================================
Output is labelled ``consensus_based_win_rate`` and carries a
disclaimer describing "the sources' consensus distribution" — a
contract field the UI is REQUIRED to render. On the live path that
claim is false and nothing could contradict it: ``valueBand`` is
stamped on **0 of 1093** rows, and ``MonteCarloButton.jsx`` synthesizes
a flat +-15% band and posts it under the same key a real Phase-4
confidence interval would use. The backend could not tell measured
disagreement from an assumption, so it asserted the flattering one on
every run.

Measured, the flat band is not uniformly wrong — it is uniformly
FLAT, which is the actual defect. Against ``marketDispersionCV`` on
683 priced rows (implied p10..p90 half-width = 1.2816 * CV):

    median  CV 0.0243  -> +-3.12%   (flat band is 4.8x wider)
    p90     CV 0.0837  -> +-10.73%  (flat band is 1.4x wider)
    max     CV 0.2631  -> +-33.72%  (flat band is 0.4x — too NARROW)

24 of 683 rows have measured disagreement exceeding +-15%, and at
least a quarter have none at all. A flat band cannot express that the
board knows some players better than others. The right width is a
modeling judgement, recorded as decision #4 in
``docs/open-modeling-decisions.md`` rather than silently re-tuned; what
is fixed here is that the claim is now checkable.

NOT ``livedata``-marked: pure arithmetic on synthetic rows, must block.
"""

from __future__ import annotations

import unittest

from src.trade import monte_carlo as mc


def _draw_mean(p10: float, p50: float, p90: float) -> float:
    """Analytic E[X] of ``_triangular_draw`` over u ~ U(0, 1).

    Derived from the four linear segments, not from the function under
    test — a re-derivation from the implementation would have a
    residual of zero for any band and could not detect the bias this
    module exists to detect.
    """
    slope_lo, slope_hi = p50 - p10, p90 - p50
    return (
        0.10 * (p10 - slope_lo / 2.0)
        + 0.40 * ((p10 + p50) / 2.0)
        + 0.40 * ((p50 + p90) / 2.0)
        + 0.10 * (p90 + slope_hi / 2.0)
    )


class TestTheDrawIsUnbiasedSoTheClampWasTheBias(unittest.TestCase):
    def test_analytic_mean_matches_a_simulated_mean(self) -> None:
        """Non-vacuity for ``_draw_mean``.

        Every bias number below is computed from this helper. If the
        helper did not actually describe ``_triangular_draw``, the
        assertions would be measuring nothing.
        """
        p10, p50, p90 = 8000.0, 9000.0, 10500.0
        n = 20001
        empirical = sum(mc._triangular_draw(p10, p50, p90, (i + 0.5) / n) for i in range(n)) / n
        self.assertAlmostEqual(empirical, _draw_mean(p10, p50, p90), delta=1.0)

    def test_a_symmetric_band_draws_exactly_its_center(self) -> None:
        """The property the clamp broke."""
        for value in (1000.0, 5000.0, 9988.0):
            self.assertAlmostEqual(_draw_mean(value * 0.85, value, value * 1.15), value, places=6)


class TestBandEndpointsAreNotClampedToTheBoardCeiling(unittest.TestCase):
    def test_top_of_board_p90_survives_above_9999(self) -> None:
        """Josh Allen, the row with the largest measured markdown."""
        tp = mc.build_trade_player({"name": "Josh Allen", "rankDerivedValue": 9988})
        self.assertGreater(
            tp.p90,
            9999.0,
            msg=(
                "p90 was clamped to the board's 9999 normalization ceiling. That "
                "is a value bound applied to a quantile: it truncates the upper "
                "tail of the top 12 assets while leaving their lower tail intact, "
                "marking Josh Allen's simulated mean down 520 points (-5.2%) and "
                "biasing every trade against whoever holds him."
            ),
        )

    def test_the_simulated_mean_now_matches_the_board_value(self) -> None:
        """The consequence, stated as the number a user would see."""
        tp = mc.build_trade_player({"name": "Josh Allen", "rankDerivedValue": 9988})
        self.assertAlmostEqual(_draw_mean(tp.p10, tp.p50, tp.p90), 9988.0, delta=1.0)

    def test_a_supplied_band_is_not_clamped_either(self) -> None:
        """The live path: the UI posts the band, it must arrive intact."""
        tp = mc.build_trade_player(
            {
                "name": "Josh Allen",
                "rankDerivedValue": 9988,
                "valueBand": {"p10": 8490, "p50": 9988, "p90": 11486},
            }
        )
        self.assertEqual(tp.p90, 11486.0)

    def test_the_zero_floor_is_kept(self) -> None:
        """Not a blanket removal — negative value is genuinely
        impossible, and the IDP scoring-fit shift can drive a band
        below zero."""
        tp = mc.build_trade_player(
            {
                "name": "Deep Bench LB",
                "pos": "LB",
                "rankDerivedValue": 300,
                "idpScoringFitDelta": -5000,
            },
            apply_scoring_fit=True,
        )
        self.assertGreaterEqual(tp.p10, 0.0)
        self.assertGreaterEqual(tp.p50, 0.0)

    def test_the_consolidation_shift_preserves_the_spread_it_promises(self) -> None:
        """``_apply_consolidation_adjustment``'s docstring says p10/p50/p90
        "all move up by the same amount per player, preserving the
        absolute spread". Clamping each endpoint separately contradicted
        that: on an asset near the ceiling, p90 stopped while p10 kept
        moving, silently narrowing the band on exactly the assets a
        consolidation premium lands on."""

        def _p(name: str, v: float) -> mc.TradePlayer:
            return mc.TradePlayer(
                name=name,
                team="BUF",
                position_group="offense",
                p10=v * 0.85,
                p50=v,
                p90=v * 1.15,
            )

        # Two-for-one, with the receiving side sitting near the ceiling
        # so the p50 clamp actually engages — the case the separate
        # endpoint clamps used to mangle.
        side_a = [_p("Elite", 9950.0)]
        side_b = [_p("Good", 5200.0), _p("Also good", 4900.0)]
        spreads_before = {p.name: p.p90 - p.p10 for p in side_a + side_b}

        new_a, new_b, info = mc._apply_consolidation_adjustment(side_a, side_b)
        if not info["applied"]:
            self.skipTest("consolidation premium not awarded for this package shape")
        for p in new_a + new_b:
            self.assertAlmostEqual(
                p.p90 - p.p10,
                spreads_before[p.name],
                delta=1.0,
                msg=(
                    f"{p.name}'s band width changed from {spreads_before[p.name]:.0f} to "
                    f"{p.p90 - p.p10:.0f} under a shift that is documented to preserve "
                    "the absolute spread. Clamping each endpoint at 9999 separately "
                    "narrows the band on exactly the assets a consolidation premium "
                    "lands on."
                ),
            )
        # The premium itself is still held to the board scale, and the
        # honest report of how much of it landed is unchanged.
        self.assertLessEqual(max(p.p50 for p in new_a + new_b), 9999.0)


class TestBandProvenanceIsReported(unittest.TestCase):
    def test_a_synthesized_band_is_labelled_as_one(self) -> None:
        tp = mc.build_trade_player({"name": "Anyone", "rankDerivedValue": 5000})
        self.assertEqual(tp.band_source, mc.BAND_SOURCE_SYNTHETIC)

    def test_an_undeclared_supplied_band_is_unknown_not_assumed_measured(self) -> None:
        """The flattering default is the one to avoid.

        A caller that posts a ``valueBand`` without saying where it came
        from has told us nothing — and the live caller's band is a
        constant. Reading the key's presence as evidence of measurement
        is exactly how the "consensus" label became unfalsifiable.
        """
        tp = mc.build_trade_player({"name": "Anyone", "valueBand": {"p10": 1, "p50": 2, "p90": 3}})
        self.assertEqual(tp.band_source, mc.BAND_SOURCE_UNKNOWN)
        self.assertNotEqual(tp.band_source, mc.BAND_SOURCE_STAMPED)

    def test_a_declared_band_source_is_honoured(self) -> None:
        tp = mc.build_trade_player(
            {
                "name": "Anyone",
                "valueBand": {"p10": 1, "p50": 2, "p90": 3},
                "bandSource": mc.BAND_SOURCE_STAMPED,
            }
        )
        self.assertEqual(tp.band_source, mc.BAND_SOURCE_STAMPED)

    def test_a_bogus_declaration_is_not_taken_at_face_value(self) -> None:
        tp = mc.build_trade_player(
            {
                "name": "Anyone",
                "valueBand": {"p10": 1, "p50": 2, "p90": 3},
                "bandSource": "measured_by_vibes",
            }
        )
        self.assertEqual(tp.band_source, mc.BAND_SOURCE_UNKNOWN)

    def test_the_result_reports_the_tally_and_the_disclaimer_admits_it(self) -> None:
        """The user-visible half. ``disclaimer`` is a contract field the
        UI is required to render, and it described a consensus
        distribution on every run."""
        rows = [{"name": "A", "rankDerivedValue": 5000}, {"name": "B", "rankDerivedValue": 4000}]
        side_a = [mc.build_trade_player(rows[0])]
        side_b = [mc.build_trade_player(rows[1])]
        out = mc.simulate_trade(side_a, side_b, n_sims=1000, seed=7).to_dict()
        self.assertEqual(out["bandSources"], {mc.BAND_SOURCE_SYNTHETIC: 2})
        self.assertIn("synthesized", out["disclaimer"])
        self.assertIn("not a measurement", out["disclaimer"])

    def test_the_disclaimer_stays_clean_when_every_band_is_real(self) -> None:
        """The asymmetry is the point — this is not a permanent scold.

        Without this, the qualification could be hardcoded into the
        string and the test above would still pass, which would make it
        vacuous.
        """
        band = {"p10": 900, "p50": 1000, "p90": 1100}
        side_a = [
            mc.build_trade_player(
                {"name": "A", "valueBand": band, "bandSource": mc.BAND_SOURCE_STAMPED}
            )
        ]
        side_b = [
            mc.build_trade_player(
                {"name": "B", "valueBand": band, "bandSource": mc.BAND_SOURCE_STAMPED}
            )
        ]
        out = mc.simulate_trade(side_a, side_b, n_sims=1000, seed=7).to_dict()
        self.assertEqual(out["bandSources"], {mc.BAND_SOURCE_STAMPED: 2})
        self.assertNotIn("synthesized", out["disclaimer"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
