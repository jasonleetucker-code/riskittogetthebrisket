#!/usr/bin/env python3
"""Low-value depth disclosure — candidate trigger rules, SHADOW measurement.  DESIGN ONLY.

Owner decision 2026-10-20 (``docs/owner/LOW_VALUE_ASSET_OWNER_DECISIONS_2026-10-20.md``
§1, §5): an optional, league-aware INFORMATIONAL disclosure that low-value depth may
be treated differently in the trade market.  It must never change a value, a
verdict or a fairness threshold.  Nothing here is wired into a served path: this
script only MEASURES how often each candidate trigger rule would fire.

Design record: ``docs/trade/LOW_VALUE_DEPTH_DISCLOSURE_DESIGN_2026-10-20.md``.

What is reused, and what is re-implemented and verified:

* board, rosters, optimal lineups and replacement anchors —
  ``low_value_asset_shadow_replay.build_context`` (one contract build of the
  newest archive, today's code; the anchors come from the canonical owners
  ``waiver_values_by_position`` and ``faab_engine.resolve_anchors``);
* the §3 classification (genuine starter / usable depth / expendable filler) —
  ``classify_assets``;
* the verdict — ``low_value_asset_shadow_replay.verdict``.  Only the band
  classifier, ``fairness_bands.classify``, is the canonical function.  The package
  utility is the research ``owa`` (q = 0.78 hard-coded) and the adjusted totals
  are the research re-implementation ``P2.adjusted``; neither is the canonical
  dispatch.  So EVERY incumbent evaluation is checked against the canonical
  ``src/valuation_math/package_model.py`` dispatch for the active model
  (``geom_q078_v1``): the utility gap must equal ``geom_utility``'s to float
  tolerance, and the adjusted totals must equal ``adjusted_pair_totals``'s to
  within that function's whole-number rounding of the adjustment (0.5).  The run
  aborts otherwise; the count checked is reported as ``packageModelParity``;
* the naive comparator rule ("fire when B_currency_replacement changes the
  verdict") — the frozen treatment in ``low_value_asset_treatments``.

Populations:

1. the filler-flip study (S3), regenerated case-for-case with the same seed and
   checked against the committed ``shadow_replay.json`` counts;
2. a realistic 2-team calculator sample (S5a's population, same seed);
3. the own-league completed trades in the archive (graded with today's values);
4. the real-roster War Room trades (S5d's sampling, same seed), with the served
   analyze path re-run so the market ordinal used here is checked against the
   engine's own and the disclosure is cross-tabulated with the Team-Context verdict.

Anchor sensitivity: the current prereg anchor (``waiver_values_by_position``), a
healthy-only anchor (pinned from ``idp_anomaly.json`` H1, same board) and the LI-5
banded waiver level (``S1``), each under two piece thresholds ("prereg": below the
anchor and not a lineup starter; "floor": below min(anchor, lowest league starter)).

Output: ``docs/trade/evidence/low_value_depth_disclosure_2026-10-20/disclosure_shadow.json``
— aggregates and NFL player names only, checked with ``assert_aggregate_only``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import random
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
OUT_DEFAULT = "docs/trade/evidence/low_value_depth_disclosure_2026-10-20/disclosure_shadow.json"
LVA_EVIDENCE = REPO / "docs/valuation/evidence/low_value_assets_2026-10-20"
sys.path.insert(0, str(REPO))


def _load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


S = _load("low_value_asset_shadow_replay")  # board / anchors / classification / verdict
T = S.T  # frozen treatments (the naive comparator)
P2 = S.P2  # assert_aggregate_only, structure_bin, orient

from src.valuation_math import fairness_bands  # noqa: E402
from src.valuation_math import package_model as pm  # noqa: E402

INCUMBENT = S.INCUMBENT  # GEOM_78
NAIVE = S.C_SOURCE  # B_currency_replacement
SEED = S.SEED

#: Rule ids (design doc §3).  ``share`` threshold X is a declared PRIOR (one
#: quarter of the package), fixed before any measurement and never tuned.
SHARE_PRIOR = 0.25
RULES = (
    "A_dependence",
    "A_dependence_public",
    "A_guarded",
    "A_guarded_public",
    "A_guarded_publicFairOnly",
    "B_share25",
    "C_extraPieces",
    "naive_B",
)
RULE_TEXT = {
    "A_dependence": "the package a team RECEIVES holds >= 1 low-value depth (LVD) piece other "
    "than its single highest-valued piece, and removing those LVD pieces changes that team's "
    "fairness REGION (disfavoured / fair / favoured) under geom_q078_v1 + fairness_bands",
    "A_dependence_public": "as A_dependence, but only a change of the public FAIR / NOT FAIR "
    "state counts (fair <-> not fair; a change of direction alone does not)",
    "A_guarded": "A_dependence, and the team's own legs (what it receives plus what it gives, "
    "Rcv_i U Gv_i) hold >= 1 piece that is NOT low-value depth (a team whose legs are all "
    "low-value pieces never fires) - the guard was added after the unsweetened low-tier bases "
    "were seen firing (design §3.1), and is reported separately",
    "A_guarded_public": "A_guarded with A_dependence_public's FAIR / NOT FAIR change",
    "A_guarded_publicFairOnly": "A_guarded_public restricted to a team whose result is FAIR and "
    "becomes NOT FAIR without its LVD extras (never fires on a NOT FAIR result, so the "
    "disclosure cannot reveal which way a NOT FAIR trade leans - privacy M4).  OWNER OPTION "
    "ONLY, not recommended: when it fires it still leaks within-FAIR direction and, used as a "
    "per-asset oracle, the replacement anchors (design §9 R1/R2)",
    "B_share25": "the received package has >= 2 pieces and its LVD pieces other than the top "
    f"piece carry >= {SHARE_PRIOR:.0%} of its raw priced value (X is a PRIOR, not tuned)",
    "C_extraPieces": "the received package has more pieces than the package given in return, "
    "and at least one of its (n_received - n_given) lowest-valued pieces is LVD",
    "naive_B": "COMPARATOR ONLY (research §11 rejected it): the B_currency_replacement "
    "treatment's signed level differs from GEOM_78's",
}
THRESHOLD_MODES = ("prereg", "floor")


def _sgn(x):
    return (x > 0) - (x < 0)


def _pct(n, d):
    return None if not d else round(100.0 * n / d, 1)


# ── anchors ───────────────────────────────────────────────────────────────


def anchor_sets(ctx: dict) -> dict[str, dict[str, float]]:
    """Three replacement-level definitions on the SAME board.

    current  — prereg §2: best unrostered value per position (+ '*' FAAB V_repl);
    healthy  — the same, excluding players injured / inactive today (pinned from
               idp_anomaly.json H1, computed on this board by investigation B);
    li5Banded — the LI-5 banded waiver level (S1, ``li5_waiverBanded``).
    '*' (picks, unknown positions) is FAAB V_repl in all three.
    """
    cur = dict(ctx["rep"])
    idp = json.loads((LVA_EVIDENCE / "idp_anomaly.json").read_text())
    healthy = {
        p: float(v["value"]) for p, v in idp["H1_dataDefect"]["healthyWaiverBestByPosition"].items()
    }
    healthy["*"] = cur["*"]
    li5 = {"*": cur["*"]}
    for pos, e in ctx["anchors"]["byPosition"].items():
        if e.get("li5_waiverBanded") is not None:
            li5[pos] = float(e["li5_waiverBanded"])
    return {"current": cur, "healthy": healthy, "li5Banded": li5}


def make_lvd(ctx: dict, anchors: dict[str, float], mode: str):
    """Return ``lvd(row) -> True | False | None`` (None = cannot classify).

    A PICK is LVD when its value is below '*'.  A PLAYER is classified against its
    position's anchor ``R_pos``:

    * prereg — LVD iff not a genuine starter (in a league optimal lineup, or
      unrostered and valued >= the lowest league starter at the position) and
      value < R_pos (exactly the §3 'filler' class when anchors are 'current');
    * floor  — LVD iff value < min(R_pos, lowest league starter at the position).
      Every lineup starter is >= that floor, so no starter can be LVD.

    Missing is never zero: no row, no value, a quarantined row, or a position with no
    anchor -> None (UNKNOWN, design §2.2).
    """
    low = ctx["lowest_starter"]
    starters, rostered = ctx["starters"], ctx["rostered"]

    def lvd(r):
        if r is None or not isinstance(r.get("value"), (int, float)) or r["value"] <= 0:
            return None
        if r.get("quarantined"):
            return None
        if r["cls"] == "pick":
            return r["value"] < anchors["*"]
        pos = r.get("pos")
        if not pos or pos not in anchors:
            return None
        c = anchors[pos]
        if mode == "floor":
            if pos not in low:
                return None
            return r["value"] < min(c, low[pos])
        if r["name"] in starters:
            return False
        if r["name"] not in rostered and pos in low and r["value"] >= low[pos]:
            return False
        return r["value"] < c

    return lvd


# ── rules ─────────────────────────────────────────────────────────────────


#: Parity of every incumbent evaluation with the canonical package-model dispatch.
PARITY: Counter = Counter()
_UTILITY_RTOL = 1e-9  # relative float tolerance on the utility gap
_ADJUSTED_TOL = 0.5 + 1e-6  # the canonical adjustment is a whole number (js_round)


def _check_parity(R, G, v) -> None:
    """Abort unless the research verdict ``v`` matches the canonical dispatch on (R, G)."""
    a, b = [r["value"] for r in R], [r["value"] for r in G]
    mid = pm.active_model_id()
    q = pm.PACKAGE_MODELS[mid]["q"]
    cgap = pm.geom_utility(a, q) - pm.geom_utility(b, q)
    scale = max(1.0, sum(a), sum(b))
    if abs(cgap - v["gap"]) > _UTILITY_RTOL * scale:
        raise AssertionError(f"utility gap {v['gap']} != canonical {cgap}")
    xa, xb, _va, _vb = pm.adjusted_pair_totals(a, b, model_id=mid)
    if abs(xa - v["adjA"]) > _ADJUSTED_TOL or abs(xb - v["adjB"]) > _ADJUSTED_TOL:
        raise AssertionError(f"adjusted {(v['adjA'], v['adjB'])} != canonical {(xa, xb)}")
    PARITY["checked"] += 1
    # Informational: the band read on the canonical (whole-number) adjusted gap.
    clvl = fairness_bands.classify(xa - xb, max(xa, xb))["level"]
    PARITY["bandAgrees" if clvl == v["level"] else "bandDiffersOnlyByRounding"] += 1


def _ord(R, G, rep, treatment=INCUMBENT):
    v = S.verdict(treatment, [S._asset(r) for r in R], [S._asset(r) for r in G], rep)
    if treatment == INCUMBENT:
        _check_parity(R, G, v)
    return v["ord"]


def _asset_id(r) -> str:
    """Canonical asset id for the top-piece tie-break: player id, else the board name."""
    return f"player:{r['pid']}" if r.get("pid") else f"name:{r['name']}"


def top_piece(R):
    """The highest-valued received piece; ties go to the lowest asset id (design §2.3)."""
    return min(R, key=lambda r: (-r["value"], _asset_id(r)))


def evaluate_team(R, G, lvd, rep_naive) -> dict:
    """Every candidate rule for ONE team: R = what it receives, G = what it gives.

    Returns {rule: True | False | None}; None = not evaluated (an unclassifiable
    piece on either side), which the design maps to 'no disclosure'.
    """
    flags = [lvd(r) for r in R + G]
    if any(f is None for f in flags) or not R or not G:
        return dict.fromkeys(RULES)
    o = _ord(R, G, rep_naive)
    top = top_piece(R)
    extras = [r for r in R if r is not top and lvd(r)]
    out = {}
    if extras:
        R2 = [r for r in R if r not in extras]
        o2 = _ord(R2, G, rep_naive)
        out["A_dependence"] = _sgn(o2) != _sgn(o)
        out["A_dependence_public"] = (o2 == 0) != (o == 0)
        fair_only = o == 0 and o2 != 0
    else:
        out["A_dependence"] = out["A_dependence_public"] = False
        fair_only = False
    mixed = any(f is False for f in flags)
    out["A_guarded"] = out["A_dependence"] and mixed
    out["A_guarded_public"] = out["A_dependence_public"] and mixed
    out["A_guarded_publicFairOnly"] = fair_only and mixed
    tot = sum(r["value"] for r in R)
    out["B_share25"] = (
        len(R) >= 2 and tot > 0 and sum(r["value"] for r in extras) / tot >= SHARE_PRIOR
    )
    k = len(R) - len(G)
    if k > 0:
        tail = sorted(R, key=lambda r: r["value"])[:k]
        out["C_extraPieces"] = any(lvd(r) for r in tail)
    else:
        out["C_extraPieces"] = False
    out["naive_B"] = _ord(R, G, rep_naive, NAIVE) != o
    return out


def evaluate_trade(A, B, lvd, rep) -> dict:
    """2-team trade: package A goes to one team, package B to the other."""
    ta = evaluate_team(A, B, lvd, rep)  # the team receiving A
    tb = evaluate_team(B, A, lvd, rep)  # the team receiving B
    out = {}
    for rule in RULES:
        if ta[rule] is None or tb[rule] is None:
            out[rule] = None
        elif rule == "naive_B":
            out[rule] = ta[rule]  # symmetric: one verdict per trade
        else:
            out[rule] = bool(ta[rule] or tb[rule])
    return {"trade": out, "A": ta, "B": tb}


# ── population 1: the filler-flip study, regenerated ─────────────────────


def regenerate_flip_cases(rows, per_cell: int, seed: int = SEED):
    """Byte-for-byte the case generation in ``low_value_asset_shadow_replay.flip_study``
    (same RNG call order), returning the bases and cases instead of aggregates."""
    rng = random.Random(seed)
    pools = S._pools(rows)
    bases = []
    for cls in S.CLASSES:
        for comp in ("any", "starters_only"):
            if cls == "picks" and comp == "starters_only":
                continue
            pool = pools[(cls, comp)]
            for shape in S.SHAPES:
                for tier in S.TIERS:
                    for _ in range(per_cell):
                        b = S._make_base(rng, pool, shape, tier, cls)
                        if b:
                            bases.append({"cls": cls, "comp": comp, "shape": shape, "tier": tier,
                                          "A": b[0], "B": b[1]})  # fmt: skip
    cases = []
    for bi, b in enumerate(bases):
        used = {r["name"] for r in b["A"] + b["B"]}
        ra, rb = (sum(r["value"] for r in b[s]) for s in ("A", "B"))
        behind = "A" if ra < rb else "B"
        for cat in S.CATS:
            spool = [r for r in pools[(b["cls"], cat)] if r["name"] not in used]
            if len(spool) < 4:
                continue
            draw = rng.sample(spool, 4)
            for k in range(1, 5):
                cases.append({"base": bi, "cat": cat, "k": k, "behind": behind, "sweet": draw[:k]})
    return bases, cases


def flip_population(rows, rep, lvd_by_variant: dict, per_cell: int) -> dict:
    bases, cases = regenerate_flip_cases(rows, per_cell)

    def sides(b, c=None):
        A, B = list(b["A"]), list(b["B"])
        if c is not None:
            if c["behind"] == "A":
                A = A + c["sweet"]
            else:
                B = B + c["sweet"]
        return A, B

    # Reproduction check against the committed evidence (incumbent region flips and
    # the naive rule's fire counts per sweetener category / class).
    base_ord = [_ord(*sides(b), rep) for b in bases]
    flip = []
    made_fair = []
    for c in cases:
        b = bases[c["base"]]
        s = 1 if c["behind"] == "A" else -1
        o0 = s * base_ord[c["base"]]
        o1 = s * _ord(*sides(b, c), rep)
        flip.append(_sgn(o1) != _sgn(o0))
        made_fair.append(o0 < 0 and o1 == 0)
    committed = json.loads((LVA_EVIDENCE / "shadow_replay.json").read_text())["S3_fillerFlipStudy"]
    repro_flips = {
        cls: {cat: sum(1 for i, c in enumerate(cases)
                       if flip[i] and c["cat"] == cat and bases[c["base"]]["cls"] == cls)
              for cat in ("filler", "depth")}
        for cls in S.CLASSES
    }  # fmt: skip
    expect_flips = {
        cls: {
            cat: committed["byClass"][cls][cat][INCUMBENT]["flips"] for cat in ("filler", "depth")
        }
        for cls in S.CLASSES
    }

    out: dict = {"variants": {}}
    for vname, lvd in lvd_by_variant.items():
        base_eval = [evaluate_trade(*sides(b), lvd, rep) for b in bases]
        per = defaultdict(lambda: defaultdict(Counter))
        attributable = defaultdict(lambda: defaultdict(Counter))
        for i, c in enumerate(cases):
            b = bases[c["base"]]
            ev = evaluate_trade(*sides(b, c), lvd, rep)
            sw = c["behind"]  # the sweetened package (its receiver is helped)
            be = base_eval[c["base"]]
            fl = "flip" if flip[i] else "noflip"
            groups = [c["cat"], f"{c['cat']}|{fl}", f"{c['cat']}|{fl}|{b['cls']}"]
            if b["comp"] == "starters_only":
                groups.append(f"{c['cat']}|starterOnlyBase")
            if made_fair[i]:
                groups.append(f"{c['cat']}|madeFair")
            for g in groups:
                per[g]["cases"]["n"] += 1
                for rule in RULES:
                    v = ev["trade"][rule]
                    if v is None:
                        per[g]["notEvaluated"][rule] += 1
                    elif v:
                        per[g]["fires"][rule] += 1
                    # attributable to the sweeteners: fires on the sweetened package
                    # now, and did not fire on that same package before sweetening.
                    if rule != "naive_B":
                        if ev[sw][rule] and not be[sw][rule]:
                            attributable[g]["fires"][rule] += 1
        table = {}
        for g, e in sorted(per.items()):
            n = e["cases"]["n"]
            table[g] = {
                "cases": n,
                "fires": {r: e["fires"][r] for r in RULES},
                "firePct": {r: _pct(e["fires"][r], n) for r in RULES},
                "sweetenerAttributableFirePct": {
                    r: _pct(attributable[g]["fires"][r], n) for r in RULES if r != "naive_B"
                },
                "notEvaluated": {r: e["notEvaluated"][r] for r in RULES if e["notEvaluated"][r]},
            }
        bt = defaultdict(Counter)
        for b, be in zip(bases, base_eval):
            for key in ("ALL", f"tier:{b['tier']}", f"class:{b['cls']}"):
                bt[key]["n"] += 1
                for r in RULES:
                    bt[key][r] += bool(be["trade"][r])
        table["baseTradesUnsweetened"] = {
            key: {"cases": e["n"], "firePct": {r: _pct(e[r], e["n"]) for r in RULES}}
            for key, e in sorted(bt.items())
        }
        out["variants"][vname] = table
    out["design"] = {
        "bases": len(bases),
        "cases": len(cases),
        "perCell": per_cell,
        "groups": "'<cat>' = every case whose 1-4 sweeteners are of that §3 class (current "
        "anchors, the study's own labels); '|flip' = the incumbent verdict crosses a region for "
        "the sweetening side (the S3 primary flip, i.e. 'filler-caused flip' when cat = filler); "
        "'|noflip' = it does not; '|starterOnlyBase' = every base asset is a genuine starter; "
        "'|madeFair' = the sweeteners turned a result AGAINST the sweetening side into FAIR (the "
        "public 'unfair made fair' case)",
        "sweetenerAttributable": "fires on the SWEETENED package and did not fire on that same "
        "package before the sweeteners were added",
    }
    naive_cur = out["variants"]["current|prereg"]
    out["reproduction"] = {
        "incumbentRegionFlips_regenerated": repro_flips,
        "incumbentRegionFlips_committed": expect_flips,
        "flipsMatch": repro_flips == expect_flips,
        "naiveRuleFires_regenerated": {cat: naive_cur[cat]["fires"]["naive_B"] for cat in S.CATS},
        "naiveRuleFires_committed": {
            cat: committed["C_informationalDisclosure"][cat]["disclosureFires"] for cat in S.CATS
        },
    }
    return out


# ── population 2: realistic 2-team calculator sample ─────────────────────


def calculator_sample(rows, rep, lvd_by_variant: dict, n: int = 2000) -> dict:
    """S5a's population, same seed: top-500 assets, 1-3 v na..na+4, raw gap <= 25%."""
    rng = random.Random(SEED + 1)
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
    out = {}
    for vname, lvd in lvd_by_variant.items():
        by_bin = defaultdict(Counter)
        by_level = defaultdict(Counter)
        for A, B in trades:
            ev = evaluate_trade(A, B, lvd, rep)
            vb = P2.structure_bin(*P2.orient([r["value"] for r in A], [r["value"] for r in B]))
            lvl = "fair" if _ord(A, B, rep) == 0 else "notFair"
            for key, tbl in ((vb, by_bin), ("ALL", by_bin), (lvl, by_level)):
                tbl[key]["n"] += 1
                for r in RULES:
                    tbl[key][r] += bool(ev["trade"][r])
        out[vname] = {
            "byStructureBin": {k: {"n": e["n"], **{r: _pct(e[r], e["n"]) for r in RULES}}
                               for k, e in sorted(by_bin.items())},
            "byIncumbentVerdict": {k: {"n": e["n"], **{r: _pct(e[r], e["n"]) for r in RULES}}
                                   for k, e in sorted(by_level.items())},
        }  # fmt: skip
    return {
        "n": n,
        "population": "S5a: top-500 non-quarantined board assets; 1-3 v na..min(na+4,7); raw gap "
        "<= 25% of the larger side; values are % of trades on which the rule fires for either team",
        "byVariant": out,
    }


