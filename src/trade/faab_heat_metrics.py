"""FAAB Market Heat — trending-velocity metrics. A `C4-FAAB-01` prerequisite.

WHAT THIS IS, AND WHAT IT DELIBERATELY IS NOT
─────────────────────────────────────────────
``docs/FAAB_MARKET_SIGNAL_NORMALIZATION_2026-08-14.md`` §4 wants Sleeper trending
adds/drops turned into a bounded, backtested "Market Heat" modifier on the FAAB
engine's recommended bid, preferring "a velocity/acceleration view when enough
snapshots exist, such as 6h/12h/24h/48h changes... over a single raw rank." The
exact bounded transform needs real backtest validation against real trending and
bid-outcome data (spec §11) — this module is NOT that. It computes the
deterministic, policy-free INPUT the eventual backtest needs (velocity over
several windows) and stops there. No coefficient is chosen here, and nothing in
this module is imported by ``src.trade.faab_engine`` or any other decision path
(pinned by ``tests/trade/test_faab_heat_metrics_non_influence.py``).

WHY THE CAPTURE HALF OF THIS ALREADY EXISTS
─────────────────────────────────────────────
Trending-add counts are already being recorded into a real time series —
``src.retention.evidence_store.observe_trending_snapshot``, called from
``server.py``'s post-scrape warm worker on every scrape cycle (C1-RET-05). This
module is a READER of that series, not a second collector.

NO LOOKAHEAD, BY CONSTRUCTION
──────────────────────────────
Every observation this module reads is explicitly constrained to be AT OR
BEFORE the instant being asked about — the same never-future rule
``src/history/asof.py`` states for canonical value history. A window with no
qualifying observation that far back returns ``None`` with a named reason,
never a fabricated zero baseline (zero trending adds recorded is a real
observation; no observation at all is a different fact and must not read the
same).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REASON_NO_CURRENT_OBSERVATION = "no_observation_at_or_before_instant"
REASON_NO_PAST_OBSERVATION = "no_observation_before_window"

DEFAULT_WINDOWS_HOURS: tuple[int, ...] = (6, 12, 24, 48)


def _parse_observed_at(observed_at: str) -> datetime | None:
    """``trending_series``' ``observedAt`` is the adapter's own
    ``datetime.now(timezone.utc).isoformat()`` stamp. A value that fails to
    parse is treated as absent rather than guessed at."""
    if not observed_at:
        return None
    try:
        dt = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _latest_at_or_before(rows: list[dict[str, Any]], instant: datetime) -> dict[str, Any] | None:
    """The most recent observation with ``observedAt <= instant``.

    ``rows`` is oldest-first (``trending_series``' own contract); scanning from
    the end finds the latest qualifying row without assuming any particular
    sort stability beyond what that contract already promises.
    """
    best: dict[str, Any] | None = None
    best_dt: datetime | None = None
    for row in rows:
        dt = _parse_observed_at(row.get("observedAt"))
        if dt is None or dt > instant:
            continue
        if best_dt is None or dt > best_dt:
            best, best_dt = row, dt
    return best


def trending_velocity(
    player_id: str,
    as_of_ms: int,
    *,
    windows_hours: tuple[int, ...] = DEFAULT_WINDOWS_HOURS,
    source: str = "sleeper_add",
    path: Path | None = None,
) -> dict[str, Any]:
    """Per-window change in trending-add count, as of ``as_of_ms``.

    Returns ``{playerId, asOfMs, current: {count, observedAt} | None,
    windows: {"6h": {...}, ...}}``. Each window entry is
    ``{deltaCount, pastCount, pastObservedAt, fidelity}`` when both anchors
    resolve, or ``{deltaCount: None, reason: ...}`` when one does not — missing
    stays missing, never a fabricated zero delta.
    """
    from src.retention.evidence_store import trending_series

    pid = str(player_id or "").strip()
    as_of = datetime.fromtimestamp(int(as_of_ms) / 1000.0, tz=timezone.utc)
    rows = trending_series(pid, source=source, path=path) if pid else []

    current = _latest_at_or_before(rows, as_of)
    result: dict[str, Any] = {
        "playerId": pid,
        "asOfMs": int(as_of_ms),
        "current": None,
        "windows": {},
    }
    if current is None:
        for hours in windows_hours:
            result["windows"][f"{hours}h"] = {
                "deltaCount": None,
                "reason": REASON_NO_CURRENT_OBSERVATION,
            }
        return result

    result["current"] = {"count": current.get("count"), "observedAt": current.get("observedAt")}
    current_count = current.get("count")

    for hours in windows_hours:
        window_dt = as_of - timedelta(hours=hours)
        past = _latest_at_or_before(rows, window_dt)
        key = f"{hours}h"
        if past is None:
            result["windows"][key] = {
                "deltaCount": None,
                "reason": REASON_NO_PAST_OBSERVATION,
            }
            continue
        past_count = past.get("count")
        delta = None
        if current_count is not None and past_count is not None:
            delta = int(current_count) - int(past_count)
        result["windows"][key] = {
            "deltaCount": delta,
            "pastCount": past_count,
            "pastObservedAt": past.get("observedAt"),
            "fidelity": "exact"
            if window_dt == _parse_observed_at(past.get("observedAt"))
            else "nearest-prior",
        }
    return result
