"""W30-F008 research script (scripts/research/w30_f008_hill_denominator.py) -- NOT ACTIVATED.

Pins the key outputs of
``docs/valuation/methodology_proposals/W30_F008_HILL_DENOMINATOR.md``:

* the independent oracle agrees with the production coordinate + curve at every
  edge rank (rank 1, fractional, the 500 boundary, 501..904, past saturation);
* the v2 fit procedure, re-implemented and fed the exact v2 inputs (carried in
  the evidence JSON so this runs on a shallow CI checkout), reproduces registry
  v2 in the native coordinate and yields C0 in the canonical one;
* on the pinned archive: structural properties of the C0 rebuild (who moves,
  which votes the outlier filter drops, which picks move), not exact counts.

Research only: nothing here touches a served path, and the in-process curve
swap is verified to restore the production constants.
"""

from __future__ import annotations

import importlib.util
import json
import math
import random
import sys
from fractions import Fraction
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "research" / "w30_f008_hill_denominator.py"
EVIDENCE = (
    REPO
    / "docs"
    / "valuation"
    / "methodology_proposals"
    / "evidence"
    / "w30_f008_hill_denominator.json"
)
ARCHIVE = "dynasty_export_20261107_063955.zip"
ARCHIVE_SHA256 = "f1ad8517f83008d44c7de1a942626115798d12a4ebdd629887b9ae225157fb60"


@pytest.fixture(scope="module")
def W():
    name = "w30_f008_hill_denominator_research"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop(name, None)


@pytest.fixture(scope="module")
def evidence():
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


# ── the oracle (pure, fast) ────────────────────────────────────────────────


def test_oracle_coordinate_edges(W):
    p = W.oracle_percentile
    assert p(1) == 0 and p(0.5) == 0  # rank 1 anchors; a sub-1 rank clamps to 0
    assert p(500) == 1  # the unit boundary is NOT a clamp any more
    assert p(501) == Fraction(500, 499) > 1
    assert p(904) == Fraction(903, 499)  # the tail ceiling
    assert p(905) == p(904) == p(10**6)  # saturation


def test_oracle_matches_production_coordinate_and_curve(W):
    from src.canonical import player_valuation as pv

    rng = random.Random(20261107)
    curves = [
        (0.11, 1.11),
        (0.112, 0.725),
        (0.083, 1.11),
        (0.077, 1.11),
        (0.088, 0.72),
        (0.024, 1.15),
    ]
    ranks = [1, 1.5, 2, 50, 100, 499, 500, 501, 903, 904, 905, 2000] + [
        rng.uniform(1, 1200) for _ in range(40)
    ]
    for c, s in curves:
        for r in ranks:
            pe = W.oracle_percentile(r)
            assert math.isclose(
                float(pe), pv.rank_to_percentile(float(r)), rel_tol=0, abs_tol=1e-15
            )
            assert W.oracle_int(W.oracle_value(pe, c, s)) == pv.percentile_to_value(
                pv.rank_to_percentile(float(r)), midpoint=c, slope=s
            )


def test_rank_form_identity_is_the_unit_statement(W):
    # V(p; c) at N=500 equals the rank-form Hill with M = c (N - 1): N is a unit.
    for c, s in ((0.11, 1.11), (0.077, 1.11)):
        for r in (2, 25, 100, 400, 904):
            assert (
                abs(W.oracle_rank_form(r, c, s) - W.oracle_value(W.oracle_percentile(r), c, s))
                < 1e-40
            )


def test_holdout_scorer_restates_the_production_rmse(W):
    from src.model_registry import holdout as h

    rng = random.Random(7)
    values = sorted((rng.uniform(50, 10000) for _ in range(420)), reverse=True)
    for c, s in ((0.11, 1.11), (0.077, 1.11)):
        prod = h._rmse(h._percentile_pairs(values), c, s)
        assert math.isclose(W.holdout_rmse(values, c, s), prod, rel_tol=1e-9)