# ── population 3: own-league completed trades ────────────────────────────


def own_league_trades(raw: dict, ctx: dict, lvd_by_variant: dict) -> dict:
    from src.api import pick_value_resolution as pvr  # noqa: PLC0415

    rows, rep, contract = ctx["rows"], ctx["rep"], ctx["contract"]
    trades = (raw.get("sleeper") or {}).get("trades") or []
    pick_rows = pvr.pick_rows_by_name(contract)
    cdy = int(contract.get("currentDraftYear") or 2027)

    def look(name):
        n = re.sub(r"\s*\(from [^)]*\)$", "", str(name))
        r = rows.get(n)
        if r is None and re.match(r"^\d{4} ", n):
            pv = pvr.resolve_pick_label_value(n, rows_by_name=pick_rows, current_draft_year=cdy)
            if pv is not None and pv.value:
                r = {"name": n, "value": float(pv.value), "cls": "pick", "pos": None}
        return r

    sides = []
    shape = Counter()
    for tr in trades:
        ss = tr.get("sides") or []
        shape[f"{len(ss)}team"] += 1
        for s in ss:
            got = [look(x) for x in s.get("got") or []]
            gave = [look(x) for x in s.get("gave") or []]
            sides.append((got, gave))
    out = {}
    for vname, lvd in lvd_by_variant.items():
        c = Counter()
        for got, gave in sides:
            if not got or not gave:
                # a give-only / receive-only side has no gap to classify: counted, not dropped
                c["notEvaluated_oneSided"] += 1
                continue
            if any(r is None for r in got + gave):
                c["notEvaluated_unpricedPiece"] += 1
                continue
            if any(r.get("quarantined") for r in got + gave):
                c["notEvaluated_quarantinedPiece"] += 1  # UNKNOWN (design §2.2)
                continue
            ev = evaluate_team(got, gave, lvd, rep)
            if any(ev[r] is None for r in RULES):
                c["notEvaluated_unclassifiablePiece"] += 1
                continue
            c["evaluated"] += 1
            for r in RULES:
                c[r] += bool(ev[r])
        out[vname] = {
            "teamSidesEvaluated": c["evaluated"],
            "teamSidesNotEvaluated": {
                "oneSided": c["notEvaluated_oneSided"],
                "unpricedPiece": c["notEvaluated_unpricedPiece"],
                "quarantinedPiece": c["notEvaluated_quarantinedPiece"],
                "unclassifiablePiece": c["notEvaluated_unclassifiablePiece"],
            },
            "firePct": {r: _pct(c[r], c["evaluated"]) for r in RULES},
        }
    return {
        "population": "every team side (got vs gave) of the own-league trades in the newest "
        "archive's sleeper.trades, valued with TODAY's board (not at-the-time values); a side "
        "is NOT evaluated (never priced at zero, never dropped) when it gives or receives "
        "nothing, or holds an unpriced, quarantined or unclassifiable piece; firePct is of the "
        "evaluated sides",
        "trades": len(trades),
        "tradesByTeamCount": dict(shape),
        "teamSides": len(sides),
        "byVariant": out,
    }


