#!/usr/bin/env python3
"""Batch 3 Unit D2 — the preregistered clean Hill rerun.

Implements ``PREREGISTRATION.md`` in this directory (committed before this script
and before any result). Evidence only: it never writes ``config/model_registry/``,
``player_valuation.py`` or any served value, and never promotes.

Usage (from the repository root, Windows: ``PYTHONUTF8=1``)::

    python docs/valuation/evidence/hill-d2-2026-10-01/run_d2.py \
        --out docs/valuation/evidence/hill-d2-2026-10-01 --workers 16

Writes ``results.json`` (every verdict input) and ``runs.jsonl`` (one compact pin
summary per substrate-v2 fit, enough to replay and verify each one).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[4]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

HERE = Path(__file__).resolve().parent
PREREG = HERE / "PREREGISTRATION.md"
REF = "origin/main"

# ── frozen design (PREREGISTRATION §2–§7) ─────────────────────────────────────
FIRST_ORIGIN = date(2026, 5, 15)
TRADES_FIRST = date(2026, 9, 9)
DLF_VALUES_FIRST = date(2026, 9, 25)
S3_FIRST = date(2026, 7, 30)
HORIZONS = (7, 0, 28)
PRIMARY_H = 7
BLOCK_DAYS = 28
RESAMPLES = 4000
SEED = 20261002
DECISIVE_LEVEL = 1 - 0.05 / 4  # 98.75 %
MIN_ORIGINS = 84
MIN_SPAN_DAYS = 84
MARGIN_POINTS = 25.0
MARGIN_FRACTION = 0.05
BANDS = ((1, 50), (51, 100), (101, 200), (201, 400))
P1_TOLERANCE = 0.5
P1_SHARE = 0.99

CHAMPION = {"c": 0.1100, "s": 1.110, "registryVersion": 2}

TARGET_PATH = "CSVs/site_raw/otcffbSf.csv"
TARGET_COL = "value"
NATIVE = {
    "N1": ("CSVs/site_raw/ktcSfTep.csv", "value"),
    "N1_crowdCsv": ("CSVs/site_raw/ktcCrowdSfTep.csv", "value"),
    "N2": ("CSVs/site_raw/ktcTradesSfTep.csv", "value"),
    "DLFnative": ("CSVs/site_raw/dlfValuesSfTep.csv", "value"),
}

EXPECTED_MANIFESTS = {
    "M1": "14aabb24d4cf923663c0d18a0040cb78cd1ece305c190c326bad723e29433adf",
    "M2": "b561959ff76f55e11a25852c16a543711e0f8a42be1692e36fae8bfb7781a85a",
    "M3": "9601c948e5ac336e4d092ebf24c8490e8e058739f643bf42cba48884776963c0",
    "M4": "d6ff34d460dc97180dc6e5e9934b2e35799e0ab057a389b7ad74e61424e4d7e7",
    "M5": "ad601099464afde3357f2f8bf0dfd6a921936ab14b411f69d6de20a8c9cd3576",
    "M6": "e6e32c79699dd73d965388a809981d17a33879ba26aa2b5bcd23f1830851e0cb",
    "M7": "79d76a0d1088066630fc34673242e0dd870a4aac44038e4eb7940681ccffa192",
    "M8": "c7876d74d1346894bac1269b51c87a351b79e52ce340f4e6868603dd02dec745",
}
DECISIVE_ARMS = ("M1", "M2", "M3", "M4")
DESCRIPTIVE_ARMS = ("M5", "M6", "M7", "M8")


def arm_manifest(arm: str):
    """The frozen OFFENSE-only manifest of one M-arm (PREREGISTRATION §4)."""
    from src.model_registry import training_manifest as tm

    off = [s for s in tm._DEFAULT_SPECS if s.scope == "OFFENSE"]
    rank_trainers = [s for s in off if s.requested_role == tm.ROLE_TRAIN and s.source_key != "ktc"]
    holdouts = [s for s in off if s.requested_role == tm.ROLE_HOLDOUT]
    base = next(s for s in off if s.source_key == "ktc")
    crowd = tm.BoardSpec(
        "KTC-CrowdTEpp",
        "ktcSfTep",
        "OFFENSE",
        tm.ROLE_TRAIN,
        "value",
        game_type_evidence=tm._KTC_BASE_GAME_TYPE_EVIDENCE
        + "; lineage ktc-historical-calibration-states (config/sources/source_lineage.json): "
        "ktcSfTep carries the same TE++ crowd values as ktcCrowdSfTep",
    )
    trades = tm.BoardSpec("KTC-Trades", "ktcTradesSfTep", "OFFENSE", tm.ROLE_TRAIN, "value")
    ktc = {
        "M1": [base],
        "M2": [base],
        "M3": [crowd],
        "M4": [crowd],
        "M5": [trades],
        "M6": [trades],
        "M7": [crowd, trades],
        "M8": [crowd, trades],
    }[arm]
    natives_on = arm in ("M1", "M3", "M5", "M7")
    policy = tm.TrainingPolicy(allow_rank_voter_native_values=natives_on)
    return tm.build_manifest(specs=[*ktc, *rank_trainers, *holdouts], policy=policy)


# ── git helpers ──────────────────────────────────────────────────────────────


def git(*args: str, binary: bool = False):
    out = subprocess.run(["git", *args], cwd=str(REPO), capture_output=True, check=True)
    return out.stdout if binary else out.stdout.decode("utf-8").strip()


def cutoff_of(day: date) -> datetime:
    return datetime.combine(day, time(23, 59, 59), tzinfo=timezone.utc)


_COMMIT_CACHE: dict[date, str | None] = {}


def commit_at(day: date) -> str | None:
    if day not in _COMMIT_CACHE:
        sha = git("rev-list", "-1", f"--before={cutoff_of(day).isoformat()}", REF)
        _COMMIT_CACHE[day] = sha or None
    return _COMMIT_CACHE[day]


def last_commit_day(path: str) -> date:
    stamp = git("log", "-1", "--format=%cI", REF, "--", path)
    return datetime.fromisoformat(stamp).astimezone(timezone.utc).date()


def blob_sha(commit: str, path: str) -> str | None:
    try:
        return git("rev-parse", f"{commit}:{path}")
    except subprocess.CalledProcessError:
        return None


_BOARD_CACHE: dict[str, tuple[list[str], list[float]] | None] = {}


def board_at(commit: str, path: str, column: str) -> tuple[list[str], list[float]] | None:
    """Players-only positive values (descending) through the manifest's one loader."""
    from src.model_registry.training_manifest import load_board_values

    blob = blob_sha(commit, path)
    if blob is None:
        return None
    key = f"{blob}:{column}"
    if key not in _BOARD_CACHE:
        data = git("cat-file", "blob", blob, binary=True)
        with tempfile.TemporaryDirectory(prefix="d2-") as td:
            p = Path(td) / "board.csv"
            p.write_bytes(data)
            bv = load_board_values(p, column)
        _BOARD_CACHE[key] = (list(bv.names), list(bv.values))
    return _BOARD_CACHE[key]


