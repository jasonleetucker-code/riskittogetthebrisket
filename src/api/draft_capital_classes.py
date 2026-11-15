"""Every league draft class on one draft-capital board (owner directive 2026-10-17).

The /league Draft Capital tab must show EVERY class the league still owns
picks in — for ``dynasty_main`` in October 2026 that is 2027, 2028 and 2029 —
not only the class the default league's workbook happens to carry.  This
module produces the owned-pick rows for the classes a builder does not
already cover and prices them on the canonical rookie-auction curve.  It
decides nothing about which classes exist, who owns a pick, or what the curve
is:

* **Which classes** — the league-scoped resolver
  (``pick_lifecycle.league_draft_years`` via
  ``draft_class_evidence.league_draft_years_for``).  A class the league has
  drafted and rostered is retired there and never reaches this module, so a
  completed rookie class cannot reappear as future capital.
* **Who owns each pick** — THE ownership fold,
  ``identity.picks.build_pick_ownership``, over the league's own rosters and
  an OBSERVED ``/traded_picks`` diff (``picks.traded_picks_observation``).
  The caller must not pass ``[]`` for a failed fetch; ``None`` refuses.
* **What a class's 72 picks are worth** — the canonical rookie-auction
  calculation (``src/draft/rookie_auction``): the owner-approved spreadsheet
  formula over the class's rookie inputs and its three-completed-class spine,
  made whole dollars by ``apportion.apportion_whole_dollars`` (the formula's
  floors and caps) and resolved per draft year through
  ``published.resolve_published_allocation`` (verified current, else THAT
  year's last known good, else unavailable).  Never another year's
  allocation, never $0.

Dollars — the $1,200 budget basis (OWNER DECISION 2026-10-18)
=============================================================

"$1,200 per draft class": each rookie draft class is its own $1,200 auction
pool (72 picks: 12 teams x 6 rounds).  **Scope: ``dynasty_main`` only**
(owner scope correction 2026-10-18 — any other league is "not configured"
and its later classes stay UNPRICED with that reason, never adapted).  All
Years is the sum of the classes, each pick counted once.

* The default league's upcoming class (the one the workbook describes) is
  priced by the SAME canonical reader as every later class (Batch F,
  ``generation.read_class_generation``); the workbook's L2:L73 column is a
  parity diagnostic only.  Its dollars are that class's $1,200 and the live
  auction budgets.
* Every later class (Batch E, owner directive 2026-10-18) is priced on the
  SAME formula: until Batch D promotes a class's real rookie inputs, its
  inputs are the frozen owner-approved 2026 provisional baseline
  (``inputMode: "frozen_fallback"``) and its spine is the three most recent
  completed classes before it — a provisional estimate, labelled as such.
  Two classes with identical inputs and spine produce identical dollars; each
  is still resolved and stored under its OWN year.
* The Sleeper-derived fallback (``draft_capital_fallback``, the path every
  non-default league takes) is OUT OF SCOPE and deliberately unchanged.

Slots.  A later class's dollars are by draft POSITION.  A pick whose class
has a real Sleeper draft order takes its slot's dollars; a pick with no known
slot is ROUND-LEVEL: the unclaimed slots of its round are shared equally
among its round's unknown-slot picks in whole dollars (they can differ by $1
so the round keeps its exact dollars; the extra dollars go in a fixed,
roster-neutral order).  No slot is ever invented.

Every class with a priced pick totals EXACTLY $1,200 in WHOLE DOLLARS, and
every team total is the exact integer sum of the picks that team owns.

MISSING IS NEVER ZERO: a pick that cannot be priced carries
``dollarValue: None`` + ``isUnpriced: True`` + ``unpricedReason`` and stays
out of every total.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from fractions import Fraction
from typing import Any, Iterable, Mapping, Sequence

from src.draft.rookie_auction.generation import (  # noqa: F401 — re-exported names
    INPUT_MODE_ACTUAL,
    INPUT_MODE_FROZEN_FALLBACK,
    PROMOTED_CLASS_SNAPSHOT_SOURCE,
    ClassCurveInputs,
    class_curve_inputs,
    curve_id,
    generation_receipt,
    input_mode_of,
)
from src.identity import picks as _picks

#: Budget-basis vocabulary (stamped on every payload as ``budgetPolicy.basis``
#: and per class as ``budgetPolicy.classes[year].budgetBasis``).  The only
#: basis since the owner decision of 2026-10-18 ("$1,200 per draft class").
#: ``shared_multi_class_pool`` — one $1,200 spread across every class — is
#: retired; a payload carrying it predates the decision.
BUDGET_POLICY_PER_CLASS = "per_class_pool"
BUDGET_POLICY_STATUS_CONFIRMED = "owner_confirmed"
BUDGET_POLICY_DECIDED_BY = "owner"
BUDGET_POLICY_DECIDED_AT = "2026-10-18"

#: How a class's dollars are SHAPED across its picks.  Since Batch E every
#: ``dynasty_main`` class is shaped by the one owner-approved formula — the
#: workbook's rookie-auction curve (``src/draft/rookie_auction``).  The former
#: ``interim_generic_market`` label (canonical generic future-pick MARKET
#: values spread linearly, #1785) is RETIRED with the code that produced it;
#: a payload carrying it predates Batch E.
CURVE_METHOD_WORKBOOK = "workbook_rookie_auction"
#: A class whose curve could not be resolved (unconfigured league, no
#: verified allocation): it carries no dollars, so it has no curve either.
CURVE_METHOD_NONE = "none"

#: Which rookie inputs fed a class's curve (``inputMode``).  ``frozen_fallback``
#: is the owner-approved PROVISIONAL 2026 baseline (``Draft Data!B2:B73``,
#: frozen with provenance) — every class priced on it is a provisional
#: estimate.  ``actual`` is the class's own rookie values, which only Batch D's
#: promotion can supply.  ``None`` = the served record does not say (unknown,
#: never guessed).
PROVISIONAL_CURVE_LABEL = (
    "provisional estimate — the rookie-auction formula on the frozen 2026 provisional "
    "rookie inputs (actual class inputs pending)"
)

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
#: The order follows the league's draft-order rule over VERIFIED final
#: regular-season standings (``src/api/draft_capital_order.py``).
SLOT_FINAL_STANDINGS = "final_standings"
SLOT_PROJECTED = "projected"  # an estimated order (workbook / standings to date), labelled
SLOT_UNKNOWN = "unknown"  # no order exists yet — the row is round-only

#: How a row's value was derived.
VALUE_BASIS_WORKBOOK = "workbook"
#: A later-class pick at a known slot: that slot's whole dollars.
VALUE_BASIS_ROOKIE_AUCTION_SLOT = "rookie_auction_slot"
#: A later-class pick with no known slot: an equal whole-dollar share of its
#: round's unclaimed slot dollars.
VALUE_BASIS_ROOKIE_AUCTION_ROUND = "rookie_auction_round_share"
#: How a round's unclaimed dollars are shared among its unknown-slot picks.
ROUND_SHARE_RULE = "equal_whole_dollar_share__extra_dollars_by_sha256_of_asset_id"

#: Why a builder could not add the classes it does not cover.
ADDITIONAL_CLASSES_OBSERVED = "observed"
ADDITIONAL_CLASSES_NOT_REQUESTED = "not_requested"
ADDITIONAL_CLASSES_UNAVAILABLE = "unavailable"


def build_class_picks(
    *,
    league_key: str,
    roster_name_by_id: Mapping[int, str],
    traded_picks: list[Any] | None,
    seasons: Iterable[int],
    rounds: int,
    slot_by_origin: Mapping[tuple[int, int], int] | None = None,
) -> list[dict[str, Any]]:
    """Owned-pick rows for ``seasons`` — identity and ownership, no dollars yet.

    Raises ``ValueError`` when ``traded_picks`` is ``None`` — an unobserved
    trade diff must never be folded as "nobody traded" (the caller decides
    how to refuse).  :func:`price_classes_on_curve` adds the dollars.
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
    rows: list[dict[str, Any]] = []
    for op in sorted(
        owned,
        key=lambda o: (o.identity.season, o.identity.round_num, o.identity.origin_roster_id),
    ):
        ident, state = op.identity, op.state
        slot = state.slot if isinstance(state.slot, int) and state.slot > 0 else None
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
                "dollarValueEstimated": True,
            }
        )
    return rows


