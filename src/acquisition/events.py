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
    sleeper_league_id: str | None = None
    season: str | None = None
    week: int | None = None
    occurred_at_ms: int | None = None
    faab_bid: int | None = None
    auction_amount: int | None = None
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
            "sleeper_league_id": self.sleeper_league_id,
            "season": self.season,
            "week": self.week,
            "occurred_at_ms": self.occurred_at_ms,
            "faab_bid": self.faab_bid,
            "auction_amount": self.auction_amount,
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
) -> list[AcquisitionEvent]:
    """Normalise ONE completed Sleeper transaction into asset movements.

    Returns ``[]`` for anything unusable (no transaction id, not
    complete, unrecognised type) rather than guessing — an event we
    cannot key is an event we cannot deduplicate, and a fabricated key
    would defeat the idempotence the ledger exists to provide.
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
                # In a trade the same player also appears in ``drops``
                # under the giving roster; that is the before-owner.
                before_owner_rid=_int_or_none(drops.get(pid)),
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
                before_owner_rid=_int_or_none(rid),
            )
        )

    for pick in tx.get("draft_picks") or []:
        if not isinstance(pick, dict):
            continue
        asset_id = _pick_asset_id(league_key, pick)
        if asset_id is None or asset_id in seen_assets:
            continue
        seen_assets.add(asset_id)
        out.append(
            _mk(
                asset_id=asset_id,
                asset_kind=ASSET_PICK,
                event_type=method,
                after_owner_rid=_int_or_none(pick.get("owner_id")),
                before_owner_rid=_int_or_none(pick.get("previous_owner_id")),
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
    """
    out: list[AcquisitionEvent] = []
    did = str(draft_id or "").strip()
    if not did:
        return out

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
                before_owner_rid=None,
                sleeper_league_id=str(sleeper_league_id) if sleeper_league_id else None,
                season=str(season) if season is not None else None,
                week=None,
                occurred_at_ms=_normalise_ms(pick.get("picked_at")),
                faab_bid=None,
                auction_amount=amount,
                source="sleeper_draft_picks",
            )
        )
    return out
