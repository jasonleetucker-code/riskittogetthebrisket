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
    n = mb._scale_csv(p, value_col="value", pos_col="position", f=0.5)
    assert n == 2
    body = p.read_text(encoding="utf-8")
    assert "A,50.0,LB" in body and "B,200,QB" in body and "C,25.0,DE" in body
    raw = {"players": {"A": {"k": 100, "_canonicalSiteValues": {"k": 100}}, "B": {"k": 10}}}
    assert mb._scale_raw_site(raw, "k", {"A"}, 2.0) == 1
    assert (
        raw["players"]["A"]["k"] == 200 and raw["players"]["A"]["_canonicalSiteValues"]["k"] == 200
    )
    assert raw["players"]["B"]["k"] == 10


def test_every_vendor_spelling_of_a_defender_is_scaled(mb, tmp_path):
    """Regression: the IDPTC CSV spells edge rushers ``ED`` (98 rows, including its top
    defender) and an earlier private spelling list missed them, so a 'level' perturbation
    moved only 272 of 377 defenders and understated every elasticity."""
    for pos in ("ED", "DT", "DE", "EDGE", "NT", "IDL", "CB", "S", "FS", "SS", "SAF", "ILB",
                "OLB", "MLB", "LB", "DL", "DB"):  # fmt: skip
        assert mb._is_idp_position(pos), pos
    for pos in ("QB", "RB", "WR", "TE", "K", "PICK", "", None):
        assert not mb._is_idp_position(pos), pos
    p = tmp_path / "idptc.csv"
    p.write_text("name,value,position,team\nE,6000,ED,\nS,2000,S,\nT,3000,TE,\nK,9000,PICK,\n",
                 encoding="utf-8")  # fmt: skip
    assert mb._scale_csv(p, value_col="value", pos_col="position", f=0.5) == 2
    body = p.read_text(encoding="utf-8")
    assert "E,3000.0,ED" in body and "S,1000.0,S" in body and "T,3000,TE" in body


def test_idp_raw_names_follow_the_raw_payloads_own_position_map(mb):
    raw = {
        "players": {
            "Josh Allen": {},
            "Zack Baun": {},
            "D.J. Wonnum": {},
            "2027 Pick 1.01": {},
            "Travis Hunter": {},
        },  # fmt: skip
        "sleeper": {
            "positions": {
                "Josh Allen": "QB",
                "Zack Baun": "LB",
                "D.J. Wonnum": "DE",
                "Travis Hunter": "WR",
            }
        },  # fmt: skip
    }
    # the shared name resolves to the offense entry the contract prices; a pick or a player
    # with no position is never a defender; spelling variants (DE, ED, S ...) all count
    assert mb.idp_raw_names(raw) == {"Zack Baun", "D.J. Wonnum"}
    assert mb.idp_raw_names({}) == set()


def test_scaled_share_demands_the_factor_on_nearly_every_row(mb):
    base = {"a": 6000.0, "b": 3000.0, "c": 45.0, "d": 5.0}
    ok = {"a": 4800.0, "b": 2400.0, "c": 36.0, "d": 4.0}  # x0.8, whole-number rounding
    assert mb.scaled_share(base, ok, 0.8)["share"] == 1.0
    partial = {**ok, "a": 6000.0}  # the top row did not move: the earlier ED defect
    s = mb.scaled_share(base, partial, 0.8)
    assert s["scaled"] == 3 and s["of"] == 4 and s["share"] == 0.75
    assert mb.scaled_share({}, {}, 0.8)["share"] is None


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


def _imported_modules(path: Path) -> set[str]:
    """Every module name an ``import`` / ``from ... import`` statement names."""
    import ast

    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_nothing_in_src_imports_the_research_script():
    # Checks real import statements, not substrings: a docstring citing a
    # research record under docs/valuation/idp_accuracy/ is not an import
    # (src/league_valuation/replacement_shadow.py does exactly that).
    hits = [
        p
        for p in (REPO / "src").rglob("*.py")
        if any("idp_accuracy" in name or "market_baseline" in name for name in _imported_modules(p))
    ]
    assert hits == []


def test_import_guard_catches_a_real_import(tmp_path):
    probe = tmp_path / "probe.py"
    probe.write_text("from scripts.idp_accuracy import market_baseline\n", encoding="utf-8")
    assert any("idp_accuracy" in n for n in _imported_modules(probe))
    doc_only = tmp_path / "doc_only.py"
    doc_only.write_text('"""Record: docs/valuation/idp_accuracy/B.md"""\n', encoding="utf-8")
    assert not any("idp_accuracy" in n for n in _imported_modules(doc_only))


