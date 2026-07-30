"""Backend/frontend parity for the rank-form Hill curve constants.

WHY THIS EXISTS
===============
``frontend/lib/value-history.js`` reconstructs a value from a rank for
two charts — the terminal team-value series
(``computeTeamValueSeries`` → ``valueFromRank``) and the derived
rank-history line on the player popup (``rankFromValue``). It does that
with its own copy of the backend's rank-form Hill constants, because
its callers are chart components that hold a rank series rather than the
contract.

A mirrored constant with a comment saying "these might drift" is not a
guard, and this pair proved it. On 2026-07-30 the mirror still read
``K = 45, EXP = 1.1, CEIL = 9999`` while Python held
``HILL_MIDPOINT = 48.44, HILL_SLOPE = 1.149`` and a span of 9998 — three
values wrong at once, one of them (the span) putting rank 1 at 10000
instead of 9999. Nothing failed. The comment had even flagged the risk
and deferred the fix to a follow-up that never came.

So the comment is replaced by this test. Same approach as
``test_source_registry_parity.py``: parse the JS as text, no eval, and
diff against the Python constants.

WHAT IT DOES NOT COVER
======================
Only the rank-form pair. The percentile-form scope masters
(``HILL_*_PERCENTILE_*``) are not mirrored in this file — the frontend
reads those from the contract's ``hillCurves`` block, which is the right
pattern and needs no static parity check.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from src.canonical.player_valuation import (
    HILL_MIDPOINT,
    HILL_SLOPE,
    rank_to_value,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
JS_PATH = REPO_ROOT / "frontend" / "lib" / "value-history.js"

# The backend span: ``value = 1 + 9998 / (1 + ...)``, so rank 1 == 9999.
EXPECTED_SPAN = 9998


def _parse_rank_form_curve() -> dict[str, float]:
    """Pull the ``RANK_FORM_CURVE`` object literal out of the JS source."""
    text = JS_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"export\s+const\s+RANK_FORM_CURVE\s*=\s*\{(?P<body>.*?)\}\s*;",
        text,
        re.DOTALL,
    )
    if not match:
        raise AssertionError(
            f"could not find `export const RANK_FORM_CURVE = {{...}}` in {JS_PATH}. "
            "If the constants moved, point this test at the new home rather "
            "than deleting it — the drift it guards is silent."
        )
    body = match.group("body")
    out: dict[str, float] = {}
    for key in ("midpoint", "slope", "span"):
        found = re.search(rf"\b{key}\s*:\s*(-?\d+(?:\.\d+)?)", body)
        if not found:
            raise AssertionError(f"RANK_FORM_CURVE is missing a numeric `{key}`: {body!r}")
        out[key] = float(found.group(1))
    return out


class TestRankFormFrontendParity(unittest.TestCase):
    def test_midpoint_matches_python(self) -> None:
        js = _parse_rank_form_curve()
        self.assertAlmostEqual(
            js["midpoint"],
            HILL_MIDPOINT,
            places=6,
            msg=(
                f"frontend RANK_FORM_CURVE.midpoint={js['midpoint']} but "
                f"HILL_MIDPOINT={HILL_MIDPOINT}. Update "
                "frontend/lib/value-history.js to match; a re-tune has to move "
                "both or the team-value chart goes out of calibration."
            ),
        )

    def test_slope_matches_python(self) -> None:
        js = _parse_rank_form_curve()
        self.assertAlmostEqual(
            js["slope"],
            HILL_SLOPE,
            places=6,
            msg=(
                f"frontend RANK_FORM_CURVE.slope={js['slope']} but "
                f"HILL_SLOPE={HILL_SLOPE}. Update "
                "frontend/lib/value-history.js to match."
            ),
        )

    def test_span_puts_rank_one_at_9999(self) -> None:
        """The bug that made rank 1 worth 10000 on the frontend."""
        js = _parse_rank_form_curve()
        self.assertEqual(js["span"], EXPECTED_SPAN)
        self.assertEqual(round(1 + js["span"] / 1.0), rank_to_value(1))

    def test_the_two_implementations_agree_numerically(self) -> None:
        """Belt and braces: reimplement the JS arithmetic from the parsed
        constants and compare against Python across the board's range.

        Catches a divergence in the FORMULA, which matching constants
        would not (e.g. a stray ``(r - 1)`` becoming ``r``).
        """
        js = _parse_rank_form_curve()
        mid, slope, span = js["midpoint"], js["slope"], js["span"]
        for rank in (1, 2, 3, 5, 10, 25, 50, 100, 200, 300, 500, 800):
            js_value = round(1 + span / (1 + ((rank - 1) / mid) ** slope))
            self.assertEqual(
                js_value,
                rank_to_value(rank),
                msg=f"rank {rank}: JS mirror gives {js_value}, Python {rank_to_value(rank)}",
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
