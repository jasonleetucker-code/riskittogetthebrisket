#!/usr/bin/env python3
"""Evaluate the BDVM directional signal against challengers (EVALUATION ONLY).

Preregistration: docs/research/bdvm-v1/SIGNAL_SATURATION_DIAGNOSIS_2026-11-08.md.
Writes nothing the serving path reads.  Needs network for the nflverse
baseline unless ``--baseline-cache`` points at a previous pickle.

    python scripts/evaluate_bdvm_signal.py --out result.json \
        --baseline-cache baseline.pkl

Exit codes: 0 done, 2 error / insufficient input.
"""

from __future__ import annotations

import argparse
import dataclasses
import glob
import json
import pickle
import re
import sys
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.bdvm import signal_diagnostics as sd  # noqa: E402
from src.bdvm.market import market_view_for_row  # noqa: E402
from src.bdvm.params import load_param_set  # noqa: E402

PRIMARY_H = 14
SECONDARY_H = 28
STRONG, WEAK = 0.30, 0.15
MIN_ORIGINS = 6
_ST = re.compile(r"dynasty_export_(\d{8})_(\d{6})\.zip$")


def archives_by_day() -> dict[date, Path]:
    """Last archive of each day (the day's final scrape)."""
    out: dict[date, Path] = {}
    for f in sorted(glob.glob(str(REPO_ROOT / "exports" / "archive" / "dynasty_export_*.zip"))):
        m = _ST.search(f)
        if m:
            out[datetime.strptime(m.group(1), "%Y%m%d").date()] = Path(f)
    return out


