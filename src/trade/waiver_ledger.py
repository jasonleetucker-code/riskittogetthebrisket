"""Per-league waiver event history — the C4-WAIV-01 canonical owner.

WHY THIS IS NOT A SECOND COLLECTOR
───────────────────────────────────
Two things already touch "waivers" in this repo, and neither is what this
module is:

* ``src.api.sleeper_overlay._build_waivers_block`` is a LIVE, on-demand
  fetch for the ``/api/data`` overlay: a rolling 365-day window, re-fetched
  from Sleeper on every cache miss, keyed to display NAMES rather than
  canonical asset ids, and never persisted. It answers "what happened
  recently, for one panel" and cannot answer "what happened ever."
* ``src.trade.faab_history`` fetches the same Sleeper transaction feed
  directly and persists a narrower derived summary — bid AMOUNTS and the
  zero-bid share — for the FAAB market model's rival-bid distribution.
  It predates the acquisition ledger and answers a market-calibration
  question, not an asset-history one.

This module answers a third, different question — "what did this league's
whole waiver-wire history actually look like, claim by claim, forever" —
and it answers it the way C1-ACQ-01's "one owner" rule requires: by
projecting the canonical ``acquisition_events`` ledger (``src.acquisition``),
never by fetching Sleeper again. If a claim is missing here, the repair is
upstream in ``src.acquisition.events``, not a second ingestion path.

GROUPING RULE
─────────────
Sleeper reports one transaction per waiver/free-agent claim, and a claim
can add more than one player and/or drop one to make room. Those stay
grouped under the transaction's own ``source_ref`` (the acquisition
ledger's natural per-transaction key) rather than flattened into
independent rows, so "what did this claim cost, and what did it require
giving up" stays answerable from one row. A transaction with no ADD side
(a bare drop) is not a claim and is excluded — the acquisition ledger
still records it, just not here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.acquisition.store import read_events
from src.trade.ledger_sort import oldest_first_key

WAIVER = "WAIVER"
FREE_AGENT = "FREE_AGENT"
_DROP = "DROP"
_CLAIM_ADD_TYPES = (WAIVER, FREE_AGENT)


def _asset_ref(ev: dict[str, Any]) -> dict[str, Any]:
    return {"assetId": ev["asset_id"], "assetKind": ev["asset_kind"]}


def waiver_claims(league_key: str, *, path: Path | None = None) -> list[dict[str, Any]]:
    """One row per completed waiver/free-agent transaction, oldest first.

    Undated claims sort first (mirroring ``acquisition.store.read_events``'s
    own convention), since they cannot be ordered against dated ones and
    treating them as the conservative earliest baseline is what that owner
    already does.
    """
    events = read_events(league_key, path=path)
    groups: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        groups.setdefault(ev["source_ref"], []).append(ev)

    claims: list[dict[str, Any]] = []
    for source_ref, group in groups.items():
        added = [e for e in group if e["event_type"] in _CLAIM_ADD_TYPES]
        if not added:
            continue
        dropped = [e for e in group if e["event_type"] == _DROP]
        primary = added[0]
        faab_bid = next((e["faab_bid"] for e in added if e["faab_bid"] is not None), None)
        claims.append(
            {
                "leagueKey": league_key,
                "sourceRef": source_ref,
                "transactionType": primary["event_type"],
                "season": primary["season"],
                "week": primary["week"],
                "occurredAtMs": primary["occurred_at_ms"],
                "timeFidelity": primary["time_fidelity"],
                "rosterRid": primary["after_owner_rid"],
                "ownerUserId": primary["after_owner_user_id"],
                "added": [_asset_ref(e) for e in added],
                "dropped": [_asset_ref(e) for e in dropped],
                "faabBid": faab_bid,
            }
        )

    claims.sort(key=lambda c: oldest_first_key(c["occurredAtMs"], c["sourceRef"]))
    return claims


def waiver_ledger_summary(league_key: str, *, path: Path | None = None) -> dict[str, Any]:
    """Counts and stamps only — never per-claim contents.

    Mirrors ``src.acquisition.store.coverage``'s posture: a health/stats
    surface that echoed private roster-move contents would move the
    ledger's privacy boundary every time someone checked it was alive.
    """
    claims = waiver_claims(league_key, path=path)
    waiver_only = [c for c in claims if c["transactionType"] == WAIVER]
    priced = [c for c in waiver_only if c["faabBid"] is not None]
    zero_bid = [c for c in priced if c["faabBid"] == 0]
    dated_ms = [c["occurredAtMs"] for c in claims if c["occurredAtMs"] is not None]

    return {
        "leagueKey": league_key,
        "totalClaims": len(claims),
        "waiverClaims": len(waiver_only),
        "freeAgentClaims": len(claims) - len(waiver_only),
        "waiverClaimsWithBid": len(priced),
        "waiverClaimsMissingBid": len(waiver_only) - len(priced),
        "zeroBidClaims": len(zero_bid),
        "faabSpent": sum(c["faabBid"] for c in priced),
        "undatedClaims": len(claims) - len(dated_ms),
        "oldestOccurredAtMs": min(dated_ms) if dated_ms else None,
        "newestOccurredAtMs": max(dated_ms) if dated_ms else None,
    }
