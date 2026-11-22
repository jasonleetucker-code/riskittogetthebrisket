"""Synthetic, hand-checked tests for the IDP independence measurement.

Every expected number below is computed by hand in the comment beside it.
No board, no network, no registry write: the measurement is read-only.
"""

from __future__ import annotations

import pytest

from src.sources import idp_independence as ii


def _row(**metas):
    return {"assetClass": "idp", "sourceRankMeta": metas}


def test_average_ranks_ties_share_the_mean_rank():
    # sorted 10,20,20,30 -> ranks 1, (2+3)/2, (2+3)/2, 4
    assert ii.average_ranks([10, 20, 20, 30]) == [1.0, 2.5, 2.5, 4.0]


def test_spearman_perfect_reversed_and_ties():
    assert ii.spearman([1, 2, 3], [5, 6, 9]) == pytest.approx(1.0)
    assert ii.spearman([1, 2, 3], [9, 6, 5]) == pytest.approx(-1.0)
    # rx=[1,2,3,4] ry=[1,2.5,2.5,4], both means 2.5; sxy=2.25+0+0+2.25=4.5,
    # sxx=5, syy=4.5 -> 4.5/sqrt(22.5) = 0.94868
    assert ii.spearman([1, 2, 3, 4], [1, 2, 2, 4]) == pytest.approx(0.94868, abs=1e-5)


def test_spearman_undefined_is_none_never_zero():
    assert ii.spearman([1], [1]) is None
    assert ii.spearman([1, 2, 3], [7, 7, 7]) is None


def test_weight_shares_pooled_and_per_row():
    rows = [
        _row(A={"appliedWeight": 1.0}, B={"appliedWeight": 1.0}),
        _row(A={"appliedWeight": 1.0}, B={"appliedWeight": 0.5}),
    ]
    out = ii.weight_shares(rows, ["A", "B"])
    # pooled: A 2/3.5, B 1.5/3.5; per row: A (1/2 + 1/1.5)/2, B (1/2 + 0.5/1.5)/2
    assert out["A"]["pooledShare"] == pytest.approx(0.5714, abs=1e-4)
    assert out["B"]["pooledShare"] == pytest.approx(0.4286, abs=1e-4)
    assert out["A"]["meanRowShare"] == pytest.approx(0.5833, abs=1e-4)
    assert out["B"]["meanRowShare"] == pytest.approx(0.4167, abs=1e-4)
    assert out["A"]["votingRows"] == out["B"]["votingRows"] == 2


def test_a_zero_weight_is_not_a_voter():
    rows = [_row(A={"appliedWeight": 1.0}, B={"appliedWeight": 0.0})]
    assert ii.voting_keys(rows) == ["A"]
    assert ii.weight_shares(rows, ["A", "B"])["B"]["votingRows"] == 0


def test_pairwise_spearman_uses_only_co_covered_rows():
    rows = [
        _row(A={"rawRank": 1}, B={"rawRank": 10}),
        _row(A={"rawRank": 2}, B={"rawRank": 20}),
        _row(A={"rawRank": 3}, B={"rawRank": 30}),
        _row(A={"rawRank": 4}),  # B absent: not counted
    ]
    out = ii.pairwise_spearman(rows, ["A", "B"], "rawRank")
    assert out["A|B"] == {"n": 3, "spearman": 1.0}
    with pytest.raises(ValueError):
        ii.pairwise_spearman(rows, ["A", "B"], "bogus")


def _native(a, b, pa="value_direct", pb="value_direct"):
    return {
        "canonicalSiteValues": {"A": a, "B": b},
        "sourceRankMeta": {
            "A": {"valueContributionPath": pa},
            "B": {"valueContributionPath": pb},
        },
    }


def test_identical_values_only_comparable_for_two_native_encodings():
    rows = [_native(5000, 5000), _native(4000, 4100)]
    out = ii.identical_value_share(rows, "A", "B")
    assert (out["n"], out["identical"], out["share"]) == (2, 1, 0.5)
    assert out["comparableEncoding"] is True
    rows = [_native(5000, 5000, pb="rank_hill"), _native(4000, 4100, pb="rank_hill")]
    assert ii.identical_value_share(rows, "A", "B")["comparableEncoding"] is False


def _t(raw, eff):
    return _row(
        T={
            "appliedWeight": 1,
            "rawRank": raw,
            "effectiveRank": eff,
            "sharedMarketTranslated": True,
            "valueContributionPath": "rank_hill",
            "ladderDepth": 3,
            "backboneDepth": 9,
        }
    )


def test_translation_profile_order_only_and_descents():
    rows = [_t(1, 5), _t(2, 8), _t(3, 8)]
    p = ii.translation_profile(rows, "T")
    assert p["translatedRows"] == 3 and p["translatedShare"] == 1.0
    assert p["orderOnly"] is True and p["rankDescents"] == 0
    assert p["ladderDepths"] == [3] and p["backboneDepths"] == [9]
    # raw ranks 1,2,3 -> effective 5,8,6: one descent (8 -> 6)
    p = ii.translation_profile([_t(1, 5), _t(2, 8), _t(3, 6)], "T")
    assert p["orderOnly"] is False and p["rankDescents"] == 1


