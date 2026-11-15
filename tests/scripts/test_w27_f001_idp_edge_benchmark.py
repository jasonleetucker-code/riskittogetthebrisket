"""Pins the W27-F001 research harness (research only — nothing here is served).

``scripts/research/w27_f001_idp_edge_benchmark.py`` evaluates the IDP edge
detectors and the candidate IDP benchmarks for the methodology proposal
``docs/valuation/methodology_proposals/W27_F001_IDP_EDGE_BENCHMARK.md``.

The fixture is a compact extract of ONE pinned, tracked archive board
(``dynasty_export_20261107_063955``) built at commit d7db52a43b; the numbers
below are the proposal's evidence, so a change to them must come with a
regenerated fixture and an updated proposal, never a loosened assertion.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "research" / "w27_f001_idp_edge_benchmark.py"
NODE_HARNESS = REPO / "scripts" / "research" / "w27_f001_frontend_crosscheck.mjs"
FIXTURE = REPO / "tests" / "scripts" / "fixtures" / "w27_f001_idp_edge_rows.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("w27_f001_idp_edge_benchmark", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


mod = _load_module()


@pytest.fixture(scope="module")
def fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def result(fixture) -> dict:
    return mod.analyze(fixture)


# ── provenance ────────────────────────────────────────────────────────────


def test_fixture_comes_from_the_pinned_tracked_archive(fixture):
    prov = fixture["provenance"]
    assert prov["archive"] == "dynasty_export_20261107_063955.zip"
    archive = REPO / "exports" / "archive" / prov["archive"]
    if not archive.exists():
        pytest.skip("tracked archive not present in this checkout")
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == prov["archiveSha256"]
    assert prov["gitHead"].startswith("d7db52a43b")


# ── 1. the canonical (KTC Market) edge on IDP rows ────────────────────────


def test_every_idp_row_is_explicitly_unpriced_by_ktc_market(result):
    census = result["census"]
    assert census["idpRows"] == 430
    assert census["byPosition"] == {"DB": 150, "DL": 165, "LB": 115}
    assert census["ktcMarketReason"] == {"no_ktc_coverage": 430}
    assert census["marketGapDirection"] == {"none": 430}
    # #2097's disclosure: an explicit "offense only", never a silent dash.
    assert census["rankingsEdgeLabel"] == {"offense only": 430}
    assert census["edgeFilterBuyOrSellMatches"] == 0


# ── 2. the incumbent /edge detector ───────────────────────────────────────


def test_incumbent_edge_detector_counts(result):
    inc = result["incumbentEdgeDetector"]
    assert inc["verdicts"] == {"BUY": 238, "HOLD": 15, "SELL": 85, "—": 92}
    # every BUY/SELL contradicts the "offense only" /rankings cell
    assert inc["contradictsRankings"] == 323
    # every one rests on expert evidence the blend itself weights below one
    # full-strength provider (FantasyPros 0.13 + Draft Sharks 0.2173)
    assert inc["verdictsWithExpertWeightBelowOne"] == 323
    assert inc["expertAppliedWeightBehindBuySell"]["median"] == pytest.approx(0.3473)
    assert inc["verdictsUsingAZeroWeightSource"] == 45
    # ...and those 45 count The IDP Show (zero weight in the blend; registry
    # relation to IDPTC: measured dependence, ancestry SUSPECTED) as evidence
    assert inc["verdictsCountingTheIdpShowAsAnExpert"] == 45
    assert inc["panelPopulationTop200ByIdptc"] == 38
    assert inc["panelVerdicts"] == {"BUY": 10, "HOLD": 3, "SELL": 25}


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_python_reproduction_matches_the_real_frontend_module(fixture):
    proc = subprocess.run(
        ["node", str(NODE_HARNESS), str(FIXTURE)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(REPO),
    )
    real = json.loads(proc.stdout)
    for row in fixture["idpRows"]:
        js = real["perRow"][row["displayName"]]
        py = mod.incumbent_idp_edge(row)
        assert js["idpMarketAction"] == py["label"], row["displayName"]
        assert js["rankingsEdge"] == mod.incumbent_rankings_edge(row), row["displayName"]
        assert js["inIdpPanelPopulation"] == mod.idp_in_top_by_idptc(row), row["displayName"]
    assert real["filterBuyMatches"] == 0 and real["filterSellMatches"] == 0
    # /edge's idpGapOf() parses "~N ordinal" but the titles say "~N%": every
    # parsed gap is 0, so the IDP panels sort by nothing and show "—" in Gap.
    assert real["titlesContainingOrdinal"] == 0
    assert real["rowsWithNonZeroParsedGap"] == 0
    assert all(item["gap"] == 0 for item in real["sellPanel"] + real["buyPanel"])


# ── 3. the incumbent's curve-shape artifact ───────────────────────────────


def test_independent_hill_oracle_reproduces_every_expert_vote(result):
    art = result["incumbentScaleArtifact"]
    assert art["hillOracleChecks"] == 890
    assert art["hillOracleMatchesWithin1"] == 890


def test_zero_disagreement_baseline_is_not_zero(result):
    art = result["incumbentScaleArtifact"]
    # experts that agree EXACTLY with IDPTC still produce these verdicts
    assert art["zeroDisagreementVerdicts"] == {"buy": 232, "hold": 51, "sell": 94}
    assert art["zeroDisagreementBaseline"]["median"] == pytest.approx(-0.1409)
    buckets = result["byIdptcRankBucket"]
    assert buckets["001-100"]["baselineMedian"] > 0.05  # SELL tilt at the top
    assert buckets["401+"]["baselineMedian"] < -0.05  # BUY tilt in the tail


def test_hill_value_matches_a_stamped_vote():
    # Micah Parsons, FantasyPros: percentile 0.406814 -> 2819 on the GLOBAL curve
    assert mod.hill_value(0.406814, 0.112, 0.725) in (2818, 2819)
    assert mod.hill_value(0.0, 0.112, 0.725) == 9999


# ── 4. signal independence ────────────────────────────────────────────────


def test_idptc_dominates_the_idp_blend_it_would_be_measured_against(result):
    ind = result["signalIndependence"]
    assert ind["idptcAppliedWeightShareOnIdpRows"]["median"] == pytest.approx(0.7422)
    assert ind["ktcInputsAppliedWeightShareOnOffenseRows"]["median"] == pytest.approx(0.1653)
    assert ind["idptcIsAlphaAnchorOnIdpRows"] == 377
    assert ind["nonIdptcVotesTranslatedThroughIdptcLadder"] == 267
    assert ind["idpRowsWhereIdptcIsTheOnlyVoter"] == 54
    assert ind["ofThoseModelEqualsIdptc"] == 28
    assert ind["ofThoseSingleSourceHaircut"] == 26


def test_c1_is_the_leave_out_gap_compressed_by_idptcs_own_share(result):
    c1 = result["candidateC1ModelVsIdptc"]
    slope = c1["regressionOnLeaveAnchorOutGap"]["slope"]
    assert slope == pytest.approx(0.2652, abs=1e-4)
    share = result["signalIndependence"]["idptcAppliedWeightShareOnIdpRows"]["median"]
    assert abs(slope - (1.0 - share)) < 0.01
    assert c1["verdicts"] == {"buy": 165, "hold": 144, "sell": 68, "unavailable": 53}


# ── 5. candidate C2 ───────────────────────────────────────────────────────


def _row(ranks: dict, weights: dict, idptc_value: float = 5000.0, **extra) -> dict:
    meta = {}
    for key, rank in ranks.items():
        meta[key] = {"effectiveRank": rank, "appliedWeight": weights.get(key, 1.0)}
    meta["idpTradeCalc"]["valueContribution"] = idptc_value
    meta["idpTradeCalc"]["valueContributionPath"] = "value_direct"
    return {"displayName": "x", "sourceRankMeta": meta, **extra}


LADDER = [9999.0 - 10.0 * i for i in range(900)]
FAMS = {"a": "famA", "b": "famB", "idpTradeCalc": "idpTradeCalc"}


def test_c2_is_exactly_zero_when_every_source_agrees_with_the_market():
    rank = 100
    row = _row({"idpTradeCalc": rank, "a": rank, "b": rank}, {}, idptc_value=LADDER[rank - 1])
    out = mod.candidate_c2(row, LADDER, FAMS)
    assert out["state"] == "available"
    assert out["ratio"] == 0.0


def test_c2_refuses_rather_than_reporting_a_zero_gap():
    no_market = _row({"idpTradeCalc": 10, "a": 20, "b": 30}, {})
    no_market["sourceRankMeta"]["idpTradeCalc"]["valueContributionPath"] = "rank_hill"
    assert mod.candidate_c2(no_market, LADDER, FAMS) == {
        "ratio": None,
        "state": "no_idp_market_price",
        "families": [],
        "evidenceWeight": 0.0,
    }
    q = _row({"idpTradeCalc": 10, "a": 20, "b": 30}, {}, quarantined=True)
    assert mod.candidate_c2(q, LADDER, FAMS)["state"] == "withheld_quarantined"
    one = _row({"idpTradeCalc": 10, "a": 20}, {})
    assert mod.candidate_c2(one, LADDER, FAMS)["state"] == "insufficient_independent_families"
    stale = _row({"idpTradeCalc": 10, "a": 20, "b": 30}, {"a": 0.13, "b": 0.2173})
    res = mod.candidate_c2(stale, LADDER, FAMS, min_weight=0.5)
    assert res["state"] == "insufficient_evidence_weight" and res["ratio"] is None
    held = _row({"idpTradeCalc": 10, "a": 20, "b": 30}, {"a": 0.0, "b": 0.0})
    assert mod.candidate_c2(held, LADDER, FAMS)["state"] == "no_independent_evidence"
    deep = _row({"idpTradeCalc": 10, "a": 5000, "b": 6000}, {})
    assert mod.candidate_c2(deep, LADDER, FAMS)["state"] == "no_independent_evidence"


def test_c2_idp_show_exclusion_is_a_parameter_not_a_premise():
    # Default (the proposal's D1 option): The IDP Show is excluded.
    fams = {**FAMS, "idpShowCombined": "idpShow"}
    row = _row({"idpTradeCalc": 50, "a": 150, "idpShowCombined": 50}, {})
    out = mod.candidate_c2(row, LADDER, fams)
    assert out["families"] == ["famA"]
    assert out["state"] == "insufficient_independent_families"
    # The alternative the owner may choose: only IDPTC itself is excluded.
    alt = mod.candidate_c2(row, LADDER, fams, excluded_families=mod.BENCHMARK_ONLY_FAMILIES)
    assert alt["families"] == ["famA", "idpShow"]
    assert alt["state"] == "available"


def test_c2_sensitivity_with_the_idp_show_included(result):
    sens = result["sensitivityIdpShowIncluded"]
    assert sens["idpShowKeys"] == ["idpShowCombined"]
    assert sens["rowsWithAnIdpShowPlacement"] == 301
    # zero applied weight on this board: including it changes nothing today
    assert sens["rowsWithIdpShowAppliedWeightAboveZero"] == 0
    for gate in ("twoFamilies", "twoFamiliesWeight0p5", "twoFamiliesWeight1p0"):
        assert sens["appliedWeights"][gate]["rowsDifferingFromExclusion"] == 0
    # ...but if its board were fresh (weight 1.0) it would decide the gate
    hypo = sens["idpShowAtFullWeightHypothetical"]
    assert hypo["twoFamiliesWeight1p0"]["states"]["available"] == 273
    assert hypo["twoFamiliesWeight1p0"]["verdicts5pct"] == {
        "buy": 204,
        "hold": 31,
        "sell": 38,
        "unavailable": 157,
    }
    assert hypo["twoFamilies"]["verdicts5pct"] == {
        "buy": 220,
        "hold": 32,
        "sell": 38,
        "unavailable": 140,
    }


def test_c2_direction_follows_the_independent_evidence():
    # sources place him deeper than the market does -> market above -> sell
    row = _row({"idpTradeCalc": 50, "a": 150, "b": 200}, {}, idptc_value=LADDER[49])
    assert mod._verdict(mod.candidate_c2(row, LADDER, FAMS)["ratio"]) == "sell"
    row = _row({"idpTradeCalc": 200, "a": 60, "b": 90}, {}, idptc_value=LADDER[199])
    assert mod._verdict(mod.candidate_c2(row, LADDER, FAMS)["ratio"]) == "buy"


def test_c2_on_the_pinned_board(result):
    c2 = result["candidateC2AnchorFreeOnMarketCurve"]
    assert c2["twoFamilies"]["states"] == {
        "available": 239,
        "insufficient_independent_families": 84,
        "no_idp_market_price": 53,
        "no_independent_evidence": 54,
    }
    assert c2["twoFamilies"]["verdicts5pct"] == {
        "buy": 139,
        "hold": 33,
        "sell": 67,
        "unavailable": 191,
    }
    # no IDP row on this board has even half a full-strength independent
    # provider behind it
    assert c2["twoFamiliesWeight0p5"]["states"].get("available", 0) == 0
    assert c2["twoFamiliesWeight1p0"]["states"].get("available", 0) == 0
    assert c2["incumbentToUngatedTransitions"] == {
        "buy->buy": 195,
        "buy->hold": 24,
        "buy->sell": 4,
        "buy->unavailable": 15,
        "hold->buy": 7,
        "hold->hold": 7,
        "hold->sell": 1,
        "sell->hold": 14,
        "sell->sell": 71,
    }


def test_selecting_on_one_side_manufactures_direction(result):
    sel = result["selectionGateEffect"]
    assert sel["populationSize"] == 38
    assert sel["topByIdptcRank"] == {"buy": 13, "hold": 2, "sell": 23}
    assert sel["topByEvidenceValue"] == {"buy": 28, "hold": 3, "sell": 7}


def test_c3_leave_idptc_out_board_was_recorded(result):
    loo = result["leaveIdptcOut"]
    assert loo is not None and loo["crosswalkFailed"] == {}
    assert loo["idpVoteMethods"]["fantasyProsIdp:extrapolated"] == 93
    assert result["candidateC3LeaveIdptcOutBoard"]["verdicts5pct"] == {
        "buy": 191,
        "hold": 17,
        "sell": 115,
        "unavailable": 107,
    }


# ── CSV-level oracle helpers (used by the history replay) ─────────────────


def test_within_idp_ranks_use_mid_ranks_for_ties():
    ranks = mod._within_idp_ranks([("a", 1.5), ("b", 1.5), ("c", 3.0)])
    assert ranks == {"a": 1.5, "b": 1.5, "c": 3.0}


def test_idp_group_spellings():
    assert mod.idp_group("DE (DL1)") == "DL"
    assert mod.idp_group("CB (DB)") == "DB"
    assert mod.idp_group("LB1") == "LB"
    assert mod.idp_group("ED") == "DL"
    assert mod.idp_group("S") == "DB"
    assert mod.idp_group("WR") is None


def test_csv_c2_zero_point_and_minimum_sources():
    idptc = {"p1": 900.0, "p2": 800.0, "p3": 700.0}
    agree = {"x": {"p1": 1, "p2": 2, "p3": 3}, "y": {"p1": 1, "p2": 2, "p3": 3}}
    out = mod.csv_c2(idptc, agree)
    assert all(math.isclose(v, 0.0, abs_tol=1e-12) for v in out.values())
    assert mod.csv_c2(idptc, {"x": agree["x"]}) == {}