def test_variant_registry_is_measurement_only(mb):
    # every variant is an offline shadow build; none names a flag DEFAULT change
    assert "baseline" in mb.VARIANTS
    src = SCRIPT.read_text(encoding="utf-8")
    assert "feature_flags._DEFAULTS" not in src
    assert not re.search(r"write_db|ArtifactData|sleeper.*\.(post|put)\(", src)
    assert math.isfinite(len(mb.VARIANTS))


# ═══════════════════════════════════════════════════════════════════════════
# vendor-stated format, scoring mismatches, receipts, cross-checks
# ═══════════════════════════════════════════════════════════════════════════

#: Markup shaped like The IDP Show's "Big 3 Scoring" page (labels, values and the
#: "(if applicable)" / "(Defense)" qualifiers split across tags and lines).
BIG3_HTML = """
<html><head><title>Big 3 Scoring - The IDP Show</title><style>.x{color:red}</style></head><body>
<h1>Big 3 Scoring</h1><p>These are our preferred IDP scoring settings.</p>
<p><strong>Solo Tackles</strong>:</p><p>1.25</p><p>Rationale: tackles are basic.</p>
<p>Assisted Tackles:</p><p>0.75</p><p>Passes Defended:</p><p>4</p>
<p>Force Fumble:</p><p>4</p><p>Fumble Recovery:</p><p>3</p><p>Sack:</p><p>5</p>
<p>Sack Yards<br>(if applicable): 1 yard = 0.1</p><p>QB Hit:</p><p>2</p>
<p>Tackle for Loss:</p><p>3</p><p>INT:</p><p>6</p><p>TD:</p><p>6</p><p>Safety:</p><p>5</p>
<p>Blocked Kick:</p><p>5</p>
<p>Return Yards<br>(Offense/Special Teams): 1 yard = 0.1</p>
<p>Return Yards<br>(Defense): 1 yard = 0.1</p>
<script>var Sack = "Sack: 99";</script>
</body></html>
"""

IDPTC_HTML = """
<!DOCTYPE html><html><head><title>The IDP Show Trade Calculator</title>
<meta name="description" content="Official trade calculator of The IDP Show, built for IDP fantasy football leagues using Big 3 scoring. Instantly evaluate trades.">
<style>.superflex{color:#fff}</style></head><body>
<h5>12-Team/.5 PPR</h5><br><h5>Updated: 10/10/2026</h5>
<span class="superflex">Superflex:</span><input type="checkbox" id="toggleButton">
<span class="tep">TEP:</span><input type="checkbox" id="toggleButtonTEP">
</body></html>
"""


def test_parse_big3_page_reads_every_label_and_ignores_script_text(mb):
    parsed = mb.parse_big3_page(BIG3_HTML)
    assert set(parsed) == set(mb.BIG3_LABEL_TO_SLEEPER)
    assert parsed["Solo Tackles"] == 1.25 and parsed["Assisted Tackles"] == 0.75
    assert parsed["Sack"] == 5.0  # the script's "Sack: 99" must not be read
    assert parsed["Sack Yards"] == 0.1 and parsed["Return Yards (Defense)"] == 0.1
    assert parsed["Tackle for Loss"] == 3.0 and parsed["Passes Defended"] == 4.0


def test_big3_card_refuses_a_partial_page(mb):
    parsed = mb.parse_big3_page(BIG3_HTML)
    card = mb.big3_sleeper_card(parsed)
    assert card["idp_tkl_solo"] == 1.25 and card["idp_sack"] == 5.0 and card["idp_pass_def"] == 4.0
    # one label prices both defensive return-yard keys
    assert card["idp_int_ret_yd"] == card["idp_fum_ret_yd"] == 0.1
    assert len(card) == 15 and all(k.startswith("idp_") for k in card)
    partial = {k: v for k, v in parsed.items() if k != "Tackle for Loss"}
    assert mb.big3_sleeper_card(partial) == {}  # never score half a card as "Big 3"
    assert mb.parse_big3_page("<p>nothing here</p>") == {}


