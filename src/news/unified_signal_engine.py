"""Unified signal engine — single entry point for every BUY/SELL/HOLD
decision emitted to users.

Sources of signals (unified here):
    1. **Value movement** — rank / canonical-value drift over 7/30d.
    2. **Usage spikes** — snap / target / carry share z-scores
       (from src.news.usage_signals).
    3. **Injury status changes** — from src.nfl_data.injury_feed
       diff.
    4. **Transaction activity** — trades / waivers / adds on the
       player's team that affect their role.

Each raw signal is converted to a unified ``UnifiedSignal`` with:
    - verdict: "BUY" | "SELL" | "HOLD"
    - confidence: 0..1 float
    - severity: "low" | "medium" | "high"
    - source_class: the engine that emitted it
    - explanation: human-readable string

Cooldown is ONE cooldown table keyed on ``(user, league, signalKey)``
— multi-source signals for the same player don't spam the user
multiple times.  The existing src.api.signal_alerts cooldown
machinery is re-used so pre-migration state is preserved.

Severity scoring
----------------
Combines the raw signal strength with the player's roster impact
(are they a starter? tier-1? recently acquired?).  A rank-only
signal on a Tier-5 flex player is LOW severity; a usage-spike +
injury + depth-chart promotion on a starter is HIGH.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from src.api import feature_flags

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class UnifiedSignal:
    name: str
    pos: str
    sleeper_id: str
    verdict: str  # "BUY" | "SELL" | "HOLD"
    confidence: float  # 0..1
    severity: str  # "low" | "medium" | "high"
    source_class: str  # "value" | "usage" | "injury" | "transaction" | "composite"
    explanation: str
    tag: str  # short key: "usage_spike_snap", "value_drift_7d", ...
    signal_key: str  # stable identifier for cooldown
    alias_signal_key: str = ""
    dismissed: bool = False

    def to_legacy_shape(self) -> dict[str, Any]:
        """Convert to the dict shape the existing signal_alerts
        pipeline consumes so we can reuse its cooldown + state."""
        return {
            "name": self.name,
            "pos": self.pos,
            "sleeperId": self.sleeper_id,
            "signal": self.verdict,
            "reason": self.explanation,
            "tag": self.tag,
            "signalKey": self.signal_key,
            "aliasSignalKey": self.alias_signal_key,
            "confidence": round(self.confidence, 2),
            "severity": self.severity,
            "sourceClass": self.source_class,
            "dismissed": self.dismissed,
        }


@dataclass
class SignalCollector:
    """Accumulates signals per player and produces a composite."""
    signals_by_player: dict[str, list[UnifiedSignal]] = field(default_factory=dict)

    def add(self, sig: UnifiedSignal) -> None:
        key = sig.sleeper_id or sig.name
        self.signals_by_player.setdefault(key, []).append(sig)

    def resolve(self) -> list[UnifiedSignal]:
        """Dedupe multiple signals per player into a single
        composite when they agree on verdict, or keep separate
        when they conflict.  Bumps severity when multiple agree.
        """
        out: list[UnifiedSignal] = []
        for key, sigs in self.signals_by_player.items():
            if len(sigs) == 1:
                out.append(sigs[0])
                continue
            # Group by verdict.
            verdicts = {s.verdict for s in sigs}
            if len(verdicts) == 1:
                # All agree → composite with bumped severity.
                verdict = sigs[0].verdict
                sources = sorted({s.source_class for s in sigs})
                avg_conf = sum(s.confidence for s in sigs) / len(sigs)
                # Severity bumps: 1 source = inherit, 2+ = at least medium,
                # 3+ = high.
                sev_order = {"low": 1, "medium": 2, "high": 3}
                max_sev_val = max(sev_order[s.severity] for s in sigs)
                # Bump by the cross-source agreement.
                bump = min(len(sigs) - 1, 2)
                bumped_val = min(3, max_sev_val + bump)
                severity = {v: k for k, v in sev_order.items()}[bumped_val]
                exp = " + ".join(s.explanation for s in sigs)
                tag = "composite_" + "_".join(sources)
                out.append(UnifiedSignal(
                    name=sigs[0].name, pos=sigs[0].pos,
                    sleeper_id=sigs[0].sleeper_id,
                    verdict=verdict, confidence=avg_conf,
                    severity=severity, source_class="composite",
                    explanation=exp, tag=tag,
                    signal_key=f"{sigs[0].name}::{tag}",
                    alias_signal_key=(
                        f"sid:{sigs[0].sleeper_id}::{tag}"
                        if sigs[0].sleeper_id else ""
                    ),
                ))
            else:
                # Conflict — keep them separate so user sees both
                # perspectives.  Don't auto-resolve contradictions.
                out.extend(sigs)
        return out


def severity_from_confidence(
    confidence: float, *, starter: bool = False, tier: int | None = None,
) -> str:
    """Convert a 0..1 confidence + roster-role weight into a
    severity bucket."""
    weighted = confidence
    if starter:
        weighted += 0.15
    if tier is not None:
        if tier <= 2:
            weighted += 0.15
        elif tier <= 4:
            weighted += 0.05
    weighted = min(1.0, weighted)
    if weighted >= 0.75:
        return "high"
    if weighted >= 0.45:
        return "medium"
    return "low"


def value_movement_signal(
    *, name: str, sleeper_id: str, position: str,
    pct_change_7d: float, pct_change_30d: float,
    starter: bool = False, tier: int | None = None,
) -> UnifiedSignal | None:
    """Convert a 7/30d value drift into a BUY/SELL/HOLD signal.

    Thresholds:
      * |7d| >= 8% OR |30d| >= 15% → fire
      * positive = BUY, negative = SELL
    Returns None when below threshold.
    """
    abs7 = abs(pct_change_7d)
    abs30 = abs(pct_change_30d)
    if abs7 < 0.08 and abs30 < 0.15:
        return None
    # Use the larger magnitude signal as the confidence.
    mag = max(abs7, abs30 / 2.0)  # scale 30d to comparable range
    confidence = min(1.0, mag * 3.0)  # 33%+ movement = fully confident
    verdict = "BUY" if (pct_change_7d + pct_change_30d) > 0 else "SELL"
    severity = severity_from_confidence(confidence, starter=starter, tier=tier)
    reason = (
        f"Value {'up' if verdict == 'BUY' else 'down'} "
        f"{pct_change_7d*100:+.1f}% (7d) / {pct_change_30d*100:+.1f}% (30d)"
    )
    tag = "value_movement"
    return UnifiedSignal(
        name=name, pos=position, sleeper_id=sleeper_id,
        verdict=verdict, confidence=confidence, severity=severity,
        source_class="value", explanation=reason, tag=tag,
        signal_key=f"{name}::{tag}",
        alias_signal_key=f"sid:{sleeper_id}::{tag}" if sleeper_id else "",
    )


def usage_signal_to_unified(
    usage_signal_dict: dict[str, Any],
    *,
    starter: bool = False, tier: int | None = None,
) -> UnifiedSignal | None:
    """Wrap an existing usage_signals output in the unified shape."""
    if not isinstance(usage_signal_dict, dict):
        return None
    verdict = str(usage_signal_dict.get("signal") or "")
    if verdict not in ("BUY", "SELL"):
        return None
    # Z-scores convert to confidence: |z|=2 → 0.5, |z|=4 → 1.0.
    z_vals = [
        abs(usage_signal_dict.get("snap_pct_z") or 0),
        abs(usage_signal_dict.get("target_share_z") or 0),
        abs(usage_signal_dict.get("carry_share_z") or 0),
    ]
    max_z = max(z_vals)
    confidence = min(1.0, max_z / 4.0)
    severity = severity_from_confidence(confidence, starter=starter, tier=tier)
    tag = str(usage_signal_dict.get("tag") or "usage")
    name = str(usage_signal_dict.get("name") or usage_signal_dict.get("player_id") or "")
    sleeper_id = str(usage_signal_dict.get("sleeperId") or "")
    return UnifiedSignal(
        name=name, pos=str(usage_signal_dict.get("pos") or ""),
        sleeper_id=sleeper_id,
        verdict=verdict, confidence=confidence, severity=severity,
        source_class="usage",
        explanation=str(usage_signal_dict.get("reason") or ""),
        tag=tag,
        signal_key=f"{name}::{tag}",
        alias_signal_key=f"sid:{sleeper_id}::{tag}" if sleeper_id else "",
    )


def injury_signal_to_unified(
    injury_diff: dict[str, Any],
    *,
    sleeper_id_resolver: Callable[[str], str] | None = None,
    starter: bool = False, tier: int | None = None,
) -> UnifiedSignal | None:
    """Wrap an injury_feed.diff_for_signals output in the unified
    shape.  SELL on injury transitions.

    ``sleeper_id_resolver`` maps ESPN athlete IDs → Sleeper IDs.
    When absent, the signal fires but has empty sleeper_id.
    """
    if not isinstance(injury_diff, dict):
        return None
    transition = injury_diff.get("transition")
    if transition not in ("healthy_to_injured", "injury_worsened"):
        return None
    new_status = str(injury_diff.get("newStatus") or "")
    # Severity map: QUESTIONABLE < DOUBTFUL < OUT < IR.
    sev_map = {
        "DAY_TO_DAY": 0.3, "QUESTIONABLE": 0.4, "DOUBTFUL": 0.6,
        "OUT": 0.75, "PUP": 0.8, "IR": 0.95,
    }
    confidence = sev_map.get(new_status, 0.5)
    severity = severity_from_confidence(confidence, starter=starter, tier=tier)
    espn_id = str(injury_diff.get("espnAthleteId") or "")
    sleeper_id = sleeper_id_resolver(espn_id) if sleeper_id_resolver else ""
    name = str(injury_diff.get("name") or "")
    tag = f"injury_{transition}"
    return UnifiedSignal(
        name=name, pos=str(injury_diff.get("position") or ""),
        sleeper_id=sleeper_id,
        verdict="SELL", confidence=confidence, severity=severity,
        source_class="injury",
        explanation=str(injury_diff.get("reason") or ""),
        tag=tag,
        signal_key=f"{name}::{tag}",
        alias_signal_key=f"sid:{sleeper_id}::{tag}" if sleeper_id else "",
    )


def transaction_signal_to_unified(
    txn: dict[str, Any],
    *,
    starter: bool = False, tier: int | None = None,
) -> UnifiedSignal | None:
    """Convert a Sleeper transaction into a signal when it
    materially affects a roster player's role.

    Rules (conservative — false positives are annoying):
      * An ADD of a same-position starter on the player's team → SELL
        the incumbent (committee risk).
      * A DROP of a same-position starter → BUY the remaining
        player (monopolized touches).
      * TRADE AWAY of a same-position rotational piece → weak BUY.
    """
    if not isinstance(txn, dict):
        return None
    txn_type = str(txn.get("type") or "")
    if txn_type not in ("add", "drop", "trade_add", "trade_drop"):
        return None
    affected_name = str(txn.get("affectedPlayer") or "")
    affected_sid = str(txn.get("affectedSleeperId") or "")
    if not affected_name:
        return None
    verdict = str(txn.get("verdict") or "")  # caller decides
    if verdict not in ("BUY", "SELL"):
        return None
    confidence = float(txn.get("confidence") or 0.4)
    severity = severity_from_confidence(confidence, starter=starter, tier=tier)
    tag = f"transaction_{txn_type}"
    return UnifiedSignal(
        name=affected_name, pos=str(txn.get("position") or ""),
        sleeper_id=affected_sid,
        verdict=verdict, confidence=confidence, severity=severity,
        source_class="transaction",
        explanation=str(txn.get("reason") or f"Transaction {txn_type}"),
        tag=tag,
        signal_key=f"{affected_name}::{tag}",
        alias_signal_key=f"sid:{affected_sid}::{tag}" if affected_sid else "",
    )


def process_user_signals_unified(
    signals: Iterable[UnifiedSignal],
) -> list[UnifiedSignal]:
    """Entry point — dedupes, resolves composites, returns the
    final emission list.  Does NOT apply cooldown (existing
    signal_alerts machinery owns that); does NOT deliver.
    """
    collector = SignalCollector()
    for s in signals:
        collector.add(s)
    return collector.resolve()