# --- the later classes' curve (Batch E) — read through THE generation reader (Batch F) ---

# The class candidate, its inputs and its receipt are owned by
# ``src/draft/rookie_auction/generation.py`` (one reader for every consumer of
# auction dollars); ``ClassCurveInputs`` / ``class_curve_inputs`` /
# ``curve_id`` are re-exported from it for existing callers.


def resolve_class_curve_allocation(
    league_key: str,
    draft_year: int,
    *,
    now: str | None = None,
    config_dir: Any = None,
    store_dirs: Sequence[Any] | None = None,
    write_dir: Any = None,
    persist: bool = True,
):
    """The published 72-pick whole-dollar allocation for one class.

    Delegates to THE reader (``generation.read_class_generation``): the
    spreadsheet formula over :func:`class_curve_inputs` and the class's own
    three-completed-class spine, handed to the canonical resolver (whole
    dollars, independent verifier, create-only storage under THIS year, else
    THIS year's last known good or ``unavailable``).  Never another year's
    allocation, never $0.  ``class_curve_inputs`` is looked up in this module
    at call time, so a caller (or test) that replaces it here is honoured.
    """
    from src.draft.rookie_auction.generation import read_class_generation  # noqa: PLC0415

    return read_class_generation(
        league_key,
        draft_year,
        now=now,
        config_dir=config_dir,
        inputs_fn=class_curve_inputs,
        store_dirs=store_dirs,
        write_dir=write_dir,
        persist=persist,
    ).allocation


