"""chaseTradeMarket P6a simulation + power study (G12s) — synthetic only.

Pins the generator's invariants, the bench's leakage and weighting rules, the
compression invariance of every headline metric, missing-is-never-zero in the
shortfall, and that nothing on the valuation path can reach this code.
"""

from __future__ import annotations

import ast
import json
import math
import re
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from src.trade import market_trade_sim as sim
from src.trade import market_trade_sim_bench as bench
from src.valuation_math import package_model

REPO = Path(__file__).resolve().parents[2]
SMALL = sim.SimConfig(
    seed=11, n_offense=60, n_idp=20, pick_years=2, pick_rounds=3, n_leagues=16, trades_per_league=14
)


def _trades(rows):
    """Hand-built TradeSet: rows of (side_a, side_b, league, date, collected)."""
    k = sim.MAX_PACKAGE
    pad = lambda s: list(s) + [-1] * (k - len(s))  # noqa: E731
    n = len(rows)
    return sim.TradeSet(
        side_a=np.asarray([pad(r[0]) for r in rows], dtype=int),
        side_b=np.asarray([pad(r[1]) for r in rows], dtype=int),
        league=np.asarray([r[2] for r in rows], dtype=int),
        stratum=np.zeros(n, dtype=int),
        date=np.asarray([r[3] for r in rows], dtype=float),
        collected=np.asarray([r[4] for r in rows], dtype=float),
        mgr_a=np.asarray([2 * i for i in range(n)], dtype=int),
        mgr_b=np.asarray([2 * i + 1 for i in range(n)], dtype=int),
        component=np.asarray([r[2] for r in rows], dtype=int),
        maturity_now=np.full(n, 3),
        maturity_pit=np.full(n, 3),
        true_residual=np.zeros(n),
        contaminated=np.zeros(n, dtype=bool),
    )


# --------------------------------------------------------------------------- #
# Generator
# --------------------------------------------------------------------------- #


def test_world_is_deterministic_and_every_id_is_synthetic():
    a, b = sim.generate_world(SMALL), sim.generate_world(SMALL)
    for name in sim.TradeSet.__dataclass_fields__:
        assert np.array_equal(getattr(a.trades, name), getattr(b.trades, name)), name
    ids = a.assets.ids + a.leagues.ids + a.manager_ids + a.component_ids
    assert all(i.startswith("syn-") for i in ids)
    assert not any(re.search(r"\d{15,}", i) for i in ids)
    other = sim.generate_world(replace(SMALL, seed=12))
    assert not np.array_equal(other.trades.date, a.trades.date)


def test_trades_are_packages_with_unequal_counts_disjoint_sides_and_latency():
    t = sim.generate_world(SMALL).trades
    counts = t.counts()
    assert counts.min() >= 1 and counts.max() <= sim.MAX_PACKAGE
    assert (counts[:, 0] != counts[:, 1]).any() and (counts[:, 0] == counts[:, 1]).any()
    for i in range(t.n):
        a = set(t.side_a[i][t.side_a[i] >= 0].tolist())
        b = set(t.side_b[i][t.side_b[i] >= 0].tolist())
        assert a and b and not (a & b)
    assert (t.collected >= t.date).all()
    assert (t.mgr_a != t.mgr_b).all()


def test_geom_log_utility_matches_the_package_model_owner():
    rng = np.random.default_rng(0)
    for _ in range(50):
        vals = rng.uniform(1, 9999, size=int(rng.integers(1, 6)))
        for q in (0.70, 0.78, 1.0):
            assert math.isclose(
                sim.geom_log_utility(vals, q),
                math.log(package_model.geom_utility(vals, q)),
                rel_tol=1e-12,
            )


def test_manager_lineage_components_are_transitive():
    comp = sim.manager_lineage_components([[0, 1], [1, 2], [9], [2, 4], [7]])
    assert comp[0] == comp[1] == comp[3]
    assert len({comp[0], comp[2], comp[4]}) == 3
    assert comp.tolist() == [0, 0, 1, 0, 2]  # dense, ordered by first league


