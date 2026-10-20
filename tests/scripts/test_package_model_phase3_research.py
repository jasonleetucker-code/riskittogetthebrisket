"""Phase 3 package-model research harness (owner directive 2026-10-20).

Pins what the Phase 3 protocol rests on:

* every ELIGIBLE family member (GEOM_q, LP_p, GP_q_g) passes the mandatory
  package-model properties at full strength — the decomposition models
  (VG_q_c / VOR_c) are diagnostics, fail homogeneity, and can never be selected;
* GP_q_g reduces exactly to GEOM_q (g = 1) and LP_g (q = 1), and GEOM_078
  matches the production incumbent;
* the discovery / confirmation split is deterministic and league-disjoint, and
  trades after the freeze date are always prospective;
* the C6 elite-overcredit flag and the selection rule behave as preregistered;
* the box output is aggregates only, and the guard precedes every app import;
* the production report's reference numbers in the script are the committed
  evidence file's numbers.

Nothing here changes the active model (``geom_q078_v1``).
"""

from __future__ import annotations

import importlib.util
import json
import random
import sys
from pathlib import Path

import numpy as np
import pytest

from src.valuation_math import package_model as pm

REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / "docs" / "valuation" / "evidence" / "package_model_phase3_2026-10-20"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


P3 = _load("package_model_phase3_research")


def _gap(u):
    def g(A, B):
        return u(sorted(A, reverse=True)) - u(sorted(B, reverse=True))

    return g


def test_production_dispatch_unchanged():
    assert pm.active_model_id() == pm.GEOM_Q078_V1
    assert pm.PACKAGE_MODELS[pm.GEOM_Q078_V1]["q"] == 0.78


@pytest.mark.parametrize("name", sorted(P3.FAMILY))
def test_every_eligible_family_member_passes_the_mandatory_properties(name):
    rng = random.Random(hash(name) & 0xFFFF)
    gap = _gap(P3.FAMILY[name]["u"])
    for _ in range(250):
        A = [float(rng.randint(1, 9999)) for _ in range(rng.randint(1, 10))]
        B = [float(rng.randint(1, 9999)) for _ in range(rng.randint(1, 10))]
        g = gap(A, B)
        x = float(rng.randint(1, 9999))
        assert g - 1e-6 <= gap(A + [x], B) <= g + x + 1e-6  # adding never hurts, adds <= x
        i = rng.randrange(len(A))
        raised = A[:i] + [A[i] + x] + A[i + 1 :]
        assert gap(raised, B) >= g - 1e-6  # raising a value never hurts
        assert gap(B, A) == pytest.approx(-g, abs=1e-6)
        assert gap(A[::-1], B[::-1]) == pytest.approx(g, abs=1e-6)
        assert gap([3 * v for v in A], [3 * v for v in B]) == pytest.approx(
            3 * g, rel=1e-9, abs=1e-6
        )
        assert gap(A + [1.0], B) - g <= 1.0 + 1e-9  # a 1-point asset adds at most 1
    assert gap([7200.0], [6000.0]) == pytest.approx(1200.0)  # 1-for-1 is raw
    assert gap([7200.0], [6000.0, 1.0]) <= gap([7200.0], [6000.0]) + 1e-9


def test_decomposition_models_are_diagnostics_not_candidates():
    assert not set(P3.DECOMP) & set(P3.FAMILY)
    assert not set(P3.DIAGNOSTIC) & set(P3.FAMILY)
    gap = _gap(P3.DECOMP["VG_078_2000"]["u"])
    # c > 0 breaks homogeneity: scaling every value does not scale the gap.
    assert gap([9000.0], [5000.0, 4000.0]) * 2 != pytest.approx(gap([18000.0], [10000.0, 8000.0]))
    rng = np.random.default_rng(0)
    res = {m: rng.normal(size=40) for m in list(P3.FAMILY) + ["VG_078_2000"]}
    res["VG_078_2000"][:] = 0.0  # a perfect diagnostic must still not be selected
    recs = [{"bin": b} for b in ("1vN_small", "ordinary", "deep", "equal") * 10]
    masks = P3.bin_masks(recs, np.ones(40, bool))
    sel, table = P3.select_candidate(res, masks)
    assert sel in P3.FAMILY and all(t["model"] in P3.FAMILY for t in table)


def test_gp_reduces_to_geom_and_lp():
    vals = sorted([7000.0, 3000.0, 1500.0, 400.0], reverse=True)
    for q in (0.6, 0.78, 0.9):
        assert P3.gp_u(q, 1.0)(vals) == pytest.approx(P3.geom_u(q)(vals))
    for p in (1.2, 1.5, 2.0):
        assert P3.gp_u(1.0, p)(vals) == pytest.approx(P3.lp_u(p)(vals))