def _share_order_key(row: Mapping[str, Any]) -> tuple[str, str]:
    """A fixed, roster-neutral order for a round's extra dollars.

    Sorting by roster id would hand the same low-id rosters every extra dollar
    in every round of every class; a hash of the canonical pick id spreads
    them with no systematic tilt, and is reproducible from the payload.  The
    caller guarantees every row has a canonical ``assetId`` (a row without one
    refuses its class — there is no identity to order it by).
    """
    ident = str(row["assetId"])
    return hashlib.sha256(ident.encode("utf-8")).hexdigest(), ident


def _unprice(row: dict[str, Any], reason: str, curve_method: str) -> None:
    row["dollarValue"] = None
    row["adjustedDollarValue"] = None
    row["isUnpriced"] = True
    row["valueBasis"] = None
    row["unpricedReason"] = reason
    row["curveMethod"] = curve_method


def _price_one_class(
    rows: list[dict[str, Any]], published: Any, team_count: int, rounds: int, input_mode: Any
) -> str | None:
    """Price one class's rows in place; ``None`` on success, else the reason."""
    from src.draft.rookie_auction.apportion import (  # noqa: PLC0415
        ApportionmentRefused,
        apportion_whole_dollars,
    )

    if published is None or getattr(published, "final_whole_dollars", None) is None:
        return (
            f"no_verified_class_allocation:{getattr(published, 'unavailable_reason', None)}"
            if published is not None
            else "no_class_allocation_resolved"
        )
    dollars = list(published.final_whole_dollars)
    if len(dollars) != team_count * rounds:
        return f"class_shape_mismatch:allocation_has_{len(dollars)}_picks"
    by_round: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        by_round.setdefault(int(r["round"]), []).append(r)
    if sorted(by_round) != list(range(1, rounds + 1)) or any(
        len(v) != team_count for v in by_round.values()
    ):
        counts = {k: len(v) for k, v in sorted(by_round.items())}
        return f"class_shape_mismatch:expected_{team_count}x{rounds}:got_{counts}"
    assigned: dict[int, tuple[int, str, float | None]] = {}
    for rnd, round_rows in by_round.items():
        slot_dollars = dollars[(rnd - 1) * team_count : rnd * team_count]
        claimed: set[int] = set()
        unknown: list[dict[str, Any]] = []
        for r in round_rows:
            slot = r.get("slot")
            if isinstance(slot, int) and not isinstance(slot, bool) and slot > 0:
                if slot > team_count or slot in claimed:
                    return f"slot_conflict:round_{rnd}_slot_{slot}"
                claimed.add(slot)
                assigned[id(r)] = (slot_dollars[slot - 1], VALUE_BASIS_ROOKIE_AUCTION_SLOT, None)
            else:
                unknown.append(r)
        if not unknown:
            continue
        if any(not isinstance(r.get("assetId"), str) or not r["assetId"] for r in unknown):
            return f"asset_id_missing:round_{rnd}"
        pool = [d for s, d in enumerate(slot_dollars, start=1) if s not in claimed]
        total = sum(pool)
        unknown.sort(key=_share_order_key)
        k = len(unknown)
        try:
            share = apportion_whole_dollars([Fraction(total, k)] * k, total)
        except ApportionmentRefused as exc:  # cannot happen for equal shares; fail closed
            return f"round_share_refused:round_{rnd}:{exc}"
        average = round(total / k, 4)
        for r, d in zip(unknown, share.dollars):
            assigned[id(r)] = (int(d), VALUE_BASIS_ROOKIE_AUCTION_ROUND, average)
    for r in rows:
        d, basis, average = assigned[id(r)]
        r["dollarValue"] = d
        r["adjustedDollarValue"] = d
        r["isUnpriced"] = False
        r["valueBasis"] = basis
        r["unpricedReason"] = None
        r["curveMethod"] = CURVE_METHOD_WORKBOOK
        r["inputMode"] = input_mode
        if average is not None:
            # The exact round-level expectation the whole-dollar share rounds
            # (reference only — never spendable).
            r["roundShareReferenceDollars"] = average
            r["roundShareRule"] = ROUND_SHARE_RULE
    return None


