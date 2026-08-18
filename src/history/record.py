"""Live recording — canonical contract → temporal-ledger observations.

Called on FRESH-SCRAPE promotions only, beside the existing
``rank_history`` / ``source_history`` appends in ``server.py``.  It
never runs on startup priming or override builds, so a restart cannot
fabricate a new observation day — the same discipline the rank-history
append already keeps.

What one contract build contributes:

* one ``canonical_board`` observation per keyable row — value
  (``rankDerivedValue``), rank (``canonicalConsensusRank`` — nullable:
  tethered slot picks carry a value and no rank, and recording them
  anyway is exactly the C1-HIST-02 repair), tier, confidence, pipeline
  version (``board_store.pipeline_version`` — the shape version + Hill
  content hash, so two boards for one date under different constants
  are two different claims);
* one ``source_value`` observation per value-direct retail number on
  the row (``ktcSfTep`` / ``idpTradeCalc`` — the ``_VALUE_BASED_SOURCES``
  restriction ``board_store._retail`` documents; rank-signal synthetic
  encodings never enter this lane).

Rows the key layer cannot resolve, and rows asserting neither a value
nor a rank, are counted in the returned summary — never silently
dropped, never guessed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.history import keys, store
from src.history.provenance import pipeline_version

ORIGIN_LIVE = "live:server"

# The value-direct retail sources allowed into the source_value lane
# from a CONTRACT row.  Same restriction (and same reason) as
# ``board_store._retail``: ``canonicalSiteValues`` mixes genuine vendor
# numbers with synthetic rank encodings, and a synthetic encoding
# recorded as a market observation would poison every future
# measurement scored against it.
_CONTRACT_RETAIL_KEYS = ("ktcSfTep", "idpTradeCalc")


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _retail(row: dict[str, Any], key: str) -> float | None:
    """Mirror of ``board_store._retail`` — see that docstring."""
    for block_name in ("rawSourceValues", "canonicalSiteValues", "sourceValues"):
        block = row.get(block_name)
        if isinstance(block, dict) and key in block:
            got = _num(block.get(key))
            if got is not None:
                return got
    return _num(row.get(key))


def _players_array(contract: dict[str, Any]) -> list[dict[str, Any]]:
    arr = contract.get("playersArray")
    if not isinstance(arr, list):
        data = contract.get("data") or {}
        arr = data.get("playersArray") if isinstance(data, dict) else None
    return arr if isinstance(arr, list) else []


def contract_board_date(contract: dict[str, Any]) -> str:
    """The producer's own UTC date claim for the board.

    Prefers the payload's ``date`` stamp (what every existing history
    store keys on); falls back to today-UTC only when the payload
    carries none.
    """
    d = contract.get("date")
    if isinstance(d, str) and len(d) == 10:
        return d
    return datetime.now(timezone.utc).date().isoformat()


def observations_from_contract(
    contract: dict[str, Any],
    *,
    origin: str = ORIGIN_LIVE,
    observed_date: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build ledger observations for one canonical contract.

    Returns ``(observations, summary)`` — the summary counts rows the
    key layer could not resolve (``unresolved``) and rows carrying
    nothing to record (``empty``).
    """
    rows = _players_array(contract)
    date_s = observed_date or contract_board_date(contract)
    observed_at = str(contract.get("scrapeTimestamp") or "") or None
    # ``scrapeTimestamp`` is tz-aware UTC as of audit F-28, so live rows
    # record ``zone="utc"`` on the producer's own statement rather than on
    # an assumption about the host.
    #
    # The naive branch survives for LEGACY payloads (committed archives, a
    # board left on disk by an older scraper), and for those the stamp's
    # zone is genuinely unrecorded — which is why it is stamped "naive"
    # here instead of being silently normalized to UTC.  The distinction is
    # load-bearing: rows written before F-28 by the production VPS are two
    # hours ahead of the instant they claim, and the zone column is what
    # makes that recoverable rather than invisible.  This is an append-only
    # store, so those rows are not rewritten; a correction, if one is ever
    # authorized, is an explicit correction row.
    zone = None
    if observed_at:
        zone = "utc" if ("+" in observed_at or observed_at.endswith("Z")) else "naive"
    pv = pipeline_version(contract)
    scope = None
    meta = contract.get("meta")
    if isinstance(meta, dict):
        scope = meta.get("scoringFingerprint") or None

    out: list[dict[str, Any]] = []
    unresolved = 0
    empty = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        keyed = keys.asset_key_for_contract_row(row)
        if keyed is None:
            unresolved += 1
            continue
        asset_key, asset_class = keyed
        base = {
            "asset_key": asset_key,
            "asset_class": asset_class,
            "observed_date": date_s,
            "observed_at": observed_at,
            "observed_at_zone": zone,
            "display_name": str(row.get("displayName") or row.get("canonicalName") or "") or None,
            "position": str(row.get("position") or "") or None,
            "player_id": str(row.get("playerId") or "") or None,
            "scope": scope,
            "origin": origin,
        }

        value = _num(row.get("rankDerivedValue"))
        rank = row.get("canonicalConsensusRank")
        rank = int(rank) if isinstance(rank, int) and rank > 0 else None
        if value is None and rank is None:
            empty += 1
        else:
            tier = row.get("canonicalTierId")
            out.append(
                {
                    **base,
                    "lane": store.LANE_CANONICAL,
                    "source_key": "",
                    "value": value,
                    "rank": rank,
                    "tier": int(tier) if isinstance(tier, int) else None,
                    "confidence": str(row.get("confidenceBucket") or "") or None,
                    "pipeline_version": pv,
                }
            )

        for skey in _CONTRACT_RETAIL_KEYS:
            got = _retail(row, skey)
            if got is not None:
                out.append(
                    {
                        **base,
                        "lane": store.LANE_SOURCE,
                        "source_key": skey,
                        "value": got,
                        "rank": None,
                        "tier": None,
                        "confidence": None,
                        "pipeline_version": None,
                    }
                )

    summary = {
        "boardDate": date_s,
        "rows": len(rows),
        "observations": len(out),
        "unresolved": unresolved,
        "empty": empty,
        "pipelineVersion": pv,
    }
    return out, summary


def record_contract(
    contract: dict[str, Any],
    *,
    path: Path | None = None,
    origin: str = ORIGIN_LIVE,
    observed_date: str | None = None,
) -> dict[str, Any]:
    """Record one canonical contract build into the temporal ledger.

    Idempotent: re-recording the same build is a counted no-op.  A
    conflicting re-record (same identity, different content — e.g. two
    same-day scrapes) is NOT possible by construction because the
    scrape instant is part of the observation identity; two scrapes on
    one date are two observations, and the as-of tie rule picks
    deterministically.
    """
    observations, summary = observations_from_contract(
        contract, origin=origin, observed_date=observed_date
    )
    result = store.write_observations(observations, path=path)
    result.update(summary)
    return result
