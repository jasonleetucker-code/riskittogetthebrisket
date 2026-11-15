"""W27-F005 TE-skew research script (scripts/research/w27_f005_te_skew.py) -- NOT ACTIVATED.

Pins the key outputs of the methodology proposal
``docs/valuation/methodology_proposals/W27_F005_TE_SKEW.md``:

* the independent restatements (gap, curve, soft knee) agree with the production owners
  they restate, and the tier / ordinal decomposition is exact, zero-sum and scale-neutral
  on synthetic boards;
* on the pinned archive + pinned tree: the archive-only measurements are exact (input
  hashes, KTC's own TE++ uplift against the curve); the build-dependent ones are pinned
  as STRUCTURAL properties (who dominates, which way a candidate moves), not as exact
  counts, so a later methodology change re-opens the proposal instead of breaking the
  suite.

Research only: nothing here touches a served path.
"""

from __future__ import annotations

import importlib.util
import math
import random
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "research" / "w27_f005_te_skew.py"
ARCHIVE = "exports/archive/dynasty_export_20261106_194518.zip"
ARCHIVE_SHA256 = "d4b196eace153ec17a2c29bff53b66568bda3264a48c09aaadac852c7ce7ced1"
TREE_REVISION = "2550b42abf36728731320bcfd78f762b7833402e"


@pytest.fixture(scope="module")
def W():
    name = "w27_f005_te_skew_research"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop(name, None)


# ── pure restatements and the decomposition (synthetic, fast) ───────────


def test_signed_gap_restates_the_market_gap_owner(W):
    from src.sources.ktc_market import compute_market_gap

    rng = random.Random(20261107)
    for _ in range(500):
        m, v = rng.uniform(1, 9999), rng.uniform(1, 9999)
        direction, ratio = compute_market_gap(v, m)
        s = W.signed_gap(m, v)
        assert math.isclose(abs(s), ratio, rel_tol=0, abs_tol=1e-12)
        assert direction == ("retail_premium" if s > 0 else "consensus_premium")
    assert W.signed_gap(None, 10.0) is None and W.signed_gap(10.0, None) is None


def test_curve_restatement_matches_the_production_curve(W):
    from src.league_intel.te_premium import tep_uplift

    curve = W.load_curve(None)
    for v in (50, 300, 480, 900, 1500, 3000, 6000, 9500):
        assert math.isclose(W.curve_uplift(v, curve), tep_uplift(v), rel_tol=1e-9)


def test_soft_knee_is_identity_below_and_bounded_above(W):
    assert W.soft_knee(9000.0) == 9000.0
    assert W.soft_knee(9900.0) == 9900.0
    assert 9900.0 < W.soft_knee(10500.0) < W.soft_knee(12000.0) < 9999.0


def _row(name, pos, model, market, rank):
    return {
        "displayName": name,
        "position": pos,
        "rankDerivedValue": model,
        "ktcMarket": {"normalizedValue": market, "value": market},
        "canonicalConsensusRank": rank,
    }


def test_decomposition_is_exact_and_zero_sum(W):
    rng = random.Random(7)
    rows = []
    for i in range(80):
        v = 9999.0 * math.exp(-i / 25.0)
        rows.append(_row(f"p{i}", "WR", v, v * rng.uniform(0.8, 1.25), i + 1))
    d = W.scale_decomposition(rows)
    assert d["maxDecompositionError"] < 1e-12
    assert abs(d["ordinalSumOverUniverse"]) < 1e-9


def test_c1_is_scale_neutral_and_c0_is_not(W):
    # The market prices every asset 10% above our board, same order: a pure tier/scale
    # difference.  C0 labels every row SELL; C1 labels none.
    rows = [
        _row(f"p{i}", "TE", 5000.0 - 40 * i, (5000.0 - 40 * i) * 1.10, i + 1) for i in range(30)
    ]
    per_row = W.scale_decomposition(rows)["_perRow"]
    assert all(
        W.signed_gap(r["ktcMarket"]["normalizedValue"], r["rankDerivedValue"]) > 0.05 for r in rows
    )
    assert all(abs(per_row[r["displayName"]]["c1"]) < 1e-12 for r in rows)
    # Swap two players' market prices: an ordinal disagreement C1 does see, both ways.
    rows[3]["ktcMarket"]["normalizedValue"], rows[20]["ktcMarket"]["normalizedValue"] = (
        rows[20]["ktcMarket"]["normalizedValue"],
        rows[3]["ktcMarket"]["normalizedValue"],
    )
    per_row = W.scale_decomposition(rows)["_perRow"]
    assert per_row["p3"]["c1"] < -0.05 and per_row["p20"]["c1"] > 0.05


