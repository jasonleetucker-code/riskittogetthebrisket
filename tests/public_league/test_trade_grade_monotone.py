"""TC-A — trade letter grades are monotone in the margin.

Before: a winner's letters ran A (3-8%), A- (8-15%), B+ (15-25%), A+ (>=25%),
so a clearer win graded LOWER than a slight one, and B+ meant both "Clear
win" and "Slight overpay".  The JS twin is pinned by
``frontend/__tests__/trade-grade-parity.test.js`` against the same shared
fixture's band table; this test pins the ordering property itself.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.public_league.trade_grading import grade_from_pct

LETTER_RANK = {"F": 0, "D": 1, "C": 2, "B": 3, "B+": 4, "A-": 5, "A": 6, "A+": 7}
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "trade_grade_parity_cases.json"

SWEEP = [x / 4 for x in range(0, 4 * 60)]  # 0.00 .. 59.75 %


def _rank(pct: float, winner: bool) -> int:
    return LETTER_RANK[grade_from_pct(pct, winner)["grade"]]


def test_a_bigger_win_never_earns_a_lower_letter() -> None:
    ranks = [_rank(p, True) for p in SWEEP]
    assert ranks == sorted(ranks), "winner letters must be non-decreasing in the margin"


def test_a_bigger_overpay_never_earns_a_higher_letter() -> None:
    ranks = [_rank(p, False) for p in SWEEP]
    assert ranks == sorted(ranks, reverse=True)


def test_a_winner_never_grades_below_the_loser_at_the_same_margin() -> None:
    assert all(_rank(p, True) >= _rank(p, False) for p in SWEEP)


def test_the_shared_band_table_is_monotone() -> None:
    bands = json.loads(FIXTURE.read_text(encoding="utf-8"))["bands"]
    win = [LETTER_RANK[b["grade"]] for b in bands["winner"]]
    lose = [LETTER_RANK[b["grade"]] for b in bands["loser"]]
    assert win == sorted(win)
    assert lose == sorted(lose, reverse=True)