def price_classes_on_curve(
    rows: list[dict[str, Any]],
    allocations: Mapping[int, Any],
    *,
    team_count: int,
    rounds: int,
) -> list[dict[str, Any]]:
    """Put whole dollars on every later-class row, one class at a time.

    ``allocations`` maps a season to its :class:`PublishedAllocation`
    (:func:`resolve_class_curve_allocation`).  A class prices only when its
    allocation is verified AND the league's class is exactly the formula's
    shape (``team_count`` x ``rounds`` owned picks, every round full); a pick
    at a known slot takes that slot's dollars and the round's unknown-slot
    picks share its unclaimed slots equally.  Otherwise EVERY pick in the
    class is unpriced with the reason — never partly priced, never $0, never
    another class's dollars.  The class then totals exactly its allocation's
    $1,200.
    """
    by_season: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        by_season.setdefault(int(r["season"]), []).append(r)
    for season, class_rows in by_season.items():
        published = allocations.get(season)
        mode = class_input_mode(published)
        reason = _price_one_class(class_rows, published, int(team_count), int(rounds), mode)
        if reason is not None:
            for r in class_rows:
                _unprice(r, reason, CURVE_METHOD_NONE)
                r["inputMode"] = None
    return rows


def _record_provenance(published: Any) -> Mapping[str, Any]:
    receipt = getattr(published, "receipt", None) or {}
    prov = receipt.get("provenance") if isinstance(receipt, Mapping) else None
    return prov if isinstance(prov, Mapping) else {}


def class_input_mode(published: Any) -> str | None:
    """The ``inputMode`` of the SERVED record (a last-known-good record says
    what IT was computed from), or ``None`` when it does not say.  One
    definition: ``generation.input_mode_of``."""
    return input_mode_of(published)


