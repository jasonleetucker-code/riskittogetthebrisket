"""Canonical MarketPickRef → value resolution (C1-U6 / C1-PICK-01/-02).

One owner for the question **"what does the canonical board say this
pick reference class is worth?"** — so no consumer re-invents tier-centre
conventions, year fallbacks, or "if the name misses, guess" ladders.
Part of the ``data_contract`` pick pipeline (the execution map's owner
for C1-U6): everything here READS values the pipeline stamped; it
computes no new value and mutates nothing.

The resolution contract:

* **slot grade** — the slot row (``"2026 Pick 1.06"``), which the
  current draft year carries (rookie-pool tethered).
* **tier grade** — the tier row.  A current-year tier row is
  alias-suppressed in favor of its centre slot
  (``pickGenericSuppressed`` + ``pickAliasFor``); the resolver follows
  the alias and says so.
* **generic grade** — for a FUTURE year, the rank-less generic-grade
  row the pipeline publishes (``"2027 Round 1"``, uniform-tier EV,
  classification PRIOR).  For the CURRENT year — where slots are the
  representation — the centre-slot convention (``Pick R.06``), the same
  MECHANICAL convention the suppression pass and the public-league
  prober already use, labelled as such.

MISSING IS NEVER ZERO: an unresolvable or unpriced reference returns
``value=None`` with a machine-readable reason — never ``0``, never a
fabricated slot or tier, and identity is never mutated (the ref the
caller passed is echoed back untouched).

The generic ↔ exact-slot transition (C1-PICK-02) is
``identity.picks.market_resolution`` changing which grade it answers as
state evolves; this module is the value half — the same league-pick
identity resolves to a finite value at every grade along the way.
Pinned by ``tests/api/test_pick_completeness.py``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from src.identity.picks import MarketPickRef

__all__ = [
    "PickValueResolution",
    "pick_rows_by_name",
    "pick_rows_from_rows",
    "resolve_owned_pick_value",
    "resolve_pick_asset_value",
    "resolve_pick_label_value",
    "resolve_pick_value",
    "stamp_owned_pick_rows",
]

# The centre slot per tier — the same MECHANICAL convention as the
# pipeline's alias-suppression pass (Early→2, Mid→6, Late→10) and the
# public-league prober.  The GENERIC grade uses the Mid centre.
_GENERIC_CENTRE_SLOT = 6


@dataclass(frozen=True)
class PickValueResolution:
    """The canonical answer for one market pick reference.

    ``value`` is the canonical board value (``rankDerivedValue`` scale),
    or ``None`` with ``reason`` set — never 0 for missing.  ``basis``
    names HOW the ref resolved (``board_row`` / ``alias_centre_slot`` / ``tier_of_unslotted_class`` /
    ``centre_slot_convention``); ``basisRowName`` is the row that
    supplied the number; ``provenance`` is that row's
    ``pickValueProvenance`` block verbatim.
    """

    ref: MarketPickRef
    value: int | None
    basis: str | None = None
    basis_row_name: str | None = None
    provenance: dict[str, Any] | None = None
    reason: str | None = None


def _finite_value(row: dict[str, Any] | None) -> int | None:
    if not isinstance(row, dict):
        return None
    v = row.get("rankDerivedValue")
    if (
        isinstance(v, (int, float))
        and not isinstance(v, bool)
        and math.isfinite(float(v))
        and v > 0
    ):
        return int(v)
    return None


def pick_rows_from_rows(rows: Any) -> dict[str, dict[str, Any]]:
    """``canonicalName -> row`` for the pick rows in ``rows``.

    The index shape :func:`resolve_pick_value` takes as ``rows_by_name``.
    Accepts any iterable of rows (a contract's ``playersArray``, or the
    values of a consumer's own row index) so a caller that already holds
    its rows indexes them once instead of re-reading the contract.
    """
    out: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        if isinstance(row, dict) and row.get("assetClass") == "pick":
            # ``displayName`` only as a fallback: on a built contract the two
            # are the same string for every pick row.
            name = str(row.get("canonicalName") or row.get("displayName") or "")
            if name:
                out[name] = row
    return out


def pick_rows_by_name(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The contract's pick rows indexed for :func:`resolve_pick_value`."""
    return pick_rows_from_rows(contract.get("playersArray") or [])


# Kept for the existing callers (``intel.manager_activity``,
# ``trade.market_trade_eval``); new code uses the public name.
_pick_rows_by_name = pick_rows_by_name


def _resolved(
    ref: MarketPickRef, row: dict[str, Any], name: str, basis: str
) -> PickValueResolution:
    value = _finite_value(row)
    if value is None:
        return PickValueResolution(
            ref=ref,
            value=None,
            basis=basis,
            basis_row_name=name,
            reason="row_present_but_unpriced",
        )
    prov = row.get("pickValueProvenance")
    return PickValueResolution(
        ref=ref,
        value=value,
        basis=basis,
        basis_row_name=name,
        provenance=dict(prov) if isinstance(prov, dict) else None,
    )


def resolve_pick_value(
    contract: dict[str, Any],
    ref: MarketPickRef,
    *,
    rows_by_name: dict[str, dict[str, Any]] | None = None,
) -> PickValueResolution:
    """Resolve one market pick reference against a built contract.

    ``rows_by_name`` lets a batch caller index the contract's pick rows
    once (:func:`pick_rows_by_name`-shaped); otherwise it is built per
    call.
    """
    rows = rows_by_name if rows_by_name is not None else pick_rows_by_name(contract)

    name = ref.board_row_name()
    if name is None:
        return PickValueResolution(ref=ref, value=None, reason="outside_board_grammar")

    row = rows.get(name)
    if row is not None and row.get("pickGenericSuppressed"):
        # Current-year tier rows alias to their centre slot — one asset,
        # one value (the suppression pass exists so the same trade asset
        # cannot carry two divergent numbers).
        alias = str(row.get("pickAliasFor") or "")
        alias_row = rows.get(alias)
        if alias_row is not None:
            return _resolved(ref, alias_row, alias, "alias_centre_slot")
        return PickValueResolution(
            ref=ref, value=None, basis_row_name=name, reason="alias_target_missing"
        )
    if row is not None:
        return _resolved(ref, row, name, "board_row")

    if ref.slot is not None:
        # No slot row: the class is UNSLOTTED (C1-U6-D2) — no vendor has
        # published its draft order, so the board carries tiers.  The slot's
        # own tier is a deterministic mapping, labelled, never a guess.
        from src.identity.picks import MarketPickRef as _Ref, slot_tier

        tier_name = _Ref(
            year=ref.year, round_num=ref.round_num, tier=slot_tier(int(ref.slot))
        ).board_row_name()
        tier_row = rows.get(tier_name) if tier_name else None
        if tier_row is not None and not tier_row.get("pickGenericSuppressed"):
            return _resolved(ref, tier_row, tier_name, "tier_of_unslotted_class")

    if ref.grade == "generic":
        # No generic row (the pipeline publishes them for FUTURE years
        # only) — the current year's representation is slots, so the
        # generic grade falls to the centre-slot convention, labelled.
        centre = f"{ref.year} Pick {ref.round_num}.{_GENERIC_CENTRE_SLOT:02d}"
        centre_row = rows.get(centre)
        if centre_row is not None:
            return _resolved(ref, centre_row, centre, "centre_slot_convention")

    return PickValueResolution(ref=ref, value=None, reason="no_board_row_for_ref")


def resolve_owned_pick_value(
    asset_id: Any,
    *,
    slot: int | None,
    rows_by_name: dict[str, dict[str, Any]],
    current_draft_year: int,
) -> PickValueResolution | None:
    """Price one OWNED league pick by identity (Brisket Trade Advisor B0-a).

    ``asset_id`` is the canonical ``pick:<leagueKey>:<season>:r<N>:o<rid>``;
    ``slot`` is that asset's STATE (``pickDetails[].slot``), never parsed
    from a display label.  ``market_resolution`` maps (identity, state,
    clock) to a market reference — an unknown slot is the GENERIC grade,
    never "assume Mid" — and :func:`resolve_pick_value` answers.  ``None``
    when the id is not a canonical league-pick id.
    """
    from src.identity.picks import market_resolution, parse_league_pick_id

    ident = parse_league_pick_id(str(asset_id or ""))
    if ident is None:
        return None
    res = market_resolution(
        year=ident.season,
        round_num=ident.round_num,
        slot=slot if isinstance(slot, int) and slot > 0 else None,
        current_draft_year=int(current_draft_year),
    )
    return resolve_pick_value({}, res.ref, rows_by_name=rows_by_name)


def resolve_pick_label_value(
    label: Any,
    *,
    rows_by_name: dict[str, dict[str, Any]],
    current_draft_year: int,
) -> PickValueResolution | None:
    """Price a pick named only by a label (no owned id).

    The label is parsed (never guessed); its OWN grade is tried first — a
    stated tier or slot is a refinement the board may price directly — and
    when that grade has no priced row, ``market_resolution`` maps it for the
    clock and the resolver answers again (a current-year generic label takes
    the labelled centre-slot convention).  ``None`` for an unparseable label.
    """
    from src.identity.picks import market_resolution, parse_pick_label

    parsed = parse_pick_label(str(label or ""))
    if parsed is None:
        return None
    pv = resolve_pick_value({}, parsed.market_ref, rows_by_name=rows_by_name)
    if pv.value is not None:
        return pv
    res = market_resolution(
        year=parsed.year,
        round_num=parsed.round_num,
        slot=parsed.slot,
        current_draft_year=int(current_draft_year),
    )
    return resolve_pick_value({}, res.ref, rows_by_name=rows_by_name)


def resolve_pick_asset_value(
    *,
    asset_id: Any,
    slot: int | None,
    label: Any,
    rows_by_name: dict[str, dict[str, Any]],
    current_draft_year: int,
) -> PickValueResolution | None:
    """The ONE rule for "what prices this traded / rostered pick".

    1. A canonical league-pick ``asset_id`` resolves by IDENTITY
       (:func:`resolve_owned_pick_value`) — the label grammar cannot change
       the answer.
    2. When identity yields no priced row (the board publishes no row for
       that grade — e.g. an unslotted current class carrying tiers only, so
       neither a slot row nor the centre-slot convention exists), or there is
       no canonical id, the label's own parse decides
       (:func:`resolve_pick_label_value`) — exactly what priced such a pick
       before identity pricing existed.  Never a guess: an unparseable label
       stays unresolved.

    ``None`` only when there is neither a canonical id nor a parseable label.
    """
    pv = resolve_owned_pick_value(
        asset_id,
        slot=slot,
        rows_by_name=rows_by_name,
        current_draft_year=current_draft_year,
    )
    if pv is not None and pv.value is not None:
        return pv
    by_label = resolve_pick_label_value(
        label, rows_by_name=rows_by_name, current_draft_year=current_draft_year
    )
    if by_label is not None and by_label.value is not None:
        return by_label
    return pv if pv is not None else by_label


def stamp_owned_pick_rows(
    teams: Any,
    rows_by_name: dict[str, dict[str, Any]],
    current_draft_year: int,
) -> Any:
    """Copy of ``teams`` with ``boardRowName`` on every ``pickDetails`` entry.

    ``boardRowName`` is the board row that prices that owned pick under
    :func:`resolve_pick_asset_value` (identity first, the label only when
    identity finds no priced row), so every consumer that needs "which board
    row is this owned pick" reads one server answer instead of re-deriving
    it from a label grammar.  It names a row and carries no number; an
    unpriced pick gets ``None`` (never a guessed row).  Additive: no other
    field changes, and the input is never mutated (the overlay's teams are
    a shared in-process cache).
    """
    if not isinstance(teams, list):
        return teams
    out: list[Any] = []
    for team in teams:
        details = team.get("pickDetails") if isinstance(team, dict) else None
        if not isinstance(details, list):
            out.append(team)
            continue
        stamped: list[Any] = []
        for d in details:
            if not isinstance(d, dict):
                stamped.append(d)
                continue
            slot = d.get("slot")
            pv = resolve_pick_asset_value(
                asset_id=d.get("assetId"),
                slot=slot if isinstance(slot, int) else None,
                label=d.get("label"),
                rows_by_name=rows_by_name,
                current_draft_year=current_draft_year,
            )
            name = pv.basis_row_name if pv is not None and pv.value is not None else None
            stamped.append({**d, "boardRowName": name})
        out.append({**team, "pickDetails": stamped})
    return out
