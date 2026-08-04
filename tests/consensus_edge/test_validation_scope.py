"""The measured result and the served board must describe the same thing.

`COMPONENT_VALIDATION["mispricing"]` cites the file that produced its
rho — a null today, +0.126 before the scale repair; either way a number
about a specific configuration. That file was produced by a code path
that calls
`fair_value_index` WITHOUT a `scoring_fit_board`; the service calls it
WITH one. The two agree today only because the checked-in Sleeper
directory carries no GSIS ids, so the fit is inert — an accident of the
fixture, not a property of the code.

The failure this guards is silent by construction: a real Sleeper
directory reaching production would multiply served fair values by
per-player multipliers the measurement never saw, and every payload
would go on citing the same rho. Nothing would break; the number would
just stop being about the thing it is quoted about.

These tests pin both halves — that the backtest really does run inert,
and that the board notices and says so if it ever stops matching.
"""

from __future__ import annotations

import inspect
import unittest
from pathlib import Path

from src.consensus_edge import score, validation_scope

REPO = Path(__file__).resolve().parents[2]


class TestTheBacktestRunsTheMeasuredConfiguration(unittest.TestCase):
    def test_the_backtest_does_not_apply_scoring_fit(self):
        source = (REPO / "scripts" / "run_consensus_edge_backtest.py").read_text()
        # The call itself, not the word: the comment explaining WHY the
        # fit is omitted legitimately names it.
        self.assertNotIn(
            "scoring_fit_board=",
            source,
            "the backtest now applies league scoring fit; either the measured "
            "configuration in validation_scope must change alongside a re-run, "
            "or this is look-ahead leakage (the multipliers are fitted on a "
            "whole season and cannot be reconstructed as-of a past date)",
        )

    def test_the_service_does_apply_it(self):
        # The other half of the divergence. If this ever stops being
        # true the scope block is measuring nothing.
        source = (REPO / "src" / "consensus_edge" / "service.py").read_text()
        self.assertIn("scoring_fit_board=fit_board", source)

    def test_the_measured_configuration_says_scoring_fit_was_inert(self):
        self.assertFalse(validation_scope.MEASURED_CONFIGURATION["scoringFitApplied"])

    def test_committed_measurements_are_cited_by_the_validation_table(self):
        for name, meta in score.COMPONENT_VALIDATION.items():
            if not meta.get("evidence"):
                continue
            self.assertTrue(
                (REPO / meta["evidence"]).exists(),
                f"{name} cites {meta['evidence']}, which is not in the repo",
            )


class TestTheBoardReportsItsScope(unittest.TestCase):
    def test_an_inert_fit_matches_the_measured_configuration(self):
        scope = validation_scope.scope_for_board({"active": False})
        self.assertTrue(scope["matchesMeasured"])
        self.assertEqual(scope["differences"], [])

    def test_an_active_fit_is_reported_as_a_divergence(self):
        scope = validation_scope.scope_for_board({"active": True})
        self.assertFalse(scope["matchesMeasured"])
        self.assertTrue(scope["differences"])
        self.assertIn("scoring fit", scope["differences"][0])

    def test_a_missing_fit_block_is_treated_as_inert(self):
        # Defensive: no scoring-fit meta at all is the flag-off / no-data
        # case, which is the measured configuration, not a divergence.
        for meta in (None, {}, {"active": None}):
            self.assertTrue(validation_scope.scope_for_board(meta)["matchesMeasured"])


class TestTheDivergenceReachesThePayload(unittest.TestCase):
    """A scope block nothing surfaces is a scope block nobody reads."""

    def test_build_board_stamps_the_scope(self):
        from src.consensus_edge import service

        source = inspect.getsource(service.build_board)
        self.assertIn('"validationScope": scope', source)

    def test_a_divergence_becomes_a_caveat(self):
        from src.consensus_edge import service

        diverged = service._caveats(validation_scope.scope_for_board({"active": True}))
        self.assertTrue(
            any("NOT running the configuration that was measured" in c for c in diverged),
            f"a configuration divergence produced no caveat: {diverged}",
        )

    def test_the_matching_case_carries_no_divergence_caveat(self):
        from src.consensus_edge import service

        matching = service._caveats(validation_scope.scope_for_board({"active": False}))
        self.assertFalse(any("NOT running the configuration" in c for c in matching))
        # The permanent caveats survive — they are not conditional.
        self.assertTrue(any("market movement" in c for c in matching))

    def test_the_caveats_no_longer_call_every_weight_a_prior(self):
        # Opportunity's weight is now a measured null, not a declared
        # prior. Calling it a prior would understate what is known.
        from src.consensus_edge import service

        text = " ".join(service._caveats(validation_scope.scope_for_board({"active": False})))
        self.assertIn("zero weight", text)


if __name__ == "__main__":
    unittest.main()
