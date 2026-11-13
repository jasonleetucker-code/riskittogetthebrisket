"""Deterministic tests for the package-model validation study (Priority 16, research only).

Script: ``scripts/research/package_model_validation.py``.  Plan:
``docs/valuation/evidence/package_model_validation_2026-11-13/PREREGISTRATION.md``.

Hand-computed utilities and residuals for small packages, the band owner reached
through ``fairness_base`` (never a ``max(...)`` of adjusted sides), date folds
that never split a date, recovery of a known q, the two-way bootstrap, the
missing-is-never-zero pricing rule, the own-league label adapter, and the
aggregate-only output guard.  No network, no live board.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "research" / "package_model_validation.py"


def _load():
    name = "package_model_validation"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pmv = _load()


def _row(a, b, *, d="2026-09-01", cluster="L1", kinds=None):
    def side(vals, ks):
        return [
            {"v": float(v), "kind": k, "pos": None if k == "pick" else "WR"}
            for v, k in zip(vals, ks)
        ]

    ka = (kinds or {}).get("a") or ["player"] * len(a)
    kb = (kinds or {}).get("b") or ["player"] * len(b)
    return {"date": d, "cluster": cluster, "sides": [side(a, ka), side(b, kb)]}


# ── Hand-computed utilities and residuals ────────────────────────────────


def test_incumbent_q_is_read_from_the_owner_and_is_078():
    assert pmv.Q_INCUMBENT == 0.78
    assert pmv.Q_GRID[0] == 0.30 and pmv.Q_GRID[-1] == 1.00 and len(pmv.Q_GRID) == 71
    assert 0.78 in pmv.Q_GRID


def test_utility_by_hand():
    # 5000 + 0.78 * 3000 = 7340; 6000 + 0.78 * 4000 + 0.78^2 * 1000 = 9728.4
    assert pmv.utility([5000, 3000], 0.78) == pytest.approx(7340.0)
    assert pmv.utility([1000, 6000, 4000], 0.78) == pytest.approx(9728.4)
    assert pmv.utility([5000, 3000], 1.0) == pytest.approx(8000.0)


def test_residual_by_hand_one_for_two():
    # A = [6000] (fewer pieces), B = [4000, 3000].
    # q = 0.78: U_A 6000, U_B 6340, g = -340; den = (6000 + 7000 + |-1000 + 340|) / 2 = 6830.
    r078 = pmv.residual(6000, 6340, 6000, 7000)
    assert r078 == pytest.approx(-340 / 6830)
    # q = 1: g = -1000, the raw gap; den = 6500.
    assert pmv.residual(6000, 7000, 6000, 7000) == pytest.approx(-1000 / 6500)
    rec = pmv.build_record(_row([4000, 3000], [6000]))
    assert rec["vA"] == [6000.0] and rec["vB"] == [4000.0, 3000.0]
    grid = pmv.residual_grid([rec], pmv.Q_GRID)
    assert grid[0, pmv.Q_GRID.index(0.78)] == pytest.approx(-340 / 6830)
    assert grid[0, pmv.Q_GRID.index(1.0)] == pytest.approx(-1000 / 6500)


def test_one_for_one_residual_does_not_depend_on_q():
    rec = pmv.build_record(_row([5000], [4000]))
    grid = pmv.residual_grid([rec], pmv.Q_GRID)
    assert np.allclose(grid[0], grid[0, 0])
    assert grid[0, 0] == pytest.approx(1000 / 4500)


def test_level_diagnostic_by_hand():
    # c = 2000: A [6000] -> 4000; B [4000, 3000] -> 2000 + 0.78 * 1000 = 2780.
    # g = 1220 on raw sums 6000 / 7000: den = (13000 + |-1000 - 1220|) / 2 = 7610.
    rec = pmv.build_record(_row([6000], [4000, 3000]))
    grid = pmv.residual_grid([rec], [0.78], level_c=2000.0)
    assert grid[0, 0] == pytest.approx(1220 / 7610)


def test_vectorized_utilities_match_the_owner_and_the_adjusted_gap():
    rows = pmv.synthetic_rows(60, true_q=0.7, sigma=0.2, seed=5)
    recs = [pmv.build_record(r) for r in rows]
    out = pmv.parity_check(recs)
    assert out["ok"] and out["rows"] == 60 and out["maxUtilityDiff"] < 1e-6


# ── Strata ───────────────────────────────────────────────────────────────


def test_shape_is_stud_side_first():
    assert pmv.build_record(_row([6000], [4000, 3000]))["shape"] == "1v2"
    # The stud (7000) sits on the two-piece side: stud plus one for one.
    assert pmv.build_record(_row([7000, 500], [5000]))["shape"] == "2v1"
    assert pmv.build_record(_row([5000], [4000]))["shape"] == "1v1"
    assert pmv.build_record(_row([5000, 100], [4000, 900]))["shape"] == "2v2"
    assert pmv.build_record(_row([9000], [3000, 2000, 1000]))["shape"] == "3+"


def test_phase3_bins_match_the_recorded_definition():
    assert pmv.phase3_bin(1, 2) == "1vN_small" and pmv.phase3_bin(1, 3) == "1vN_small"
    assert pmv.phase3_bin(2, 3) == "ordinary" and pmv.phase3_bin(1, 4) == "ordinary"
    assert pmv.phase3_bin(2, 5) == "deep" and pmv.phase3_bin(3, 3) == "equal"


def test_asset_class_and_tier():
    rec = pmv.build_record(_row([6000], [4000, 3000], kinds={"b": ["player", "pick"]}))
    assert rec["assetClass"] == "includes_picks_no_idp"
    idp = _row([6000], [4000])
    idp["sides"][1][0]["pos"] = "LB"
    assert pmv.build_record(idp)["assetClass"] == "includes_idp"
    assert pmv.build_record(_row([6000], [4000]))["assetClass"] == "offense_players_only"
    assert pmv.build_record(_row([6000], [4000]))["tier"] == "4000-5999"  # (6000 + 4000) / 2
    assert pmv.value_tier(1999.0) == "<2000" and pmv.value_tier(8000.0) == "8000+"


# ── Folds, fitting and the bootstrap ─────────────────────────────────────


def test_date_blocks_never_split_a_date_and_are_ordered():
    dates = sorted(
        [f"2026-09-{d:02d}" for d in range(1, 11) for _ in range(3)] + ["2026-09-05"] * 7
    )
    blocks = pmv.date_blocks(dates, k=5)
    by_date = {}
    for d, b in zip(dates, blocks):
        by_date.setdefault(d, set()).add(int(b))
    assert all(len(v) == 1 for v in by_date.values())
    assert list(blocks) == sorted(blocks)
    assert set(blocks) == {0, 1, 2, 3, 4}


def test_fit_recovers_a_known_q_without_noise():
    rows = pmv.synthetic_rows(400, true_q=0.66, sigma=0.0, seed=11)
    recs = [pmv.build_record(r) for r in rows]
    res = pmv.residual_grid(recs, pmv.Q_GRID)
    unequal = np.array([r["unequal"] for r in recs])
    assert pmv.Q_GRID[pmv.fit_index(res, unequal)] == 0.66
    assert pmv.Q_GRID[pmv.fit_index(res, unequal, moment=True)] == 0.66


def test_bootstrap_weights_are_products_of_league_and_date_draws():
    boot = pmv.TwoWayBoot(["a", "a", "b", None], ["d1", "d2", "d1", "d2"], reps=50, seed=3)
    assert boot.n_leagues == 3 and boot.n_dates == 2
    assert np.all(boot.ml.sum(axis=1) == 3) and np.all(boot.md.sum(axis=1) == 2)
    _s, _e, w = next(boot._chunks())
    assert np.allclose(w[0], boot.ml[0][boot.li] * boot.md[0][boot.di])
    x = np.array([1.0, 2.0, 3.0, 4.0])
    reps = boot.means([(x, np.ones(4, dtype=bool))])
    assert reps.shape == (50, 1)
    lo, hi = pmv.ci95(reps[:, 0])
    assert lo <= x.mean() <= hi
    again = pmv.TwoWayBoot(["a", "a", "b", None], ["d1", "d2", "d1", "d2"], reps=50, seed=3)
    assert np.array_equal(again.means([(x, np.ones(4, dtype=bool))]), reps, equal_nan=True)


def test_league_only_bootstrap_ignores_dates():
    boot = pmv.TwoWayBoot(["a", "b"], ["d1", "d2"], reps=10, seed=1, by_date=False)
    assert np.all(boot.md == 1.0)


def test_evaluate_end_to_end_on_synthetic_trades():
    rows = pmv.synthetic_rows(600, true_q=0.70, sigma=0.05, seed=21, leagues=40, days=60)
    recs = [pmv.build_record(r) for r in rows]
    out = pmv.evaluate(recs, boot_reps=60, qhat_reps=40)
    ev = out["outOfSample"]
    assert len(out["folds"]) == pmv.K_BLOCKS - 1
    assert all(f["scored"] for f in out["folds"])
    assert abs(out["qFit"]["qHat"] - 0.70) <= 0.03
    assert out["qFit"]["ci95"][0] <= out["qFit"]["qHat"] <= out["qFit"]["ci95"][1]
    # True q = 0.70: the fitted model beats both fixed q values out of sample.
    assert ev["mseMFIT"]["value"] < ev["mseM078"]["value"] < ev["mseM100"]["value"]
    assert ev["diffM078minusMFIT"]["ci95"][0] > 0
    assert out["rules"]["R1_078_vs_fitted"] == "favours_alternative"
    assert out["rules"]["D1_momentQ_vs_078"] == "interval_below"
    assert set(out["outOfSample"]["J"]) == {"M078", "MFIT", "M100", "MMOM"}
    # 600 trades in 40 leagues cannot meet R0.
    assert out["sufficiency"]["decisive"] is False
    assert set(out["residualTables"]["shape"]) == set(pmv.SHAPES)
    pmv.assert_aggregate_only(out)
    json.dumps(out)  # native types only: no numpy scalar reaches the output


# ── Fairness bands through the owner ─────────────────────────────────────


def test_band_levels_use_the_owner_by_hand():
    # A [6000] vs B [4000, 3000].  q = 0.78: |g| 340 >= 250, base max(U) = 6340,
    # 5.36 % -> slight, against the consolidating side.  q = 1: 1000 / 7000 =
    # 14.3 % -> unfair.  A 1-for-1 within the 250 floor is fair at any q.
    recs = [pmv.build_record(_row([6000], [4000, 3000])), pmv.build_record(_row([5000], [4900]))]
    lv, against = pmv.band_levels(recs, 0.78)
    assert lv == ["slight", "fair"] and against.tolist() == [True, False]
    lv1, _ = pmv.band_levels(recs, 1.0)
    assert lv1 == ["unfair", "fair"]


def test_band_evaluation_reports_excess_over_1v1():
    rows = pmv.synthetic_rows(300, true_q=0.78, sigma=0.1, seed=4, leagues=30, days=30)
    recs = [pmv.build_record(r) for r in rows]
    boot = pmv.TwoWayBoot([r["cluster"] for r in recs], [r["date"] for r in recs], reps=40, seed=2)
    out = pmv.band_evaluation(recs, boot, {"0.78": 0.78, "qHat": 0.6, "1.00": 1.0})
    t = out["byQ"]["0.78"]["table"]["shape"]["1v2"]
    assert sum(t["levels"].values()) == t["n"]
    assert "1v2" in out["byQ"]["0.78"]["excessOver1v1"]
    assert out["stabilityVs078"]["1.00"]["1v1"] == 0.0  # a 1-for-1 never depends on q
    assert out["bands"]["version"] == "fairness_bands_v2"
    json.dumps(out)


def test_the_script_never_passes_the_band_owner_a_max_base():
    detector_path = REPO / "tests" / "valuation_math" / "test_fairness_bands.py"
    spec = importlib.util.spec_from_file_location("_fb_detector_pmv", detector_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert not mod._py_offenders(SCRIPT.read_text(encoding="utf-8"), SCRIPT.name)
    text = SCRIPT.read_text(encoding="utf-8")
    for legacy in (
        "package_model_hybrid_research",
        "package_model_phase2_research",
        "level_v1_legacy",
    ):
        assert legacy not in text


# ── Pricing: point in time, all or nothing ───────────────────────────────


class _FakeBoard:
    def __init__(self, values):
        self._v = values

    def values(self, asset):
        v = self._v.get(asset.get("canonicalId"))
        return {} if v is None else {"canonical": v}


def _group(sides, d="2026-09-10"):
    return {
        "occurredDate": d,
        "sides": sides,
        "dedupeState": "CONFIRMED_UNIQUE",
        "marketFormat": {"general": {"dynastyState": "dynasty"}, "offense": {"superflex": True}},
        "hostLeagueId": "999",
        "sourceFamilies": ["test"],
    }


def _p(pid):
    return {"kind": "player", "canonicalId": f"player:{pid}", "position": "WR"}


def test_pricing_is_strictly_before_the_trade_and_all_or_nothing():
    boards = [
        (date(2026, 9, 1), "b1", "i1"),
        (date(2026, 9, 9), "b2", "i2"),
        (date(2026, 9, 10), "b3", "i3"),
    ]
    loaded = []

    def load(path, inner):
        loaded.append(path)
        return _FakeBoard({"player:1": 5000.0, "player:2": 3000.0, "player:3": 2500.0})

    groups = [
        _group([[_p(1)], [_p(2), _p(3)]]),  # priced on b2 (9/9), never b3 (same day)
        _group([[_p(1)], [_p(2), _p(4)]]),  # player 4 unpriced: excluded, never 0
        _group([[_p(1)], [_p(2)]], d="2026-08-20"),  # no board within 7 days before
    ]
    rows, audit = pmv.price_groups(groups, boards, load_board=load)
    assert loaded == ["b2"]
    assert len(rows) == 1 and rows[0]["date"] == "2026-09-10"
    assert [p["v"] for p in rows[0]["sides"][1]] == [3000.0, 2500.0]
    assert audit["excluded"] == {
        "asset_unpriced_on_point_in_time_board": 1,
        "no_board_strictly_before_within_lag": 1,
    }
    assert rows[0]["cluster"] != "999" and len(rows[0]["cluster"]) == 16


def test_ledger_eligibility_is_the_owners():
    boards = [(date(2026, 9, 9), "b2", "i2")]
    g = _group([[_p(1)], [_p(2)]])
    g["marketFormat"]["offense"]["superflex"] = None  # unknown fails closed
    rows, audit = pmv.price_groups([g], boards, load_board=lambda *_: _FakeBoard({}))
    assert rows == [] and audit["excluded"] == {"board_basis_superflex_mismatch_or_unknown": 1}


# ── Own-league adapter ───────────────────────────────────────────────────


def test_own_league_labels():
    ids, pos = {"Kyle Pitts": "1234"}, {"Kyle Pitts": "TE"}
    a, down = pmv.own_league_asset("2027 Mid 2nd (from Kich)", ids, pos)
    assert a["canonicalId"] == "mpick:2027:r2" and down is True  # baked "Mid" -> generic grade
    a, down = pmv.own_league_asset("2027 Pick 1.06", ids, pos)
    assert a["canonicalId"] == "mpick:2027:r1:s6" and down is False
    a, _ = pmv.own_league_asset("Kyle Pitts", ids, pos)
    assert a == {"kind": "player", "canonicalId": "player:1234", "position": "TE"}
    assert pmv.own_league_asset("Somebody Unknown", ids, pos)[0]["kind"] == "unresolved"
    assert pmv.own_league_asset("$5 FAAB", ids, pos)[0]["kind"] == "faab"


def test_own_league_groups_from_a_snapshot(tmp_path):
    snap = {
        "rosterData": {
            "leagueId": "L-now",
            "leagueSettings": {"type": 2},
            "rosterPositions": ["QB", "SUPER_FLEX"],
            "playerIds": {"A": "1", "B": "2"},
            "positions": {"A": "WR", "B": "LB"},
            "trades": [
                {
                    "leagueId": "L-now",
                    "timestamp": 1788000000000,
                    "sides": [{"got": ["A"]}, {"got": ["B", "2028 Round 3"]}],
                },
                {
                    "leagueId": "L-old",
                    "timestamp": 1760000000000,
                    "sides": [{"got": ["A"]}, {"got": ["B"]}],
                },
            ],
        }
    }
    p = tmp_path / "snap.json"
    p.write_text(json.dumps(snap), encoding="utf-8")
    groups, audit = pmv.own_league_groups(p)
    assert len(groups) == 1 and audit["format"] == {"dynasty": True, "superflex": True}
    assert audit["excludedBeforePricing"] == {"other_season_league_format_not_the_snapshots": 1}
    assert groups[0]["sides"][1][1]["canonicalId"] == "mpick:2028:r3"


# ── Output safety ────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad", ["player:4881", "mpick:2027:r1", "1312006700437352448", "a@b"])
def test_aggregate_guard_refuses_identifiers(bad):
    with pytest.raises(ValueError):
        pmv.assert_aggregate_only({"x": [bad]})


def test_aggregate_guard_accepts_a_commit_sha_and_dates():
    pmv.assert_aggregate_only(
        {"codeSha": "a" * 40, "dateRange": ["2026-07-01", "2026-11-13"], "n": 5}
    )


def test_write_rows_refuses_the_repository(tmp_path):
    with pytest.raises(SystemExit):
        pmv.write_rows([], REPO / "rows.jsonl")
    out = tmp_path / "rows.jsonl"
    pmv.write_rows([_row([1.0], [2.0])], out)
    assert pmv.read_rows(out)[0]["sides"][0][0]["v"] == 1.0


def test_read_rows_refuses_a_missing_value(tmp_path):
    p = tmp_path / "rows.jsonl"
    p.write_text(
        json.dumps({"date": "2026-09-01", "sides": [[{"v": None}], [{"v": 3.0}]]}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        pmv.read_rows(p)


def test_cli_on_a_rows_file_writes_aggregate_json(tmp_path):
    rows = pmv.synthetic_rows(300, true_q=0.78, sigma=0.1, seed=8, leagues=30, days=40)
    src = tmp_path / "rows.jsonl"
    pmv.write_rows(rows, src, audit={"graded": 300, "dataLabel": "SYNTHETIC test rows"})
    out = tmp_path / "out.json"
    code = pmv.main(
        ["--rows", str(src), "--out", str(out), "--boot-reps", "40", "--qhat-boot-reps", "30"]
    )
    assert code == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["data"] == "SYNTHETIC test rows" and doc["audit"]["graded"] == 300
    assert doc["evaluation"]["n"] == 300 and doc["evaluation"]["parity"]["ok"] is True
    assert doc["packageModel"]["id"] == "geom_q078_v1"


def test_an_exported_ledger_copy_must_exist(tmp_path):
    with pytest.raises(SystemExit):
        pmv.open_ledger_copy(tmp_path / "missing.sqlite")


# ── Estimator behaviour on synthetic trades with a known q ───────────────


def test_noise_placements_clear_exactly_without_noise():
    for noise in ("symmetric", "b_side"):
        rows = pmv.synthetic_rows(50, true_q=0.78, sigma=0.0, seed=2, noise=noise)
        recs = [pmv.build_record(r) for r in rows]
        res = pmv.residual_grid(recs, [0.78])
        assert np.allclose(res[:, 0], 0.0, atol=1e-12)
    with pytest.raises(ValueError):
        pmv.synthetic_rows(1, true_q=0.78, sigma=0.1, seed=1, noise="other")


def test_mse_fit_is_pulled_below_the_true_q_by_noise_and_the_moment_fit_is_not():
    # Pinned because the results document relies on it (deviation D1): with
    # clearing noise the r**2 criterion prefers a lower q (it shrinks the noisy
    # multi-piece side), while the mean-zero criterion stays near the truth.
    rows = pmv.synthetic_rows(3000, true_q=0.78, sigma=0.25, seed=99, noise="symmetric")
    recs = [pmv.build_record(r) for r in rows]
    res = pmv.residual_grid(recs, pmv.Q_GRID)
    unequal = np.array([r["unequal"] for r in recs])
    q_mse = pmv.Q_GRID[pmv.fit_index(res, unequal)]
    q_mom = pmv.Q_GRID[pmv.fit_index(res, unequal, moment=True)]
    assert q_mse <= 0.72
    assert abs(q_mom - 0.78) <= 0.04


def test_bootstrap_moment_argmin_matches_the_point_fit_on_unit_weights():
    rows = pmv.synthetic_rows(200, true_q=0.7, sigma=0.0, seed=3)
    recs = [pmv.build_record(r) for r in rows]
    res = pmv.residual_grid(recs, pmv.Q_GRID)
    unequal = np.array([r["unequal"] for r in recs])
    boot = pmv.TwoWayBoot([None] * len(recs), ["d"] * len(recs), reps=25, seed=4, by_date=False)
    assert {pmv.Q_GRID[i] for i in boot.argmin(res, unequal, moment=True)} == {0.7}
    assert {pmv.Q_GRID[i] for i in boot.argmin(res, unequal)} == {0.7}