# ── population 4: real-roster War Room trades ────────────────────────────


def war_room_population(ctx: dict, lvd_by_variant: dict, run_engine: bool) -> dict:
    """S5d's sampling (same seed, same rules): a capped roster sends one of its genuine
    starters X (2,500-6,500) for an opponent asset Y at 86-97% of X, then receives
    k = 1..3 of that opponent's expendable fillers."""
    rows, rep, teams = ctx["rows"], ctx["rep"], ctx["teams"]
    cap = int(ctx["roster_settings"].get("rosterSize") or 0)
    rng = random.Random(SEED + 2)

    def ok(n):
        r = rows.get(n)
        return r if r and not r["quarantined"] and r["cls"] != "pick" else None

    samples = []
    for ti, me in enumerate(teams):
        if len(me.get("players") or []) != cap:
            continue
        mine = [r for r in (ok(n) for n in me["players"]) if r]
        mine = [r for r in mine if r["cat"] == "starter" and 2500 <= r["value"] <= 6500]
        opps = [o for oi, o in enumerate(teams) if oi != ti]
        rng.shuffle(opps)
        for opp in opps[:5]:
            theirs = [r for r in (ok(n) for n in opp["players"]) if r]
            fillers = [r for r in theirs if r["cat"] == "filler" and r["value"] >= 300]
            if not mine or len(fillers) < 3:
                continue
            x = rng.choice(mine)
            cand = [r for r in theirs
                    if r["cat"] != "filler" and 0.86 * x["value"] <= r["value"] <= 0.97 * x["value"]]  # fmt: skip
            if not cand:
                continue
            y = rng.choice(cand)
            samples.append({"me": me, "x": x, "y": y, "fill": rng.sample(fillers, 3)})

    engine = {}
    if run_engine:
        from src.trade import analyze_service as AS  # noqa: PLC0415
        from src.trade import analyze_trade as AT  # noqa: PLC0415
        from src.trade import trade_decision as TD  # noqa: PLC0415

        def ordinal(sim, tc):
            market = AT._market_lens(sim)
            if not market.available:
                return None
            feas = (AT._feasibility_lens(sim) if tc
                    else AT._excluded_by_mode("feasibility", AT.LINEAGE_ROSTER_RULES))  # fmt: skip
            a = TD._objective_value(market, feas)
            return _sgn(a["netGap"]) * S.LEVEL_RANK[a["band"]["level"]]

        for si, s in enumerate(samples):
            for k in range(4):
                pin = [s["y"]["name"]] + [r["name"] for r in s["fill"][:k]]
                res = {}
                for tc in (False, True):
                    sim = AS.simulate_for_team(
                        ctx["contract"], league_key=S.LEAGUE, roster_settings=ctx["roster_settings"],
                        resolved_team=s["me"], players_in=pin, players_out=[s["x"]["name"]],
                        team_context=tc, for_analysis=True,
                    )  # fmt: skip
                    res[tc] = ordinal(sim, tc)
                engine[(si, k)] = res
    out = {}
    agree = disagree = 0
    for vname, lvd in lvd_by_variant.items():
        by_k = defaultdict(Counter)
        cross = defaultdict(Counter)
        for si, s in enumerate(samples):
            for k in range(4):
                R, G = [s["y"]] + s["fill"][:k], [s["x"]]
                ev = evaluate_team(R, G, lvd, rep)
                by_k[k]["n"] += 1
                for r in RULES:
                    by_k[k][r] += bool(ev[r])
                if (si, k) in engine and vname == "current|prereg":
                    mo = engine[(si, k)][False]
                    if mo is not None:
                        agree += mo == _ord(R, G, rep)
                        disagree += mo != _ord(R, G, rep)
                if k and (si, k) in engine:
                    e0, e1 = engine[(si, 0)], engine[(si, k)]
                    if None in (e0[False], e1[False], e1[True], e0[True]):
                        continue
                    if _sgn(e1[False]) == _sgn(e0[False]):
                        outcome = "noAssetOnlyFlip"
                    elif _sgn(e1[True]) == _sgn(e0[True]):
                        outcome = "flipNeutralisedByTeamContext"
                    elif _sgn(e1[True]) < _sgn(e0[True]):
                        outcome = "flipOverCorrected"
                    else:
                        outcome = "flipSurvivesTeamContext"
                    cross[outcome]["n"] += 1
                    for r in RULES[:5]:
                        cross[outcome][r] += bool(ev[r])
                    # the disclosure beside a Team-Context verdict that now goes AGAINST
                    # the receiver: the copy must still read correctly (design §4.4).
                    if ev["A_dependence"] and e1[True] < 0:
                        cross[outcome]["A_dependence_besideTeamCtxVerdictAgainstReceiver"] += 1
        out[vname] = {
            "byFillersAdded": {str(k): {"n": e["n"], **{r: _pct(e[r], e["n"]) for r in RULES}}
                               for k, e in sorted(by_k.items())},
            "crossTabWithTeamContext": {k: dict(v) for k, v in sorted(cross.items())},
        }  # fmt: skip
    return {
        "samples": len(samples),
        "steps": 4 * len(samples),
        "engineRerun": run_engine,
        "marketOrdinalMatchesServedAssetOnlyLens": {"agree": agree, "disagree": disagree},
        "note": "rules are evaluated on the MARKET (asset-only) fairness of the trade; the served "
        "Team-Context verdict is reported beside it, never changed",
        "byVariant": out,
    }


