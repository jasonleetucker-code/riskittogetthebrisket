"""OD-F6 option A (owner, 2026-10-21): the history grade is RELABELLED, never re-graded.

The League Hub / ``/trades`` history grade used to call its lowest tier
"Fair trade", the same word as the market-fairness verdict (FAIR TRADE /
NOT FAIR, ``fairness_bands_v2``) -- a different predicate.  The owner chose
to rename the tier, state the calculation basis, and define the 3% criterion
in one place, with ZERO numerical grade changes.

This test is the proof of "zero".  ``tests/fixtures/history_grade_relabel_reference.json``
was written ONCE by this file's ``--write`` mode at ``main`` ``ce22d5de7``
(before the relabel), from the pre-change grading code.  It holds:

* ``bandRuns`` -- the piecewise-constant output of ``grade_from_pct`` over a
  0.001-step scan of 0..60 %, for winners and losers, as runs
  ``[startPct, grade, color, label]``, plus probes 1e-9 either side of every
  cut point;
* ``sideCases`` -- seeded ``grade_trade_side`` inputs (got, gave, a supplied
  ``vaNet``) and their full output dicts (every number, the letter, colour
  and label);
* ``tradeCases`` -- seeded multi-piece trades through ``grade_trade_sides``
  (the active package model computes the VA) and their full outputs.

Each check recomputes with today's code and compares to the reference with
exactly one difference allowed: the label ``"Fair trade"`` reads
``HISTORY_EVEN_LABEL``.  Every letter, colour, pctGap, net and cut point is
byte-identical.  The JS twin (``frontend/__tests__/history-grade-relabel-no-change.test.js``)
asserts the same reference against ``frontend/lib/league-analysis.js``.
"""

from __future__ import annotations

import json
import random
import re
import sys
import unittest
from pathlib import Path
from typing import Any

from src.public_league import trade_grading

REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_PATH = REPO_ROOT / "tests" / "fixtures" / "history_grade_relabel_reference.json"
JS_POLICY_PATH = REPO_ROOT / "frontend" / "lib" / "trade-history-grade-policy.js"

PRE_CHANGE_LABEL = "Fair trade"
_SCAN_STEP_MILLI = 1  # 0.001 %
_SCAN_MAX_MILLI = 60_000  # 60 %
_EDGE_EPSILON = 1e-9


def _scan_runs(grade_fn) -> dict[str, list[list[Any]]]:
    out: dict[str, list[list[Any]]] = {}
    for key, is_winner in (("winner", True), ("loser", False)):
        runs: list[list[Any]] = []
        for milli in range(0, _SCAN_MAX_MILLI + 1, _SCAN_STEP_MILLI):
            pct = milli / 1000.0
            g = grade_fn(pct, is_winner)
            triple = [g["grade"], g["color"], g["label"]]
            if not runs or runs[-1][1:] != triple:
                runs.append([pct, *triple])
        out[key] = runs
    return out


def _edge_probes(grade_fn, cuts: list[float]) -> list[list[Any]]:
    probes: list[list[Any]] = []
    for cut in cuts:
        for pct in (cut - _EDGE_EPSILON, cut, cut + _EDGE_EPSILON):
            for is_winner in (True, False):
                g = grade_fn(pct, is_winner)
                probes.append([pct, is_winner, g["grade"], g["color"], g["label"]])
    return probes


