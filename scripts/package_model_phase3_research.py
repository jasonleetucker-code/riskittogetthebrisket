#!/usr/bin/env python3
"""Package Value Adjustment research, Phase 3 — production-ledger exploration and
preregistered validation (owner directive 2026-10-20).  RESEARCH ONLY.

``geom_q078_v1`` (q = 0.78) stays the production model.  Nothing here is wired
into a served path, and every candidate below is scored in this process only.

Run on the production host the same way as Phase 2 (``--box``): the read-only
audit hook (``research_readonly_guard.py``) is installed BEFORE any application
import, the ledger is opened ``mode=ro``, boards are rebuilt one at a time, and
the output is aggregates only (``assert_aggregate_only``).  Exit codes: 0 ok,
2 no ledger, 3 the guard refused a write / process start.

What it adds over Phase 2 (all frozen in
``docs/valuation/evidence/package_model_phase3_2026-10-20/PREREGISTRATION.md``):

* model FAMILIES around the incumbent — geometric ``GEOM_q``, power-norm
  ``LP_p`` and their common generalisation ``GP_q_g`` (geometric weights on
  power-transformed values: ``(sum q^i v_i^g)^(1/g)``; g = 1 is GEOM, q = 1 is
  LP) — plus non-homogeneous value-over-replacement DIAGNOSTICS (``VOR_*``),
  which can never be production candidates (they fail homogeneity) but say
  whether the market's discount follows ABSOLUTE value levels (a value-curve /
  replacement question) or RELATIVE package shape (a package question);
* a league-disjoint DISCOVERY / CONFIRMATION split (salted hash of the league),
  a preregistered selection rule applied on discovery only, and the frozen
  confirmation criteria on the other half;
* a PROSPECTIVE population (trades after the freeze date), reported once it
  is large enough — the only population nobody has looked at;
* league-clustered bootstrap uncertainty (leagues resampled, not trades);
* structure, composition (players / picks), IDP-position, source, vendor-flag,
  star-tier, period and board-lag strata; week-balanced means; and the implied
  market weight of the second / third piece by absolute and relative size.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(os.environ.get("RISKIT_APP_DIR") or Path(__file__).resolve().parents[1]).resolve()
SCRIPT_DIR = Path(__file__).resolve().parent

# numpy is third-party (no application code) and is imported before the guard
# because CPython's ctypes import performs a dlopen the guard refuses.  No
# bytecode is written either way.
sys.dont_write_bytecode = True
import numpy as np  # noqa: E402

if "--box" in sys.argv:
    _gspec = importlib.util.spec_from_file_location(
        "research_readonly_guard", SCRIPT_DIR / "research_readonly_guard.py"
    )
    GUARD = importlib.util.module_from_spec(_gspec)
    sys.modules["research_readonly_guard"] = GUARD
    _gspec.loader.exec_module(GUARD)
    GUARD.install()
else:
    GUARD = None

sys.path.insert(0, str(REPO))

_spec = importlib.util.spec_from_file_location(
    "package_model_phase2_research", SCRIPT_DIR / "package_model_phase2_research.py"
)
P2 = importlib.util.module_from_spec(_spec)
sys.modules["package_model_phase2_research"] = P2
_spec.loader.exec_module(P2)

# ── frozen protocol constants (PREREGISTRATION.md §3) ─────────────────────

FREEZE_DATE = "2026-10-20"  # trades AFTER this date are the prospective population
SPLIT_SALT = "phase3-pkg-2026-10-20"  # league-disjoint discovery / confirmation
UNEQUAL_BINS = ("1vN_small", "ordinary", "deep")
BINS = P2.BINS
BOOT_REPS = 400
BOOT_SEED = 20261020
PROSPECTIVE_MIN_UNEQUAL = 2000
NO_BIN_WORSE_TOLERANCE = 0.02
INCUMBENT = "GEOM_78"
PHASE2_REFERENCE = {  # the 2026-10-20 production report (all 18,031 graded trades)
    "GEOM_78": {"1vN_small": -0.3012, "ordinary": -0.1349, "deep": -0.1267},
    "LP_150": {"1vN_small": -0.1622, "ordinary": -0.077, "deep": -0.0943},
    "graded": 18031,
    "lastTradeDate": "2026-10-19",
}

# ── model families ────────────────────────────────────────────────────────

Q_GRID = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.78, 0.80, 0.85, 0.90)
P_GRID = (1.10, 1.20, 1.30, 1.40, 1.50, 1.60, 1.75, 2.00, 2.50, 3.00, 4.00)
GP_Q = (0.60, 0.70, 0.78, 0.85, 0.90)
GP_G = (1.10, 1.20, 1.30, 1.50, 1.75, 2.00, 2.50)
VOR_C = (250, 500, 1000, 1500, 2000, 3000)
# Decomposition grid (diagnostic): geometric package weight q x replacement level c.
DECOMP_Q = (0.50, 0.60, 0.65, 0.70, 0.75, 0.78, 0.80, 0.85, 0.90, 1.00)
DECOMP_C = (0, 250, 500, 750, 1000, 1250, 1500, 1750, 2000, 2500, 3000, 4000)
ELITE_LEVEL = 6000  # top-asset level (mean of both sides' best asset) for S2


def geom_u(q: float):
    """``sum q^i v_(i)``, values descending — GEOM_78 is the incumbent's form."""
    return lambda d: sum(v * q**i for i, v in enumerate(d))


