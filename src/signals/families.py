"""Evidence extractors — one function per wired family (C6-SIG-01).

Each function turns ONE upstream system's raw, already-computed output
into a :class:`src.signals.reconciler.SignalFamilyEvidence`, or ``None``
when that system has no opinion on this asset. ``None`` is the
MISSING-IS-NEVER-ZERO case: an absent family is never coerced into a
neutral vote.

None of these functions RECOMPUTES anything. They read fields already
stamped by their family's own canonical owner:

  * ``board_consensus_gap_family`` reads ``marketGapDirection`` /
    ``marketGapValueRatio`` off a ``/api/data`` contract row, already
    computed by ``src.api.data_contract._compute_market_gap``.
  * ``bdvm_fundamental_family`` reads ``src.bdvm.market.buy_hold_sell``'s
    own ``{"signal": ..., "reason": ...}`` output verbatim.
  * ``sharp_transaction_family`` reads one row of
    ``src.sharp.market.market_payload()["assets"]`` verbatim.
    **Read-only** — nothing in this module writes to ``src/sharp/``.
"""

from __future__ import annotations

import time
from typing import Any

from src.signals.reconciler import Direction, SignalFamilyEvidence, gate_parameter

__all__ = [
    "bdvm_fundamental_family",
    "board_consensus_gap_family",
    "sharp_transaction_family",
]

#: Retail(KTC)-vs-consensus direction, per
#: src.api.data_contract._compute_market_gap's own docstring: a
#: consensus premium means the experts value the player MORE than
#: retail — a potential buy-low; a retail premium means retail prices
#: the player above the experts — a potential sell-into-hype.
_BOARD_GAP_DIRECTION = {
    "consensus_premium": Direction.BUY_SIDE,
    "retail_premium": Direction.SELL_SIDE,
}


def board_consensus_gap_family(
    contract_row: dict[str, Any],
    *,
    fresh: bool | None = None,
) -> SignalFamilyEvidence | None:
    """Family from the existing market-gap stamp on a contract row.

    Returns ``None`` when ``marketGapDirection`` is ``"none"`` or absent
    — ``_compute_market_gap`` already means "no comparison was possible"
    by that value, and this function does not reinterpret it.

    ``fresh`` is supplied by the caller (typically from
    ``src.api.data_contract._source_freshness_flags()``'s retail-key
    entry) rather than re-derived here, so this module never re-reads
    source timestamps a canonical owner has already computed.
    """
    direction = _BOARD_GAP_DIRECTION.get(str(contract_row.get("marketGapDirection") or ""))
    if direction is None:
        return None
    ratio = contract_row.get("marketGapValueRatio")
    if ratio is None:
        return None
    magnitude = min(1.0, abs(float(ratio)))
    return SignalFamilyEvidence(
        family="board_consensus_gap",
        direction=direction,
        magnitude=magnitude,
        family_confidence="high" if magnitude >= gate_parameter("STRONG_MAGNITUDE_THRESHOLD") else "medium",
        fresh=fresh,
        provenance={
            "marketGapDirection": contract_row.get("marketGapDirection"),
            "marketGapValueRatio": ratio,
        },
    )


def bdvm_fundamental_family(
    bdvm_signal: dict[str, Any] | None,
    *,
    fresh: bool | None = None,
    shared_anchor: str | None = None,
) -> SignalFamilyEvidence | None:
    """Family from ``src.bdvm.market.buy_hold_sell``'s own output.

    ``bdvm_signal`` is that function's verbatim ``{"signal": ...,
    "reason": ...}`` return value, or ``None`` when BDVM did not run for
    this asset at all. ``NO_MARKET`` and ``HOLD`` both return ``None``
    here — BDVM's own contract already means "no anchor" / "inside the
    hold band, no material lean" by those values, so nothing about this
    family should count as evidence for either direction.

    ``shared_anchor``, when the caller knows this row's BDVM market
    anchor is the same retail source ``board_consensus_gap`` used
    (typically ``"ktcSfTep"``), is recorded in provenance so the
    reconciler can declare — never silently collapse — the overlap.
    """
    if not bdvm_signal:
        return None
    signal = str(bdvm_signal.get("signal") or "")
    if signal in ("STRONG_BUY", "BUY"):
        direction = Direction.BUY_SIDE
    elif signal in ("STRONG_SELL", "SELL"):
        direction = Direction.SELL_SIDE
    else:
        return None
    magnitude = (
        gate_parameter("BDVM_STRONG_SIGNAL_MAGNITUDE")
        if signal.startswith("STRONG_")
        else gate_parameter("BDVM_PLAIN_SIGNAL_MAGNITUDE")
    )
    provenance: dict[str, Any] = {"signal": signal, "reason": bdvm_signal.get("reason")}
    if shared_anchor:
        provenance["sharedAnchors"] = [shared_anchor]
    return SignalFamilyEvidence(
        family="bdvm_fundamental",
        direction=direction,
        magnitude=float(magnitude),
        family_confidence="high" if signal.startswith("STRONG_") else "medium",
        fresh=fresh,
        provenance=provenance,
    )


def sharp_transaction_family(
    sharp_row: dict[str, Any] | None,
    *,
    now_ms: int | None = None,
) -> SignalFamilyEvidence | None:
    """Family from one row of ``src.sharp.market.market_payload()``.

    Read-only: this function only reads fields already computed by
    ``src.sharp.market``; it never calls into or modifies anything
    under ``src/sharp/``.

    Returns ``None`` when the row's own ``confidence`` tier (from
    ``src.sharp.signals.confidence_tier``) is ``"insufficient"`` — an
    under-sampled cohort reading contributes no vote, matching
    ``sharp/market.py``'s own MISSING-IS-NEVER-ZERO posture — or when
    ``net`` is exactly zero (no directional lean at all).
    """
    if not sharp_row:
        return None
    tier = str(sharp_row.get("confidence") or "")
    if tier == "insufficient" or not tier:
        return None
    net = sharp_row.get("net")
    if net is None or int(net) == 0:
        return None
    direction = Direction.BUY_SIDE if int(net) > 0 else Direction.SELL_SIDE
    strength = sharp_row.get("signalStrength")
    magnitude = min(1.0, abs(float(strength)) / gate_parameter("SHARP_SIGNAL_STRENGTH_SCALE")) if strength is not None else 0.0

    last_ts = sharp_row.get("lastTs")
    fresh: bool | None = None
    if last_ts:
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        age_hours = max(0.0, (now - int(last_ts)) / 3_600_000.0)
        fresh = age_hours <= gate_parameter("SHARP_TRANSACTION_MAX_AGE_HOURS")

    return SignalFamilyEvidence(
        family="sharp_transaction",
        direction=direction,
        magnitude=magnitude,
        family_confidence=tier if tier in ("high", "medium", "low") else "low",
        fresh=fresh,
        provenance={
            "net": net,
            "signalStrength": strength,
            "uniqueManagers": sharp_row.get("uniqueManagers"),
            "uniqueLeagues": sharp_row.get("uniqueLeagues"),
        },
    )