def test_ladder_coupling_counts_votes_on_anchor_positions():
    rows = [
        _row(A={"rawRank": 3}, T={"sharedMarketTranslated": True, "effectiveRank": 3}),
        _row(A={"rawRank": 5}, T={"sharedMarketTranslated": True, "effectiveRank": 5}),
        _row(A={"rawRank": 9}, T={"sharedMarketTranslated": True, "effectiveRank": 7}),
        _row(T={"sharedMarketTranslated": False, "effectiveRank": 9}),  # ignored
    ]
    out = ii.ladder_coupling(rows, "T", "A")
    # anchor positions {3,5,9}; translated votes 3,5,7 -> 2 of 3
    assert (out["translatedVotes"], out["onAnchorPositions"]) == (3, 2)
    assert out["ladderSetShare"] == pytest.approx(0.6667, abs=1e-4)
    assert out["anchorPositions"] == 3


LINEAGE = {
    "relations": [
        {"id": "m", "sources": ["A", "B"], "classification": "measured"},
        {"id": "s", "sources": ["A", "B"], "classification": "suspected"},
        {"id": "p", "sources": ["A", "C"], "classification": "proven"},
    ]
}
PROVIDERS = {"A": "pa", "B": "pb", "C": "pc", "D": "pa"}


def test_similarity_relations_do_not_count_as_lineage_evidence():
    out = ii.pair_lineage(LINEAGE, PROVIDERS.get, "A", "B")
    assert [r["category"] for r in out["relations"]] == [
        "MEASURED_DEPENDENCE",
        "SUSPECTED_DEPENDENCE",
    ]
    assert out["countsAsLineageEvidence"] is False


def test_proven_relation_or_shared_provider_counts_as_lineage_evidence():
    assert ii.pair_lineage(LINEAGE, PROVIDERS.get, "A", "C")["countsAsLineageEvidence"] is True
    same = ii.pair_lineage(LINEAGE, PROVIDERS.get, "A", "D")
    assert same["sameProvider"] and same["countsAsLineageEvidence"] is True
    assert ii.pair_lineage(LINEAGE, PROVIDERS.get, "B", "C")["countsAsLineageEvidence"] is False


_HIGH = {
    "independence": "high",
    "coverage": "high",
    "freshness": "high",
    "applicability": "high",
    "agreement": "high",
}


def test_confidence_profile_bottleneck_and_sole_blocker():
    rows = [
        {
            "confidenceBucket": "medium",
            "independentSourceCount": 4,
            "confidenceAxes": {**_HIGH, "independence": "medium"},
        },
        {
            "confidenceBucket": "low",
            "independentSourceCount": 2,
            "confidenceAxes": {**_HIGH, "independence": "low", "agreement": "low"},
        },
        {"confidenceBucket": "high", "independentSourceCount": 5, "confidenceAxes": dict(_HIGH)},
        {"confidenceBucket": "low"},  # no axes: skipped
    ]
    out = ii.confidence_profile(rows, independence_high_families=5)
    assert out["rowsWithAxes"] == 3
    assert out["buckets"] == {"medium": 1, "low": 1, "high": 1}
    # row1 floor medium -> independence; row2 floor low -> independence + agreement
    assert out["bottleneckAxes"] == {"independence": 2, "agreement": 1}
    # only row1 has exactly one axis below high
    assert out["soleBlockerAxes"] == {"independence": 1}
    assert out["maxFamiliesOnAnyRow"] == 5 and out["rowsAtOrAboveHighFamilies"] == 1


def test_withheld_reasons_groups_by_reason_class():
    rows = [
        {"sourceAuthorityReasons": {"X": "held:owner_policy", "Y": "stale=0.087@2026-09-04"}},
        {"sourceAuthorityReasons": {"X": "held:owner_policy", "Y": "outlier_dropped"}},
    ]
    assert ii.withheld_reasons(rows) == {
        "X": {"held": 2},
        "Y": {"stale": 1, "outlier_dropped": 1},
    }


def test_board_diff_hand_checked():
    def mk(name, value, bucket, rank):
        return {
            "displayName": name,
            "rankDerivedValue": value,
            "confidenceBucket": bucket,
            "canonicalConsensusRank": rank,
        }

    base = [mk("a", 100, "low", 1), mk("b", 200, "low", 2), mk("c", 400, "low", 3)]
    alt = [mk("a", 110, "medium", 1), mk("b", 200, "low", 3), mk("c", 400, "low", 3)]
    out = ii.board_diff(base, alt)
    # deltas sorted [0, 0, 0.10]: median idx 1 -> 0, p90 idx 2 -> 10.0%
    assert out["matchedRows"] == 3 and out["valuesMoved"] == 1
    assert out["medianAbsPct"] == 0.0 and out["p90AbsPct"] == 10.0 and out["maxAbsPct"] == 10.0
    assert out["confidenceBucketFlips"] == 1
    assert out["consensusRankChanges"] == 1  # only b: rank 2 -> 3