def lp_u(p: float):
    """``(sum v^p)^(1/p)`` — the power norm (Minkowski: an added x adds <= x)."""
    return lambda d: sum(v**p for v in d) ** (1.0 / p) if d else 0.0


def gp_u(q: float, g: float):
    """``(sum q^i v_(i)^g)^(1/g)``: geometric rank weights on power-transformed
    values.  g = 1 -> GEOM_q; q = 1 -> LP_g.  Monotone, positively homogeneous,
    permutation invariant, 1-for-1 identity, and an added piece adds at most its
    own value (weights <= 1 and non-increasing, Minkowski for g >= 1)."""
    return lambda d: sum(q**i * v**g for i, v in enumerate(d)) ** (1.0 / g) if d else 0.0


def vor_u(c: float, q: float = 1.0):
    """DIAGNOSTIC ONLY: value over a fixed replacement level ``c``.  Not
    homogeneous (scaling every value does not scale the gap), so it is never a
    production candidate; it asks whether the market discount follows absolute
    value levels rather than package shape."""
    return lambda d: sum(q**i * max(0.0, v - c) for i, v in enumerate(d))


def _name(prefix: str, *parts: float) -> str:
    return prefix + "_" + "_".join(f"{round(x * 100):03d}" for x in parts)


FAMILY: dict[str, dict] = {}
for _q in Q_GRID:
    FAMILY[_name("GEOM", _q)] = {"u": geom_u(_q), "family": "geom", "params": {"q": _q}}
for _p in P_GRID:
    FAMILY[_name("LP", _p)] = {"u": lp_u(_p), "family": "lp", "params": {"p": _p}}
for _q in GP_Q:
    for _g in GP_G:
        FAMILY[_name("GP", _q, _g)] = {"u": gp_u(_q, _g), "family": "gp", "params": {"q": _q, "g": _g}}  # fmt: skip
DIAGNOSTIC: dict[str, dict] = {}
for _c in VOR_C:
    DIAGNOSTIC[f"VOR_{_c}"] = {"u": vor_u(_c), "family": "vor", "params": {"c": _c}}
DECOMP: dict[str, dict] = {}
for _q in DECOMP_Q:
    for _c in DECOMP_C:
        DECOMP[f"VG_{round(_q * 100):03d}_{_c}"] = {
            "u": vor_u(_c, _q),
            "family": "vor_geom",
            "params": {"q": _q, "c": _c},
        }
NAMED = list(P2.MODELS)  # the 13 Phase 2 models, incumbent via production dispatch


def residual_from_u(u, dA: list[float], dB: list[float]) -> float:
    """``P2.signed_residual`` for a utility on pre-sorted descending lists."""
    g = u(dA) - u(dB)
    ra, rb = sum(dA), sum(dB)
    a = ra + max(0.0, g - (ra - rb))
    b = rb + max(0.0, (ra - rb) - g)
    return g / ((a + b) / 2.0)


# ── trade rows → oriented analysis records ───────────────────────────────


def asset_meta(trade: dict, _board) -> dict:
    """Per-side asset metadata aligned with the side values (``row_extras``)."""
    meta = []
    for side in trade.get("sides") or []:
        s = []
        for a in side:
            pick = a.get("pick") or {}
            s.append([a.get("kind"), a.get("position"), pick.get("year")])
        meta.append(s)
    return {"meta": meta}


def split_bucket(league: str | None) -> str:
    if not league:
        return "noLeague"
    h = hashlib.sha256(f"{SPLIT_SALT}|{league}".encode()).digest()[0]
    return "discovery" if h % 2 == 0 else "confirmation"


def _cap(n: int, hi: int) -> str:
    return f"{n}" if n < hi else f"{hi}+"


def _tier(v: float, edges: tuple, labels: tuple) -> str:
    for e, lab in zip(edges, labels):
        if v < e:
            return lab
    return labels[-1]


_IDP = {"DL", "LB", "DB"}


