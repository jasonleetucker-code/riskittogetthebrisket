#!/usr/bin/env python3
"""Low-value-asset research — local shadow replay and filler-flip study.  RESEARCH ONLY.

Owner directive 2026-10-20; protocol frozen in
``docs/valuation/evidence/low_value_assets_2026-10-20/PREREGISTRATION.md`` (commit
160cc28b5).  Everything here is EXPLORATORY (prereg §"What counts as
confirmatory"): the local board, no market ledger.

``geom_q078_v1`` (q = 0.78) stays the production model.  The candidates are the
frozen treatments in ``scripts/low_value_asset_treatments.py`` (imported, never
re-implemented).  Wherever a served engine is replayed (Trade Finder, the
analyze path) a treatment is installed in-process behind
``package_model._geom_pair`` through ``package_model_finder_replay.installed``,
which ALWAYS restores production (try/finally).  No file other than the
evidence JSON is written; no config, no served path, no canonical value moves.

Sections (match the owner task):

1. replacement anchors per position — the prereg rule (``waiver_values_by_position``;
   ``*`` = FAAB ``V_repl``), with the other measures reported beside it;
2. §3 classification of every board asset: genuine starter / usable depth /
   expendable filler (picks against ``*``);
3. the filler-flip study (criteria F1–F3 per class);
4. real-player examples (Phase 3 §8.1 + new IDP-depth and rookie-pick cases);
5. surfaces: (a) calculator fairness sample, (b) Trade Finder replay,
   (c) Trade History grades, (d) War Room with Team Context (GEOM_78 only),
   (e) public-category shadow;
6. a mathematical property table per treatment.

Output: ``docs/valuation/evidence/low_value_assets_2026-10-20/shadow_replay.json``
— aggregates and real player NAMES only (no league / user / roster / team ids or
manager names; checked with ``assert_aggregate_only``).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import multiprocessing
import random
import re
import shutil
import statistics
import sys
import tempfile
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
OUT_DEFAULT = "docs/valuation/evidence/low_value_assets_2026-10-20/shadow_replay.json"
sys.path.insert(0, str(REPO))


def _load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


T = _load("low_value_asset_treatments")
P3L = _load("package_model_phase3_local")  # board loader + newest archive
P2 = P3L.P2  # adjusted / level / structure_bin / orient / assert_aggregate_only
P1 = P3L.P1  # level / leader (the shared fairness classifier) / _git_sha
FR = P3L.FR  # Trade Finder replay harness (installed / run / compare)

from src.valuation_math import package_model as pm  # noqa: E402

LEAGUE = "dynasty_main"
SEED = 20261020
TREATMENTS = list(T.TREATMENTS)  # GEOM_78, A_curve_*, B_currency_*
INCUMBENT = "GEOM_78"
C_SOURCE = "B_currency_replacement"  # C_informational discloses when this one changes the level
POSITIONS = ("QB", "RB", "WR", "TE", "K", "DL", "LB", "DB")
LEVEL_RANK = {"fair": 0, "slight": 1, "unfair": 2, "lopsided": 3}
CATS = ("filler", "depth", "starter")
CLASSES = ("offense", "idp", "picks", "mixed")


# ── shared helpers ────────────────────────────────────────────────────────


def verdict(treatment: str, A, B, rep: dict) -> dict:
    """Fairness verdict on ADJUSTED totals through the shared classifier.

    ``A`` / ``B`` are lists of (value, position).  Returns the signed gap, the
    level (``fairness_bands.classify`` via ``P1.level``), the favoured side and an
    ordinal from A's point of view (-3 lopsided against A .. +3 lopsided for A).
    """
    g = T.gap(treatment, A, B, rep)
    av, bv = [v for v, _ in A], [v for v, _ in B]
    g2, x, y = P2.adjusted(lambda _a, _b: g, av, bv)
    lvl = P1.level(g2, x, y)
    sign = 1 if g > 0 else (-1 if g < 0 else 0)
    return {
        "gap": g,
        "adjA": x,
        "adjB": y,
        "level": lvl,
        "lead": P1.leader(g2, x, y),
        "ord": sign * LEVEL_RANK[lvl],
    }


def _sgn(x):
    return (x > 0) - (x < 0)


def _r(x, n=0):
    return None if x is None else round(x, n) if n else round(x)


def newest_board() -> tuple[Path, str, bytes, dict]:
    zpath, member = P3L.newest_archive()
    with zipfile.ZipFile(zpath) as zf:
        blob = zf.read(member)
    return zpath, member, blob, json.loads(blob)


# ── 1. replacement anchors ────────────────────────────────────────────────


def build_context(raw: dict) -> dict:
    """ONE contract build: board rows, rosters, optimal lineups, anchors."""
    from src.api import league_registry  # noqa: PLC0415
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415
    from src.draft.displacement import waiver_values_by_position  # noqa: PLC0415
    from src.league_intel.replacement import compute_replacement_levels  # noqa: PLC0415
    from src.trade import faab_engine  # noqa: PLC0415

    contract = build_api_data_contract(raw)
    rows = {}
    for r in contract.get("playersArray") or []:
        v = r.get("rankDerivedValue")
        if isinstance(v, (int, float)) and v > 0:
            rows[r["displayName"]] = {
                "name": r["displayName"],
                "value": float(v),
                "cls": r.get("assetClass"),
                "pos": (r.get("position") or "").upper() or None,
                "rookie": bool(r.get("rookie")),
                "quarantined": bool(r.get("quarantined")),
                "pid": str(r.get("playerId") or ""),
            }
    teams = contract["sleeper"]["teams"]
    cfg = league_registry.get_league_by_key(LEAGUE)
    roster_settings = dict(cfg.roster_settings or {})
    rostered_names = {n for t in teams for n in (t.get("players") or [])}
    rostered_keys = list(rostered_names) + [
        str(x) for t in teams for x in (t.get("playerIds") or []) if x
    ]

    # (i) PRIMARY (prereg §2): best unrostered rankDerivedValue per position.
    waiver = waiver_values_by_position(contract, rostered_keys)

    # (ii) FAAB anchors, built exactly as server.py's FAAB route does.
    excluded = set(faab_engine.FaabConfig().get("anchors", "excludedPositions", []) or [])
    starters_map = roster_settings.get("starters") or {}
    spt = sum(int(v or 0) for k, v in starters_map.items() if str(k).upper() != "K") or 20
    board_vals, avail_vals = [], []
    for r in rows.values():
        if r["cls"] == "pick" or (r["pos"] or "") in excluded:
            continue
        board_vals.append(r["value"])
        if r["name"] not in rostered_names:
            avail_vals.append(r["value"])
    anchors = faab_engine.resolve_anchors(
        board_vals,
        faab_engine.LeagueContext(team_count=len(teams) or 12, starters_per_team=spt),
        available_values=avail_vals or None,
    )

    # (iii) LI-5 replacement tiers, optimizer run on canonical values (rosValue := rankDerivedValue).
    def prow(n):
        r = rows.get(n)
        if not r or r["cls"] == "pick":
            return None
        return {"playerId": r["name"], "canonicalName": r["name"], "position": r["pos"],
                "rosValue": r["value"]}  # fmt: skip

    slots = (teams[0].get("optimalLineup") or {}).get("slots") or []
    rep_teams = [{"players": [p for p in (prow(n) for n in t["players"]) if p]} for t in teams]
    fas = [prow(n) for n, r in rows.items() if n not in rostered_names and r["cls"] != "pick"]
    li5 = compute_replacement_levels(rep_teams, slots, free_agents=[f for f in fas if f])

    # (iv) the canonical optimal lineups the contract stamps (prereg §3).
    starters: set[str] = set()
    lineups_available = 0
    for t in teams:
        ol = t.get("optimalLineup") or {}
        if ol.get("available"):
            lineups_available += 1
            starters |= set(ol.get("starters") or [])
    lowest_starter: dict[str, float] = {}
    for n in starters:
        r = rows.get(n)
        if r and r["pos"]:
            lowest_starter[r["pos"]] = min(lowest_starter.get(r["pos"], 1e9), r["value"])

    rep = {p: float(v) for p, v in waiver.items()}
    rep["*"] = float(anchors.v_repl)
    by_value: dict = defaultdict(set)
    for r in rows.values():
        by_value[r["value"]].add(rep.get(r["pos"], rep["*"]) if r["cls"] != "pick" else rep["*"])
    ambiguous = sum(1 for cs in by_value.values() if len(cs) > 1)
    by_pos = {}
    for pos in POSITIONS:
        li = li5.get(pos)
        lv = (li.levels if li else {}) or {}
        by_pos[pos] = {
            "waiverBestUnrostered_PRIMARY": _r(waiver.get(pos)),
            "li5_starterMedianMarginal": _r(lv["starter"].value) if "starter" in lv else None,
            "li5_bestBallStarter": _r(lv["bestBallStarter"].value) if "bestBallStarter" in lv else None,
            "li5_roster_lastRostered": _r(lv["roster"].value) if "roster" in lv else None,
            "li5_waiverBanded": _r(lv["waiver"].value) if "waiver" in lv else None,
            "lowestStarterAcross12OptimalLineups": _r(lowest_starter.get(pos)),
            "boardRowsPriced": sum(1 for r in rows.values() if r["pos"] == pos),
            "anchorUsed": _r(rep.get(pos, rep["*"])),
            "anchorSource": "waiver_values_by_position" if pos in rep else "* (FAAB V_repl) — "
            "no priced unrostered player at this position on the board",
        }  # fmt: skip
    anchor_report = {
        "rule": "prereg §2 (frozen 160cc28b5): c_pos = src/draft/displacement."
        "waiver_values_by_position (best unrostered rankDerivedValue at the position, newest "
        "board, dynasty_main rosters); '*' (unknown position AND every pick) = FAAB V_repl "
        "from src/trade/faab_engine.resolve_anchors, built as server.py's FAAB route builds it",
        "replacementAnchorDict": {k: round(v) for k, v in sorted(rep.items())},
        "byPosition": by_pos,
        "faab": {k: v for k, v in anchors.to_dict().items()},
        "faabInputs": {
            "teamCount": len(teams),
            "startersPerTeamExclK": spt,
            "boardPlayerValues": len(board_vals),
            "unrosteredPlayerValues": len(avail_vals),
        },  # fmt: skip
        "picks": "Picks take '*' = league-wide FAAB V_repl.  A pick is not a waiver-wire "
        "replacement for a roster spot (displacement._available_players excludes picks), so no "
        "per-position waiver level exists for it; V_repl is the league's format-level "
        "replacement value (board rank ~2x the starting pool, blended with the live pool).",
        "notes": [
            "Kickers carry no canonical value on this board (0 priced K rows), so K has no "
            "anchor of its own and no K asset enters any trade below.",
            "li5_* tiers run the exact lineup optimizer with rosValue := rankDerivedValue "
            "(canonical scale), so they are canonical-value replacement levels, not projections.",
        ],
        "optimalLineupsAvailable": lineups_available,
        "starterSlots": slots,
    }
    return {
        "contract": contract,
        "rows": rows,
        "teams": teams,
        "roster_settings": roster_settings,
        "rostered": rostered_names,
        "starters": starters,
        "lowest_starter": lowest_starter,
        "rep": rep,
        "anchors": anchor_report,
        "ambiguousValues": ambiguous,
    }


# ── 2. classification ─────────────────────────────────────────────────────


def classify_assets(ctx: dict) -> dict:
    rows, rep = ctx["rows"], ctx["rep"]
    low = ctx["lowest_starter"]
    for r in rows.values():
        if r["cls"] == "pick":
            r["cat"] = "depth" if r["value"] >= rep["*"] else "filler"
            r["group"] = "picks"
            continue
        r["group"] = "offense" if r["cls"] == "offense" else "idp"
        c = rep.get(r["pos"], rep["*"])
        if r["name"] in ctx["starters"]:
            r["cat"] = "starter"
        elif r["name"] not in ctx["rostered"] and r["pos"] in low and r["value"] >= low[r["pos"]]:
            r["cat"] = "starter"
        elif r["value"] >= c:
            r["cat"] = "depth"
        else:
            r["cat"] = "filler"
    table: dict = {}
    for r in rows.values():
        key = r["pos"] if r["cls"] != "pick" else ("PICK_rookie_class" if "Pick" in r["name"]
                                                   else "PICK_future")  # fmt: skip
        e = table.setdefault(key, {c: {"n": 0, "rostered": 0, "valueMin": None, "valueMax": None}
                                   for c in CATS})  # fmt: skip
        b = e[r["cat"]]
        b["n"] += 1
        b["rostered"] += r["name"] in ctx["rostered"]
        b["valueMin"] = r["value"] if b["valueMin"] is None else min(b["valueMin"], r["value"])
        b["valueMax"] = r["value"] if b["valueMax"] is None else max(b["valueMax"], r["value"])
    for e in table.values():
        for b in e.values():
            b["valueMin"], b["valueMax"] = _r(b["valueMin"]), _r(b["valueMax"])
    ex = {}
    for cat in CATS:
        for grp in ("offense", "idp", "picks"):
            pool = sorted((r for r in rows.values() if r["cat"] == cat and r["group"] == grp),
                          key=lambda r: -r["value"])  # fmt: skip
            if pool:
                ex[f"{grp}:{cat}"] = [f"{r['name']} ({r['pos']}, {r['value']:.0f})"
                                      for r in pool[:: max(1, len(pool) // 5)][:6]]  # fmt: skip
    return {
        "rule": "prereg §3: genuine starter = in a dynasty_main roster's canonical optimal lineup "
        "(contract sleeper.teams[].optimalLineup.starters); an UNROSTERED asset is a starter when "
        "its value >= the lowest starter value at its position across the 12 lineups; usable "
        "depth = not a starter and value >= its position anchor; expendable filler = value < "
        "its position anchor.  Picks: value vs '*' (never 'starter'; >= '*' is reported as "
        "depth).  Rookie-class picks (e.g. '2027 Pick 1.10') and future-year tier picks are "
        "reported separately and never pooled with players.",
        "counts": {
            "byPositionAndClass": table,
            "totals": dict(Counter(r["cat"] for r in rows.values())),
            "quarantinedExcludedFromTradePools": sum(1 for r in rows.values() if r["quarantined"]),
        },
        "examples": ex,
    }


# ── 3. filler-flip study ──────────────────────────────────────────────────

TIERS = {"elite": (7000, 1e9), "high": (4000, 7000), "mid": (2000, 4000), "low": (0, 2000)}
SHAPES = ((1, 1), (1, 2), (2, 2), (2, 3))


def _asset(r):
    return (r["value"], None if r["cls"] == "pick" else r["pos"])


def _pools(rows):
    ok = [r for r in rows.values() if not r["quarantined"]]
    by = defaultdict(list)
    for r in ok:
        by[(r["group"], "any")].append(r)
        by[(r["group"], r["cat"])].append(r)
        by[("mixed", "any")].append(r)
        by[("mixed", r["cat"])].append(r)
        if r["cat"] == "starter":
            by[("mixed", "starters_only")].append(r)
            by[(r["group"], "starters_only")].append(r)
    return by


def _make_base(rng, pool, shape, tier, cls, tries=200):
    na, nb = shape
    lo, hi = TIERS[tier]
    tops = [r for r in pool if lo <= r["value"] < hi]
    if not tops:
        return None
    for _ in range(tries):
        top = rng.choice(tops)
        A = [top]
        others = [r for r in pool if r["value"] <= top["value"] and r is not top]
        if na > 1:
            if len(others) < na - 1:
                continue
            A += rng.sample(others, na - 1)
        ra = sum(r["value"] for r in A)
        used = {r["name"] for r in A}
        cand = [r for r in pool if r["name"] not in used and r["value"] < ra]
        if len(cand) < nb:
            continue
        B = rng.sample(cand, nb - 1) if nb > 1 else []
        need = ra - sum(r["value"] for r in B)
        if need <= 0:
            continue
        used |= {r["name"] for r in B}
        last = min((r for r in pool if r["name"] not in used), key=lambda r: abs(r["value"] - need))
        B.append(last)
        rb = sum(r["value"] for r in B)
        if abs(ra - rb) > 0.10 * max(ra, rb):
            continue
        groups = {r["group"] for r in A + B}
        if cls == "mixed" and len(groups) < 2:
            continue
        return A, B
    return None


def flip_study(rows, rep, per_cell: int, seed: int = SEED) -> dict:
    rng = random.Random(seed)
    pools = _pools(rows)
    bases = []
    for cls in CLASSES:
        for comp in ("any", "starters_only"):
            if cls == "picks" and comp == "starters_only":
                continue
            pool = pools[(cls, comp)]
            for shape in SHAPES:
                for tier in TIERS:
                    for _ in range(per_cell):
                        b = _make_base(rng, pool, shape, tier, cls)
                        if b:
                            bases.append({"cls": cls, "comp": comp, "shape": shape, "tier": tier,
                                          "A": b[0], "B": b[1]})  # fmt: skip
    # Sweetener draws are fixed per base so every treatment scores identical trades.
    cases = []
    for bi, b in enumerate(bases):
        used = {r["name"] for r in b["A"] + b["B"]}
        ra, rb = (sum(r["value"] for r in b[s]) for s in ("A", "B"))
        behind = "A" if ra < rb else "B"
        for cat in CATS:
            spool = [r for r in pools[(b["cls"], cat)] if r["name"] not in used]
            if len(spool) < 4:
                continue
            draw = rng.sample(spool, 4)
            for k in range(1, 5):
                cases.append({"base": bi, "cat": cat, "k": k, "behind": behind, "sweet": draw[:k]})

    def sides(b, case=None):
        A = [_asset(r) for r in b["A"]]
        B = [_asset(r) for r in b["B"]]
        if case is not None:
            add = [_asset(r) for r in case["sweet"]]
            if case["behind"] == "A":
                A = A + add
            else:
                B = B + add
        return A, B

    base_v = {t: [verdict(t, *sides(b), rep) for b in bases] for t in TREATMENTS}
    res = {t: [] for t in TREATMENTS}
    for t in TREATMENTS:
        for c in cases:
            b = bases[c["base"]]
            v0 = base_v[t][c["base"]]
            v1 = verdict(t, *sides(b, c), rep)
            s = 1 if c["behind"] == "A" else -1  # orient the ordinal toward the sweetening side
            o0, o1 = s * v0["ord"], s * v1["ord"]
            res[t].append({
                "flip": _sgn(o1) != _sgn(o0),
                "changed": o1 != o0,
                "winnerFlip": o0 < 0 < o1,
                "manufacturedFair": o0 < 0 and o1 == 0,
                "o1": o1,
            })  # fmt: skip

    def tally(t, pred):
        sel = [i for i, c in enumerate(cases) if pred(c)]
        r = res[t]
        return {
            "cases": len(sel),
            "flips": sum(r[i]["flip"] for i in sel),
            "verdictChanged": sum(r[i]["changed"] for i in sel),
            "winnerFlipped": sum(r[i]["winnerFlip"] for i in sel),
            "unfairMadeFair": sum(r[i]["manufacturedFair"] for i in sel),
        }

    by_class: dict = {}
    criteria: dict = {}
    for cls in CLASSES:
        by_class[cls] = {}
        for cat in CATS:
            by_class[cls][cat] = {t: tally(t, lambda c, cl=cls, ca=cat: bases[c["base"]]["cls"] == cl
                                           and c["cat"] == ca) for t in TREATMENTS}  # fmt: skip
        # F2: starter-only BASE trades, level (signed) vs GEOM_78.
        so = [i for i, b in enumerate(bases) if b["cls"] == cls and b["comp"] == "starters_only"]
        so_multi = [i for i in so if bases[i]["shape"] != (1, 1)]
        f2 = {}
        for t in TREATMENTS:
            ch = sum(base_v[t][i]["ord"] != base_v[INCUMBENT][i]["ord"] for i in so)
            chm = sum(base_v[t][i]["ord"] != base_v[INCUMBENT][i]["ord"] for i in so_multi)
            f2[t] = {"bases": len(so), "levelChanged": ch,
                     "share": round(ch / len(so), 4) if so else None,
                     "excluding1v1": {"bases": len(so_multi), "levelChanged": chm,
                                      "share": round(chm / len(so_multi), 4) if so_multi else None}}  # fmt: skip
        criteria[cls] = {}
        for t in TREATMENTS:
            if t == INCUMBENT:
                continue
            g_f = by_class[cls]["filler"][INCUMBENT]["flips"]
            t_f = by_class[cls]["filler"][t]["flips"]
            g_d = by_class[cls]["depth"][INCUMBENT]["flips"]
            t_d = by_class[cls]["depth"][t]["flips"]
            fall_f = (g_f - t_f) / g_f if g_f else None
            fall_d = (g_d - t_d) / g_d if g_d else None
            f2s = f2[t]
            criteria[cls][t] = {
                "F1_fillerFlipFall": _r(fall_f, 4),
                "F1": "insufficient" if g_f < 100 else ("pass" if fall_f >= 0.80 else "fail"),
                "F2_starterBaseLevelChangedShare": f2s["share"],
                "F2": "not_applicable (no starter picks)" if cls == "picks" else (
                    "insufficient" if f2s["bases"] < 100 else ("pass" if f2s["share"] <= 0.02 else "fail")),
                "F3_depthFlipFall": _r(fall_d, 4),
                "F3": "insufficient" if g_d < 100 else ("pass" if fall_d <= 0.25 else "fail"),
                "incumbentFlipCases": {"filler": g_f, "depth": g_d},
            }  # fmt: skip
        by_class[cls]["F2_starterOnlyBases"] = f2
    # Approach C: disclosure rate (B_currency_replacement's verdict differs from GEOM_78's).
    disclosure = {}
    for cat in CATS:
        sel = [i for i, c in enumerate(cases) if c["cat"] == cat]
        disclosure[cat] = {
            "cases": len(sel),
            "disclosureFires": sum(res[C_SOURCE][i]["o1"] != res[INCUMBENT][i]["o1"] for i in sel),
        }
    # Sweetener value bands for filler flips (incumbent vs B_replacement).
    band_tbl: dict = {}
    for i, c in enumerate(cases):
        if c["cat"] != "filler":
            continue
        tot = sum(r["value"] for r in c["sweet"])
        band = (
            "<500"
            if tot < 500
            else "500-1500"
            if tot < 1500
            else "1500-3000"
            if tot < 3000
            else ">=3000"
        )
        e = band_tbl.setdefault(band, {"cases": 0, **{t: 0 for t in TREATMENTS}})
        e["cases"] += 1
        for t in TREATMENTS:
            e[t] += res[t][i]["flip"]
    by_tier = {}
    for tier in TIERS:
        by_tier[tier] = {cat: {t: tally(t, lambda c, ti=tier, ca=cat: bases[c["base"]]["tier"] == ti
                                        and c["cat"] == ca)["flips"] for t in TREATMENTS}
                         for cat in CATS}  # fmt: skip
    # A few concrete filler flips the incumbent makes and B_currency_replacement does not.
    examples = []
    for i, c in enumerate(cases):
        if len(examples) >= 8:
            break
        if (
            c["cat"] == "filler"
            and res[INCUMBENT][i]["winnerFlip"]
            and not res[C_SOURCE][i]["changed"]
        ):
            b = bases[c["base"]]
            examples.append({
                "class": b["cls"],
                "A": [f"{r['name']} ({r['pos']}, {r['value']:.0f})" for r in b["A"]],
                "B": [f"{r['name']} ({r['pos']}, {r['value']:.0f})" for r in b["B"]],
                "sweetenersToSideBehind": [f"{r['name']} ({r['pos']}, {r['value']:.0f})" for r in c["sweet"]],
                "sideBehind": c["behind"],
            })  # fmt: skip
    return {
        "design": {
            "bases": len(bases),
            "cases": len(cases),
            "perCell": per_cell,
            "shapes": [f"{a}v{b}" for a, b in SHAPES],
            "tiersOfTopAsset": {k: [v[0], v[1] if v[1] < 1e8 else None] for k, v in TIERS.items()},
            "rawGapWithin": "10% of the larger raw side",
            "compositions": "'any' (assets of the class drawn freely) and 'starters_only' (every "
            "base asset a §3 genuine starter); picks have no starters_only bases",
            "sweeteners": "1-4 assets drawn ONCE per base and category (filler / depth / starter, "
            "same class as the base; mixed draws across classes) and added to the side that is "
            "behind on raw value; identical cases for every treatment",
            "flip": "PRIMARY flips = the verdict crosses a region for the sweetening side "
            "(disfavoured -> fair, disfavoured -> favoured, or fair -> favoured), the shared "
            "classifier (fairness_bands_v1) on adjusted totals; this is what F1/F3 count.  "
            "Secondary: verdictChanged = any change of the signed level (e.g. lopsided -> unfair "
            "against); winnerFlipped = disfavoured -> favoured; unfairMadeFair = disfavoured -> FAIR",
            "basesByClass": dict(Counter(b["cls"] for b in bases)),
            "basesByComposition": dict(Counter(f"{b['cls']}:{b['comp']}" for b in bases)),
            "basesByShape": dict(Counter(f"{b['shape'][0]}v{b['shape'][1]}" for b in bases)),
            "criteriaThresholds": "F1 filler-only flips fall >= 80% vs GEOM_78; F2 starter-only "
            "base trades level changes <= 2%; F3 usable-depth flips fall <= 25%; <100 flip cases "
            "(or <100 starter-only bases for F2) = insufficient",
            "incumbentNote": "GEOM_78 here is the exact geometric utility (q = 0.78); production "
            "rounds the adjustment to an integer, which moves no level in this study by design "
            "of the bands (absolute minimum 250).",
        },
        "byClass": by_class,
        "criteria": criteria,
        "C_informationalDisclosure": disclosure,
        "fillerFlipsBySweetenerTotal": band_tbl,
        "verdictChangedByBaseTier": by_tier,
        "exampleFillerFlipsRemovedByB_replacement": examples,
    }


# ── 4. real-player examples ───────────────────────────────────────────────


def real_examples(rows, rep) -> dict:
    missing = []

    def a(name):
        r = rows.get(name)
        if r is None:
            missing.append(name)
        return r

    def side(names):
        rs = [a(n) for n in names]
        return None if any(r is None for r in rs) else rs

    def fmt(rs):
        return [f"{r['name']} ({r['pos']}, {r['value']:.0f}, {r['cat']})" for r in rs]

    def ev(A, B):
        out = {}
        for t in TREATMENTS:
            v = verdict(t, [_asset(r) for r in A], [_asset(r) for r in B], rep)
            out[t] = {"gapA": round(v["gap"]), "level": v["level"],
                      "favours": "A" if v["lead"] == 1 else ("B" if v["lead"] == -1 else "even")}  # fmt: skip
        out["C_informational"] = {"disclosure": out[C_SOURCE]["level"] != out[INCUMBENT]["level"]
                                  or out[C_SOURCE]["favours"] != out[INCUMBENT]["favours"]}  # fmt: skip
        return out

    def pick_near(pred, target, k, used):
        pool = [
            r for r in rows.values() if pred(r) and not r["quarantined"] and r["name"] not in used
        ]
        got = []
        for _ in range(k):
            x = min(pool, key=lambda r: abs(r["value"] - target))
            pool.remove(x)
            used.add(x["name"])
            got.append(x)
        return got

    specs = [
        ("§8.1 Hurts vs Egbuka", ["Jalen Hurts"], ["Emeka Egbuka"]),
        ("§8.1 … + Isaiah Hodgins", ["Jalen Hurts"], ["Emeka Egbuka", "Isaiah Hodgins"]),
        ("§8.1 … + four fillers", ["Jalen Hurts"],
         ["Emeka Egbuka", "Isaiah Hodgins", "Frank Gore", "Khalil Herbert", "Mason Tipton"]),
        ("§8.1 Gibbs vs Smith + Higgins", ["Jahmyr Gibbs"], ["DeVonta Smith", "Tee Higgins"]),
        ("§8.1 … + four ~1,000 fillers", ["Jahmyr Gibbs"],
         ["DeVonta Smith", "Tee Higgins", "Nick Westbrook-Ikhine", "Kalel Mullings",
          "Xavier Restrepo", "Jarrett Stidham"]),
        ("§8.1 Gibbs vs Young + Kraft", ["Jahmyr Gibbs"], ["Bryce Young", "Tucker Kraft"]),
        ("§8.1 Gibbs vs six starters", ["Jahmyr Gibbs"],
         ["Blake Corum", "Pat Freiermuth", "Eli Raridon", "Xavier Worthy", "David Montgomery",
          "Antonio Williams"]),
        ("§8.1 Wilson vs Ferguson + Kelce", ["Garrett Wilson"], ["Jake Ferguson", "Travis Kelce"]),
        ("§8.1 IDP Schwesinger vs Baun + Parsons", ["Carson Schwesinger"], ["Zack Baun", "Micah Parsons"]),
        ("§8.1 Picks Love vs 2027 1.10 + 2028 Late 1st", ["Jeremiyah Love"],
         ["2027 Pick 1.10", "2028 Late 1st"]),
    ]  # fmt: skip
    cases = []
    for label, an, bn in specs:
        A, B = side(an), side(bn)
        if A is None or B is None:
            cases.append({"case": label, "skipped": "asset not priced on this board"})
            continue
        cases.append({"case": label, "A": fmt(A), "B": fmt(B),
                      "rawA": round(sum(r["value"] for r in A)), "rawB": round(sum(r["value"] for r in B)),
                      "treatments": ev(A, B)})  # fmt: skip

    def idp(cat):
        return lambda r: r["group"] == "idp" and r["cat"] == cat

    # New IDP-depth cases (deterministic: nearest board value to a target).
    used: set = set()
    star = max((r for r in rows.values() if r["group"] == "idp" and not r["quarantined"]),
               key=lambda r: r["value"])  # fmt: skip
    used.add(star["name"])
    s1 = pick_near(idp("starter"), 0.62 * star["value"], 1, used)
    d1 = pick_near(idp("depth"), 0.38 * star["value"], 1, used)
    new = [("IDP-depth 1: IDP star vs IDP starter + IDP usable depth", [star], s1 + d1, s1)]
    used = set()
    wr = pick_near(lambda r: r["group"] == "offense" and r["pos"] == "WR" and r["cat"] == "starter",
                   4200, 1, used)  # fmt: skip
    s2 = pick_near(idp("starter"), 3500, 1, used)
    f2 = pick_near(
        lambda r: r["group"] == "idp" and r["pos"] == "DB" and r["cat"] == "filler", 1100, 2, used
    )
    new.append(("IDP-depth 2: WR starter vs IDP starter + two DB fillers", wr, s2 + f2, s2))
    used = set()
    two = pick_near(idp("starter"), 3800, 2, used)
    s3 = pick_near(idp("starter"), 4600, 1, used)
    d3 = pick_near(
        lambda r: r["group"] == "idp" and r["pos"] == "LB" and r["cat"] == "depth", 2600, 1, used
    )
    new.append(("IDP-depth 3: two IDP starters vs IDP starter + LB usable depth", two, s3 + d3, s3))
    used = set()
    love = side(["Jeremiyah Love"]) or []
    used |= {r["name"] for r in love}
    f1 = pick_near(
        lambda r: r["cls"] == "pick" and "Pick 1." in r["name"],
        0.55 * (love[0]["value"] if love else 7000),
        1,
        used,
    )
    f1b = pick_near(
        lambda r: r["cls"] == "pick" and "Late 1st" in r["name"],
        0.45 * (love[0]["value"] if love else 7000),
        1,
        used,
    )
    fp = pick_near(lambda r: r["cls"] == "pick" and r["cat"] == "filler", 1300, 1, used)
    if love:
        new.append(
            (
                "Rookie-pick 1: top rookie vs two firsts + a filler pick",
                love,
                f1 + f1b + fp,
                f1 + f1b,
            )
        )
    used = set()
    hi = pick_near(lambda r: r["cls"] == "pick" and "Pick 1." in r["name"], 5100, 1, used)
    lo = pick_near(lambda r: r["cls"] == "pick" and "Pick 1." in r["name"], 3900, 1, used)
    fps = pick_near(lambda r: r["cls"] == "pick" and r["cat"] == "filler", 1250, 2, used)
    new.append(("Rookie-pick 2: early first vs late first + two filler picks", hi, lo + fps, lo))
    for label, A, B, base in new:
        cases.append({"case": label, "A": fmt(A), "B": fmt(B),
                      "rawA": round(sum(r["value"] for r in A)), "rawB": round(sum(r["value"] for r in B)),
                      "treatments": ev(A, B),
                      "withoutSweetener": {"B": fmt(base), "treatments": ev(A, base)}})  # fmt: skip
    return {
        "convention": "gapA = adjusted A minus adjusted B (positive favours A); level = "
        "fairness_bands_v1 on adjusted totals (shared classifier); values = today's board; "
        "§3 class in each label",
        "cases": cases,
        "missingAssets": sorted(set(missing)),
    }


# ── 5a. calculator fairness sample ───────────────────────────────────────


def fairness_sample(rows, rep, n: int = 2000, seed: int = SEED + 1) -> dict:
    rng = random.Random(seed)
    top = sorted((r for r in rows.values() if not r["quarantined"]), key=lambda r: -r["value"])[
        :500
    ]
    trades = []
    while len(trades) < n:
        na = rng.randint(1, 3)
        nb = rng.randint(na, min(na + 4, 7))
        A = rng.sample(top, na)
        B = rng.sample([r for r in top if r not in A], nb)
        ra, rb = sum(r["value"] for r in A), sum(r["value"] for r in B)
        if abs(ra - rb) <= 0.25 * max(ra, rb):
            trades.append((A, B))
    lv = {t: [verdict(t, [_asset(r) for r in A], [_asset(r) for r in B], rep) for A, B in trades]
          for t in TREATMENTS}  # fmt: skip
    bins = [P2.structure_bin(*P2.orient(A, B)) for A, B in trades]
    out = {}
    base = lv[INCUMBENT]
    for t in TREATMENTS:
        trans: Counter = Counter()
        by_bin: dict = {}
        ch = fl = 0
        for i, (b0, b1) in enumerate(zip(base, lv[t])):
            trans[f"{b0['level']}->{b1['level']}"] += 1
            c = b0["ord"] != b1["ord"]
            f = b0["lead"] != 0 and b1["lead"] != 0 and b0["lead"] != b1["lead"]
            ch += c
            fl += f
            e = by_bin.setdefault(bins[i], {"n": 0, "levelChanged": 0, "leaderFlipped": 0})
            e["n"] += 1
            e["levelChanged"] += c
            e["leaderFlipped"] += f
        out[t] = {"levelChanged": ch, "leaderFlipped": fl, "transitions": dict(sorted(trans.items())),
                  "levelCounts": dict(Counter(x["level"] for x in lv[t])), "byStructureBin": by_bin}  # fmt: skip
    return {
        "n": n,
        "seed": seed,
        "population": "Phase 3 local §D population: assets drawn from the top 500 non-quarantined "
        "board assets; 1-3 v na..min(na+4, 7); raw gap <= 25% of the larger raw side",
        "binCounts": dict(Counter(bins)),
        "C_informational": {
            "disclosureFires": out[C_SOURCE]["levelChanged"],
            "note": "numbers unchanged (GEOM_78); the disclosure fires when "
            "B_currency_replacement changes the signed level",
        },  # fmt: skip
        "byTreatment": out,
    }


# ── 5b. Trade Finder replay ───────────────────────────────────────────────

FINDER_MODELS = ["GEOM_78", "A_curve_market", "B_currency_market"]


def _finder_gap(mid):
    if mid == "GEOM_78":
        return None
    return lambda a, b, _m=mid: T.gap(_m, [(v, None) for v in a], [(v, None) for v in b])


def _replay_chunk(job):
    raw_path, chunk = job
    models = {m: {"gap": _finder_gap(m) or FR._geom_exact_gap()} for m in FINDER_MODELS}
    return FR.run(board_raw_path=Path(raw_path), models=models, model_ids=chunk, level=P2.level)


# ── 5c. Trade History grades ──────────────────────────────────────────────


def trade_history(raw: dict, ctx: dict) -> dict:
    from src.api import pick_value_resolution as pvr  # noqa: PLC0415
    from src.public_league import trade_grading as tg  # noqa: PLC0415

    rows, rep, contract = ctx["rows"], ctx["rep"], ctx["contract"]
    trades = (raw.get("sleeper") or {}).get("trades") or []
    pick_rows = pvr.pick_rows_by_name(contract)
    cdy = int(contract.get("currentDraftYear") or 2027)
    resolved_labels: Counter = Counter()

    def look(name):
        n = re.sub(r"\s*\(from [^)]*\)$", "", str(name))
        r = rows.get(n)
        if r is None and re.match(r"^\d{4} ", n):
            pv = pvr.resolve_pick_label_value(n, rows_by_name=pick_rows, current_draft_year=cdy)
            if pv is not None and pv.value:
                resolved_labels[pv.basis or "resolved"] += 1
                v = float(pv.value)
                r = {"name": n, "value": v, "cls": "pick", "pos": None,
                     "cat": "depth" if v >= rep["*"] else "filler"}  # fmt: skip
        return r, n

    changes = {t: 0 for t in TREATMENTS}
    changes_full = {t: 0 for t in TREATMENTS}
    full_sides = 0
    letter_changes = {t: Counter() for t in TREATMENTS}
    sides_graded = unpriced_sides = 0
    prod_mismatch = 0
    examples = []
    for tr in trades:
        for s in tr.get("sides") or []:
            got = [look(x) for x in s.get("got") or []]
            gave = [look(x) for x in s.get("gave") or []]
            if not got or not gave:
                continue
            fully = all(r is not None for r, _ in got + gave)
            if not fully:
                unpriced_sides += 1
            full_sides += fully
            G = [_asset(r) for r, _ in got if r]
            V = [_asset(r) for r, _ in gave if r]
            if not G or not V:
                continue
            sides_graded += 1
            grades = {}
            for t in TREATMENTS:
                gap = T.gap(t, G, V, rep)
                va = gap - (sum(v for v, _ in G) - sum(v for v, _ in V))
                grades[t] = tg.grade_trade_side([v for v, _ in G], [v for v, _ in V], va)
            prod = tg.grade_trade_sides([([v for v, _ in G], [v for v, _ in V])])[0]

            def key(gr):
                return f"{gr['grade']} {gr['label']}"

            g0 = key(grades[INCUMBENT]["grade"])
            if key(prod["grade"]) != g0:
                prod_mismatch += 1
            for t in TREATMENTS:
                g1 = key(grades[t]["grade"])
                if g1 != g0:
                    changes[t] += 1
                    changes_full[t] += fully
                    letter_changes[t][f"{g0} -> {g1}"] += 1
            if key(grades[C_SOURCE]["grade"]) != g0 and len(examples) < 6:
                examples.append({
                    "got": [f"{n} ({r['value']:.0f}, {r['cat']})" for r, n in got if r],
                    "gave": [f"{n} ({r['value']:.0f}, {r['cat']})" for r, n in gave if r],
                    **{t: {"grade": key(grades[t]["grade"]), "pctGap": round(grades[t]["pctGap"], 1)}
                       for t in TREATMENTS},
                })  # fmt: skip
    return {
        "label": "own-league trades in the newest archive's sleeper.trades, graded with TODAY's "
        "canonical values (not at-the-time values), through trade_grading.grade_trade_side with "
        "each treatment's package adjustment as va_net",
        "trades": len(trades),
        "sidesGraded": sides_graded,
        "sidesWithAnUnpricedAsset": unpriced_sides,
        "unpricedNote": "unpriced = a 2026 pick of the completed draft (now a player) or a player "
        "the board does not price; graded on its priced assets only (as the frontend resolver "
        "does) and also reported on fully-priced sides alone",
        "pickLabelsResolvedVia_pick_value_resolution": dict(resolved_labels),
        "fullyPricedSides": full_sides,
        "gradeBucketChangedVsGEOM_78_fullyPricedSides": changes_full,
        "productionDispatchVsExactGeomLetterMismatches": prod_mismatch,
        "gradeBucketChangedVsGEOM_78": changes,
        "letterTransitions": {t: dict(c) for t, c in letter_changes.items() if c},
        "C_informational": {"disclosureFires": changes[C_SOURCE]},
        "examples": examples,
    }


# ── 5d/5e. War Room (Team Context) + public category ─────────────────────


def war_room(ctx, max_opps: int = 5, seed: int = SEED + 2) -> dict:
    from src.trade import analyze_service as AS  # noqa: PLC0415
    from src.trade import analyze_trade as AT  # noqa: PLC0415
    from src.trade import trade_decision as TD  # noqa: PLC0415

    rng = random.Random(seed)
    rows, rep, teams, contract = ctx["rows"], ctx["rep"], ctx["teams"], ctx["contract"]
    cap = int(ctx["roster_settings"].get("rosterSize") or 0)

    def ok(n):
        r = rows.get(n)
        return r if r and not r["quarantined"] and r["cls"] != "pick" else None

    def run(me, pin, pout, tc):
        sim = AS.simulate_for_team(contract, league_key=LEAGUE, roster_settings=ctx["roster_settings"],
                                   resolved_team=me, players_in=pin, players_out=pout,
                                   team_context=tc, for_analysis=True)  # fmt: skip
        return sim

    def comp_a(sim, tc):
        market = AT._market_lens(sim)
        if not market.available:
            return None
        feas = (AT._feasibility_lens(sim) if tc
                else AT._excluded_by_mode("feasibility", AT.LINEAGE_ROSTER_RULES))  # fmt: skip
        return TD._objective_value(market, feas)

    def ordinal(a):
        if a is None:
            return None
        lvl = a["band"]["level"]
        return (1 if a["netGap"] > 0 else -1 if a["netGap"] < 0 else 0) * LEVEL_RANK[lvl]

    samples = []
    t0 = time.time()
    for ti, me in enumerate(teams):
        if len(me.get("players") or []) != cap:
            continue
        mine = [ok(n) for n in me["players"]]
        mine = [r for r in mine if r and r["cat"] == "starter" and 2500 <= r["value"] <= 6500]
        opps = [o for oi, o in enumerate(teams) if oi != ti]
        rng.shuffle(opps)
        for opp in opps[:max_opps]:
            theirs = [r for r in (ok(n) for n in opp["players"]) if r]
            fillers = [r for r in theirs if r["cat"] == "filler" and r["value"] >= 300]
            if not mine or len(fillers) < 3:
                continue
            x = rng.choice(mine)
            # Y slightly below X so the receiving side starts behind.
            cand = [
                r
                for r in theirs
                if r["cat"] != "filler" and 0.86 * x["value"] <= r["value"] <= 0.97 * x["value"]
            ]
            if not cand:
                continue
            y = rng.choice(cand)
            fl = rng.sample(fillers, 3)
            samples.append({"me": me, "x": x, "y": y, "fill": fl})
    results = []
    for s in samples:
        rec = {"me": s["me"], "x": s["x"], "y": s["y"], "fill": s["fill"], "steps": []}
        for k in range(0, 4):
            pin = [s["y"]["name"]] + [r["name"] for r in s["fill"][:k]]
            pout = [s["x"]["name"]]
            sa = run(s["me"], pin, pout, False)
            st = run(s["me"], pin, pout, True)
            a_ao, a_tc = comp_a(sa, False), comp_a(st, True)
            rc = st.get("rosterCapacity") or {}
            rec["steps"].append({
                "k": k,
                "assetOnlyOrd": ordinal(a_ao),
                "teamCtxOrd": ordinal(a_tc),
                "vaGap": a_ao["vaAdjustedGap"] if a_ao else None,
                "releaseCharged": (a_tc or {}).get("forcedReleaseCost"),
                "forcedDrops": len(rc.get("forcedDrops") or []),
                "dropValues": [d.get("value") for d in rc.get("forcedDrops") or []],
                "dropReleaseCosts": [d.get("releaseCost") for d in rc.get("forcedDrops") or []],
                "dropBasis": [d.get("valueBasis") for d in rc.get("forcedDrops") or []],
                "dropAcquiredInTrade": [bool(d.get("acquiredInTrade")) for d in rc.get("forcedDrops") or []],
                "_pin": pin,
                "_pout": pout,
            })  # fmt: skip
        results.append(rec)
    elapsed_d = time.time() - t0

    flips = absorbed = reversed_ = still = 0
    credit, charged = [], []
    basis: Counter = Counter()
    per_drop: list = []
    acquired = 0
    for rec in results:
        s0 = rec["steps"][0]
        for st in rec["steps"][1:]:
            basis.update(st["dropBasis"])
            per_drop += [c for c in st["dropReleaseCosts"] if isinstance(c, (int, float))]
            acquired += sum(st["dropAcquiredInTrade"])
            if st["assetOnlyOrd"] is None or s0["assetOnlyOrd"] is None or st["teamCtxOrd"] is None:
                continue
            if st["vaGap"] is not None and s0["vaGap"] is not None:
                credit.append(st["vaGap"] - s0["vaGap"])
                charged.append(st["releaseCharged"] or 0)
            if _sgn(st["assetOnlyOrd"]) != _sgn(s0["assetOnlyOrd"]):
                flips += 1
                if _sgn(st["teamCtxOrd"]) == _sgn(s0["teamCtxOrd"]):
                    absorbed += 1
                elif _sgn(st["teamCtxOrd"]) < _sgn(s0["teamCtxOrd"]):
                    reversed_ += 1
                else:
                    still += 1
    share = [ch / c for c, ch in zip(credit, charged) if c and c > 0]
    d_out = {
        "path": "src/trade/analyze_service.simulate_for_team (+ analyze_trade lenses and "
        "trade_decision._objective_value = Component A: VA gap minus the forced-release cost "
        "of the cuts the trade ADDS) — production GEOM_78 only, Team Context ON vs Asset-Only",
        "design": "every dynasty_main roster at exactly the 58 cap receives: sends one of its own "
        "genuine starters X (2,500-6,500) for an opponent asset Y at 86-97% of X, then 1-3 of that "
        "opponent's expendable fillers (>= 300, non-quarantined) are added to what it receives",
        "samples": len(results),
        "sweetenedSteps": sum(len(r["steps"]) - 1 for r in results),
        "fillerFlipsAssetOnly": flips,
        "flipsNeutralisedByTeamContext": absorbed,
        "flipsOverAbsorbed_verdictMovesAgainstReceiver": reversed_,
        "flipsSurvivingTeamContext": still,
        "forcedDropBasis": dict(basis),
        "forcedDropsThatAreTheJustAcquiredFiller": acquired,
        "releaseCostPerForcedDropMedian": _r(statistics.median(per_drop)) if per_drop else None,
        "fillerVaCreditMedian": _r(statistics.median(credit)) if credit else None,
        "releaseChargedMedian": _r(statistics.median(charged)) if charged else None,
        "releaseAsShareOfFillerCreditMedian": _r(statistics.median(share), 3) if share else None,
        "localLimit": "the roster-utility lens (lineup effect, Component B) needs the box-local "
        "projection snapshot; locally it is 'projection_basis_no_projection_snapshot', so every "
        "Team-Context headline is NOT_ENOUGH_EVIDENCE here.  Component A (the forced-drop "
        "release charge) is fully computed and is what is measured.",
        "flipDefinition": "same region rule as S3 (receiver disfavoured / fair / favoured)",
        "elapsedSec": round(elapsed_d, 1),
        "examples": [
            {"send": f"{r['x']['name']} ({r['x']['value']:.0f})",
             "receive": f"{r['y']['name']} ({r['y']['value']:.0f})",
             "fillers": [f"{f['name']} ({f['value']:.0f})" for f in r["fill"]],
             "steps": [{k: v for k, v in st.items() if not k.startswith("_")} for st in r["steps"]]}
            for r in results[:4]
        ],
    }  # fmt: skip

    # 5e. public category (fairness-only = asset-only analyze) under every treatment.
    per_trade = []
    for rec in results:
        for st in rec["steps"]:
            per_trade.append((rec, st))
    cats = {t: [] for t in TREATMENTS}
    skipped_ambiguous = 0
    for t in TREATMENTS:
        for rec, st in per_trade:
            assets = [rec["x"], rec["y"]] + rec["fill"][: st["k"]]
            vmap: dict = {}
            amb = False
            for r in assets:
                c = T.anchor_for(t, r["pos"], rep)
                if r["value"] in vmap and vmap[r["value"]] != c:
                    amb = True
                vmap[r["value"]] = c
            if amb and t.endswith("replacement"):
                skipped_ambiguous += 1
                cats[t].append(None)
                continue
            if t == INCUMBENT:
                gap = None
            else:
                u = T.TREATMENTS[t]["u"]

                def gap(a, b, _u=u, _vm=vmap):
                    return _u([(v, _vm.get(v, rep["*"])) for v in a]) - _u(
                        [(v, _vm.get(v, rep["*"])) for v in b]
                    )

            with FR.installed(gap):
                sim = run(rec["me"], st["_pin"], st["_pout"], False)
                an = AS.analyze_for_team(sim, contract=contract, counterfactuals=False)
            cats[t].append(TD.public_category_from_decision(an.get("decision")))
    assert pm.active_model_id() == pm.GEOM_Q078_V1
    e_out = {}
    for t in TREATMENTS:
        pairs = [(a, b) for a, b in zip(cats[INCUMBENT], cats[t]) if b is not None]
        e_out[t] = {
            "evaluated": len(pairs),
            "categoryChangedVsGEOM_78": sum(a != b for a, b in pairs),
            "categoryCounts": dict(Counter(b for _, b in pairs)),
            "transitions": dict(Counter(f"{a}->{b}" for a, b in pairs if a != b)),
        }
    e_res = {
        "path": "trade_decision.public_category_from_decision over analyze_for_team (asset-only, "
        "counterfactuals off) with each treatment installed in-process behind "
        "package_model._geom_pair (FR.installed, always restored); replacement anchors mapped "
        "per trade from that trade's own assets (value -> c), skipped if ambiguous",
        "sample": "the War Room trades (base + 1..3 filler sweeteners)",
        "skippedAmbiguousValueMap": skipped_ambiguous,
        "noPublicPathChanged": "no public route exists for a fairness-only calculator yet; this "
        "is a shadow of the category mapping only, and the production dispatch was restored "
        "after every call (asserted)",
        "byTreatment": e_out,
    }
    return {"d_warRoom": d_out, "e_publicCategory": e_res}


# ── 6. mathematical properties ───────────────────────────────────────────

PROPS = (
    "addAssetNeverHurts",
    "raiseValueNeverHurts",
    "orderInvariance",
    "swapNegatesGap",
    "oneForOneIsRawGap",
    "addedPieceAddsAtMostItsValue",
    "continuityEpsilon",
    "homogeneity",
    "unbundlingNeverHelps",
)


def properties(rep, cases: int = 3000, seed: int = SEED + 3) -> dict:
    rng = random.Random(seed)
    pos = ["QB", "RB", "WR", "TE", "DL", "LB", "DB", None]
    plan = []
    for _ in range(cases):
        A = [(float(rng.randint(100, 9999)), rng.choice(pos)) for _ in range(rng.randint(1, 6))]
        B = [(float(rng.randint(100, 9999)), rng.choice(pos)) for _ in range(rng.randint(1, 6))]
        pa, pb = A[:], B[:]
        rng.shuffle(pa)
        rng.shuffle(pb)
        plan.append({"A": A, "B": B, "x": (float(rng.randint(1, 9999)), rng.choice(pos)),
                     "i": rng.randrange(len(A)), "d": float(rng.randint(1, 2000)),
                     "k": rng.uniform(0.25, 3.0), "pa": pa, "pb": pb,
                     "one": ((float(rng.randint(1, 9999)), rng.choice(pos)),
                             (float(rng.randint(1, 9999)), rng.choice(pos)))})  # fmt: skip
    tol = 1e-6
    out = {}
    for t in TREATMENTS:

        def gf(a, b, _t=t):
            return T.gap(_t, a, b, rep)

        f = dict.fromkeys(PROPS, 0)
        one_changed = 0
        for c in plan:
            A, B = c["A"], c["B"]
            g = gf(A, B)
            f["addAssetNeverHurts"] += (g - gf(A + [c["x"]], B)) > tol
            f["addAssetNeverHurts"] += (gf(A, B + [c["x"]]) - g) > tol
            raised = A[:]
            raised[c["i"]] = (raised[c["i"]][0] + c["d"], raised[c["i"]][1])
            f["raiseValueNeverHurts"] += (g - gf(raised, B)) > tol
            f["orderInvariance"] += abs(gf(c["pa"], c["pb"]) - g) > tol
            f["swapNegatesGap"] += abs(gf(B, A) + g) > tol
            (a1, b1) = c["one"]
            d1 = abs(gf([a1], [b1]) - (a1[0] - b1[0]))
            f["oneForOneIsRawGap"] += d1 > tol
            one_changed += d1 > 0.5
            f["addedPieceAddsAtMostItsValue"] += (gf(A + [c["x"]], B) - g) > c["x"][0] + tol
            f["continuityEpsilon"] += abs(gf(A + [(0.01, None)], B) - g) > 0.01 + tol
            k = c["k"]
            hk = gf([(k * v, p) for v, p in A], [(k * v, p) for v, p in B])
            f["homogeneity"] += abs(hk - k * g) > max(1e-6 * (1 + k), 1e-9 * abs(k * g))
            i = c["i"]
            v, p = A[i]
            split = A[:i] + A[i + 1 :] + [(v / 2, p), (v / 2, p)]
            f["unbundlingNeverHelps"] += (gf(split, B) - g) > tol
        out[t] = {
            "approach": T.TREATMENTS[t]["approach"],
            "anchor": T.TREATMENTS[t]["anchor"],
            "failures": f,
            "oneForOneChangedOver0p5": one_changed,
            "summary": {p: ("PASS" if f[p] == 0 else f"FAIL ({f[p]}/{cases})") for p in PROPS},
        }
    return {"cases": cases, "seed": seed, "piecesPerSide": [1, 6], "valueRange": [100, 9999],
            "anchors": "this board's replacement dict for *_replacement; 2,000 for *_market",
            "byTreatment": out,
            "pinnedBy": "tests/scripts/test_low_value_asset_treatments.py (treatment math)"}  # fmt: skip


# ── main ──────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--per-cell", type=int, default=30, help="flip-study bases per cell")
    ap.add_argument("--sample", type=int, default=2000)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--skip-replay", action="store_true")
    ap.add_argument("--war-room-opps", type=int, default=5)
    args = ap.parse_args()
    assert pm.active_model_id() == pm.GEOM_Q078_V1, "the incumbent must be the active model"
    t0 = time.time()
    zpath, member, blob, raw = newest_board()
    scratch = Path(tempfile.mkdtemp(prefix="lva_shadow_"))
    raw_path = scratch / member
    raw_path.write_bytes(blob)

    pool = pending = None
    if not args.skip_replay:
        jobs = [(str(raw_path), [m]) for m in FINDER_MODELS]
        pool = multiprocessing.get_context("fork").Pool(min(args.workers, len(jobs)))
        pending = pool.map_async(_replay_chunk, jobs)

    timings = {}
    t = time.time()
    ctx = build_context(raw)
    timings["board+anchors"] = round(time.time() - t, 1)
    rows, rep = ctx["rows"], ctx["rep"]
    classification = classify_assets(ctx)
    t = time.time()
    flips = flip_study(rows, rep, per_cell=args.per_cell)
    timings["flipStudy"] = round(time.time() - t, 1)
    examples = real_examples(rows, rep)
    t = time.time()
    sample = fairness_sample(rows, rep, n=args.sample)
    timings["fairnessSample"] = round(time.time() - t, 1)
    history = trade_history(raw, ctx)
    t = time.time()
    wr = war_room(ctx, max_opps=args.war_room_opps)
    timings["warRoom+public"] = round(time.time() - t, 1)
    math_tbl = properties(rep)
    assert pm.active_model_id() == pm.GEOM_Q078_V1

    replay_out: dict = {"run": False, "reason": "--skip-replay"}
    if pending is not None:
        parts = pending.get()
        pool.close()
        pool.join()
        replay = P3L._merge(parts, FINDER_MODELS)
        comp = FR.compare(replay)
        replay_out = {
            "run": True,
            "context": "context-free (use_team_context=False), as Phase 2/3",
            "harness": "scripts/package_model_finder_replay.py; treatment installed behind "
            "package_model._geom_pair in-process, always restored",
            "modelsCovered": FINDER_MODELS,
            "notCovered": {
                "A_curve_replacement / B_currency_replacement": "not covered: the installed "
                "dispatch sees values only, and on this board value -> anchor is not a function "
                f"({ctx['ambiguousValues']} canonical values are shared by assets with different "
                "anchors, almost all a pick and a player), so a replacement anchor cannot be "
                "attached unambiguously"
            },
            "surfaces": replay["surfaces"],
            "teamCount": len(replay["teams"]),
            "timingsSec": replay["timingsSec"],
            "comparisonVsIncumbent": comp,
            "examples": P3L._strip_examples(FR.examples(replay), set(FINDER_MODELS), per=4),
        }
    shutil.rmtree(scratch, ignore_errors=True)

    result = {
        "purpose": "RESEARCH ONLY, EXPLORATORY (prereg 160cc28b5). geom_q078_v1 (q = 0.78) stays "
        "active; no canonical value, band, recommendation or served path changed.",
        "generatedBy": "scripts/low_value_asset_shadow_replay.py",
        "activeModelAtRun": pm.active_model_id(),
        "board": {
            "archive": str(zpath.relative_to(REPO)),
            "member": member,
            "sha256": hashlib.sha256(blob).hexdigest(),
            "methodology": "built through src.api.data_contract.build_api_data_contract with "
            "today's code (today's methodology), not the archived contract",
            "pricedAssets": len(rows),
            "byClass": dict(Counter(r["cls"] for r in rows.values())),
        },
        "codeSha": P1._git_sha(),
        "treatments": {
            t: {"approach": s["approach"], "anchor": s["anchor"]} for t, s in T.TREATMENTS.items()
        },
        "S1_replacementAnchors": ctx["anchors"],
        "S2_classification": classification,
        "S3_fillerFlipStudy": flips,
        "S4_realExamples": examples,
        "S5a_calculatorFairnessSample": sample,
        "S5b_tradeFinderReplay": replay_out,
        "S5c_tradeHistory": history,
        "S5d_warRoomTeamContext": wr["d_warRoom"],
        "S5e_publicCategoryShadow": wr["e_publicCategory"],
        "S6_mathematicalProperties": math_tbl,
        "timingsSec": {**timings, "total": round(time.time() - t0, 1)},
    }
    P2.assert_aggregate_only({k: v for k, v in result.items() if k not in ("board", "codeSha")})
    P2.assert_aggregate_only({k: v for k, v in result["board"].items() if k != "sha256"})
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, default=str) + "\n")
    print(json.dumps({"out": str(out), "timingsSec": result["timingsSec"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
