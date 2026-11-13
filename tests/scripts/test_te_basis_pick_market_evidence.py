"""Pure-function tests for the MD-113 / MD-108 evidence script (no board rebuild)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.research import te_basis_pick_market_evidence as m

REPO = Path(__file__).resolve().parents[2]


def _te(name, value, rank, **meta):
    return {
        "displayName": name,
        "position": "TE",
        "assetClass": "offense",
        "rankDerivedValue": value,
        "canonicalConsensusRank": rank,
        "sourceRankMeta": meta,
    }


def test_quantile_and_summarize_empty_is_none_not_zero():
    assert m.quantile([], 0.5) is None
    assert m.summarize([])["median"] is None
    assert m.summarize([None, 2.0, 4.0])["median"] == 3.0
    assert m.quantile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5


def test_share_of_keeps_missing_missing():
    out = m.share_of({"a": 1.0, "b": 3.0, "c": None})
    assert out == {"a": 0.25, "b": 0.75, "c": None}
    assert m.share_of({"a": 0.0}) == {"a": None}


def test_te_vote_census_separates_converted_native_and_exempt():
    rows = [
        _te(
            "A",
            5000,
            10,
            dlfSf={"tepBoostApplied": True, "tepMultiplier": 1.3},
            idpTradeCalc={"tepNativeCorrectionApplied": True},
            ktcSfTep={},
        ),
        _te("B", 3000, 40, fantasyCalc={"tepBoostApplied": True, "tepMultiplier": 1.5}),
        {"displayName": "WR1", "position": "WR", "sourceRankMeta": {}},
    ]
    c = m.te_vote_census(rows)
    assert (c["teRows"], c["rowsWithConvertedVote"], c["convertedVotes"]) == (2, 2, 2)
    assert c["nativeFlatVotes"] == 1 and c["ktcExemptVotes"] == 1
    assert c["liftPerVote"]["median"] == 1.4


def test_edge_split_labels_and_gate():
    def r(ratio, direction, rank=10):
        return {
            **_te("x", 1, rank),
            "marketGapValueRatio": ratio,
            "marketGapDirection": direction,
        }

    rows = [
        r(0.20, "retail_premium"),
        r(0.20, "consensus_premium"),
        r(0.01, "retail_premium"),
        r(None, "none"),
        r(0.5, "retail_premium", rank=251),  # outside the label population
    ]
    te = m.edge_split(rows)["TE"]
    assert te == {"sell": 1, "buy": 1, "hold": 1, "unmeasured": 1}


def test_diff_boards_value_and_rank():
    base = [_te("A", 1000, 5), _te("B", 500, 9)]
    alt = [_te("A", 800, 7), _te("B", 500, 9)]
    d = m.diff_boards(base, alt)
    assert d["rowsChangedByPosition"] == {"TE": 1}
    assert d["pctChangeByPosition"]["TE"]["min"] == -0.2
    assert d["rankDisplacementTE"]["max"] == 2
    assert d["topTeMovers"][0]["name"] == "A"


def test_positional_pool_short_is_unknown_not_smaller():
    rows = [_te("A", 100, 1), _te("B", 50, 2)]
    assert m.positional_pool_value(rows, "TE", 2) == 150.0
    assert m.positional_pool_value(rows, "TE", 3) is None
    assert m.value_at_positional_rank(rows, "TE", 2) == 50.0
    assert m.value_at_positional_rank(rows, "TE", 3) is None


def test_demand_vs_value_uses_given_demand_and_team_count():
    rows = [_te(f"T{i}", 100 - i, i + 1) for i in range(4)] + [
        {
            "displayName": f"W{i}",
            "position": "WR",
            "assetClass": "offense",
            "rankDerivedValue": 100 - i,
            "canonicalConsensusRank": 10 + i,
        }
        for i in range(8)
    ]
    out = m.demand_vs_value(rows, {"TE": 2.0, "WR": 4.0}, team_count=2)
    assert out["starterPoolSize"] == {"QB": 0, "RB": 0, "TE": 4, "WR": 8}
    assert out["demandShare"]["TE"] == pytest.approx(0.3333, abs=1e-4)
    assert out["starterPoolValue"]["QB"] is None


def test_pick_class_uses_identity_owner():
    assert m.pick_class("2027 Early 1st") == {
        "year": 2027,
        "round": 1,
        "grade": "tier",
        "tier": "early",
        "slot": None,
    }
    assert m.pick_class("2027 Pick 1.02")["grade"] == "slot"
    assert m.pick_class("2028 Round 3")["grade"] == "generic"
    assert m.pick_class("Josh Allen") is None


def _pick(name, state, prov, conf, providers=()):
    return {
        "displayName": name,
        "assetClass": "pick",
        "rankDerivedValue": 1000,
        "confidenceBucket": conf,
        "pickValueProvenance": {"class": prov},
        "pickEvidence": {"state": state, "votingProviders": list(providers), "valueBasis": "x"},
    }


def test_pick_tables_and_provider_coverage():
    rows = [
        _pick("2028 Early 1st", "multi_provider", "direct_market_blend", "high", ["a", "b"]),
        _pick("2027 Pick 1.01", "single_provider", "rookie_pool_tether", "low", ["b"]),
        _pick("2027 Pick 6.01", "no_provider", "rookie_pool_tether", "low", []),
        {"displayName": "Pickens", "assetClass": "offense"},
    ]
    t = m.pick_class_table(rows)
    assert t["cells"]["2027:slot"]["rows"] == {"n": 2}
    assert t["cells"]["2027:slot"]["evidenceState"] == {"no_provider": 1, "single_provider": 1}
    cov = m.provider_coverage(rows)
    assert cov["soleProviderRowsByClass"] == {"b": {"2027:r1": 1}}
    assert m.provenance_by_confidence(rows)["rookie_pool_tether"] == {"low": 2}


def test_age_days_and_frozen_providers():
    assert m.age_days("2026-10-10T00:00:00Z", "2026-11-13T00:00:00Z") == 34.0
    assert m.age_days(None, "2026-11-13T00:00:00Z") is None
    assert m.age_days("garbage", "2026-11-13T00:00:00Z") is None
    out = m.frozen_providers(
        {
            "old": {"sourceDataAsOf": "2026-10-10T00:00:00Z"},
            "new": {"sourceDataAsOf": "2026-11-12T00:00:00Z"},
            "none": {},
        },
        "2026-11-13T00:00:00Z",
        14,
    )
    assert [out[k]["state"] for k in ("old", "new", "none")] == ["frozen", "current", "unknown"]


def test_change_gaps_skip_narrow_changes():
    hist = [
        {"at": "2026-01-01T00:00:00Z", "broad": True},
        {"at": "2026-01-02T00:00:00Z", "broad": False},
        {"at": "2026-01-11T00:00:00Z", "broad": True},
    ]
    assert m.change_gaps_days(hist) == [10.0]
    assert m.change_gaps_days(hist, only_broad=False) == [1.0, 9.0]


def test_diff_pick_rows_reports_state_and_confidence_moves():
    a = [_pick("2028 Early 1st", "multi_provider", "direct_market_blend", "high", ["a", "b"])]
    b = [dict(a[0], pickEvidence={"state": "single_provider"}, confidenceBucket="low")]
    b[0]["rankDerivedValue"] = 990
    d = m.diff_pick_rows(a, b)
    assert d["evidenceStateMoves"] == {"multi_provider->single_provider": 1}
    assert d["confidenceMoves"] == {"high->low": 1}
    assert d["pickRowsValueChanged"] == 1


def test_committed_evidence_files_are_well_formed():
    te = REPO / "docs/valuation/evidence/te-basis-2026-11-13/evidence.json"
    pk = REPO / "docs/picks/evidence/pick-market-2026-11-13/evidence.json"
    for path in (te, pk):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data["inputs"]["rawPayloadSha256"]) == 64
    t = json.loads(te.read_text(encoding="utf-8"))["result"]
    assert set(t["variants"]) == set(m.TE_VARIANTS)
    p = json.loads(pk.read_text(encoding="utf-8"))["result"]
    assert sum(p["provenanceCounts"].values()) == p["pickRows"]