def build_records(rows: list[dict]) -> list[dict]:
    recs = []
    for r in rows:
        mA, mB = r["meta"][0], r["meta"][1]
        A, B = list(zip(r["A"], mA)), list(zip(r["B"], mB))
        if len(A) > len(B):
            A, B = B, A
        A.sort(key=lambda x: -x[0])
        B.sort(key=lambda x: -x[0])
        dA, dB = [v for v, _ in A], [v for v, _ in B]
        kinds = [m[0] for _, m in A + B]
        poss = {m[1] for _, m in A + B if m[0] == "player"}
        n_pick = sum(1 for k in kinds if k == "pick")
        idp_pos = poss & _IDP
        off_pos = poss - _IDP
        pick_share_b = sum(v for v, m in B if m[0] == "pick") / max(sum(dB), 1e-9)
        if n_pick == 0:
            comp = "player_only"
        elif n_pick == len(kinds):
            comp = "pick_only"
        else:
            comp = "mixed"
        deep_comp = None
        if len(dB) >= 5:
            if all(m[0] == "player" for _, m in B):
                deep_comp = "deep_all_players"
            elif pick_share_b >= 0.5:
                deep_comp = "deep_pick_dominated"
            else:
                deep_comp = "deep_mixed_player_dominated"
        idp = (
            "offense_only"
            if not idp_pos
            else ("idp_only" if not off_pos and n_pick == 0 else "mixed_offense_idp")
        )
        d = date.fromisoformat(r["date"])
        recs.append(
            {
                "dA": dA,
                "dB": dB,
                "date": r["date"],
                "week": (d.toordinal() - d.weekday()),
                "league": r.get("league"),
                "bucket": "prospective"
                if r["date"] > FREEZE_DATE
                else split_bucket(r.get("league")),
                "bin": P2.structure_bin(dA, dB),
                "shape": f"{_cap(len(dA), 3)}v{_cap(len(dB), 5)}",
                "composition": comp,
                "deepComposition": deep_comp,
                "multiPick": "2+_picks" if n_pick >= 2 else "0-1_picks",
                "pickShareB": _tier(
                    pick_share_b,
                    (1e-9, 0.25, 0.5, 0.75),
                    ("0", "<=25%", "25-50%", "50-75%", ">75%"),
                ),  # fmt: skip
                "aKind": "A_pick" if all(m[0] == "pick" for _, m in A) else "A_player",
                "idp": idp,
                "idpPositions": sorted(idp_pos),
                "source": r.get("source") or "unknown",
                "vft": str(r.get("vft")),
                "tep": str(r.get("tep")),
                "idpFormat": str(r.get("idp")),
                "starTier": _tier(
                    max(dA),
                    (2000, 4000, 6000, 8000),
                    ("<2000", "2000-3999", "4000-5999", "6000-7999", "8000+"),
                ),  # fmt: skip
                # Noise-balanced level: the mean of BOTH sides' best asset.  Binning
                # on one side's value alone selects on that side's measurement
                # error (regression to the mean) and manufactures a gradient.
                "topLevel": (max(dA) + max(dB)) / 2.0,
                "levelTier": _tier(
                    (max(dA) + max(dB)) / 2.0,
                    (2000, 4000, 6000, 8000),
                    ("<2000", "2000-3999", "4000-5999", "6000-7999", "8000+"),
                ),  # fmt: skip
                "regime": (
                    "pre_2026-09-14"
                    if r["date"] < "2026-09-14"
                    else "gap_09-14_to_09-27"
                    if r["date"] < "2026-09-28"
                    else "from_2026-09-28"
                ),  # fmt: skip
                "month": r["date"][:7],
                "sourceRegime": f"{r.get('source') or 'unknown'}|{'pre_2026-09-28' if r['date'] < '2026-09-28' else 'from_2026-09-28'}",
                "lag": _tier(r.get("boardLagDays") or 0, (2, 4, 8), ("1d", "2-3d", "4-7d")),
                "leagueSize": (
                    "unknown"
                    if not isinstance(r.get("teams"), int)
                    else _tier(r["teams"], (11, 13, 15), ("<=10", "11-12", "13-14", "15+"))
                ),
            }
        )
    return recs


# ── residual matrix + clustered bootstrap ─────────────────────────────────


def residual_matrix(recs: list[dict], models: list[str]) -> dict[str, np.ndarray]:
    out = {}
    for m in models:
        spec = FAMILY.get(m) or DIAGNOSTIC.get(m) or DECOMP.get(m)
        if spec is not None:
            u = spec["u"]
            out[m] = np.array([residual_from_u(u, r["dA"], r["dB"]) for r in recs])
        else:
            gf = P2.MODELS[m]["gap"]
            out[m] = np.array([P2.signed_residual(gf, r["dA"], r["dB"]) for r in recs])
    return out