# ── worked examples ──────────────────────────────────────────────────────


EXAMPLES = (
    ("Hurts for Egbuka", ["Jalen Hurts"], ["Emeka Egbuka"]),
    ("Hurts for Egbuka + Hodgins", ["Jalen Hurts"], ["Emeka Egbuka", "Isaiah Hodgins"]),
    ("Hurts for Egbuka + four ~900 fillers", ["Jalen Hurts"],
     ["Emeka Egbuka", "Isaiah Hodgins", "Frank Gore", "Khalil Herbert", "Mason Tipton"]),
    ("Gibbs for Smith + Higgins + four ~1,000 fillers", ["Jahmyr Gibbs"],
     ["DeVonta Smith", "Tee Higgins", "Nick Westbrook-Ikhine", "Kalel Mullings",
      "Xavier Restrepo", "Jarrett Stidham"]),
    ("Gibbs for Young + Kraft", ["Jahmyr Gibbs"], ["Bryce Young", "Tucker Kraft"]),
    ("Gibbs for six starters / usable depth", ["Jahmyr Gibbs"],
     ["Blake Corum", "Pat Freiermuth", "Eli Raridon", "Xavier Worthy", "David Montgomery",
      "Antonio Williams"]),
    ("Wilson for Ferguson + Kelce", ["Garrett Wilson"], ["Jake Ferguson", "Travis Kelce"]),
    ("Schwesinger for Baun + Parsons", ["Carson Schwesinger"], ["Zack Baun", "Micah Parsons"]),
    ("Love for 2027 1.10 + 2028 Late 1st", ["Jeremiyah Love"], ["2027 Pick 1.10", "2028 Late 1st"]),
)  # fmt: skip


