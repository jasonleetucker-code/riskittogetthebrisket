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

__all__ = ["PickValueResolution", "resolve_pick_value"]

# The centre slot per tier — the same MECHANICAL convention as the
# pipeline's alias-suppression pass (Early→2, Mid→6, Late→10) and the
# public-league prober.  The GENERIC grade uses the Mid centre.
_GENERIC_CENTRE_SLOT = 6


@dataclass(frozen=True)
class PickValueResolution:
    """The canonical answer for one market pick reference.

    ``value`` is the canonical board value (``rankDerivedValue`` scale),
    or ``None`` with ``reason`` set — never 0 for missing.  ``basis``
    names HOW the ref resolved (``board_row`` / ``alias_centre_slot`` /
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


def _pick_rows_by_name(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in contract.get("playersArray") or []:
        if isinstance(row, dict) and row.get("assetClass") == "pick":
            name = str(row.get("canonicalName") or "")
            if name:
                out[name] = row
    return out


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
    once (``_pick_rows_by_name``-shaped); otherwise it is built per
    call.
    """
    rows = rows_by_name if rows_by_name is not None else _pick_rows_by_name(contract)

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

    if ref.grade == "generic":
        # No generic row (the pipeline publishes them for FUTURE years
        # only) — the current year's representation is slots, so the
        # generic grade falls to the centre-slot convention, labelled.
        centre = f"{ref.year} Pick {ref.round_num}.{_GENERIC_CENTRE_SLOT:02d}"
        centre_row = rows.get(centre)
        if centre_row is not None:
            return _resolved(ref, centre_row, centre, "centre_slot_convention")

    return PickValueResolution(ref=ref, value=None, reason="no_board_row_for_ref")