def class_valuation_block(
    published: Any, *, draft_year: int, budget: int, priced: bool
) -> dict[str, Any]:
    """The per-year API block: ``budgetBasis``, ``curveId``, ``spineYears``,
    ``inputMode`` and which allocation was served.

    Read from the SERVED record's provenance — never from what this request
    tried to compute — so a ``last_known_good`` answer describes the curve
    actually published.  A field the record does not carry is ``None``.
    """
    prov = _record_provenance(published)
    receipt = getattr(published, "receipt", None) or {}
    formula = receipt.get("formulaVersion") if isinstance(receipt, Mapping) else None
    spine = prov.get("spineYears")
    spine_years = [int(y) for y in spine] if isinstance(spine, list) else None
    mode = class_input_mode(published)
    cid = prov.get("curveId")
    if not cid and published is not None and getattr(published, "record_checksum", None):
        if formula and mode and spine_years:
            source = (
                prov.get("inputsId")
                or ("workbook" if prov.get("workbookSha256") else None)
                or str(prov.get("classSnapshotSha256") or "")[:16]
                or None
            )
            cid = curve_id(str(formula), mode, source, spine_years)
        else:
            cid = f"{formula}|record:{str(published.record_checksum)[:16]}"
    state = getattr(published, "allocation_state", None) if published is not None else None
    # The Batch F receipt — one definition (``generation.generation_receipt``).
    gr = generation_receipt(published, int(draft_year))
    return {
        "draftYear": int(draft_year),
        "targetDraftYear": gr["targetDraftYear"],
        "generationHash": gr["generationHash"],
        "curveVersion": gr["curveVersion"] if priced else None,
        "budgetBasis": BUDGET_POLICY_PER_CLASS,
        "budget": int(budget),
        "curveMethod": CURVE_METHOD_WORKBOOK if priced else CURVE_METHOD_NONE,
        "curveId": cid if priced else None,
        "formulaVersion": formula if priced else None,
        "spineYears": spine_years if priced else None,
        "inputMode": mode if priced else None,
        "actualInputClassYear": gr["actualInputClassYear"] if priced else None,
        # Frozen inputs = a provisional estimate; unknown inputs are not
        # claimed to be actual either.
        "provisional": (mode != INPUT_MODE_ACTUAL) if priced else None,
        "allocationState": state,
        "effectiveAt": getattr(published, "effective_at", None),
        "lastValidAt": getattr(published, "last_valid_at", None),
        "failedRefresh": (
            dict(published.failed_refresh)
            if published is not None and getattr(published, "failed_refresh", None)
            else None
        ),
        "unavailableReason": getattr(published, "unavailable_reason", None),
        "warning": getattr(published, "warning", None),
        "recordChecksum": getattr(published, "record_checksum", None),
    }


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


#: The workbook class has no verified whole-dollar allocation to publish.
DRAFT_DOLLARS_UNAVAILABLE_ERROR = "draft_dollars_unavailable"


def formula_pick_count() -> int:
    """Picks in the formula's own class (dynasty_main: 12 x 6 = 72)."""
    from src.draft.rookie_auction.curve import WORKBOOK_PARAMS  # noqa: PLC0415

    return int(WORKBOOK_PARAMS.pick_count)


#: ``workbookParity.state`` vocabulary (Batch F).
WORKBOOK_PARITY_MATCHES = "matches"
WORKBOOK_PARITY_DIFFERS = "differs"
WORKBOOK_PARITY_NOT_COMPARED = "not_compared"


def workbook_parity_block(workbook_values: Any, served_reference: Any) -> dict[str, Any]:
    """Does the workbook's L2:L73 still equal the served class curve?

    Batch F reads the upcoming class's dollars from the canonical generation
    reader; the workbook's "Final Dollar Per Pick" column is the SAME quantity
    for the class it was built for, so it is kept as a diagnostic only.  A
    difference is reported (``differs`` + the picks), never silently applied
    in either direction.  Exact comparison — no float tolerance.
    """
    from src.draft.rookie_auction.curve import iter_labels  # noqa: PLC0415

    base: dict[str, Any] = {"range": "Draft Data!L2:L73", "authority": "diagnostic_only"}
    if served_reference is None:
        return {**base, "state": WORKBOOK_PARITY_NOT_COMPARED, "reason": "no_served_allocation"}
    if not workbook_values:
        return {**base, "state": WORKBOOK_PARITY_NOT_COMPARED, "reason": "workbook_column_missing"}
    served = list(served_reference)
    sheet = list(workbook_values)[: len(served)]
    if len(sheet) != len(served):
        return {
            **base,
            "state": WORKBOOK_PARITY_NOT_COMPARED,
            "reason": f"workbook_column_has_{len(sheet)}_of_{len(served)}_picks",
        }
    labels = list(iter_labels())
    mismatched: list[dict[str, Any]] = []
    for i, (w, r) in enumerate(zip(sheet, served)):
        try:
            same = _exact(w) == _exact(r)
        except (ArithmeticError, ValueError, TypeError):
            same = False
        if not same:
            mismatched.append(
                {"pick": labels[i] if i < len(labels) else str(i + 1), "workbook": w, "served": r}
            )
    return {
        **base,
        "state": WORKBOOK_PARITY_DIFFERS if mismatched else WORKBOOK_PARITY_MATCHES,
        "reason": None,
        "comparedPicks": len(served),
        "mismatchCount": len(mismatched),
        "mismatchedPicks": mismatched[:12],
    }


