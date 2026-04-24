"""Tests for the unified signal engine."""
from __future__ import annotations

from src.news import unified_signal_engine as ue


def test_severity_from_confidence_base():
    assert ue.severity_from_confidence(0.2) == "low"
    assert ue.severity_from_confidence(0.6) == "medium"
    assert ue.severity_from_confidence(0.85) == "high"


def test_severity_bumps_for_starter():
    # 0.4 → low on its own, medium if starter + tier 1.
    assert ue.severity_from_confidence(0.40) == "low"
    assert ue.severity_from_confidence(0.40, starter=True, tier=1) in ("medium", "high")


def test_value_movement_below_threshold_is_none():
    sig = ue.value_movement_signal(
        name="X", sleeper_id="1", position="WR",
        pct_change_7d=0.03, pct_change_30d=0.05,
    )
    assert sig is None


def test_value_movement_positive_fires_buy():
    sig = ue.value_movement_signal(
        name="X", sleeper_id="1", position="WR",
        pct_change_7d=0.12, pct_change_30d=0.20,
    )
    assert sig is not None
    assert sig.verdict == "BUY"
    assert sig.source_class == "value"


def test_value_movement_negative_fires_sell():
    sig = ue.value_movement_signal(
        name="X", sleeper_id="1", position="WR",
        pct_change_7d=-0.12, pct_change_30d=-0.20,
    )
    assert sig.verdict == "SELL"


def test_usage_signal_converts_correctly():
    raw = {
        "signal": "BUY", "tag": "usage_spike_snap",
        "name": "Player", "pos": "WR", "sleeperId": "1",
        "snap_pct_z": 3.0, "target_share_z": None, "carry_share_z": None,
        "reason": "Snap spike",
    }
    sig = ue.usage_signal_to_unified(raw)
    assert sig is not None
    assert sig.verdict == "BUY"
    assert sig.source_class == "usage"
    assert sig.confidence > 0.5


def test_usage_non_actionable_returns_none():
    raw = {"signal": "HOLD", "name": "X"}
    assert ue.usage_signal_to_unified(raw) is None


def test_injury_transition_fires_sell():
    diff = {
        "transition": "healthy_to_injured",
        "newStatus": "OUT",
        "espnAthleteId": "3918298",
        "name": "Josh Allen",
        "position": "QB",
        "reason": "New injury",
    }
    sig = ue.injury_signal_to_unified(diff, sleeper_id_resolver=lambda _: "4017")
    assert sig is not None
    assert sig.verdict == "SELL"
    assert sig.source_class == "injury"
    assert sig.sleeper_id == "4017"


def test_injury_ir_status_is_high_severity():
    diff = {
        "transition": "healthy_to_injured",
        "newStatus": "IR",
        "espnAthleteId": "1",
        "name": "X", "position": "RB",
        "reason": "IR placement",
    }
    sig = ue.injury_signal_to_unified(diff, starter=True, tier=1)
    assert sig.severity == "high"


def test_transaction_signal_fires():
    txn = {
        "type": "add",
        "affectedPlayer": "Incumbent",
        "affectedSleeperId": "1",
        "position": "RB",
        "verdict": "SELL",
        "confidence": 0.6,
        "reason": "Same-pos starter added on team",
    }
    sig = ue.transaction_signal_to_unified(txn)
    assert sig is not None
    assert sig.verdict == "SELL"
    assert sig.source_class == "transaction"


def test_unified_composite_bumps_severity_on_agreement():
    # Three sources all saying SELL on same player → composite
    # with bumped severity + explanation combining all.
    value = ue.value_movement_signal(
        name="Player", sleeper_id="1", position="WR",
        pct_change_7d=-0.15, pct_change_30d=-0.25,
    )
    usage = ue.usage_signal_to_unified({
        "signal": "SELL", "tag": "usage_drop_snap",
        "name": "Player", "pos": "WR", "sleeperId": "1",
        "snap_pct_z": -3.5, "reason": "Snap drop",
    })
    injury = ue.injury_signal_to_unified(
        {
            "transition": "injury_worsened", "newStatus": "OUT",
            "espnAthleteId": "1", "name": "Player", "position": "WR",
            "reason": "Q → Out",
        },
        sleeper_id_resolver=lambda _: "1",
    )
    unified = ue.process_user_signals_unified([value, usage, injury])
    # All three agreed on SELL — one composite emitted.
    assert len(unified) == 1
    assert unified[0].source_class == "composite"
    assert unified[0].verdict == "SELL"
    assert unified[0].severity == "high"


def test_unified_conflict_keeps_signals_separate():
    # Value says BUY, injury says SELL — don't auto-resolve.
    v = ue.value_movement_signal(
        name="P", sleeper_id="1", position="WR",
        pct_change_7d=0.15, pct_change_30d=0.25,
    )
    i = ue.injury_signal_to_unified(
        {
            "transition": "healthy_to_injured", "newStatus": "OUT",
            "espnAthleteId": "1", "name": "P", "position": "WR",
            "reason": "injury",
        },
        sleeper_id_resolver=lambda _: "1",
    )
    unified = ue.process_user_signals_unified([v, i])
    # Two signals, opposite verdicts → kept separate.
    assert len(unified) == 2
    verdicts = {s.verdict for s in unified}
    assert verdicts == {"BUY", "SELL"}


def test_legacy_shape_compatible_with_signal_alerts():
    """to_legacy_shape output must be consumable by
    detect_signal_transitions — same key names."""
    sig = ue.value_movement_signal(
        name="X", sleeper_id="1", position="QB",
        pct_change_7d=0.12, pct_change_30d=0.20,
    )
    shape = sig.to_legacy_shape()
    # Keys the existing signal_alerts pipeline reads.
    for k in ("name", "pos", "signal", "reason", "tag", "signalKey",
              "aliasSignalKey", "sleeperId", "dismissed"):
        assert k in shape