# ── the reproduction (from the evidence fixture; no git history needed) ─────


def test_v2_procedure_reproduces_the_champion_and_yields_c0(W, evidence):
    inputs = evidence["v2Inputs"]
    assert inputs["revFull"].startswith("3df9cc4")
    assert inputs["idptcIdpSliceRows"] == 0  # v2's IDP master was DraftSharks-IDP alone
    repro = W.reproduction_section(inputs)
    assert repro["reproducesRegistryV2"] is True
    nat, can = repro["native"]["masters"], repro["canonical"]["masters"]
    assert (nat["OFFENSE"]["c"], nat["OFFENSE"]["s"]) == (0.11, 1.11)
    assert (nat["GLOBAL"]["c"], nat["GLOBAL"]["s"]) == (0.112, 0.725)
    assert (nat["IDP"]["c"], nat["IDP"]["s"]) == (0.083, 1.11)
    assert (can["OFFENSE"]["c"], can["OFFENSE"]["s"]) == (0.077, 1.11)
    assert (can["GLOBAL"]["c"], can["GLOBAL"]["s"]) == (0.088, 0.72)
    assert (can["IDP"]["c"], can["IDP"]["s"]) == (0.024, 1.15)
    # Per source the correction IS the unit transform c * (n - 1) / 499, to the grid step.
    assert all(u["absErr"] <= 0.001 for u in repro["perSourceUnitTransform"].values())
    vd = repro["valueDirectScale"]
    assert vd["OFFENSE"] == [0.115, 0.945] and vd["GLOBAL"] == [0.149, 0.78]


def test_fixture_vectors_match_the_git_blobs_when_history_is_present(W, evidence):
    rev = evidence["v2Inputs"]["rev"]
    if not W.git_available(rev):
        pytest.skip(f"revision {rev} not in this (shallow) checkout")
    fresh = W.extract_v2_inputs(rev)
    assert fresh["blobs"] == evidence["v2Inputs"]["blobs"]
    assert fresh["values"] == evidence["v2Inputs"]["values"]


# ── the pinned board (structural, not exact counts) ───────────────────────


def test_c0_rebuild_structure_on_the_pinned_archive(W):
    path = REPO / "exports" / "archive" / ARCHIVE
    if not path.is_file():
        pytest.skip(f"{ARCHIVE} not in this checkout")
    from src.canonical import player_valuation as pv
    from src.canonical import rank_coordinates as rc

    before = dict(rc._CURVE_BY_POOL)
    payload, sha = W.load_archive_payload(ARCHIVE)
    assert sha == ARCHIVE_SHA256
    inc = {sc: W.V2_PARAMS[sc] for sc in W.SCOPES}
    c0 = {"OFFENSE": (0.077, 1.11), "GLOBAL": (0.088, 0.72), "IDP": (0.024, 1.15)}
    base = W.build_board(payload, inc)
    cand = W.build_board(payload, c0)
    # the in-process swap restored production exactly
    assert rc._CURVE_BY_POOL == before
    assert (pv.HILL_PERCENTILE_C, pv.HILL_PERCENTILE_S) == W.V2_PARAMS["OFFENSE"]

    # no served rank-Hill vote lands in the IDP pool: the IDP master prices nothing
    pools = {
        m.get("rankCoordinatePool")
        for r in base["playersArray"]
        for m in (r.get("sourceRankMeta") or {}).values()
        if m.get("valueContributionPath") == "rank_hill"
    }
    assert "idp" not in pools and {"offense", "shared_market"} <= pools

    d = W.board_diff(base, cand, {})
    assert d["rowsFalling"] > 0.8 * d["comparableRows"]
    # C0 lowers every rank-Hill vote and the blend is monotone in its votes, so a
    # row can only RISE when the outlier filter kept a different set of votes.
    # "rowsRising == 0" was not an invariant: this rebuild reads today's CSVs and
    # dataset state, and on 2026-11-08 a data refresh produced one such row
    # (LaJohntay Wester: a vote the filter dropped under v2 was kept under C0).
    # Override rows are excluded: a tethered pick and a two-way boost replace the
    # blend with a value from another population, so its filter set says nothing.
    base_rows = {r["displayName"]: r for r in base["playersArray"]}
    risers = [
        (name, base_rows[name], row)
        for name, row in ((r["displayName"], r) for r in cand["playersArray"])
        if name in base_rows
        and base_rows[name].get("rankDerivedValue")
        and (row.get("rankDerivedValue") or 0) > base_rows[name]["rankDerivedValue"]
        and row.get("assetClass") != "pick"
        and not row.get("twoWayPlayerBoost")
    ]
    for name, b_row, c_row in risers:
        assert set(b_row.get("droppedSources") or []) != set(
            c_row.get("droppedSources") or []
        ), f"{name} rose under a lower curve with an unchanged outlier-filter set"
    # among picks only the rookie-tethered slotted class moves; vendor classes do not
    b = {r["displayName"]: r for r in base["playersArray"] if r.get("assetClass") == "pick"}
    c = {r["displayName"]: r for r in cand["playersArray"] if r.get("assetClass") == "pick"}
    moved = [n for n in b if b[n].get("rankDerivedValue") != c[n].get("rankDerivedValue")]
    assert moved and all(
        (b[n].get("pickValueProvenance") or {}).get("class") == "rookie_pool_tether" for n in moved
    )


