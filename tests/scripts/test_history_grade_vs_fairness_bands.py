"""Pin ``scripts/history_grade_vs_fairness_bands.py`` (OD-F6 measurement, read-only).

Synthetic inputs only.  What is pinned:

* the report is AGGREGATE-ONLY -- hostile labels / ids in the input never reach it, and the
  guard refuses free text;
* no band threshold is hard-coded in the script (the owner and the history module are
  CALLED), and the owner's classifier is what decides the band side;
* deterministic output;
* MISSING IS NEVER ZERO -- a trade with any missing / non-finite / non-positive asset value
  is counted as not gradable and excluded, never priced at 0;
* the measurement itself on hand-built cases, derived from the owners' own constants.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import math
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "history_grade_vs_fairness_bands.py"
_spec = importlib.util.spec_from_file_location("history_grade_vs_fairness_bands", SCRIPT)
hg = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(hg)

from src.public_league import trade_grading as tg  # noqa: E402
from src.valuation_math import fairness_bands as fb  # noqa: E402


def _one_for_one(got: float, gave: float, pick: bool = False) -> dict:
    return {
        "sides": [{"got": [got], "gave": [gave]}, {"got": [gave], "gave": [got]}],
        "hasPick": pick,
    }


def _gave_for_pct(pct: float, got: float = 100_000.0) -> float:
    """A 1v1 where the receiving side's gap is ``pct`` of the larger side (large values, so
    the owner's absolute floor is far below the gap)."""
    return got * (1 + pct / 100.0)


# ── the measurement on hand-built cases ───────────────────────────────────


def test_between_the_two_fair_cuts_history_is_stricter_than_the_owner() -> None:
    mid = (tg._GRADE_PCT_FAIR + fb.SLIGHT_PCT) / 2.0
    rep = hg.evaluate([_one_for_one(100_000.0, _gave_for_pct(mid))])
    side = rep["sideLevel"]
    assert rep["census"]["gradable"] == 1
    assert side["sides"] == 2
    assert side["historyFair"] == 0 and side["ownerFair"] == 2
    assert side["historyNotFairOwnerFair"] == 2 and side["historyFairOwnerNotFair"] == 0
    assert side["fairClassificationDiffers"] == 2
    # the only grade bucket that moves is the fair boundary, and it moves toward "Fair trade"
    assert side["gradeBucketChangesIfOnlyFairIsOwners"] == 2
    assert side["gradeBucketChangeDirection"] == {"fairToNotFair": 0, "notFairToFair": 2}
    assert rep["tradeLevel"]["historyNotFairOwnerFair"] == 1
    assert rep["sideLevel"]["decomposition"]["1_relativeCutChange"]["notFairToFair"] == 2


def test_below_the_absolute_floor_the_owner_is_fair_where_history_is_not() -> None:
    # a 1v1 whose gap is under the owner's floor but ABOVE the history fair cut
    small = fb.ABSOLUTE_MINIMUM / 2.0
    # a base so the relative gap exceeds BOTH relative fair cuts yet |gap| < the floor
    base = small / (fb.UNFAIR_PCT / 100.0)
    rep = hg.evaluate([_one_for_one(base, base + small)])
    side = rep["sideLevel"]
    assert side["historyFair"] == 0 and side["ownerFair"] == 2
    assert rep["absoluteFloor"]["sidesBelowFloor"] == 2
    assert rep["absoluteFloor"]["ownerFairOnlyBecauseOfFloor"] == 2
    assert side["decomposition"]["2_absoluteFloorAdded"]["notFairToFair"] == 2
    assert rep["byAbsGap"]["below_1x_floor"]["sides"] == 2


def test_above_both_cuts_the_two_agree_on_not_fair() -> None:
    rep = hg.evaluate([_one_for_one(100_000.0, _gave_for_pct(fb.UNFAIR_PCT * 2))])
    side = rep["sideLevel"]
    assert side["fairClassificationDiffers"] == 0
    assert side["historyFair"] == 0 and side["ownerFair"] == 0
    assert side["gradeBucketChangesIfOnlyFairIsOwners"] == 0
    assert rep["twoTeamAsymmetries"] == 0 and rep["gapAgreementFailures"] == 0


def test_deep_package_denominator_makes_the_owner_stricter() -> None:
    # 3 pieces for 1: the package utility discounts depth, so the owner's base is smaller
    # than the history grade's effective-side denominator
    trade = {
        "sides": [
            {"got": [9000.0], "gave": [4000.0, 3000.0, 2500.0]},
            {"got": [4000.0, 3000.0, 2500.0], "gave": [9000.0]},
        ],
        "hasPick": False,
    }
    rep = hg.evaluate([trade])
    ratio = rep["packageUtilityOverHistoryScale"]
    assert ratio is not None and ratio["median"] < 1.0
    assert rep["byShape"]["larger_two_team"]["sides"] == 2


