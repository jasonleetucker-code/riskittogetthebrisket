"""B-Series Completion Audit — structural verification against current main.

Every check answers a requirement from the audit scope with an
observation of the live tree, not with a claim.
"""

import inspect
import json
import sys
from pathlib import Path

sys.path.insert(0, "/home/user/riskittogetthebrisket")
ROOT = Path("/home/user/riskittogetthebrisket")

results = []


def check(area, requirement, fn):
    try:
        ok, detail = fn()
    except Exception as exc:  # noqa: BLE001 - an audit reports its own failures
        ok, detail = False, f"check raised: {type(exc).__name__}: {exc}"
    results.append((area, requirement, ok, detail))


import src.api.data_contract as dc  # noqa: E402
from src.api import confidence as conf  # noqa: E402

DC_SRC = (ROOT / "src" / "api" / "data_contract.py").read_text(encoding="utf-8")


# ── A. Canonical valuation ownership ───────────────────────────────────
def a_one_value():
    """Observe the BUILT board, not the source text.

    A substring search reports the comment that documents the removal.
    The question is whether any row carries a second canonical value.
    """
    gone = not hasattr(dc, "apply_valuation_factors")
    payload = json.loads(
        (ROOT / "exports" / "latest" / "dynasty_data_2026-08-14.json").read_text(encoding="utf-8")
    )
    rows = dc.build_api_data_contract(payload)["playersArray"]
    second = {k for r in rows for k in r if "offenseOnly" in k or "ExperimentalValue" in k}
    return (gone and not second), (
        f"apply_valuation_factors absent={gone}; second-value keys on {len(rows)} live rows: "
        f"{sorted(second) or 'none'}"
    )


def a_scale_owner():
    from src.canonical.player_valuation import DISPLAY_SCALE_MAX, DISPLAY_SCALE_MIN

    imported = "DISPLAY_SCALE_MAX as _CANONICAL_VALUE_MAX" in DC_SRC
    return (
        imported,
        f"scale imported from player_valuation ({DISPLAY_SCALE_MIN}-{DISPLAY_SCALE_MAX}), not restated: {imported}",
    )


def a_lens_withdrawn():
    """The stamp lives where the REQUEST is answered — server.py."""
    server = (ROOT / "server.py").read_text(encoding="utf-8")
    stamped = server.count("league_adjusted_withdrawn: not_canonical")
    no_seam = "valuation_factors" not in DC_SRC
    return (stamped >= 2 and no_seam), (
        f"withdrawal stamped at {stamped} server sites; valuation_factors seam deleted "
        f"from data_contract={no_seam}"
    )


# ── B. Source methodology ──────────────────────────────────────────────
def b_families():
    """The invariant, not a memorised count: independence < coverage."""
    groups = {
        str(s.get("correlation_group")) for s in dc._RANKING_SOURCES if s.get("correlation_group")
    }
    members = sum(1 for s in dc._RANKING_SOURCES if s.get("correlation_group"))
    families = {dc.correlation_group_for(str(s["key"])) for s in dc._RANKING_SOURCES}
    one_head = all(  # every declared family resolves to exactly one head
        len(
            {
                dc.correlation_group_for(k)
                for k in [
                    str(x["key"])
                    for x in dc._RANKING_SOURCES
                    if dc.correlation_group_for(str(x["key"])) == g
                ]
            }
        )
        == 1
        for g in groups
    )
    fewer = len(families) < len(dc._RANKING_SOURCES)
    return (bool(groups) and fewer and one_head), (
        f"{len(dc._RANKING_SOURCES)} sources collapse to {len(families)} independent "
        f"families; {members} sources declared into {len(groups)} multi-board providers "
        f"{sorted(groups)}"
    )


def b_collapse_is_selection():
    src = inspect.getsource(dc.collapse_to_independent_families)
    averages = any(tok in src for tok in ("sum(", "mean", "/ len("))
    return (not averages), f"no averaging in the collapse: {not averages}"


def b_blend_consumes_families():
    src = inspect.getsource(dc._compute_unified_rankings)
    return ("collapse_to_independent_families" in src), "blend calls the collapse"