def _side_inputs(seed: int, n: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    cases: list[dict[str, Any]] = []
    for i in range(n):
        got = [rng.randint(1, 9999) for _ in range(rng.randint(1, 4))]
        gave = [rng.randint(1, 9999) for _ in range(rng.randint(1, 4))]
        if i % 3 == 0:
            # Near-even: the gap lands within a few percent, so the fair edge
            # is exercised far more than a uniform draw would.
            gave = list(got)
            gave[0] = max(1, gave[0] + rng.randint(-400, 400))
        va = 0 if i % 5 == 0 else rng.randint(-1500, 1500)
        cases.append({"got": got, "gave": gave, "vaNet": va})
    return cases


def _trade_inputs(seed: int, n: int) -> list[list[dict[str, list[int]]]]:
    rng = random.Random(seed)
    trades: list[list[dict[str, list[int]]]] = []
    for _ in range(n):
        a = [rng.randint(100, 9999) for _ in range(rng.randint(1, 4))]
        b = [rng.randint(100, 9999) for _ in range(rng.randint(1, 4))]
        trades.append([{"got": b, "gave": a}, {"got": a, "gave": b}])
    return trades


def _cuts() -> list[float]:
    return [
        trade_grading._GRADE_PCT_FAIR,
        trade_grading._GRADE_PCT_SLIGHT,
        trade_grading._GRADE_PCT_GOOD,
        trade_grading._GRADE_PCT_CLEAR,
        trade_grading._GRADE_PCT_ROBBERY,
    ]


def build_reference() -> dict[str, Any]:
    sides = _side_inputs(20261021, 600)
    trades = _trade_inputs(20261022, 200)
    return {
        "_comment": [
            "OD-F6 option A no-change reference.  Written ONCE by",
            "tests/public_league/test_history_grade_relabel_no_change.py --write at main ce22d5de7,",
            "BEFORE the history tier was relabelled.  Do not regenerate: it is the",
            "pre-change evidence the relabel is checked against.  Only the label",
            "'Fair trade' may differ (it now reads HISTORY_EVEN_LABEL).",
        ],
        "preChangeLabel": PRE_CHANGE_LABEL,
        "cuts": _cuts(),
        "bandRuns": _scan_runs(trade_grading.grade_from_pct),
        "edgeProbes": _edge_probes(trade_grading.grade_from_pct, _cuts()),
        "sideCases": [
            {**c, "out": trade_grading.grade_trade_side(c["got"], c["gave"], c["vaNet"])}
            for c in sides
        ],
        "tradeCases": [
            {
                "sides": t,
                "out": trade_grading.grade_trade_sides([(s["got"], s["gave"]) for s in t]),
            }
            for t in trades
        ],
    }


def _relabel(obj: Any, new_label: str) -> Any:
    """The reference with the one permitted difference applied."""
    if isinstance(obj, dict):
        return {k: _relabel(v, new_label) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_relabel(v, new_label) for v in obj]
    if obj == PRE_CHANGE_LABEL:
        return new_label
    return obj


class HistoryGradeRelabelNoChange(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with REFERENCE_PATH.open(encoding="utf-8") as fh:
            cls.ref = json.load(fh)
        cls.expected = _relabel(cls.ref, trade_grading.HISTORY_EVEN_LABEL)

    def test_reference_is_the_pre_change_evidence(self) -> None:
        self.assertEqual(self.ref["preChangeLabel"], PRE_CHANGE_LABEL)
        # The reference really contains the old word -- otherwise the
        # comparison below could not detect a grade moving into or out of it.
        dumped = json.dumps(self.ref)
        self.assertGreater(dumped.count(PRE_CHANGE_LABEL), 100)
        self.assertGreaterEqual(len(self.ref["sideCases"]), 600)
        self.assertGreaterEqual(len(self.ref["tradeCases"]), 200)
        even = sum(
            1 for c in self.ref["sideCases"] if c["out"]["grade"]["label"] == PRE_CHANGE_LABEL
        )
        self.assertGreater(even, 50, "too few evenly-valued sides to exercise the edge")

    def test_cut_points_are_unchanged(self) -> None:
        self.assertEqual(_cuts(), self.ref["cuts"])
        self.assertEqual(trade_grading.HISTORY_EVEN_PCT, self.ref["cuts"][0])

    def test_band_table_is_unchanged_except_the_tier_zero_word(self) -> None:
        self.assertEqual(_scan_runs(trade_grading.grade_from_pct), self.expected["bandRuns"])
        self.assertEqual(
            _edge_probes(trade_grading.grade_from_pct, self.ref["cuts"]),
            self.expected["edgeProbes"],
        )

    def test_every_side_grade_and_number_is_unchanged(self) -> None:
        for case, want in zip(self.ref["sideCases"], self.expected["sideCases"]):
            got = trade_grading.grade_trade_side(case["got"], case["gave"], case["vaNet"])
            self.assertEqual(got, want["out"], case)

    def test_every_trade_grade_and_number_is_unchanged(self) -> None:
        for case, want in zip(self.ref["tradeCases"], self.expected["tradeCases"]):
            got = trade_grading.grade_trade_sides([(s["got"], s["gave"]) for s in case["sides"]])
            self.assertEqual(got, want["out"], case["sides"])

    def test_old_word_is_gone_and_the_new_word_is_not_the_advisor_phrase(self) -> None:
        self.assertEqual(trade_grading.HISTORY_EVEN_LABEL, "Evenly valued")
        self.assertNotIn("fair", trade_grading.HISTORY_EVEN_LABEL.lower())
        self.assertEqual(trade_grading.grade_from_pct(0.0, True)["label"], "Evenly valued")


class HistoryEvenCriterionHasOneOwner(unittest.TestCase):
    """The 3% criterion is defined once per runtime and the two are pinned equal."""

    def test_js_policy_mirrors_the_python_owner(self) -> None:
        src = JS_POLICY_PATH.read_text(encoding="utf-8")
        pct = re.search(r"export const HISTORY_EVEN_PCT = ([0-9.]+);", src)
        label = re.search(r'export const HISTORY_EVEN_LABEL = "([^"]+)";', src)
        self.assertIsNotNone(pct, "frontend policy must export HISTORY_EVEN_PCT")
        self.assertIsNotNone(label, "frontend policy must export HISTORY_EVEN_LABEL")
        self.assertEqual(float(pct.group(1)), trade_grading.HISTORY_EVEN_PCT)
        self.assertEqual(label.group(1), trade_grading.HISTORY_EVEN_LABEL)

    def test_no_bare_three_percent_literal_in_the_history_grade_paths(self) -> None:
        # Every history-grade use of the criterion reads the named constant.
        checks = {
            "frontend/lib/league-analysis.js": [r"pct < 3\b", r"pctGap >= 3\b", r"pctGap <= -3\b"],
            "frontend/app/trades/page.jsx": [r"pctGap >= 3\b", r"Fair trade"],
            "src/public_league/trade_grading.py": [r"_GRADE_PCT_FAIR = 3"],
        }
        for rel, patterns in checks.items():
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            for pat in patterns:
                self.assertIsNone(re.search(pat, text), f"{rel} still has {pat!r}")


if __name__ == "__main__" and "--write" in sys.argv:
    REFERENCE_PATH.write_text(
        json.dumps(build_reference(), separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {REFERENCE_PATH}")