def test_parse_idptc_page_states_what_it_states_and_nothing_more(mb):
    p = mb.parse_idptc_page(IDPTC_HTML)
    assert p["title"] == "The IDP Show Trade Calculator"
    assert p["statedIdpScoringBasis"] == "Big 3"
    assert (p["teams"], p["ppr"], p["pageUpdated"]) == (12, 0.5, "10/10/2026")
    assert p["toggleControls"] == {"superflex": True, "tePremium": True}
    assert not any(p["pageMentions"].values())  # no starter / lineup / roster / best-ball text
    bare = mb.parse_idptc_page("<html><body><h5>hello</h5></body></html>")
    assert bare["statedIdpScoringBasis"] is None and bare["teams"] is None and bare["ppr"] is None


def test_idp_card_comparison_is_key_by_key(mb):
    card = {"idp_sack": 2.92, "idp_tkl_loss": 4.24, "idp_tkl_solo": 1.33}
    big3 = {"idp_sack": 5.0, "idp_tkl_loss": 3.0, "idp_tkl_solo": 1.25}
    rows = {r["sleeperKey"]: r for r in mb.idp_card_comparison(card, big3)}
    assert rows["idp_sack"]["leagueOverBig3"] == round(2.92 / 5.0, 3)
    assert rows["idp_tkl_loss"]["leagueOverBig3"] == round(4.24 / 3.0, 3)
    assert rows["idp_pass_def"]["league"] is None  # a key the league card lacks: absent, not 0
    assert rows["idp_pass_def"]["leagueOverBig3"] is None


def test_pooled_ratio_ci_is_a_ratio_of_sums_with_a_player_bootstrap(mb):
    num = {f"p{i}": 1.1 * (10 + i) for i in range(30)}
    den = {f"p{i}": float(10 + i) for i in range(30)}
    out = mb.pooled_ratio_ci(num, den, sorted(num))
    assert out["n"] == 30 and out["ratio"] == pytest.approx(1.1, abs=1e-4)
    assert out["ci95"][0] <= out["ratio"] <= out["ci95"][1]
    assert mb.pooled_ratio_ci(num, den, sorted(num)) == out  # seeded: reproducible
    small = mb.pooled_ratio_ci(num, den, sorted(num)[:5])
    assert small["ratio"] is None and small["ci95"] is None  # too few players: unavailable
    assert mb.pooled_ratio_ci(num, {k: 0.0 for k in den}, sorted(num))["ratio"] is None


def test_scoring_drift_separates_level_from_order(mb):
    ids = [f"p{i}" for i in range(20)]
    a = {s: {1: 10.0 + i, 2: 12.0 + i, 3: 8.0 + i} for i, s in enumerate(ids)}
    b = {s: {w: v * 0.8 for w, v in wk.items()} for s, wk in a.items()}  # a pure level change
    out = mb.scoring_drift(a, b, ids)
    assert out["ratio"] == pytest.approx(1.25, abs=1e-4) and out["spearmanPpg"] == 1.0
    short = {s: {1: 5.0, 2: 6.0} for s in ids}  # two games: below MIN_GAMES
    assert mb.scoring_drift(short, short, ids)["ratio"] is None


def test_reception_points_attach_flat_tier_and_position_bonus(mb):
    card = {"rec": 0.1, "rec_0_4": 0.25, "rec_5_9": 0.5, "rec_10_19": 0.75, "bonus_rec_wr": 0.02,
            "bonus_rec_te": 0.0}  # fmt: skip
    stats = {
        1: {
            "wr": {"gp": 1, "rec": 4, "rec_0_4": 1, "rec_5_9": 1, "rec_10_19": 2,
                   "bonus_rec_wr": 4, "rec_yd": 60},
            "te": {"gp": 1, "rec": 2, "rec_5_9": 2, "rec_yd": 20},
            "dnp": {"gp": 0, "rec": 3, "rec_0_4": 3},
            "norec": {"gp": 1, "rush_yd": 50},
        }
    }  # fmt: skip
    pos = {"wr": "WR", "te": "TE", "dnp": "WR", "norec": "RB"}
    recs, pts = mb.reception_points(stats, card, pos.get)
    assert set(recs) == {"wr", "te"}  # gp 0 and no-reception lines never count
    # WR: 4 * 0.1 + 0.25 + 0.5 + 2 * 0.75 + 4 * 0.02 ; yards are NOT reception points
    assert pts["wr"] == pytest.approx(0.4 + 0.25 + 0.5 + 1.5 + 0.08)
    assert pts["te"] == pytest.approx(0.2 + 1.0)  # bonus_rec_te is 0.0 on the card
    assert recs["wr"] == 4 and recs["te"] == 2


