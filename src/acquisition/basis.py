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
* **the clock is an argument, and it decides a real thing.**
  ``market_resolution()`` takes the current draft year as an INPUT.  For
  a pick whose slot is KNOWN it returns the ``exact_slot`` grade once
  that draft year has arrived and the ``tier_from_slot`` grade while it
  is still future — so asking with TODAY's clock would price a
  pre-draft trade at the slot the pick eventually landed on.  That is
  the ``C3-REPLAY-01`` defect class: it measures the methodology rather
  than the aging.

  Where the slot is genuinely unknown the answer is the GENERIC grade
  and the clock is not consulted at all — by construction, not by
  omission.  Both cases are exercised in ``tests/acquisition/test_cost_basis.py``.
* **before the floor is missing, not cheap.**  An acquisition earlier
  than ``HISTORY_FLOOR`` gets ``basis_value = None`` with
  ``basis_missing_reason = "before_history_boundary"`` — never
  interpolated, never today's value, and never the earliest FUTURE
  observation, which is the same look-ahead in a different direction.

An undated acquisition has no instant to ask about, so it is
``undated_acquisition``.  Missing is never zero — and a genuine value of
``0.0`` is a value, not a miss, which this module distinguishes by
branching on ``is None`` and never on truthiness.
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


def _draft_year_at(instant: datetime) -> int:
    """Which rookie draft was 'current' at ``instant``.

    Delegates to :func:`data_contract.rookie_draft_year_on`, the owner's
    AS-OF form.  An earlier cut of this module reimplemented the rollover
    rule locally and reached across the package boundary for a private
    config loader; the rule now lives in one place.

    Deliberately NOT ``current_rookie_draft_year``: that answers a
    present-tense question, and its ``currentDraftYear`` override and
    observed-year self-roll both win over the date argument — so calling
    it with a historical date would silently return today's answer, which
    is the exact re-grading this module exists to prevent.
    """
    from src.api.data_contract import rookie_draft_year_on

    return int(rookie_draft_year_on(instant.astimezone(timezone.utc).date()))


def _history_asset_key(
    asset_id: str, instant: datetime, *, realized_slot: int | None = None
) -> str | None:
    """Acquisition asset id → the ``src/history`` key namespace.

    Players map straight across.  A league pick does not: history keys
    price MARKET refs (``mpick:*``), and a league pick resolves to one
    through the C1-U3 owner — with BOTH the slot as it was known and the
    clock as of the event.

    ``realized_slot`` is what makes the clock load-bearing.  With a slot,
    ``market_resolution`` answers ``exact_slot`` once that draft year has
    arrived and ``tier_from_slot`` while it is still future; without one
    it answers the generic grade and never reads the clock.  Passing
    ``None`` unconditionally — as an earlier cut did — made the whole
    as-of-event mechanism unreachable.
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
        slot=realized_slot,
        current_draft_year=_draft_year_at(instant),
    )
    if resolution is None or resolution.ref is None:
        return None
    row_name = resolution.ref.board_row_name()
    return pick_asset_key(row_name) if row_name else None


def _coerce_slot(value: Any) -> int | None:
    """A slot is known or it is not.  ``0`` is not a slot."""
    if value is None or isinstance(value, bool):
        return None
    try:
        slot = int(value)
    except (TypeError, ValueError):
        return None
    return slot if slot > 0 else None


def basis_for_holding(holding: dict[str, Any], *, path: Path | None = None) -> dict[str, Any]:
    """``{value, fidelity, missingReason}`` for one holding period."""
    ms = holding.get("acquired_at_ms")
    if ms is None:
        return {"value": None, "fidelity": None, "missingReason": REASON_UNDATED}

    from src.history.asof import value_known_before

    instant = _instant(int(ms))
    asset_key = _history_asset_key(
        str(holding.get("asset_id") or ""),
        instant,
        realized_slot=_coerce_slot(holding.get("realized_slot")),
    )
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