def sha256_lf(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# ── fits (worker) ────────────────────────────────────────────────────────────


def _fit_job(job: tuple[str, str, str]) -> dict[str, Any]:
    arm, commit, cutoff_iso = job
    from src.model_registry import training_run as tr

    m = arm_manifest(arm)
    run = tr.replay(commit=commit, cutoff=datetime.fromisoformat(cutoff_iso), manifest=m)
    rec = run.record
    off = rec["masters"].get("OFFENSE") or {}
    return {
        "arm": arm,
        "trainingCutoff": rec["trainingCutoff"],
        "inputsCommit": rec["inputsCommit"],
        "manifestHash": rec["manifestHash"],
        "codeHash": rec["codeHash"],
        "codeSha": rec["codeSha"],
        "substrateVersion": rec["substrateVersion"],
        "pinsHash": rec["pinsHash"],
        "modelHash": rec["modelHash"],
        "challengerHash": rec["challengerHash"],
        "evidenceHash": rec["evidenceHash"],
        "inputsContentHash": rec["inputsContentHash"],
        "snapshot": (rec.get("snapshot") or {}).get("path"),
        "offense": {"c": off.get("c"), "s": off.get("s"), "rmse": off.get("rmse")},
        "trainers": [f["label"] for f in rec["perSourceFits"].get("OFFENSE", [])],
        "skipped": (rec["scopes"].get("OFFENSE") or {}).get("fitSkipped"),
        "nonPromotableReasons": (rec["scopes"].get("OFFENSE") or {}).get("nonPromotableReasons"),
        "promotable": (rec["scopes"].get("OFFENSE") or {}).get("promotable"),
    }


# ── metric ───────────────────────────────────────────────────────────────────


def target_pairs(values: list[float]) -> list[tuple[float, float]]:
    from src.model_registry import holdout

    return holdout._percentile_pairs(values)


def master_curve(c: float, s: float, pairs: list[tuple[float, float]]) -> list[float]:
    from src.model_registry import holdout

    return [holdout.hill(p, c, s) for p, _ in pairs]


def native_curve(values: list[float]) -> list[float]:
    top = values[0]
    return [v / top * 9999.0 for v in values]


def rmse_on(curve: list[float], pairs: list[tuple[float, float]], n: int, lo=1, hi=None) -> float:
    hi = n if hi is None else min(hi, n)
    idx = range(lo - 1, hi)
    errs = [(curve[i] - pairs[i][1]) ** 2 for i in idx]
    return math.sqrt(sum(errs) / len(errs)) if errs else float("nan")


def score(curve_a, curve_b, pairs) -> dict[str, Any]:
    """Paired RMSE of two spacing curves on one target, on the common index set."""
    n = min(len(pairs), len(curve_a), len(curve_b))
    out = {
        "n": n,
        "ref": rmse_on(curve_a, pairs, n),
        "arm": rmse_on(curve_b, pairs, n),
        "bands": {},
    }
    for lo, hi in BANDS:
        if lo > n:
            continue
        out["bands"][f"{lo}-{hi}"] = {
            "ref": rmse_on(curve_a, pairs, n, lo, hi),
            "arm": rmse_on(curve_b, pairs, n, lo, hi),
        }
    return out


# ── bootstrap / verdict ──────────────────────────────────────────────────────


def moving_block_ci(xs: list[float], levels=(DECISIVE_LEVEL, 0.95)) -> dict[str, Any]:
    n = len(xs)
    if n == 0:
        return {}
    rng = random.Random(SEED)
    k = math.ceil(n / BLOCK_DAYS)
    means = []
    for _ in range(RESAMPLES):
        draw: list[float] = []
        for _b in range(k):
            s = rng.randrange(n)
            draw.extend(xs[(s + j) % n] for j in range(BLOCK_DAYS))
        means.append(sum(draw[:n]) / n)
    means.sort()

    def q(p: float) -> float:
        i = min(len(means) - 1, max(0, int(round(p * (len(means) - 1)))))
        return means[i]

    out = {"mean": sum(xs) / n}
    for lv in levels:
        a = (1 - lv) / 2
        out[f"ci{round(lv * 100, 2)}"] = [q(a), q(1 - a)]
    return out


def verdict(primary: dict, secondary_means: dict[int, float | None], band_pos: int, margin: float):
    if primary["origins"] < MIN_ORIGINS or primary["spanDays"] < MIN_SPAN_DAYS:
        return "INSUFFICIENT"
    lo, hi = primary["ci"][f"ci{round(DECISIVE_LEVEL * 100, 2)}"]
    mean = primary["ci"]["mean"]
    if (
        lo > 0
        and mean >= margin
        and all((v is not None and v > 0) for v in secondary_means.values())
        and band_pos >= 3
    ):
        return "BETTER"
    if hi < 0:
        return "WORSE"
    if hi < margin:
        return "NOT BETTER"
    return "INCONCLUSIVE"


# ── main ─────────────────────────────────────────────────────────────────────


def daterange(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def p1_check() -> dict[str, Any]:
    from src.utils.name_clean import resolve_canonical_name

    out = {"dates": {}, "pass": True}
    for d in daterange(TRADES_FIRST, date(2026, 9, 30)):
        c = commit_at(d)
        a = board_at(c, *NATIVE["N1"]) if c else None
        b = board_at(c, *NATIVE["N1_crowdCsv"]) if c else None
        if not a or not b:
            continue
        bmap = {resolve_canonical_name(n): v for n, v in zip(*b)}
        matched = ok = 0
        for n, v in zip(*a):
            k = resolve_canonical_name(n)
            if k in bmap:
                matched += 1
                ok += abs(v - bmap[k]) <= P1_TOLERANCE
        share = ok / matched if matched else 0.0
        out["dates"][d.isoformat()] = {"matched": matched, "within": ok, "share": round(share, 4)}
        if share < P1_SHARE:
            out["pass"] = False
    out["datesChecked"] = len(out["dates"])
    if not out["dates"]:
        out["pass"] = False
    return out


def snapshot_meta(commit: str) -> dict[str, Any]:
    from src.model_registry.training_run import _snapshot_at
    from src.utils.name_clean import resolve_canonical_name

    rel = _snapshot_at(commit)
    if not rel:
        return {}
    d = json.loads(git("show", f"{commit}:{rel}", binary=True).decode("utf-8"))
    pos = {
        resolve_canonical_name(k): str(v).upper()
        for k, v in ((d.get("sleeper") or {}).get("positions") or {}).items()
    }
    rookie = {
        resolve_canonical_name(k): (p or {}).get("_yearsExp") == 0
        for k, p in (d.get("players") or {}).items()
        if isinstance(p, dict)
    }
    return {"path": rel, "pos": pos, "rookie": rookie}


def player_matched(native: tuple[list[str], list[float]], target, c: float, s: float, meta):
    """S5: per-player |ln v_arm - ln v_OTC| for N1 vs c3 (both at KTC's players-only rank)."""
    from src.canonical.player_valuation import training_percentiles
    from src.model_registry import holdout
    from src.utils.name_clean import resolve_canonical_name

    names, vals = native
    tnames, tvals = target
    tnames, tvals = tnames[:400], tvals[:400]
    ttop = tvals[0]
    tmap = {resolve_canonical_name(n): v / ttop * 9999.0 for n, v in zip(tnames, tvals)}
    ps = training_percentiles(len(vals))
    top = vals[0]
    rows = []
    for i, (n, v) in enumerate(zip(names, vals)):
        k = resolve_canonical_name(n)
        if k not in tmap:
            continue
        tv = tmap[k]
        nat = v / top * 9999.0
        hv = holdout.hill(ps[i], c, s)
        rows.append(
            {
                "pos": meta.get("pos", {}).get(k, "UNMATCHED"),
                "rookie": bool(meta.get("rookie", {}).get(k, False)),
                "eNative": abs(math.log(nat) - math.log(tv)),
                "eC3": abs(math.log(hv) - math.log(tv)),
            }
        )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=HERE)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args()

    from src.model_registry import training_run as tr

    # Pins.
    code_sha = git("rev-parse", "HEAD")
    dirty = bool(git("status", "--porcelain", "--untracked-files=no"))
    prereg_commit = git("log", "-1", "--format=%H", "--", str(PREREG.relative_to(REPO)))
    for arm, h in EXPECTED_MANIFESTS.items():
        got = arm_manifest(arm).manifest_hash()
        if got != h:
            raise SystemExit(f"{arm}: manifest {got} != preregistered {h}; refusing to score")

    last_target = last_commit_day(TARGET_PATH)
    last_fit_day = last_target  # h=0 needs a target on the origin day
    origins = list(daterange(FIRST_ORIGIN, last_fit_day))
    print(f"[d2] origins {origins[0]} .. {origins[-1]} ({len(origins)}); target last {last_target}")

    p1 = p1_check()
    print(f"[d2] P1 pass={p1['pass']} over {p1['datesChecked']} dates")
    n1_first = FIRST_ORIGIN if p1["pass"] else TRADES_FIRST

    # Fits.
    jobs = []
    for d in origins:
        c = commit_at(d)
        if not c:
            continue
        for arm in DECISIVE_ARMS:
            if arm in ("M3", "M4") and d < n1_first:
                continue
            jobs.append((arm, c, cutoff_of(d).isoformat()))
        if d >= TRADES_FIRST:
            for arm in DESCRIPTIVE_ARMS:
                jobs.append((arm, c, cutoff_of(d).isoformat()))
    print(f"[d2] {len(jobs)} substrate-v2 replays")
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        fits = list(ex.map(_fit_job, jobs, chunksize=2))
        verify = None if args.no_verify else list(ex.map(_fit_job, jobs, chunksize=2))
    mismatch: dict[str, int] = {}
    if verify is not None:
        for a, b in zip(fits, verify):
            if a["challengerHash"] != b["challengerHash"] or a["offense"] != b["offense"]:
                mismatch[a["arm"]] = mismatch.get(a["arm"], 0) + 1
    print(f"[d2] verification mismatches: {mismatch or 'none'}")
    fit_by = {(f["arm"], f["trainingCutoff"][:10]): f for f in fits}

    with (args.out / "runs.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for f in sorted(fits, key=lambda x: (x["arm"], x["trainingCutoff"])):
            fh.write(json.dumps(f, sort_keys=True) + "\n")

    # Spacing curves per origin.
    def curve_for(arm: str, d: date, pairs):
        if arm == "C0":
            return master_curve(CHAMPION["c"], CHAMPION["s"], pairs)
        if arm.startswith("M"):
            f = fit_by.get((arm, d.isoformat()))
            if not f or f["offense"]["c"] is None or not f.get("promotable", True):
                return None
            return master_curve(f["offense"]["c"], f["offense"]["s"], pairs)
        path, col = NATIVE[arm]
        b = board_at(commit_at(d), path, col)
        return native_curve(b[1]) if b and len(b[1]) >= 100 else None

    comparisons = {
        # decisive
        "Q1": ("N1", "C0", n1_first, True),
        "Q2": ("C0", "M1", FIRST_ORIGIN, True),
        "Q3": ("M1", "M3", n1_first, True),
        "Q4": ("M1", "M2", FIRST_ORIGIN, True),
        # secondary (S1, S2) and descriptive (S4, S6)
        "S1_c3_underM1_vs_N1": ("N1", "M1", n1_first, False),
        "S2_M4_vs_M1": ("M1", "M4", n1_first, False),
        "S2_M2_vs_C0": ("C0", "M2", FIRST_ORIGIN, False),
        "S2_M3_vs_C0": ("C0", "M3", n1_first, False),
        "S2_M4_vs_C0": ("C0", "M4", n1_first, False),
        "S4_Q1_crowdCsv": ("N1_crowdCsv", "C0", TRADES_FIRST, False),
        "S6_M5_vs_M1": ("M1", "M5", TRADES_FIRST, False),
        "S6_M6_vs_M1": ("M1", "M6", TRADES_FIRST, False),
        "S6_M7_vs_M1": ("M1", "M7", TRADES_FIRST, False),
        "S6_M8_vs_M1": ("M1", "M8", TRADES_FIRST, False),
        "S6_N2_vs_C0": ("N2", "C0", TRADES_FIRST, False),
        "S6_DLFnative_vs_C0": ("DLFnative", "C0", DLF_VALUES_FIRST, False),
    }

    target_pins: dict[str, Any] = {}
    series: dict[str, dict[int, list[dict]]] = {k: {h: [] for h in HORIZONS} for k in comparisons}
    for d in origins:
        for h in HORIZONS:
            td = d + timedelta(days=h)
            if td > last_target:
                continue
            tc = commit_at(td)
            tb = board_at(tc, TARGET_PATH, TARGET_COL) if tc else None
            if not tb or len(tb[1]) < 100:
                continue
            target_pins[td.isoformat()] = {"commit": tc, "blob": blob_sha(tc, TARGET_PATH)}
            pairs = target_pairs(tb[1])
            for name, (ref, arm, first, _dec) in comparisons.items():
                if d < first:
                    continue
                if name == "S6_DLFnative_vs_C0" and h != 0:
                    continue
                ca, cb = curve_for(ref, d, pairs), curve_for(arm, d, pairs)
                if ca is None or cb is None:
                    continue
                sc = score(ca, cb, pairs)
                sc["origin"] = d.isoformat()
                sc["target"] = td.isoformat()
                series[name][h].append(sc)

    def summarize(rows: list[dict], first: date | None = None) -> dict[str, Any]:
        rows = [r for r in rows if first is None or r["origin"] >= first.isoformat()]
        if not rows:
            return {"origins": 0, "spanDays": 0}
        deltas = [r["ref"] - r["arm"] for r in rows]
        days = [date.fromisoformat(r["origin"]) for r in rows]
        bands: dict[str, Any] = {}
        for lo, hi in BANDS:
            k = f"{lo}-{hi}"
            vals = [r["bands"][k]["ref"] - r["bands"][k]["arm"] for r in rows if k in r["bands"]]
            if vals:
                bands[k] = {"meanDelta": statistics.fmean(vals), "n": len(vals)}
        return {
            "origins": len(rows),
            "spanDays": (max(days) - min(days)).days + 1,
            "first": min(days).isoformat(),
            "last": max(days).isoformat(),
            "meanRmseRef": statistics.fmean(r["ref"] for r in rows),
            "meanRmseArm": statistics.fmean(r["arm"] for r in rows),
            "medianIndexN": statistics.median(r["n"] for r in rows),
            "ci": moving_block_ci(deltas),
            "winShare": sum(x > 0 for x in deltas) / len(deltas),
            "bands": bands,
        }

    results: dict[str, Any] = {}
    for name, (ref, arm, _first, decisive) in comparisons.items():
        entry: dict[str, Any] = {"reference": ref, "arm": arm, "decisive": decisive}
        for h in HORIZONS:
            entry[f"h{h}"] = summarize(series[name][h])
        if decisive:
            prim = entry[f"h{PRIMARY_H}"]
            margin = (
                max(MARGIN_POINTS, MARGIN_FRACTION * prim["meanRmseRef"])
                if prim["origins"]
                else None
            )
            sec = {
                h: (entry[f"h{h}"].get("ci") or {}).get("mean") for h in HORIZONS if h != PRIMARY_H
            }
            band_pos = sum(1 for b in prim.get("bands", {}).values() if b["meanDelta"] > 0)
            arm_void = mismatch.get(arm, 0) or mismatch.get(ref, 0)
            entry["margin"] = margin
            entry["bandsPositive"] = band_pos
            entry["verdict"] = (
                "VOID (verification mismatch)"
                if arm_void
                else (verdict(prim, sec, band_pos, margin) if prim["origins"] else "INSUFFICIENT")
            )
            entry["S3_postSelection"] = summarize(series[name][PRIMARY_H], S3_FIRST)
        results[name] = entry
        print(f"[d2] {name}: {entry.get('verdict', '(secondary)')}")

    # S5: player-matched Q1 at h = 7.
    s5_rows: list[dict] = []
    s5_by_origin: dict[str, float] = {}
    for d in origins:
        if d < n1_first:
            continue
        td = d + timedelta(days=PRIMARY_H)
        if td > last_target:
            continue
        nb = board_at(commit_at(d), *NATIVE["N1"])
        tb = board_at(commit_at(td), TARGET_PATH, TARGET_COL)
        if not nb or not tb:
            continue
        meta = snapshot_meta(commit_at(td))
        rows = player_matched(nb, tb, CHAMPION["c"], CHAMPION["s"], meta)
        if rows:
            s5_by_origin[d.isoformat()] = statistics.fmean(r["eNative"] - r["eC3"] for r in rows)
            for r in rows:
                r["origin"] = d.isoformat()
            s5_rows.extend(rows)

    def s5_group(pred) -> dict[str, Any]:
        sel = [r for r in s5_rows if pred(r)]
        if not sel:
            return {"n": 0}
        by_o: dict[str, list[float]] = {}
        for r in sel:
            by_o.setdefault(r["origin"], []).append(r["eNative"] - r["eC3"])
        daily = [statistics.fmean(v) for _k, v in sorted(by_o.items())]
        return {
            "n": len(sel),
            "origins": len(daily),
            "meanAbsLogErrNative": statistics.fmean(r["eNative"] for r in sel),
            "meanAbsLogErrC3": statistics.fmean(r["eC3"] for r in sel),
            "ci": moving_block_ci(daily),
        }

    results["S5_playerMatched_Q1_h7"] = {
        "definition": "mean over players of |ln v_N1 - ln v_OTC| minus |ln v_c3(C0) - ln v_OTC|; >0 = c3 closer",
        "all": s5_group(lambda r: True),
        **{p: s5_group(lambda r, p=p: r["pos"] == p) for p in ("QB", "RB", "WR", "TE")},
        "rookies": s5_group(lambda r: r["rookie"]),
        "veterans": s5_group(lambda r: not r["rookie"]),
        "teNote": "TE basis-confounded: KTC TE++ vs OTC base",
    }

    out = {
        "schema": "hill-d2/v1",
        "pins": {
            "codeSha": code_sha,
            "trackedTreeDirty": dirty,
            "ref": REF,
            "refSha": git("rev-parse", REF),
            "preregistration": {
                "path": str(PREREG.relative_to(REPO)).replace("\\", "/"),
                "commit": prereg_commit,
                "sha256Lf": sha256_lf(PREREG),
            },
            "runScriptSha256Lf": sha256_lf(Path(__file__)),
            "codeHash": tr.code_identity()["codeHash"],
            "substrateVersion": 2,
            "defaultManifestHash": __import__(
                "src.model_registry.training_manifest", fromlist=["x"]
            )
            .default_manifest()
            .manifest_hash(),
            "armManifests": EXPECTED_MANIFESTS,
            "champion": CHAMPION,
            "target": {
                "path": TARGET_PATH,
                "column": TARGET_COL,
                "lastCommitDay": str(last_target),
            },
            "targetBoards": dict(sorted(target_pins.items())),
            "bootstrap": {
                "method": "circular moving-block over daily paired deltas",
                "blockDays": BLOCK_DAYS,
                "resamples": RESAMPLES,
                "seed": SEED,
                "decisiveLevel": DECISIVE_LEVEL,
            },
            "fits": len(fits),
            "verified": verify is not None,
            "verificationMismatches": mismatch,
            "recordedAt": datetime.now(timezone.utc).isoformat(),
        },
        "p1": p1,
        "n1FirstOrigin": n1_first.isoformat(),
        "results": results,
        "s5DailyQ1": s5_by_origin,
    }
    (args.out / "results.json").write_text(
        json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