def test_winners_and_losers_rule_follows_each_definition() -> None:
    mid = (tg._GRADE_PCT_FAIR + fb.SLIGHT_PCT) / 2.0
    rep = hg.evaluate([_one_for_one(100_000.0, _gave_for_pct(mid))])
    wl = rep["sideLevel"]["winnersLosers"]
    assert (wl["historyWins"], wl["historyLosses"]) == (1, 1)
    assert (wl["ownerWins"], wl["ownerLosses"]) == (0, 0)
    assert wl["sidesWithChangedStatus"] == 2
    assert wl["historyStatusToOwnerStatus"] == {"loss>none": 1, "win>none": 1}


# ── MISSING IS NEVER ZERO ─────────────────────────────────────────────────


@pytest.mark.parametrize("bad", [None, math.nan, math.inf, 0.0, -5.0, True, "7"])
def test_a_missing_value_makes_the_trade_not_gradable_and_excluded(bad) -> None:
    good = _one_for_one(100_000.0, _gave_for_pct(20))
    broken = {
        "sides": [{"got": [bad, 5000.0], "gave": [6000.0]}, {"got": [6000.0], "gave": [5000.0]}],
        "hasPick": False,
    }
    rep = hg.evaluate([good, broken])
    assert rep["census"]["trades"] == 2
    assert rep["census"]["gradable"] == 1
    assert rep["census"]["notGradable"] == 1
    assert rep["census"]["notGradable_unpriced_asset"] == 1
    # exactly the good trade's two sides were measured: the broken one was not coerced
    assert rep["sideLevel"]["sides"] == 2
    assert rep["tradeLevel"]["trades"] == 1


def test_malformed_trades_are_counted_not_crashed() -> None:
    rep = hg.evaluate([{"sides": None}, {"sides": [{"got": [1.0], "gave": [1.0]}]}, {}])
    assert rep["census"].get("gradable", 0) == 0
    assert rep["census"]["notGradable"] == 3
    assert rep["sideLevel"]["sides"] == 0
    assert rep["tradeLevel"]["shareFairClassificationDiffers"] is None


def test_priced_trades_with_an_unresolvable_label_are_not_gradable() -> None:
    def price(label: str):
        return (None, "player") if "UNKNOWN" in label else (10_000.0, "player")

    raw = [
        {"sides": [{"got": ["A"], "gave": ["B"]}, {"got": ["B"], "gave": ["A"]}]},
        {"sides": [{"got": ["UNKNOWN X"], "gave": ["B"]}, {"got": ["B"], "gave": ["C"]}]},
    ]
    rep = hg.evaluate(hg.price_trades(raw, price))
    assert rep["census"]["gradable"] == 1 and rep["census"]["notGradable"] == 1


# ── aggregate-only ────────────────────────────────────────────────────────

SENTINELS = ("SENTINEL_TEAM_ZED", "SENTINEL_MGR_QUX", "SENTINEL_ID_000", "Player Label Alpha")


def test_report_carries_no_input_label_or_identifier() -> None:
    raw = [
        {
            "leagueId": "SENTINEL_ID_001",
            "sides": [
                {
                    "team": SENTINELS[0],
                    "ownerId": SENTINELS[2],
                    "got": [SENTINELS[3] + " (from " + SENTINELS[1] + ")"],
                    "gave": ["2029 Mid 1st (from " + SENTINELS[1] + ")"],
                },
                {
                    "team": SENTINELS[1],
                    "ownerId": SENTINELS[2],
                    "got": ["2029 Mid 1st (from " + SENTINELS[1] + ")"],
                    "gave": [SENTINELS[3]],
                },
            ],
        }
    ]

    def price(label: str):
        return (12_000.0 if "1st" in label else 9_000.0), ("pick" if "1st" in label else "offense")

    rep = hg.build_report(
        {
            "own": {
                "description": hg.NOTES["population"],
                **hg.evaluate(hg.price_trades(raw, price)),
            }
        },
        hg.common_meta(),
    )
    text = json.dumps(rep)
    for needle in SENTINELS:
        assert needle not in text
    assert rep["populations"]["own"]["byPicks"]["includes_pick"]["sides"] == 2


def test_guard_refuses_free_text_and_odd_keys() -> None:
    with pytest.raises(ValueError):
        hg.assert_aggregate_only({"note": "Brent traded his 2029 first"})
    with pytest.raises(ValueError):
        hg.assert_aggregate_only({"path": "has space.txt"})
    with pytest.raises(ValueError):
        hg.assert_aggregate_only({"Some Team Name!": 1})
    with pytest.raises(ValueError):
        hg.assert_aggregate_only({"x": object()})
    # fixed vocabulary and provenance pins are accepted
    hg.assert_aggregate_only(
        {"level": "fair", "label": "Evenly valued", "path": "data/sleeper_last_good.json", "n": 3}
    )


