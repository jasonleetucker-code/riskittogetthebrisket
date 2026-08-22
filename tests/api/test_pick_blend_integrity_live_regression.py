from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.api.data_contract import build_api_data_contract


def _latest_payload() -> dict:
    candidates = sorted(Path("exports/latest").glob("dynasty_data_*.json"))
    assert candidates, "tracked latest dynasty payload is required for the blend-integrity regression"
    with candidates[-1].open("r", encoding="utf-8") as handle:
        return json.load(handle)


def test_2027_late_first_does_not_false_trip_blend_integrity() -> None:
    """Reproduce the production deploy blocker with enough stage evidence to diagnose it."""
    contract = build_api_data_contract(
        _latest_payload(),
        data_source={"type": "test_file", "path": "exports/latest"},
    )
    rows = list(contract.get("playersArray") or [])
    row = next(
        (
            candidate
            for candidate in rows
            if candidate.get("canonicalName") == "2027 Late 1st"
            or candidate.get("displayName") == "2027 Late 1st"
        ),
        None,
    )
    assert row is not None, "2027 Late 1st disappeared from the canonical contract"

    violation = row.get("blendIntegrityViolation")
    if violation:
        meta = row.get("sourceRankMeta") or {}
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
            "sourceRankMeta": {
                key: {
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
                for key, value in meta.items()
                if isinstance(value, dict)
            },
            "violation": violation,
        }
        pytest.fail(json.dumps(diagnostic, sort_keys=True, default=str))