# ── the pinned archive + pinned tree ────────────────────────────────────


@pytest.fixture(scope="module")
def pinned(W):
    if not (REPO / ARCHIVE).is_file():
        pytest.skip("pinned archive absent")
    try:
        subprocess.run(
            ["git", "-C", str(REPO), "cat-file", "-e", f"{TREE_REVISION}^{{commit}}"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("pinned tree revision not in this clone's history")
    return W.analyse_archive(ARCHIVE, counterfactuals=True)


def test_inputs_are_pinned_and_offline(pinned):
    inputs = pinned["inputs"]
    assert inputs["archiveSha256"] == ARCHIVE_SHA256
    assert inputs["treeRevision"] == TREE_REVISION
    assert inputs["networkAttemptsRefused"] == 0
    assert pinned["incumbentRestatementMismatches"] == 0


def test_ktc_own_te_uplift_matches_the_curve_on_the_pin(pinned):
    o = pinned["ktcUpliftOracle"]
    # KTC's base and TE++ boards are byte-identical off TE: the natural experiment holds.
    for pos, n in (("QB", 71), ("RB", 128), ("WR", 186)):
        assert o["byPosition"][pos] == {"identical": n, "medianRatio": 1.0, "n": n}
    assert o["byPosition"]["TE"]["identical"] == 0
    assert o["byPosition"]["TE"]["medianRatio"] == pytest.approx(1.3483, abs=1e-4)
    # ...and the production curve reproduces KTC's own uplift: no transformation drift.
    assert o["teMedianLogResidualActualOverCurve"] == pytest.approx(-0.0098, abs=1e-4)
    assert abs(o["teMeanLogResidualActualOverCurve"]) < 0.01


def test_incumbent_te_skew_is_reproduced(pinned):
    te = pinned["census"]["C0_incumbent_gate005"]["TE"]
    assert te["sell"] + te["buy"] >= 20
    assert te["sell"] / (te["sell"] + te["buy"]) >= 0.9


def test_tier_term_dominates_the_te_gap(pinned):
    d = pinned["decomposition"]
    assert d["maxDecompositionError"] < 1e-9
    te = d["byPosition"]["TE"]
    assert te["tierMedian"] > te["ordinalMedian"] > 0
    assert te["tierShareOfTotal"] >= 0.6
    # The same tier term drives RB and WR, which have no TE transform at all.
    assert d["byPosition"]["RB"]["tierMedian"] > 0.04
    assert d["byPosition"]["WR"]["tierMedian"] > 0.04


def test_c1_removes_most_te_labels_without_forcing_symmetry(pinned):
    c0 = pinned["census"]["C0_incumbent_gate005"]
    c1 = pinned["census"]["C1_scaleNeutral_gate005"]
    assert c1["TE"]["sell"] <= 0.6 * c0["TE"]["sell"]
    # Not symmetry: KTC still ranks tight ends above our board and quarterbacks below.
    assert c1["TE"]["sell"] > c1["TE"]["buy"]
    assert c1["QB"]["buy"] > c1["QB"]["sell"]


def test_board_te_posture_sits_between_every_other_tep_vendor_and_ktc(pinned):
    src = pinned["tePosture"]["sources"]
    board = src["__board__"]["theta"]
    assert 0.8 <= board < 0.98
    for key in ("ktcCrowdSfTep", "ktcTradesSfTep", "ktcCrowdTradesSfTep"):
        assert src[key]["theta"] >= 0.95
    for key in (
        "idpTradeCalc",
        "dynastyNerdsSfTep",
        "fantasyProsFitzmaurice",
        "yahooBoone",
        "draftSharks",
        "dlfValuesSfTep",
    ):
        assert src[key]["registryTepNative"] is True
        assert src[key]["theta"] < board


def test_c2_native_as_base_cannot_explain_the_skew(pinned):
    c2 = pinned["C2_nativeAsBase"]
    # Even at KTC's own TE posture...
    assert c2["tePosture"]["theta"] >= 0.97
    # ...the incumbent label stays overwhelmingly SELL on tight ends.
    te = c2["census_gate005"]["TE"]
    assert te["sell"] / (te["sell"] + te["buy"]) >= 0.8
    # Only TE rows and tethered current-year picks move.
    assert set(c2["valueImpacts"]["rowsChangedByPosition"]) <= {"TE", "PICK"}
    # The independent log-linear oracle tracks the production rebuild.
    assert c2["oracleVsPipelineTeValue"]["medianAbsPctError"] < 0.03
