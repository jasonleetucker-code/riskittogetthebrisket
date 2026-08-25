from __future__ import annotations

import json
from pathlib import Path

from src.api.data_contract import build_api_data_contract


def _latest_payload() -> dict:
    candidates = sorted(Path("exports/latest").glob("dynasty_data_*.json"))
    if not candidates:
        raise AssertionError("tracked latest dynasty payload is required")
    with candidates[-1].open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _late_first_row(contract: dict) -> dict:
    for row in contract.get("playersArray") or []:
        if row.get("canonicalName") == "2027 Late 1st":
            return row
    raise AssertionError("2027 Late 1st disappeared from the canonical contract")


def test_2027_late_first_does_not_false_trip_blend_integrity() -> None:
    contract = build_api_data_contract(
        _latest_payload(),
        data_source={"type": "test_file", "path": "exports/latest"},
    )
    row = _late_first_row(contract)
    violation = row.get("blendIntegrityViolation")
    if violation is None:
        return

    source_meta = {}
    for key, value in (row.get("sourceRankMeta") or {}).items():
        if not isinstance(value, dict):
            continue
        source_meta[key] = {
            "valueContribution": value.get("valueContribution"),
            "contributedToBlend": value.get("contributedToBlend"),
            "hampelDropped": value.get("hampelDropped"),
            "supersededBy": value.get("supersededBy"),
            "valueContributionPath": value.get("valueContributionPath"),
            "rawRank": value.get("rawRank"),
            "effectiveRank": value.get("effectiveRank"),
            "rankCoordinatePool": value.get("rankCoordinatePool"),
            "method": value.get("method"),
        }

    diagnostic = {
        "rankDerivedValue": row.get("rankDerivedValue"),
        "canonicalConsensusRank": row.get("canonicalConsensusRank"),
        "anchorValue": row.get("anchorValue"),
        "subgroupBlendValue": row.get("subgroupBlendValue"),
        "subgroupDelta": row.get("subgroupDelta"),
        "alphaShrinkage": row.get("alphaShrinkage"),
        "pickYearDiscount": row.get("pickYearDiscount"),
        "pickValueProvenance": row.get("pickValueProvenance"),
        "canonicalSiteValues": row.get("canonicalSiteValues"),
        "sourceRanks": row.get("sourceRanks"),
        "sourceRankMeta": source_meta,
        "violation": violation,
    }
    raise AssertionError(json.dumps(diagnostic, sort_keys=True, default=str))