def worked_examples(ctx, lvd_by_variant) -> list:
    rows, rep = ctx["rows"], ctx["rep"]

    def nearest(pred, target, k, used):
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

    specs = [(lbl, [rows.get(n) for n in a], [rows.get(n) for n in b]) for lbl, a, b in EXAMPLES]
    # Two deterministic constructions (S4's): a WR starter for an IDP starter + two DB
    # fillers near 1,100; an early rookie first for a late first + two filler picks.
    used: set = set()
    wr = nearest(
        lambda r: r["group"] == "offense" and r["pos"] == "WR" and r["cat"] == "starter",
        4200,
        1,
        used,
    )
    s2 = nearest(lambda r: r["group"] == "idp" and r["cat"] == "starter", 3500, 1, used)
    f2 = nearest(
        lambda r: r["group"] == "idp" and r["pos"] == "DB" and r["cat"] == "filler", 1100, 2, used
    )
    specs.append(("WR starter for IDP starter + two DB fillers", wr, s2 + f2))
    used = set()
    hi = nearest(lambda r: r["cls"] == "pick" and "Pick 1." in r["name"], 5100, 1, used)
    lo = nearest(lambda r: r["cls"] == "pick" and "Pick 1." in r["name"], 3900, 1, used)
    fps = nearest(lambda r: r["cls"] == "pick" and r["cat"] == "filler", 1250, 2, used)
    specs.append(("Early first for late first + two filler picks", hi, lo + fps))
    out = []
    for lbl, A, B in specs:
        if any(r is None for r in A + B):
            out.append({"case": lbl, "skipped": "asset not priced on this board"})
            continue
        v = S.verdict(INCUMBENT, [S._asset(r) for r in A], [S._asset(r) for r in B], rep)
        _check_parity(A, B, v)
        e = {
            "case": lbl,
            "A": [f"{r['name']} ({r['pos'] or 'pick'}, {r['value']:.0f}, {r['cat']})" for r in A],
            "B": [f"{r['name']} ({r['pos'] or 'pick'}, {r['value']:.0f}, {r['cat']})" for r in B],
            "incumbent": {"gapA": round(v["gap"]), "level": v["level"],
                          "favours": "A" if v["lead"] == 1 else "B" if v["lead"] == -1 else "even"},
            "byVariant": {},
        }  # fmt: skip
        for vname, lvd in lvd_by_variant.items():
            ev = evaluate_trade(A, B, lvd, rep)
            e["byVariant"][vname] = {
                "lvdPiecesInB": [r["name"] for r in B if lvd(r)],
                "lvdPiecesInA": [r["name"] for r in A if lvd(r)],
                "firesForReceiverOfB": {r: ev["B"][r] for r in RULES},
                "firesForReceiverOfA": {r: ev["A"][r] for r in RULES},
            }
        out.append(e)
    return out


