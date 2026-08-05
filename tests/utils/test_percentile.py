"""One percentile-rank definition, and every caller reaches it.

Audit W30-F007: four independent implementations, disagreeing on the
edges of a 12-value population (0.0/1.0 vs 0.0417/0.9583) and on what
an EMPTY population means (0.5 vs 0.0).

The interesting assertions here are the AGREEMENT ones — they fail
against the pre-fix tree, which is the point.
"""

from __future__ import annotations

import unittest

from src.public_league.power import _percentile_rank as power_v1_rank
from src.ros.power_v2 import _percentile as ros_v2_rank
from src.roster_intel.window import league_competitiveness
from src.sharp.score import percentile_rank as sharp_rank
from src.utils.percentile import percentile_rank

_POP12 = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0, 110.0, 120.0]


class SharedDefinitionTests(unittest.TestCase):
    def test_self_inclusive_midrank(self) -> None:
        self.assertAlmostEqual(percentile_rank(120.0, _POP12), 23 / 24)
        self.assertAlmostEqual(percentile_rank(10.0, _POP12), 1 / 24)

    def test_all_identical_population_is_neutral(self) -> None:
        # No information in the population; must not read as elite.
        self.assertEqual(percentile_rank(5.0, [5.0] * 8), 0.5)

    def test_empty_population_is_absent_by_default(self) -> None:
        # Absence stays representable rather than resolving to a
        # confident 0.0 (which on a team board reads "worst in league").
        self.assertIsNone(percentile_rank(5.0, []))
        self.assertIsNone(percentile_rank(5.0, None))

    def test_empty_policy_is_the_callers_and_is_explicit(self) -> None:
        self.assertEqual(percentile_rank(5.0, [], empty=0.5), 0.5)

    def test_non_numeric_entries_are_ignored_not_coerced(self) -> None:
        self.assertAlmostEqual(percentile_rank(30.0, [10.0, "x", None, 30.0]), 0.75)


class CallerAgreementTests(unittest.TestCase):
    """Every percentile-rank caller answers the same question the same way."""

    def test_all_callers_agree_on_the_league_maximum(self) -> None:
        expected = 23 / 24
        self.assertAlmostEqual(power_v1_rank(_POP12, 120.0), expected)
        self.assertAlmostEqual(sharp_rank(120.0, _POP12), expected)
        self.assertAlmostEqual(ros_v2_rank(_POP12, 120.0), expected)

    def test_all_callers_agree_on_the_league_minimum(self) -> None:
        expected = 1 / 24
        self.assertAlmostEqual(power_v1_rank(_POP12, 10.0), expected)
        self.assertAlmostEqual(sharp_rank(10.0, _POP12), expected)
        self.assertAlmostEqual(ros_v2_rank(_POP12, 10.0), expected)

    def test_all_callers_agree_that_unmeasurable_is_not_worst(self) -> None:
        self.assertEqual(power_v1_rank([], 5.0), 0.5)
        self.assertEqual(sharp_rank(5.0, []), 0.5)
        self.assertEqual(ros_v2_rank([], 5.0), 0.5)

    def test_window_competitiveness_matches_the_shared_helper(self) -> None:
        """window.py's two inline copies are gone; it calls the helper."""
        scores = {f"o{i}": float(v) for i, v in enumerate(_POP12)}
        pct, source = league_competitiveness("o11", lineup_scores=scores)
        self.assertEqual(source, "lineupScoreRank")
        self.assertAlmostEqual(pct, percentile_rank(120.0, _POP12))

        odds = [
            {"ownerId": f"o{i}", "championshipOdds": v / 1000.0}
            for i, v in enumerate(_POP12)
        ]
        pct, source = league_competitiveness("o0", playoff_odds=odds)
        self.assertEqual(source, "championshipOdds")
        self.assertAlmostEqual(pct, percentile_rank(10.0, _POP12))


class NoSecondDefinitionTests(unittest.TestCase):
    """A grep test: no module may re-derive the midrank inline."""

    def test_no_inline_midrank_reimplementations(self) -> None:
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parents[2] / "src"
        # ``(below + 0.5 * equal) / n`` written by hand, in any spelling.
        pattern = re.compile(r"below\s*\+\s*0?\.?5\s*\*\s*(?:equal|same|ties)")
        offenders = [
            str(p.relative_to(root))
            for p in root.rglob("*.py")
            if p.name != "percentile.py" and pattern.search(p.read_text(encoding="utf-8"))
        ]
        self.assertEqual(offenders, [], f"inline percentile-rank copies: {offenders}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
