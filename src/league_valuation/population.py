"""Which canonical rows may enter a league fair value population.

Structural eligibility only -- what the ROW says about itself. Evidence-based
exclusions (no projection, proxy-only, stale) are decided in
``challenger.compute_fair_values`` against the utility evidence. Every excluded
row keeps its market value exactly, and the reason travels with it.

Excluded, first matching reason wins (deterministic order):

* ``pick`` -- picks are out of scope in v1;
* ``unsupported_position`` -- K, P and anything outside OFFENSE QB/RB/WR/TE and
  IDP DL/LB/DB;
* ``no_asset_key`` / ``duplicate_asset_key`` -- an identity the temporal-history
  key owner cannot mint, or two rows colliding on one key (both are excluded:
  neither may be trusted to order the other);
* ``no_market_value`` -- there is nothing to shrink;
* ``quarantined`` -- the canonical pipeline already withheld the row;
* ``blend_integrity_violation`` -- the row's own value fell outside its
  contributions' range; it is not an ordinary canonical number;
* ``single_source_haircut`` -- the value carries the 30% single-source
  retention haircut, a policy discount the challenger must not re-interpret;
* ``two_way_player`` -- a post-blend override row (or a row the override
  inspected); BDVM prices a two-way player under one combined defensive record,
  so his utility does not belong to one scope;
* ``off_cap_value_only`` -- a value past ``OVERALL_RANK_LIMIT`` with no rank:
  value availability, not top-board membership.

TE rows are KEPT and carry the ``te_basis_tepp`` label: the market is anchored
on TE++, so the residual against it is exactly the league's TE demand signal,
measured rather than added.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.history.keys import asset_key_for_contract_row
from src.league_valuation.contracts import SCOPES
from src.utils.name_clean import normalize_position_family

#: Scope -> position families admitted in v1. Mirrors ``fair_value_v1.json``'s
#: ``scopes`` block; a test pins the two together.
SCOPE_POSITIONS: Mapping[str, frozenset[str]] = {
    "OFFENSE": frozenset({"QB", "RB", "WR", "TE"}),
    "IDP": frozenset({"DL", "LB", "DB"}),
}


def scope_of_row(row: Mapping[str, Any]) -> str | None:
    family = normalize_position_family(str(row.get("position") or "")) or ""
    for scope, families in SCOPE_POSITIONS.items():
        if family in families:
            return scope
    return None


def market_value_of(row: Mapping[str, Any]) -> int | None:
    """The canonical value as published, or ``None``. Never coerced to 0."""
    value = row.get("rankDerivedValue")
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number <= 0:  # NaN or non-positive
        return None
    rounded = int(round(number))
    # A positive value that rounds to 0 is below the canonical scale: it is not
    # a market value to shrink (ln 0 is undefined), and never a published 0.
    return rounded if rounded >= 1 else None


def row_key(row: Mapping[str, Any], index: int) -> str:
    keyed = asset_key_for_contract_row(dict(row))
    if keyed is None:
        return f"unkeyed:{index}:{row.get('canonicalName') or row.get('displayName') or ''}"
    return keyed[0]


def _structural_reason(row: Mapping[str, Any]) -> str | None:
    if str(row.get("assetClass") or "").lower() == "pick":
        return "pick"
    if scope_of_row(row) is None:
        return "unsupported_position"
    if market_value_of(row) is None:
        return "no_market_value"
    if row.get("quarantined"):
        return "quarantined"
    flags = row.get("anomalyFlags") or ()
    if isinstance(row.get("blendIntegrityViolation"), Mapping) or (
        isinstance(flags, (list, tuple)) and "blend_integrity_violation" in flags
    ):
        return "blend_integrity_violation"
    if row.get("singleSourceValuePenaltyApplied"):
        return "single_source_haircut"
    if isinstance(row.get("twoWayPlayerBoost"), Mapping):
        return "two_way_player"
    if row.get("offCapPlayerValue") or not row.get("canonicalConsensusRank"):
        return "off_cap_value_only"
    return None


def eligible_rows(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, list[Mapping[str, Any]]], dict[str, str]]:
    """``(per-scope populations, excluded asset_key -> reason)``.

    Rows are returned as the caller's own objects, unmodified; nothing here
    writes to a row. Population order follows input order.
    """
    keyed: list[tuple[str, Mapping[str, Any]]] = []
    counts: dict[str, int] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        key = row_key(row, index)
        keyed.append((key, row))
        counts[key] = counts.get(key, 0) + 1

    populations: dict[str, list[Mapping[str, Any]]] = {scope: [] for scope in SCOPES}
    excluded: dict[str, str] = {}
    for key, row in keyed:
        reason = _structural_reason(row)
        if reason is None and key.startswith("unkeyed:"):
            reason = "no_asset_key"
        if reason is None and counts[key] > 1:
            reason = "duplicate_asset_key"
        if reason is not None:
            # A colliding key keeps the most specific reason seen first.
            excluded.setdefault(key, reason)
            if counts[key] > 1 and excluded[key] != "duplicate_asset_key":
                excluded[key] = "duplicate_asset_key"
            continue
        scope = scope_of_row(row)
        assert scope is not None  # guarded by _structural_reason
        populations[scope].append(row)
    return populations, excluded
