"""Page serving projections of the canonical board; no ranking calculations.

Rankings and trade share the same universe and canonical row representation.
Opaque source audit records load with a selected player. Keep
the field census pinned against the frontend materializer and its consumers.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.api.compact_view import compact_player

SCHEMA_VERSION = 1
MODEL_VERSION = "prepared-board-v1"
BOARD_FIELDS = frozenset(
    {
        "playerId",
        "_sleeperId",
        "displayName",
        "canonicalName",
        "position",
        "team",
        "age",
        "rookie",
        "assetClass",
        "values",
        "rankDerivedValue",
        "canonicalSiteValues",
        "rawSourceValues",
        "canonicalConsensusRank",
        "canonicalTierId",
        "rankChange",
        "marketBreadthAgreementIndex",
        "marketConfidence",
        "marketCorridorClamp",
        "twoWayPlayerBoost",
        "sourceRanks",
        "effectiveSourceRanks",
        "droppedSources",
        "sourceRankMeta",
        "blendedSourceRank",
        "sourceCount",
        "sourceSpread",
        "madPenaltyApplied",
        "anchorValue",
        "subgroupBlendValue",
        "subgroupDelta",
        "alphaShrinkage",
        "softFallbackCount",
        "sourceRankPercentileSpread",
        "confidenceBucket",
        "confidenceLabel",
        "anomalyFlags",
        "isSingleSource",
        "hasSourceDisagreement",
        "sourceRankSpread",
        "marketGapDirection",
        "marketGapValueRatio",
        "marketGapMagnitude",
        "sourceOriginalRanks",
        "sourceNativeValues",
        "yearsExp",
        "_yearsExp",
        "identityResolutionConfidence",
        "identityConfidence",
        "identityMethod",
        "quarantined",
        "rankHistory",
        "pickGenericSuppressed",
    }
)
DEFERRED_FIELDS = frozenset({"sourceAudit", "pickDetails", "hillValueSpread", "marketDispersionCV"})
ENVELOPE_FIELDS = frozenset(
    {
        "contractVersion",
        "date",
        "playerCount",
        "meta",
        "dataFreshness",
        "rankingsOverride",
        "valuationBasis",
        "valueAuthority",
        "pickAliases",
        "currentDraftYear",
        "hillCurves",
        "methodology",
        "sleeper",
        "scrapeTimestamp",
        "dataSource",
        "warnings",
        "sites",
        "valuationOverlay",
    }
)
CATALOG_FIELDS = frozenset(
    {
        "playerId",
        "displayName",
        "canonicalName",
        "position",
        "team",
        "assetClass",
        "canonicalConsensusRank",
        "rankDerivedValue",
        "values",
    }
)


class ReadModelEnvelope(BaseModel):
    """Validate the shared versioned boundary without coercing canonical values."""

    model_config = ConfigDict(extra="allow", strict=True)
    schemaVersion: Literal[1]
    payloadView: Literal["rankings", "trade", "catalog"]
    playersArray: list[dict]
    meta: dict


def asset_key(row: dict) -> str:
    ident = str(row.get("playerId") or row.get("_sleeperId") or "").strip()
    identity = (
        ["player", ident]
        if ident
        else [
            "asset",
            str(row.get("displayName") or row.get("canonicalName") or ""),
            str(row.get("position") or ""),
        ]
    )
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()


def project_board(contract: dict, generation: str, *, view: str = "rankings") -> dict:
    if view not in {"rankings", "trade", "catalog"}:
        raise ValueError("unsupported read model")
    fields = CATALOG_FIELDS if view == "catalog" else BOARD_FIELDS
    rows = []
    seen = set()
    for row in contract.get("playersArray") or []:
        key = asset_key(row)
        if key in seen:
            raise ValueError("duplicate canonical asset identity")
        seen.add(key)
        # Reuse the already consumer-verified compact metadata policy. All
        # visible source contributions/weights/methods survive; full source
        # audit metadata is retrieved with a selected player.
        projected = compact_player(row) if view != "catalog" else row
        rows.append({**{k: v for k, v in projected.items() if k in fields}, "readModelKey": key})
    payload = {k: v for k, v in contract.items() if k in ENVELOPE_FIELDS}
    if view == "catalog":
        payload = {
            "date": contract.get("date"),
            "playerCount": len(rows),
            "sleeper": contract.get("sleeper"),
            "sites": contract.get("sites"),
        }
    payload.update(
        {
            "schemaVersion": SCHEMA_VERSION,
            "payloadView": view,
            "playersArray": rows,
            "meta": {
                **(contract.get("meta") or {}),
                "readModelGeneration": generation,
                "deferredPlayerFields": sorted(DEFERRED_FIELDS),
            },
        }
    )
    ReadModelEnvelope.model_validate(payload)
    return payload


def player_index(contract: dict) -> dict[str, dict]:
    """Built once per generation, including picks and unresolved name-only assets."""
    result = {}
    for row in contract.get("playersArray") or []:
        key = asset_key(row)
        if key in result:
            raise ValueError("duplicate canonical asset identity")
        result[key] = row
    return result