def draft_valuation_state_block(published: Any) -> dict[str, Any]:
    """The payload's ``draftValuation`` block: which allocation was published
    and why, plus the Batch F receipt — never ownership, never the per-pick
    arrays twice."""
    return {
        **generation_receipt(published, int(published.draft_year)),
        "allocationState": published.allocation_state,
        "draftYear": published.draft_year,
        "effectiveAt": published.effective_at,
        "lastValidAt": published.last_valid_at,
        "failedRefresh": dict(published.failed_refresh) if published.failed_refresh else None,
        "warning": published.warning,
        "recordChecksum": published.record_checksum,
    }


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


def budget_policy_block(
    budget: int,
    seasons: Iterable[int],
    *,
    workbook_season: int | None = None,
    priced_seasons: Iterable[int] | None = None,
    classes: Mapping[int, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """What ``budgetPolicy`` says about a payload's dollars.

    One basis (owner decision 2026-10-18, ``dynasty_main`` only): each listed
    class is its own ``budget`` pool and All Years is their sum.
    ``priced_seasons`` (default: every listed class) names the classes with at
    least one priced pick; a class that cannot be priced holds no dollars, so
    it is listed in ``unpricedClasses`` and left out of ``allYearsBudget``
    rather than counted as a $1,200 nobody can see.  ``classes`` carries the
    per-year blocks (:func:`class_valuation_block`) — ``budgetBasis``,
    ``curveId``, ``spineYears``, ``inputMode`` — keyed by season.
    """
    seasons = sorted({int(s) for s in seasons})
    priced = (
        seasons
        if priced_seasons is None
        else sorted({int(s) for s in priced_seasons} & set(seasons))
    )
    per_class = {int(k): dict(v) for k, v in (classes or {}).items() if int(k) in seasons}
    provisional = [s for s in seasons if per_class.get(s, {}).get("provisional") is True]
    methods = {
        str(s): (
            per_class[s].get("curveMethod")
            if s in per_class
            else (CURVE_METHOD_WORKBOOK if s in priced else CURVE_METHOD_NONE)
        )
        for s in seasons
    }
    note = "Each draft class is its own $%d pool; All Years adds the classes together." % budget
    if workbook_season is not None:
        note += " The %d class is the league's upcoming auction." % int(workbook_season)
    if provisional:
        note += " %s dollars: %s." % (
            ", ".join(str(s) for s in provisional),
            PROVISIONAL_CURVE_LABEL,
        )
    unpriced = [s for s in seasons if s not in priced]
    if unpriced:
        note += " %s: not priced (no verified class allocation)." % ", ".join(
            str(s) for s in unpriced
        )
    return {
        "basis": BUDGET_POLICY_PER_CLASS,
        "budget": int(budget),
        "seasons": seasons,
        "status": BUDGET_POLICY_STATUS_CONFIRMED,
        "decidedBy": BUDGET_POLICY_DECIDED_BY,
        "decidedAt": BUDGET_POLICY_DECIDED_AT,
        "classBudgets": {str(s): int(budget) for s in seasons},
        "unpricedClasses": unpriced,
        "allYearsBudget": int(budget) * len(priced),
        "classCurveMethods": methods,
        # Retired with the interim generic-market curve (Batch E); kept as
        # ``None`` so an older reader sees "no interim class", not a KeyError.
        "interimCurveLabel": None,
        "provisionalClasses": provisional,
        "provisionalCurveLabel": PROVISIONAL_CURVE_LABEL if provisional else None,
        "classes": {str(s): per_class[s] for s in seasons if s in per_class},
        "note": note,
    }