def load_raw(path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")]
        return json.loads(zf.read(names[0]))


def snapshot_for_day(day: date, path: Path, records, params, cfg) -> dict | None:
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415
    from src.bdvm.service import run_valuation  # noqa: PLC0415

    contract = build_api_data_contract(load_raw(path))
    if not (contract.get("sleeper") or {}).get("scoringSettings"):
        return None
    market: dict[str, tuple[float, str]] = {}
    for row in contract.get("playersArray") or []:
        pid = row.get("playerId")
        if not pid or row.get("assetClass") == "pick":
            continue
        view = market_view_for_row(row, str(row.get("position") or ""), params)
        if view.market_value is not None and view.market_value > 0:
            market[str(pid)] = (float(view.market_value), str(view.market_source))
    payload = run_valuation(
        contract,
        league_key="dynasty_main",
        params=params,
        registry_roster_settings=cfg.roster_settings,
        idp_enabled=bool(cfg.idp_enabled),
        scoring_profile=str(cfg.scoring_profile or ""),
        # Point-in-time: stamp records AND snapshot with the origin's own
        # archive day.  Left at the build date, early origins see records
        # dated in their future and take the stale down-weight.
        projection_records=[dataclasses.replace(r, as_of=day.isoformat()) for r in records],
        snapshot_as_of=day.isoformat(),
        season=2026,
    )
    rows = []
    for e in payload.get("players") or []:
        m = e.get("market") or {}
        if m.get("marketValue") is None or m["marketValue"] <= 0:
            continue
        tv = (e.get("tradeValue") or {}).get("balanced")
        if tv is None:
            continue
        rows.append(
            {
                "id": str(e["playerId"]),
                "pos": e["position"],
                "group": e["group"],
                "fund": float(tv),
                "mkt": float(m["marketValue"]),
                "src": m.get("marketSource"),
                "liq": m.get("liquidity"),
                "liqMeasured": bool(m.get("liquidityMeasured")),
                "alpha": m.get("alpha"),
                "signal": (e.get("signal") or {}).get("signal"),
                "proxy": bool((e.get("projection") or {}).get("anyProxy")),
            }
        )
    return {"market": market, "rows": rows}


def evaluate_pairs(snaps: dict[date, dict], origin: date, horizon: int, th, params_liq_lo: float):
    target = origin + timedelta(days=horizon)
    if origin not in snaps or target not in snaps:
        return None
    rows = snaps[origin]["rows"]
    fwd = snaps[target]["market"]
    keep = [r for r in rows if r["id"] in fwd and fwd[r["id"]][1] == r["src"]]
    if len(keep) < 100:
        return None
    fund = [r["fund"] for r in keep]
    mkt = [r["mkt"] for r in keep]
    liq = [r["liq"] if r["liq"] is not None else params_liq_lo for r in keep]
    groups = [r["group"] for r in keep]
    fx = sd.excess_forward_change(mkt, [fwd[r["id"]][0] for r in keep])
    alpha = [(f - m) * q for f, m, q in zip(fund, mkt, liq)]
    inc_lab = [r["signal"] for r in keep]
    c1 = sd.percentile_gap_labels(fund, mkt, strong=STRONG, weak=WEAK)
    pf, pm = sd.percentiles(fund), sd.percentiles(mkt)
    c1_score = [a - b for a, b in zip(pf, pm)]
    c2 = sd.scale_aligned_labels(fund, mkt, liq, th)
    aligned = sd.quantile_match(fund, mkt)
    c2_score = [(f - m) * q for f, m, q in zip(aligned, mkt, liq)]
    c3 = sd.position_percentile_gap_labels(fund, mkt, groups, strong=STRONG, weak=WEAK)
    c3_score = [0.0] * len(keep)
    for g in set(groups):
        ix = [i for i, x in enumerate(groups) if x == g]
        a, b = sd.percentiles([fund[i] for i in ix]), sd.percentiles([mkt[i] for i in ix])
        for i, x, y in zip(ix, a, b):
            c3_score[i] = x - y
    n0_score = [-m for m in mkt]
    out = {"origin": origin.isoformat(), "horizon": horizon, "n": len(keep)}
    for name, lab, score in (
        ("C0", inc_lab, alpha),
        ("C1", c1, c1_score),
        ("C2", c2, c2_score),
        ("C3", c3, c3_score),
        ("N0", ["HOLD"] * len(keep), n0_score),
    ):
        out[name] = sd.evaluate_origin(lab, score, fx)
        out[name]["labels"] = sd.label_census(lab)
    return out


def summarize(per_origin: list[dict]) -> dict:
    res: dict = {"origins": len(per_origin)}
    for name in ("C0", "C1", "C2", "C3", "N0"):
        ics = [o[name]["ic"] for o in per_origin if o[name]["ic"] is not None]
        sell_pairs = [
            (round((o[name]["sell_hit"] or 0) * o[name]["n_sell"]), o[name]["n_sell"])
            for o in per_origin
        ]
        buy_pairs = [
            (round((o[name]["buy_hit"] or 0) * o[name]["n_buy"]), o[name]["n_buy"])
            for o in per_origin
        ]
        sells = sum(n for _, n in sell_pairs)
        buys = sum(n for _, n in buy_pairs)
        n = sum(o["n"] for o in per_origin)
        base_down = sum(o[name]["base_down"] * o["n"] for o in per_origin) / n if n else None
        base_up = sum(o[name]["base_up"] * o["n"] for o in per_origin) / n if n else None
        res[name] = {
            "mean_ic": (sum(ics) / len(ics)) if ics else None,
            "ic_sd_across_origins": (
                (sum((x - sum(ics) / len(ics)) ** 2 for x in ics) / (len(ics) - 1)) ** 0.5
                if len(ics) > 1
                else None
            ),
            "ic_min": min(ics) if ics else None,
            "ic_max": max(ics) if ics else None,
            "mean_ic_ci95_origin_bootstrap": sd.bootstrap_mean_ci(ics),
            "sign_flip_p_mean_ic_zero": sd.sign_flip_p(ics),
            "frac_origins_ic_positive": (sum(1 for x in ics if x > 0) / len(ics)) if ics else None,
            "n_sell": sells,
            "sell_hit": (sum(h for h, _ in sell_pairs) / sells) if sells else None,
            "sell_hit_ci95_origin_cluster": sd.cluster_rate_ci(sell_pairs),
            "n_buy": buys,
            "buy_hit": (sum(h for h, _ in buy_pairs) / buys) if buys else None,
            "buy_hit_ci95_origin_cluster": sd.cluster_rate_ci(buy_pairs),
            "base_down": base_down,
            "base_up": base_up,
        }
    return res


def verdicts(summary: dict) -> dict:
    if summary["origins"] < MIN_ORIGINS:
        return {"verdict": "INSUFFICIENT", "reason": f"{summary['origins']} usable origins"}
    inc, nul = summary["C0"], summary["N0"]
    out = {}

    def beats(mean_ic: float, ref: dict) -> bool:
        # None means "no reference value", which cannot be beaten by 0.02 of
        # nothing; a real 0.0 is a real value (never treated as missing).
        return ref["mean_ic"] is not None and mean_ic >= ref["mean_ic"] + 0.02

    for name in ("C1", "C2", "C3"):
        s = summary[name]
        p1 = (
            s["mean_ic"] is not None
            and s["mean_ic"] >= 0.05
            and beats(s["mean_ic"], inc)
            and beats(s["mean_ic"], nul)
        )
        sell_ok = s["sell_hit"] is not None and s["sell_hit"] - s["base_down"] >= 0.05
        buy_ok = s["buy_hit"] is not None and s["buy_hit"] - s["base_up"] >= 0.05
        p3 = s["frac_origins_ic_positive"] is not None and s["frac_origins_ic_positive"] >= 0.70
        out[name] = {"P1": p1, "P2": bool(sell_ok and buy_ok), "P3": p3}
        out[name]["PASS"] = all(out[name].values())
    return {"verdict": "SCREENED", "challengers": out}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--baseline-cache", type=Path, default=None)
    ap.add_argument("--panel-cache", type=Path, default=None)
    args = ap.parse_args()

    params = load_param_set()
    th = {
        k: float(v) for k, v in params["market"]["signal_thresholds"].items() if k.endswith("alpha")
    }
    lo = float(params["market"]["liquidity"]["clip_lo"])
    days = archives_by_day()
    if not days:
        print("no archives", file=sys.stderr)
        return 2
    first, last = min(days), max(days)

    if args.panel_cache and args.panel_cache.exists():
        snaps = pickle.loads(args.panel_cache.read_bytes())
    else:
        from src.api import league_registry as lr  # noqa: PLC0415
        from src.bdvm.baseline import fetch_and_build_baseline  # noqa: PLC0415

        if args.baseline_cache and args.baseline_cache.exists():
            records = pickle.loads(args.baseline_cache.read_bytes())
        else:
            from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

            scoring = build_api_data_contract(load_raw(days[last]))["sleeper"]["scoringSettings"]
            records, _ = fetch_and_build_baseline(
                season=2026, as_of=last.isoformat(), scoring_settings=scoring, seasons_back=3
            )
            if args.baseline_cache:
                args.baseline_cache.write_bytes(pickle.dumps(records))
        cfg = lr.get_league_by_key("dynasty_main")
        snaps = {}
        d = first
        while d <= last:
            near = [x for x in days if x >= d and (x - d).days <= 2]
            if near:
                day = min(near)
                try:
                    s = snapshot_for_day(day, days[day], records, params, cfg)
                except Exception as exc:  # noqa: BLE001
                    print(f"skip {day}: {exc!r}", file=sys.stderr)
                    s = None
                if s:
                    snaps[d] = s
                    print(f"{d} <- {day}: {len(s['rows'])} rows", file=sys.stderr)
            d += timedelta(days=7)
        if args.panel_cache:
            args.panel_cache.write_bytes(pickle.dumps(snaps))

    result: dict = {"dates": sorted(x.isoformat() for x in snaps)}
    # Level census at the newest origin (reproduction of the saturation).
    newest = max(snaps)
    rows = snaps[newest]["rows"]
    result["newestOrigin"] = newest.isoformat()
    result["newestSignalCensus"] = sd.label_census([r["signal"] for r in rows])
    result["newestProxyShare"] = sum(r["proxy"] for r in rows) / len(rows)
    for tag, horizon, step in (("primary", PRIMARY_H, 14), ("secondary", SECONDARY_H, 7)):
        per = []
        for i, d in enumerate(sorted(snaps)):
            if (d - first).days % step:
                continue
            r = evaluate_pairs(snaps, d, horizon, th, lo)
            if r:
                per.append(r)
        s = summarize(per) if per else {"origins": 0}
        result[tag] = {"horizon": horizon, "perOrigin": per, "summary": s, "verdict": verdicts(s)}
    args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({k: result[k]["verdict"] for k in ("primary", "secondary")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