def test_native_level_ratios_use_each_markets_own_scale(mb):
    rows = []
    for i, (o, d) in enumerate([(100, 50), (80, 40), (60, 30), (40, 20)]):
        rows.append(_row(f"O{i}", "WR", o * 100, i + 1, sites={"mk": o}))
        rows.append(_row(f"D{i}", "LB", d * 100, i + 5, sites={"mk": d}))
    rows.append(_row("DNP", "LB", None, None, sites={}))  # no value: absent, not 0
    board = mb.board_rows(_contract(rows))
    got = mb.native_level_ratios(board, offense_key="mk", idp_key="mk", ks=(1, 2, 4, 9),
                                 off_pool=4, idp_pool=4)  # fmt: skip
    assert [e["k"] for e in got["atEqualDepth"]] == [1, 2, 4]  # k=9 does not exist
    assert got["atEqualDepth"][0]["idpOverOffense"] == 0.5
    assert got["nIdp"] == 4 and got["starterPools"]["medianRatio"] == 0.5
    canon = mb.native_level_ratios(board, offense_key=None, idp_key=None, ks=(1,), off_pool=4,
                                   idp_pool=4)  # fmt: skip
    assert canon["atEqualDepth"][0]["offense"] == 10000.0
    assert canon["offenseKey"] == "rankDerivedValue"
    deep = mb.native_level_ratios(board, offense_key="mk", idp_key="mk", off_pool=99, idp_pool=99)
    assert deep["starterPools"] is None  # pool deeper than the data: unavailable


def test_served_board_sha256_is_order_invariant_and_field_sensitive(mb):
    rows = [_row("A", "QB", 9000, 1), _row("B", "LB", 4000, 2), _row("C", "WR", None, None)]
    base = mb.served_board_sha256(rows)
    assert base == mb.served_board_sha256(list(reversed(rows)))
    moved = [dict(rows[0], rankDerivedValue=9001), rows[1], rows[2]]
    assert mb.served_board_sha256(moved) != base
    flagged = [rows[0], dict(rows[1], quarantined=True), rows[2]]
    assert mb.served_board_sha256(flagged) != base
    extra = [dict(r, someUnrelatedField=1) for r in rows]
    assert mb.served_board_sha256(extra) == base  # only the six pinned fields count


def test_roster_format_fingerprint_matches_lane_a_manifest(mb):
    """rf1:10f897578eea2fe4 is the value Lane A's MANIFEST.json records for dynasty_main."""
    slots = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "TE", "FLEX", "FLEX", "SUPER_FLEX", "K",
             "DL", "DL", "DL", "LB", "LB", "LB", "DB", "DB", "DB"]  # fmt: skip
    league = {
        "roster_positions": slots + ["BN"] * 37,
        "settings": {
            "num_teams": 12,
            "taxi_slots": 0,
            "reserve_slots": 0,
            "best_ball": 1,
            "type": 2,
        },  # fmt: skip
    }
    assert mb.roster_format_fingerprint(league) == "rf1:10f897578eea2fe4"
    other = {**league, "settings": {**league["settings"], "best_ball": 0}}
    assert mb.roster_format_fingerprint(other) != "rf1:10f897578eea2fe4"


