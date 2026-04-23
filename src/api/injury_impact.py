"""Injury-to-value impact model.

A lookup-table model that translates a news/injury payload into a
short-term percentage adjustment on a player's ``rankDerivedValue``.
Used to stamp ``injuryAdjustedValue`` onto roster rows so the
terminal + rankings UI can show the current market-adjusted number
alongside the canonical blend.

Scope
─────

This is NOT a predictive model.  It's a codified rulebook of
"injury type + severity + position + age → short-term value
discount" derived from the well-known fantasy-football conventional
wisdom.  Every rule cites the input fields it consumes and the
fixed % / duration it applies, so the UI can show "-15% (ACL, RB,
≥25) · expires 2026-06-01" verbatim when questioned.

The model has a deliberate 30-day decay: an alert fires a
``discountPct`` immediately, the discount halves at 15 days and
zeros out at 30.  Real injury-to-value dynamics are messier than
that (the market overreacts, then partially reverts, then reacts
again when news lands), but a linear decay is the right floor
until we have months of news-vs-market price data to train on.

Integration
───────────

Called from ``terminal.py`` on every roster row once per build:

    impact = apply_injury_impact(
        row=row,
        news_for_player=news_items_matching_this_player,
        now_ms=int(time.time() * 1000),
    )
    if impact["appliedDiscountPct"]:
        row["injuryAdjustedValue"] = impact["adjustedValue"]
        row["injuryImpact"] = impact  # for UI transparency

Rules
─────

Severity tiers (matching the news-service contract):

    alert   → severe, career-impacting (Achilles, ACL, spinal)
    watch   → mid-grade (high-ankle, hamstring Gr 2, concussion)
    info    → soft-tissue / day-to-day (low-ankle, bruise, illness)

Position modifiers:

    RB  × 1.20  (most injury-sensitive; workload-dependent)
    WR  × 1.00  (baseline)
    TE  × 0.90  (comparatively robust)
    QB  × 0.70  (short-term benches don't destroy value)
    IDP × 0.80

Age modifiers (for non-rookie):

    ≤25  × 0.80  (younger bounces back)
    26-28 × 1.00
    29-31 × 1.20
    ≥32  × 1.40

Values are capped at 60% total discount to stop a single news item
from zeroing a player's value.
"""
from __future__ import annotations

from typing import Any


# Base discount percentages by severity.
#
# Sized for the DYNASTY context: a single news item should NOT
# materially reprice a player who will still play 3+ more seasons.
# A torn ACL in Week 8 is a redraft disaster (-30% on rest-of-
# season) but a dynasty hiccup (-3 to -5% on multi-year value).
# The numbers below target a 5% cap after position/age multipliers.
BASE_DISCOUNT_PCT = {
    "alert": 4.0,
    "watch": 2.0,
    "info":  0.5,
}

# Duration (ms) over which the discount linearly decays to zero.
_DECAY_WINDOW_MS: int = 30 * 24 * 3600 * 1000

# Maximum discount.  Capped low for dynasty.
_MAX_DISCOUNT_PCT: float = 5.0


# NFL offseason months (inclusive).  February through August is
# the window where news-driven price shocks should be dampened to
# zero: the player has 4-7 months to recover before Week 1 so
# dynasty-horizon buyers don't meaningfully reprice a February
# shoulder scope.  September through January is the live window.
#
# Covers: Feb (combine/free agency) → Aug (training camp).
# Excludes: Jan (playoffs) → Sep-Dec (regular season).
_OFFSEASON_MONTHS: frozenset[int] = frozenset({2, 3, 4, 5, 6, 7, 8})


def _is_nfl_offseason(now_ms: int) -> bool:
    """True when the NFL is currently between Super Bowl and
    Week 1 (roughly Feb 1 – Aug 31 each year).

    Intentionally coarse — we use the UTC month boundary rather
    than the actual Super Bowl / Week 1 dates.  Good enough for
    a discount switch; getting fancy with schedule lookups would
    add a data dependency for a ~2-week edge case at each end.
    """
    from datetime import datetime, timezone
    dt = datetime.fromtimestamp(now_ms / 1000.0, tz=timezone.utc)
    return dt.month in _OFFSEASON_MONTHS


def _position_multiplier(pos: str) -> float:
    p = str(pos or "").upper()
    if p in ("RB",):
        return 1.20
    if p in ("WR",):
        return 1.00
    if p in ("TE",):
        return 0.90
    if p in ("QB",):
        return 0.70
    if p in ("DL", "LB", "DB", "IDP", "DE", "DT", "CB", "S"):
        return 0.80
    return 1.00


def _age_multiplier(age: Any, is_rookie: bool) -> float:
    if is_rookie:
        return 0.80
    try:
        a = float(age) if age is not None else None
    except (TypeError, ValueError):
        a = None
    if a is None or a <= 0:
        return 1.00
    if a <= 25:
        return 0.80
    if a <= 28:
        return 1.00
    if a <= 31:
        return 1.20
    return 1.40


def _news_ms(iso: Any) -> int | None:
    if not isinstance(iso, str):
        return None
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def _decay_factor(age_ms: int) -> float:
    """Linear decay from 1.0 at t=0 to 0 at t=DECAY_WINDOW_MS."""
    if age_ms <= 0:
        return 1.0
    if age_ms >= _DECAY_WINDOW_MS:
        return 0.0
    return 1.0 - (age_ms / _DECAY_WINDOW_MS)