def lvd_census(ctx, lvd_by_variant) -> dict:
    out = {}
    for vname, lvd in lvd_by_variant.items():
        c = defaultdict(Counter)
        for r in ctx["rows"].values():
            key = "PICK" if r["cls"] == "pick" else (r["pos"] or "UNKNOWN")
            f = lvd(r)
            c[key]["lvd" if f else ("unclassifiable" if f is None else "notLvd")] += 1
            if f and r["name"] in ctx["rostered"]:
                c[key]["lvdRostered"] += 1
        out[vname] = {k: dict(v) for k, v in sorted(c.items())}
    return out


def thresholds(ctx, sets) -> dict:
    low = ctx["lowest_starter"]
    out = {}
    for aname, a in sets.items():
        out[aname] = {}
        for pos in ("QB", "RB", "WR", "TE", "DL", "LB", "DB"):
            if pos in a and pos in low:
                out[aname][pos] = {"anchor": round(a[pos]), "lowestLeagueStarter": round(low[pos]),
                                   "floorThreshold": round(min(a[pos], low[pos]))}  # fmt: skip
        out[aname]["*picks"] = round(a["*"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--per-cell", type=int, default=30)
    ap.add_argument("--no-engine", action="store_true", help="skip the War Room engine re-run")
    args = ap.parse_args()
    assert pm.active_model_id() == pm.GEOM_Q078_V1, "the incumbent must be the active model"
    t0 = time.time()
    zpath, member, blob, raw = S.newest_board()
    ctx = S.build_context(raw)
    S.classify_assets(ctx)  # §3 labels under the current anchors (the study's own labels)
    rep = ctx["rep"]
    sets = anchor_sets(ctx)
    variants = {
        f"{a}|{m}": make_lvd(ctx, sets[a], m)
        for a in ("current", "healthy", "li5Banded")
        for m in THRESHOLD_MODES
    }
    timings = {"board": round(time.time() - t0, 1)}
    t = time.time()
    flips = flip_population(ctx["rows"], rep, variants, args.per_cell)
    timings["flipStudy"] = round(time.time() - t, 1)
    t = time.time()
    calc = calculator_sample(ctx["rows"], rep, variants)
    timings["calculatorSample"] = round(time.time() - t, 1)
    own = own_league_trades(raw, ctx, variants)
    t = time.time()
    wr = war_room_population(ctx, variants, run_engine=not args.no_engine)
    timings["warRoom"] = round(time.time() - t, 1)
    result = {
        "purpose": "DESIGN ONLY, SHADOW. Owner decisions 2026-10-20 §1/§5: an informational "
        "disclosure; geom_q078_v1, canonical values, verdicts and fairness thresholds unchanged. "
        "Nothing here is served.",
        "generatedBy": "scripts/low_value_depth_disclosure_shadow.py",
        "activeModelAtRun": pm.active_model_id(),
        "board": {
            "archive": str(zpath.relative_to(REPO)),
            "member": member,
            "sha256": hashlib.sha256(blob).hexdigest(),
            "pricedAssets": len(ctx["rows"]),
        },  # fmt: skip
        "rules": RULE_TEXT,
        "sharePrior": SHARE_PRIOR,
        "lvdDefinition": {
            "prereg": "players - not a genuine starter (league optimal lineup, or unrostered >= the "
            "lowest league starter at the position) and value < anchor[pos]; pick: value < "
            "anchor['*']",
            "floor": "players - value < min(anchor[pos], lowest league starter at pos); pick: value "
            "< anchor['*']",
            "missing": "no value, quarantined, no position or no anchor for the position = "
            "unclassifiable (UNKNOWN) -> the rule is NOT evaluated (no disclosure), never "
            "treated as zero or as low",
        },
        "topPieceTieBreak": "highest value; ties go to the lowest canonical asset id (the "
        "player id, else the board name)",
        "thresholdsByAnchorSet": thresholds(ctx, sets),
        "lvdCensus": lvd_census(ctx, variants),
        "P1_fillerFlipStudy": flips,
        "P2_calculatorSample": calc,
        "P3_ownLeagueTrades": own,
        "P4_warRoom": wr,
        "workedExamples": worked_examples(ctx, variants),
        "packageModelParity": {
            "modelId": pm.active_model_id(),
            "incumbentEvaluationsChecked": PARITY["checked"],
            "utilityGapTolerance": f"relative {_UTILITY_RTOL:g} of the larger raw side",
            "adjustedTotalTolerance": "0.5 (adjusted_pair_totals rounds the adjustment to a "
            "whole number, js_round)",
            "bandAgreesOnCanonicalAdjustedGap": PARITY["bandAgrees"],
            "bandDiffersOnlyByRounding": PARITY["bandDiffersOnlyByRounding"],
            "note": "every incumbent (GEOM_78) evaluation in every population was checked: the "
            "research utility gap equals package_model.geom_utility's and the research adjusted "
            "totals equal package_model.adjusted_pair_totals' within the tolerances above; any "
            "mismatch aborts the run.  The band comparison is informational (it reads "
            "fairness_bands.classify on the canonical whole-number adjusted gap)",
        },
        "timingsSec": {**timings, "total": round(time.time() - t0, 1)},
    }
    assert pm.active_model_id() == pm.GEOM_Q078_V1
    P2.assert_aggregate_only({k: v for k, v in result.items() if k != "board"})
    P2.assert_aggregate_only({k: v for k, v in result["board"].items() if k != "sha256"})
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, default=str) + "\n")
    print(json.dumps({"out": str(out), "timingsSec": result["timingsSec"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