def test_true_trade_residual_is_the_clearing_gap_under_q_true():
    w = sim.generate_world(SMALL)
    t = w.trades
    fx = w.true_format_offset
    for i in range(0, t.n, max(1, t.n // 25)):
        vals = np.exp(w.assets.theta_at(t.date[i]) + fx[w.assets.position, t.stratum[i]])
        a = vals[t.side_a[i][t.side_a[i] >= 0]]
        b = vals[t.side_b[i][t.side_b[i] >= 0]]
        gap = sim.geom_log_utility(a, w.config.q_true) - sim.geom_log_utility(b, w.config.q_true)
        assert math.isclose(gap, t.true_residual[i], abs_tol=1e-9)


def test_maturity_has_both_readings_and_cohorts():
    w = sim.generate_world(replace(SMALL, season_end_day=180))
    t = w.trades
    before = t.date < 180
    assert (t.maturity_pit[before] == t.maturity_now[before] - 1).all()
    assert (t.maturity_pit[~before] == t.maturity_now[~before]).all()
    assert sim.maturity_cohort(np.array([0, 1, 2, 3, 6])).tolist() == [
        "below_B",
        "below_B",
        "B",
        "A",
        "A",
    ]


def test_format_offsets_leave_the_reference_stratum_at_zero():
    fx = sim.format_offset_matrix((("QB", "1QB", -0.5), ("TE", "TEP", 0.25)))
    assert (fx[:, sim.REFERENCE_STRATUM] == 0).all()
    qb, te = sim.POSITIONS.index("QB"), sim.POSITIONS.index("TE")
    assert fx[qb].tolist() == [0.0, 0.0, -0.5, -0.5]
    assert fx[te].tolist() == [0.0, 0.25, 0.0, 0.25]
    design = sim.format_effect_design((("QB", "1QB", -0.5),))
    assert design.sum() == 2  # (QB, 1QB/NONE) and (QB, 1QB/TEP)


# --------------------------------------------------------------------------- #
# Folds and weights
# --------------------------------------------------------------------------- #


def test_reserve_assignment_is_hash_based_and_order_independent():
    ids = [f"syn-comp-{i:04d}" for i in range(400)]
    res = sim.reserved_components(ids, salt="s", share=0.2)
    rev = sim.reserved_components(ids[::-1], salt="s", share=0.2)
    assert {ids[i] for i in res} == {ids[::-1][i] for i in rev}
    assert 50 < len(res) < 110
    assert sim.reserved_components(ids, salt="other", share=0.2) != res


def test_chronological_split_filters_on_collection_time_not_trade_date():
    t = _trades(
        [
            ([0], [1], 0, 10.0, 11.0),
            ([1], [2], 0, 95.0, 130.0),  # dated before the cutoff, collected after: NOT training
            ([2], [3], 1, 99.0, 99.5),
            ([3], [4], 1, 120.0, 121.0),  # inside the purge gap: neither
            ([4], [5], 1, 140.0, 141.0),
        ]
    )
    train, test, cutoff = sim.chronological_split(t, cutoff_day=100.0, purge_days=30.0)
    assert train.tolist() == [True, False, True, False, False]
    assert test.tolist() == [False, False, False, False, True]
    assert cutoff == 99.5


def test_observation_weights_recency_league_cap_and_pair_cap():
    t = _trades([([0], [1], 0, 100.0 - 90.0 * k, 100.0) for k in range(3)])
    w = bench.observation_weights(
        t, evidence_cutoff=100.0, half_life_days=90.0, league_cap=None, pair_cap=None
    )
    assert np.allclose(w, [1.0, 0.5, 0.25])
    many = _trades([([0], [1], 0, 50.0, 51.0)] * 40 + [([2], [3], 1, 50.0, 51.0)] * 3)
    w = bench.observation_weights(
        many, evidence_cutoff=51.0, half_life_days=None, league_cap=10.0, pair_cap=None
    )
    assert math.isclose(w[many.league == 0].sum(), 10.0)
    assert np.allclose(w[many.league == 1], 1.0)
    pair = _trades([([0], [1], 0, 50.0, 51.0)] * 6)
    pair.mgr_a[:] = 3
    pair.mgr_b[:] = 4
    pair.mgr_a[::2], pair.mgr_b[::2] = 4, 3  # same unordered pair, both directions
    w = bench.observation_weights(
        pair, evidence_cutoff=51.0, half_life_days=None, league_cap=None, pair_cap=2.0
    )
    assert math.isclose(w.sum(), 2.0)
    assert bench.kish_effective_n(np.ones(9)) == 9.0


# --------------------------------------------------------------------------- #
# Model internals
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("loss,mgr", [("huber", False), ("l2", True)])
def test_objective_gradient_matches_finite_differences(loss, mgr):
    w = sim.generate_world(SMALL)
    t = w.trades.subset(np.arange(w.trades.n) < 60)
    spec = bench.EstimatorSpec("g", loss=loss, manager_effect=mgr)
    d = bench._build_design(w, t, spec)
    rng = np.random.default_rng(3)
    p = rng.normal(0, 0.7, d.n_params)
    wt = rng.uniform(0.2, 1.0, t.n)
    args = (d, 0.78, wt, loss, 0.15, 0.25)
    _, g = bench._objective(p, *args)
    for j in rng.choice(d.n_params, size=25, replace=False):
        e = np.zeros_like(p)
        e[j] = 1e-6
        num = (bench._objective(p + e, *args)[0] - bench._objective(p - e, *args)[0]) / 2e-6
        assert math.isclose(num, g[j], rel_tol=1e-4, abs_tol=1e-5), (j, num, g[j])


def test_two_edge_connected_core_drops_a_pendant_asset():
    t = _trades(
        [([0], [1], 0, 1, 1), ([1], [2], 0, 1, 1), ([2], [0], 0, 1, 1), ([0], [3], 0, 1, 1)]
    )
    core = bench.two_edge_connected_core(5, t, np.zeros(5, dtype=int))
    assert core.tolist() == [True, True, True, False, False]
    # A pair seen in two trades is never a bridge.
    t2 = _trades([([0], [1], 0, 1, 1), ([1], [0], 0, 1, 1)])
    assert bench.two_edge_connected_core(2, t2, np.zeros(2, dtype=int)).all()


def test_pairwise_accuracy_is_compression_invariant():
    rng = np.random.default_rng(1)
    truth = rng.normal(size=40)
    est = truth + rng.normal(0, 0.4, size=40)
    acc, n = bench.pairwise_accuracy(truth, est, min_log_gap=0.2)
    assert n > 0
    assert bench.pairwise_accuracy(truth, np.exp(3 * est) + 7, min_log_gap=0.2)[0] == acc
    assert bench.pairwise_accuracy(truth, np.full(40, 2.0), min_log_gap=0.2)[0] == 0.5
    assert bench.pairwise_accuracy(truth, -truth, min_log_gap=0.2)[0] == 0.0
    assert bench.pairwise_accuracy(truth[:1], est[:1], min_log_gap=0.2) == (None, 0)


def _fit_from(world, theta, status=None):
    n = world.assets.n
    return bench.FitResult(
        spec=bench.EstimatorSpec("fixed"),
        theta=np.asarray(theta, dtype=float),
        se_contrast=None,
        status=np.full(n, bench.STATUS_SUPPORTED, dtype=object) if status is None else status,
        reason=np.full(n, "", dtype=object),
        format_offset=np.zeros((len(sim.POSITIONS), len(sim.STRATA))),
        q_eval=0.78,
        core=np.ones(n, dtype=bool),
        info={"appearances": np.ones(n)},
        diagnostics={},
        n_clusters=5,
    )


def test_decoy_metric_gives_a_compressed_board_no_credit_and_the_truth_credit():
    w = sim.generate_world(SMALL)
    flat = bench.decoy_accuracy(w, _fit_from(w, np.zeros(w.assets.n)), w.trades, q=0.78)
    assert flat["easy"] == 0.5 and flat["hard"] == 0.5 and flat["evaluated"] > 0
    truth = bench.decoy_accuracy(
        w, _fit_from(w, w.assets.theta_at(w.config.span_days / 2)), w.trades, q=0.78
    )
    assert truth["easy"] > 0.75 and truth["hard"] > 0.6


def test_decoy_metric_skips_unpriced_trades_instead_of_imputing():
    w = sim.generate_world(SMALL)
    status = np.full(w.assets.n, bench.STATUS_SUPPORTED, dtype=object)
    theta = np.zeros(w.assets.n)
    hit = int(w.trades.side_a[0, 0])
    status[hit], theta[hit] = bench.STATUS_INSUFFICIENT, np.nan
    out = bench.decoy_accuracy(w, _fit_from(w, theta, status), w.trades, q=0.78)
    touching = ((w.trades.side_a == hit) | (w.trades.side_b == hit)).any(axis=1).sum()
    assert out["skipped_unpriced"] == touching > 0


# --------------------------------------------------------------------------- #
# Estimators end to end
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def fitted():
    # No IDP leagues, so every IDP asset is untraded: the missing-evidence path.
    cfg = replace(
        SMALL,
        n_leagues=40,
        trades_per_league=30,
        noise_scale=0.06,
        contamination_share=0.0,
        drift_sd_per_week=0.0,
        idp_league_share=0.0,
    )
    w = sim.generate_world(cfg)
    train, _, cutoff = sim.chronological_split(w.trades, cutoff_day=cfg.span_days, purge_days=0)
    t = w.trades.subset(train)
    fits = {
        spec.name: bench.fit_estimator(w, t, spec, evidence_cutoff=cutoff)
        for spec in bench.DEFAULT_ESTIMATORS + (bench.ABLATION_ESTIMATORS[2],)
    }
    return w, t, cutoff, fits


def test_latent_model_recovers_ordering_and_beats_the_prior(fitted):
    w, _t, cutoff, fits = fitted
    truth = w.assets.theta_at(cutoff)
    off = w.assets.domain == 0

    def acc(name):
        f = fits[name]
        sel = off & np.isfinite(f.theta) & (f.info["appearances"] > 0)
        return bench.pairwise_accuracy(truth[sel], f.theta[sel], min_log_gap=math.log(1.2))[0]

    assert acc("geom_huber") > 0.85
    assert acc("geom_huber") > acc("prior_only") + 0.15
    assert fits["geom_huber"].diagnostics["converged"]
    assert (
        fits["geom_huber_mgr"].diagnostics["n_params"] > fits["geom_huber"].diagnostics["n_params"]
    )


def test_unpriced_assets_are_null_with_a_reason_never_zero(fitted):
    w, t, _cutoff, fits = fitted
    f = fits["geom_huber"]
    seen = np.zeros(w.assets.n, dtype=bool)
    seen[t.side_a[t.side_a >= 0]] = True
    seen[t.side_b[t.side_b >= 0]] = True
    assert (~seen).any(), "fixture should leave some asset untraded"
    assert np.isnan(f.theta[~seen]).all()
    assert set(f.status[~seen]) == {bench.STATUS_INSUFFICIENT}
    assert set(f.reason[~seen]) == {"no_trade_evidence"}
    sup = f.status == bench.STATUS_SUPPORTED
    assert sup.any() and np.isfinite(f.theta[sup]).all()
    assert (f.info["components"][sup] >= bench.SupportThresholds().min_components).all()
    assert (f.se_contrast[sup] <= bench.SupportThresholds().max_contrast_se).all()
    # Prior share is bounded: ~1 with no evidence, small for supported assets.
    assert f.info["prior_influence"][sup].max() <= bench.SupportThresholds().max_prior_influence


def test_trade_influence_predicts_a_leave_one_out_refit(fitted):
    w, t, cutoff, fits = fitted
    f = fits["geom_huber"]
    a = int(np.flatnonzero(f.status == bench.STATUS_SUPPORTED)[0])
    infl = bench.trade_influence(f, a)
    top = int(np.argmax(np.abs(infl)))
    keep = np.arange(t.n) != top
    refit = bench.fit_latent(w, t.subset(keep), f.spec, evidence_cutoff=cutoff)
    cm = f.internals["cmat"]
    before = cm[a] @ np.nan_to_num(f.theta)
    after = cm[a] @ np.nan_to_num(refit.theta)
    moved = before - after  # effect of INCLUDING the trade
    assert np.sign(moved) == np.sign(infl[top])
    assert abs(moved - infl[top]) < 0.5 * abs(infl[top]) + 0.02
    ex = bench.worked_examples(w, f, n_assets=5)
    assert len(ex) == 5 and all(e["asset"].startswith("syn-") and e["top_trades"] for e in ex)


def test_inner_cv_chooses_from_the_grid_on_training_data_only(fitted):
    w, t, _cutoff, _fits = fitted
    grid = [{"half_life_days": 90.0}, {"half_life_days": None}]
    out = bench.select_by_inner_cv(w, t, bench.EstimatorSpec("geom_huber"), grid)
    assert out["chosen"].half_life_days in (90.0, None)
    assert len(out["scores"]) == 2


# --------------------------------------------------------------------------- #
# Power study, requirement and shortfall
# --------------------------------------------------------------------------- #


def test_required_count_interpolates_and_never_extrapolates():
    pts = [(100, 0.6), (200, 0.7), (400, 0.9), (800, 0.92)]
    req = bench.required_count(pts, 0.8)
    assert req["state"] == "reached" and 200 < req["required"] < 400
    assert bench.required_count(pts, 0.95) == {
        "state": "beyond_grid",
        "required": None,
        "max_grid": 800.0,
    }
    assert bench.required_count(pts, 0.5)["state"] == "at_or_below_grid_min"
    # Must stay above target at every larger point.
    dip = [(100, 0.85), (200, 0.7), (400, 0.9)]
    assert bench.required_count(dip, 0.8)["required"] > 200
    assert bench.required_count([(100, None), (200, 0.9)], 0.8)["required"] == 200.0


def test_shortfall_is_unknown_without_an_observed_count_never_zero():
    req = {"state": "reached", "required": 1500.0}
    assert bench.shortfall(req, None) == {"state": "unknown_observed_count", "shortfall": None}
    assert bench.shortfall(req, 400)["shortfall"] == 1100.0
    assert bench.shortfall(req, 2000)["state"] == "met"
    beyond = bench.shortfall({"state": "beyond_grid", "required": None}, 400)
    assert beyond["state"] == "beyond_grid" and beyond["shortfall"] is None


def test_maturity_signal_test_refuses_with_too_few_leagues():
    w = sim.generate_world(replace(SMALL, n_leagues=3))
    f = _fit_from(w, w.assets.theta_at(0))
    f.spec = bench.EstimatorSpec("geom_huber")
    out = bench.maturity_signal_test(w, f, w.trades, q=0.78)
    assert out["p_value"] is None
    pit = bench.maturity_signal_test(w, f, w.trades, q=0.78, reading="point_in_time")
    assert pit["p_value"] is None
    with pytest.raises(ValueError):
        bench.maturity_signal_test(w, f, w.trades, q=0.78, reading="newest")


# --------------------------------------------------------------------------- #
# Isolation and CLI
# --------------------------------------------------------------------------- #

SIM_MODULES = (
    "src/trade/market_trade_sim.py",
    "src/trade/market_trade_sim_bench.py",
    "scripts/chase_trade_market_sim.py",
)
VALUATION_PATH = (
    "src/api/data_contract.py",
    "src/api/pick_value_resolution.py",
    "src/canonical/player_valuation.py",
    "src/canonical/calibration.py",
    "src/api/confidence.py",
    "Dynasty Scraper.py",
    "server.py",
)


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out |= {f"{node.module}.{a.name}" for a in node.names}
    return out


def test_no_valuation_path_module_imports_the_simulation():
    for rel in VALUATION_PATH:
        p = REPO / rel
        if p.exists():
            assert not any("market_trade_sim" in m for m in _imports(p)), rel


def test_simulation_reads_no_store_and_imports_no_ledger_or_value_owner():
    for rel in SIM_MODULES:
        mods = _imports(REPO / rel)
        src_mods = {m for m in mods if m.startswith("src.")}
        # Only the simulation family itself: no ledger, store, network or
        # canonical-value owner is reachable from a synthetic run.
        assert all(
            m == "src.trade" or m.startswith("src.trade.market_trade_sim") for m in src_mods
        ), (rel, src_mods)
        text = (REPO / rel).read_text(encoding="utf-8")
        assert "sqlite" not in text and "data/" not in text, rel
        assert "requests" not in mods and "urllib.request" not in mods, rel


def test_cli_emits_strict_synthetic_json(tmp_path):
    env = {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "PATH": "/usr/bin:/bin"}
    out = tmp_path / "p.json"
    md = tmp_path / "p.md"
    res = subprocess.run(
        [
            sys.executable,
            "scripts/chase_trade_market_sim.py",
            "power",
            "--leagues",
            "8,12",
            "--trades-per-league",
            "8",
            "--replicates",
            "1",
            "--only",
            "prior_only,geom_huber",
            "--target",
            "pairwise_accuracy=0.5",
            "--target",
            "supported_coverage=0.1",
            "--observed-train-trades",
            "50",
            "--out",
            str(out),
            "--markdown",
            str(md),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )
    assert res.returncode == 0, res.stderr
    data = json.loads(
        out.read_text(), parse_constant=lambda c: pytest.fail(f"non-strict JSON constant {c}")
    )
    assert data["synthetic"] is True and data["observed"] == {"train_trades": 50.0}
    assert len(data["points"]) == 2
    assert data["requirements"] and all(":" in k.split("|")[1] for k in data["requirements"])
    key = next(k for k in data["requirements"] if k.startswith("geom_huber|offense:T1"))
    assert data["requirements"][key]["shortfall_trades"]["state"] in ("met", "short", "beyond_grid")
    first = data["points"][0]["train_trades_by_domain_mean"]
    assert set(first) == set(sim.DOMAINS)
    assert first["offense"] <= data["points"][0]["train_trades_mean"]
    joint = data["requirements"][
        "geom_huber|offense:T1|joint(pairwise_accuracy,supported_coverage)|tpl=8"
    ]
    assert "required_train_trades_touching_domain" in joint
    acc = data["requirements"]["geom_huber|offense:T1|pairwise_accuracy>=0.5|tpl=8"][
        "required_train_trades"
    ]
    cov = data["requirements"]["geom_huber|offense:T1|supported_coverage>=0.1|tpl=8"][
        "required_train_trades"
    ]
    if acc["required"] is not None and cov["required"] is not None:
        assert joint["required_train_trades"]["required"] == max(acc["required"], cov["required"])
    else:
        assert joint["required_train_trades"]["required"] is None
    assert "## Requirements" in md.read_text()
    comp = subprocess.run(
        [
            sys.executable,
            "scripts/chase_trade_market_sim.py",
            "components",
            "--leagues",
            "6",
            "--overlap",
            "0",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert comp.returncode == 0, comp.stderr
    assert json.loads(comp.stdout)["rows"][0]["components"] == 6


def test_config_json_takes_aggregates_and_refuses_ids_and_unknown_keys(tmp_path):
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        import chase_trade_market_sim as cli
    finally:
        sys.path.pop(0)
    good = tmp_path / "good.json"
    good.write_text(
        json.dumps(
            {"topology": [[1, 1, 0.5], [2, 1, 0.5]], "maturity_probs": [0.5, 0.5], "n_leagues": 9}
        )
    )
    over = cli.load_config_overrides(good)
    cfg = replace(sim.SimConfig(), **over)
    assert (
        cfg.topology == ((1, 1, 0.5), (2, 1, 0.5))
        and cfg.maturity_probs == (0.5, 0.5)
        and cfg.n_leagues == 9
    )
    bad = tmp_path / "bad.json"
    fake_id = "9" * 18  # built at runtime: no id-shaped literal in a public repo
    bad.write_text(json.dumps({"leagueIds": [fake_id]}))
    with pytest.raises(ValueError, match="unknown SimConfig keys"):
        cli.load_config_overrides(bad)
    sneaky = tmp_path / "sneaky.json"
    sneaky.write_text(json.dumps({"_comment": f"from league {fake_id}"}))
    with pytest.raises(ValueError, match="long numeric id"):
        cli.load_config_overrides(sneaky)
