"""Every league draft class on one draft-capital board (owner directive 2026-10-17).

The /league Draft Capital tab must show EVERY class the league still owns
picks in — for ``dynasty_main`` in October 2026 that is 2027, 2028 and 2029 —
not only the class the default league's workbook happens to carry.  This
module produces the owned-pick rows for the classes a builder does not
already cover, and prices them with the canonical pick values.  It decides
nothing about which classes exist, who owns a pick, or what a pick is worth:

* **Which classes** — the league-scoped resolver
  (``pick_lifecycle.league_draft_years`` via
  ``draft_class_evidence.league_draft_years_for``).  A class the league has
  drafted and rostered is retired there and never reaches this module, so a
  completed rookie class cannot reappear as future capital.
* **Who owns each pick** — THE ownership fold,
  ``identity.picks.build_pick_ownership``, over the league's own rosters and
  an OBSERVED ``/traded_picks`` diff (``picks.traded_picks_observation``).
  The caller must not pass ``[]`` for a failed fetch; ``None`` refuses.
* **What a pick is worth** — the canonical board through
  ``identity.picks.market_resolution`` + ``api.pick_value_resolution``.  A
  class whose draft order is unknown resolves at the GENERIC grade (every
  pick of one season + round prices identically); no slot is fabricated.

Dollars — the $1,200 budget basis
=================================

Per-pick dollars are a linear share of a $1,200 pool over canonical values,
the same rule ``draft_capital_fallback`` already uses.  WHICH picks share one
pool is the open owner question recorded beside ``budgetPolicy``:

* ``per_class_pool`` — each draft class is its own $1,200 pool (the
  owner-confirmed rookie-auction framework: 72 picks, one $1,200 league-wide
  pool per draft).  The default league uses this, because it is the only
  basis under which the workbook's current-class dollars — the live auction
  budgets — stay exactly as published.
* ``shared_multi_class_pool`` — one $1,200 across every priced pick of every
  class.  The Sleeper-derived fallback has always normalized this way and
  keeps doing so.

This module implements the per-class pricing; it does not switch either
builder's established basis.  ``budget_policy_block`` stamps which one a
payload used so the page can say so.

MISSING IS NEVER ZERO: a pick the board cannot price carries
``dollarValue: None`` + ``isUnpriced: True`` and stays out of its pool.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from src.identity import picks as _picks

#: Budget-basis vocabulary (stamped on every payload as ``budgetPolicy.basis``).
BUDGET_POLICY_PER_CLASS = "per_class_pool"
BUDGET_POLICY_SHARED = "shared_multi_class_pool"

#: Whether a row's slot is a real draft position.
SLOT_KNOWN = "known"  # the league's draft order for that class is set on Sleeper
SLOT_PROJECTED = "projected"  # an estimated order (workbook / standings), labelled
SLOT_UNKNOWN = "unknown"  # no order exists yet — the row is round-only

#: How a row's value was derived.
VALUE_BASIS_WORKBOOK = "workbook"
VALUE_BASIS_CANONICAL_PREFIX = "canonical_"

#: Why a builder could not add the classes it does not cover.
ADDITIONAL_CLASSES_OBSERVED = "observed"
ADDITIONAL_CLASSES_NOT_REQUESTED = "not_requested"
ADDITIONAL_CLASSES_UNAVAILABLE = "unavailable"


def _current_draft_year(contract: Mapping[str, Any] | None) -> int:
    raw = (contract or {}).get("currentDraftYear") if isinstance(contract, Mapping) else None
    try:
        return int(raw)
    except (TypeError, ValueError):
        from src.api.data_contract import current_rookie_draft_year  # noqa: PLC0415

        return int(current_rookie_draft_year())


def canonical_pick_value(
    contract: Mapping[str, Any] | None,
    *,
    season: int,
    round_num: int,
    slot: int | None,
    rows_by_name: dict[str, dict[str, Any]] | None = None,
    league_size: int = 12,
) -> tuple[int | None, str | None]:
    """``(canonical value, valueBasis)`` for one league pick, or ``(None, reason)``.

    ``slot`` must be a REAL draft slot or ``None`` — a stand-in ordering never
    reaches here, because the canonical answer for an unknown slot is the
    generic grade.
    """
    if not isinstance(contract, Mapping) or not contract:
        return None, "no_contract_loaded"
    from src.api.pick_value_resolution import resolve_pick_value  # noqa: PLC0415

    res = _picks.market_resolution(
        year=int(season),
        round_num=int(round_num),
        slot=slot,
        current_draft_year=_current_draft_year(contract),
        league_size=league_size,
    )
    out = resolve_pick_value(dict(contract), res.ref, rows_by_name=rows_by_name)
    if out.value is None:
        return None, out.reason
    grade = {"exact_slot": "slot", "tier_from_slot": "tier", "unknown_slot": "generic_round"}
    return int(out.value), VALUE_BASIS_CANONICAL_PREFIX + grade.get(res.basis, res.basis)


def pick_rows_index(contract: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Index the contract's pick rows once for a batch of lookups."""
    if not isinstance(contract, Mapping) or not contract:
        return {}
    from src.api.pick_value_resolution import _pick_rows_by_name  # noqa: PLC0415

    return _pick_rows_by_name(dict(contract))


