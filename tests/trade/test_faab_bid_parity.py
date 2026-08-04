"""Server/client parity for the FAAB baseline bid (audit finding H4).

Twin of ``frontend/__tests__/faab-bid-parity.test.js``.  Both halves
assert against ONE fixture, ``tests/fixtures/faab_bid_parity_cases.json``:

  * ``src/trade/waiver.py::_compute_faab_bid`` is what the API returns
    (``POST /api/waiver/suggestions``, and the baseline leg of
    ``POST /api/waiver/faab-recommend``).
  * ``frontend/lib/waiver-logic.js::computeFaabHint`` is what the
    /waivers table SHOWS in its "FAAB hint" column.

They are the same formula written twice, and nothing checked that they
agreed.  They did not: Python's ``round`` is half-to-even and JS's
``Math.round`` is half-up, so every ``.5`` boundary produced a $1
disagreement between the number on the page and the number the API
recommends — a top-of-pool lowball on a $100 budget is exactly $10.50.
Both sides now spell out half-up explicitly and derive all three tiers
from the unrounded aggressive figure.

NEITHER half may hardcode expectations of its own.  The fixture's
``expected`` blocks are hand-derived from the formula it documents; if
the two implementations disagree, exactly one suite goes red against a
shared, human-authored statement of intent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.trade.waiver import _compute_faab_bid, _round_half_up

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "faab_bid_parity_cases.json"

FIXTURE: dict[str, Any] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
CASES: list[dict[str, Any]] = FIXTURE["cases"]


# ── Fixture integrity ────────────────────────────────────────────────


class TestFixtureIntegrity:
    """The fixture has to be worth trusting before it can bind anything."""

    def test_case_ids_are_unique(self) -> None:
        ids = [c["id"] for c in CASES]
        dupes = {i for i in ids if ids.count(i) > 1}
        assert not dupes, f"duplicate case ids: {sorted(dupes)}"

    def test_every_case_declares_a_full_expectation(self) -> None:
        for case in CASES:
            assert set(case["expected"]) == {"aggressive", "reasonable", "lowball"}

    def test_the_rounding_boundary_is_actually_covered(self) -> None:
        """A parity fixture that never lands on ``.5`` proves nothing.

        The whole point is the boundary, so pin that at least one case
        expects a tier the OLD code got wrong (half-to-even $10.50 → $10
        on the server, half-up → $11 on the client).
        """
        top = next(c for c in CASES if c["id"] == "top_of_pool_full_budget")
        assert top["expected"]["lowball"] == 11
        assert FIXTURE["rounding"]["convention"] == "half-up"


# ── The shared cases ─────────────────────────────────────────────────


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_python_bid_matches_the_shared_fixture(case: dict[str, Any]) -> None:
    aggressive, reasonable, lowball = _compute_faab_bid(
        case["candidateValue"],
        budget=case["budget"],
        top_value_in_pool=case["topValueInPool"],
    )
    assert {
        "aggressive": aggressive,
        "reasonable": reasonable,
        "lowball": lowball,
    } == case["expected"], case["why"]


# ── The rounding rule itself ─────────────────────────────────────────


def test_rounding_is_half_up_not_bankers() -> None:
    """``_round_half_up`` must not be a rename of the built-in.

    Hand-stated table.  The built-in ``round`` answers 10, 12 and 24 on
    the first three (ties go to the even integer) — those three lines
    are the entire bug this helper exists to prevent.
    """
    assert _round_half_up(10.5) == 11
    assert _round_half_up(12.5) == 13
    assert _round_half_up(24.5) == 25
    # Ties are the only interesting case; everything else agrees.
    assert _round_half_up(10.4) == 10
    assert _round_half_up(10.6) == 11
    assert _round_half_up(0.0) == 0


def test_tiers_scale_the_unrounded_aggressive_bid() -> None:
    """$17.50 aggressive → 70% is $12.25 → $12, not 70% of $18 → $13.

    Hand-derived: share 0.5 → 0.05 + 0.125 = 0.175 → $100 × 0.175 =
    $17.50.  Rounding first and scaling second is what produced $13.
    """
    aggressive, reasonable, _ = _compute_faab_bid(
        2500, budget=100, top_value_in_pool=5000
    )
    assert aggressive == 18
    assert reasonable == 12