@pytest.mark.livedata
def test_c0_magnitudes_on_todays_csvs(W):
    """Research magnitudes, which depend on the current CSVs and dataset state.

    Not in the hard gate: the archive rebuild reads today's ``CSVs/site_raw`` and
    ``data/scrape_state``, so these are facts about the latest refresh. The
    deterministic record of the same claims is
    ``test_committed_evidence_headline_numbers``.
    """
    if not (REPO / "exports" / "archive" / ARCHIVE).is_file():
        pytest.skip(f"{ARCHIVE} not in this checkout")
    payload, _ = W.load_archive_payload(ARCHIVE)
    inc = {sc: W.V2_PARAMS[sc] for sc in W.SCOPES}
    c0 = {"OFFENSE": (0.077, 1.11), "GLOBAL": (0.088, 0.72), "IDP": (0.024, 1.15)}
    base = W.build_board(payload, inc)
    cand = W.build_board(payload, c0)
    d = W.board_diff(base, cand, {})
    assert (
        d["byPosition"]["WR"]["medianPctValueChange"]
        < -15
        < d["byPosition"]["LB"]["medianPctValueChange"]
    )
    # the outlier filter starts discarding value-direct market votes on offense rows
    inc_drops = W.value_direct_drops(base)["offense"]["rowsWithDroppedValueDirectVote"]
    c0_drops = W.value_direct_drops(cand)["offense"]["rowsWithDroppedValueDirectVote"]
    assert c0_drops > 5 * max(inc_drops, 1)


# ── the committed evidence says what the proposal says ─────────────────────


def test_committed_evidence_headline_numbers(evidence):
    assert evidence["activationStatus"] == "NOT ACTIVATED"
    assert evidence["oracle"]["integerMismatches"] == 0
    fw = evidence["holdoutForward"]["summary"]
    assert fw["C0"]["winDays"] == fw["C0"]["days"] >= 100
    assert fw["C_vd"]["winDays"] == 0
    order = evidence["forwardOrdering"]
    assert order["holdoutMarkets_biasedTowardIncumbent"]["C0"]["pairsBetterThanIncumbent"] == 0
    assert order["ktcMarket_biasedTowardC0"]["C0"]["pairsBetterThanIncumbent"] == 0
    assert evidence["board"]["rankHillVotesByPool"].get("idp") is None
