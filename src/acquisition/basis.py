"""Cost basis — what an asset was known to be worth AT acquisition.

THE NEVER-FUTURE RULE
─────────────────────
``value_known_before``, never ``value_as_of``.

``value_as_of`` is day-granular, so a board built later on the same
calendar day qualifies.  For a cost basis that is a look-ahead leak: it
prices Monday's trade with Monday evening's board, which already
contains the market's reaction to that trade.  ``value_known_before`` is
instant-strict — an observation whose scrape instant is unknown does not
qualify even on the same day (``src/history/asof.py``).

TWO MORE LEAKS, CLOSED EXPLICITLY
─────────────────────────────────
* **the clock is an argument.**  ``market_resolution()`` takes the
  current draft year as an INPUT, so a pick's grade must be resolved
  with the clock AS OF THE EVENT.  Passing today's re-grades an old
  trade under today's basis, which is the ``C3-REPLAY-01`` defect
  class: it measures the methodology rather than the aging.
* **before the floor is missing, not cheap.**  An acquisition earlier
  than ``HISTORY_FLOOR`` gets ``basis_value = None`` with
  ``basis_missing_reason = "before_history_boundary"`` — never
  interpolated, never today's value, and never the earliest FUTURE
  observation, which is the same look-ahead in a different direction.

An undated acquisition has no instant to ask about, so it is
``undated_acquisition``.  Missing is never zero.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

REASON_UNDATED = "undated_acquisition"
REASON_NO_ASSET_KEY = "unresolvable_asset_key"
REASON_NO_OBSERVATION = "no_prior_observation"
REASON_BEFORE_FLOOR = "before_history_boundary"


def _instant(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def _history_asset_key(asset_id: str, instant: datetime) -> str | None:
    """Acquisition asset id → the ``src/history`` key namespace.

    Players map straight across.  A league pick does not: history keys
    priced MARKET refs (``mpick:*``), and a league pick resolves to one
    through the C1-U3 owner — with the clock passed as of the event, per
    the module docstring.
    """
    from src.history.keys import pick_asset_key
    from src.identity.picks import market_resolution, parse_league_pick_id

    if asset_id.startswith("player:"):
        return asset_id

    identity = parse_league_pick_id(asset_id)
    if identity is None:
        return None

    resolution = market_resolution(
        year=identity.season,
        round_num=identity.round_num,
        slot=None,
        current_draft_year=_draft_year_at(instant),
    )
    if resolution is None or resolution.ref is None:
        return None
    row_name = resolution.ref.board_row_name()
    return pick_asset_key(row_name) if row_name else None


def _draft_year_at(instant: datetime) -> int:
    """Which rookie draft was 'current' at ``instant``.

    The same rollover convention ``current_rookie_draft_year`` uses, but
    evaluated at the EVENT's instant rather than now.  Reading the live
    resolver would re-grade every historical acquisition under today's
    clock, which is exactly what this module exists to prevent.
    """
    from src.api.data_contract import _load_pick_year_discount

    cfg = _load_pick_year_discount() or {}
    roll_m = int(cfg.get("rolloverMonth") or 5)
    roll_d = int(cfg.get("rolloverDay") or 15)
    d = instant.astimezone(timezone.utc).date()
    return d.year + 1 if (d.month, d.day) >= (roll_m, roll_d) else d.year


def basis_for_holding(holding: dict[str, Any], *, path: Path | None = None) -> dict[str, Any]:
    """``{value, fidelity, missingReason}`` for one holding period."""
    ms = holding.get("acquired_at_ms")
    if ms is None:
        return {"value": None, "fidelity": None, "missingReason": REASON_UNDATED}

    from src.history.asof import value_known_before

    instant = _instant(int(ms))
    asset_key = _history_asset_key(str(holding.get("asset_id") or ""), instant)
    if not asset_key:
        return {"value": None, "fidelity": None, "missingReason": REASON_NO_ASSET_KEY}

    result = value_known_before(asset_key, instant, path=path)
    value = result.get("value")
    if value is None:
        reason = result.get("missingReason") or REASON_NO_OBSERVATION
        return {"value": None, "fidelity": result.get("fidelity"), "missingReason": reason}
    return {
        "value": float(value),
        "fidelity": result.get("fidelity"),
        "missingReason": None,
    }


def attach_basis(
    holdings: Sequence[dict[str, Any]], *, path: Path | None = None
) -> list[dict[str, Any]]:
    """Stamp basis onto each holding.  Mutates and returns the list.

    Never raises: an unreachable ledger degrades every row to an
    explicit missing reason rather than taking the derivation down.  A
    projection that refuses to build because a value lookup failed is
    strictly worse than one that says which values it could not find.
    """
    for holding in holdings:
        # The DERIVATION may already know something more specific than a
        # value lookup ever can.  ``no_explaining_event`` says WHY there
        # is no acquisition instant; ``undated_acquisition`` only says
        # that there isn't one.  Overwriting the first with the second
        # would lose the diagnosis and leave every unexplained holding
        # looking like an ordinary timestamp gap.
        prior_reason = holding.get("basis_missing_reason")
        try:
            result = basis_for_holding(holding, path=path)
        except Exception:  # noqa: BLE001
            result = {
                "value": None,
                "fidelity": None,
                "missingReason": REASON_NO_OBSERVATION,
            }
        holding["basis_value"] = result["value"]
        holding["basis_fidelity"] = result["fidelity"]
        if result["value"] is None and prior_reason:
            holding["basis_missing_reason"] = prior_reason
        else:
            holding["basis_missing_reason"] = result["missingReason"]
    return list(holdings)
