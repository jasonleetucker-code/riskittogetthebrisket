"""Team asset-equity decomposition: player + pick = total, unknown never 0.

Owner of the *arithmetic* behind any field that claims to be a team's TOTAL
asset equity (see ``docs/roster_intel/TEAM_SEMANTICS_2026-11-08.md``).  It owns
no valuation: player values arrive from the caller's canonical board rows and
owned picks are priced by ``src.api.pick_value_resolution`` (identity first).

Rules (owner directive 2026-11-08 Priority 15, MISSING IS NEVER ZERO):

* ``playerValue`` and ``pickValue`` are separate named quantities.
* ``totalAssetValue = playerValue + pickValue`` ONLY when pick ownership was
  observed AND every held pick priced.  Otherwise it is ``None`` and the
  partial figure is published as ``totalAssetValueLowerBound`` with the reason.
* Unobserved ownership is ``pickValue: None`` (state ``unavailable``), never 0.
* An unpriced held pick is counted in ``unpricedPickCount`` and excluded from
  ``pricedPickValue``; it is not valued at 0 inside a claimed total.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.api.pick_value_resolution import resolve_pick_asset_value
from src.identity.picks import team_pick_ownership_unavailable_reason

#: Pick-state vocabulary.
PICKS_COMPLETE = "complete"
PICKS_PARTIAL = "partial_unpriced"
PICKS_UNAVAILABLE = "unavailable"


def decompose_team_equity(
    *,
    player_value: int | float,
    team: Mapping[str, Any] | None,
    pick_rows_by_name: Mapping[str, dict[str, Any]],
    current_draft_year: int | None,
) -> dict[str, Any]:
    """``{playerValue, pickValue, totalAssetValue, ...}`` for one team.

    ``team`` is the overlay's ``sleeper.teams[]`` entry (carries
    ``pickDetails`` and the ownership state).  ``player_value`` is the sum the
    caller already computed from canonical board rows (priced players only).
    """
    out: dict[str, Any] = {
        "playerValue": player_value,
        "pickValue": None,
        "pricedPickValue": None,
        "pickCount": None,
        "pricedPickCount": None,
        "unpricedPickCount": None,
        "pickValueState": PICKS_UNAVAILABLE,
        "pickValueReason": None,
        "totalAssetValue": None,
        "totalAssetValueLowerBound": None,
    }
    if not isinstance(team, Mapping):
        out["pickValueReason"] = "team_unresolved"
        return out
    reason = team_pick_ownership_unavailable_reason(team)
    if reason is not None:
        out["pickValueReason"] = reason
        out["totalAssetValueLowerBound"] = player_value
        return out
    details = team.get("pickDetails")
    if not isinstance(details, list):
        out["pickValueReason"] = "pick_inventory_not_published"
        out["totalAssetValueLowerBound"] = player_value
        return out
    if current_draft_year is None:
        out["pickValueReason"] = "current_draft_year_unknown"
        out["totalAssetValueLowerBound"] = player_value
        return out

    priced = 0
    unpriced = 0
    total = 0
    for d in details:
        if not isinstance(d, Mapping):
            unpriced += 1
            continue
        slot = d.get("slot")
        pv = resolve_pick_asset_value(
            asset_id=d.get("assetId"),
            slot=slot if isinstance(slot, int) else None,
            label=d.get("label"),
            rows_by_name=dict(pick_rows_by_name),
            current_draft_year=int(current_draft_year),
        )
        if pv is None or pv.value is None:
            unpriced += 1
            continue
        priced += 1
        total += int(pv.value)

    out["pickCount"] = len(details)
    out["pricedPickCount"] = priced
    out["unpricedPickCount"] = unpriced
    out["pricedPickValue"] = total
    if unpriced:
        out["pickValueState"] = PICKS_PARTIAL
        out["pickValueReason"] = "held_picks_unpriced"
        out["totalAssetValueLowerBound"] = player_value + total
        return out
    out["pickValue"] = total
    out["pickValueState"] = PICKS_COMPLETE
    out["totalAssetValue"] = player_value + total
    out["totalAssetValueLowerBound"] = player_value + total
    return out