class Boot:
    """League-clustered bootstrap: leagues are resampled with replacement (one
    shared weight matrix, so paired statistics use the same resamples)."""

    def __init__(self, recs: list[dict], reps: int = BOOT_REPS, seed: int = BOOT_SEED):
        codes: dict = {}
        self.lg = np.array(
            [codes.setdefault(r["league"] or f"_anon{i}", len(codes)) for i, r in enumerate(recs)]
        )
        self.nl = len(codes)
        rng = np.random.default_rng(seed)
        self.W = rng.multinomial(self.nl, np.full(self.nl, 1.0 / self.nl), size=reps).astype(
            np.float32
        )

    def means(self, x: np.ndarray, mask: np.ndarray) -> np.ndarray:
        s = np.bincount(self.lg[mask], weights=x[mask], minlength=self.nl)
        n = np.bincount(self.lg[mask], minlength=self.nl).astype(np.float64)
        with np.errstate(invalid="ignore", divide="ignore"):
            return (self.W @ s) / (self.W @ n)


def _ci(samples: np.ndarray) -> list | None:
    s = samples[np.isfinite(samples)]
    if len(s) < 20:
        return None
    return [round(float(np.percentile(s, 2.5)), 4), round(float(np.percentile(s, 97.5)), 4)]


def bin_masks(recs: list[dict], sel: np.ndarray) -> dict[str, np.ndarray]:
    b = np.array([r["bin"] for r in recs])
    return {k: sel & (b == k) for k in BINS}


def bin_summary(res: np.ndarray, masks: dict, boot: Boot | None) -> dict:
    out = {}
    for k, m in masks.items():
        n = int(m.sum())
        if n == 0:
            out[k] = {"n": 0}
            continue
        x = res[m]
        cell = {
            "n": n,
            "meanSigned": round(float(x.mean()), 4),
            "medianSigned": round(float(np.median(x)), 4),
            "meanAbs": round(float(np.abs(x).mean()), 4),
        }
        if boot is not None and k != "equal" and n >= 30:
            cell["ci95Clustered"] = _ci(boot.means(res, m))
        out[k] = cell
    return out


def J(res: np.ndarray, masks: dict) -> float:
    """The preregistered calibration loss: the WORST unequal-bin |mean signed|."""
    vals = [abs(float(res[masks[b]].mean())) for b in UNEQUAL_BINS if masks[b].any()]
    return max(vals) if vals else float("nan")


def J_boot(res: np.ndarray, masks: dict, boot: Boot) -> np.ndarray:
    cols = [np.abs(boot.means(res, masks[b])) for b in UNEQUAL_BINS if masks[b].any()]
    return np.nanmax(np.vstack(cols), axis=0)


def select_candidate(res: dict, masks: dict) -> tuple[str, list[dict]]:
    """PREREGISTRATION §4: argmin J over the eligible family on DISCOVERY; ties
    (|dJ| < 1e-4) go to the simpler model (GEOM < LP < GP), then grid order."""
    order = {"geom": 0, "lp": 1, "gp": 2}
    ranked = sorted(
        ((J(res[m], masks), order[FAMILY[m]["family"]], i, m) for i, m in enumerate(FAMILY)),
        key=lambda t: (round(t[0], 4), t[1], t[2]),
    )
    table = [
        {
            "model": m,
            "J": round(j, 4),
            **FAMILY[m]["params"],
            "twoPieceFactor": round(FAMILY[m]["u"]([1.0, 1.0]), 3),
        }
        for j, _, _, m in ranked
    ]
    return ranked[0][3], table


# ── confirmation (PREREGISTRATION §5) ─────────────────────────────────────


def confirm(sel_name: str, res: dict, recs: list[dict], sel: np.ndarray, boot: Boot) -> dict:
    masks = bin_masks(recs, sel)
    S, G = res[sel_name], res[INCUMBENT]
    jS, jG = J(S, masks), J(G, masks)
    dj = J_boot(G, masks, boot) - J_boot(S, masks, boot)
    c1 = {"J_selected": round(jS, 4), "J_incumbent": round(jG, 4),
          "dJ": round(jG - jS, 4), "dJ_ci95Clustered": _ci(dj)}  # fmt: skip
    c1["pass"] = bool(c1["dJ_ci95Clustered"] and c1["dJ_ci95Clustered"][0] > 0)
    worse = {
        b: round(abs(float(S[masks[b]].mean())) - abs(float(G[masks[b]].mean())), 4)
        for b in UNEQUAL_BINS
        if masks[b].any()
    }
    c2 = {"absMeanWorseBy": worse, "tolerance": NO_BIN_WORSE_TOLERANCE,
          "pass": all(v <= NO_BIN_WORSE_TOLERANCE for v in worse.values())}  # fmt: skip
    allm = sel.copy()
    d_abs = np.abs(S) - np.abs(G)
    c3 = {"meanAbsSelectedMinusIncumbent_allTrades": round(float(d_abs[allm].mean()), 4),
          "ci95Clustered": _ci(boot.means(d_abs, allm))}  # fmt: skip
    c3["pass"] = bool(c3["ci95Clustered"] and c3["ci95Clustered"][1] < 0)
    src = np.array([r["source"] for r in recs])
    c4 = {}
    for s in ("ktc_trade_database", "sleeper_sharp_discovery"):
        mk = bin_masks(recs, sel & (src == s))
        c4[s] = {"J_selected": round(J(S, mk), 4), "J_incumbent": round(J(G, mk), 4)}
        c4[s]["pass"] = c4[s]["J_selected"] < c4[s]["J_incumbent"]
    comp = np.array([r["composition"] for r in recs])
    c5 = {}
    for label, cm in (
        ("player_only", comp == "player_only"),
        ("with_picks", comp != "player_only"),
    ):
        mk = bin_masks(recs, sel & cm)
        c5[label] = {"J_selected": round(J(S, mk), 4), "J_incumbent": round(J(G, mk), 4)}
        c5[label]["pass"] = c5[label]["J_selected"] < c5[label]["J_incumbent"]
    verdict = (
        all(x["pass"] for x in (c1, c2, c3))
        and all(v["pass"] for v in c4.values())
        and all(v["pass"] for v in c5.values())
    )
    return {
        "selected": sel_name,
        "n": int(sel.sum()),
        "C1_calibration_gain_clustered": c1,
        "C2_no_bin_materially_worse": c2,
        "C3_dispersion_not_worse": c3,
        "C4_both_source_families": c4,
        "C5_players_and_picks": c5,
        "verdict": ("CALIBRATION_ADVANTAGE_REPLICATED" if verdict else "NOT_REPLICATED"),
        "bins": {m: bin_summary(res[m], masks, boot) for m in dict.fromkeys([sel_name, INCUMBENT])},
    }


