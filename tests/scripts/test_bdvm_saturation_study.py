"""Pins for the W13-F003 offline study (``scripts/research/bdvm_saturation_study.py``).

The study is research only (NOT ACTIVATED).  These tests pin three things:

1. its incumbent re-derivation reproduces the PRODUCTION ``market_comparison`` +
   ``buy_hold_sell`` labels row for row on the audit's frozen run (so every
   candidate is compared against the real incumbent, not a paraphrase of it);
2. its candidate arithmetic agrees with independent oracles written here in
   plain Python (brute-force quantile map, grid-searched exponent), and the C2
   labels agree with the production ladder fed the oracle-mapped values;
3. the headline numbers the proposal document quotes
   (``docs/valuation/methodology_proposals/W13_F003_BDVM_SIGNAL_SATURATION.md``).

It also guards the study's independence: it must not import the BDVM code it
evaluates.
"""

from __future__ import annotations

import ast
import json
from collections import Counter
from pathlib import Path

import pytest

from scripts.research import bdvm_saturation_study as study

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "research" / "bdvm_saturation_study.py"
EVIDENCE = study.DEFAULT_EVIDENCE
ARCHIVE = study.DEFAULT_ARCHIVE
IDP_GROUPS = ("DL", "LB", "DB")

pytestmark = pytest.mark.skipif(not EVIDENCE.exists(), reason="recorded W13 engine run absent")


@pytest.fixture(scope="module")
def study_state():
    params = study.load_params(study.DEFAULT_PARAMS)
    rows, facts = study.load_rows(EVIDENCE)
    res = study.run_candidates(rows, params, facts["dvMaxAllPriced"])
    return params, rows, facts, res


def _production_label(tv_balanced: float, player: dict, prod_params) -> str:
    from src.bdvm.market import MarketView, buy_hold_sell, market_comparison

    m = player["market"]
    view = MarketView(
        market_value=m["marketValue"],
        market_source=m["marketSource"],
        market_type=m["marketType"],
        dispersion=m["marketDispersion"],
        liquidity=m["liquidity"],
    )
    out = market_comparison(
        {"balanced": tv_balanced},
        view,
        prod_params,
        is_idp=player["group"] in IDP_GROUPS,
        is_rookie=bool((player.get("projection") or {}).get("isRookie")),
    )
    sig = buy_hold_sell(
        out, prod_params, p_collapse_1y=(player.get("probs") or {}).get("p_value_collapse_1y")
    )
    return sig["signal"]


def _anchored_players_by_key() -> dict[tuple[str, str], dict]:
    data = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    return {
        (p["name"], str(p.get("playerId") or "")): p
        for p in data["players"]
        if (p.get("market") or {}).get("marketValue") is not None
    }


def test_incumbent_rederivation_matches_production_row_for_row(study_state):
    from src.bdvm.params import load_param_set

    _, rows, facts, res = study_state
    prod_params = load_param_set("params_v1")
    players = _anchored_players_by_key()
    assert len(rows) == len(players) == 676
    mismatches = []
    for row, label in zip(rows, res["labels"]["C0"]):
        p = players[(row["name"], row["playerId"])]
        prod = _production_label(p["tradeValue"]["balanced"], p, prod_params)
        if prod != label:
            mismatches.append((row["name"], prod, label))
    assert mismatches == []
    # ...and both equal the audit's recorded counts (W13-F003).
    assert study.label_counts(res["labels"]["C0"]) == {
        "STRONG_BUY": 10,
        "BUY": 14,
        "HOLD": 69,
        "SELL": 13,
        "STRONG_SELL": 570,
    }
    assert facts["noMarketRows"] == 23


def _oracle_quantile_map(values: list[float], reference: list[float]) -> list[float]:
    """Brute force: mid-rank percentile by counting, then manual interpolation."""
    n = len(values)
    ref = sorted(reference)
    m = len(ref)
    pos = [(k + 0.5) / m for k in range(m)]
    out = []
    for v in values:
        less = sum(1 for w in values if w < v)
        equal = sum(1 for w in values if w == v)
        p = (less + equal / 2.0) / n
        if p <= pos[0]:
            out.append(ref[0])
            continue
        if p >= pos[-1]:
            out.append(ref[-1])
            continue
        k = 0
        while pos[k + 1] < p:
            k += 1
        t = (p - pos[k]) / (pos[k + 1] - pos[k])
        out.append(ref[k] + t * (ref[k + 1] - ref[k]))
    return out


def test_quantile_map_candidates_match_bruteforce_oracle(study_state):
    _, rows, _, res = study_state
    tv = [row["tv"] for row in rows]
    market = [row["market"] for row in rows]
    pooled = _oracle_quantile_map(tv, market)
    assert max(abs(a - b) for a, b in zip(pooled, res["tv"]["C2"])) < 1e-6
    for source in study.MARKET_SOURCES:
        idx = [i for i, row in enumerate(rows) if row["source"] == source]
        mapped = _oracle_quantile_map([tv[i] for i in idx], [market[i] for i in idx])
        assert max(abs(mapped[j] - res["tv"]["C3"][i]) for j, i in enumerate(idx)) < 1e-6