def test_geom_078_matches_the_production_incumbent():
    rng = random.Random(11)
    u = P3.FAMILY["GEOM_078"]["u"]
    gf = P3.P2.MODELS["GEOM_78"]["gap"]
    for _ in range(300):
        A = sorted((float(rng.randint(100, 9999)) for _ in range(rng.randint(1, 4))), reverse=True)
        B = sorted((float(rng.randint(100, 9999)) for _ in range(rng.randint(1, 6))), reverse=True)
        r_pure = P3.residual_from_u(u, A, B)
        r_prod = P3.P2.signed_residual(gf, A, B)
        assert r_pure == pytest.approx(r_prod, abs=2e-3)  # production rounds VA to whole points


def test_split_is_deterministic_and_league_disjoint():
    leagues = [f"lg{i}" for i in range(400)]
    first = {lg: P3.split_bucket(lg) for lg in leagues}
    assert first == {lg: P3.split_bucket(lg) for lg in leagues}
    share = sum(v == "discovery" for v in first.values()) / len(first)
    assert 0.4 < share < 0.6
    assert P3.split_bucket(None) == "noLeague"


def _row(date, league, A, B, metaA=None, metaB=None, source="ktc_trade_database"):
    return {
        "date": date,
        "league": league,
        "A": A,
        "B": B,
        "meta": [
            metaA or [["player", "WR", None]] * len(A),
            metaB or [["player", "RB", None]] * len(B),
        ],
        "source": source,
        "vft": True,
        "tep": 1,
        "idp": False,
        "boardLagDays": 1,
        "teams": 12,
    }


def test_records_orient_by_count_and_label_composition():
    rows = [
        _row("2026-10-21", "x", [3000.0, 2000.0], [6000.0]),
        _row(
            "2026-10-01",
            "y",
            [8000.0],
            [3000.0, 2500.0, 2000.0, 1500.0, 900.0],
            metaB=[["pick", None, 2027]] * 3 + [["player", "LB", None], ["player", "DB", None]],
        ),
    ]
    a, b = P3.build_records(rows)
    assert a["dA"] == [6000.0] and a["bucket"] == "prospective" and a["bin"] == "1vN_small"
    assert (
        b["bin"] == "deep"
        and b["composition"] == "mixed"
        and b["deepComposition"] == "deep_pick_dominated"
    )
    assert b["idp"] == "mixed_offense_idp" and b["idpPositions"] == ["DB", "LB"]
    assert b["levelTier"] == "4000-5999"  # mean of both sides' best asset, not one side's


def test_c6_flags_elite_overcredit_only():
    tc = {
        "8000+": {
            "binN": {"1vN_small": 80, "ordinary": 10, "deep": 60},
            "meanSigned": {
                "A": {"1vN_small": 0.08, "ordinary": 0.30, "deep": 0.0},
                "B": {"1vN_small": 0.04, "ordinary": 0.30, "deep": -0.2},
            },
        }
    }
    flags = P3.c6_flags(tc, ["A", "B"])
    assert flags["A"]["flagged"] and not flags["B"]["flagged"]  # n < 50 bins do not flag


def test_analysis_output_is_aggregate_only():
    rng = random.Random(3)
    rows = []
    for i in range(600):
        nA = 1 if i % 3 else 2
        nB = rng.choice([1, 2, 3, 5]) if nA == 1 else rng.choice([2, 3, 4])
        rows.append(
            _row(
                f"2026-10-{1 + i % 25:02d}",
                f"league-{i % 90}",
                [float(rng.randint(500, 9999)) for _ in range(nA)],
                [float(rng.randint(300, 6000)) for _ in range(nB)],
                source=rng.choice(["ktc_trade_database", "sleeper_sharp_discovery"]),
            )
        )
    out = P3.analyse(rows, [{"A": r["A"], "B": r["B"], "league": r["league"]} for r in rows[:200]])
    P3.P2.assert_aggregate_only(out)
    assert "league-1" not in json.dumps(out)
    assert out["discovery"]["S1_pooled"]["selected"] in P3.FAMILY


def test_guard_precedes_app_imports_and_bytecode_is_off():
    src = (REPO / "scripts" / "package_model_phase3_research.py").read_text(encoding="utf-8")
    guard_at = src.index("GUARD.install()")
    assert src.index("sys.dont_write_bytecode = True") < src.index("import numpy as np")
    assert guard_at < src.index("sys.path.insert(0, str(REPO))")
    assert guard_at < src.index("_spec.loader.exec_module(P2)")
    assert "import subprocess" not in src


def test_reference_numbers_are_the_committed_production_report():
    rep = json.loads((EVIDENCE / "production_ledger_run_2026-10-20.json").read_text())
    cal = rep["marketLedgerCalibration"]
    assert cal["audit"]["graded"] == P3.PHASE2_REFERENCE["graded"]
    for m in ("GEOM_78", "LP_150"):
        for b in P3.UNEQUAL_BINS:
            assert (
                cal["calibration"]["byModel"][m]["all"][b]["meanSigned"]
                == P3.PHASE2_REFERENCE[m][b]
            )
    P3.P2.assert_aggregate_only(rep)