def test_crosscheck_manifest_reports_each_input_without_asserting(mb):
    lid = mb.LEAGUE_ID
    manifest = {
        "manifestVersion": "idp-accuracy-manifest/v1",
        "repo": {"pinnedSha": "abc"},
        "rosterFormat": {"rosterFormatFingerprint": "rf1:aa"},
        "scoringCard": {"scoringFingerprint": "sf1:aa"},
        "pinnedArchive": {"sha256": "arch"},
        "servedBoard": {"servedBoardSha256": "board"},
        "datasets": {"sleeperPublicApi": {
            f"/league/{lid}": {"sha256": "h1"},
            f"/league/{lid}/rosters": {"sha256": "OLD"},
            "/players/nfl": {"sha256": "h3"},
        }},
    }  # fmt: skip
    receipts = {
        f"{mb.SLEEPER}/league/{lid}": {"sha256": "h1"},
        f"{mb.SLEEPER}/league/{lid}/rosters": {"sha256": "NEW"},
        f"{mb.SLEEPER}/players/nfl": {"sha256": "h3"},
        f"{mb.SLEEPER}/stats/nfl/regular/2026/1": {"sha256": "x"},
        "https://idptradecalculator.com/": {"sha256": "vendor"},  # not Sleeper: ignored
    }
    out = mb.crosscheck_manifest(manifest, receipts=receipts, served_sha="board",
                                 archive_sha="arch", live_fingerprint="sf1:aa",
                                 archived_fingerprint="sf1:bb",
                                 roster_fingerprint="rf1:aa")  # fmt: skip
    assert out["servedBoardSha256"] == "match" and out["archiveSha256"] == "match"
    assert out["rosterFormatFingerprint"] == "match"
    assert out["scoringFingerprintLive"] == "match"
    assert out["scoringFingerprintArchived"] == "differs"
    ep = out["sleeperEndpoints"]
    assert ep["/league/{leagueId}"] == "match" and ep["/league/{leagueId}/rosters"] == "differs"
    assert ep["/stats/nfl/regular/2026/1"] == "absent" and ep["/players/nfl"] == "match"
    assert lid not in json.dumps(out)  # the raw league id never reaches the evidence
    assert out["sleeperEndpointCounts"] == {"match": 2, "differs": 1, "absent": 1}


def test_raw_fetcher_receipts_hash_the_body_byte_for_byte(mb, tmp_path):
    import hashlib

    f = mb.RawFetcher(tmp_path, offline=True)
    url = f"{mb.SLEEPER}/league/{mb.LEAGUE_ID}"
    body = b'{"a": 1,   "b": [1,2]}\n'  # not canonical JSON: re-serializing would change the hash
    f._path(url).write_bytes(body)
    assert f.get(url) == {"a": 1, "b": [1, 2]}
    assert f.receipts[url]["sha256"] == hashlib.sha256(body).hexdigest()
    assert f.receipts[url]["bytes"] == len(body)
    with pytest.raises(RuntimeError, match="offline and not cached"):
        f.get(f"{mb.SLEEPER}/players/nfl")


def test_scorer_check_separates_no_stat_line_zeros_from_misses(mb):
    pts = {"a": {1: 10.0}, "b": {1: 5.0}}
    matchups = {1: [{"players_points": {"a": 10.004, "b": 5.2, "c": 0.0, "d": 7.5}}]}
    out = mb.scorer_check(pts, matchups)
    assert out["playerWeeksCompared"] == 2 and out["within0.01"] == 1
    assert out["maxAbsDiff"] == pytest.approx(0.2)
    assert out["noScoredLineAwardedZero"] == 1  # c: no line, awarded 0 (a real zero)
    assert out["nonzeroHostPointsWithNoScoredLine"] == 1  # d: a miss, reported not hidden


def test_card_alignment_compares_references_on_shared_resamples(mb):
    ids = [f"p{i}" for i in range(40)]
    val = {s: float(i) for i, s in enumerate(ids)}
    league = {s: float(i) + (3 if i % 2 else 0) for i, s in enumerate(ids)}

    def pos(_sid):
        return "LB"

    def same(sid):
        return league[sid]

    def flipped(sid):
        return -float(val[sid])

    out = mb.card_alignment(val, same, {"same": same, "flipped": flipped}, pos)
    cell = out["IDP"]
    assert cell["n"] == 40 and set(cell["references"]) == {"same", "flipped"}
    assert cell["references"]["same"]["leagueMinusRef"] == 0.0
    assert cell["references"]["same"]["ci95"] == [0.0, 0.0]
    assert cell["references"]["flipped"]["leagueMinusRef"] > 1.5  # rho ~ +1 vs rho ~ -1
    assert out["DL"]["references"] == {} and out["DL"]["n"] == 0  # no DL players: unavailable


def test_script_never_reads_a_scraper_composite_or_a_hash_seeded_set_order(mb):
    src = SCRIPT.read_text(encoding="utf-8")
    assert "_composite" not in src  # the served canonical fields only
    assert re.search(r"common = sorted\(set\(pit_vals\)", src)  # bootstrap order is deterministic


# ── the committed evidence ──────────────────────────────────────────────────

_VAL = REPO / "docs" / "valuation" / "idp_accuracy"
EVIDENCE = _VAL / "evidence" / "c_market_baseline_2026-10-25.json"
REPORT = _VAL / "C_MARKET_CROSS_POSITION.md"
#: servedBoardSha256 in Lane A's MANIFEST.json for the same pinned archive + tree
LANE_A_SERVED_BOARD_SHA256 = "4e6ba1f5c1695f5968e33d69aa26d5776e9587872e438ea8ea179baeed7d8712"


