"""Raw Sleeper transactions and draft picks → acquisition events.

ONE ROW PER (TRANSACTION, ASSET) MOVEMENT
─────────────────────────────────────────
An asset moves at most once inside one Sleeper transaction, so
``(league_key, source_ref, asset_id)`` is a natural key rather than a
synthesised one.  That matters for the shape it preserves: a three-team
trade produces one row per asset while remaining ONE transaction, so the
multi-party structure survives instead of being flattened into fictional
two-party trades.

WHAT IS DELIBERATELY NOT COERCED
────────────────────────────────
* an **undated** event stays undated (``occurred_at_ms = None``,
  ``time_fidelity = "undated"``) — never epoch zero;
* ``auction_amount is None`` means *not an auction*, which is a
  different statement from a $0 price.  ``src/public_league/draft.py``
  already draws this distinction and says why; the live overlay
  normaliser collapses both to ``0``, so this module reads Sleeper's
  ``metadata.amount`` itself rather than through that path;
* ``faab_bid is None`` means *not a waiver*, not a free claim.  A
  waiver that genuinely cost $0 records ``0``;
* a movement with no explaining event is never back-filled with the
  most likely method — see ``IMPORT_UNKNOWN`` in ``holdings.py``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable

#: How an asset ARRIVED.  Closed set; a method not on this list is a
#: schema change, not a string someone passes in.
ACQUISITION_METHODS = (
    "TRADE",
    "WAIVER",
    "FREE_AGENT",
    "DRAFT",
    "COMMISSIONER",
    "IMPORT_UNKNOWN",
)

#: How an asset LEFT.  ``TRADE_AWAY`` and ``DROP`` are distinct because
#: one has a counterparty and the other does not.
DISPOSAL_METHODS = ("TRADE_AWAY", "DROP", "COMMISSIONER")

ASSET_PLAYER = "player"
ASSET_PICK = "pick"

TIME_EXACT = "exact"
TIME_UNDATED = "undated"

#: Sleeper transaction ``type`` → acquisition method.
_TX_TYPE_TO_METHOD = {
    "trade": "TRADE",
    "waiver": "WAIVER",
    "free_agent": "FREE_AGENT",
    "commissioner": "COMMISSIONER",
}


@dataclass(frozen=True)
class AcquisitionEvent:
    """One asset moving once, inside one transaction."""

    league_key: str
    source_ref: str
    asset_id: str
    asset_kind: str
    event_type: str
    after_owner_rid: int | None
    before_owner_rid: int | None = None
    #: Sleeper USER id of the roster that received the asset.  A roster
    #: id is stable only WITHIN one Sleeper league id, and a registry
    #: league spans several across seasons — so roster id alone cannot
    #: answer "which human", and every cross-season consumer would need
    #: an out-of-band join.  ``None`` when the roster→owner map could not
    #: be resolved: unattributed, never guessed.
    after_owner_user_id: str | None = None
    before_owner_user_id: str | None = None
    sleeper_league_id: str | None = None
    season: str | None = None
    week: int | None = None
    occurred_at_ms: int | None = None
    faab_bid: int | None = None
    auction_amount: int | None = None
    #: Which KIND of draft, when this is a DRAFT event: Sleeper's own
    #: ``type`` (``rookie`` / ``startup`` / ``auction`` / …).  A startup
    #: auction and a rookie draft are different acquisition facts with
    #: different cost-basis semantics, and collapsing them loses that.
    #: ``None`` for non-draft events and for a draft whose type was not
    #: reported.
    draft_kind: str | None = None
    #: The pick slot this event REALIZED, for a pick asset.  Load-bearing
    #: for cost basis: with a slot, ``market_resolution`` distinguishes
    #: the exact-slot grade from the tier grade *using the clock as of
    #: the event*; without one it answers the generic grade and the clock
    #: is not consulted.  ``None`` = slot genuinely unknown, never 0.
    realized_slot: int | None = None
    source: str = "sleeper"
    extra: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def time_fidelity(self) -> str:
        return TIME_EXACT if self.occurred_at_ms is not None else TIME_UNDATED

    def content_hash(self) -> str:
        """Hash of the FACTS, excluding identity and observation time.

        Re-ingesting the same event must be a no-op; re-ingesting the
        same event with *different facts* is a conflict worth surfacing
        rather than silently overwriting.  Observation stamps are
        excluded so that merely re-reading the feed is not a conflict.
        """
        payload = {
            "asset_kind": self.asset_kind,
            "event_type": self.event_type,
            "after_owner_rid": self.after_owner_rid,
            "before_owner_rid": self.before_owner_rid,
            "after_owner_user_id": self.after_owner_user_id,
            "before_owner_user_id": self.before_owner_user_id,
            "sleeper_league_id": self.sleeper_league_id,
            "season": self.season,
            "week": self.week,
            "occurred_at_ms": self.occurred_at_ms,
            "faab_bid": self.faab_bid,
            "auction_amount": self.auction_amount,
            "draft_kind": self.draft_kind,
            "realized_slot": self.realized_slot,
            "source": self.source,
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _int_or_none(v: Any) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _normalise_ms(value: Any) -> int | None:
    """Sleeper stamps are seconds on some endpoints, ms on others.

    Same rule as ``retention.league_events._normalise_ms``; duplicated
    rather than imported because importing it would make this module a
    reader of the retention package's internals, and the boundary
    between "raw recorder" and "derived projection" is the one thing
    this unit must not blur.
    """
    n = _int_or_none(value)
    if n is None or n <= 0:
        return None
    return n * 1000 if n < 10_000_000_000 else n


def _player_asset_id(player_id: Any) -> str | None:
    pid = str(player_id or "").strip()
    return f"player:{pid}" if pid else None


def _pick_asset_id(league_key: str, pick: dict[str, Any]) -> str | None:
    """Canonical league-pick id via the C1-U3 identity owner.

    Never minted locally.  ``origin`` is ``roster_id`` on Sleeper's
    ``draft_picks`` entries — the ORIGINAL owner, which is what makes a
    pick's identity survive every transfer.
    """
    from src.identity.picks import LeaguePickIdentity

    season = _int_or_none(pick.get("season"))
    rnd = _int_or_none(pick.get("round"))
    origin = _int_or_none(pick.get("roster_id"))
    if season is None or rnd is None or origin is None:
        return None
    try:
        return LeaguePickIdentity(
            league_key=league_key, season=season, round_num=rnd, origin_roster_id=origin
        ).canonical_id
    except (ValueError, TypeError):
        return None


def events_from_transaction(
    tx: dict[str, Any],
    *,
    league_key: str,
    sleeper_league_id: str | None = None,
    season: str | None = None,
    owner_by_roster: dict[Any, str] | None = None,
    slot_by_origin: dict[tuple[int, int], int] | None = None,
) -> list[AcquisitionEvent]:
    """Normalise ONE completed Sleeper transaction into asset movements.

    Returns ``[]`` for anything unusable (no transaction id, not
    complete, unrecognised type) rather than guessing — an event we
    cannot key is an event we cannot deduplicate, and a fabricated key
    would defeat the idempotence the ledger exists to provide.

    ``owner_by_roster`` maps ``roster_id -> Sleeper user id`` for THIS
    chain member, so events carry manager identity and not only a roster
    id that means nothing outside one Sleeper league.  ``slot_by_origin``
    maps ``(season, origin_roster_id) -> draft slot`` — the shape
    ``sleeper_overlay._league_draft_slot_lookup`` already returns — so a
    pick whose slot is known records it.  Both are optional and both
    fail to ``None`` rather than to a guess.
    """
    if not isinstance(tx, dict):
        return []
    tx_id = str(tx.get("transaction_id") or "").strip()
    if not tx_id:
        return []
    if str(tx.get("status") or "") != "complete":
        return []
    method = _TX_TYPE_TO_METHOD.get(str(tx.get("type") or ""))
    if method is None:
        return []

    source_ref = f"tx:{tx_id}"
    occurred = _normalise_ms(tx.get("status_updated") or tx.get("created"))
    week = _int_or_none(tx.get("leg"))

    settings = tx.get("settings") if isinstance(tx.get("settings"), dict) else {}
    # ``None`` when this is not a waiver at all; ``0`` when it is a
    # waiver that genuinely cost nothing.
    faab = _int_or_none(settings.get("waiver_bid")) if method == "WAIVER" else None

    adds = tx.get("adds") if isinstance(tx.get("adds"), dict) else {}
    drops = tx.get("drops") if isinstance(tx.get("drops"), dict) else {}
    owners = owner_by_roster or {}
    slots = slot_by_origin or {}

    def _owner(rid: Any) -> str | None:
        """Roster id -> Sleeper user id, or None.  Never a guess."""
        if rid is None:
            return None
        for probe in (rid, _int_or_none(rid), str(rid)):
            if probe is None:
                continue
            found = owners.get(probe)
            if found:
                return str(found)
        return None

    def _mk(**kw: Any) -> AcquisitionEvent:
        return AcquisitionEvent(
            league_key=league_key,
            source_ref=source_ref,
            sleeper_league_id=str(sleeper_league_id) if sleeper_league_id else None,
            season=str(season) if season is not None else None,
            week=week,
            occurred_at_ms=occurred,
            source="sleeper_transactions",
            **kw,
        )

    out: list[AcquisitionEvent] = []
    seen_assets: set[str] = set()

    for pid, rid in adds.items():
        asset_id = _player_asset_id(pid)
        if asset_id is None or asset_id in seen_assets:
            continue
        seen_assets.add(asset_id)
        out.append(
            _mk(
                asset_id=asset_id,
                asset_kind=ASSET_PLAYER,
                event_type=method,
                after_owner_rid=_int_or_none(rid),
                after_owner_user_id=_owner(rid),
                # In a trade the same player also appears in ``drops``
                # under the giving roster; that is the before-owner.
                before_owner_rid=_int_or_none(drops.get(pid)),
                before_owner_user_id=_owner(drops.get(pid)),
                faab_bid=faab,
            )
        )

    for pid, rid in drops.items():
        asset_id = _player_asset_id(pid)
        if asset_id is None or asset_id in seen_assets:
            # Already emitted as the receiving half of this same move.
            continue
        seen_assets.add(asset_id)
        out.append(
            _mk(
                asset_id=asset_id,
                asset_kind=ASSET_PLAYER,
                event_type="TRADE_AWAY" if method == "TRADE" else "DROP",
                after_owner_rid=None,
                after_owner_user_id=None,
                before_owner_rid=_int_or_none(rid),
                before_owner_user_id=_owner(rid),
            )
        )

    for pick in tx.get("draft_picks") or []:
        if not isinstance(pick, dict):
            continue
        asset_id = _pick_asset_id(league_key, pick)
        if asset_id is None or asset_id in seen_assets:
            continue
        seen_assets.add(asset_id)
        pick_season = _int_or_none(pick.get("season"))
        pick_origin = _int_or_none(pick.get("roster_id"))
        realized = (
            slots.get((pick_season, pick_origin))
            if pick_season is not None and pick_origin is not None
            else None
        )
        out.append(
            _mk(
                asset_id=asset_id,
                asset_kind=ASSET_PICK,
                event_type=method,
                after_owner_rid=_int_or_none(pick.get("owner_id")),
                after_owner_user_id=_owner(pick.get("owner_id")),
                before_owner_rid=_int_or_none(pick.get("previous_owner_id")),
                before_owner_user_id=_owner(pick.get("previous_owner_id")),
                realized_slot=_int_or_none(realized),
            )
        )

    return out


def events_from_draft_picks(
    picks: Iterable[dict[str, Any]],
    *,
    league_key: str,
    draft_id: str,
    sleeper_league_id: str | None = None,
    season: str | None = None,
    draft_kind: str | None = None,
    owner_by_roster: dict[Any, str] | None = None,
) -> list[AcquisitionEvent]:
    """Normalise ``/v1/draft/<id>/picks`` into DRAFT acquisitions.

    Draft is an acquisition method, and it is the one asset-origin class
    with NO durable record anywhere: the live overlay path is a
    two-second in-memory cache and the public-league snapshot is a
    different surface.  Once Sleeper ages the draft object out, a
    completed auction's realized prices are unrecoverable.

    ``metadata.amount`` semantics follow
    ``src/public_league/draft.py::_normalize_pick``: an int, or ``None``
    for a snake draft.  ``None`` means *not an auction*, never *free*.

    ``draft_kind`` is Sleeper's own draft ``type`` (``rookie`` /
    ``startup`` / ``auction`` / …).  It is carried rather than dropped
    because a startup auction and a rookie draft are different
    acquisition facts: the first is how a franchise was founded, the
    second is an annual replenishment, and their cost bases are not
    comparable.  ``None`` when the draft object did not report one —
    unlabelled, not assumed to be a rookie draft.
    """
    out: list[AcquisitionEvent] = []
    did = str(draft_id or "").strip()
    if not did:
        return out

    owners = owner_by_roster or {}

    def _owner(rid: Any) -> str | None:
        if rid is None:
            return None
        for probe in (rid, _int_or_none(rid), str(rid)):
            if probe is None:
                continue
            found = owners.get(probe)
            if found:
                return str(found)
        return None

    for pick in picks or []:
        if not isinstance(pick, dict):
            continue
        pick_no = _int_or_none(pick.get("pick_no"))
        asset_id = _player_asset_id(pick.get("player_id"))
        if pick_no is None or asset_id is None:
            continue

        meta = pick.get("metadata") if isinstance(pick.get("metadata"), dict) else {}
        raw_amount = meta.get("amount")
        amount = None
        if raw_amount is not None:
            amount = _int_or_none(str(raw_amount).lstrip("$").strip() or None)

        out.append(
            AcquisitionEvent(
                league_key=league_key,
                # The draft's own identity — not a synthesised
                # transaction id.
                source_ref=f"draft:{did}:{pick_no}",
                asset_id=asset_id,
                asset_kind=ASSET_PLAYER,
                event_type="DRAFT",
                after_owner_rid=_int_or_none(pick.get("roster_id")),
                # Sleeper reports ``picked_by`` as a USER id already, so
                # it is used directly; the roster→owner map is only the
                # fallback for picks that carry a roster but no picker.
                after_owner_user_id=(
                    str(pick.get("picked_by")).strip() or None
                    if pick.get("picked_by")
                    else _owner(pick.get("roster_id"))
                ),
                before_owner_rid=None,
                sleeper_league_id=str(sleeper_league_id) if sleeper_league_id else None,
                season=str(season) if season is not None else None,
                week=None,
                occurred_at_ms=_normalise_ms(pick.get("picked_at")),
                faab_bid=None,
                auction_amount=amount,
                draft_kind=str(draft_kind) if draft_kind else None,
                # The slot this selection consumed.  Sleeper reports it
                # per pick; it is the within-round position, not
                # ``pick_no`` (which is overall).
                realized_slot=_int_or_none(pick.get("draft_slot")),
                source="sleeper_draft_picks",
            )
        )
    return out
