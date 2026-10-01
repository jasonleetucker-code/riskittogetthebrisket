"""Leakage-safe source-quality evaluator (Batch 3 B/C) -- invariants on synthetic panels.

No assertion depends on which sources answered the last scrape: the live-board
test only asserts the equal-weight override reproduces the champion exactly.
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from src.source_quality import challengers as ch
from src.source_quality import evaluate as ev
from src.source_quality import metrics as mt
from src.source_quality import panel as pn
from src.source_quality.bootstrap import block_ids, bootstrap
from tests.source_quality.synthetic import START, build_panel, spec

FAST = mt.Config(n_boot=60, splits=4)


@pytest.fixture(scope="module")
def synth():
    panel, dates = build_panel()
    m = pn.build_matrix(panel, dates)
    return panel, dates, m, m.family_matrix()


# ── point in time ────────────────────────────────────────────────────────


def test_as_of_never_returns_a_later_version(synth):
    panel, dates, *_ = synth
    for k in panel.versions:
        for d in dates[::7]:
            t = pn.day_end(d) - timedelta(hours=13)  # before that day's noon version
            v = panel.as_of(k, t)
            assert v is None or v.known_at <= t
            nxt = [x for x in panel.versions[k] if x.known_at > t]
            assert not nxt or v is not nxt[0]


def test_as_of_rejects_naive_instants(synth):
    panel, *_ = synth
    with pytest.raises(ValueError):
        panel.as_of("src_lead", datetime(2026, 5, 1))


def test_truncated_panel_holds_nothing_after_the_cutoff(synth):
    panel, dates, *_ = synth
    cut = pn.day_end(dates[40])
    t = panel.truncated(cut)
    assert all(v.known_at <= cut for vs in t.versions.values() for v in vs)
    assert sum(len(v) for v in t.versions.values()) < sum(len(v) for v in panel.versions.values())


def test_matrix_is_causal_slice_equals_truncated_build(synth):
    panel, dates, m, _ = synth
    c = 50
    a = pn.build_matrix(panel.truncated(pn.day_end(dates[c])), dates[: c + 1])
    b = ev.slice_matrix(m, c)
    assert a.assets == b.assets or set(a.assets) <= set(b.assets)
    idx = {x: i for i, x in enumerate(b.assets)}
    for k, arr in a.obs.items():
        sub = b.obs[k][[idx[x] for x in a.assets]]
        assert np.array_equal(np.isnan(arr), np.isnan(sub))
        assert np.allclose(arr[np.isfinite(arr)], sub[np.isfinite(sub)])


def test_a_future_observation_can_never_change_learned_weights(synth):
    panel, dates, m, X = synth
    plan = ev.Plan(primary_horizon=7, metrics=FAST)
    cut = 70
    before = ev.candidate_weights(
        "C3_lead_lag_authority",
        ev.slice_matrix(m, cut),
        {f: a[:, : cut + 1] for f, a in X.items()},
        plan,
        False,
    )
    # Corrupt every version known after the cutoff (reverse every board).
    cutoff = pn.day_end(dates[cut])
    mutated = {
        k: [
            v
            if v.known_at <= cutoff
            else replace(v, rows=tuple(reversed(v.rows)), content_hash="x" + v.content_hash)
            for v in vs
        ]
        for k, vs in panel.versions.items()
    }
    m2 = pn.build_matrix(pn.ObservationPanel(list(panel.specs.values()), mutated), dates)
    X2 = m2.family_matrix()
    after = ev.candidate_weights(
        "C3_lead_lag_authority",
        ev.slice_matrix(m2, cut),
        {f: a[:, : cut + 1] for f, a in X2.items()},
        plan,
        False,
    )
    assert before[0] == after[0]
    assert np.isfinite(list(before[0].values())).all()


# ── leave-family-out targets ─────────────────────────────────────────────


def test_lead_target_excludes_the_evaluated_family(synth):
    _, _, m, X = synth
    res = mt.lead_lag(m, X, "lead", "OFFENSE", 7, FAST)
    assert res["status"] == "ok"
    assert "lead" not in res["targetFamilies"]
    res2 = mt.lead_lag(m, X, "lead", "OFFENSE", 7, FAST, exclude_targets=frozenset({"a"}))
    assert set(res2["targetFamilies"]) == {"b", "c", "d"}


def test_future_agreement_target_excludes_the_evaluated_family():
    # Family "self" is pure noise but perfectly persistent; it would score
    # perfectly against a target that contained itself.
    panel, dates = build_panel(
        lags={"self": 0, "a": 0, "b": 0, "c": 0}, noise={"self": 3.0}, days=60
    )
    m = pn.build_matrix(panel, dates)
    X = m.family_matrix()
    fa = mt.future_agreement(m, X, "OFFENSE", 7, FAST)
    assert fa["self"]["point"] < min(fa[f]["point"] for f in ("a", "b", "c"))


def test_a_leading_family_measures_positive_lead_and_laggards_do_not(synth):
    _, _, m, X = synth
    lead = mt.lead_lag(m, X, "lead", "OFFENSE", 7, FAST)["betaGap"]
    lag = mt.lead_lag(m, X, "a", "OFFENSE", 7, FAST)["betaGap"]
    assert lead["ci90"][0] > 0
    assert lead["point"] > lag["point"]


def test_noise_family_shows_higher_self_reversal():
    panel, dates = build_panel(
        noise={"lead": 0.05, "a": 0.8, "b": 0.05, "c": 0.05, "d": 0.05}, days=80
    )
    m = pn.build_matrix(panel, dates)
    X = m.family_matrix()
    noisy = mt.stability(m, X, "a", "OFFENSE", 7, FAST)["selfReversal"]["point"]
    calm = mt.stability(m, X, "b", "OFFENSE", 7, FAST)["selfReversal"]["point"]
    assert noisy > calm


# ── bootstrap ────────────────────────────────────────────────────────────


def test_block_bootstrap_is_deterministic_under_a_seed():
    dates = [START + timedelta(days=i) for i in range(60)]
    rng = np.random.default_rng(1)
    per = np.stack([rng.normal(1, 1, 60), np.ones(60)], axis=1)
    blocks = block_ids(dates, 14)

    def stat(s):
        return s[0] / s[1]

    a = bootstrap(per, stat, blocks, n_boot=200, seed=11)
    b = bootstrap(per, stat, blocks, n_boot=200, seed=11)
    c = bootstrap(per, stat, blocks, n_boot=200, seed=12)
    assert a == b
    assert a.se != c.se
    assert a.n_blocks == 5


def test_bootstrap_never_reports_an_undefined_statistic_as_a_number():
    dates = [START + timedelta(days=i) for i in range(10)]
    per = np.zeros((10, 2))
    est = bootstrap(
        per, lambda s: None if s[1] == 0 else s[0] / s[1], block_ids(dates, 7), n_boot=50, seed=1
    )
    assert est.point is None and est.se is None


# ── shrinkage, cap, families ─────────────────────────────────────────────


def test_shrinkage_bounds_and_no_signal_means_champion():
    q = {f: ch.Quality(p, 0.01, 8) for f, p in zip("abcdef", [0.9, 0.1, 0.5, 0.4, -0.7, 3.0])}
    w, _ = ch.shrunk_weights(q)
    assert all(1 - ch.CAP <= v <= 1 + ch.CAP for v in w.values())
    assert w["f"] > w["a"] > w["e"]
    noisy = {f: ch.Quality(p, 10.0, 8) for f, p in zip("abcd", [0.9, 0.1, 0.5, 0.4])}
    w2, d2 = ch.shrunk_weights(noisy)
    assert set(w2.values()) == {1.0} and "champion" in d2["reason"]


def test_thin_evidence_never_moves_a_family():
    q = {
        "a": ch.Quality(5.0, 0.01, 2),
        "b": ch.Quality(0.0, 0.01, 8),
        "c": ch.Quality(0.1, 0.01, 8),
        "d": ch.Quality(-0.1, 0.01, 8),
    }
    w, _ = ch.shrunk_weights(q)
    assert w["a"] == 1.0


@pytest.mark.parametrize("bad", [1.3, 0.7, math.nan, math.inf, -1.0])
def test_authority_cap_refuses_pathological_weights(bad):
    with pytest.raises(ValueError):
        ch.validate_weight(bad)
    with pytest.raises(ValueError):
        ch.to_source_overrides({"fam": bad}, {"k1": "fam"})


def test_correlated_products_of_one_family_are_not_double_rewarded():
    from src.api import data_contract as dc

    # Two identical products: the family score is their MEAN, not their sum.
    panel, dates = build_panel(lags={"x": 0, "a": 4, "b": 4}, days=30)
    vs = panel.versions["src_x"]
    twin = [replace(v, source="src_x2") for v in vs]
    specs = list(panel.specs.values()) + [spec("src_x2", "x")]
    p2 = pn.ObservationPanel(specs, {**panel.versions, "src_x2": twin})
    X1 = pn.build_matrix(panel, dates).family_matrix()
    X2 = pn.build_matrix(p2, dates).family_matrix()
    assert np.allclose(np.nan_to_num(X1["x"]), np.nan_to_num(X2["x"]))
    # Each member gets the family weight, and the production family cap holds the
    # family's total authority to that one weight however many members vote.
    fam_of = {"dlfSf": "dlf", "dlfRookieSf": "dlf", "dlfIdp": "dlf"}
    ov = ch.to_source_overrides({"dlf": 1.2}, fam_of)
    assert ov == {"dlfSf": 1.2, "dlfRookieSf": 1.2, "dlfIdp": 1.2}
    adjusted, _ = dc.cap_family_weights({"dlfSf": 1.2, "dlfRookieSf": 1.2}, base=ov)
    assert sum(adjusted.values()) == pytest.approx(1.2)


# ── parsing, identity, ledger ────────────────────────────────────────────


def test_parse_csv_keeps_published_order_and_drops_non_fantasy_positions():
    s = spec("v", "v")
    rows, stats = pn.parse_csv(
        "name,Rank,position\nJosh Allen,2,QB\nTyler Bass,1,K\nBijan Robinson,1,RB\n", s
    )
    assert [r.name for r in sorted(rows, key=lambda r: r.order)] == ["bijan robinson", "josh allen"]
    assert stats["nonFantasyPosition"] == 1
    vs = replace(s, signal="value")
    rows, _ = pn.parse_csv("name,value\n2027 Early 1st,7000\nJosh Allen,9000\n", vs)
    assert rows[0].is_pick and rows[0].order == -7000.0


def test_multi_universe_source_classified_only_by_same_date_co_observation():
    off = spec("off", "off", ("OFFENSE",))
    idp = spec("idp", "idp", ("IDP",))
    both = spec("both", "both", ("OFFENSE", "IDP"))
    t = datetime(2026, 5, 1, 12, tzinfo=timezone.utc)

    def ver(k, names):
        rows = tuple(pn.Row(n, float(i + 1), None, False) for i, n in enumerate(names))
        return pn.Version(k, t, "s", rows, {}, pn._hash_rows(rows))

    p = pn.ObservationPanel(
        [off, idp, both],
        {
            "off": [ver("off", ["a", "dup"])],
            "idp": [ver("idp", ["b", "dup"])],
            "both": [ver("both", ["a", "b", "dup", "ghost"])],
        },
    )
    m = pn.build_matrix(p, [date(2026, 5, 1)])
    assert m.identity["both"] == {"ambiguousUniverse": 1, "unclassifiedUniverse": 1}
    assert "a::OFFENSE" in m.assets and "b::IDP" in m.assets
    assert not np.isfinite(m.obs["both"][m.assets.index("dup::OFFENSE"), 0])


def test_ledger_rows_without_an_instant_are_known_at_end_of_day(tmp_path):
    db = tmp_path / "ledger.sqlite"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE observations (source_key TEXT, observed_date TEXT, observed_at TEXT, display_name TEXT, position TEXT, value REAL, lane TEXT)"
    )
    con.executemany(
        "INSERT INTO observations VALUES (?,?,?,?,?,?,?)",
        [
            ("v", "2026-07-20", None, "Josh Allen", "QB", 9000, "source_value"),
            ("v", "2026-07-20", None, "Bijan Robinson", "RB", 9500, "source_value"),
            (
                "v",
                "2026-07-21",
                "2026-07-21T06:00:00+00:00",
                "Josh Allen",
                "QB",
                9600,
                "source_value",
            ),
            ("v", "2026-07-21", None, "Ignored", "QB", 1, "canonical_board"),
        ],
    )
    con.commit()
    con.close()
    out = pn.versions_from_ledger(db, [replace(spec("v", "v"), signal="value")])["v"]
    assert out[0].known_at == datetime(2026, 7, 20, 23, 59, 59, tzinfo=timezone.utc)
    assert out[1].known_at.hour == 6
    assert [r.name for r in out[0].rows] == ["bijan robinson", "josh allen"]


def test_eligibility_fails_closed_on_unverified_game_type():
    census = {
        "sources": [
            {
                "key": "a",
                "votingStatus": "VOTING",
                "gameType": "DYNASTY",
                "outOfSampleEvaluation": {"state": "DATA_PREREQUISITES_MET"},
                "family": {"correlationGroup": "a"},
                "population": {"offense": True},
            },
            {
                "key": "b",
                "votingStatus": "VOTING",
                "gameType": None,
                "outOfSampleEvaluation": {"state": "DATA_PREREQUISITES_MET"},
            },
            {
                "key": "c",
                "votingStatus": "VOTING",
                "gameType": "REDRAFT_ROS",
                "outOfSampleEvaluation": {"state": "DATA_PREREQUISITES_MET"},
            },
            {"key": "d", "votingStatus": "NON_VOTING", "nonVotingClass": "benchmark"},
        ]
    }
    specs, excluded = pn.eligible_specs(census, [{"key": "a"}], {"a": "CSVs/site_raw/a.csv"})
    assert [s.key for s in specs] == ["a"]
    assert set(excluded) == {"b", "c", "d"}


def test_fundamental_foresight_and_transaction_fit_declare_missing_evidence(synth):
    _, dates, m, X = synth
    assert mt.fundamental_foresight(m, X, None, dates[-1])["status"] == "INSUFFICIENT_EVIDENCE"
    assert mt.transaction_fit(None)["status"] == "INSUFFICIENT_EVIDENCE"


# ── walk-forward + gates on synthetic data ───────────────────────────────


def test_walk_forward_learns_only_before_each_fold(synth):
    _, dates, m, X = synth
    plan = ev.Plan(primary_horizon=7, fold_start=dates[60], fold_days=14, metrics=FAST)
    wf = ev.walk_forward(
        m,
        X,
        plan,
        False,
        {
            "allTargets": frozenset(),
            "noKtcTargets": frozenset(),
            "noKtcLineageTargets": frozenset(),
        },
    )
    assert wf["status"] == "ok"
    for fold in wf["folds"]:
        assert fold["learnedThrough"] < fold["foldStart"] <= fold["testOrigins"][0]
    g = ev.gates(wf, plan, m.dates, False, {c: True for c in ev.CANDIDATES})
    assert g["C2_asset_class_reliability"]["disposition"] == "NOT_RUN"
    assert g["C3_lead_lag_authority"]["disposition"] in {
        "MEETS_PREREGISTERED_GATE",
        "DOES_NOT_MEET_PREREGISTERED_GATE",
        "INSUFFICIENT_EVIDENCE",
    }


# ── the override path (real archived board) ──────────────────────────────


@pytest.fixture(scope="module")
def raw_payload():
    from tests.archive_fixtures import newest_complete_raw_payload

    payload, _ = newest_complete_raw_payload()
    if payload is None:
        pytest.skip("no complete archived scrape")
    return payload


def test_equal_weight_champion_reproduces_the_live_board_via_the_override_path(raw_payload):
    from src.api import value_replay as vr

    fam_of = ev.registry_families()
    base = vr.build(raw_payload)
    equal = vr.build(
        raw_payload,
        {"weights": ch.to_source_overrides({f: 1.0 for f in set(fam_of.values())}, fam_of)},
    )
    assert vr.board_hash(equal) == vr.board_hash(base)
    moved = vr.build(raw_payload, {"weights": ch.to_source_overrides({"dlf": 1.2}, fam_of)})
    assert vr.board_hash(moved) != vr.board_hash(base)


def test_end_to_end_run_and_report_on_a_synthetic_panel():
    import importlib.util
    from pathlib import Path

    from src.source_quality import report

    path = Path(__file__).resolve().parents[2] / "scripts" / "source_quality_eval.py"
    spec_ = importlib.util.spec_from_file_location("source_quality_eval", path)
    mod = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(mod)
    panel, dates = build_panel(days=110)
    plan = ev.Plan(primary_horizon=7, fold_start=dates[60], metrics=FAST)
    result = mod.run(panel, {}, {"sources": []}, {"relations": []}, plan, progress=lambda _m: None)
    assert result["status"] == "SHADOW"
    assert set(result["gates"]) == set(ev.CANDIDATES)
    assert result["gates"]["C2_asset_class_reliability"]["disposition"] == "NOT_RUN"
    result["pins"].update(
        {
            "codeRevision": "x",
            "preregistration": {"path": "p", "sha256": "0" * 64, "commit": "c"},
            "census": {"path": "c", "sha256": "0" * 64},
            "ledgerUsed": False,
        }
    )
    md = report.markdown(result)
    assert "SHADOW" in md and "Challenger dispositions" in md
    json.dumps(result)


def test_archive_records_are_compact_and_shadow():
    result = {
        "generatedAt": "2026-10-01T00:00:00+00:00",
        "pins": {"codeRevision": "abc", "preregistration": {"sha256": "p"}, "panelDigest": "d"},
        "dataWindow": ["2026-04-16", "2026-09-30"],
        "plan": {"primary_horizon": 21},
        "finalWeights": {"C1": {"a": 1.0}},
        "gates": {
            "C1": {
                "disposition": "INSUFFICIENT_EVIDENCE",
                "strata": {"ALL": {}},
                "failed": [],
                "missingEvidence": ["x"],
            }
        },
    }
    recs = ev.archive_records(result)
    assert recs[0]["status"] == "SHADOW" and recs[0]["preregistrationSha256"] == "p"
    assert len(json.dumps(recs[0])) < 2000
