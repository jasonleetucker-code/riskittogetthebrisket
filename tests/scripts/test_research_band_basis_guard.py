"""Research scripts take fairness levels from the owner, except a short, annotated allow-list.

Context (``docs/valuation/LOW_VALUE_ASSET_V2_CORRECTION_2026-10-21.md``): the
low-value-asset filler-flip study reached ``package_model_hybrid_research.level`` --
the retired fairness_bands_v1 denominator (the larger ADJUSTED side) -- through a
chain of research modules and went unnoticed after the owner moved to
fairness_bands_v2 (the larger PACKAGE UTILITY).  The bug was a research script
passing the owner's ``classify`` a base the owner did not compute.

This guard does not add a second fairness formula.  It checks that:

* a script outside ``V1_LEGACY_ALLOWLIST`` neither loads a research module that
  exposes the legacy level, nor names the legacy helpers, nor passes an
  adjusted-side / ``max(...)`` base to an owner band call (the same detector that
  guards ``src/``: ``test_fairness_bands._py_offenders``);
* every allow-list entry still exists and still trips a detector, so the list
  cannot rot into a blanket exemption;
* the legacy helper is named and documented as legacy;
* the low-value-asset replay's DEFAULT basis is the owner and never reaches the
  legacy helper.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"

#: Research modules that expose / wrap the retired v1 level helper.
LEGACY_MODULES = frozenset(
    {
        "package_model_hybrid_research",
        "package_model_phase2_research",
        "package_model_phase3_local",
        "package_model_phase3_research",
    }
)
#: Names that exist only to reproduce v1.
LEGACY_NAMES = frozenset({"level_v1_legacy", "legacy_v1_denominator"})

#: scripts that intentionally keep (or can reproduce) the v1 basis.  Every entry says why.
V1_LEGACY_ALLOWLIST: dict[str, str] = {
    "package_model_hybrid_research.py": "defines the legacy helper; Phase 1 evidence (2026-10-19) "
    "was measured on the v1 denominator and is preserved as recorded",
    "package_model_phase2_research.py": "Phase 2 frozen research (2026-10-19), v1 as recorded",
    "package_model_phase3_local.py": "Phase 3 local lane (2026-10-20), v1 as recorded; also the "
    "board/archive loader the low-value replay reuses",
    "package_model_phase3_research.py": "Phase 3 frozen research, v1 as recorded",
    "low_value_asset_box.py": "owner-run confirmatory box script, code pinned for the 2026-10-20 "
    "run; it loads the Phase 3 module for its read-only guard and board loader and classifies no "
    "fairness band",
    "low_value_asset_shadow_replay.py": "DEFAULT basis is the owner (--band-basis current); the "
    "legacy helper is reachable only behind --band-basis v1_legacy, to reproduce the recorded "
    "2026-10-20 evidence",
    "low_value_asset_forced_drop_diagnostic.py": "loads the replay; --band-basis v1_legacy wraps "
    "the engine in legacy_v1_denominator() to reproduce the recorded evidence; default is current",
    "package_model_v2_remeasure.py": "Package VA Phases 1-3 re-measurement (2026-10-21): runs each "
    "band-dependent section on v1_legacy ONLY to reproduce the recorded evidence, and on current "
    "(fairness_bands_v2, the owner) for the result; it loads the frozen phase modules to do so",
    "package_model_v2_remeasure_extract.py": "runs INSIDE a detached checkout of a recorded "
    "revision and loads THAT revision's phase scripts to rebuild the recorded board / Finder "
    "replay as plain values; it classifies no band (the driver re-tags on both bases)",
}

_BAND_CALLS = ("classify", "is_even", "relative_pct", "fair_threshold")


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _references_legacy(path: Path) -> list[str]:
    """Reasons ``path`` reaches the legacy level helper (module load or name)."""
    hits: list[str] = []
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            hits += [f"import {a.name}" for a in node.names if a.name in LEGACY_MODULES]
        elif isinstance(node, ast.ImportFrom):
            if node.module in LEGACY_MODULES:
                hits.append(f"from {node.module} import ...")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # a module name anywhere in a path-like string ("scripts/package_model_x.py") loads it
            if (
                len(node.value) < 160
                and not any(c.isspace() for c in node.value)
                and any(mod in node.value for mod in LEGACY_MODULES)
            ):
                hits.append(f"loads {node.value!r}")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "level"
        ):
            # ``<module>.P1.level(...)`` is the retired v1 helper under its kept alias
            hits.append(".level(...) call (retired v1 alias)")
        elif isinstance(node, ast.Attribute) and node.attr in LEGACY_NAMES:
            hits.append(f".{node.attr}")
        elif isinstance(node, ast.Name) and node.id in LEGACY_NAMES:
            hits.append(node.id)
    return hits


def _band_offenders(path: Path) -> list[str]:
    """An owner band call whose base is an adjusted side / ``max(...)`` (the same
    detector that guards ``src/``).

    Limit: a base routed through a variable (``larger = max(a, b); classify(g, larger)``) is not
    detected; the same limit applies to the ``src/`` detector this reuses.
    """
    detector = _load_detector()
    return detector(path.read_text(encoding="utf-8"), path.name)


_DETECTOR = None


def _load_detector():
    global _DETECTOR
    if _DETECTOR is None:
        path = REPO / "tests" / "valuation_math" / "test_fairness_bands.py"
        spec = importlib.util.spec_from_file_location("_fairness_bands_detector", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _DETECTOR = mod._py_offenders
    return _DETECTOR


def _all_scripts() -> list[Path]:
    return sorted(SCRIPTS.glob("*.py"))


def test_no_unlisted_script_reaches_the_v1_legacy_basis():
    offenders = []
    for path in _all_scripts():
        if path.name in V1_LEGACY_ALLOWLIST:
            continue
        reasons = _references_legacy(path) + _band_offenders(path)
        if reasons:
            offenders.append(f"{path.name}: {sorted(set(map(str, reasons)))}")
    assert not offenders, (
        "research must obtain fairness levels from the fairness-band owner "
        "(fairness_bands.classify_packages / fairness_base + classify).  If a script "
        "intentionally reproduces v1 evidence, add it to V1_LEGACY_ALLOWLIST with its reason:\n"
        + "\n".join(offenders)
    )


def test_allowlist_has_no_stale_entries():
    for name, reason in V1_LEGACY_ALLOWLIST.items():
        path = SCRIPTS / name
        assert path.exists(), f"{name}: allow-listed script is gone; remove the entry"
        assert reason.strip(), f"{name}: an allow-list entry needs a reason"
        assert _references_legacy(path) or _band_offenders(
            path
        ), f"{name} no longer reaches the legacy basis; remove it from the allow-list"


def test_the_detector_fires_on_a_decoy():
    decoy = (
        "from src.valuation_math import fairness_bands\n"
        "fairness_bands.classify(g, max(adj_a, adj_b))\n"
    )
    assert _load_detector()(decoy, "decoy.py")
    assert not _load_detector()(
        "fairness_bands.classify(g, fairness_bands.fairness_base(utils))\n", "ok.py"
    )


def test_a_script_loading_a_legacy_module_is_caught(tmp_path):
    p = tmp_path / "decoy_script.py"
    p.write_text(
        'P1 = _load("package_model_hybrid_research")\nP1.level_v1_legacy(1, 2, 3)\n',
        encoding="utf-8",
    )
    assert _references_legacy(p)
    q = tmp_path / "clean_script.py"
    q.write_text(
        "from src.valuation_math import fairness_bands\nfairness_bands.receipt()\n",
        encoding="utf-8",
    )
    assert not _references_legacy(q)


# ── the legacy helper is named and documented as legacy ──────────────────


def _load_script(name: str):
    path = SCRIPTS / f"{name}.py"
    saved = sys.modules.get(name)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        if saved is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = saved
    return mod


@pytest.fixture(scope="module")
def hybrid():
    return _load_script("package_model_hybrid_research")


def test_legacy_helper_is_named_and_marked_legacy(hybrid):
    assert hybrid.FAIRNESS_BAND_BASIS == "v1_legacy"
    doc = hybrid.level_v1_legacy.__doc__ or ""
    assert "LEGACY" in doc and "fairness_bands_v1" in doc
    # the historical name is an alias of the legacy function, not a second definition
    assert hybrid.level is hybrid.level_v1_legacy
    assert "LEGACY" in (hybrid.legacy_v1_denominator.__doc__ or "")


def test_legacy_denominator_context_is_scoped_and_restores_the_owner(hybrid):
    from src.valuation_math import fairness_bands, package_model

    a, b = [5313.0, 4590.0], [2111.0, 2912.0, 641.0, 2467.0, 1494.0]
    owner = fairness_bands.larger_package_utility
    v2_base = owner(a, b)
    a_adj, b_adj, _, _ = package_model.adjusted_pair_totals(a, b)
    with hybrid.legacy_v1_denominator():
        assert fairness_bands.larger_package_utility(a, b) == max(a_adj, b_adj)
    assert fairness_bands.larger_package_utility is owner
    assert owner(a, b) == v2_base
    assert v2_base < max(a_adj, b_adj)  # the two denominators really differ on a deep package


# ── the replay: owner by default, never the legacy helper ────────────────

_REPLAY_MODULES = (
    "low_value_asset_shadow_replay",
    "low_value_asset_treatments",
    "research_pinned_board",
    "package_model_phase3_local",
    "package_model_phase3_research",
    "package_model_phase2_research",
    "package_model_hybrid_research",
    "package_model_finder_replay",
    "research_readonly_guard",
)


@pytest.fixture(scope="module")
def replay():
    saved = {n: sys.modules.get(n) for n in _REPLAY_MODULES}
    spec = importlib.util.spec_from_file_location(
        "low_value_asset_shadow_replay", SCRIPTS / "low_value_asset_shadow_replay.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["low_value_asset_shadow_replay"] = mod
    spec.loader.exec_module(mod)
    yield mod
    for n, m in saved.items():
        if m is None:
            sys.modules.pop(n, None)
        else:
            sys.modules[n] = m


_DEEP = (
    [(5313.0, "WR"), (4590.0, "RB")],
    [(2111.0, "WR"), (2912.0, "RB"), (641.0, "WR"), (2467.0, "TE"), (1494.0, "WR")],
)


def test_replay_declares_and_defaults_to_the_owner_basis(replay):
    assert replay.FAIRNESS_BAND_BASIS == "current_owner"
    assert replay.BAND_BASIS == "current"
    assert replay.BAND_BASES == ("current", "v1_legacy")


def test_replay_current_verdict_is_the_owner_and_never_touches_the_legacy_helper(
    replay, monkeypatch
):
    from src.valuation_math import fairness_bands

    def boom(*_a, **_k):
        raise AssertionError("the current basis must not call the legacy level helper")

    monkeypatch.setattr(replay.P1, "level_v1_legacy", boom)
    A, B = _DEEP
    rep = {"*": replay.T.MARKET_LEVEL}
    v = replay.verdict(replay.INCUMBENT, A, B, rep)  # default basis
    owner = fairness_bands.classify_packages(v["gap"], [x for x, _ in A], [x for x, _ in B])
    assert v["level"] == owner["level"] == "lopsided"
    # a comparator treatment is classified on ITS OWN package utilities through the owner
    t = "B_currency_market"
    vt = replay.verdict(t, A, B, rep)
    base = fairness_bands.fairness_base(replay._treatment_utilities(t, A, B, rep))
    assert vt["level"] == fairness_bands.classify(vt["gap"], base)["level"]


def test_replay_v1_legacy_basis_reproduces_the_retired_denominator(replay):
    A, B = _DEEP
    rep = {"*": replay.T.MARKET_LEVEL}
    assert replay.verdict(replay.INCUMBENT, A, B, rep, basis="v1_legacy")["level"] == "unfair"
    assert replay.verdict(replay.INCUMBENT, A, B, rep, basis="current")["level"] == "lopsided"
    with pytest.raises(ValueError):
        replay.verdict(replay.INCUMBENT, A, B, rep, basis="bogus")


def test_replay_incumbent_gap_and_level_equal_the_package_model_and_the_owner(replay):
    import random

    from src.valuation_math import fairness_bands, package_model

    q = package_model.PACKAGE_MODELS[package_model.active_model_id()]["q"]
    rng = random.Random(20261021)
    rep = {"*": replay.T.MARKET_LEVEL}
    for _ in range(300):
        a = [float(rng.randint(300, 9000)) for _ in range(rng.randint(1, 3))]
        b = [float(rng.randint(300, 9000)) for _ in range(rng.randint(1, 6))]
        v = replay.verdict(replay.INCUMBENT, [(x, None) for x in a], [(x, None) for x in b], rep)
        canonical = package_model.geom_utility(a, q) - package_model.geom_utility(b, q)
        assert abs(v["gap"] - canonical) <= 1e-9 * max(1.0, sum(a), sum(b))
        assert v["level"] == fairness_bands.classify_packages(canonical, a, b)["level"]


def test_replay_source_computes_no_band_threshold_or_denominator():
    src = (SCRIPTS / "low_value_asset_shadow_replay.py").read_text(encoding="utf-8")
    for literal in (r"\b0\.035\b", r"\b3\.5\b", r"\bSLIGHT_PCT\b", r"\bABSOLUTE_MINIMUM\b"):
        assert not re.search(literal, src), literal
