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

Dollars — the $1,200 budget basis (OWNER DECISION 2026-10-18)
=============================================================

"$1,200 per draft class": each rookie draft class is its own $1,200 auction
pool (72 picks: 12 teams x 6 rounds).  **Scope: ``dynasty_main`` only**
(owner scope correction 2026-10-18 — the approval does not extend to any
other league).  Per-pick dollars are a linear share of their class's $1,200
over canonical values; All Years is the sum of the classes, each pick counted
once.

* The default league's workbook class keeps the workbook's own dollars (they
  are that class's $1,200 and the live auction budgets); its later classes
  are each their own $1,200 here (:func:`price_per_class`).
* The Sleeper-derived fallback (``draft_capital_fallback``, the path every
  non-default league takes) is OUT OF SCOPE and deliberately unchanged: it
  keeps its pre-decision single $1,200 pool and stamps no ``budgetPolicy``,
  which the frontend reads as "no multi-class basis stated".

Every class with a priced pick totals EXACTLY $1,200 in WHOLE DOLLARS (owner
decisions 2026-10-18): every final pick value is an integer from the
canonical whole-dollar step (``src.draft.rookie_auction.apportion``), and
every team total is the exact integer sum of the picks that team owns, so
pick dollars, team totals, year totals and All Years reconcile exactly.  The
workbook's half-dollar column survives only as reference data
(``workbookReferenceDollarValue``).

The SHAPE of a class's dollars is two different value domains, labelled per
class (``curveMethod``) and never presented as one methodology: the workbook
class follows the sheet's rookie-auction curve (``workbook_rookie_auction``);
every other class spreads canonical generic future-pick MARKET values
linearly (``interim_generic_market``) — an explicitly labelled INTERIM
("provisional estimate — final rookie-auction curve pending") until the
separate Draft Valuation workstream's spreadsheet-driven curve replaces it.
``budget_policy_block`` stamps the decided basis on every payload.

MISSING IS NEVER ZERO: a pick the board cannot price carries
``dollarValue: None`` + ``isUnpriced: True`` and stays out of its pool.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from typing import Any, Iterable, Mapping

from src.identity import picks as _picks

#: Budget-basis vocabulary (stamped on every payload as ``budgetPolicy.basis``).
#: The only basis since the owner decision of 2026-10-18 ("$1,200 per draft
#: class").  ``shared_multi_class_pool`` — one $1,200 spread across every
#: class — is retired; a payload carrying it predates the decision.
BUDGET_POLICY_PER_CLASS = "per_class_pool"
BUDGET_POLICY_STATUS_CONFIRMED = "owner_confirmed"
BUDGET_POLICY_DECIDED_BY = "owner"
BUDGET_POLICY_DECIDED_AT = "2026-10-18"

#: How a class's dollars are SHAPED across its picks (owner addendum
#: 2026-10-18).  Two different value domains, never presented as one:
#:
#: * ``workbook_rookie_auction`` — the default league's workbook class: the
#:   sheet's own rookie-auction curve and dollars.
#: * ``interim_generic_market`` — the default league's later classes: canonical
#:   generic future-pick MARKET values spread linearly over the class's
#:   $1,200.  An explicitly labelled INTERIM, not the final methodology — the
#:   spreadsheet-driven rookie-auction curve is a separate Draft Valuation
#:   workstream that will replace it.
CURVE_METHOD_WORKBOOK = "workbook_rookie_auction"
CURVE_METHOD_INTERIM_GENERIC_MARKET = "interim_generic_market"
CURVE_METHOD_INTERIM_LABEL = "provisional estimate — final rookie-auction curve pending"

#: Whether ``teamTotals`` (the UPCOMING class's per-team dollars — the
#: auction-budget basis /draft, the auction room, the /league simulator and
#: the /trade stack read) can be published.  MISSING IS NEVER ZERO: when the
#: budgets cannot be stated, every ``auctionDollars`` is ``None`` and the
#: reason is named — never a board of $0 budgets.
TEAM_TOTALS_STATE_FIELD = "teamTotalsState"
TEAM_TOTALS_REASON_FIELD = "teamTotalsReason"
TEAM_TOTALS_AVAILABLE = "available"
TEAM_TOTALS_UNAVAILABLE = "unavailable"
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


#: How the final whole-dollar allocation is made (owner decision 2026-10-18,
#: "whole dollars only"), stamped on payloads as ``wholeDollarAllocation.method``.
WHOLE_DOLLAR_METHOD = "floor_then_largest_remainder_earlier_pick_first"

#: Why the workbook class could not be published in whole dollars.
WHOLE_DOLLAR_REFUSED_ERROR = "draft_dollars_refused"


def _exact(value: Any) -> Fraction:
    """An exact rational for a board / workbook number (no float arithmetic)."""
    if isinstance(value, bool) or value is None:
        raise ValueError(f"not a number: {value!r}")
    if isinstance(value, float):
        # Decimal(str()) keeps the number as written in the source (the
        # workbook caches half-dollars such as 134.5) rather than its binary
        # expansion; non-finite values are refused by Decimal → Fraction.
        return Fraction(Decimal(str(value)))
    return Fraction(value)


def allocate_class_budget(values: list[float], budget: int) -> list[int]:
    """Spread ``budget`` WHOLE dollars over ``values`` linearly, EXACTLY.

    Owner decisions 2026-10-18: a class totals exactly its budget, in whole
    dollars only.  Each value's exact share (``value x budget / sum``, in
    Fractions — never floats) goes through THE canonical whole-dollar step,
    ``src.draft.rookie_auction.apportion.apportion_whole_dollars``: floor
    every share, then the integer residual by largest fractional remainder,
    ties to the earlier position.  The step requires draft-position order to
    be non-increasing, so shares are apportioned in value-descending order (a
    stable sort keeps the caller's season / round / origin order among equal
    values) and mapped back.  Two picks of identical value can differ by $1;
    that is the price of an exact whole-dollar total, and it is deterministic.

    ``[]`` → ``[]`` (nothing priced: no distribution is manufactured); a
    non-positive total gives every value 0.  Raises
    ``ApportionmentRefused`` rather than publish a total other than ``budget``.
    """
    from src.draft.rookie_auction.apportion import apportion_whole_dollars  # noqa: PLC0415

    if not values:
        return []
    exact = [_exact(v) for v in values]
    total = sum(exact, Fraction(0))
    if total <= 0:
        return [0] * len(values)
    shares = [v * int(budget) / total for v in exact]
    order = sorted(range(len(shares)), key=lambda i: -shares[i])
    result = apportion_whole_dollars([shares[i] for i in order], int(budget))
    out = [0] * len(values)
    for pos, i in enumerate(order):
        out[i] = int(result.dollars[pos])
    return out


def workbook_class_whole_dollars(
    reference_values: list[Any], budget: int
) -> tuple[list[int], dict[str, Any]]:
    """The workbook class's final whole-dollar pick values + a receipt.

    ``reference_values`` is the sheet's half-dollar "Final Dollar Per Pick"
    column (L2:L73) in draft order — kept as mathematical REFERENCE data.
    The operational dollars are the canonical rookie-auction calculation's
    separately identified final step (``apportion_whole_dollars`` with the
    formula's own floors and caps, ``curve.whole_dollar_constraints``).  Any
    violated constraint raises ``ApportionmentRefused``: the caller refuses
    the board rather than change the $1,200.
    """
    from src.draft.rookie_auction.apportion import apportion_whole_dollars  # noqa: PLC0415
    from src.draft.rookie_auction.curve import whole_dollar_constraints  # noqa: PLC0415

    floors, caps = whole_dollar_constraints()
    # The formula's round floors / caps are defined for its own 72-pick
    # draft (12 x 6, dynasty_main).  A workbook of any other size still gets
    # integers, the exact total and the non-increasing check; the receipt
    # says the round bounds did not apply rather than pretending they did.
    bounds_apply = len(reference_values) == len(floors)
    result = apportion_whole_dollars(
        [_exact(v) for v in reference_values],
        int(budget),
        floors=floors if bounds_apply else None,
        caps=caps if bounds_apply else None,
    )
    receipt = {
        "method": WHOLE_DOLLAR_METHOD,
        "referenceColumn": "Draft Data!L2:L73 (half-dollar reference)",
        "roundBoundsApplied": bounds_apply,
        "floored": sum(result.floored),
        "residual": result.residual,
        "plusOneOverallPicks": [i + 1 for i in result.plus_one_indices],
        "total": result.total,
    }
    return [int(d) for d in result.dollars], receipt


def price_per_class(rows: list[dict[str, Any]], budget: int) -> list[dict[str, Any]]:
    """Spread ``budget`` over each class's PRICED picks, linearly in value.

    One pool per season (``per_class_pool``), allocated by
    :func:`allocate_class_budget`, so every class with a priced pick totals
    exactly ``budget``.  Unpriced rows get ``None`` and no share.  Every row
    is stamped with the class's ``curveMethod`` (interim, see
    :data:`CURVE_METHOD_INTERIM_GENERIC_MARKET`).
    """
    by_season: dict[int, list[int]] = {}
    for i, r in enumerate(rows):
        v = r.get("_canonicalValue")
        if isinstance(v, (int, float)) and v > 0:
            by_season.setdefault(int(r["season"]), []).append(i)
    dollars_by_index: dict[int, int | float] = {}
    for indices in by_season.values():
        alloc = allocate_class_budget([float(rows[i]["_canonicalValue"]) for i in indices], budget)
        dollars_by_index.update(zip(indices, alloc))
    for i, r in enumerate(rows):
        r.pop("_canonicalValue", None)
        r["curveMethod"] = CURVE_METHOD_INTERIM_GENERIC_MARKET
        if i in dollars_by_index:
            r["dollarValue"] = dollars_by_index[i]
            r["adjustedDollarValue"] = dollars_by_index[i]
            r["isUnpriced"] = False
        else:
            r["dollarValue"] = None
            r["adjustedDollarValue"] = None
            r["isUnpriced"] = True
    return rows


def budget_policy_block(
    budget: int,
    seasons: Iterable[int],
    *,
    workbook_season: int | None = None,
    priced_seasons: Iterable[int] | None = None,
) -> dict[str, Any]:
    """What ``budgetPolicy`` says about a payload's dollars.

    One basis (owner decision 2026-10-18, ``dynasty_main`` only): each listed class
    is its own ``budget`` pool and All Years is their sum.  ``priced_seasons``
    (default: every listed class) names the classes with at least one priced
    pick; a class the board cannot price at all holds no dollars, so it is
    listed in ``unpricedClasses`` and left out of ``allYearsBudget`` rather
    than counted as a $1,200 nobody can see.
    """
    seasons = sorted({int(s) for s in seasons})
    priced = (
        seasons
        if priced_seasons is None
        else sorted({int(s) for s in priced_seasons} & set(seasons))
    )
    estimated = [s for s in seasons if workbook_season is None or s != int(workbook_season)]
    return {
        "basis": BUDGET_POLICY_PER_CLASS,
        "budget": int(budget),
        "seasons": seasons,
        "status": BUDGET_POLICY_STATUS_CONFIRMED,
        "decidedBy": BUDGET_POLICY_DECIDED_BY,
        "decidedAt": BUDGET_POLICY_DECIDED_AT,
        "classBudgets": {str(s): int(budget) for s in seasons},
        "unpricedClasses": [s for s in seasons if s not in priced],
        "allYearsBudget": int(budget) * len(priced),
        "classCurveMethods": {
            str(s): (
                CURVE_METHOD_WORKBOOK
                if workbook_season is not None and s == int(workbook_season)
                else CURVE_METHOD_INTERIM_GENERIC_MARKET
            )
            for s in seasons
        },
        "interimCurveLabel": CURVE_METHOD_INTERIM_LABEL if estimated else None,
        "note": (
            "Each draft class is its own $%d pool; All Years adds the classes together. " % budget
            + (
                "The %d class uses the league workbook's dollars; " % int(workbook_season)
                if workbook_season is not None
                else ""
            )
            + (
                "%s dollars are a %s (interim generic market values)."
                % (", ".join(str(s) for s in estimated), CURVE_METHOD_INTERIM_LABEL)
                if estimated
                else ""
            )
        ).strip(),
    }
