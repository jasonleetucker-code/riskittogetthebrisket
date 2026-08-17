"""Events → holding periods and pick lineage.  A pure replay.

DETERMINISM IS THE WHOLE CONTRACT
─────────────────────────────────
These are derivations, not records.  Replaying the same events must
produce byte-identical output regardless of the order they were
ingested in, so the ordering rule lives in
``store.read_events`` and nothing here depends on insertion order,
wall-clock time, or dict iteration.

That is what makes the backfill safe to re-run and makes "rebuild from
scratch" a valid repair for any derived-table corruption.

REACQUISITION OPENS A NEW PERIOD
────────────────────────────────
Owning a player, trading him away, and trading him back is three facts,
not one.  Each ``(league, asset, owner)`` gets an incrementing
``sequence_num``; the earlier period keeps its own ``acquired_at`` and
``disposed_at`` and is never mutated.  Collapsing them would make "how
long did he hold him" unanswerable and would silently merge two
different cost bases.

IMPORT_UNKNOWN IS FAIL-CLOSED, AND THAT IS THE POINT
────────────────────────────────────────────────────
An asset on a roster with no explaining event gets
``acquired_method = "IMPORT_UNKNOWN"``, an undated acquisition, and
``basis_missing_reason = "no_explaining_event"``.

Defaulting it to ``FREE_AGENT`` because most such assets were free
agents is "missing is zero" wearing a label: it would report a $0 cost
basis the platform never observed, and every downstream profit figure
would inherit it.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from src.acquisition.events import ACQUISITION_METHODS, ASSET_PICK, DISPOSAL_METHODS

ORDER_FIDELITY_ORDERED = "ordered"
ORDER_FIDELITY_UNDATED_PRESENT = "undated_event_present"

BASIS_REASON_NO_EVENT = "no_explaining_event"


def _is_acquisition(event_type: str) -> bool:
    return event_type in ACQUISITION_METHODS


def _is_disposal(event_type: str) -> bool:
    return event_type in DISPOSAL_METHODS


def derive_holdings(
    league_key: str,
    events: Sequence[dict[str, Any]],
    *,
    current_rosters: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Replay ``events`` (already in ``store.read_events`` order).

    ``current_rosters`` maps ``asset_id`` → owning ``roster_id`` right
    now.  When supplied, any asset held today with no explaining
    acquisition event is minted as ``IMPORT_UNKNOWN`` rather than being
    left out — an asset that exists on a roster is a fact, and omitting
    it would make the projection quietly incomplete instead of
    explicitly uncertain.
    """
    any_undated = any(e.get("occurred_at_ms") is None for e in events)
    order_fidelity = ORDER_FIDELITY_UNDATED_PRESENT if any_undated else ORDER_FIDELITY_ORDERED

    # asset_id -> the open holding dict, if any
    open_by_asset: dict[str, dict[str, Any]] = {}
    # (asset_id, owner_rid) -> how many periods have started
    seq_by_pair: dict[tuple[str, int], int] = {}
    out: list[dict[str, Any]] = []

    def _open(asset_id: str, owner_rid: int, ev: dict[str, Any]) -> None:
        pair = (asset_id, owner_rid)
        seq_by_pair[pair] = seq_by_pair.get(pair, 0) + 1
        holding = {
            "league_key": league_key,
            "asset_id": asset_id,
            "owner_rid": owner_rid,
            "sequence_num": seq_by_pair[pair],
            "acquired_at_ms": ev.get("occurred_at_ms"),
            "acquired_ref": ev.get("source_ref"),
            "acquired_method": ev.get("event_type"),
            "disposed_at_ms": None,
            "disposed_ref": None,
            "disposed_method": None,
            "basis_value": None,
            "basis_fidelity": None,
            "basis_missing_reason": None,
            "order_fidelity": order_fidelity,
        }
        open_by_asset[asset_id] = holding
        out.append(holding)

    def _close(asset_id: str, ev: dict[str, Any], method: str) -> None:
        holding = open_by_asset.pop(asset_id, None)
        if holding is None:
            return
        holding["disposed_at_ms"] = ev.get("occurred_at_ms")
        holding["disposed_ref"] = ev.get("source_ref")
        holding["disposed_method"] = method

    for ev in events:
        asset_id = str(ev.get("asset_id") or "")
        if not asset_id:
            continue
        event_type = str(ev.get("event_type") or "")
        after = ev.get("after_owner_rid")
        before = ev.get("before_owner_rid")

        # DIRECTION IS DECIDED BY ``after_owner_rid``, NOT BY THE METHOD
        # NAME.  ``COMMISSIONER`` is deliberately in both vocabularies —
        # a commissioner can hand an asset to a roster or take one off
        # — so branching on the name would silently drop every
        # commissioner ADD.  The owner field is the fact; the method
        # only names how it happened.
        if after is None:
            if _is_disposal(event_type):
                _close(asset_id, ev, event_type)
            continue

        if not _is_acquisition(event_type):
            continue

        # A transfer closes the giving side's period with the SAME
        # event.  Without this the previous holder's period would stay
        # open forever and two managers would own one asset at once.
        current = open_by_asset.get(asset_id)
        if current is not None:
            if current["owner_rid"] == after:
                # Already theirs — an idempotent restatement, not a
                # reacquisition.  Opening a second period here is how a
                # re-ingest inflates history.
                continue
            _close(
                asset_id,
                ev,
                "TRADE_AWAY" if event_type == "TRADE" else "DROP",
            )
        elif before is not None:
            # We learned about the giving side only now.  Record the
            # prior period so lineage is not silently truncated.
            pair = (asset_id, int(before))
            seq_by_pair[pair] = seq_by_pair.get(pair, 0) + 1
            out.append(
                {
                    "league_key": league_key,
                    "asset_id": asset_id,
                    "owner_rid": int(before),
                    "sequence_num": seq_by_pair[pair],
                    "acquired_at_ms": None,
                    "acquired_ref": ev.get("source_ref"),
                    "acquired_method": "IMPORT_UNKNOWN",
                    "disposed_at_ms": ev.get("occurred_at_ms"),
                    "disposed_ref": ev.get("source_ref"),
                    "disposed_method": ("TRADE_AWAY" if event_type == "TRADE" else "DROP"),
                    "basis_value": None,
                    "basis_fidelity": None,
                    "basis_missing_reason": BASIS_REASON_NO_EVENT,
                    "order_fidelity": order_fidelity,
                }
            )

        _open(asset_id, int(after), ev)

    if current_rosters:
        for asset_id, owner_rid in sorted(current_rosters.items()):
            held = open_by_asset.get(asset_id)
            if held is not None and held["owner_rid"] == int(owner_rid):
                continue
            if held is not None:
                # The roster says someone else owns it now and no event
                # explains the move.  Close what we had and mint the
                # unexplained period rather than pretending continuity.
                held["disposed_at_ms"] = None
                held["disposed_ref"] = None
                held["disposed_method"] = "COMMISSIONER"
            pair = (asset_id, int(owner_rid))
            seq_by_pair[pair] = seq_by_pair.get(pair, 0) + 1
            holding = {
                "league_key": league_key,
                "asset_id": asset_id,
                "owner_rid": int(owner_rid),
                "sequence_num": seq_by_pair[pair],
                "acquired_at_ms": None,
                "acquired_ref": "roster_snapshot",
                "acquired_method": "IMPORT_UNKNOWN",
                "disposed_at_ms": None,
                "disposed_ref": None,
                "disposed_method": None,
                "basis_value": None,
                "basis_fidelity": None,
                "basis_missing_reason": BASIS_REASON_NO_EVENT,
                "order_fidelity": order_fidelity,
            }
            open_by_asset[asset_id] = holding
            out.append(holding)

    out.sort(
        key=lambda h: (
            h["asset_id"],
            h["owner_rid"],
            h["sequence_num"],
        )
    )
    return out


