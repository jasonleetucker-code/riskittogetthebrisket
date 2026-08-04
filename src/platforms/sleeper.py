"""Thin normalized wrapper around the existing Sleeper crawl outputs.

Sleeper acquisition remains owned by ``src.intel.crawler`` and
``src.sharp.records``. This module translates their already-stable event
shape into the platform contract without creating a competing crawler.
"""

from __future__ import annotations

from typing import Any

from src.platforms.base import (
    IDENTITY_GLOBAL_VERIFIED,
    NormalizedBatch,
    NormalizedLeague,
    NormalizedManager,
    NormalizedMembership,
    NormalizedMovement,
    NormalizedTransaction,
    scoped_key,
)


def normalize_crawler_state(state: dict[str, Any]) -> NormalizedBatch:
    batch = NormalizedBatch(platform="sleeper")
    names = state.get("memberNames") or {}
    for source_id, display_name in names.items():
        batch.managers.append(
            NormalizedManager.build(
                "sleeper",
                str(source_id),
                display_name=str(display_name or "") or None,
                source_identity_type=IDENTITY_GLOBAL_VERIFIED,
                identity_scope="platform",
                identity_confidence=1.0,
            )
        )
    for league_id, raw in (state.get("leagues") or {}).items():
        if not isinstance(raw, dict):
            continue
        league_key = scoped_key("sleeper", str(league_id))
        batch.leagues.append(
            NormalizedLeague.build(
                "sleeper",
                str(league_id),
                season=str(raw.get("season") or "") or None,
                name=str(raw.get("name") or "") or None,
                total_rosters=raw.get("totalRosters"),
                format_type="sleeper",
                metadata={"legacyCrawler": True},
            )
        )
        for source_id in raw.get("memberOwnerIds") or []:
            batch.memberships.append(
                NormalizedMembership(
                    "sleeper",
                    league_key,
                    scoped_key("sleeper", str(source_id)),
                )
            )

    tx_seen: set[str] = set()
    for event in state.get("events") or []:
        if not isinstance(event, dict):
            continue
        source_tx = str(event.get("txId") or "").strip()
        source_mv = str(event.get("eventId") or "").strip()
        league_id = str(event.get("leagueId") or "").strip()
        owner_id = str(event.get("ownerId") or "").strip()
        asset_id = str(event.get("assetId") or "").strip()
        if not all((source_tx, source_mv, league_id, owner_id, asset_id)):
            continue
        transaction_key = scoped_key("sleeper", source_tx)
        league_key = scoped_key("sleeper", league_id)
        ts = int(event.get("ts") or 0)
        if transaction_key not in tx_seen:
            tx_seen.add(transaction_key)
            batch.transactions.append(
                NormalizedTransaction.build(
                    "sleeper",
                    source_tx,
                    league_key=league_key,
                    season=str(event.get("season") or "") or None,
                    week=event.get("week"),
                    transaction_type=str(event.get("txType") or ""),
                    status="complete",
                    created_ms=ts,
                    metadata={"legacyCrawler": True},
                )
            )
        batch.movements.append(
            NormalizedMovement.build(
                "sleeper",
                source_mv,
                transaction_key=transaction_key,
                league_key=league_key,
                canonical_asset_id=asset_id,
                source_asset_id=asset_id,
                source_name=None,
                asset_type=str(event.get("assetType") or "player"),
                action=str(event.get("action") or ""),
                manager_key=scoped_key("sleeper", owner_id),
                roster_id=str(event.get("rosterId") or "") or None,
                counterparty_manager_key=(
                    scoped_key("sleeper", str(event.get("counterpartyUserId")))
                    if event.get("counterpartyUserId")
                    else None
                ),
                timestamp_ms=ts,
                week=event.get("week"),
                faab_bid=event.get("faabBid"),
                metadata={"legacyCrawler": True},
            )
        )
    return batch
