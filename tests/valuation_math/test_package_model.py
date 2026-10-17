"""Package-model dispatch (owner package 2026-10-17).

Pins:
* the ACTIVE model is the KTC incumbent, identical in the committed config,
  the Python owner and the JS owner (one promotion point, both languages);
* the KTC path IS ``ktc_va_core.adjust_package_raw`` — routing every consumer
  through the dispatch changed no number;
* JS/Python parity on the shared fixture for every registered model;
* the incumbent's known non-monotone cases, pinned as KNOWN_DEFECT rather
  than "fixed" under the KTC label;
* the shadow challenger's structural guarantees with ZERO failures over a
  seeded random suite (the bar any promotion candidate must clear).
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

import pytest

from src.valuation_math import package_model as pm
from src.valuation_math.ktc_va_core import adjust_package_raw

REPO = Path(__file__).resolve().parents[2]
FIXTURE = json.loads(
    (REPO / "tests/fixtures/package_model_parity_cases.json").read_text(encoding="utf-8")
)


def _gap(a, b, model_id):
    value, side, displayed = pm.adjust_pair(a, b, model_id=model_id)
    va_a = value if displayed and side == 1 else 0
    va_b = value if displayed and side == 2 else 0
    return (sum(a) + va_a) - (sum(b) + va_b)


# ── one active model, one promotion point ──────────────────────────────


def test_active_model_is_the_incumbent_in_config_python_and_js():
    config = json.loads((REPO / "config/trade/package_model.json").read_text(encoding="utf-8"))
    assert config["active"] == pm.KTC_2026_04 == pm.active_model_id()
    js = (REPO / "frontend/lib/trade-logic.js").read_text(encoding="utf-8")
    m = re.search(r"export const ACTIVE_PACKAGE_MODEL_ID = PACKAGE_MODEL_IDS\.(\w+);", js)
    assert m and m.group(1) == "KTC_2026_04"
    assert pm.shadow_model_ids() == [pm.GEOM_Q078_V1]


def test_js_registry_mirrors_python_registry():
    js = (REPO / "frontend/lib/trade-logic.js").read_text(encoding="utf-8")
    for spec in pm.PACKAGE_MODELS.values():
        assert f'id: PACKAGE_MODEL_IDS.{spec["id"].upper()}' in js
        assert f'version: "{spec["version"]}"' in js
        assert spec["label"] in js
    assert "q: 0.78," in js


def test_receipt_names_the_model():
    r = pm.receipt()
    assert r == {
        "id": "ktc_2026_04",
        "family": "ktc",
        "version": "2026-04",
        "label": pm.PACKAGE_MODELS["ktc_2026_04"]["label"],
        "classification": "INCUMBENT",
    }
    assert pm.receipt(pm.GEOM_Q078_V1)["classification"] == "PRIOR"
    with pytest.raises(ValueError):
        pm.receipt("nope")


def test_unreadable_config_falls_back_to_the_incumbent(monkeypatch, tmp_path):
    bad = tmp_path / "package_model.json"
    bad.write_text('{"active": "geom_q999"}', encoding="utf-8")
    monkeypatch.setattr(pm, "_CONFIG_PATH", bad)
    pm._config.cache_clear()
    try:
        assert pm.active_model_id() == pm.KTC_2026_04
    finally:
        pm._config.cache_clear()


# ── incumbent unchanged ────────────────────────────────────────────────


def test_ktc_dispatch_is_exactly_the_incumbent_on_the_139_trade_fixture():
    obs = json.loads((REPO / "scripts/ktc_va_observations.json").read_text(encoding="utf-8"))
    trades = obs.get("observations") or obs.get("trades") or obs
    checked = 0
    for t in trades:
        a = t.get("team1") or t.get("team1Values") or t.get("side1")
        b = t.get("team2") or t.get("team2Values") or t.get("side2")
        if not a or not b:
            continue
        a = [x["value"] if isinstance(x, dict) else x for x in a]
        b = [x["value"] if isinstance(x, dict) else x for x in b]
        assert pm.adjust_pair(a, b, model_id=pm.KTC_2026_04) == adjust_package_raw(a, b)
        checked += 1
    assert checked >= 100


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda c: f"{c['team1']}v{c['team2']}"[:60])
def test_js_python_parity(case):
    for model_id, expected in case["expected"].items():
        assert list(pm.adjust_pair(case["team1"], case["team2"], model_id=model_id)) == expected


# ── incumbent known defects (pinned, not fixed under the KTC label) ────


def test_known_defect_adding_a_positive_asset_worsens_the_adding_side():
    # Raw and adjusted gap A +1200; B adds a 500 asset and A's lead GROWS.
    assert _gap([7200], [6000], pm.KTC_2026_04) == 1200
    assert pm.adjust_pair([7200], [6000, 500], model_id=pm.KTC_2026_04) == (2900, 1, True)
    assert _gap([7200], [6000, 500], pm.KTC_2026_04) == 3600
    # A one-point addition does it too.
    assert _gap([7200], [6000, 1], pm.KTC_2026_04) > 1200
    assert _gap([9000], [8500, 1], pm.KTC_2026_04) > _gap([9000], [8500], pm.KTC_2026_04)


def test_known_defect_twelve_lesser_assets_beat_an_elite_one_under_ktc():
    assert _gap([9000], [2000] * 12, pm.KTC_2026_04) < 0


# ── challenger structural guarantees: zero failures ────────────────────


def test_geom_matches_the_closed_form():
    # U_A = 7200; U_B = 6000 + .78 * 500 = 6390; gap = 810.
    assert _gap([7200], [6000, 500], pm.GEOM_Q078_V1) == 810
    assert pm.adjust_pair([7200], [6000], model_id=pm.GEOM_Q078_V1) == (0, 0, False)
    assert _gap([9000], [2000] * 12, pm.GEOM_Q078_V1) > 0
    assert _gap([9000], [2500] * 12, pm.GEOM_Q078_V1) < 0


def _random_side(rng):
    return [rng.randint(500, 9999) for _ in range(rng.randint(1, 4))]


def test_geom_has_zero_structural_failures_on_a_seeded_suite():
    rng = random.Random(98231)
    failures = {"addA": 0, "addB": 0, "raiseB": 0, "swap": 0, "order": 0, "scale": 0}
    tol = 1  # integer rounding of the displayed adjustment
    for _ in range(5000):
        a, b = _random_side(rng), _random_side(rng)
        g = _gap(a, b, pm.GEOM_Q078_V1)
        x = rng.randint(1, 3000)
        if _gap(a + [x], b, pm.GEOM_Q078_V1) < g - tol:
            failures["addA"] += 1
        if _gap(a, b + [x], pm.GEOM_Q078_V1) > g + tol:
            failures["addB"] += 1
        raised = list(b)
        raised[rng.randrange(len(raised))] += rng.randint(1, 2000)
        if _gap(a, raised, pm.GEOM_Q078_V1) > g + tol:
            failures["raiseB"] += 1
        if abs(_gap(b, a, pm.GEOM_Q078_V1) + g) > tol:
            failures["swap"] += 1
        if abs(_gap(list(reversed(a)), b[::-1], pm.GEOM_Q078_V1) - g) > tol:
            failures["order"] += 1
        if abs(_gap([2 * v for v in a], [2 * v for v in b], pm.GEOM_Q078_V1) - 2 * g) > 2 * tol:
            failures["scale"] += 1
    assert failures == dict.fromkeys(failures, 0)


def test_ktc_is_not_monotone_on_the_same_suite():
    """The contrast that motivates the challenger, measured — not asserted away."""
    rng = random.Random(98231)
    worsened = 0
    for _ in range(2000):
        a, b = _random_side(rng), _random_side(rng)
        if _gap(a, b + [rng.randint(1, 3000)], pm.KTC_2026_04) > _gap(a, b, pm.KTC_2026_04) + 1:
            worsened += 1
    assert worsened > 0


def test_adjusted_pair_totals_matches_ktc_va_for_the_incumbent():
    from src.trade import ktc_va

    for case in FIXTURE["cases"]:
        a, b = case["team1"], case["team2"]
        assert pm.adjusted_pair_totals(a, b) == ktc_va.adjusted_pair_totals(a, b)


# ── no consumer bypasses the dispatch ──────────────────────────────────

#: Callers allowed to name KTC directly, each because it IS a KTC-named
#: surface rather than a package-equity consumer:
#: * the owners themselves and the legacy re-export shim;
#: * ``trade_grading.ktc_adjust_package`` — the KTC reference helper the
#:   parity fixture's real keeptradecut.com captures (``vaEngineCases``) pin;
#: * ``cross_market`` — its MARKET_KTC lens is literally "KTC's published
#:   package rule applied to that calculator's own values".
_KTC_DIRECT_ALLOWED = {
    "src/valuation_math/ktc_va_core.py",
    "src/valuation_math/package_model.py",
    "src/trade/ktc_va.py",
    "src/trade/market_value_adjustment.py",
    "src/public_league/trade_grading.py",
    "src/league_intel/cross_market.py",
}


def test_no_python_consumer_calls_ktc_directly():
    offenders = []
    for path in (REPO / "src").rglob("*.py"):
        rel = path.relative_to(REPO).as_posix()
        if rel in _KTC_DIRECT_ALLOWED:
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(
            r"\b(adjust_package_raw|ktc_adjust_package|adjusted_pair_totals)\s*\(", text
        ) and ("ktc_va" in text and "package_model" not in text):
            offenders.append(rel)
        if re.search(r"from src\.trade\.ktc_va import[^\n]*adjusted_pair_totals", text):
            offenders.append(rel)
    assert offenders == []


def test_no_js_consumer_calls_ktc_directly():
    offenders = []
    for sub in ("lib", "components", "app"):
        for path in (REPO / "frontend" / sub).rglob("*.js*"):
            rel = path.relative_to(REPO).as_posix()
            if rel == "frontend/lib/trade-logic.js":
                continue
            code = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
            code = re.sub(r"//[^\n]*", "", code)
            if re.search(r"\bktcAdjustPackage\s*\(", code):
                offenders.append(rel)
    assert offenders == []
