"""The simulated mean must equal the board value, and a fabricated band
must say so — W09-F005 / W09-F016.

Two separate defects, both of the R9 shape: a missing input became a
confident number.

1. **No live row carries a ``valueBand``.**  0 of 1,092 rows on the
   2026-08-04 contract have one, so ``build_trade_player``'s documented
   degradation path — a flat +/-15% triangle — is the ONLY path, for
   every player, pick and defender, regardless of whether the board
   blended 1 source or 14.  It was still described to the user as "our
   6+ ranking sources don't fully agree on value".  The band is not
   wrong so much as uninformative, and nothing said which it was.

2. **The band was clamped at the board ceiling on one side only.**
   ``_shifted`` applied ``min(9999, ...)`` to every quantile, so for a
   top-of-board asset the +15% leg was truncated while the -15% leg was
   not.  The extended-triangular quantile map is mean-preserving, so the
   sampled mean then falls BELOW the value the user is shown: Brock
   Bowers at 9,947 simulated at 9,441.9.  The trade meter and the
   simulator disagreed about the same player by 5%.
"""

from __future__ import annotations

import math

from src.trade import monte_carlo as mc
from src.trade import symmetrize as sym


def _row(name, value, **extra):
    return {"name": name, "team": "LV", "pos": "TE", "rankDerivedValue": value, **extra}


class TestBandProvenance:
    def test_a_synthesized_band_is_labelled_as_synthesized(self):
        tp = mc.build_trade_player(_row("Brock Bowers", 9947))
        assert tp.band_source == mc.BAND_SOURCE_SYNTHETIC

    def test_a_stamped_band_is_labelled_as_stamped(self):
        tp = mc.build_trade_player(
            _row("Brock Bowers", 9947, valueBand={"p10": 9000, "p50": 9947, "p90": 9990})
        )
        assert tp.band_source == mc.BAND_SOURCE_STAMPED

    def test_the_run_reports_how_many_bands_it_had_to_invent(self):
        a = [mc.build_trade_player(_row("A", 8000))]
        b = [
            mc.build_trade_player(
                _row("B", 6000, valueBand={"p10": 5000, "p50": 6000, "p90": 7000})
            )
        ]
        out = sym.simulate_symmetric(a, b, n_sims=2000, seed=1)
        prov = out["bandProvenance"]
        assert prov["synthetic"] == 1
        assert prov["stamped"] == 1
        assert prov["syntheticWidthPct"] == 15
        # And says it in words, since this is what the disclaimer is for.
        assert "placeholder" in prov["note"].lower()


class TestTheSampledMeanMatchesTheBoard:
    def test_a_top_of_board_asset_does_not_simulate_below_its_value(self):
        """Brock Bowers, the finding's own case: 9,947 on the board."""
        bowers = mc.build_trade_player(_row("Brock Bowers", 9947))
        out = sym.simulate_symmetric([bowers], [], n_sims=20000, seed=11)
        assert out["sideAMean"] == 9947.0 or abs(out["sideAMean"] - 9947.0) <= 25.0

    def test_an_unclamped_asset_was_already_correct_and_stays_correct(self):
        mid = mc.build_trade_player(_row("Mid", 8000))
        out = sym.simulate_symmetric([mid], [], n_sims=20000, seed=11)
        assert abs(out["sideAMean"] - 8000.0) <= 25.0

    def test_the_band_floor_at_zero_survives(self):
        """The >= 0 floor is real — a negative dynasty value is not a
        thing — and only the board CEILING is removed."""
        tp = mc.build_trade_player(
            _row("Fringe", 10, valueBand={"p10": -500, "p50": 10, "p90": 40})
        )
        assert tp.p10 == 0.0


class TestConvergenceIsReported:
    def test_a_standard_error_accompanies_the_win_probability(self):
        out = sym.simulate_symmetric(
            [mc.build_trade_player(_row("A", 6000))],
            [mc.build_trade_player(_row("B", 5800))],
            n_sims=4000,
            seed=3,
        )
        p = out["winProbA"]
        expected = math.sqrt(p * (1.0 - p) / out["nDraws"])
        assert out["mcStandardError"] > 0
        assert abs(out["mcStandardError"] - expected) < 1e-6

    def test_n_sims_is_what_was_requested_and_n_draws_is_what_was_drawn(self):
        out = sym.simulate_symmetric(
            [mc.build_trade_player(_row("A", 6000))],
            [mc.build_trade_player(_row("B", 5800))],
            n_sims=4000,
            seed=3,
        )
        # It reported 8000 here — the two symmetrization passes summed —
        # and the UI rendered "X% of 8,000 simulations" for a 4,000 ask.
        assert out["nSims"] == 4000
        assert out["nDraws"] == 8000
        assert out["nPasses"] == 2

    def test_the_seed_is_echoed_so_a_run_can_be_reproduced(self):
        out = sym.simulate_symmetric(
            [mc.build_trade_player(_row("A", 6000))],
            [mc.build_trade_player(_row("B", 5800))],
            n_sims=2000,
            seed=1234,
        )
        assert out["seed"] == 1234
        assert (
            sym.simulate_symmetric(
                [mc.build_trade_player(_row("A", 6000))],
                [mc.build_trade_player(_row("B", 5800))],
                n_sims=2000,
                seed=None,
            )["seed"]
            is None
        )
