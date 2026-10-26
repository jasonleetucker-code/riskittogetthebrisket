"""D2 follow-up — multi-snapshot named-pair dependence (``scripts/audit/lineage_pair_snapshots.py``).

Synthetic inputs only (no live board, no git history), so the arithmetic the
OTC re-measurement quotes is tested.  The two instrument findings it reports
are pinned here as properties of the arithmetic, not of today's boards:

* per-board percentiles manufacture residual agreement between two boards of
  similar DEPTH that share no opinion; the common-population rule does not;
* a curve SHAPE shared by two boards shows in ``valueResidualRaw`` and is
  removed by ``valueResidualDetrended``.
"""

from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def lps():
    path = REPO / "scripts" / "audit" / "lineage_pair_snapshots.py"
    spec = importlib.util.spec_from_file_location("lineage_pair_snapshots", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["lineage_pair_snapshots"] = module
    spec.loader.exec_module(module)
    return module


def test_partial_correlation_removes_a_shared_intermediary(lps):
    # x and y correlate only through z: r(x,y) = r(x,z) * r(y,z).
    assert lps.partial_correlation(0.42, 0.6, 0.7) == pytest.approx(0.0, abs=1e-12)
    assert lps.partial_correlation(0.5, 0.0, 0.0) == pytest.approx(0.5)
    assert lps.partial_correlation(0.5, 1.0, 0.3) is None


def test_cubic_detrend_removes_any_cubic_in_the_consensus(lps):
    xs = [i / 10 for i in range(50)]
    resid = [0.3 * x**3 - x + 2 for x in xs]
    assert max(abs(r) for r in lps.cubic_detrend(resid, xs)) < 1e-6


def test_log_values_are_scale_free_and_skip_non_positive(lps):
    sweep = lps.sweep
    lines = ["name,value"] + [f"P{i},{1000 - 10 * i}" for i in range(40)] + ["Zero,0"]
    board = sweep.parse_board("x", "\n".join(lines) + "\n")
    idents = list(board.entries)
    lv = lps.log_values(board, idents)
    assert max(lv.values()) == pytest.approx(0.0)
    assert "zero" not in {k.lower() for k in lv}
    assert len(lv) == 40


def test_lfo_drops_the_members_families_and_providers(lps):
    pool = ["ktcCrowdSfTep", "ktcTradesSfTep", "fantasyNavigatorSf", "dlfSf", "otcffbSf"]
    groups = {"ktcCrowdSfTep": "ktcCrowd", "fantasyNavigatorSf": "ktcCrowd", "ktc": "ktcCrowd"}
    providers = {
        "ktc": "keepTradeCut",
        "ktcCrowdSfTep": "keepTradeCut",
        "ktcTradesSfTep": "keepTradeCut",
        "fantasyNavigatorSf": "fantasyNavigator",
        "dlfSf": "dynastyLeagueFootball",
        "otcffbSf": "otcFantasyFootball",
    }
    assert lps.lfo_others(pool, ("otcffbSf", "ktc"), groups, providers) == ["dlfSf"]


def test_common_population_is_shared_by_every_included_board(lps):
    orders = {
        "a": {f"p{i}": i for i in range(100)},
        "b": {f"p{i}": i for i in range(80)},
        "c": {f"p{i}": i for i in range(60)},  # covers 75% of a∩b -> included
        "d": {f"p{i}": i for i in range(20)},  # 25% -> excluded
    }
    incl, pop = lps.common_population(orders, ("a", "b"), ["c", "d"], min_cover=0.6)
    assert incl == ["c"]
    assert set(pop) == {f"p{i}" for i in range(60)}
    pct, _ = lps.restrict(orders, {}, ["a", "b", "c"], pop)
    assert all(len(p) == 60 and max(p.values()) == 1.0 for p in pct.values())


def _random_boards(seed, deep, shallow, n_cons=6, n_players=500, noise=0.15):
    """Independent noisy views of one truth; ``deep`` boards list n_players,
    the consensus boards list only the top ``shallow``."""
    rng = random.Random(seed)
    truth = {f"p{i}": i / n_players for i in range(n_players)}

    def view(depth):
        scores = {n: t + rng.gauss(0, noise * (0.05 + t)) for n, t in truth.items()}
        top = sorted(scores, key=scores.get)[:depth]
        return {n: scores[n] for n in top}

    orders = {"a": view(deep), "b": view(deep)}
    for k in range(n_cons):
        orders[f"c{k}"] = view(shallow)
    return orders


def test_per_board_percentiles_manufacture_agreement_between_equally_deep_boards(lps):
    """The depth artifact: a and b share NO opinion (independent noise), but
    both list 450 players while every consensus board lists 320, so on the
    sweep's per-board percentiles their residuals agree.  Re-ranking every
    board inside the common population leaves only the leave-pair-out
    baseline: two residuals against one consensus share its error, about
    1 / (k + 1) for k equally noisy consensus boards (1/7 here)."""
    sweep = lps.sweep
    lpo, cp = [], []
    for seed in range(8):
        orders = _random_boards(seed, deep=450, shallow=320)
        others = [k for k in orders if k.startswith("c")]
        pct = {k: sweep.to_percentiles(o) for k, o in orders.items()}
        r, _ = sweep.leave_pair_out_residuals(pct, "a", "b", others)
        lpo.append(r)
        incl, pop = lps.common_population(orders, ("a", "b"), others)
        cpct, _ = lps.restrict(orders, {}, ["a", "b", *incl], pop)
        r2, _ = sweep.leave_pair_out_residuals(cpct, "a", "b", incl, len(incl))
        cp.append(r2)
    mean_lpo, mean_cp = sum(lpo) / len(lpo), sum(cp) / len(cp)
    assert mean_lpo > 0.4
    assert mean_cp < 0.2
    assert mean_lpo - mean_cp > 0.25


def test_shared_curve_shape_shows_raw_and_vanishes_detrended(lps):
    """Two boards with the same steep curve and independent player noise:
    raw log-value residuals correlate (shape), detrended ones keep only the
    ~1 / (k + 1) shared-consensus baseline (k = 12 here)."""
    rng = random.Random(7)
    names = [f"p{i}" for i in range(300)]
    base = {n: -i / 60 for i, n in enumerate(names)}
    cons = [f"c{k}" for k in range(12)]
    logv = {}
    for k, steep in [("a", 1.6), ("b", 1.6)] + [(c, 1.0) for c in cons]:
        logv[k] = {n: steep * base[n] + rng.gauss(0, 0.15) for n in names}
    out = lps.pair_value_dependence(logv, "a", "b", cons)
    assert out["valueResidualRaw"] > 0.8
    assert abs(out["valueResidualDetrended"]) < 0.2
    assert out["nValue"] == 300


def test_summarize_reports_distribution_not_a_single_day(lps):
    s = lps.summarize([0.1, None, 0.5, -0.2])
    assert s == {
        "nSnapshots": 3,
        "median": 0.1,
        "min": -0.2,
        "max": 0.5,
        "positiveShare": 0.667,
    }
    assert lps.summarize([None])["nSnapshots"] == 0


def test_snapshot_instants_end_on_the_requested_day(lps):
    from datetime import datetime, timezone

    start = datetime(2026, 9, 1, 23, 59, 59, tzinfo=timezone.utc)
    end = datetime(2026, 9, 17, 23, 59, 59, tzinfo=timezone.utc)
    got = lps.snapshot_instants(start, end, 7)
    assert [t.day for t in got] == [1, 8, 15, 17]
