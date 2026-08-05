"""Python half of the competitive-window parity test.

Twin of ``frontend/__tests__/team-phase.test.js``. Both halves assert
against ONE fixture, ``tests/fixtures/competitive_window_cases.json``.

Audit W20-F006 / W30-F016: four independent team-direction classifiers
shipped simultaneously and agreed on 3 of 12 live teams.
``src/roster_intel/window.py`` is the nominated definition — the only
one with a measured axis pair, the only one reporting a distribution
rather than picking a side of a threshold. ``frontend/lib/team-phase.js``
is a port of it, and this file exists so the port cannot drift: change
an anchor, a weight, the temperature or the age bounds on one side and
the other side's suite goes red.

NEITHER half may hardcode expectations of its own. Regenerate the
fixture only when the MODEL changes, and expect both suites to move.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.roster_intel.window import (
    COMPETITIVE_STATES,
    DEFAULT_TEMPERATURE,
    _AGE_OLD,
    _AGE_YOUNG,
    _COMPETITIVENESS_WEIGHT,
    _STATE_ANCHORS,
    _TRAJECTORY_WEIGHT,
    _softmax_affinities,
)

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / (
    "competitive_window_cases.json"
)
FIXTURE = json.loads(FIXTURE_PATH.read_text())


class ModelConstantsTests(unittest.TestCase):
    def test_fixture_records_the_live_model(self) -> None:
        model = FIXTURE["model"]
        self.assertEqual(model["temperature"], DEFAULT_TEMPERATURE)
        self.assertEqual(model["competitivenessWeight"], _COMPETITIVENESS_WEIGHT)
        self.assertEqual(model["trajectoryWeight"], _TRAJECTORY_WEIGHT)
        self.assertEqual(model["ageYoung"], _AGE_YOUNG)
        self.assertEqual(model["ageOld"], _AGE_OLD)
        self.assertEqual(
            {k: list(v) for k, v in _STATE_ANCHORS.items()},
            model["stateAnchors"],
        )
        self.assertEqual(sorted(COMPETITIVE_STATES), sorted(model["stateAnchors"]))


class ProbabilityParityTests(unittest.TestCase):
    def test_every_case_reproduces(self) -> None:
        self.assertGreaterEqual(len(FIXTURE["cases"]), 8)
        for case in FIXTURE["cases"]:
            with self.subTest(case=case["id"]):
                probs = _softmax_affinities(
                    case["competitiveness"],
                    case["trajectory"],
                    DEFAULT_TEMPERATURE,
                )
                for state in COMPETITIVE_STATES:
                    self.assertAlmostEqual(
                        probs[state], case["probabilities"][state], places=9
                    )
                self.assertEqual(max(probs, key=lambda k: probs[k]), case["mostLikely"])

    def test_rebuild_is_reachable_at_the_bottom_of_a_twelve_team_league(self) -> None:
        """The defect the port had to fix, stated as a property.

        The frontend classifier this replaced could not emit Rebuild at
        all on the live board (0 of 12 teams — W20-F008). The bottom of
        a 12-team league sits at percentile 1/24 = 0.0417. Whatever its
        age curve, that roster must land on a SELLING state, and on
        ``rebuild`` specifically for every trajectory short of the
        youngest extreme (where ``productive_struggle`` — young and
        losing — is the right read and is itself a selling state).
        """
        sellers = {"rebuild", "productive_struggle"}
        for trajectory in (0.0, 0.25, 0.5, 0.6, 0.75, 0.9, 1.0):
            with self.subTest(trajectory=trajectory):
                probs = _softmax_affinities(1 / 24, trajectory, DEFAULT_TEMPERATURE)
                state = max(probs, key=lambda k: probs[k])
                self.assertIn(state, sellers)
                if trajectory <= 0.75:
                    self.assertEqual(state, "rebuild")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
