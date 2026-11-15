"""Package VA Phases 1-3 re-measured under fairness_bands_v2 (2026-10-21): the band switch.

``docs/valuation/PACKAGE_MODEL_PHASES_1_3_V2_REMEASURE_2026-10-21.md``.  The phase
scripts classify through ``package_model_hybrid_research.band_level``; these tests pin
that

* its DEFAULT is the recorded v1 basis, identical to the retired helper on every model,
  so the frozen scripts still reproduce their committed evidence;
* its ``current`` basis is the fairness-band owner: the incumbent through
  ``classify_packages``, KTC through the owner's ``larger_package_utility``, any other
  model on its own package utilities, and no research-side threshold;
* every Phase 1-3 model has a band rule, and the basis scope always restores;
* the driver never writes into an original evidence directory, and its Trade Finder
  re-tag reproduces ``FR.classify`` exactly on v1.
"""

from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"

_MODULES = (
    "package_model_v2_remeasure",
    "package_model_phase3_local",
    "package_model_phase3_research",
    "package_model_phase2_research",
    "package_model_hybrid_research",
    "package_model_finder_replay",
    "research_pinned_board",
    "research_readonly_guard",
)


@pytest.fixture(scope="module")
def R():
    saved = {n: sys.modules.get(n) for n in _MODULES}
    spec = importlib.util.spec_from_file_location(
        "package_model_v2_remeasure", SCRIPTS / "package_model_v2_remeasure.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["package_model_v2_remeasure"] = mod
    spec.loader.exec_module(mod)
    yield mod
    for n, m in saved.items():
        if m is None:
            sys.modules.pop(n, None)
        else:
            sys.modules[n] = m


def _trades(n=250, seed=20261021):
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        a = [float(rng.randint(300, 9500)) for _ in range(rng.randint(1, 3))]
        b = [float(rng.randint(300, 9500)) for _ in range(rng.randint(1, 7))]
        out.append((a, b))
    return out


def _all_models(R):
    models = dict(R.P1.MODELS)
    models.update(R.P2.MODELS)
    models.update(R.P3L.build_models())
    return models


def test_default_basis_is_the_recorded_v1(R):
    assert R.P1.current_band_basis() == "v1_legacy"
    assert R.P1.FAIRNESS_BAND_BASIS == "v1_legacy"


def test_v1_basis_equals_the_retired_helper_on_every_model(R):
    for name, spec in _all_models(R).items():
        for A, B in _trades(60):
            g = spec["gap"](A, B)
            ra, rb = sum(A), sum(B)
            adj = (ra + max(0.0, g - (ra - rb)), rb + max(0.0, (ra - rb) - g))
            assert R.P1.band_level(name, g, A, B) == R.P1.level_v1_legacy(g, *adj), name


def test_every_phase_model_has_a_band_rule(R):
    for name in _all_models(R):
        assert (
            name in ("GEOM_78", "KTC") or name.startswith("BLEND_") or name in R.P1.BAND_UTILITY
        ), name


def test_current_basis_is_the_owner(R):
    from src.valuation_math import fairness_bands, package_model

    models = _all_models(R)
    for A, B in _trades():
        g = models["GEOM_78"]["gap"](A, B)
        assert (
            R.P1.band_level("GEOM_78", g, A, B, basis="current")
            == fairness_bands.classify_packages(g, A, B)["level"]
        )
        gk = models["KTC"]["gap"](A, B)
        base = fairness_bands.larger_package_utility(A, B, model_id=package_model.KTC_2026_04)
        assert (
            R.P1.band_level("KTC", gk, A, B, basis="current")
            == fairness_bands.classify(gk, base)["level"]
        )
        for name in ("LP_150", "HYBRID_50", "FGEOM_70_20", "EFD_78", "GP_078_150"):
            u = R.P1.BAND_UTILITY[name]
            gm = models[name]["gap"](A, B)
            want = fairness_bands.classify(gm, fairness_bands.fairness_base((u(A), u(B))))
            assert R.P1.band_level(name, gm, A, B, basis="current") == want["level"]
            # the utility model's gap IS the utility difference, so numerator and base share a scale
            assert abs(gm - (u(A) - u(B))) <= 1e-6 * max(1.0, sum(A), sum(B))


def test_the_two_bases_really_differ_on_a_deep_package(R):
    A, B = [5313.0, 4590.0], [2111.0, 2912.0, 641.0, 2467.0, 1494.0]
    g = R.P1.MODELS["GEOM_78"]["gap"](A, B)
    assert R.P1.band_level("GEOM_78", g, A, B, basis="v1_legacy") == "unfair"
    assert R.P1.band_level("GEOM_78", g, A, B, basis="current") == "lopsided"


def test_band_basis_scope_restores_and_refuses_unknown(R):
    with R.P1.band_basis("current"):
        assert R.P1.current_band_basis() == "current"
    assert R.P1.current_band_basis() == "v1_legacy"
    with pytest.raises(ValueError):
        with R.P1.band_basis("bogus"):
            pass
    with pytest.raises(ValueError):
        R.P1.band_level("GEOM_78", 1.0, [2.0], [1.0], basis="bogus")
    with pytest.raises(RuntimeError):
        with R.P1.band_basis("current"):
            raise RuntimeError("boom")
    assert R.P1.current_band_basis() == "v1_legacy"


def test_band_level_computes_no_threshold():
    src = (SCRIPTS / "package_model_hybrid_research.py").read_text(encoding="utf-8")
    body = src.split("def band_level", 1)[1].split("\n\n\n", 1)[0]
    for literal in ("0.035", "3.5", "SLIGHT_PCT", "ABSOLUTE_MINIMUM", "250"):
        assert literal not in body, literal


def test_driver_never_writes_into_an_original_evidence_dir(R, monkeypatch, tmp_path):
    for pin in R.PINS.values():
        assert "package_model_v2_remeasure" not in str(pin["recorded"])
    monkeypatch.setattr(
        sys,
        "argv",
        ["x", "--phase", "3", "--out", "docs/valuation/evidence/package_model_phase3_2026-10-20"],
    )
    with pytest.raises(AssertionError, match="original evidence"):
        R.main()


def test_retag_reproduces_fr_classify_on_v1_and_moves_only_band_tags(R):
    models = R.P2.MODELS
    rng = random.Random(7)
    raw = {}
    for mid in R.FR.DEFAULT_MODELS:
        trades = []
        for i in range(40):
            give = [(f"g{i}{j}", float(rng.randint(400, 9800))) for j in range(rng.randint(1, 3))]
            recv = [(f"r{i}{j}", float(rng.randint(400, 9800))) for j in range(rng.randint(1, 4))]
            x = {"give": [{"name": n, "value": v} for n, v in give],
                 "receive": [{"name": n, "value": v} for n, v in recv]}  # fmt: skip
            tags = R.FR.classify(x, R._replay_gap(models, mid), R.P2.level)
            trades.append({"key": str(i), "give": give, "receive": recv, "tags": tags})
        raw[mid] = {"s": {"t": {"keys": [t["key"] for t in trades], "trades": trades,
                                "enumeration": None}}}  # fmt: skip
    replay = {"models": list(raw), "surfaces": ["s"], "teams": ["t"], "raw": raw}
    v1, changed = R.retag(replay, models, "v1_legacy")
    assert changed == 0
    v2, _ = R.retag(replay, models, "current")
    for mid in raw:
        for t1, t2 in zip(v1["raw"][mid]["s"]["t"]["trades"], v2["raw"][mid]["s"]["t"]["trades"]):
            for k in ("sensibleDepth", "multiPiece3plus", "elite", "shape", "priced"):
                assert t1["tags"][k] == t2["tags"][k]