# ── C. Circularity ─────────────────────────────────────────────────────
def c_market_gap():
    src = inspect.getsource(dc._compute_market_gap)
    return ("expand_correlation_groups" in src), "retail side expanded across families"


# ── D. Thresholds / units ──────────────────────────────────────────────
def d_registry():
    from src.api.thresholds import threshold_entries

    entries = threshold_entries()
    bad = [n for n, e in entries.items() if not (e.get("unit") and e.get("derivedFrom"))]
    return (not bad), f"{len(entries)} thresholds, all with unit + derivation: {not bad}"


def d_ros_percentile():
    """A GAP between percentiles is percentilePoints, and saying so is
    the unit discipline B9b established — not a violation of it."""
    from src.api.thresholds import threshold_entries

    entries = threshold_entries()
    ros = {n: e for n, e in entries.items() if n.startswith("ROS_")}
    ok = all(
        e["unit"] == ("percentilePoints" if n.endswith("_GAP") else "percentile")
        for n, e in ros.items()
    )
    return ok, (
        f"{len(ros)} ROS thresholds; "
        + ", ".join(f"{n}={e['unit']}" for n, e in sorted(ros.items()))
    )


# ── E. Second Opinions ─────────────────────────────────────────────────
def e_scale_contract():
    """The panel must not READ a display mode. A comment saying it
    deliberately does not is documentation, not a violation."""
    src = (ROOT / "frontend" / "lib" / "second-opinions.js").read_text(encoding="utf-8")
    has_basis = "VALUE_BASIS" in src and "KTC_NATIVE" in src
    panel = (ROOT / "frontend" / "components" / "trade" / "TradeSourceBreakdown.jsx").read_text(
        encoding="utf-8"
    )
    code = "\n".join(ln.split("//", 1)[0] for ln in panel.splitlines())
    no_mode = "valueMode" not in code
    return (has_basis and no_mode), (
        f"basis type exists={has_basis}; panel CODE free of the display valueMode={no_mode}"
    )


# ── F. Confidence / B11 ────────────────────────────────────────────────
def f_owner():
    retired = not any(
        hasattr(dc, n)
        for n in (
            "_compute_confidence_bucket",
            "_CONFIDENCE_PERCENTILE_HIGH",
            "_CONFIDENCE_PERCENTILE_MEDIUM",
            "_CONFIDENCE_SPREAD_HIGH",
            "_CONFIDENCE_SPREAD_MEDIUM",
        )
    )
    owned = callable(conf.assess_confidence)
    return (
        retired and owned
    ), f"old rule + constants gone={retired}; confidence.py owns it={owned}"


def f_axes():
    return (len(conf.AXES) == 5), f"axes={list(conf.AXES)}"


def f_no_frontend_math():
    registry = json.loads((ROOT / "config" / "thresholds.json").read_text(encoding="utf-8"))
    js = (ROOT / "frontend" / "lib" / "thresholds.js").read_text(encoding="utf-8")
    leaked = [n for n in conf.gate_parameters() if n in registry.get("thresholds", {}) or n in js]
    return (not leaked), f"gate parameters absent from the frontend mirror: {not leaked}"


def f_params_declared():
    bad = [
        n for n, e in conf.gate_parameters().items() if not (e.get("unit") and e.get("derivedFrom"))
    ]
    return (not bad), f"{len(conf.gate_parameters())} parameters, all declared: {not bad}"


def f_override_restated():
    return hasattr(dc, "_restate_confidence_after_override"), (
        "post-blend override re-states confidence"
    )


# ── G. Missingness ─────────────────────────────────────────────────────
def g_display_value():
    src = (ROOT / "frontend" / "lib" / "trade-logic.js").read_text(encoding="utf-8")
    tree_has = "export function formatBoardValue" in src and "unpricedAssetsOnSide" in src
    returns_null = "if (!row) return null;" in src
    return (tree_has and returns_null), (
        f"formatBoardValue + unpricedAssetsOnSide exist={tree_has}; displayValue nulls={returns_null}"
    )


def g_predicate_consumed():
    consumers = []
    for p in (ROOT / "frontend").rglob("*.jsx"):
        if "node_modules" in str(p):
            continue
        if "isUnpricedBoardRow" in p.read_text(encoding="utf-8"):
            consumers.append(p.name)
    return bool(consumers), f"production consumers of isUnpricedBoardRow: {consumers}"


