"""DLF Trade Analyzer Values: normalization gate (read-only measurement).

Owner decision 2026-09-24: Hampel is a diagnostic, not the objective. Measures
ordering, native spacing, monotonicity, Hampel, board impact, family-cap
interaction with DLF Rank, new-vs-duplicate information, circularity and
explainability for each candidate. Never tunes to KTC; KTC is reported only as
one board among the native-value boards in the curve-shape context table.

Candidates:
  raw_max    value-direct raw / max x 9999 (DLF's own spacing, no borrowed curve)
  rank_hill  CONTROL: DLF Value ORDER -> percentile -> live OFFENSE Hill master
  quantile   declared target = the live OFFENSE Hill master (the pooled
             native-value target the refit builds from trainer boards, never
             our board). With that target it is identical to rank_hill by
             construction, so it is not run separately; any other target would
             import another market's spacing or read our own board (circular).

Run from the repo root with a captured CSVs/site_raw/dlfValuesSfTep.csv:
    python scripts/dlf_values_gate.py [--no-board] [--out report.json]
Record of the first result: docs/sources/DLF_VALUES_GATE_2026-09-25.md
Changes nothing in the repository: writes only --out and one temp CSV.
"""

from __future__ import annotations

import argparse
import copy
import csv
import importlib.util
import json
import math
import os
import tempfile
import sys
from pathlib import Path

REPO = Path(os.getcwd())
sys.path.insert(0, str(REPO))
KEY = "dlfValuesSfTep"
VALUES_CSV = Path(os.environ.get("DLFV_CSV") or REPO / "CSVs/site_raw/dlfValuesSfTep.csv")
RANK_CSV = REPO / "CSVs/site_raw/dlfSf.csv"
P_GRID = (0.0, 0.01, 0.02, 0.05, 0.10, 0.20, 0.30, 0.50, 0.70, 0.90)

from src.canonical import player_valuation as pv  # noqa: E402
from src.utils.name_clean import normalize_player_name as norm  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "fitter", REPO / "scripts" / "fit_hill_curve_percentile.py"
)
fitter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fitter)
from src.model_registry import holdout as ho  # noqa: E402

C_OFF, S_OFF = pv.HILL_PERCENTILE_C, pv.HILL_PERCENTILE_S


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else float("nan")


def hill(p, c=C_OFF, s=S_OFF):
    return fitter._hill(p, c, s)


def competition_ranks(values):
    """1-based ranks by value desc; ties share the min rank."""
    order = sorted(range(len(values)), key=lambda i: -values[i])
    ranks = [0] * len(values)
    prev, prev_rank = None, 0
    for pos, i in enumerate(order, 1):
        if values[i] != prev:
            prev, prev_rank = values[i], pos
        ranks[i] = prev_rank
    return ranks


