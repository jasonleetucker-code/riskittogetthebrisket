"""Rookie-source coverage — how many sources actually priced each rookie.

Owner directive 2026-11-21 (DYN10, top-10 item 8, "rookie source coverage and
freshness").  ``/draft`` shows rookie values with no signal of how well
supported each one is: a rookie priced by KTC alone looked as sound as one
priced by six, and a vendor-empty rookie board (the DLF rookie boards,
2026-11-19..21) was invisible.

This module DECIDES NOTHING about value.  It reads facts the canonical
contract already stamped and republishes them additively:

* per rookie — the row's own ``sourceRankMeta`` (the blend's per-observation
  record), counted with ``voting_status.meta_voted``, the same definition the
  per-source tallies use;
* pool level — the contract's ``sourceVotingStatus`` entries (voting, held,
  seasonal, stale, data issue), restricted to the rookie-relevant sources.

MISSING IS NEVER ZERO.  A row with no ``sourceRankMeta`` has an UNKNOWN count
(``None`` + reason), never ``0``; a contract with no ``sourceVotingStatus``
yields an ``unavailable`` pool block with null counts.

The count is of voting SOURCE KEYS, not independent families (KTC Crowd and
KTC Trades are two keys of one provider); it describes how many boards priced
the rookie, not how independent they are.  Confidence owns independence.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.draft.rookie_pool import select_rookie_rows
from src.sources.voting_status import (
    ACTIVE_STATUSES,
    COVERAGE_ROOKIE,
    STATUS_SEASONAL,
    STATUS_STALE,
    STATUS_TESTING,
    meta_voted,
)

__all__ = [
    "LOW_COVERAGE_BELOW",
    "STATE_LOW",
    "STATE_OK",
    "STATE_UNKNOWN",
    "VERSION",
    "build_pool_coverage",
    "row_coverage",
]

VERSION = "rookie-source-coverage/v1"

#: Fewer voting sources than this marks a rookie LOW coverage.  Not a new
#: methodology number: three is the blend's own untrimmed-median rung
#: (``_mean_median_blend``: 1 passthrough, 2 plain mean, 3-4 untrimmed
#: mean-median, 5+ trimmed), so below it the published value is a passthrough
#: or a two-source mean.  Display marker only; it moves no value.
LOW_COVERAGE_BELOW = 3

STATE_OK = "ok"
STATE_LOW = "low"
STATE_UNKNOWN = "unknown"

# Pool-level per-source states.
SOURCE_VOTING = "voting"
SOURCE_HELD = "held"
SOURCE_SEASONAL = "seasonal"
SOURCE_STALE = "stale"
SOURCE_MISSING = "missing"


def row_coverage(row: Mapping[str, Any]) -> dict[str, Any]:
    """The additive per-rookie coverage stamp for one contract row."""
    meta = row.get("sourceRankMeta") if isinstance(row, Mapping) else None
    if not isinstance(meta, Mapping) or not meta:
        return {
            "votingSourceCount": None,
            "votingSources": None,
            "state": STATE_UNKNOWN,
            "reason": "source_meta_unavailable",
        }
    voting = sorted(str(k) for k, m in meta.items() if isinstance(m, Mapping) and meta_voted(m))
    count = len(voting)
    return {
        "votingSourceCount": count,
        "votingSources": voting,
        "state": STATE_LOW if count < LOW_COVERAGE_BELOW else STATE_OK,
        "reason": None,
    }


def _source_state(entry: Mapping[str, Any], pool_rows: int) -> str:
    status = str(entry.get("status") or "")
    if status == STATUS_SEASONAL:
        return SOURCE_SEASONAL
    if status == STATUS_TESTING:
        return SOURCE_HELD
    if status == STATUS_STALE:
        return SOURCE_STALE
    if status in ACTIVE_STATUSES and pool_rows > 0:
        return SOURCE_VOTING
    # data_issue, unknown status, or "active" yet it priced no rookie in this pool: nothing
    # usable reached the board (vendor-empty / unmatched / not provisioned).
    return SOURCE_MISSING


def _unavailable(reason: str, pool_size: int) -> dict[str, Any]:
    return {
        "version": VERSION,
        "state": "unavailable",
        "reason": reason,
        "poolSize": pool_size,
        "lowCoverageBelow": LOW_COVERAGE_BELOW,
        "votingCount": None,
        "relevantCount": None,
        "lowCoverageRows": None,
        "unknownRows": None,
        "sources": [],
    }


def build_pool_coverage(contract: Mapping[str, Any] | None, top_n: int = 72) -> dict[str, Any]:
    """The pool-level block: which rookie-relevant sources vote / are held /
    seasonal / stale / missing, over the same rows ``_our_rookie_pool`` ranks.

    Rookie-relevant = a registered rookie board (``coverage == "rookie"``) or
    any source that voted on at least one pool rookie.
    """
    rows = select_rookie_rows(contract, top_n)
    pool_size = len(rows)
    if not isinstance(contract, Mapping):
        return _unavailable("contract_unavailable", pool_size)
    status_block = contract.get("sourceVotingStatus")
    entries = status_block.get("sources") if isinstance(status_block, Mapping) else None
    if not isinstance(entries, list) or not entries:
        return _unavailable("source_voting_status_unavailable", pool_size)
    if pool_size == 0:
        # An empty / unmatched pool says nothing about vendors; do not let every
        # board read "missing".
        return _unavailable("empty_pool", pool_size)

    per_row = [row_coverage(r) for r in rows]
    rows_pricing: dict[str, int] = {}
    for cov in per_row:
        for key in cov["votingSources"] or ():
            rows_pricing[key] = rows_pricing.get(key, 0) + 1

    sources: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        key = str(entry.get("key") or "")
        if not key:
            continue
        priced = rows_pricing.get(key, 0)
        if entry.get("coverage") != COVERAGE_ROOKIE and priced == 0:
            continue
        sources.append(
            {
                "key": key,
                "displayName": entry.get("displayName") or key,
                "state": _source_state(entry, priced),
                "statusLabel": entry.get("statusLabel"),
                "reason": entry.get("reason"),
                "rookiesPriced": priced,
                "rookieBoard": entry.get("coverage") == COVERAGE_ROOKIE,
            }
        )

    return {
        "version": VERSION,
        "state": "available",
        "reason": None,
        "poolSize": pool_size,
        "lowCoverageBelow": LOW_COVERAGE_BELOW,
        "votingCount": sum(1 for s in sources if s["state"] == SOURCE_VOTING),
        "relevantCount": len(sources),
        "lowCoverageRows": sum(1 for c in per_row if c["state"] == STATE_LOW),
        "unknownRows": sum(1 for c in per_row if c["state"] == STATE_UNKNOWN),
        "sources": sources,
    }
