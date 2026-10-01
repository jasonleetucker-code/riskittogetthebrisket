"""Batch 3 Unit G — ingestion / lineage integrity sweep.

Two kinds of test live here:

* the measurement primitives of ``scripts/audit/lineage_integrity_sweep.py``
  on synthetic inputs (no live board, no network, no git history), so the
  numbers the sweep report quotes come from tested arithmetic;
* consistency guards for statements the sweep found contradicted by live
  code.  Guards for files owned by another active lane
  (``src/api/data_contract.py`` — Batch 3 Unit E; ``scripts/source_inventory.py``
  — the DLF / source-membership claim) are NON-strict xfails naming the
  owning lane: they fail today, and the owner's patch flips them to XPASS
  without breaking that lane's CI (remove the marker in the same patch).
  Patch descriptions are in ``docs/sources/integrity/INTEGRITY_SWEEP_2026-10-01.md`` §7.
"""

from __future__ import annotations

import importlib.util
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def sweep():
    path = REPO / "scripts" / "audit" / "lineage_integrity_sweep.py"
    spec = importlib.util.spec_from_file_location("lineage_integrity_sweep", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["lineage_integrity_sweep"] = module
    spec.loader.exec_module(module)
    return module


def _board(sweep, key, rows):
    """rows: list of (name, rank, value, position)."""
    lines = ["name,rank,value,position"]
    for name, rank, value, pos in rows:
        lines.append(
            f"{name},{'' if rank is None else rank},{'' if value is None else value},{pos}"
        )
    return sweep.parse_board(key, "\n".join(lines) + "\n")


# ── semantics / identity ──────────────────────────────────────────────


def test_duplicate_identity_is_recorded_not_silently_merged(sweep):
    b = _board(
        sweep, "x", [("Demario Douglas", None, 1946, "WR"), ("DeMario Douglas", None, 1946, "WR")]
    )
    assert len(b.entries) == 1
    assert len(b.duplicates) == 1
    assert b.duplicates[0]["sameSignal"] is True


def test_ordering_prefers_rank_then_negated_value(sweep):
    b = _board(sweep, "x", [("A Player", 2, 10, "WR"), ("B Player", None, 50, "WR")])
    order = sweep.ordering(b)
    assert order[sweep.canonical("A Player")] == 2
    assert order[sweep.canonical("B Player")] == -50


def test_position_universe(sweep):
    assert sweep.position_universe("WR") == "offense"
    assert sweep.position_universe("ED") == "idp"
    assert sweep.position_universe("RDP") == "pick"
    assert sweep.position_universe("K") is None


def test_universe_index_leaves_cross_universe_name_collisions_unresolved(sweep):
    a = _board(sweep, "a", [("Justin Jefferson", 1, None, "WR")])
    b = _board(sweep, "b", [("Justin Jefferson", 300, None, "LB")])
    idx = sweep.build_universe_index({"a": a, "b": b})
    assert sweep.canonical("Justin Jefferson") not in idx


# ── change clocks ─────────────────────────────────────────────────────


def test_insert_only_change_is_order_preserving(sweep):
    prev = _board(
        sweep, "x", [("A A", 1, None, "WR"), ("B B", 2, None, "WR"), ("C C", 3, None, "WR")]
    )
    cur = _board(
        sweep,
        "x",
        [
            ("A A", 1, None, "WR"),
            ("N N", 2, None, "WR"),
            ("B B", 3, None, "WR"),
            ("C C", 4, None, "WR"),
        ],
    )
    c = sweep.classify_rank_change(prev, cur)
    assert c["orderPreserving"] is True
    assert c["added"] == 1 and c["rankKeyChanged"] == 2


def test_swap_is_a_reordering(sweep):
    prev = _board(sweep, "x", [("A A", 1, None, "WR"), ("B B", 2, None, "WR")])
    cur = _board(sweep, "x", [("A A", 2, None, "WR"), ("B B", 1, None, "WR")])
    assert sweep.classify_rank_change(prev, cur)["orderPreserving"] is False


def test_unchanged_board_is_no_change(sweep):
    prev = _board(sweep, "x", [("A A", 1, None, "WR")])
    assert sweep.classify_rank_change(prev, prev) is None


def test_versions_match_events_observed_before_the_commit(sweep):
    t0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    versions = [t0, t0 + timedelta(hours=10)]
    # first event observed 20 min before its commit; second version has none
    events = [t0 - timedelta(minutes=20)]
    matched, leftover = sweep.match_versions_to_events(versions, events)
    assert matched == 1 and leftover == []
    # an event long after a commit never matches it
    assert sweep.match_versions_to_events([t0], [t0 + timedelta(hours=2)])[0] == 0


def test_cadence_check_reports_a_binding_declared_bound(sweep):
    as_of = datetime(2026, 10, 1, tzinfo=timezone.utc)
    hist = [{"at": (as_of - timedelta(hours=6 * k)).isoformat(), "broad": True} for k in range(10)]
    out = sweep.cadence_check({"changeHistory": hist}, {"minHours": 12, "maxHours": 48}, as_of)
    assert out["observedP75Hours"] == 6.0
    assert out["declaredBoundBinding"] == "minHours"


# ── dependence ────────────────────────────────────────────────────────


def _percentiles(sweep, values):
    return sweep.to_percentiles({k: -v for k, v in values.items()})


def test_leave_pair_out_residual_sees_a_shared_error_and_not_noise(sweep):
    rng = random.Random(7)
    truth = {f"p{i}": float(400 - i) for i in range(300)}
    shared = {k: rng.gauss(0, 40) for k in truth}
    boards = {
        "copyA": {k: v + shared[k] + rng.gauss(0, 5) for k, v in truth.items()},
        "copyB": {k: v + shared[k] + rng.gauss(0, 5) for k, v in truth.items()},
    }
    for j in range(5):
        boards[f"indep{j}"] = {k: v + rng.gauss(0, 40) for k, v in truth.items()}
    pct = {k: _percentiles(sweep, v) for k, v in boards.items()}
    pool = list(boards)
    copies, _ = sweep.leave_pair_out_residuals(pct, "copyA", "copyB", pool)
    indep, _ = sweep.leave_pair_out_residuals(pct, "indep0", "indep1", pool)
    assert copies > 0.8
    assert abs(indep) < 0.25


def test_leave_pair_out_excludes_both_members_from_the_consensus(sweep):
    # Two boards alone with one bystander: no name has 3 other observations,
    # so no consensus exists and nothing is reported (unknown, not zero).
    pct = {k: {f"p{i}": i / 50 for i in range(1, 51)} for k in ("a", "b", "c")}
    res, n = sweep.leave_pair_out_residuals(pct, "a", "b", ["a", "b", "c"])
    assert res is None and n == 0


def test_value_identity(sweep):
    vi = sweep.value_identity(
        {"x": 100.0, "y": 200.0, "z": 300.0}, {"x": 100.0, "y": 201.0, "z": 330.0}
    )
    assert vi["exactEqual"] == 1
    assert vi["within1pct"] == 2
    assert vi["n"] == 3


def test_discordant_share(sweep):
    a = {f"p{i}": float(i) for i in range(40)}
    assert sweep.discordant_share(a, dict(a))[1] == 0.0
    rev = {k: -v for k, v in a.items()}
    assert sweep.discordant_share(a, rev)[1] == 1.0
    assert sweep.discordant_share({"a": 1.0}, {"a": 1.0})[1] is None


# ── the committed sweep artifact ──────────────────────────────────────

SWEEP_JSON = REPO / "docs" / "sources" / "integrity" / "INTEGRITY_SWEEP_2026-10-01.json"


def test_committed_sweep_covers_every_voting_source():
    from src.api.data_contract import _RANKING_SOURCES

    data = json.loads(SWEEP_JSON.read_text(encoding="utf-8"))
    assert data["schema"] == "lineage-integrity-sweep/v1"
    voting = {s["key"] for s in _RANKING_SOURCES}
    swept = {k for k, v in data["sources"].items() if v.get("voting")}
    assert voting <= swept, sorted(voting - swept)


def test_committed_sweep_clocks_never_moved_on_byte_only_versions():
    """An unchanged re-fetch must never become 'new' (owner Section G)."""
    data = json.loads(SWEEP_JSON.read_text(encoding="utf-8"))
    offenders = {
        k: v["clockHonesty"]["byteOnlyCoincidingWithEvent"]
        for k, v in data["sources"].items()
        if (v.get("clockHonesty") or {}).get("byteOnlyCoincidingWithEvent")
    }
    assert offenders == {}


# ── four lineage categories (owner requirement) ───────────────────────


def _lineage():
    from src.sources import source_census as sc

    return sc, sc.load_lineage()


def test_lineage_registry_is_valid_with_four_categories():
    sc, lin = _lineage()
    assert sc.validate_lineage(lin) == []
    assert set(lin["categories"]) == set(sc.LINEAGE_CATEGORIES)
    assert len(sc.LINEAGE_CATEGORIES) == 4


OWNER_NAMED_PAIRS = {
    frozenset({"ktcCrowdSfTep", "fantasyNavigatorSf"}),
    frozenset({"pfkDynasty", "ktcCrowdSfTep"}),
    frozenset({"fantasyCalc", "dynastyDaddySf"}),
    frozenset({"fantasyProsSf", "fantasyProsFitzmaurice"}),
    frozenset({"dlfSf", "dlfRookieSf"}),
    frozenset({"draftSharks", "draftSharksIdp"}),
    frozenset({"ktcCrowdSfTep", "ktcTradesSfTep"}),
    frozenset({"idpTradeCalc", "idpShow"}),
    frozenset({"signalsDynasty", "ktcCrowdSfTep"}),
}


def test_every_owner_named_pair_is_reconciled_with_all_implications():
    sc, lin = _lineage()
    pairs = lin["pairReconciliation"]
    for want in OWNER_NAMED_PAIRS:
        hits = [p for p in pairs if want <= set(p["sources"])]
        assert hits, sorted(want)
        for p in hits:
            assert set(sc.PAIR_IMPLICATION_AXES) <= set(p["implications"]), p["id"]


def test_signals_is_unknown_not_guessed():
    _, lin = _lineage()
    sig = [p for p in lin["pairReconciliation"] if "signalsDynasty" in p["sources"]]
    assert sig and all(p["category"] is None and p["unknownReason"] for p in sig)


def _pair(**kw):
    base = {
        "id": "p",
        "sources": ["ktcCrowdSfTep", "pfkDynasty"],
        "category": "MEASURED_DEPENDENCE",
        "relations": ["pfk-ktc-dependence"],
        "measurement": {"method": "m", "window": "w", "n": 10},
        "implications": {
            a: "x"
            for a in (
                "familyCap",
                "hillHoldout",
                "sourceQualityEvaluation",
                "hillTraining",
                "completedTradeEvaluation",
            )
        },
        "evidence": ["config/sources/source_lineage.json"],
        "asOf": "2026-10-01",
    }
    base.update(kw)
    return base


def _errors_with(pair):
    sc, lin = _lineage()
    lin = json.loads(json.dumps(lin))
    lin["pairReconciliation"] = [pair]
    return sc.validate_lineage(lin)


def test_correlation_never_becomes_ancestry():
    # a measured relation cannot support PROVEN_COMMON_ANCESTRY
    errs = _errors_with(_pair(category="PROVEN_COMMON_ANCESTRY"))
    assert any("needs a supporting proven relation" in e for e in errs)


def test_measured_dependence_must_pin_method_window_and_n():
    errs = _errors_with(_pair(measurement={"method": "m"}))
    assert any("measurement must pin" in e for e in errs)


def test_unknown_category_and_missing_implication_are_rejected():
    assert any("category must be one of" in e for e in _errors_with(_pair(category="CORRELATED")))
    impl = dict(_pair()["implications"])
    impl.pop("hillHoldout")
    assert any("implications missing" in e for e in _errors_with(_pair(implications=impl)))
    assert any("needs unknownReason" in e for e in _errors_with(_pair(category=None)))


def test_supporting_relation_must_involve_two_of_the_pairs_own_sources():
    # fn-fantasypros-dependence is about (fantasyNavigatorSf, fantasyProsSf):
    # it shares ONE source with a (ktcCrowdSfTep, fantasyNavigatorSf) pair and
    # so cannot support it -- nor can a relation on a disjoint pair.
    one_shared = _pair(
        sources=["ktcCrowdSfTep", "fantasyNavigatorSf"],
        relations=["fn-ktc-dependence", "fn-fantasypros-dependence"],
    )
    errs = _errors_with(one_shared)
    assert any("'fn-fantasypros-dependence'" in e and "at least two" in e for e in errs), errs
    disjoint = _pair(relations=["fc-dd-dependence"])
    errs = _errors_with(disjoint)
    assert any("'fc-dd-dependence'" in e and "at least two" in e for e in errs), errs
    # A PROVEN pair cannot borrow proof from a relation on another pair.
    borrowed = _pair(
        sources=["ktcCrowdSfTep", "pfkDynasty"],
        category="PROVEN_COMMON_ANCESTRY",
        relations=["pfk-ktc-dependence", "fn-uses-ktc-data"],
    )
    errs = _errors_with(borrowed)
    assert any("needs a supporting proven relation" in e for e in errs), errs
    assert _errors_with(_pair()) == []


def _independent(pid, sources):
    return _pair(
        id=pid,
        sources=sources,
        category="INDEPENDENT_NO_EVIDENCE",
        relations=[],
        measurement=None,
    )


def _with_pfk_pair_replaced(sources):
    """The live registry with ``pair-ktc-pfk`` replaced by an uncited INDEPENDENT pair."""
    sc, lin = _lineage()
    lin = json.loads(json.dumps(lin))
    lin["pairReconciliation"] = [
        p for p in lin["pairReconciliation"] if p["id"] != "pair-ktc-pfk"
    ] + [_independent("pair-pfk-ktc-independent", sources)]
    return sc.validate_lineage(lin)


def test_independent_pair_cannot_omit_a_recorded_dependence():
    """#1601 review repro, literally: an INDEPENDENT (pfkDynasty, ktc) pair citing
    no relation used to validate while ``pfk-ktc-dependence`` records measured
    dependence of PFK on ``ktcSfTep`` -- which ``ktc-historical-calibration-states``
    PROVES is the same crowd as ``ktc``. Recorded evidence, cited or not, forbids
    "no evidence"."""
    errs = _with_pfk_pair_replaced(["pfkDynasty", "ktc"])
    assert any("pair-pfk-ktc-independent" in e and "'pfk-ktc-dependence'" in e for e in errs), errs


def test_independent_pair_contradicted_directly_by_an_uncited_relation():
    errs = _with_pfk_pair_replaced(["pfkDynasty", "ktcSfTep"])
    assert any("pair-pfk-ktc-independent" in e and "'pfk-ktc-dependence'" in e for e in errs), errs


def test_independent_pair_beside_a_proven_relation_is_refused():
    errs = _errors_with(_independent("p", ["ktcCrowdSfTep", "ktcTradesSfTep"]))
    assert any("'ktc-crowd-trades-same-payload'" in e and "proven" in e for e in errs), errs


def test_independent_pair_beside_only_a_suspected_relation_is_allowed():
    """SUSPECTED is not evidence of dependence strong enough to contradict the
    absence-of-evidence verdict at validation time (the manifest still takes the
    worse of the two)."""
    errs = _errors_with(_independent("p", ["signalsDynasty", "signalsIdpDynasty"]))
    assert errs == [], errs


def test_independent_pair_with_one_shared_source_is_not_contradicted():
    # fn-ktc-dependence joins fantasyNavigatorSf with ktcCrowdSfTep; a pair on
    # (fantasyNavigatorSf, draftSharks) shares only one of its sources.
    errs = _errors_with(_independent("p", ["fantasyNavigatorSf", "draftSharks"]))
    assert errs == [], errs


def test_missing_categories_key_is_rejected():
    sc, lin = _lineage()
    lin = json.loads(json.dumps(lin))
    del lin["categories"]
    assert any("categories must be exactly" in e for e in sc.validate_lineage(lin))


@pytest.mark.parametrize("bad_n", [0, -3, 1.5, "354", True])
def test_measurement_n_must_be_a_positive_int(bad_n):
    errs = _errors_with(_pair(measurement={"method": "m", "window": "w", "n": bad_n}))
    assert any("measurement.n must be an int > 0" in e for e in errs), errs


def test_fantasy_navigator_pairs_say_input_use_not_derived_values():
    _, lin = _lineage()
    by_id = {p["id"]: p for p in lin["pairReconciliation"]}
    ktc = by_id["pair-ktccrowd-fantasynavigator"]
    assert ktc["category"] == "PROVEN_COMMON_ANCESTRY"
    assert "fn-fantasypros-dependence" not in ktc["relations"]
    assert "Proven KTC INPUT USE" in ktc["basis"]
    assert "NOT KTC-derived values" in ktc["basis"]
    fp = by_id["pair-fantasynavigator-fantasyprossf"]
    assert fp["category"] == "MEASURED_DEPENDENCE"
    assert set(fp["sources"]) == {"fantasyNavigatorSf", "fantasyProsSf"}
    assert fp["measurement"]["n"] == 354
    assert "TWO families" in fp["implications"]["familyCap"]


def test_independent_no_evidence_cannot_contradict_a_measurement():
    errs = _errors_with(_pair(category="INDEPENDENT_NO_EVIDENCE"))
    assert any("contradicts" in e for e in errs)


def test_census_relations_carry_their_category():
    sc, lin = _lineage()
    cats = {sc.lineage_category(r) for r in lin["relations"]}
    assert cats <= set(sc.LINEAGE_CATEGORIES)


# ── consistency guards ────────────────────────────────────────────────


def test_idpshow_fetcher_no_longer_says_the_voting_board_votes_nothing():
    from src.api.data_contract import _RANKING_SOURCES

    assert "idpShowCombined" in {s["key"] for s in _RANKING_SOURCES}
    text = (REPO / "scripts" / "fetch_idpshow.py").read_text(encoding="utf-8")
    assert "votes NOTHING" not in text


@pytest.mark.xfail(
    strict=False,
    raises=AssertionError,
    reason=(
        "owned by the DLF / source-membership lane (scripts/source_inventory.py); "
        "non-strict so that lane's patch (INTEGRITY_SWEEP_2026-10-01.md §7 P3) "
        "does not break its CI"
    ),
)
def test_source_inventory_does_not_call_idpshow_a_cut_of_the_combined_board():
    text = (REPO / "scripts" / "source_inventory.py").read_text(encoding="utf-8")
    assert "IDP-only cut of idpShowCombined" not in text


def test_contract_phase_1c_comment_does_not_claim_the_set_is_empty():
    text = (REPO / "src" / "api" / "data_contract.py").read_text(encoding="utf-8")
    assert "this set is currently EMPTY" not in text


def test_contract_rookie_ladder_comment_names_the_crowd_ladder_it_uses():
    from src.api.data_contract import ROOKIE_LADDER_PAIRS

    assert ("dlfRookieSf", "ktcCrowdSfTep") in {(a, b) for a, b, _ in ROOKIE_LADDER_PAIRS}
    text = (REPO / "src" / "api" / "data_contract.py").read_text(encoding="utf-8")
    assert "KTC Crowd+Trades ladder" not in text
