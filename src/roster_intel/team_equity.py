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
* ``player_value`` is ``None`` when no rostered player priced (unknown, not 0);
  ``player_coverage < 1`` (some rostered players unpriced) means the player sum
  is partial, so ``totalAssetValue`` is withheld and only the labelled lower
  bound is published.  A total is never "complete" on partial player evidence.
* A pick value <= 0 is UNRESOLVED, exactly like a player: the shared resolver
  (``pick_value_resolution._finite_value``) only prices ``rankDerivedValue > 0``,
  so a zero pick is counted in ``unpricedPickCount``, never summed as 0.
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


PLAYERS_COMPLETE = "complete"
PLAYERS_PARTIAL = "partial_unpriced"
PLAYERS_UNAVAILABLE = "unavailable"


def _player_state(value: int | float | None, coverage: float | None) -> str:
    if value is None:
        return PLAYERS_UNAVAILABLE
    if coverage is None or coverage < 1.0:
        return PLAYERS_PARTIAL
    return PLAYERS_COMPLETE


def _lb(player_value: int | float | None, picks: int | float) -> int | float | None:
    """Lower bound: priced evidence only; ``None`` when there is none at all."""
    if player_value is None:
        return picks if picks else None
    return player_value + picks


def decompose_team_equity(
    *,
    player_value: int | float | None,
    player_coverage: float | None = 1.0,
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
        "playerCoverage": player_coverage,
        "playerValueState": _player_state(player_value, player_coverage),
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
        out["totalAssetValueLowerBound"] = _lb(player_value, 0)
        return out
    details = team.get("pickDetails")
    if not isinstance(details, list):
        out["pickValueReason"] = "pick_inventory_not_published"
        out["totalAssetValueLowerBound"] = _lb(player_value, 0)
        return out
    if current_draft_year is None:
        out["pickValueReason"] = "current_draft_year_unknown"
        out["totalAssetValueLowerBound"] = _lb(player_value, 0)
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
        out["totalAssetValueLowerBound"] = _lb(player_value, total)
        return out
    out["pickValue"] = total
    out["pickValueState"] = PICKS_COMPLETE
    out["totalAssetValueLowerBound"] = _lb(player_value, total)
    if out["playerValueState"] == PLAYERS_COMPLETE:
        out["totalAssetValue"] = player_value + total  # type: ignore[operator]
    return out
