"""Per-source RANK capture — the #804 longitudinal observation lane.

CAPTURE ONLY.  Nothing here scores, weights, downweights, groups sources
into families, or touches a published number.  Correlation methodology
and any use of the series are POST-V1 and unauthorized; this unit exists
so that when they are authorized there is something to analyse, because
the evidence is otherwise destroyed on every scrape.

WHY THIS LANE EXISTS
────────────────────
#804 is about **correlated / shared-lineage source movement**: injected
correlated anomalies moved the blend by as much as ~48% without existing
defenses catching them, because sources agreeing on something wrong is
indistinguishable from agreement at the point of the blend.

Deciding whether two sources are genuinely independent needs their
observations OVER TIME — a correlation that holds every day is structural
dependence; one that appears on a single board is noise.  The platform
publishes 22-24 per-source rank maps on every build and retains none of
them: measured 2026-08-18, 24 source boards exist live and exactly 3 are
preserved in any archive, across 0 of 176 bundles.  Every build that goes
unrecorded is a day of evidence no later effort can reconstruct.

WHY A NEW LANE AND NOT ``source_value``
───────────────────────────────────────
A rank is an ordering POSITION; a value is a PRICE.  They are not
convertible, they do not share units, and a query that had to guess which
one a row carried would be unable to answer either question.  The two
also disagree about what "missing" means: a source can rank an asset it
publishes no value for, and vice versa.

WHAT ONE BUILD CONTRIBUTES
──────────────────────────
One observation per (asset, source) that the board says the source ranked:

* ``rank``                     the EFFECTIVE rank — the comparable
                               coordinate a later correlation is computed on;
* ``raw_rank``                 what the source actually PUBLISHED, before
                               ladder translation (a rookie board's #36
                               becomes #247 on the overall ladder — the
                               two are different facts and both matter);
* ``rank_method`` / ``rank_pool`` / ``shared_market_translated``
                               the lineage.  ``shared_market_translated``
                               is the single most important field here: a
                               source projected onto another market's
                               backbone is correlated with that market BY
                               CONSTRUCTION, and an independence analysis
                               that missed it would "discover" a
                               correlation the pipeline itself created.

MISSING IS ABSENCE, NEVER ZERO
──────────────────────────────
A source that did not rank an asset contributes NO ROW.  It does not
contribute rank 0, rank null, or a sentinel — the store refuses all three
(``store._validate_source_rank``).  Absence is the only encoding a later
pass can read correctly, because rank 0 would sort first on every board.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.history import keys, record, store
from src.history.provenance import pipeline_version

ORIGIN_LIVE = "live:server"


def _effective_rank(value: Any) -> int | None:
    """A published ordering position, or ``None``.

    Bools are excluded explicitly (``True`` is an ``int`` in Python and
    would otherwise store as rank 1), and anything below 1 is refused
    here as well as at the store — a rank of 0 is not a position.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    as_int = int(value)
    return as_int if as_int >= 1 else None


def _raw_rank(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value > 0 else None


def observations_from_contract(
    contract: dict[str, Any],
    *,
    origin: str = ORIGIN_LIVE,
    observed_date: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build ``source_rank`` observations for one canonical contract.

    Returns ``(observations, summary)``.  The summary counts rows the key
    layer could not resolve and rows that carried no per-source rank map
    at all — never silently dropped, never guessed.
    """
    rows = record._players_array(contract)
    date_s = observed_date or record.contract_board_date(contract)
    observed_at, zone = record.contract_observed_instant(contract)
    pv = pipeline_version(contract)

    scope_default = None
    meta_block = contract.get("meta")
    if isinstance(meta_block, dict):
        scope_default = meta_block.get("scoringFingerprint") or None

    out: list[dict[str, Any]] = []
    unresolved = 0
    without_ranks = 0
    sources_seen: set[str] = set()

    for row in rows:
        if not isinstance(row, dict):
            continue
        ranks = row.get("sourceRanks")
        if not isinstance(ranks, dict) or not ranks:
            without_ranks += 1
            continue
        keyed = keys.asset_key_for_contract_row(row)
        if keyed is None:
            unresolved += 1
            continue
        asset_key, asset_class = keyed

        raw_ranks = row.get("sourceOriginalRanks")
        raw_ranks = raw_ranks if isinstance(raw_ranks, dict) else {}
        rank_meta = row.get("sourceRankMeta")
        rank_meta = rank_meta if isinstance(rank_meta, dict) else {}

        base = {
            "asset_key": asset_key,
            "asset_class": asset_class,
            "observed_date": date_s,
            "observed_at": observed_at,
            "observed_at_zone": zone,
            "display_name": str(row.get("displayName") or row.get("canonicalName") or "") or None,
            "position": str(row.get("position") or "") or None,
            "player_id": str(row.get("playerId") or "") or None,
            "pipeline_version": pv,
            "origin": origin,
        }

        for source_key, published in ranks.items():
            skey = str(source_key or "").strip()
            if not skey:
                continue
            effective = _effective_rank(published)
            if effective is None:
                # The source did not rank this asset on this board.  No row:
                # absence is the honest encoding, and rank 0 would sort first.
                continue
            meta = rank_meta.get(skey)
            meta = meta if isinstance(meta, dict) else {}
            translated = meta.get("sharedMarketTranslated")
            out.append(
                {
                    **base,
                    "lane": store.LANE_SOURCE_RANK,
                    "source_key": skey,
                    "value": None,
                    "rank": effective,
                    "tier": None,
                    "confidence": None,
                    "scope": str(meta.get("scope") or "") or scope_default,
                    "raw_rank": _raw_rank(raw_ranks.get(skey)),
                    "rank_method": str(meta.get("method") or "") or None,
                    "rank_pool": str(meta.get("rankCoordinatePool") or "") or None,
                    "shared_market_translated": (
                        None if translated is None else int(bool(translated))
                    ),
                }
            )
            sources_seen.add(skey)

    summary = {
        "boardDate": date_s,
        "rows": len(rows),
        "rankObservations": len(out),
        "distinctSources": len(sources_seen),
        "unresolved": unresolved,
        "rowsWithoutRanks": without_ranks,
        "pipelineVersion": pv,
    }
    return out, summary


def record_source_ranks(
    contract: dict[str, Any],
    *,
    path: Path | None = None,
    origin: str = ORIGIN_LIVE,
    observed_date: str | None = None,
) -> dict[str, Any]:
    """Record one build's per-source ranks into the canonical ledger.

    Append-only and idempotent, inherited wholesale from
    ``store.write_observations``: re-recording the same build is a counted
    no-op because the scrape instant is part of the observation identity.
    """
    observations, summary = observations_from_contract(
        contract, origin=origin, observed_date=observed_date
    )
    result = store.write_observations(observations, path=path)
    result.update(summary)
    return result