def spearman(a, b):
    n = len(a)
    ra, rb = _avg_ranks(a), _avg_ranks(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = math.sqrt(sum((x - ma) ** 2 for x in ra))
    vb = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return cov / (va * vb)


def _avg_ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def discordant_share(a, b):
    n = len(a)
    disc = tot = 0
    for i in range(n):
        for j in range(i + 1, n):
            da, db = a[i] - a[j], b[i] - b[j]
            if da == 0 or db == 0:
                continue
            tot += 1
            disc += (da > 0) != (db > 0)
    return disc / tot if tot else float("nan")


def load_values():
    rows = []
    with VALUES_CSV.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                v = float(r["value"])
            except (TypeError, ValueError, KeyError):
                continue
            rows.append({"name": r["name"], "pos": r.get("pos") or "", "value": v})
    return rows


def load_rank():
    out = {}
    with RANK_CSV.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                out[norm(r["name"])] = float(r["rank"])
            except (TypeError, ValueError, KeyError):
                continue
    return out


def standalone(report):
    rows = load_values()
    vals = [r["value"] for r in rows]
    top = max(vals)
    inversions = sum(1 for a, b in zip(vals, vals[1:]) if b > a)
    ties = len(vals) - len(set(vals))
    report["capture"] = {
        "rows": len(rows),
        "top": top,
        "min": min(vals),
        "fileOrderInversions": inversions,
        "tiedValues": ties,
        "positions": {
            p: sum(1 for r in rows if r["pos"] == p) for p in sorted({r["pos"] for r in rows})
        },
    }

    # --- ordering vs DLF Rank (the family sibling) ---
    rank = load_rank()
    vranks = competition_ranks(vals)
    matched = [
        (vranks[i], rank[norm(r["name"])], r) for i, r in enumerate(rows) if norm(r["name"]) in rank
    ]
    va = [m[0] for m in matched]
    rb = [m[1] for m in matched]
    disp = [abs(a - b) for a, b in zip(va, rb)]
    ordering = {
        "matchedToDlfRank": len(matched),
        "valuesOnly": len(rows) - len(matched),
        "rankOnly": len(rank) - len(matched),
        "spearman": round(spearman(va, rb), 4),
        "discordantPairShare": round(discordant_share(va, rb), 4),
        "rankDisplacement": {"median": q(disp, 0.5), "p90": q(disp, 0.9), "max": max(disp)},
    }
    for n in (24, 50, 100, 200):
        a = {m[2]["name"] for m in matched if m[0] <= n}
        b = {m[2]["name"] for m in matched if m[1] <= n}
        ordering[f"top{n}Overlap"] = round(len(a & b) / n, 3)
    report["ordering"] = ordering

    # --- CONTROL: rank->Hill of DLF Value order vs rank->Hill of DLF Rank ---
    # If these agree, rank->Hill of the Values board carries no information the
    # family's existing DLF Rank vote does not already carry.
    ctrl = []
    spacing = []
    for vr, rr, r in matched:
        h_val = hill(pv.rank_to_percentile(vr))
        h_rank = hill(pv.rank_to_percentile(rr))
        ctrl.append(abs(h_val - h_rank) / h_rank * 100)
        raw = r["value"] / top * 9999
        spacing.append((raw - h_rank) / h_rank * 100)
    report["control_rank_hill_vs_dlfRank"] = {
        "medianAbsPct": round(q(ctrl, 0.5), 2),
        "p90AbsPct": round(q(ctrl, 0.9), 2),
        "maxAbsPct": round(max(ctrl), 2),
    }
    report["raw_max_vs_dlfRank_hill_signedPct"] = {
        "p10": round(q(spacing, 0.1), 2),
        "median": round(q(spacing, 0.5), 2),
        "p90": round(q(spacing, 0.9), 2),
    }

    # --- curve shape: DLF's native spacing vs the aggregation space ---
    desc = sorted(vals, reverse=True)[: ho.FIT_TOP_N]
    pairs = fitter._percentile_pairs(desc)
    c, s, _ = fitter._fit(pairs)
    report["curve"] = {
        "dlfOwnHill": {"c": round(c, 4), "s": round(s, 3)},
        "liveOffenseMaster": {"c": C_OFF, "s": S_OFF},
        "rmseVsLiveMaster": round(ho._rmse(pairs, C_OFF, S_OFF), 1),
        "rmseVsOwnFit": round(ho._rmse(pairs, c, s), 1),
        # The pending Autopilot challenger, when one exists: robustness only.
        # Neither curve is a target for DLF; this shows whether the verdict
        # depends on which champion happens to be live.
        "pendingChallenger": _challenger_rmse(pairs),
        "atP": {
            str(p): {
                "dlf": _r(_interp(pairs, p)),  # None past the board's depth
                "master": round(hill(p)),
            }
            for p in P_GRID
        },
    }
    # Context: every native-value OFFENSE board against the same master. KTC is
    # one row here, not the target.
    ctx = {}
    boards = {**fitter.OFFENSE_SOURCES, **ho.OFFENSE_HOLDOUT_SOURCES}
    for extra in ("ktcCrowdSfTep", "ktcTradesSfTep"):
        path = REPO / f"CSVs/site_raw/{extra}.csv"
        if path.exists():
            boards[extra] = (f"CSVs/site_raw/{extra}.csv", "value")
    for name, (rel, col) in boards.items():
        try:
            bv = fitter._load_values(REPO / rel, col)[: ho.FIT_TOP_N]
        except OSError:
            continue
        if len(bv) >= 50:
            ctx[name] = round(ho._rmse(fitter._percentile_pairs(bv), C_OFF, S_OFF), 1)
    report["curve"]["otherBoardsRmseVsLiveMaster"] = dict(sorted(ctx.items(), key=lambda kv: kv[1]))


def _challenger_rmse(pairs):
    path = REPO / "config/model_registry/hill_autopilot_runs.jsonl"
    try:
        last = json.loads(path.read_text(encoding="utf-8").strip().splitlines()[-1])
        params = last["composedParams"]
        c, s = params["HILL_PERCENTILE_C"], params["HILL_PERCENTILE_S"]
    except (OSError, KeyError, ValueError, IndexError):
        return None
    return {
        "c": c,
        "s": s,
        "evaluatedAt": last.get("evaluatedAt"),
        "rmse": round(ho._rmse(pairs, c, s), 1),
    }


def _r(x):
    return None if x != x else round(x)


def _interp(pairs, p):
    for (p0, v0), (p1, v1) in zip(pairs, pairs[1:]):
        if p0 <= p <= p1:
            return v0 if p1 == p0 else v0 + (v1 - v0) * (p - p0) / (p1 - p0)
    return pairs[0][1] if p <= pairs[0][0] else float("nan")  # beyond depth


# ── board simulations ────────────────────────────────────────────────────────


def build(variant):
    from src.api import data_contract as dc
    from tests.archive_fixtures import newest_complete_raw_payload

    saved = (dict(dc._SOURCE_CSV_PATHS), list(dc._RANKING_SOURCES), dc._VALUE_BASED_SOURCES)
    try:
        if variant != "baseline":
            base = next(s for s in dc._RANKING_SOURCES if s.get("key") == "dlfSf")
            entry = copy.deepcopy(base)
            entry["key"] = KEY
            entry["display_name"] = "DLF Trade Analyzer Values (gate sim)"
            if variant == "raw_max":
                dc._SOURCE_CSV_PATHS[KEY] = {"path": str(VALUES_CSV), "signal": "value"}
                dc._VALUE_BASED_SOURCES = frozenset(dc._VALUE_BASED_SOURCES | {KEY})
            else:  # rank_hill control: value ORDER as a rank board
                rows = load_values()
                ranks = competition_ranks([r["value"] for r in rows])
                tmp = Path(tempfile.gettempdir()) / "dlfValues_as_rank.csv"
                with tmp.open("w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(["name", "rank"])
                    for r, k in zip(rows, ranks):
                        w.writerow([r["name"], k])
                dc._SOURCE_CSV_PATHS[KEY] = {"path": str(tmp), "signal": "rank"}
            dc._RANKING_SOURCES.append(entry)
        raw, name = newest_complete_raw_payload()
        contract = dc.build_api_data_contract(raw)
    finally:
        dc._SOURCE_CSV_PATHS.clear()
        dc._SOURCE_CSV_PATHS.update(saved[0])
        dc._RANKING_SOURCES[:] = saved[1]
        dc._VALUE_BASED_SOURCES = saved[2]
    out = {}
    for r in contract["playersArray"]:
        meta = r.get("sourceRankMeta") or {}
        out[r["canonicalName"]] = {
            "value": r.get("rankDerivedValue"),
            "rank": r.get("canonicalConsensusRank"),
            "pos": r.get("position"),
            "dlfSf": meta.get("dlfSf"),
            "dlfV": meta.get(KEY),
        }
    return name, out


def board_effect(base, var):
    moved = []
    for k, a in base.items():
        b = var.get(k)
        if not b or not a["value"] or not b["value"]:
            continue
        pct = (b["value"] - a["value"]) / a["value"] * 100
        moved.append((abs(pct), pct, k, a, b))
    ch = [m for m in moved if m[3]["value"] != m[4]["value"]]
    absd = [m[0] for m in ch]
    top = lambda n: [m for m in moved if m[3]["rank"] and m[3]["rank"] <= n]  # noqa: E731
    votes = [m[4]["dlfV"] for m in moved if isinstance(m[4].get("dlfV"), dict)]
    dropped = sum(1 for v in votes if v.get("hampelDropped"))
    sib = [m[4]["dlfSf"] for m in moved if isinstance(m[4].get("dlfSf"), dict)]
    sib_dropped = sum(1 for v in sib if v.get("hampelDropped"))
    fam = [v.get("familyAdjustment") for v in votes if v.get("familyAdjustment") is not None]
    return {
        "rowsChanged": len(ch),
        "rowsCompared": len(moved),
        "absPct": {
            "median": round(q(absd, 0.5), 2),
            "p90": round(q(absd, 0.9), 2),
            "p95": round(q(absd, 0.95), 2),
            "max": round(max(absd), 2) if absd else 0,
        },
        "signedPctMedian": round(q([m[1] for m in ch], 0.5), 2) if ch else 0,
        "top50MaxAbsPct": round(max((m[0] for m in top(50)), default=0), 2),
        "top150MaxAbsPct": round(max((m[0] for m in top(150)), default=0), 2),
        "dlfValuesVotes": len(votes),
        "dlfValuesHampelDropRate": round(dropped / len(votes), 3) if votes else None,
        "dlfRankHampelDropRate": round(sib_dropped / len(sib), 3) if sib else None,
        "familyAdjustmentMedian": q(fam, 0.5) if fam else None,
        "topMovers": [
            {
                "name": m[2],
                "pos": m[3]["pos"],
                "from": m[3]["value"],
                "to": m[4]["value"],
                "pct": round(m[1], 2),
            }
            for m in sorted(ch, key=lambda m: -m[0])[:15]
        ],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-board", action="store_true")
    ap.add_argument("--out", default="dlf_values_gate.json")
    args = ap.parse_args()
    report = {"repoHead": os.popen("git rev-parse --short HEAD").read().strip()}
    standalone(report)
    if not args.no_board:
        name, base = build("baseline")
        report["payload"] = name
        for variant in ("raw_max", "rank_hill"):
            _n, var = build(variant)
            report[f"board_{variant}"] = board_effect(base, var)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