def derive_pick_lineage(league_key: str, events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The ordered chain of hands each league pick has passed through.

    Keyed on ``LeaguePickIdentity.canonical_id``, which by construction
    survives both ownership transfer and slot realization — owner and
    slot are STATE, not identity (C1-U3).  That is why a pick traded
    A→B→C and then drafted is ONE chain of two hops rather than several
    unrelated assets, and why no acquisition-local pick id is minted.

    Sleeper's ``/traded_picks`` cannot express this: it reports only
    CURRENT ownership, so N appearances across N season snapshots is not
    N trades.  A chain needs the transaction feed, which is what this
    reads.
    """
    hops_by_pick: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        if str(ev.get("asset_kind") or "") != ASSET_PICK:
            continue
        to_rid = ev.get("after_owner_rid")
        if to_rid is None:
            continue
        pick_id = str(ev.get("asset_id") or "")
        if not pick_id:
            continue
        hops_by_pick.setdefault(pick_id, []).append(
            {
                "league_key": league_key,
                "pick_id": pick_id,
                "hop_num": 0,  # assigned below, after the full chain is known
                "from_rid": ev.get("before_owner_rid"),
                "to_rid": int(to_rid),
                "source_ref": ev.get("source_ref"),
                "occurred_at_ms": ev.get("occurred_at_ms"),
            }
        )

    out: list[dict[str, Any]] = []
    for pick_id in sorted(hops_by_pick):
        for i, hop in enumerate(hops_by_pick[pick_id], start=1):
            hop["hop_num"] = i
            out.append(hop)
    return out