# ── strata, week balance, implied piece weights ───────────────────────────

STRATA = (
    "shape", "composition", "deepComposition", "multiPick", "pickShareB", "aKind", "idp",
    "source", "vft", "tep", "idpFormat", "starTier", "levelTier", "regime", "month", "sourceRegime", "lag",
    "leagueSize",
)  # fmt: skip


def strata_tables(recs, res, models, sel, boot) -> dict:
    out = {}
    for key in STRATA:
        vals = np.array([str(r[key]) for r in recs])
        tab = {}
        for v in sorted(set(vals[sel])):
            if v == "None":
                continue
            m = sel & (vals == v)
            masks = bin_masks(recs, m)
            tab[v] = {"n": int(m.sum()),
                      "models": {k: bin_summary(res[k], masks, boot) for k in models}}  # fmt: skip
        out[key] = tab
    pos = {}
    for p in sorted(_IDP):
        m = sel & np.array([p in r["idpPositions"] for r in recs])
        if m.any():
            masks = bin_masks(recs, m)
            pos[p] = {"n": int(m.sum()),
                      "models": {k: bin_summary(res[k], masks, None) for k in models}}  # fmt: skip
    out["idpPositionInvolved"] = pos
    return out


def week_balanced(recs, res, models, sel) -> dict:
    """Every week carries equal total weight within each bin, so the October
    surge cannot dominate the mean."""
    wk = np.array([r["week"] for r in recs])
    out = {}
    for m in models:
        cell = {}
        for b, mask in bin_masks(recs, sel).items():
            ws = [res[m][mask & (wk == w)].mean() for w in np.unique(wk[mask])]
            cell[b] = {"weeks": len(ws), "meanSigned": round(float(np.mean(ws)), 4) if ws else None}
        out[m] = cell
    return out


def implied_weights(recs, res, models, sel) -> dict:
    """1-for-2: the market's implied weight on the second piece,
    ``w2 = (a - b1) / b2`` (GEOM_78 implies 0.78 always); 1-for-3:
    ``w23 = (a - b1) / (b2 + b3)``.  Cells use only the DEPTH side's own shape
    (extra pieces relative to its best piece) and the extra pieces' ABSOLUTE
    size — never the single asset's value, which would select on its
    measurement error.  A pattern by relative size points to package shape; one
    by absolute size to the value curve / replacement level."""
    out = {}
    for nB in (2, 3):
        cells: dict = {}
        for i, r in enumerate(recs):
            if not sel[i] or len(r["dA"]) != 1 or len(r["dB"]) != nB:
                continue
            b = r["dB"]
            extra = sum(b[1:])
            if extra <= 0:
                continue
            rel = _tier(extra / b[0], (0.25, 0.5, 0.75, 1.0, 1.5), ("<0.25", "0.25-0.5", "0.5-0.75", "0.75-1.0", "1.0-1.5", "1.5+"))  # fmt: skip
            ab = _tier(extra, (1000, 2000, 3500, 5000), ("<1000", "1000-1999", "2000-3499", "3500-4999", "5000+"))  # fmt: skip
            cells.setdefault(("rel", rel), []).append(i)
            cells.setdefault(("abs", ab), []).append(i)
        tab = {}
        for (kind, lab), idx in sorted(cells.items()):
            w = np.array(
                [(recs[i]["dA"][0] - recs[i]["dB"][0]) / sum(recs[i]["dB"][1:]) for i in idx]
            )
            ok = len(idx) >= 10
            tab[f"{kind}:{lab}"] = {
                "n": len(idx),
                "impliedWeightMedian": round(float(np.median(w)), 3) if ok else None,
                "impliedWeightIQR": [
                    round(float(np.percentile(w, 25)), 3),
                    round(float(np.percentile(w, 75)), 3),
                ]
                if ok
                else None,  # fmt: skip
                "meanSigned": {m: round(float(res[m][idx].mean()), 4) for m in models},
            }
        out[f"1v{nB}"] = tab
    return out