@pytest.fixture(scope="module")
def evidence():
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def test_evidence_is_aggregate_only(mb, evidence):
    text = EVIDENCE.read_text(encoding="utf-8")
    assert mb.LEAGUE_ID not in text  # no raw Sleeper league id in a public artifact
    mb.assert_aggregate_only(evidence, {mb.LEAGUE_ID, "Risk It To Get The Brisket"})
    for needle in ("owner_id", "ownerId", "display_name", "avatar", "roster_id", "user_id"):
        assert needle not in text


def test_evidence_pins_the_inputs_it_claims(mb, evidence):
    inp = evidence["inputs"]
    assert inp["archive"] == mb.PINNED_ARCHIVE and inp["leagueKey"] == mb.LEAGUE_KEY
    assert inp["servedBoardSha256"] == LANE_A_SERVED_BOARD_SHA256
    path = REPO / mb.PINNED_ARCHIVE
    if path.exists():
        assert inp["archiveSha256"] == mb.sha256_file(path)
    assert inp["scorerCheck"]["within0.01"] == inp["scorerCheck"]["playerWeeksCompared"] == 3299
    wide = inp["scorerCheckNoGpFilter"]  # Lane A's wider denominator, same scorer
    assert wide["within0.01"] == wide["playerWeeksCompared"] == 3710
    assert wide["nonzeroHostPointsWithNoScoredLine"] == 0 and wide["noScoredLineAwardedZero"] == 461
    assert inp["scoringWeeks"] == [1, 2, 3, 4, 5, 6] and "EXCLUDED" in inp["week7"]
    pert = evidence["perturbations"]
    assert pert["controlBaselineMatchesInProcess"] is True
    assert all("error" not in v for v in pert.values() if isinstance(v, dict))


def test_evidence_agrees_with_lane_a_manifest(evidence):
    cc = evidence["inputs"]["laneAManifestCrosscheck"]
    assert cc["servedBoardSha256"] == cc["archiveSha256"] == "match"
    assert cc["scoringFingerprintLive"] == cc["scoringFingerprintArchived"] == "match"
    assert cc["rosterFormatFingerprint"] == "match"
    counts = cc["sleeperEndpointCounts"]
    # the weekly stat dumps, matchups, league card and rosters are byte-identical to Lane A's;
    # the player directory is a daily-changing file and may legitimately differ
    assert counts.get("match", 0) >= 14 and counts.get("absent", 0) == 0
    assert all(v == "match" for k, v in cc["sleeperEndpoints"].items() if k != "/players/nfl")


def test_sample_types_are_labelled_in_the_evidence(evidence):
    corr = evidence["correlationReproduction"]
    pre = corr["pointInTimePreseason_20260909"]
    assert "OUT-OF-SAMPLE" in pre["sampleType"]
    assert "IN-SAMPLE" in corr["pinnedInSeason_20261025"]["sampleType"]
    assert pre["offense"]["n"] > 0 and pre["idp"]["n"] > 0


def test_vendor_stated_format_is_recorded_with_receipts(evidence):
    sf = evidence["leagueFormatAlignment"]["statedFormat"]
    page = sf["idpTradeCalc"]["page"]
    assert page["statedIdpScoringBasis"] == "Big 3" and page["headline"] == "12-Team/.5 PPR"
    assert len(page["sha256"]) == 64 and page["bytes"] > 0
    big3 = sf["theIdpShowBig3"]
    assert big3["page"]["labelsMissing"] == [] and big3["sleeperCard"]["idp_sack"] == 5.0
    obs = sf["idpTradeCalc"]["archiveObserved"]["toggles"]
    assert obs["superflex"]["observed"] is True and obs["tePremium"]["observed"] is True


def test_verdict_in_evidence_matches_the_report(evidence):
    v = evidence["verdict"]
    assert v["answer"] in {"JUSTIFIED", "NOT_JUSTIFIED", "UNRESOLVED"}
    assert v["levelCorrectness"] == "UNRESOLVED"
    report = REPORT.read_text(encoding="utf-8")
    assert f"**Verdict on the shared-market anchor: {v['answer']}.**" in report
    for dotted in v["evidencePaths"]:
        node = evidence
        for part in dotted.split("."):
            assert isinstance(node, dict) and part in node, dotted
            node = node[part]
