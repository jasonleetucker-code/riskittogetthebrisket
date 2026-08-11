#!/usr/bin/env python3
"""Corridor dependency pass — pin, and answer Q1/Q2/Q3.

``--pin``        record the fresh CD inputs (a NEW pin; the B4 pin is not
                 reused, recomputed or overwritten).
``--diagnose``   Q1 anchor independence, Q2 band independence, Q3 the
                 confidence-bucket dependency (#796).

Nothing here changes production.

Three boards are built from one pinned input and every diagnostic is a
difference between them:

``P``   production — corridor on.
``N``   corridor suppressed (``suppress_market_corridor_clamp=True``, a
        parameter the pipeline already exposes). This is the pre-corridor
        blend, i.e. what the corridor is acting on.
``L``   leave-one-out: ``idpTradeCalc`` excluded from the blend, corridor
        suppressed. **Diagnostic only.** Removing IDPTC from the canonical
        blend is explicitly not a candidate repair — this board exists to
        measure how much of the blend IDPTC already is, so its second
        influence through the anchor can be stated as an increment rather
        than as a total.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

OUT = Path(__file__).resolve().parent
CSV_DIR = ROOT / "CSVs" / "site_raw"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def latest_board() -> Path:
    files = sorted((ROOT / "exports" / "latest").glob("dynasty_data_*.json"), reverse=True)
    if not files:
        raise SystemExit("no exported board under exports/latest")
    return files[0]


def pin() -> dict:
    from src.api.data_contract import (
        _MARKET_ANCHOR_BY_ASSET_CLASS,
        _MARKET_ANCHOR_FALLBACKS,
        _MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS,
        _MARKET_CORRIDOR_MIN_BUCKET_N,
        _MARKET_CORRIDOR_PERCENTILE,
        _RANKING_SOURCES,
    )
    from src.canonical.tail_policy import TAIL_SATURATION_RANK
    from src.model_registry.hill_masters import MODEL_ID, load_or_seed_registry

    board = latest_board()
    raw = json.loads(board.read_bytes())
    reg = load_or_seed_registry()
    dirty = [ln.split(maxsplit=1)[-1] for ln in _git("status", "--porcelain").splitlines()]
    return {
        "phase": "CD (corridor dependency)",
        "note": (
            "A NEW pin. The B4 pin (board sha256 8fb6ede274171aee…) is historical "
            "and is neither reused nor overwritten by this pass."
        ),
        "codeSha": _git("rev-parse", "HEAD"),
        "codeSubject": _git("log", "-1", "--format=%s"),
        "mainTip": _git("rev-parse", "origin/main"),
        "dirtyPaths": dirty,
        "dirtyIsEvidenceOnly": all(p.startswith("docs/master-site-audit/evidence/") for p in dirty),
        "board": {
            "path": str(board.relative_to(ROOT)),
            "sha256": _sha(board),
            "bytes": board.stat().st_size,
            "scrapeTimestamp": raw.get("scrapeTimestamp"),
            "playerCount": len(raw.get("players") or {}),
        },
        "sourceCsvs": {
            p.name: {"sha256": _sha(p), "bytes": p.stat().st_size}
            for p in sorted(CSV_DIR.glob("*.csv"))
        },
        "championModel": {
            "modelId": MODEL_ID,
            "version": reg.champion.version,
            "params": dict(reg.champion.params),
        },
        "corridorConstants": {
            "percentile": _MARKET_CORRIDOR_PERCENTILE,
            "minBucketN": _MARKET_CORRIDOR_MIN_BUCKET_N,
            "maxBandByAssetClass": dict(_MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS),
            "anchorByAssetClass": dict(_MARKET_ANCHOR_BY_ASSET_CLASS),
            "anchorFallbacks": {k: list(v) for k, v in _MARKET_ANCHOR_FALLBACKS.items()},
        },
        "tailPolicy": {"TAIL_SATURATION_RANK": TAIL_SATURATION_RANK},
        "blendVoters": sorted(str(s.get("key")) for s in _RANKING_SOURCES),
    }


def build(*, corridor: bool = True, drop_source: str | None = None) -> list[dict]:
    from src.api.data_contract import build_api_data_contract

    raw = json.loads(latest_board().read_bytes())
    overrides = {drop_source: {"include": False}} if drop_source else None
    with contextlib.redirect_stdout(io.StringIO()):
        contract = build_api_data_contract(
            raw,
            source_overrides=overrides,
            suppress_market_corridor_clamp=not corridor,
        )
    return contract.get("playersArray") or []


def _idx(rows: list[dict]) -> dict[str, dict]:
    return {str(r.get("displayName")): r for r in rows}


def diagnose() -> None:
    from src.api.data_contract import (
        _MARKET_ANCHOR_FALLBACKS,
        _MARKET_CORRIDOR_MIN_BUCKET_N,
        _MARKET_CORRIDOR_PERCENTILE,
        _RANKING_SOURCES,
        _percentile,
    )

    snap = pin()
    print("== CD pin ==")
    print(f"  code   {snap['codeSha'][:9]}   main {snap['mainTip'][:9]}")
    b = snap["board"]
    print(f"  board  {b['path']}  sha256={b['sha256'][:16]}…  {b['bytes']} B")
    print(f"         scraped={b['scrapeTimestamp']}  players={b['playerCount']}")
    print(f"  csvs   {len(snap['sourceCsvs'])} hashed")
    print(f"  champ  v{snap['championModel']['version']}")
    print(f"  tail   TAIL_SATURATION_RANK={snap['tailPolicy']['TAIL_SATURATION_RANK']}")
    print(
        f"  band   P{int(_MARKET_CORRIDOR_PERCENTILE * 100)} per confidence bucket, "
        f"minBucketN={_MARKET_CORRIDOR_MIN_BUCKET_N}, "
        f"maxBand={snap['corridorConstants']['maxBandByAssetClass']}"
    )
    if snap["dirtyPaths"]:
        print(
            f"  dirty  {len(snap['dirtyPaths'])} path(s), evidence-only="
            f"{snap['dirtyIsEvidenceOnly']}"
        )

    voters = {str(s.get("key")) for s in _RANKING_SOURCES}

    # ── Q1: is any anchor independent of the blend it constrains? ──
    print("\n" + "=" * 72)
    print("Q1  ANCHOR INDEPENDENCE")
    print("=" * 72)
    print("\n-- structural: is any anchor NOT a voter in the blend it constrains? --")
    chain_report = {}
    for ac, chain in _MARKET_ANCHOR_FALLBACKS.items():
        rows = [(k, k in voters) for k in chain]
        chain_report[ac] = {k: v for k, v in rows}
        indep = [k for k, v in rows if not v]
        print(f"  {ac:<8} chain={chain}")
        print(f"           independent members: {indep or 'NONE'}")
    print("\n  Every member of every chain votes in the blend it later anchors.")
    print("  The stage-3 median fallback is a median OVER THAT SAME CHAIN, so it is")
    print("  not independent either — it is a second statistic of the same voters.")

    print("\n-- building P (production), N (no corridor), L (leave-one-out IDPTC) --")
    P, N, L = build(), build(corridor=False), build(corridor=False, drop_source="idpTradeCalc")
    pi, ni, li = _idx(P), _idx(N), _idx(L)
    print(f"  rows: P={len(P)} N={len(N)} L={len(L)}")

    clamped = {
        nm: r["marketCorridorClamp"]
        for nm, r in pi.items()
        if isinstance(r.get("marketCorridorClamp"), dict)
        and r["marketCorridorClamp"].get("applied")
    }
    print(f"  clamped rows: {len(clamped)}")

    q1: dict = {"chains": chain_report, "clampedRows": len(clamped)}

    # The sharp statement: on a clamped row the final value is
    # A x (1 +/- band) -- a pure function of the anchor. Whatever share the
    # anchor had in the blend, after the clamp it has all of it.
    shares, jumps, incs, firsts = [], [], [], []
    anchor_is_voter = 0
    for nm, c in clamped.items():
        row = pi[nm]
        n_sources = len(
            [1 for m in (row.get("sourceRankMeta") or {}).values() if isinstance(m, dict)]
        )
        share = 1.0 / n_sources if n_sources else None
        if share is not None:
            shares.append(share)
            jumps.append(1.0 - share)
        if c.get("marketSource") in voters:
            anchor_is_voter += 1
        v_pre = float((ni.get(nm) or {}).get("rankDerivedValue") or 0.0)
        v_fin = float(row.get("rankDerivedValue") or 0.0)
        v_loo = float((li.get(nm) or {}).get("rankDerivedValue") or 0.0)
        if v_pre and v_fin:
            incs.append(abs(v_fin - v_pre) / v_pre)
        if v_pre and v_loo:
            firsts.append(abs(v_pre - v_loo) / v_loo)

    def stats(xs):
        if not xs:
            return None
        s = sorted(xs)
        return {
            "n": len(s),
            "min": round(s[0], 4),
            "median": round(s[len(s) // 2], 4),
            "p90": round(s[int(0.9 * (len(s) - 1))], 4),
            "max": round(s[-1], 4),
            "mean": round(sum(s) / len(s), 4),
        }

    print("\n-- incremental second influence, on clamped rows --")
    print(f"  anchor is also a blend voter on {anchor_is_voter} of {len(clamped)} clamped rows")
    print(f"  anchor's share of the blend BEFORE the clamp (1/n): {stats(shares)}")
    print(f"  anchor's share of the value AFTER the clamp        : 1.0 on every clamped row")
    print("    (final = anchor x (1 +/- band), so the value is a pure function of the anchor)")
    print(f"  share JUMP attributable to the corridor            : {stats(jumps)}")
    print(f"  |final - preCorridor| / preCorridor                : {stats(incs)}")
    print(f"  FIRST influence, |pre - leaveOneOut| / leaveOneOut  : {stats(firsts)}")
    q1.update(
        {
            "anchorIsAlsoVoter": anchor_is_voter,
            "anchorBlendShareBeforeClamp": stats(shares),
            "anchorShareAfterClamp": 1.0,
            "shareJump": stats(jumps),
            "incrementalSecondInfluence": stats(incs),
            "firstInfluenceViaBlend": stats(firsts),
        }
    )

    print("\n-- anchor source distribution on clamped rows --")
    anchors = Counter(c.get("marketSource") for c in clamped.values())
    print(f"  {dict(anchors)}")
    q1["anchorSources"] = dict(anchors)

    # ── Q2: is a self-derived P90 a valid catastrophic-error rail? ──
    print("\n" + "=" * 72)
    print("Q2  BAND INDEPENDENCE")
    print("=" * 72)

    # The structural claim, checked arithmetically: a P90 band clamps the
    # worst ~10% of rows BY CONSTRUCTION, whatever the board looks like.
    eligible = [
        r
        for r in N
        if r.get("canonicalConsensusRank") and str(r.get("assetClass") or "") != "offense"
    ]
    print(f"\n-- eligible IDP-side rows (post-blend, pre-corridor): {len(eligible)} --")
    rate = 100.0 * len(clamped) / len(eligible) if eligible else 0.0
    print(f"  clamped {len(clamped)} of {len(eligible)} = {rate:.1f}%")
    print(
        f"  a P{int(_MARKET_CORRIDOR_PERCENTILE * 100)} band clamps the worst "
        f"{100 * (1 - _MARKET_CORRIDOR_PERCENTILE):.0f}% by construction, minus ties"
    )
    q2: dict = {
        "eligibleRows": len(eligible),
        "clampedRows": len(clamped),
        "triggerRatePct": round(rate, 2),
        "percentile": _MARKET_CORRIDOR_PERCENTILE,
    }

    # Systemic drift: scale every IDP blended value by f, leaving anchors
    # alone. A rail that detects calibration failure should fire MORE as f
    # grows. A self-derived P90 re-centres on the drifted board.
    from src.api.data_contract import _market_anchor_for_row

    base_pairs = []
    for r in eligible:
        a, _src = _market_anchor_for_row(r)
        v = float(r.get("rankDerivedValue") or 0.0)
        if a and v > 0:
            base_pairs.append((str(r.get("displayName")), v, a))

    def fire_set(pairs):
        drifts = sorted(abs(v - a) / a for _n, v, a in pairs)
        band = _percentile(drifts, _MARKET_CORRIDOR_PERCENTILE)
        return band, {n for n, v, a in pairs if abs(v - a) / a > band}

    print("\n-- systemic whole-IDP-board drift: does the band move WITH the defect? --")
    print("  Every IDP blended value scaled by f, anchors untouched — a whole-board")
    print("  calibration failure, which is exactly what a safety rail exists for.")
    print(f"  {'drift f':<10}{'P90 band':>12}{'fires':>8}{'rate':>9}{'same rows as f=1':>19}")
    drift_rows = []
    base_band, base_fired = fire_set(base_pairs)
    for f in (1.0, 1.05, 1.15, 1.30, 1.60, 2.00, 3.00, 10.0):
        band, fired = fire_set([(n, v * f, a) for n, v, a in base_pairs])
        pct = 100.0 * len(fired) / len(base_pairs)
        same = fired == base_fired
        print(f"  {f:<10.2f}{band:>12.4f}{len(fired):>8}{pct:>8.1f}%{str(same):>19}")
        drift_rows.append(
            {
                "f": f,
                "band": round(band, 4),
                "fired": len(fired),
                "ratePct": round(pct, 2),
                "identicalRowSetToUndrifted": same,
            }
        )
    q2["systemicDrift"] = drift_rows
    print("\n  A flat rate on the SAME rows means the band is not detecting the drift at")
    print("  all — it re-derives itself from the drifted board. That is #795, and it is a")
    print("  tautology rather than a tuning problem: a P90 threshold cuts the worst 10% of")
    print("  whatever distribution it is handed, healthy or catastrophic.")

    print("\n-- absorption: how much of the board can break before the rail stops seeing it? --")
    print("  A fraction q of rows is inflated 3x. A rail should catch all of them; a P90")
    print("  can flag at most ~10% of the board, so past that it must start missing.")
    print(f"  {'broken q':<11}{'rows':>7}{'caught':>8}{'detection':>11}{'band':>9}")
    absorb = []
    for q in (0.02, 0.05, 0.10, 0.20, 0.40, 0.80):
        k = max(1, int(q * len(base_pairs)))
        broken = {n for n, _v, _a in base_pairs[:k]}
        band, fired = fire_set(
            [(n, v * (3.0 if n in broken else 1.0), a) for n, v, a in base_pairs]
        )
        caught = len(fired & broken)
        det = 100.0 * caught / len(broken)
        print(f"  {q:<11.0%}{len(broken):>7}{caught:>8}{det:>10.1f}%{band:>9.4f}")
        absorb.append(
            {
                "brokenFraction": q,
                "brokenRows": len(broken),
                "caught": caught,
                "detectionPct": round(det, 2),
                "band": round(band, 4),
            }
        )
    q2["absorption"] = absorb
    print("\n  Detection collapsing as q grows is the same tautology from the other side:")
    print("  the rail's capacity is fixed at ~10% of the board however much is broken.")

    # ── Q3: are the confidence buckets a valid axis for separate bands? ──
    print("\n" + "=" * 72)
    print("Q3  CONFIDENCE-BUCKET DEPENDENCY  (#796, audited as a dependency)")
    print("=" * 72)
    from src.api.data_contract import _market_anchor_for_row

    by_bucket: dict[str, list[float]] = {}
    for r in eligible:
        a, _ = _market_anchor_for_row(r)
        v = float(r.get("rankDerivedValue") or 0.0)
        if not a or v <= 0:
            continue
        by_bucket.setdefault(str(r.get("confidenceBucket") or "low"), []).append(abs(v - a) / a)
    overall = sorted(x for xs in by_bucket.values() for x in xs)
    overall_p90 = _percentile(overall, _MARKET_CORRIDOR_PERCENTILE)
    print(f"\n  {'bucket':<10}{'n':>6}{'usesOwnBand':>14}{'P90':>10}{'medianDrift':>14}")
    q3buckets = {}
    for bkt, vals in sorted(by_bucket.items()):
        s = sorted(vals)
        own = len(s) >= _MARKET_CORRIDOR_MIN_BUCKET_N
        p90 = _percentile(s, _MARKET_CORRIDOR_PERCENTILE) if own else overall_p90
        med = s[len(s) // 2]
        print(f"  {bkt:<10}{len(s):>6}{str(own):>14}{p90:>10.4f}{med:>14.4f}")
        q3buckets[bkt] = {
            "n": len(s),
            "usesOwnBand": own,
            "band": round(p90, 4),
            "medianDrift": round(med, 4),
        }
    print(f"  {'OVERALL':<10}{len(overall):>6}{'—':>14}{overall_p90:>10.4f}")
    q3 = {
        "buckets": q3buckets,
        "overallP90": round(overall_p90, 4),
        "minBucketN": _MARKET_CORRIDOR_MIN_BUCKET_N,
    }

    bands = [v["band"] for v in q3buckets.values()]
    if bands:
        spread = max(bands) - min(bands)
        print(
            f"\n  band spread across buckets: {spread:.4f} "
            f"(min {min(bands):.4f}, max {max(bands):.4f})"
        )
        print("  If the bands are close, confidence-specific banding is doing little work")
        print("  and the dependency is mostly unearned complexity.")
        q3["bandSpread"] = round(spread, 4)

    payload = {
        "pin": snap,
        "q1_anchorIndependence": q1,
        "q2_bandIndependence": q2,
        "q3_confidenceDependency": q3,
    }
    (OUT / "cd_corridor_diagnose.json").write_text(json.dumps(payload, indent=1, default=str))
    print(f"\nwrote {OUT / 'cd_corridor_diagnose.json'}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pin", action="store_true")
    ap.add_argument("--diagnose", action="store_true")
    args = ap.parse_args()
    if args.pin:
        print(json.dumps(pin(), indent=1, default=str))
        return 0
    if args.diagnose:
        diagnose()
        return 0
    ap.error("pass --pin or --diagnose")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