def build_class_picks(
    *,
    league_key: str,
    roster_name_by_id: Mapping[int, str],
    traded_picks: list[Any] | None,
    seasons: Iterable[int],
    rounds: int,
    contract: Mapping[str, Any] | None,
    slot_by_origin: Mapping[tuple[int, int], int] | None = None,
) -> list[dict[str, Any]]:
    """Owned-pick rows for ``seasons``, valued but not yet in dollars.

    Raises ``ValueError`` when ``traded_picks`` is ``None`` — an unobserved
    trade diff must never be folded as "nobody traded" (the caller decides
    how to refuse).  Each row carries a private ``_canonicalValue`` that
    :func:`price_per_class` turns into dollars and then removes, so the raw
    board value is never published.
    """
    if traded_picks is None:
        raise ValueError("traded_picks_not_observed")
    seasons = [int(s) for s in seasons]
    if not seasons or not roster_name_by_id:
        return []
    rids = sorted(int(r) for r in roster_name_by_id)
    owned = _picks.build_pick_ownership(
        league_key,
        rids,
        traded_picks,
        seasons=seasons,
        rounds=int(rounds),
        slot_by_origin=slot_by_origin,
    )
    index = pick_rows_index(contract)
    league_size = max(len(rids), 1)
    value_cache: dict[tuple[int, int, int | None], tuple[int | None, str | None]] = {}
    rows: list[dict[str, Any]] = []
    for op in sorted(
        owned,
        key=lambda o: (o.identity.season, o.identity.round_num, o.identity.origin_roster_id),
    ):
        ident, state = op.identity, op.state
        slot = state.slot if isinstance(state.slot, int) and state.slot > 0 else None
        key = (ident.season, ident.round_num, slot)
        if key not in value_cache:
            value_cache[key] = canonical_pick_value(
                contract,
                season=ident.season,
                round_num=ident.round_num,
                slot=slot,
                rows_by_name=index,
                league_size=league_size,
            )
        value, basis = value_cache[key]
        origin = int(ident.origin_roster_id)
        owner = int(state.owner_roster_id) if state.owner_roster_id is not None else None
        rows.append(
            {
                # Round-only label when the slot is unknown — never a made-up
                # "1.05".  ``pickInRound`` stays ``None`` for the same reason.
                "pick": f"{ident.round_num}.{slot:02d}" if slot else f"R{ident.round_num}",
                "season": ident.season,
                "round": ident.round_num,
                "pickInRound": slot,
                "slot": slot,
                "slotStatus": SLOT_KNOWN if slot else SLOT_UNKNOWN,
                "currentOwner": roster_name_by_id.get(owner, f"Team {owner}"),
                "originalOwner": roster_name_by_id.get(origin, f"Team {origin}"),
                "originRosterId": origin,
                "currentOwnerRosterId": owner,
                "assetId": ident.canonical_id,
                "isTraded": owner is not None and owner != origin,
                "isExpansion": False,
                "valueBasis": basis if value is not None else None,
                "unpricedReason": None if value is not None else basis,
                "dollarValueEstimated": True,
                "_canonicalValue": value,
            }
        )
    return rows


def _money(v: float) -> float | int:
    r = round(float(v), 2)
    return int(r) if r.is_integer() else r


def price_per_class(rows: list[dict[str, Any]], budget: int) -> list[dict[str, Any]]:
    """Spread ``budget`` over each class's PRICED picks, linearly in value.

    One pool per season (``per_class_pool``).  Picks with equal canonical
    value get equal dollars (rounded to the cent; no largest-remainder nudge
    that would price two identical generic picks differently), so a class
    total can differ from ``budget`` by rounding cents — the year summary
    publishes the actual sum.  Unpriced rows get ``None`` and no share.
    """
    totals: dict[int, float] = {}
    for r in rows:
        v = r.get("_canonicalValue")
        if isinstance(v, (int, float)) and v > 0:
            totals[int(r["season"])] = totals.get(int(r["season"]), 0.0) + float(v)
    for r in rows:
        v = r.pop("_canonicalValue", None)
        total = totals.get(int(r["season"]))
        if isinstance(v, (int, float)) and v > 0 and total:
            dollars = _money(float(v) * float(budget) / total)
            r["dollarValue"] = dollars
            r["adjustedDollarValue"] = dollars
            r["isUnpriced"] = False
        else:
            r["dollarValue"] = None
            r["adjustedDollarValue"] = None
            r["isUnpriced"] = True
    return rows


def budget_policy_block(
    basis: str, budget: int, seasons: Iterable[int], *, workbook_season: int | None = None
) -> dict[str, Any]:
    """What ``budgetPolicy`` says about a payload's dollars."""
    seasons = sorted({int(s) for s in seasons})
    block: dict[str, Any] = {
        "basis": basis,
        "budget": int(budget),
        "seasons": seasons,
        # The question is open: see the module docstring.  Stated on the
        # payload so the page can label the numbers instead of implying a
        # settled methodology.
        "status": "owner_confirmation_pending",
    }
    if basis == BUDGET_POLICY_PER_CLASS:
        block["classBudgets"] = {str(s): int(budget) for s in seasons}
        block["allYearsBudget"] = int(budget) * len(seasons)
        block["note"] = (
            "Each draft class is its own $%d pool. " % budget
            + (
                "The %d class uses the league workbook's dollars; " % workbook_season
                if workbook_season is not None
                else ""
            )
            + "later classes are estimated from canonical round values."
        )
    else:
        block["allYearsBudget"] = int(budget)
        block["note"] = (
            "One $%d pool is shared across every listed class; a year view "
            "adds up that year's share of it." % budget
        )
    return block