# ── KTC-market basis: is the best family member the same on KTC's scale? ──


def ktc_basis(krows: list[dict]) -> dict:
    recs = []
    for r in krows:
        A, B = sorted(r["A"], reverse=True), sorted(r["B"], reverse=True)
        if len(A) > len(B):
            A, B = B, A
        recs.append({"dA": A, "dB": B, "bin": P2.structure_bin(A, B), "league": r.get("league")})
    if not recs:
        return {"n": 0}
    models = list(FAMILY) + list(DIAGNOSTIC) + list(DECOMP) + [INCUMBENT, "RAW", "KTC"]
    res = residual_matrix(recs, models)
    masks = bin_masks(recs, np.ones(len(recs), bool))
    sel_name, table = select_candidate(res, masks)
    return {
        "n": len(recs),
        "binCounts": {k: int(v.sum()) for k, v in masks.items()},
        "bestEligibleOnKtcScale": sel_name,
        "familyRankingTop10": table[:10],
        "diagnosticsJ": {m: round(J(res[m], masks), 4) for m in DIAGNOSTIC},
        "incumbentJ": round(J(res[INCUMBENT], masks), 4),
        "decomposition": decomposition(res, masks),
    }


# ── driver ────────────────────────────────────────────────────────────────


def decomposition(res: dict, masks: dict) -> dict:
    """DIAGNOSTIC: package weight q x replacement level c, jointly.  ``VG_q_c`` is
    ``sum q^i max(0, v_i - c)``: q is a package (shape) effect, c an absolute
    value-level effect.  The best (q, c) says how much of the market residual is
    each.  Never a production candidate (c > 0 breaks homogeneity)."""
    grid = {m: J(res[m], masks) for m in DECOMP}
    best = min(grid, key=lambda m: (round(grid[m], 4), m))
    by_q = {}
    for q in DECOMP_Q:
        cand = {m: j for m, j in grid.items() if DECOMP[m]["params"]["q"] == q}
        bm = min(cand, key=lambda m: (round(cand[m], 4), m))
        by_q[f"{q:.2f}"] = {"bestC": DECOMP[bm]["params"]["c"], "J": round(cand[bm], 4),
                            "J_c0": round(cand[f"VG_{round(q * 100):03d}_0"], 4)}  # fmt: skip
    return {"best": best, "bestParams": DECOMP[best]["params"], "J": round(grid[best], 4),
            "byQ": by_q, "grid": {m: round(j, 4) for m, j in sorted(grid.items())}}  # fmt: skip


def _decomp_by(recs, res, sel, key, min_unequal: int = 300) -> dict:
    vals = np.array([str(r[key]) for r in recs])
    out = {}
    for v in sorted(set(vals[sel])):
        masks = bin_masks(recs, sel & (vals == v))
        unequal = int(sum(masks[b].sum() for b in UNEQUAL_BINS))
        if unequal < min_unequal:
            out[v] = {"unequal": unequal, "reported": False}
            continue
        d = decomposition(res, masks)
        out[v] = {
            "unequal": unequal,
            "best": d["best"],
            "bestParams": d["bestParams"],
            "J": d["J"],
            "byQ": d["byQ"],
        }
    return out


def tier_consistency(names: list[str], res: dict, recs: list[dict], sel: np.ndarray) -> dict:
    """C6: residual by noise-balanced value level.  A package model is
    scale-free, so a residual that changes with value level is not something a
    package formula can (or should) fix."""
    lev = np.array([r["levelTier"] for r in recs])
    out = {}
    for t in sorted(set(lev[sel])):
        masks = bin_masks(recs, sel & (lev == t))
        out[t] = {
            "n": int((sel & (lev == t)).sum()),
            "binN": {b: int(masks[b].sum()) for b in UNEQUAL_BINS},
            "J": {m: round(J(res[m], masks), 4) for m in names},
            "meanSigned": {
                m: {
                    b: (round(float(res[m][masks[b]].mean()), 4) if masks[b].any() else None)
                    for b in UNEQUAL_BINS
                }
                for m in names
            },  # fmt: skip
        }
    return out


ELITE_TIERS = ("6000-7999", "8000+")
ELITE_OVERCREDIT = 0.05
ELITE_MIN_N = 50


