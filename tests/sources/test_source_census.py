"""Source trust census (Batch 3 Unit A) — ``src/sources/source_census.py``.

Invariants, not counts: the board under test is the newest COMPLETE archived
scrape (``tests.archive_fixtures``), so nothing here depends on which sources
answered the last live refresh.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import pytest

from src.api import data_contract as dc
from src.history import asof as ledger_asof
from src.history import keys as ledger_keys
from src.history import store as ledger_store
from src.sources import ktc_market
from src.sources import source_census as sc
from src.sources.signals import BOARDS as SIGNALS_BOARDS

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    from scripts import source_census as cli
    from tests.archive_fixtures import newest_complete_raw_payload

    payload, name = newest_complete_raw_payload()
    if payload is None:
        pytest.skip("no complete archived scrape to build a census from")
    path = tmp_path_factory.mktemp("census") / f"{Path(str(name)).stem}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    args = argparse.Namespace(
        state_dir=REPO / "data" / "scrape_state",
        ledger=tmp_path_factory.mktemp("noledger") / "absent.sqlite",
        no_git=True,
        label="TEST",
    )
    inputs = cli.collect_inputs(path, args)
    census = sc.build_census(inputs)
    return inputs, census


def _entry(census, key):
    return next(e for e in census["sources"] if e["key"] == key)


# ── population ───────────────────────────────────────────────────────────


def test_every_registered_source_appears_as_a_model_input(built):
    _, census = built
    keys = {e["key"] for e in census["sources"]}
    for src in dc._RANKING_SOURCES:
        assert src["key"] in keys
        e = _entry(census, src["key"])
        assert e["votingStatus"] in (sc.VOTING, sc.REGISTERED_NO_VOTES)
        assert e["family"]["correlationGroup"] == dc.correlation_group_for(src["key"])
        assert e["weighting"]["baseWeight"] == float(src["weight"])


def test_non_voting_benchmarks_and_second_opinions_appear_with_reasons(built):
    _, census = built
    expected = (
        {ktc_market.KTC_MARKET_KEY}
        | {b.source_key for b in SIGNALS_BOARDS.values()}
        | set(dc._NON_VOTING_SOURCE_CSV_KEYS)
        | {"dlfValuesSfTep"}
    )
    for key in expected:
        e = _entry(census, key)
        assert e["votingStatus"] == sc.NON_VOTING, key
        assert e["nonVotingClass"] in sc.NON_VOTING_CLASSES - {sc.NV_UNCLASSIFIED}, key
        assert isinstance(e["nonVotingReason"], str) and e["nonVotingReason"].strip(), key
        assert e["weighting"]["effectiveAuthority"] is None
    assert _entry(census, ktc_market.KTC_MARKET_KEY)["nonVotingClass"] == sc.NV_BENCHMARK
    for b in SIGNALS_BOARDS.values():
        assert _entry(census, b.source_key)["nonVotingClass"] == sc.NV_SECOND_OPINION
    assert census["summary"]["unclassified"] == []


# ── missing is never zero ────────────────────────────────────────────────


def test_every_unknown_is_null_with_a_reason(built):
    _, census = built
    for e in census["sources"]:
        nulls = sc.none_paths(e)
        missing = [p for p in nulls if p not in e["unknown"]]
        assert not missing, (e["key"], missing)
        assert all(isinstance(r, str) and r.strip() for r in e["unknown"].values())


def test_signals_without_a_local_store_are_null_not_zero(built):
    _, census = built
    for b in SIGNALS_BOARDS.values():
        e = _entry(census, b.source_key)
        if e["freshness"]["state"] is None:
            assert "freshness.state" in e["unknown"]
            assert e["coverage"]["datasetRows"] is None
            assert "coverage.datasetRows" in e["unknown"]


def test_build_refuses_a_null_without_a_reason():
    entry = sc._Entry("x")
    with pytest.raises(ValueError):
        entry.set("a.b", None)
    entry.set("a.c", 1)
    entry.data["a"]["d"] = None  # bypassing set() must still be caught
    with pytest.raises(ValueError):
        entry.finish()


# ── no subjective score ──────────────────────────────────────────────────


def _all_keys(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(str(k))
            _all_keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _all_keys(v, out)
    return out


def test_no_numeric_quality_score_field_exists(built):
    _, census = built
    # Pins are excluded: they echo feature-flag names, which are not census fields.
    scanned = {k: v for k, v in census.items() if k != "pins"}
    keys = {k.lower() for k in _all_keys(scanned, set())}
    for banned in ("score", "quality", "rating", "grade", "stars", "rank10"):
        offenders = [k for k in keys if k == banned or k.endswith(banned)]
        assert not offenders, (banned, offenders)
    for e in census["sources"]:
        assert e["evidenceState"] in sc.EVIDENCE_STATES
        assert isinstance(e["evidenceState"], str)


def test_no_source_claims_out_of_sample_evaluation_without_a_record(built):
    _, census = built
    for e in census["sources"]:
        if e["evidenceState"] == sc.EVIDENCE_OUT_OF_SAMPLE:
            assert any(r["kind"] == "out_of_sample" for r in e["evidenceRecords"])
    assert census["summary"]["cleanOutOfSampleEvaluationPossibleNow"] == []
    assert census["outOfSampleEvaluation"]["globalBlockers"]


# ── effective authority is the pipeline's own ────────────────────────────


def test_effective_authority_equals_the_pipelines_stamped_weights(built):
    inputs, census = built
    contract = inputs.contract
    summary = contract["sourceWeighting"]["sources"]
    applied = defaultdict(list)
    for row in contract["playersArray"]:
        for key, meta in (row.get("sourceRankMeta") or {}).items():
            if sc._voted(meta):
                applied[key].append(float(meta["appliedWeight"]))
    for src in dc._RANKING_SOURCES:
        key = src["key"]
        auth = _entry(census, key)["weighting"]["effectiveAuthority"]
        assert auth["matchesPipelineSummary"] is True, key
        assert auth["votingRows"] == summary[key]["votingRows"] == len(applied[key])
        if applied[key]:
            mean = round(sum(applied[key]) / len(applied[key]), 4)
            assert auth["meanAppliedWeight"] == mean == summary[key]["meanAppliedWeight"]
    assert census["summary"]["authorityMismatches"] == []


def test_source_level_factors_are_the_published_ones(built):
    inputs, census = built
    summary = inputs.contract["sourceWeighting"]["sources"]
    for src in dc._RANKING_SOURCES:
        key = src["key"]
        sw = summary[key]
        w = _entry(census, key)["weighting"]
        if sw.get("measured"):
            assert w["healthFactor"] == sw["healthFactor"]
            assert w["coverageFactor"] == sw["coverageFactor"]
            assert w["freshnessFactor"] == sw["subsets"]["players"]["freshness"]


# ── lineage registry ─────────────────────────────────────────────────────


def test_lineage_registry_is_valid_and_evidence_backed():
    lineage = sc.load_lineage()
    assert sc.validate_lineage(lineage, REPO) == []
    for rel in lineage["relations"]:
        assert rel["classification"] in ("proven", "measured", "suspected")
        assert rel["evidence"] and all((REPO / p).exists() for p in rel["evidence"])
        if rel["classification"] == "measured":
            assert "dependence" in rel["relation"] or "independence" in rel["relation"]


def test_validate_lineage_rejects_measured_ancestry_and_missing_evidence():
    lineage = json.loads(json.dumps(sc.load_lineage()))
    lineage["relations"].append(
        {
            "id": "bad",
            "sources": ["a", "b"],
            "relation": "derived_from",
            "classification": "measured",
            "evidence": ["does/not/exist.md"],
        }
    )
    errors = sc.validate_lineage(lineage, REPO)
    assert any("bad" in e and "dependence" in e for e in errors)
    assert any("does/not/exist.md" in e for e in errors)


def test_every_census_source_has_a_lineage_entry(built):
    _, census = built
    assert census["summary"]["lineageGaps"] == []
    for e in census["sources"]:
        assert e["provider"]["id"] in sc.load_lineage()["providers"]


def test_suspected_is_kept_apart_from_proven(built):
    _, census = built
    lineage = sc.load_lineage()
    cls = {r["id"]: r["classification"] for r in lineage["relations"]}
    for e in census["sources"]:
        for fld, want in (
            ("provenAncestry", "proven"),
            ("measuredDependence", "measured"),
            ("suspectedAncestry", "suspected"),
        ):
            assert all(cls[r["id"]] == want for r in e["lineage"][fld])


def test_ktc_market_lineage_agrees_with_its_canonical_owner():
    rel = next(r for r in sc.load_lineage()["relations"] if r["id"] == "ktc-market-derived")
    assert set(rel["sources"]) == {ktc_market.KTC_MARKET_KEY, *ktc_market.KTC_MARKET_DERIVED_FROM}
    assert rel["classification"] == "proven"


def test_required_lineage_pairs_are_recorded():
    rels = sc.load_lineage()["relations"]

    def has(a, b, classification=None):
        return any(
            a in r["sources"]
            and b in r["sources"]
            and (classification is None or r["classification"] == classification)
            for r in rels
        )

    assert has("ktcCrowdSfTep", "ktcTradesSfTep", "proven")
    assert has("fantasyNavigatorSf", "ktcCrowdSfTep", "proven")
    assert has("fantasyNavigatorSf", "ktcCrowdSfTep", "measured")
    assert has("pfkDynasty", "ktcSfTep", "measured")
    assert has("pfkDynasty", "ktcSfTep", "suspected")
    assert has("fantasyCalc", "dynastyDaddySf", "measured")
    assert has("dlfSf", "dlfValuesSfTep")
    assert has("fantasyProsSf", "fantasyProsFitzmaurice")
    assert has("flockFantasySf", "flockFantasySfRookies", "proven")
    assert has("draftSharks", "draftSharksIdp", "proven")
    assert has("idpShowCombined", "idpShow", "proven")
    assert has("idpTradeCalc", "idpShow", "measured")


# ── IO collectors ────────────────────────────────────────────────────────


def test_profile_csv_counts_tied_values_given_distinct_ranks(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("name,value,rank\na,10,1\nb,10,2\nc,9,3\nd,8,4\ne,8,4\n", encoding="utf-8")
    prof = sc.profile_csv(p)
    assert prof["rows"] == 5
    assert prof["valueMax"] == 10.0 and prof["valueMin"] == 8.0
    assert prof["tiedValueRowsWithDistinctRanks"] == 2  # a/b tied at 10 with ranks 1,2
    assert sc.profile_csv(tmp_path / "missing.csv") is None


def test_ledger_coverage_never_creates_the_database(tmp_path):
    target = tmp_path / "ledger.sqlite"
    got = ledger_asof.source_lane_coverage(target)
    assert got["exists"] is False and got["reason"]
    assert not target.exists()


def test_ledger_coverage_counts_source_lane_dates(tmp_path):
    target = tmp_path / "ledger.sqlite"
    asset = ledger_keys.player_asset_key("4984", "Josh Allen", "QB")
    rows = [
        {
            "asset_key": asset,
            "asset_class": ledger_keys.ASSET_CLASS_OFFENSE,
            "lane": ledger_store.LANE_SOURCE,
            "source_key": "ktcCrowdSfTep",
            "observed_date": day,
            "observed_at": f"{day}T12:00:00+00:00",
            "observed_at_zone": "utc",
            "value": 9990.0,
            "rank": None,
            "tier": None,
            "confidence": None,
            "display_name": "Josh Allen",
            "position": "QB",
            "player_id": "4984",
            "scope": None,
            "pipeline_version": None,
            "origin": "test",
        }
        for day in ("2026-08-01", "2026-08-02")
    ]
    res = ledger_store.write_observations(rows, path=target)
    assert res["written"] == 2, res
    got = ledger_asof.source_lane_coverage(target)
    assert got["exists"] is True
    assert got["sources"]["ktcCrowdSfTep"]["distinctDates"] == 2
    assert got["sources"]["ktcCrowdSfTep"]["firstDate"] == "2026-08-01"


def test_synthetic_census_marks_unregistered_unreasoned_files_unclassified():
    inputs = sc.CensusInputs(
        contract={"playersArray": [], "sourceWeighting": {"sources": {}}},
        registry=[{"key": "a", "weight": 1.0, "scope": "overall_offense", "game_type": "DYNASTY"}],
        value_based=frozenset(),
        non_voting_declared=frozenset(),
        retired_groups={},
        csv_paths={"a": {"path": "CSVs/site_raw/a.csv", "signal": "rank"}},
        lineage={"sources": {}, "providers": {}, "relations": [], "evaluations": [], "defects": []},
        on_disk_csv_stems=["a", "mystery"],
        benchmark_key="bench",
    )
    census = sc.build_census(inputs)
    assert _entry(census, "mystery")["nonVotingClass"] == sc.NV_UNCLASSIFIED
    assert census["summary"]["unclassified"] == ["mystery"]
    a = _entry(census, "a")
    assert a["votingStatus"] == sc.REGISTERED_NO_VOTES
    assert a["provider"] is None and "provider" in a["unknown"]
    assert census["summary"]["lineageGaps"] == sorted(["a", "bench", "mystery"])
    assert a["outOfSampleEvaluation"]["state"] == sc.OOS_BLOCKED


def test_cli_writes_json_and_markdown_and_exits_clean(tmp_path):
    from scripts import source_census as cli
    from tests.archive_fixtures import newest_complete_raw_payload

    payload, _ = newest_complete_raw_payload()
    if payload is None:
        pytest.skip("no complete archived scrape")
    raw = tmp_path / "raw.json"
    raw.write_text(json.dumps(payload), encoding="utf-8")
    out_json, out_md = tmp_path / "c.json", tmp_path / "c.md"
    code = cli.main(
        [
            "--payload",
            str(raw),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
            "--no-git",
            "--ledger",
            str(tmp_path / "absent.sqlite"),
        ]
    )
    assert code == 0
    census = json.loads(out_json.read_text(encoding="utf-8"))
    assert census["schema"] == sc.CENSUS_SCHEMA
    assert census["lineageErrors"] == []
    assert census["temporalLedger"]["exists"] is False
    assert "| source |" in out_md.read_text(encoding="utf-8")
    assert cli.main(["--payload", str(tmp_path / "nope.json")]) == 2


def test_redraft_and_unverified_boards_are_never_dynasty_evaluation_ready(built):
    _, census = built
    for key in ("draftSharksRosSf", "draftSharksRosIdp"):
        if any(e["key"] == key for e in census["sources"]):
            e = _entry(census, key)
            assert e["gameType"] == "REDRAFT_ROS"
            assert "GAME_TYPE_NOT_VERIFIED_DYNASTY" in e["outOfSampleEvaluation"]["blockers"]
    ready = set(census["summary"]["outOfSampleDataPrerequisitesMet"])
    for e in census["sources"]:
        if e.get("gameType") != "DYNASTY":
            assert e["key"] not in ready, e["key"]


def test_every_evidence_kind_held_is_published_and_no_applied_weight_is_recomputed(built):
    _, census = built
    for e in census["sources"]:
        held = e["evidenceHeld"]
        assert isinstance(held, list)
        assert e["evidenceState"] == (held[0] if held else "UNEVALUATED")
        assert "sourceLevelEffectiveWeight" not in (e.get("weighting") or {})


def _relation_with_stats(measurements, as_of="2026-10-01"):
    return {
        "id": "stats-under-test",
        "sources": ["otcffbSf", "ktc"],
        "relation": "measured_dependence",
        "classification": "measured",
        "evidence": ["config/sources/source_lineage.json"],
        "asOf": as_of,
        "statistics": measurements,
    }


def _m(as_of, status, **values):
    return {
        "asOf": as_of,
        "status": status,
        "method": "leave-pair-out residual",
        "window": "w",
        "n": 100,
        "values": values or {"residualR": 0.5},
    }


def _stats_errors(statistics, as_of="2026-10-01"):
    lineage = json.loads(json.dumps(sc.load_lineage()))
    lineage["relations"].append(_relation_with_stats(statistics, as_of))
    return [e for e in sc.validate_lineage(lineage, REPO) if "stats-under-test" in e]


def test_relation_statistics_are_a_dated_history():
    good = {
        "measurements": [
            _m("2026-08-04", "superseded", residualR=0.329),
            _m("2026-10-01", "current", residualR=0.654),
        ]
    }
    assert _stats_errors(good) == []


def test_flat_statistics_are_refused():
    # The defect the D2 review found: a bare number beside a refreshed summary.
    errors = _stats_errors({"residualRho": 0.891})
    assert any("exactly {'measurements'" in e for e in errors)


def test_statistics_need_exactly_one_current_dated_as_the_relation():
    two = {"measurements": [_m("2026-10-01", "current"), _m("2026-10-01", "current")]}
    assert any("exactly one measurement must be current" in e for e in _stats_errors(two))
    none = {"measurements": [_m("2026-08-04", "superseded")]}
    assert any("exactly one measurement must be current" in e for e in _stats_errors(none))
    # Refreshing asOf without adding a measurement is refused.
    stale = {"measurements": [_m("2026-08-04", "current")]}
    assert any("must carry the relation asOf" in e for e in _stats_errors(stale))


def test_a_superseded_measurement_cannot_be_newer_than_the_current_one():
    bad = {
        "measurements": [_m("2026-10-02", "superseded"), _m("2026-10-01", "current")],
    }
    assert any("newer than the current" in e for e in _stats_errors(bad))


def test_measurement_entries_pin_date_method_values_and_a_real_n():
    entry = _m("2026-10-01", "current")
    for field, value, needle in (
        ("asOf", "yesterday", "ISO date"),
        ("method", "", "method required"),
        ("values", {}, "values must be a non-empty object"),
        ("values", {"r": "high"}, "every value must be a number"),
        ("n", 0, "n must be an int > 0"),
        ("n", True, "n must be an int > 0"),
        ("status", "latest", "status must be one of"),
    ):
        broken = dict(entry, **{field: value})
        errors = _stats_errors({"measurements": [broken]})
        assert any(needle in e for e in errors), (field, errors)
    # n may be null: unrecorded is distinguishable from a sample size.
    assert _stats_errors({"measurements": [dict(entry, n=None)]}) == []


def test_census_view_carries_only_the_current_measurement():
    rel = next(r for r in sc.load_lineage()["relations"] if r["id"] == "otc-ktc-dependence")
    view = sc._relation_view(rel, "otcffbSf")
    assert view["statistics"]["status"] == "current"
    assert view["statistics"]["asOf"] == rel["asOf"]


def test_otc_holdout_lineage_is_recorded_against_every_offense_trainer():
    """OTC is a declared OFFENSE Hill holdout; its relation to every OFFENSE
    trainer must be a recorded, categorised pair (D2 follow-up) — an
    unmeasured pair must not read as an independent one."""
    from src.model_registry import training_manifest as tm

    trainers = {
        s.source_key
        for s in tm._DEFAULT_SPECS
        if s.scope == "OFFENSE" and s.requested_role == tm.ROLE_TRAIN
    }
    pairs = sc.load_lineage()["pairReconciliation"]
    covered = {
        s: p["category"]
        for p in pairs
        if "otcffbSf" in p["sources"]
        for s in p["sources"]
        if s != "otcffbSf"
    }
    missing = trainers - set(covered)
    assert not missing, f"OTC has no recorded pair with trainers {sorted(missing)}"
    assert all(covered[t] in sc.LINEAGE_CATEGORIES for t in trainers)


def test_lineage_cannot_assert_dynasty_game_type():
    import copy

    lineage = json.loads(
        (REPO / "config" / "sources" / "source_lineage.json").read_text(encoding="utf-8")
    )
    bad = copy.deepcopy(lineage)
    next(iter(bad["sources"].values()))["gameType"] = "DYNASTY"
    assert any(
        "DYNASTY may only come from the source registry" in e for e in sc.validate_lineage(bad)
    )