# ── H. Board integrity ─────────────────────────────────────────────────
def h_scale_enforced():
    src = inspect.getsource(dc.validate_api_data_contract)
    return ("_CANONICAL_VALUE_MAX" in src), "validator enforces the canonical scale"


def h_board_builds():
    payload = json.loads(
        (ROOT / "exports" / "latest" / "dynasty_data_2026-08-14.json").read_text(encoding="utf-8")
    )
    contract = dc.build_api_data_contract(payload)
    rows = contract["playersArray"]
    values = [r["rankDerivedValue"] for r in rows if r.get("rankDerivedValue") is not None]
    in_range = all(dc._CANONICAL_VALUE_MIN <= v <= dc._CANONICAL_VALUE_MAX for v in values)
    from collections import Counter

    buckets = Counter(r.get("confidenceBucket") for r in rows)
    axes_present = sum(1 for r in rows if r.get("confidenceAxes"))
    return (in_range and axes_present > 0), (
        f"{len(rows)} rows, {len(values)} priced, all in "
        f"[{dc._CANONICAL_VALUE_MIN},{dc._CANONICAL_VALUE_MAX}]={in_range}; "
        f"buckets={dict(buckets)}; rows with axes={axes_present}"
    )


def h_deterministic():
    payload = json.loads(
        (ROOT / "exports" / "latest" / "dynasty_data_2026-08-14.json").read_text(encoding="utf-8")
    )
    a = dc.build_api_data_contract(payload)
    b = dc.build_api_data_contract(payload)
    key = lambda r: r.get("canonicalName") or r.get("displayName")  # noqa: E731
    A = {key(r): r for r in a["playersArray"]}
    B = {key(r): r for r in b["playersArray"]}
    fields = ("rankDerivedValue", "canonicalConsensusRank", "confidenceBucket", "confidenceAxes")
    diffs = {f: sum(1 for k in A if A[k].get(f) != B[k].get(f)) for f in fields}
    nondet = {f: n for f, n in diffs.items() if n}
    return (not nondet), f"back-to-back builds differ on: {nondet or 'nothing'}"


for area, req, fn in [
    ("A", "one canonical value per asset; no offense-only second board", a_one_value),
    ("A", "canonical 1-9999 scale has a single owner", a_scale_owner),
    ("A", "rejected league-adjusted methodology stays withdrawn", a_lens_withdrawn),
    ("B", "provider families declared", b_families),
    ("B", "family collapse is a SELECTION, never an average", b_collapse_is_selection),
    ("B", "the blend consumes families, not raw keys", b_blend_consumes_families),
    ("C", "market gap splits retail/consensus by FAMILY", c_market_gap),
    ("D", "every threshold records unit + derivation", d_registry),
    ("D", "ROS gates are percentiles, not index points", d_ros_percentile),
    ("E", "Second Opinions declares a value basis; panel ignores display mode", e_scale_contract),
    ("F", "the max-minus-min rule and its constants are gone", f_owner),
    ("F", "five axes", f_axes),
    ("F", "no frontend confidence math (parameters not mirrored)", f_no_frontend_math),
    ("F", "every gate parameter declares unit + derivation", f_params_declared),
    ("F", "post-blend overrides re-state confidence", f_override_restated),
    ("G", "unpriced renders as unknown, not zero", g_display_value),
    ("G", "the unpriced predicate has production consumers", g_predicate_consumed),
    ("H", "the contract validator enforces the canonical scale", h_scale_enforced),
    ("H", "the live board builds, in range, with confidence axes", h_board_builds),
    ("H", "the board is deterministic across builds", h_deterministic),
]:
    check(area, req, fn)

print("| area | requirement | status | evidence |")
print("|---|---|---|---|")
for area, req, ok, detail in results:
    print(f"| {area} | {req} | {'PASS' if ok else 'FAIL'} | {detail} |")
print()
failed = [r for r in results if not r[2]]
print(f"TOTAL {len(results)} checks · PASS {len(results) - len(failed)} · FAIL {len(failed)}")
for area, req, _ok, detail in failed:
    print(f"  FAIL {area}: {req} — {detail}")