def c6_flags(tc: dict, names: list[str]) -> dict:
    """C6 (PREREGISTRATION §5): a candidate is FLAGGED when, in an elite level
    tier, any unequal bin with >= ELITE_MIN_N trades has a signed mean above
    +ELITE_OVERCREDIT — i.e. it credits consolidation more than the market paid
    exactly where the superstar-vs-depth question lives."""
    flags = {}
    for m in names:
        hits = []
        for tier in ELITE_TIERS:
            cell = tc.get(tier)
            if not cell:
                continue
            for b in UNEQUAL_BINS:
                v = cell["meanSigned"][m][b]
                if v is not None and cell["binN"][b] >= ELITE_MIN_N and v > ELITE_OVERCREDIT:
                    hits.append(f"{tier}:{b}:{v:+.3f}")
        flags[m] = {"flagged": bool(hits), "hits": hits}
    return flags


def analyse(rows: list[dict], krows: list[dict]) -> dict:
    recs = build_records(rows)
    models = list(dict.fromkeys(NAMED + list(FAMILY) + list(DIAGNOSTIC) + list(DECOMP)))
    res = residual_matrix(recs, models)
    boot = Boot(recs)
    bucket = np.array([r["bucket"] for r in recs])
    dates = np.array([r["date"] for r in recs])
    level = np.array([r["topLevel"] for r in recs])
    upto = bucket != "prospective"
    disc = (bucket == "discovery") | (bucket == "noLeague")
    conf = bucket == "confirmation"
    prosp = bucket == "prospective"
    elite = level >= ELITE_LEVEL

    # 0. reproduction of the Phase 2 production report on the same date range
    ref = upto & (dates <= PHASE2_REFERENCE["lastTradeDate"])
    rmask = bin_masks(recs, ref)
    reproduction = {
        "n": int(ref.sum()),
        "referenceGraded": PHASE2_REFERENCE["graded"],
        "models": {
            m: {
                b: {
                    "now": round(float(res[m][rmask[b]].mean()), 4),
                    "reported": PHASE2_REFERENCE[m][b],
                }
                for b in UNEQUAL_BINS
            }  # fmt: skip
            for m in ("GEOM_78", "LP_150")
        },
    }

    # 1. discovery: preregistered selections (S1 pooled, S2 elite level)
    dmask = bin_masks(recs, disc)
    emask = bin_masks(recs, disc & elite)
    s1, table1 = select_candidate(res, dmask)
    s2, table2 = select_candidate(res, emask)
    best_by_family = {
        fam: next(t for t in table1 if FAMILY[t["model"]]["family"] == fam)
        for fam in ("geom", "lp", "gp")
    }
    discovery = {
        "n": int(disc.sum()),
        "binCounts": {k: int(v.sum()) for k, v in dmask.items()},
        "S1_pooled": {"selected": s1, "params": FAMILY[s1]["params"], "ranking": table1},
        "S2_eliteLevel": {
            "selected": s2,
            "params": FAMILY[s2]["params"],
            "minLevel": ELITE_LEVEL,
            "binCounts": {k: int(v.sum()) for k, v in emask.items()},
            "ranking": table2[:15],
        },  # fmt: skip
        "bestByFamily": best_by_family,
        "namedModelsJ": {m: round(J(res[m], dmask), 4) for m in NAMED},
        "diagnosticsJ": {m: round(J(res[m], dmask), 4) for m in DIAGNOSTIC},
        "decomposition_pooled": decomposition(res, dmask),
        "decomposition_eliteLevel": decomposition(res, emask),
    }

    # 2. confirmation (league-disjoint) — the frozen tests, for S1 and S2
    cands = list(dict.fromkeys([s1, s2]))
    confirmation = {s: confirm(s, res, recs, conf, boot) for s in cands}
    c6_names = list(dict.fromkeys([INCUMBENT, *cands, "LP_150"]))
    confirmation["C6_tierConsistency"] = tier_consistency(c6_names, res, recs, conf)
    confirmation["C6_eliteOvercreditFlags"] = c6_flags(confirmation["C6_tierConsistency"], c6_names)
    confirmation["decomposition"] = decomposition(res, bin_masks(recs, conf))
    confirmation["notIndependent_LP_150"] = {
        "note": "LP_150 was seen on the full sample before this protocol was frozen; shown, not tested",
        "bins": bin_summary(res["LP_150"], bin_masks(recs, conf), boot),
    }

    # 3. prospective (after the freeze date)
    pmask = bin_masks(recs, prosp)
    n_unequal = int(sum(pmask[b].sum() for b in UNEQUAL_BINS))
    prospective = {
        "n": int(prosp.sum()),
        "unequal": n_unequal,
        "minUnequal": PROSPECTIVE_MIN_UNEQUAL,
    }
    if n_unequal >= PROSPECTIVE_MIN_UNEQUAL:
        prospective["tests"] = {s: confirm(s, res, recs, prosp, boot) for s in cands}
        p6 = list(dict.fromkeys([INCUMBENT, *cands]))
        prospective["C6_tierConsistency"] = tier_consistency(p6, res, recs, prosp)
        prospective["C6_eliteOvercreditFlags"] = c6_flags(prospective["C6_tierConsistency"], p6)
        prospective["decomposition"] = decomposition(res, pmask)
        prospective["reported"] = True
    else:
        prospective["reported"] = False

    key = list(dict.fromkeys(
        ["RAW", INCUMBENT, "KTC", "BLEND_G50_K50", "EFD_78", "LP_150", s1, s2,
         best_by_family["geom"]["model"], best_by_family["lp"]["model"], best_by_family["gp"]["model"],
         discovery["decomposition_pooled"]["best"], "VOR_1000"]
    ))  # fmt: skip
    full = upto
    return {
        "population": {
            "records": len(recs),
            "byBucket": {
                k: int((bucket == k).sum())
                for k in ("discovery", "confirmation", "noLeague", "prospective")
            },  # fmt: skip
            "leagues": boot.nl,
        },
        "reproductionOfPhase2Report": reproduction,
        "discovery": discovery,
        "confirmationLeagueDisjoint": confirmation,
        "prospective": prospective,
        "fullPopulation": {
            "n": int(full.sum()),
            "bins": {m: bin_summary(res[m], bin_masks(recs, full), boot) for m in key},
            "namedAndFamilyJ": {
                m: round(J(res[m], bin_masks(recs, full)), 4)
                for m in NAMED + list(FAMILY) + list(DIAGNOSTIC)
            },  # fmt: skip
            "tierConsistency": tier_consistency(key, res, recs, full),
            "decomposition": decomposition(res, bin_masks(recs, full)),
            # If the replacement level c tracks league size (deeper leagues ->
            # lower replacement value), the residual is a replacement / roster
            # effect, not a property of the package formula.
            "decompositionByLeagueSize": _decomp_by(recs, res, full, "leagueSize"),
            "decompositionBySource": _decomp_by(recs, res, full, "source"),
            "decompositionByComposition": _decomp_by(recs, res, full, "composition"),
        },
        "keyModels": key,
        "strata": strata_tables(recs, res, key, full, boot),
        "weekBalanced": week_balanced(recs, res, key, full),
        "impliedPieceWeights": implied_weights(recs, res, key, full),
        "ktcMarketBasis": ktc_basis(krows),
    }


