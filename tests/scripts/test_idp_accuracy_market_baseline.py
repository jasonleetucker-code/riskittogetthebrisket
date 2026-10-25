"""Lane C-market baseline (scripts/idp_accuracy/market_baseline.py) — pure helpers.

Synthetic contracts only: no network, no live board.  The two archive-backed tests read
tracked ``exports/archive`` bundles (immutable by construction) and pin the
no-future-data property of the pre-season board.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "idp_accuracy" / "market_baseline.py"


@pytest.fixture(scope="module")
def mb():
    spec = importlib.util.spec_from_file_location("idp_c_market_baseline", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["idp_c_market_baseline"] = mod
    spec.loader.exec_module(mod)
    return mod


def _row(name, pos, value, rank, *, cls=None, sites=None, meta=None, alpha=0.1, conf="low"):
    cls = cls or ("pick" if pos == "PICK" else "idp" if pos in ("DL", "LB", "DB") else "offense")
    meta = meta or {}
    return {
        "displayName": name,
        "playerId": f"id-{name}",
        "position": pos,
        "assetClass": cls,
        "rankDerivedValue": value,
        "canonicalConsensusRank": rank,
        "confidenceBucket": conf,
        "canonicalSiteValues": sites or {},
        "sourceRankMeta": meta,
        "effectiveSourceRanks": {k: 1 for k in meta},
        "alphaShrinkage": alpha,
    }


def _contract(rows):
    return {"playersArray": rows}


@pytest.fixture
def toy(mb):
    rows = [
        _row("Q1", "QB", 9000, 1, sites={"idpTradeCalc": 9999}),
        _row("W1", "WR", 8000, 2, sites={"idpTradeCalc": 9000}),
        _row("L1", "LB", 6000, 3, sites={"idpTradeCalc": 9500}),
        _row("R1", "RB", 5000, 4, sites={"idpTradeCalc": 5000}),
        _row("D1", "DL", 4000, 5, sites={"idpTradeCalc": 3000}),
        _row("P1", "PICK", 3500, 6, sites={"idpTradeCalc": 9800}),
        _row("B1", "DB", 3000, 7, sites={"idpTradeCalc": 2000}),
        _row("T1", "TE", 2000, 8, sites={"idpTradeCalc": 1000}),
        _row("U1", "DB", 0, None),  # unpriced: value 0 on the wire must read as MISSING
        _row("U2", "WR", None, None),
    ]
    return mb.board_rows(_contract(rows))


def test_unpriced_is_missing_never_zero(mb, toy):
    by = {r["name"]: r for r in toy}
    assert by["U1"]["value"] is None and by["U2"]["value"] is None
    assert all(r["name"] not in ("U1", "U2") for r in mb.by_value(toy))


def test_groups_and_top_overall(mb, toy):
    top = mb.top_overall(toy, 5)
    assert [r["name"] for r in top["rows"]] == ["Q1", "W1", "L1", "R1", "D1"]
    assert top["groupCounts"] == {"offense": 3, "idp": 2}
    bands = {b["band"]: b for b in mb.band_counts(toy)}
    assert bands["1-25"]["idp"] == 3 and bands["1-25"]["offense"] == 4
    assert bands["1-25"]["pick"] == 1


def test_kth_values_and_placement(mb, toy):
    kth = {e["k"]: e for e in mb.kth_values(toy, (1, 2, 3, 4))}
    assert kth[1]["idp"]["name"] == "L1" and kth[1]["offense"]["name"] == "Q1"
    assert kth[1]["idpOverOffenseValue"] == round(6000 / 9000, 3)
    assert kth[4]["idp"] is None  # three priced defenders only: absent, not zero
    pm = mb.placement_metrics(toy)
    assert pm["topDefender"]["name"] == "L1" and pm["topDefender"]["rank"] == 3
    assert pm["idpInTopN"]["25"] == 3
    assert pm["familyKthOverallRank"]["DB"]["1"] == 7
    assert pm["familyKthOverallRank"]["DB"]["3"] is None


def test_compare_placement_measures_a_pure_idp_level_shift(mb, toy):
    shifted = [dict(r) for r in toy]
    for r in shifted:
        if r["group"] == "idp" and r["value"] is not None:
            r["value"] *= 0.8
    cmp_ = mb.compare_placement(toy, shifted, idp_n=3, off_n=4)
    assert cmp_["idpMedianValueRatio"] == pytest.approx(0.8, abs=1e-4)
    assert cmp_["offenseMedianValueRatio"] == pytest.approx(1.0)
    assert cmp_["idpRelativeToOffenseMedian"] == pytest.approx(0.8, abs=1e-4)
    same = mb.compare_placement(toy, toy, idp_n=3, off_n=4)
    assert same["idpGeoMeanValueRatio"] == 1.0 and same["idpRowsHalvedOrWorse"] == 0


def test_compare_placement_separates_haircut_rows_from_a_level_shift(mb, toy):
    v = [dict(r) for r in toy]
    for r in v:
        if r["name"] == "B1":
            r["value"] *= 0.3  # the single-source haircut, on one row
    cmp_ = mb.compare_placement(toy, v, idp_n=3, off_n=4)
    assert cmp_["idpRowsHalvedOrWorse"] == 1
    assert cmp_["idpMedianValueRatio"] == pytest.approx(1.0)  # robust
    assert cmp_["idpGeoMeanValueRatio"] < 0.7  # not robust: why both are reported


def test_idptc_native_ranks_on_its_own_board(mb, toy):
    nat = mb.idptc_native(toy, ks=(1, 2, 3))
    k = {e["k"]: e for e in nat["kthDefenderPlacement"]}
    # IDPTC players by value: Q1 9999, L1 9500, W1 9000, R1 5000, D1 3000, B1 2000, T1
    assert k[1]["idptcKthDefender"] == "L1" and k[1]["idptcPlayerRank"] == 2
    # with the pick (9800) the defender drops one place
    assert k[1]["idptcRankWithPicks"] == 3
    # canonical player-only rank of the top defender: Q1, W1, L1 -> 3
    assert k[1]["canonicalPlayerRank"] == 3
    assert nat["rowsWithValue"] == {"offense": 4, "idp": 3, "pick": 1}
    assert nat["idpRankAgreement"]["n"] == 3
    ds = mb.idptc_native(toy, ks=(1,), same_scale=False)
    assert ds["kthOffenseControl"] is None
    assert "canonicalOverNative" not in ds["kthDefenderPlacement"][0]


def test_bridge_trace_attribution(mb):
    meta = {
        "idpTradeCalc": {"isAnchor": True, "appliedWeight": 0.5, "rankCoordinatePool":
                         "shared_market", "method": "direct"},
        "draftSharksIdp": {"isAnchor": True, "appliedWeight": 0.5, "rankCoordinatePool":
                           "shared_market", "method": "ds_combined_cross_market"},
        "fantasyProsIdp": {"isAnchor": False, "appliedWeight": 1.0, "sharedMarketTranslated":
                           True, "rankCoordinatePool": "shared_market", "method": "exact"},
        "idpShowCombined": {"isAnchor": True, "appliedWeight": 0.0, "contributedToBlend": False},
    }  # fmt: skip
    rows = mb.board_rows(_contract([_row("L1", "LB", 6000, 1, meta=meta)]))
    tr = mb.bridge_trace({}, rows, anchor_keys={"idpTradeCalc", "draftSharksIdp"},
                         ladder_seeds=["idpTradeCalc"], idp_n=1)  # fmt: skip
    att = tr["topIdpLevelAttribution"]
    # anchors 0.9 split 50/50; the translated subgroup vote (0.1) belongs to the seed
    assert att["idpTradeCalc"] == pytest.approx(0.55)
    assert att["draftSharks"] == pytest.approx(0.45)
    assert sum(att.values()) == pytest.approx(1.0)
    assert tr["topIdpAnchorVoterSets"] == {"draftSharksIdp,idpTradeCalc": 1}
    assert tr["topIdpMeanAnchorWeight"] == pytest.approx(0.9)


def test_assert_aggregate_only(mb):
    mb.assert_aggregate_only({"rows": [{"name": "Josh Allen"}]}, {"Some Manager"})
    with pytest.raises(AssertionError):
        mb.assert_aggregate_only({"x": [{"name": "Some Manager"}]}, {"Some Manager"})
    with pytest.raises(AssertionError):
        mb.assert_aggregate_only({"x": {"ownerId": "1"}}, set())
    with pytest.raises(AssertionError):
        mb.assert_aggregate_only({"1312006700437352448": 1}, {"1312006700437352448"})


def test_statistics_match_scipy(mb):
    from scipy import stats as sps

    xs = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 4]
    ys = [2, 1, 4, 3, 6, 5, 8, 7, 10, 9, 12, 11, 14, 13, 4]
    rho = sps.spearmanr(xs, ys).statistic
    assert mb._spearman(xs, ys) == pytest.approx(round(rho, 3))
    ci = mb.spearman_ci(xs, ys, boot=200)
    assert ci["rho"] == pytest.approx(round(rho, 3)) and ci["n"] == 15
    assert ci["ci95"][0] <= ci["rho"] <= ci["ci95"][1]
    assert mb.spearman_ci(xs[:5], ys[:5])["rho"] is None  # small n: unavailable, not 0


def test_holm(mb):
    adj = mb.holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adj == {"a": 0.03, "c": 0.06, "b": 0.06}


def test_reference_card_is_investigation_b_constant(mb):
    card = mb.reference_tackle_heavy_card()
    assert card["idp_tkl_solo"] == 1.5 and card["idp_pass_def"] == 1.0
    assert all(k.startswith("idp_") for k in card)


def test_scale_helpers(mb, tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("name,value,position,team\nA,100,LB,\nB,200,QB,\nC,50,DE,\n", encoding="utf-8")
    n = mb._scale_csv(p, value_col="value", pos_col="position",
                      positions=mb._IDP_CSV_POSITIONS, f=0.5)  # fmt: skip
    assert n == 2
    body = p.read_text(encoding="utf-8")
    assert "A,50.0,LB" in body and "B,200,QB" in body and "C,25.0,DE" in body
    raw = {"players": {"A": {"k": 100, "_canonicalSiteValues": {"k": 100}}, "B": {"k": 10}}}
    assert mb._scale_raw_site(raw, "k", {"A"}, 2.0) == 1
    assert (
        raw["players"]["A"]["k"] == 200 and raw["players"]["A"]["_canonicalSiteValues"]["k"] == 200
    )
    assert raw["players"]["B"]["k"] == 10


def test_starter_bench_by_tier_counts_weekly_best_ball_starts(mb):
    slots = ["DL", "LB"]
    pools = [[
        {"sid": "a", "position": "DL", "fantasyPositions": ["DL"], "value": 5000, "group": "idp"},
        {"sid": "b", "position": "DL", "fantasyPositions": ["DL", "LB"], "value": 1200,
         "group": "idp"},
        {"sid": "c", "position": "LB", "fantasyPositions": ["LB"], "value": None, "group": "idp"},
    ]]  # fmt: skip
    pts = {"a": {1: 10, 2: 10}, "b": {1: 9, 2: 1}, "c": {1: 5, 2: 8}}

    def band_of(v):
        return "unvalued" if v is None else "hi" if v >= 3000 else "lo"

    out = mb.starter_bench_by_tier(pools, pts, [1, 2], slots, band_of, ["hi", "lo", "unvalued"])
    cells = {(r["group"], r["band"]): r for r in out["table"]}
    assert cells[("idp", "hi")]["regularStarter"] == 1  # a starts both weeks at DL
    # week 1: b (9) beats c (5) for LB via multi-eligibility; week 2: c (8) beats b (1)
    assert cells[("idp", "lo")]["regularStarter"] == 1
    assert cells[("idp", "unvalued")]["regularStarter"] == 1
    assert out["slotsPerWeek"] == 2 and out["teams"] == 1


def test_preseason_archive_is_strictly_before_kickoff(mb):
    path = REPO / mb.PRESEASON_ARCHIVE
    if not path.exists():
        pytest.skip("archive pruned")
    with zipfile.ZipFile(path) as zf:
        member = next(n for n in zf.namelist() if re.match(r"dynasty_data_.*\.json$", n))
        ts = json.loads(zf.read(member))["scrapeTimestamp"]
    assert datetime.fromisoformat(ts) < datetime.fromisoformat(mb.KICKOFF_UTC)


def test_preseason_csv_tree_is_before_kickoff(mb):
    try:
        committed = subprocess.run(
            ["git", "-C", str(REPO), "log", "-1", "--format=%cI", mb.PRESEASON_CSV_REV],
            check=True, capture_output=True, text=True,
        ).stdout.strip()  # fmt: skip
    except subprocess.CalledProcessError:
        pytest.skip("revision not in this clone")
    assert datetime.fromisoformat(committed) < datetime.fromisoformat(mb.KICKOFF_UTC)


def test_nothing_in_src_imports_the_research_script():
    hits = [
        p
        for p in (REPO / "src").rglob("*.py")
        if "idp_accuracy" in p.read_text(encoding="utf-8", errors="ignore")
        or "market_baseline" in p.read_text(encoding="utf-8", errors="ignore")
    ]
    assert hits == []


def test_variant_registry_is_measurement_only(mb):
    # every variant is an offline shadow build; none names a flag DEFAULT change
    assert "baseline" in mb.VARIANTS
    src = SCRIPT.read_text(encoding="utf-8")
    assert "feature_flags._DEFAULTS" not in src
    assert not re.search(r"write_db|ArtifactData|sleeper.*\.(post|put)\(", src)
    assert math.isfinite(len(mb.VARIANTS))
