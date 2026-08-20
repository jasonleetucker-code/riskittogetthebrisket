"""Evidence-extractor tests for src.signals.families (C6-SIG-01).

Each extractor is tested for the MISSING-IS-NEVER-ZERO boundary that
matters most for it: what upstream value means "absent" and must
produce ``None`` rather than a fabricated neutral vote.
"""

from __future__ import annotations

from src.analyst.stance import Direction
from src.signals.families import (
    bdvm_fundamental_family,
    board_consensus_gap_family,
    sharp_transaction_family,
)


# ── board_consensus_gap_family ──────────────────────────────────────────


def test_board_gap_none_direction_is_absent():
    assert board_consensus_gap_family({"marketGapDirection": "none"}) is None


def test_board_gap_missing_direction_is_absent():
    assert board_consensus_gap_family({}) is None


def test_board_gap_missing_ratio_is_absent():
    assert board_consensus_gap_family({"marketGapDirection": "consensus_premium"}) is None


def test_board_gap_consensus_premium_is_buy():
    ev = board_consensus_gap_family(
        {"marketGapDirection": "consensus_premium", "marketGapValueRatio": 0.2}
    )
    assert ev is not None
    assert ev.direction == Direction.BUY_SIDE


def test_board_gap_retail_premium_is_sell():
    ev = board_consensus_gap_family(
        {"marketGapDirection": "retail_premium", "marketGapValueRatio": 0.2}
    )
    assert ev is not None
    assert ev.direction == Direction.SELL_SIDE


def test_board_gap_magnitude_clamps_to_one():
    ev = board_consensus_gap_family(
        {"marketGapDirection": "retail_premium", "marketGapValueRatio": 5.0}
    )
    assert ev is not None
    assert ev.magnitude == 1.0


def test_board_gap_passes_through_caller_supplied_freshness():
    ev = board_consensus_gap_family(
        {"marketGapDirection": "retail_premium", "marketGapValueRatio": 0.2},
        fresh=False,
    )
    assert ev is not None
    assert ev.fresh is False


# ── bdvm_fundamental_family ─────────────────────────────────────────────


def test_bdvm_none_input_is_absent():
    assert bdvm_fundamental_family(None) is None


def test_bdvm_no_market_is_absent():
    assert bdvm_fundamental_family({"signal": "NO_MARKET", "reason": "no anchor"}) is None


def test_bdvm_hold_is_absent():
    """HOLD is a real BDVM answer ('inside the hold band') and must not
    become a directional vote for either side."""
    assert bdvm_fundamental_family({"signal": "HOLD", "reason": "inside band"}) is None


def test_bdvm_strong_buy_outranks_plain_buy_in_magnitude():
    strong = bdvm_fundamental_family({"signal": "STRONG_BUY", "reason": "x"})
    plain = bdvm_fundamental_family({"signal": "BUY", "reason": "x"})
    assert strong is not None and plain is not None
    assert strong.magnitude > plain.magnitude
    assert strong.direction == Direction.BUY_SIDE
    assert plain.direction == Direction.BUY_SIDE


def test_bdvm_sell_side():
    ev = bdvm_fundamental_family({"signal": "STRONG_SELL", "reason": "x"})
    assert ev is not None
    assert ev.direction == Direction.SELL_SIDE


def test_bdvm_shared_anchor_is_only_recorded_when_supplied():
    with_anchor = bdvm_fundamental_family(
        {"signal": "BUY", "reason": "x"}, shared_anchor="ktcSfTep"
    )
    without_anchor = bdvm_fundamental_family({"signal": "BUY", "reason": "x"})
    assert with_anchor is not None and without_anchor is not None
    assert with_anchor.provenance.get("sharedAnchors") == ["ktcSfTep"]
    assert "sharedAnchors" not in without_anchor.provenance


# ── sharp_transaction_family ────────────────────────────────────────────


def test_sharp_none_input_is_absent():
    assert sharp_transaction_family(None) is None


def test_sharp_insufficient_confidence_is_absent():
    row = {"confidence": "insufficient", "net": 10, "signalStrength": 50}
    assert sharp_transaction_family(row) is None


def test_sharp_zero_net_is_absent():
    """No directional lean at all -- not a HOLD vote, an absence."""
    row = {"confidence": "medium", "net": 0, "signalStrength": 50}
    assert sharp_transaction_family(row) is None


def test_sharp_positive_net_is_buy():
    row = {"confidence": "high", "net": 5, "signalStrength": 60}
    ev = sharp_transaction_family(row)
    assert ev is not None
    assert ev.direction == Direction.BUY_SIDE


def test_sharp_negative_net_is_sell():
    row = {"confidence": "high", "net": -5, "signalStrength": 60}
    ev = sharp_transaction_family(row)
    assert ev is not None
    assert ev.direction == Direction.SELL_SIDE


def test_sharp_freshness_none_when_no_timestamp():
    row = {"confidence": "high", "net": 5, "signalStrength": 60, "lastTs": None}
    ev = sharp_transaction_family(row)
    assert ev is not None
    assert ev.fresh is None


def test_sharp_freshness_true_within_budget():
    now_ms = 1_000_000_000_000
    row = {
        "confidence": "high",
        "net": 5,
        "signalStrength": 60,
        "lastTs": now_ms - 3_600_000,  # 1 hour ago
    }
    ev = sharp_transaction_family(row, now_ms=now_ms)
    assert ev is not None
    assert ev.fresh is True


def test_sharp_freshness_false_outside_budget():
    now_ms = 1_000_000_000_000
    ten_days_ms = 10 * 24 * 3_600_000
    row = {
        "confidence": "high",
        "net": 5,
        "signalStrength": 60,
        "lastTs": now_ms - ten_days_ms,
    }
    ev = sharp_transaction_family(row, now_ms=now_ms)
    assert ev is not None
    assert ev.fresh is False
