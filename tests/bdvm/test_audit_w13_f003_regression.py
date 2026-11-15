"""CW-40 / master-site-audit W13-F003 regression evidence (P1).

Finding: the BDVM signal layer saturates.  ``DynastyEngine.calibrate`` anchors only
the board MAXIMUM to ``target_top_value`` while ``signal_thresholds`` are absolute
point values (+/-400, +/-900), so a fundamental board whose median sits far below
the market's reads STRONG_SELL almost everywhere (570 of 699 priced players).

Adjudication (docs/audits/remediation_2026-11-06/CW40_P1_OPEN_ADJUDICATION.md): OPEN.

The calibration (``engine.py::calibrate``), the gap/alpha arithmetic
(``market.py::market_comparison``) and the thresholds
(``config/bdvm/params_v1.json`` ``market.signal_thresholds``) are unchanged in kind
since the audit.  A full live re-run needs the nflverse weekly feed (network), so
this test does the next best deterministic thing: it feeds the audit's RECORDED
per-player ``tradeValue`` / ``market`` blocks
(``docs/master-site-audit/evidence/W13/engine-live-run.json``, tracked) through the
CURRENT ``market_comparison`` + ``buy_hold_sell`` and the recorded collapse
probability.  Inputs are frozen; the logic under test is today's.  Measured on
current main this reproduces the audit's counts exactly (570 STRONG_SELL / 69 HOLD /
23 NO_MARKET / 14 BUY / 13 SELL / 10 STRONG_BUY).

It cannot say the live board of today still saturates; it says no code since the
audit would stop it.  Flips (strict xfail) when a repair changes the signal logic;
a repair confined to engine calibration needs a re-run of the evidence script
against a pinned input and an updated artifact.
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

import pytest

from src.bdvm.market import MarketView, buy_hold_sell, market_comparison
from src.bdvm.params import load_param_set

EVIDENCE = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "master-site-audit"
    / "evidence"
    / "W13"
    / "engine-live-run.json"
)
PARAMS = load_param_set("params_v1")
IDP_GROUPS = ("DL", "LB", "DB")


def _signal_counts() -> collections.Counter:
    data = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    counts: collections.Counter = collections.Counter()
    for p in data["players"]:
        m = p.get("market") or {}
        if m.get("marketValue") is None:
            counts["NO_MARKET"] += 1
            continue
        view = MarketView(
            market_value=m["marketValue"],
            market_source=m["marketSource"],
            market_type=m["marketType"],
            dispersion=m["marketDispersion"],
            liquidity=m["liquidity"],
        )
        out = market_comparison(
            p["tradeValue"],
            view,
            PARAMS,
            is_idp=p["group"] in IDP_GROUPS,
            is_rookie=bool((p.get("projection") or {}).get("isRookie")),
        )
        sig = buy_hold_sell(
            out, PARAMS, p_collapse_1y=(p.get("probs") or {}).get("p_value_collapse_1y")
        )
        counts[sig["signal"]] += 1
    return counts


def test_signal_ladder_control_is_magnitude_ordered():
    """Control: the ladder itself behaves as documented, so the test below is not
    failing for a harness reason."""
    base = {"liquidity": 0.9, "liquidityMeasured": True}
    assert buy_hold_sell({**base, "alpha": -1000.0}, PARAMS)["signal"] == "STRONG_SELL"
    assert buy_hold_sell({**base, "alpha": -500.0}, PARAMS)["signal"] == "SELL"
    assert buy_hold_sell({**base, "alpha": 0.0}, PARAMS)["signal"] == "HOLD"
    assert buy_hold_sell({**base, "alpha": 500.0}, PARAMS)["signal"] == "BUY"
    assert buy_hold_sell({"alpha": None}, PARAMS)["signal"] == "NO_MARKET"


@pytest.mark.skipif(not EVIDENCE.exists(), reason="recorded W13 engine run absent")
@pytest.mark.xfail(
    strict=True,
    reason="W13-F003: absolute alpha thresholds vs top-only calibration -> >80% STRONG_SELL",
)
def test_signal_distribution_is_not_saturated():
    counts = _signal_counts()
    market_anchored = sum(counts.values()) - counts["NO_MARKET"]
    assert market_anchored > 600, "harness drift: the recorded run lost its market-anchored rows"
    share = counts["STRONG_SELL"] / market_anchored
    # A sell call that fires on the large majority of the board carries no
    # information.  The 0.5 bound is a tripwire, not a methodology: the target
    # distribution is an owner/evidence decision.
    assert share <= 0.5, f"STRONG_SELL share {share:.3f} of {market_anchored}: {dict(counts)}"
