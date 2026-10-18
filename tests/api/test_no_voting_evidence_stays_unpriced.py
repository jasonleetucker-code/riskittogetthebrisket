"""A row whose every observation is withheld stays UNPRICED — never 0.

When freshness / health weighting withholds every source on a row, nothing
votes.  The blend's ``center_value`` is then a literal ``0.0`` placeholder,
and the row used to enter the ranked pool with it: a published rank and
``rankDerivedValue`` 0 for a row with no evidence (found by the IDP Trade
Calculator cutoff simulation on the 2026-10-16 archive — Ashton Gillotte,
whose only voter was IDPTC, landed at rank 800 with value 0).  MISSING IS
NEVER ZERO: such a row is unpriced and unranked exactly like a row nothing
matched, and its withheld observation stays on the record.
"""

from __future__ import annotations

from typing import Any

import pytest

import src.api.data_contract as dc
from src.sources.freshness import SourceWeighting

_WITHHELD = "idpTradeCalc"


def _payload() -> dict[str, Any]:
    players = {
        # Only voter is the withheld source.
        "Lonely Edge": {"position": "DL", "sites": {_WITHHELD: 1500}},
        # Corroborated rows keep ranking normally.
        "Alpha QB": {
            "position": "QB",
            "sites": {"ktcCrowdSfTep": 9000, _WITHHELD: 8800, "dynastyNerdsSfTep": 9100},
        },
        "Beta WR": {
            "position": "WR",
            "sites": {"ktcCrowdSfTep": 7000, _WITHHELD: 7100, "dynastyNerdsSfTep": 6900},
        },
    }
    return {
        "scrapeTimestamp": "2026-10-16T00:00:00+00:00",
        "players": {
            name: {
                "position": p["position"],
                "team": "???",
                "_canonicalSiteValues": p["sites"],
                "_sites": len(p["sites"]),
            }
            for name, p in players.items()
        },
    }


def _health_zero(source_key: str) -> SourceWeighting:
    # Health FAILED: weight factor 0 on every row, so the source never votes.
    return SourceWeighting(
        source_key=source_key,
        measured=True,
        subsets={},
        health_state="FAILED",
        health_factor=0.0,
        coverage=None,
        coverage_factor=1.0,
        row_count=None,
        rolling_median_rows=None,
    )


@pytest.fixture
def contract(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    weighting = {_WITHHELD: _health_zero(_WITHHELD)}
    monkeypatch.setattr(dc, "_load_source_weighting", lambda as_of, csv_root=None: weighting)
    # The contract path may resolve weighting through the lower-level seam
    # (which also reports why weighting was unavailable); patch it too so the
    # test pins the blend, not which wrapper the build happens to call.
    if hasattr(dc, "_source_weighting_resolution"):
        monkeypatch.setattr(
            dc, "_source_weighting_resolution", lambda as_of, csv_root=None: (weighting, None)
        )
    return dc.build_api_data_contract(_payload())


def _row(contract: dict[str, Any], name: str) -> dict[str, Any]:
    return next(r for r in contract["playersArray"] if r.get("displayName") == name)


def test_row_with_every_source_withheld_is_unpriced_not_zero(contract):
    row = _row(contract, "Lonely Edge")
    assert row.get("rankDerivedValue") is None
    assert row.get("canonicalConsensusRank") is None
    meta = (row.get("sourceRankMeta") or {}).get(_WITHHELD) or {}
    assert meta.get("contributedToBlend") is False
    assert meta.get("excludedReason") == "freshness_or_health_zero_weight"


def test_no_published_value_is_zero(contract):
    for row in contract["playersArray"]:
        v = row.get("rankDerivedValue")
        assert v is None or v > 0, (row.get("displayName"), v)


def test_corroborated_rows_still_rank(contract):
    for name in ("Alpha QB", "Beta WR"):
        row = _row(contract, name)
        assert (row.get("rankDerivedValue") or 0) > 0
        assert row.get("canonicalConsensusRank") is not None


def test_unpriced_row_carries_no_single_source_haircut(contract):
    # The haircut is a statement about a value; a row nothing voted on has
    # none.  It used to be stamped ``singleSourceValuePenaltyApplied`` anyway
    # because the haircut ran before the no-vote exit (seen on the
    # 2026-10-18 18:59 archive: Chris Moore, Jawhar Jordan).
    row = _row(contract, "Lonely Edge")
    assert row.get("rankDerivedValue") is None
    assert not row.get("singleSourceValuePenaltyApplied")
