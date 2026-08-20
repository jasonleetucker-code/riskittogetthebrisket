"""Ticker movement windows (C6-SIG-02) — stamped on the ``/api/data`` contract.

Mirrors ``src.api.data_contract._stamp_rank_changes``'s exact pattern:
read-only against the temporal ledger, degrades to an explicit
"unavailable" on any failure (a ledger outage must never become a wrong
number), and is the canonical movement source for the market ticker.

Deliberately built on ``src.history.asof`` (the ``LANE_CANONICAL``
temporal ledger) and NOT on ``data/rank_history.jsonl`` (the log
``src.api.terminal`` / ``/api/movers`` / ``frontend/lib/movers.js`` read).
Both are stores of a similar fact, populated by two different write
paths — a real, named duplication this unit does not resolve (see
``docs/lane4/C6_SIG_01_RECONCILER.md``). Structurally guarded by
``tests/signals/test_movement.py``: patching the JSONL loader to raise
must not affect this module at all.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

__all__ = ["stamp_movement_windows"]

#: Named windows only — an arbitrary lookback on a sparsely-populated
#: early ledger period could silently return "unavailable" for most
#: values, so the contract stays predictable: exactly these two spans,
#: each honest about its own fidelity.
_WINDOWS_DAYS: dict[str, int] = {"7d": 7, "30d": 30}


def stamp_movement_windows(
    rows: list[dict[str, Any]],
    *,
    board_date: str | None = None,
    ledger_path: "Any | None" = None,
) -> None:
    """Stamp ``movementWindows`` on each row: ``{"7d": {...}, "30d": {...}}``.

    Each window entry: ``{"deltaRank": int|None, "deltaValue": int|None,
    "windowDaysRequested": int, "asOfDate": str|None, "fidelity":
    "exact"|"nearest-prior"|"unavailable"}``.

    Read-only: writes nothing to the ledger. A ledger failure (missing
    file, corrupt store, the rollback flag) degrades every row's
    ``movementWindows`` to explicit unavailability, never to a
    fabricated delta.
    """
    try:
        from src.history import asof as _asof
        from src.history import keys as _history_keys
    except Exception:
        _asof = None
        _history_keys = None

    if not board_date:
        board_date = datetime.now(timezone.utc).date().isoformat()
    try:
        board_dt = date.fromisoformat(board_date)
    except ValueError:
        board_dt = datetime.now(timezone.utc).date()

    for row in rows:
        windows: dict[str, Any] = {}
        for label, days in _WINDOWS_DAYS.items():
            windows[label] = _window_entry(
                row,
                asof_module=_asof,
                history_keys=_history_keys,
                board_date=board_dt,
                window_days=days,
                ledger_path=ledger_path,
            )
        row["movementWindows"] = windows


def _window_entry(
    row: dict[str, Any],
    *,
    asof_module: Any,
    history_keys: Any,
    board_date: date,
    window_days: int,
    ledger_path: Any,
) -> dict[str, Any]:
    unavailable = {
        "deltaRank": None,
        "deltaValue": None,
        "windowDaysRequested": window_days,
        "asOfDate": None,
        "fidelity": "unavailable",
    }
    if asof_module is None or history_keys is None:
        return unavailable

    keyed = history_keys.asset_key_for_contract_row(row)
    if not keyed:
        return unavailable
    asset_key, _asset_class = keyed

    requested_date = (board_date - timedelta(days=window_days)).isoformat()
    try:
        prior = asof_module.value_as_of(asset_key, requested_date, path=ledger_path)
    except Exception:
        return unavailable

    if prior.get("fidelity") == "unavailable" or prior.get("value") is None:
        return dict(unavailable, asOfDate=prior.get("requestedDate"))

    cur_value = row.get("rankDerivedValue")
    cur_rank = row.get("canonicalConsensusRank")
    prior_value = prior.get("value")
    prior_rank = prior.get("rank")

    delta_value = None
    if cur_value is not None and prior_value is not None:
        try:
            delta_value = int(cur_value) - int(prior_value)
        except (TypeError, ValueError):
            delta_value = None

    delta_rank = None
    if cur_rank is not None and prior_rank is not None:
        try:
            # Positive = moved UP (lower rank number now), matching
            # _stamp_rank_changes's own sign convention.
            delta_rank = int(prior_rank) - int(cur_rank)
        except (TypeError, ValueError):
            delta_rank = None

    return {
        "deltaRank": delta_rank,
        "deltaValue": delta_value,
        "windowDaysRequested": window_days,
        "asOfDate": prior.get("observedDate"),
        "fidelity": prior.get("fidelity", "unavailable"),
    }
