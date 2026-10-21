#!/usr/bin/env python3
"""Low-value-asset research — confirmatory box run (owner directive 2026-10-20).

RESEARCH ONLY, read-only, owner-run on the production host exactly like Phase 3:
``--box`` installs ``research_readonly_guard.py`` before any application import,
the market ledger and the temporal ledger are opened ``mode=ro``, and the output
is aggregates only (``assert_aggregate_only``).  Exit codes: 0 ok, 2 no market
ledger, 3 the guard refused a write / process start.

Protocol: ``docs/valuation/evidence/low_value_assets_2026-10-20/PREREGISTRATION.md``
(§5, metrics M1–M4).  Treatments: ``scripts/low_value_asset_treatments.py``.
Production (``geom_q078_v1``, canonical values, fairness bands) is untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(os.environ.get("RISKIT_APP_DIR") or Path(__file__).resolve().parents[1]).resolve()
SCRIPT_DIR = Path(__file__).resolve().parent

sys.dont_write_bytecode = True
import numpy as np  # noqa: E402  (third-party, before the guard: ctypes dlopen)

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


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# The Phase 3 module installs its own guard when "--box" is on the command line;
# one guard per process is the invariant (a second hook would refuse the first
# guard's scratch dir and its refusals would not be counted here), so it is
# loaded with "--box" hidden.  This script's GUARD above is the only guard.
_argv = sys.argv
sys.argv = [a for a in _argv if a != "--box"]
try:
    P3 = _load("package_model_phase3_research")
finally:
    sys.argv = _argv
P2 = P3.P2
T = _load("low_value_asset_treatments")

# ── frozen protocol constants (PREREGISTRATION.md §2, §3, §5) ─────────────

FREEZE_DATE = "2026-10-20"
SPLIT_SALT = "lva-2026-10-20"
PROSPECTIVE_MIN_UNEQUAL = 2000
TREATMENTS = list(T.TREATMENTS)
UNEQUAL_BINS = P3.UNEQUAL_BINS
BINS = P3.BINS
# Replacement anchors and starter lines for dynasty_main, computed by the frozen
# rule (§2: waiver value by position; "*" = FAAB V_repl) on the newest board and
# recorded by the shadow-replay evidence (shadow_replay.json).  Filled at freeze.
ANCHORS: dict[str, float] = {
    "QB": 1923.0, "RB": 1626.0, "WR": 1802.0, "TE": 2061.0,
    "DL": 1918.0, "LB": 2149.0, "DB": 2156.0, "*": 1687.0,
}  # fmt: skip
# Lowest starter value at the position across the 12 optimal lineups; "*" (picks,
# K, unknown) = FAAB V_allin, the league-wide starter-pool line (Amendment 1).
STARTER_LINES: dict[str, float] = {
    "QB": 1988.0, "RB": 1653.0, "WR": 1510.0, "TE": 1671.0,
    "DL": 1539.0, "LB": 1474.0, "DB": 1335.0, "*": 2387.0,
}  # fmt: skip
_IDP = {"DL", "LB", "DB"}


def piece_class(value: float, kind: str | None, pos: str | None) -> str:
    """PREREGISTRATION §3 class for a piece outside our rosters (market trades)."""
    key = pos if (kind == "player" and pos in ANCHORS) else "*"
    line = STARTER_LINES.get(key, STARTER_LINES.get("*", float("inf")))
    anchor = ANCHORS.get(key, ANCHORS.get("*", 0.0))
    if value >= line:
        return "starter"
    return "usable" if value >= anchor else "filler"


def split_bucket(league: str | None, d: str) -> str:
    if d > FREEZE_DATE:
        return "prospective"
    if not league:
        return "noLeague"
    h = hashlib.sha256(f"{SPLIT_SALT}|{league}".encode()).digest()[0]
    return "discovery" if h % 2 == 0 else "confirmation"


def records(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        sides = []
        for vals, meta in zip((r["A"], r["B"]), r["meta"][:2]):
            pieces = sorted(
                (
                    {
                        "v": v,
                        "kind": m[0],
                        "pos": m[1],
                        "year": m[2],
                        "cid": m[3] if len(m) > 3 else None,
                    }
                    for v, m in zip(vals, meta)
                ),
                key=lambda p: -p["v"],
            )
            sides.append(pieces)
        A, B = sides
        if len(A) > len(B):
            A, B = B, A
        kinds = {p["kind"] for p in A + B}
        poss = {p["pos"] for p in A + B if p["kind"] == "player"}
        years = [p["year"] for p in A + B if p["kind"] == "pick" and p["year"]]
        if poss & _IDP:
            aclass = "idp_involved"
        elif kinds == {"player"}:
            aclass = "player_only_offense"
        elif kinds == {"pick"}:
            aclass = "pick_only"
        else:
            aclass = "mixed_offense_picks"
        rookie = any(y is not None and int(y) <= int(r["date"][:4]) + 1 for y in years)
        out.append(
            {
                "A": A,
                "B": B,
                "date": r["date"],
                "league": r.get("league"),
                "source": r.get("source"),
                "bucket": split_bucket(r.get("league"), r["date"]),
                "bin": P2.structure_bin([p["v"] for p in A], [p["v"] for p in B]),
                "assetClass": aclass,
                "rookiePick": "next_two_classes"
                if rookie
                else ("later_picks" if years else "no_picks"),
                "extraClasses": sorted(
                    {piece_class(p["v"], p["kind"], p["pos"]) for p in B[len(A) :]}
                ),
            }
        )
    return out


def _side(pieces: list[dict], name: str) -> list[tuple[float, float]]:
    rep = ANCHORS or {"*": T.MARKET_LEVEL}
    return [
        (p["v"], T.anchor_for(name, p["pos"] if p["kind"] == "player" else None, rep))
        for p in pieces
    ]


def residual(name: str, rec: dict) -> float:
    u = T.TREATMENTS[name]["u"]
    a, b = _side(rec["A"], name), _side(rec["B"], name)
    g = u(a) - u(b)
    ra, rb = sum(p["v"] for p in rec["A"]), sum(p["v"] for p in rec["B"])
    adj_a = ra + max(0.0, g - (ra - rb))
    adj_b = rb + max(0.0, (ra - rb) - g)
    return g / ((adj_a + adj_b) / 2.0)


# ── M1: market agreement ─────────────────────────────────────────────────


def m1(recs, res, boot) -> dict:
    out = {}
    bucket = np.array([r["bucket"] for r in recs])
    for pop in ("discovery", "confirmation", "prospective"):
        sel = bucket == pop
        n_unequal = int(sum(1 for i, r in enumerate(recs) if sel[i] and r["bin"] != "equal"))
        if pop == "prospective" and n_unequal < PROSPECTIVE_MIN_UNEQUAL:
            out[pop] = {"unequal": n_unequal, "reported": False}
            continue
        masks = P3.bin_masks(recs, sel)
        cell = {"n": int(sel.sum()),
                "J": {t: round(P3.J(res[t], masks), 4) for t in TREATMENTS},
                "bins": {t: P3.bin_summary(res[t], masks, boot) for t in TREATMENTS},
                "byAssetClass": {}, "byRookiePick": {}}  # fmt: skip
        for key, field in (("byAssetClass", "assetClass"), ("byRookiePick", "rookiePick")):
            vals = np.array([r[field] for r in recs])
            for v in sorted(set(vals[sel])):
                mk = P3.bin_masks(recs, sel & (vals == v))
                cell[key][v] = {
                    "n": int((sel & (vals == v)).sum()),
                    "binN": {b: int(mk[b].sum()) for b in UNEQUAL_BINS},
                    "J": {t: round(P3.J(res[t], mk), 4) for t in TREATMENTS},
                    "meanSigned": {
                        t: {
                            b: (round(float(res[t][mk[b]].mean()), 4) if mk[b].any() else None)
                            for b in UNEQUAL_BINS
                        }
                        for t in TREATMENTS
                    },  # fmt: skip
                }
        out[pop] = cell
    return out


# ── M2: implied credit of the extra piece, by class and position group ────


def m2(recs) -> dict:
    cells: dict = {}
    for r in recs:
        if len(r["A"]) != 1 or len(r["B"]) != 2 or r["bucket"] == "prospective":
            continue
        a, (b1, b2) = r["A"][0]["v"], r["B"]
        if b2["v"] <= 0:
            continue
        w = (a - b1["v"]) / b2["v"]
        grp = "pick" if b2["kind"] == "pick" else ("idp" if b2["pos"] in _IDP else "offense")
        cls = piece_class(b2["v"], b2["kind"], b2["pos"])
        band = P3._tier(b2["v"], (1000, 2500, 4000), ("<1000", "1000-2499", "2500-3999", "4000+"))
        for key in (
            f"class:{cls}",
            f"group:{grp}|class:{cls}",
            f"band:{band}|class:{cls}",
            f"band:{band}|group:{grp}",
        ):
            cells.setdefault(key, []).append(w)
    out = {}
    for k, ws in sorted(cells.items()):
        arr = np.array(ws)
        out[k] = {
            "n": len(ws),
            "median": round(float(np.median(arr)), 3) if len(ws) >= 20 else None,
            "iqr": [
                round(float(np.percentile(arr, 25)), 3),
                round(float(np.percentile(arr, 75)), 3),
            ]
            if len(ws) >= 20
            else None,  # fmt: skip
        }
    return out


# ── M3 / M4: served history from the temporal ledger (read-only) ───────────


def _ledger():
    from src.history import asof, store  # noqa: PLC0415

    if not Path(store.DB_PATH).exists():
        return None, None
    return asof, store


BANDS = ((500, "<500"), (1000, "500-999"), (1500, "1000-1499"), (2000, "1500-1999"), (3000, "2000-2999"),
         (4500, "3000-4499"), (6000, "4500-5999"), (float("inf"), "6000+"))  # fmt: skip


def _band(v: float) -> str:
    return next(lab for edge, lab in BANDS if v < edge)


def m3() -> dict:
    asof, store = _ledger()
    if asof is None:
        return {"available": False, "reason": "no_temporal_ledger_on_this_host"}
    import sqlite3  # noqa: PLC0415

    conn = sqlite3.connect(f"file:{store.DB_PATH}?mode=ro", uri=True)
    try:
        keys = conn.execute(
            "SELECT DISTINCT asset_key, asset_class FROM observations WHERE lane = ? AND source_key = ''",
            (store.LANE_CANONICAL,),
        ).fetchall()
    finally:
        conn.close()
    starts = [date(2026, 7, 15) + timedelta(days=7 * k) for k in range(10)]  # 07-15 .. 09-16
    acc: dict = {}
    for key, aclass in keys:
        s = asof.series(key, lane=store.LANE_CANONICAL)
        pts = {
            p["requestedDate"]: p
            for p in s.get("points") or []
            if isinstance(p.get("value"), (int, float))
        }
        if not pts:
            continue
        for d0 in starts:
            p0 = pts.get(d0.isoformat())
            if not p0 or not p0["value"] or p0["value"] <= 0:
                continue
            v0 = float(p0["value"])
            for h in (30, 60):
                p1 = pts.get((d0 + timedelta(days=h)).isoformat())
                cell = acc.setdefault(
                    (str(aclass), _band(v0), h), {"r": [], "missing": 0, "pipelineChanged": 0}
                )
                if not p1 or not p1["value"] or p1["value"] <= 0:
                    cell["missing"] += 1
                    continue
                cell["r"].append(float(p1["value"]) / v0)
                pv0 = (p0.get("provenance") or {}).get("pipelineVersion")
                pv1 = (p1.get("provenance") or {}).get("pipelineVersion")
                cell["pipelineChanged"] += int(pv0 != pv1)
    out = {}
    for (aclass, band, h), c in sorted(acc.items()):
        r = np.array(c["r"]) if c["r"] else np.array([])
        out[f"{aclass}|{band}|{h}d"] = {
            "n": int(len(r)),
            "missingAtHorizon": c["missing"],
            "medianRetention": round(float(np.median(r)), 4) if len(r) >= 20 else None,
            "meanLogRetention": round(float(np.log(np.clip(r, 1e-6, None)).mean()), 4)
            if len(r) >= 20
            else None,
            "pipelineVersionChanged": c["pipelineChanged"],
        }
    return {"available": True, "assets": len(keys), "cells": out}


def m4(recs_meta: list) -> dict:
    """Extras vs consolidated pieces: served 30-day retention after the trade."""
    asof, store = _ledger()
    if asof is None:
        return {"available": False, "reason": "no_temporal_ledger_on_this_host"}
    acc: dict = {"extra": [], "consolidated": [], "extraByClass": {}, "missing": 0, "eligible": 0}
    for key_a, key_b, cls, d in recs_meta:
        d0 = date.fromisoformat(d)
        if (d0 + timedelta(days=30)).isoformat() > date.today().isoformat():
            continue
        acc["eligible"] += 1
        for role, k in (("consolidated", key_a), ("extra", key_b)):
            r0 = asof.value_as_of(k, d0, lane=store.LANE_CANONICAL, max_age_days=7)
            r1 = asof.value_as_of(
                k, d0 + timedelta(days=30), lane=store.LANE_CANONICAL, max_age_days=7
            )
            if (
                r0["fidelity"] == "unavailable"
                or r1["fidelity"] == "unavailable"
                or not r0["value"]
            ):
                acc["missing"] += 1
                continue
            ratio = float(r1["value"]) / float(r0["value"])
            acc[role].append(ratio)
            if role == "extra":
                acc["extraByClass"].setdefault(cls, []).append(ratio)

    def summ(xs):
        return {
            "n": len(xs),
            "medianRetention": round(float(np.median(xs)), 4) if len(xs) >= 20 else None,
        }

    return {"available": True, "eligibleTrades": acc["eligible"], "missingLookups": acc["missing"],
            "consolidated": summ(acc["consolidated"]), "extra": summ(acc["extra"]),
            "extraByClass": {k: summ(v) for k, v in sorted(acc["extraByClass"].items())}}  # fmt: skip


# ── driver ────────────────────────────────────────────────────────────────


def asset_meta(trade: dict, _board) -> dict:
    meta = []
    for side in trade.get("sides") or []:
        meta.append(
            [
                [
                    a.get("kind"),
                    a.get("position"),
                    (a.get("pick") or {}).get("year"),
                    a.get("canonicalId"),
                ]
                for a in side
            ]
        )
    return {"meta": meta}


def analyse(rows: list[dict]) -> dict:
    recs = records(rows)
    res = {t: np.array([residual(t, r) for r in recs]) for t in TREATMENTS}
    boot = P3.Boot(recs)
    # 1-for-2 extras for M4: (consolidated key, extra key, extra class, date)
    m4_meta = [
        (
            r["A"][0]["cid"],
            r["B"][1]["cid"],
            piece_class(r["B"][1]["v"], r["B"][1]["kind"], r["B"][1]["pos"]),
            r["date"],
        )
        for r in recs
        if len(r["A"]) == 1 and len(r["B"]) == 2 and r["A"][0]["cid"] and r["B"][1]["cid"]
    ]
    return {
        "population": {
            "records": len(recs),
            "byBucket": {
                k: sum(1 for r in recs if r["bucket"] == k)
                for k in ("discovery", "confirmation", "noLeague", "prospective")
            },  # fmt: skip
            "byAssetClass": {
                k: sum(1 for r in recs if r["assetClass"] == k)
                for k in sorted({r["assetClass"] for r in recs})
            },  # fmt: skip
            "leagues": boot.nl,
        },
        "anchors": ANCHORS,
        "starterLines": STARTER_LINES,
        "M1_marketAgreement": m1(recs, res, boot),
        "M2_extraPieceCredit": m2(recs),
        "M3_servedValueDynamics": m3(),
        "M4_extraPieceRetention": m4(m4_meta),
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
        groups, max_lag_days=max_lag_days, value_keys=("canonical",), row_extras=asset_meta
    )
    rows, audit = priced["canonical"]
    n_groups = len(groups)
    del groups
    result = {
        "purpose": "RESEARCH ONLY (low-value-asset program). geom_q078_v1 stays active; nothing is promoted.",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "deployedCodeSha": P2._deployed_sha(REPO),
        "researchScript": "scripts/low_value_asset_box.py --box",
        "preregistration": "docs/valuation/evidence/low_value_assets_2026-10-20/PREREGISTRATION.md",
        "ledgerBuiltAt": (meta or {}).get("builtAt") or (meta or {}).get("built_at"),
        "ledgerDatedGroupsSince20260701": n_groups,
        "audit": {k: v for k, v in audit.items() if k != "byDate"},
        "analysis": analyse(rows),
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
    ap.add_argument("--box", action="store_true", help="read-only production run")
    ap.add_argument("--max-lag-days", type=float, default=7.0)
    args = ap.parse_args()
    if not args.box:
        ap.error("only --box is supported")
    return box_main(args.max_lag_days)


if __name__ == "__main__":
    raise SystemExit(main())