# ── no hard-coded thresholds; the owners decide ───────────────────────────


def _numbers(tree: ast.AST) -> set[float]:
    """Numeric literals that could be a threshold.  A small integer literal (a piece
    count, a quantile index) is not one -- ``3`` is the history fair cut only as a
    FLOAT percentage -- so integers below 8 are not collected."""
    return {
        float(n.value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, (int, float))
        and not isinstance(n.value, bool)
        and not (isinstance(n.value, int) and n.value < 8)
    }


def test_no_band_or_grade_threshold_is_hard_coded_in_the_script() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    forbidden = {
        float(x)
        for x in (
            fb.ABSOLUTE_MINIMUM,
            fb.SLIGHT_PCT,
            fb.UNFAIR_PCT,
            fb.LOPSIDED_PCT,
            *hg.history_cut_points(),
            fb.SLIGHT_PCT / 100.0,
            fb.UNFAIR_PCT / 100.0,
            fb.LOPSIDED_PCT / 100.0,
        )
    }
    assert forbidden & _numbers(tree) == set()


def test_the_script_calls_the_owners() -> None:
    src = SCRIPT.read_text(encoding="utf-8")
    for needle in (
        "fb.classify_packages(",
        "fb.larger_package_utility(",
        "fb.counts_as_fair_trade(",
        "tg.grade_trade_sides(",
        "tg.grade_from_pct(",
    ):
        assert needle in src
    # grading and band code are imported, never re-implemented here
    defs = {n.name for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef)}
    assert not defs & {"classify", "grade_from_pct", "grade_trade_side", "grade_trade_sides"}


def test_the_owners_were_not_modified_by_the_measurement() -> None:
    before = (fb.receipt(), hg.history_cut_points())
    hg.evaluate([_one_for_one(100_000.0, _gave_for_pct(5))])
    assert (fb.receipt(), hg.history_cut_points()) == before


# ── determinism / synthetic generator ─────────────────────────────────────


def test_synthetic_generator_and_report_are_deterministic() -> None:
    pool = [float(v) for v in range(500, 9000, 37)]
    a = hg.synthetic_trades(pool, 25, seed=7)
    b = hg.synthetic_trades(pool, 25, seed=7)
    c = hg.synthetic_trades(pool, 25, seed=8)
    assert a == b and a != c
    ra = json.dumps(hg.evaluate(a), sort_keys=True)
    rb = json.dumps(hg.evaluate(b), sort_keys=True)
    assert ra == rb
    # every synthetic trade is fully priced, so none is excluded
    assert hg.evaluate(a)["census"]["gradable"] == 25


def test_gap_bins_are_a_ruler_on_the_owners_floor() -> None:
    floor = fb.ABSOLUTE_MINIMUM
    assert hg.gap_bin(0.0) == "below_1x_floor"
    assert hg.gap_bin(floor * 0.999) == "below_1x_floor"
    assert hg.gap_bin(floor) == "1x_to_2x_floor"
    assert (
        hg.gap_bin(floor * hg.GAP_BIN_MULTIPLES[-1]) == f"{hg.GAP_BIN_MULTIPLES[-1]}x_or_more_floor"
    )


def test_the_floor_makes_fair_non_monotone_in_the_history_margin() -> None:
    small = fb.ABSOLUTE_MINIMUM / 2.0
    tiny = _one_for_one(small / (fb.UNFAIR_PCT / 100.0), small / (fb.UNFAIR_PCT / 100.0) + small)
    big = _one_for_one(100_000.0, _gave_for_pct(fb.SLIGHT_PCT * 1.5))
    fbnd = hg.evaluate([tiny, big])["sideLevel"]["fairBoundary"]
    assert fbnd["ownerFairMaxPct"] > fbnd["ownerNotFairMinPct"]
    assert fbnd["ownerNotFairSidesBelowOwnerFairMax"] == 2


def test_asset_census_counts_only() -> None:
    from collections import Counter

    census: Counter = Counter()
    raw = [
        {"sides": [{"got": ["Secret Name"], "gave": ["2030 Early 2nd"]}, {"got": [], "gave": []}]}
    ]
    hg.price_trades(
        raw, lambda lab: (None, "pick") if lab[:1].isdigit() else (5.0, "offense"), census
    )
    assert dict(census) == {"assets": 2, "unpriced": 1, "unpriced_class_pick": 1}


def test_empty_population_does_not_divide_by_zero() -> None:
    rep = hg.evaluate([])
    assert rep["sideLevel"]["sides"] == 0
    assert rep["tradeLevel"]["trades"] == 0
    assert rep["absoluteFloor"]["shareBelowFloor"] is None