def box_main(max_lag_days: float) -> int:
    from src.trade import market_trade_report as report  # noqa: PLC0415

    conn = report.open_canonical_ledger()
    if conn is None:
        print(json.dumps({"available": False, "reason": "no_market_trade_ledger_on_this_host"}))
        return 2
    try:
        meta = report.read_ledger_meta(conn)
        groups = [g for g, _f in report.read_ledger_window(conn, since_date="2026-07-01")]
    finally:
        conn.close()
    priced = P2.price_market_groups(
        groups,
        max_lag_days=max_lag_days,
        value_keys=("canonical", "ktcMarket"),
        row_extras=asset_meta,
    )
    rows, audit = priced["canonical"]
    krows, _ = priced["ktcMarket"]
    n_groups = len(groups)
    del groups
    result = {
        "purpose": "RESEARCH ONLY (Phase 3). geom_q078_v1 stays active; nothing is promoted.",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "deployedCodeSha": P2._deployed_sha(REPO),
        "researchScript": "scripts/package_model_phase3_research.py --box",
        "preregistration": "docs/valuation/evidence/package_model_phase3_2026-10-20/PREREGISTRATION.md",
        "freezeDate": FREEZE_DATE,
        "ledgerBuiltAt": (meta or {}).get("builtAt") or (meta or {}).get("built_at"),
        "ledgerDatedGroupsSince20260701": n_groups,
        "audit": {k: v for k, v in audit.items() if k != "byDate"},
        "analysis": analyse(rows, krows),
    }
    denied = GUARD.denied() if GUARD else []
    net = [d for d in denied if d["event"].startswith("socket.")]
    fatal = [d for d in denied if not d["event"].startswith("socket.")]
    result["readOnlyGuard"] = {
        "installed": bool(GUARD and GUARD.installed()),
        "refusedWriteOrProcessAttempts": len(fatal),
        "refusedWriteOrProcessEvents": sorted({d["event"] for d in fatal}),
        "refusedNetworkAttempts": len(net),
        "refusedNetworkCallers": sorted({d["caller"] for d in net}),
    }
    result["peakRssMb"] = P2._peak_rss_mb()
    P2.assert_aggregate_only(result)
    print(json.dumps(result, indent=1, default=str))
    return 3 if fatal else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--box", action="store_true", help="read-only production-ledger run")
    ap.add_argument("--max-lag-days", type=float, default=7.0)
    args = ap.parse_args()
    if not args.box:
        ap.error("only --box is supported; local analyses live in the Phase 3 local script")
    return box_main(args.max_lag_days)


if __name__ == "__main__":
    raise SystemExit(main())