def test_c2_labels_match_production_ladder_fed_oracle_values(study_state):
    from src.bdvm.params import load_param_set

    _, rows, _, res = study_state
    prod_params = load_param_set("params_v1")
    players = _anchored_players_by_key()
    mapped = _oracle_quantile_map([row["tv"] for row in rows], [row["market"] for row in rows])
    prod_labels = [
        _production_label(t, players[(row["name"], row["playerId"])], prod_params)
        for t, row in zip(mapped, rows)
    ]
    assert prod_labels == res["labels"]["C2"]
    assert Counter(prod_labels) == {
        "STRONG_BUY": 131,
        "BUY": 78,
        "HOLD": 225,
        "SELL": 18,
        "STRONG_SELL": 224,
    }


def test_spec_gamma_matches_grid_search_oracle(study_state):
    _, rows, _, res = study_state
    import math

    dv = sorted((row["dv"] for row in rows), reverse=True)[: study.GAMMA_FIT_TOP_K]
    mk = sorted((row["market"] for row in rows), reverse=True)[: study.GAMMA_FIT_TOP_K]
    ld = [math.log(x / dv[0]) for x in dv[1:]]
    lm = [math.log(x / mk[0]) for x in mk[1:]]
    best = min(
        (sum((b - g * a) ** 2 for a, b in zip(ld, lm)), g)
        for g in (i / 10000.0 for i in range(3000, 15001))
    )[1]
    assert abs(best - res["gammaStar"]) < 2e-4
    assert round(res["gammaStar"], 4) == 0.5452  # spec prior is 1.20


def test_shape_component_alone_reproduces_the_saturation(study_state):
    params, rows, facts, res = study_state
    diag = study.diagnostics(rows, res, params, facts["dvMaxAllPriced"])
    dec = diag["decomposition"]
    # The level/curve component is negative on every row and alone yields a
    # STRONG_SELL on 675 of 676; the rank-disagreement component is centred.
    assert dec["shapeShareNegative"] == 1.0
    assert dec["signalsIfShapeOnly"]["STRONG_SELL"] == 675
    assert dec["rankMedian"] == -49.5
    assert dec["shapeMedian"] == -1315.8
    assert diag["board"]["spearmanIncumbentAlphaMarket"] == -0.7482
    # Liquidity does not drive it: forcing liquidity to 1.0 moves one row.
    assert diag["liquidity"]["signalsWithLiquidityForcedTo1"]["C0"]["STRONG_SELL"] == 571


def test_c5_is_three_state_and_abstains_on_most_rows(study_state):
    _, rows, _, res = study_state
    counts = study.label_counts(res["labels"]["C5"])
    assert counts["STRONG_BUY"] == counts["STRONG_SELL"] == 0
    assert counts == {"STRONG_BUY": 0, "BUY": 83, "HOLD": 526, "SELL": 67, "STRONG_SELL": 0}


@pytest.mark.skipif(
    study.archive_on_or_after(ARCHIVE, "20261102") is None,
    reason="committed export archive absent",
)
def test_outcome_evaluation_numbers_quoted_by_the_proposal():
    report, table = study.build_report(
        EVIDENCE, study.DEFAULT_PARAMS, ARCHIVE, n_boot=0, seed=20261107
    )
    assert len(table) == 676
    ev = report["evaluation"]
    assert ev["30"]["archive"] == "dynasty_export_20260903_225148.zip"
    assert ev["90"]["archive"] == "dynasty_export_20261102_015256.zip"
    assert ev["30"]["censored"] == 22

    def metric(h, c, k):
        return ev[h]["candidates"][c][k]

    assert metric("30", "C0", "spearman") == pytest.approx(-0.2078, abs=1e-3)
    assert metric("30", "C2", "spearman") == pytest.approx(-0.1219, abs=1e-3)
    assert metric("30", "C0", "partialSpearmanGivenMarketRank") == pytest.approx(-0.0673, abs=1e-3)
    assert metric("30", "C2", "partialSpearmanGivenMarketRank") == pytest.approx(-0.0310, abs=1e-3)
    assert metric("30", "C5", "partialSpearmanGivenMarketRank") == pytest.approx(0.0131, abs=1e-3)
    assert metric("90", "C2", "partialSpearmanGivenMarketRank") == pytest.approx(0.0076, abs=1e-3)
    # C4 (percentile thresholds on the incumbent alpha) points the wrong way.
    assert metric("30", "C4", "longShortSpread") == pytest.approx(-0.0281, abs=1e-3)
    assert report["alertTransitionsAtSwitch"]["C2"] == 216


def test_study_does_not_import_the_code_it_evaluates():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    src_imports = {m for m in imported if m == "src" or m.startswith("src.")}
    assert src_imports == {"src.utils.name_clean"}
    assert "feature_flags" not in SCRIPT.read_text(encoding="utf-8")