def compute_injury_discount(
    *,
    pos: str,
    age: Any,
    is_rookie: bool,
    news_for_player: list[dict[str, Any]],
    now_ms: int,
) -> dict[str, Any]:
    """Score all news items attached to this player and pick the
    worst-case (highest discount) rule that applies.

    Returns::

        {
          "appliedDiscountPct":  float (0-60),
          "basePct":             float,
          "positionMultiplier":  float,
          "ageMultiplier":       float,
          "decayFactor":         float (0-1),
          "severity":            "alert" | "watch" | "info" | None,
          "headline":            str,    # the newest driving item
          "newsTs":              str,    # ISO timestamp of the item
          "adjustedPct":         float,  # 100 - appliedDiscountPct
        }

    ``adjustedPct`` is a convenience for callers that multiply the
    live value: ``int(round(value * adjustedPct / 100))``.

    When no applicable news is present, every numeric field returns
    0 and the caller leaves ``rankDerivedValue`` unchanged.
    """
    result = {
        "appliedDiscountPct": 0.0,
        "basePct": 0.0,
        "positionMultiplier": 0.0,
        "ageMultiplier": 0.0,
        "decayFactor": 0.0,
        "severity": None,
        "headline": "",
        "newsTs": "",
        "adjustedPct": 100.0,
        "offseasonSuppressed": False,
    }
    if not news_for_player:
        return result
    # Offseason suppressor: injury news during Feb-Aug gets 0%
    # discount because the player will recover before any game
    # matters to dynasty value.  Flag it on the result so the UI
    # can show "injury news (suppressed — offseason)" instead of
    # silently ignoring it.
    if _is_nfl_offseason(now_ms):
        result["offseasonSuppressed"] = True
        # We still pick the representative headline so the UI can
        # render "Injury news (offseason)" with context.
        newest = None
        for item in news_for_player:
            if not isinstance(item, dict):
                continue
            sev = str(item.get("severity") or "").strip().lower()
            if sev not in BASE_DISCOUNT_PCT:
                continue
            ts = _news_ms(item.get("ts") or item.get("timestamp"))
            if newest is None or (ts is not None and (newest[0] is None or ts > newest[0])):
                newest = (ts, item)
        if newest is not None:
            result["severity"] = str(newest[1].get("severity") or "").lower() or None
            result["headline"] = str(newest[1].get("headline") or "")[:160]
            result["newsTs"] = str(newest[1].get("ts") or newest[1].get("timestamp") or "")
        return result

    pos_mult = _position_multiplier(pos)
    age_mult = _age_multiplier(age, is_rookie)

    best_discount = 0.0
    best: dict[str, Any] = {}
    for item in news_for_player:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "").strip().lower()
        base = BASE_DISCOUNT_PCT.get(severity)
        if not base:
            continue
        # Only negative-impact news drives a value discount.  If the
        # news item labels the affected player as positive-impact
        # (news-service adds this tag), skip it even if severity
        # happens to be "alert" — e.g. a trade to a better offense
        # could be alert-severity but positive.
        impacts = item.get("players") or []
        if isinstance(impacts, list):
            has_positive = any(
                isinstance(p, dict) and str(p.get("impact") or "") == "positive"
                for p in impacts
            )
            if has_positive:
                continue
        # Age of the news item drives decay.
        ts_ms = _news_ms(item.get("ts") or item.get("timestamp"))
        if ts_ms is None:
            # Unknown timestamp — assume brand new so the decay
            # doesn't under-discount something recent.
            decay = 1.0
            age_ms = 0
        else:
            age_ms = max(0, now_ms - ts_ms)
            decay = _decay_factor(age_ms)
        if decay <= 0:
            continue
        discount = base * pos_mult * age_mult * decay
        if discount > best_discount:
            best_discount = discount
            best = {
                "basePct": base,
                "positionMultiplier": pos_mult,
                "ageMultiplier": age_mult,
                "decayFactor": decay,
                "severity": severity,
                "headline": str(item.get("headline") or "")[:160],
                "newsTs": str(item.get("ts") or item.get("timestamp") or ""),
            }

    if best_discount <= 0:
        return result

    discount_pct = min(_MAX_DISCOUNT_PCT, round(best_discount, 2))
    result.update(best)
    result["appliedDiscountPct"] = discount_pct
    result["adjustedPct"] = round(100.0 - discount_pct, 2)
    return result


def apply_injury_impact(
    *,
    row: dict[str, Any],
    news_for_player: list[dict[str, Any]],
    now_ms: int,
) -> dict[str, Any]:
    """Compute the injury impact for a row and return a payload
    suitable for stamping onto the contract row.

    Returns a dict with the fields ``compute_injury_discount``
    emits PLUS ``adjustedValue`` (the live value × decay factor),
    or a zero-discount default when no applicable news exists.
    """
    pos = row.get("pos") or row.get("position")
    age = row.get("age")
    is_rookie = bool(row.get("rookie") or row.get("isRookie"))
    impact = compute_injury_discount(
        pos=pos, age=age, is_rookie=is_rookie,
        news_for_player=news_for_player, now_ms=now_ms,
    )
    base_value = row.get("rankDerivedValue")
    try:
        base_value = int(base_value) if base_value is not None else None
    except (TypeError, ValueError):
        base_value = None
    if base_value is None or base_value <= 0:
        impact["adjustedValue"] = None
        return impact
    adjusted = int(round(base_value * impact["adjustedPct"] / 100.0))
    adjusted = max(1, adjusted)
    impact["adjustedValue"] = adjusted
    return impact
