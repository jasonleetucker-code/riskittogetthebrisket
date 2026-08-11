#!/usr/bin/env python3
"""B3 — pin the baseline and reproduce W02-F003 (IDP market corridor clamp).

Two things, deliberately in one script so the numbers can never be quoted
against a different tree than the one that produced them:

  ``--pin``       record the exact B3 inputs — code SHA + dirty state, the
                  board snapshot and its hash, every source CSV hash and
                  mtime, contract freshness stamps, and the ACTIVE champion
                  model version and constants.
  ``--reproduce`` measure the corridor's current behaviour on that pin, and
                  the anchor-lineage question B3 §5 makes mandatory.

The lineage question is the reason this is not just a counter. The corridor
anchors IDP rows to ``idpTradeCalc``, and ``idpTradeCalc`` is a *voting
member of the blend being clamped*. Every fallback anchor
(``dlfIdp`` / ``idpShow`` / ``fantasyProsIdp``) is too. So the "market
anchor" is not independent evidence about the row — it is one of the
inputs, given a second, post-blend veto. This script quantifies that by
building three boards from ONE pinned payload:

  clamped          the production board
  unclamped        ``suppress_market_corridor_clamp=True``
  no-IDPTC         ``suppress`` + ``idpTradeCalc`` dropped from voting

Nothing here changes production. ``suppress_market_corridor_clamp`` is an
existing parameter with an existing caller (``consensus_edge/fair_value``).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

OUT = Path(__file__).resolve().parent
CSV_DIR = ROOT / "CSVs" / "site_raw"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


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
    board = latest_board()
    from src.model_registry.hill_masters import MODEL_ID, load_or_seed_registry

    reg = load_or_seed_registry()
    champ = reg.champion
    raw = json.loads(board.read_bytes())

    snapshot = {
        "phase": "B3",
        "codeSha": _git("rev-parse", "HEAD"),
        "codeSubject": _git("log", "-1", "--format=%s"),
        "dirty": bool(_git("status", "--porcelain")),
        "board": {
            "path": str(board.relative_to(ROOT)),
            "sha256_16": _sha(board),
            "bytes": board.stat().st_size,
            "mtime": board.stat().st_mtime,
            "scrapeTimestamp": raw.get("scrapeTimestamp"),
            "date": raw.get("date"),
            "playerCount": len(raw.get("players") or {}),
        },
        "sourceCsvs": {
            p.name: {"sha256_16": _sha(p), "bytes": p.stat().st_size, "mtime": p.stat().st_mtime}
            for p in sorted(CSV_DIR.glob("*.csv"))
        },
        "championModel": {
            "modelId": MODEL_ID,
            "version": champ.version,
            "status": champ.status,
            "producer": champ.producer,
            "fittedAt": champ.fitted_at,
            "promotedAt": getattr(champ, "promoted_at", None),
            "appliedAt": getattr(champ, "applied_at", None),
            "params": dict(champ.params),
        },
        "registryVersions": [v.version for v in reg.versions],
    }
    return snapshot


# ── contract builds ────────────────────────────────────────────────────


def build(board: Path, **kwargs) -> dict:
    from src.api.data_contract import build_api_data_contract

    raw = json.loads(board.read_bytes())
    with contextlib.redirect_stdout(io.StringIO()):
        return build_api_data_contract(raw, **kwargs)


def _pct(part: int, whole: int) -> str:
    return f"{100.0 * part / whole:.1f}%" if whole else "n/a"


def _q(vals: list[float], p: float) -> float:
    if not vals:
        return float("nan")
    s = sorted(vals)
    return s[min(len(s) - 1, int(round(p * (len(s) - 1))))]


def reproduce() -> None:
    from src.api.data_contract import (
        _MARKET_ANCHOR_BY_ASSET_CLASS,
        _MARKET_ANCHOR_FALLBACKS,
        _MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS,
        _MARKET_CORRIDOR_MIN_BUCKET_N,
        _MARKET_CORRIDOR_PERCENTILE,
        _RANKING_SOURCES,
    )

    board = latest_board()
    print("== B3 pin ==")
    snap = pin()
    print(f"  code   {snap['codeSha'][:9]}  dirty={snap['dirty']}")
    print(
        f"  board  {snap['board']['path']}  sha256_16={snap['board']['sha256_16']}  "
        f"{snap['board']['bytes']} B  scraped={snap['board']['scrapeTimestamp']}"
    )
    print(f"  csvs   {len(snap['sourceCsvs'])} hashed")
    print(
        f"  champ  v{snap['championModel']['version']} "
        f"({snap['championModel']['status']}) params={snap['championModel']['params']}"
    )

    print("\n== corridor configuration as shipped ==")
    print(f"  primary anchors      {_MARKET_ANCHOR_BY_ASSET_CLASS}")
    print(f"  fallback chains      {_MARKET_ANCHOR_FALLBACKS}")
    print(f"  percentile           {_MARKET_CORRIDOR_PERCENTILE}")
    print(f"  min bucket n         {_MARKET_CORRIDOR_MIN_BUCKET_N}")
    print(f"  hard max band        {_MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS}")

    voting = {str(s.get("key") or "") for s in _RANKING_SOURCES}
    idp_chain = _MARKET_ANCHOR_FALLBACKS.get("idp") or []
    print("\n  anchor sources that are ALSO voting members of the blend they clamp:")
    for key in idp_chain:
        print(f"    {key:<18} voting={key in voting}")

    clamped = build(board)
    unclamped = build(board, suppress_market_corridor_clamp=True)

    rows_c = {r.get("displayName"): r for r in clamped.get("playersArray") or []}
    rows_u = {r.get("displayName"): r for r in unclamped.get("playersArray") or []}

    # ── prevalence ──
    clamps = [r for r in rows_c.values() if r.get("marketCorridorClamp")]
    ranked_idp = [
        r
        for r in rows_c.values()
        if r.get("assetClass") == "idp" and r.get("canonicalConsensusRank")
    ]
    eligible_non_offense = [
        r
        for r in rows_c.values()
        if str(r.get("assetClass") or "") != "offense" and r.get("canonicalConsensusRank")
    ]
    by_class: dict[str, int] = {}
    for r in clamps:
        by_class[str(r.get("assetClass"))] = by_class.get(str(r.get("assetClass")), 0) + 1

    print("\n== W02-F003 reproduction ==")
    print(
        f"  clamped {len(clamps)} rows — {_pct(len(clamps), len(ranked_idp))} of "
        f"{len(ranked_idp)} ranked IDP rows; asset classes {by_class}"
    )
    print(
        f"  non-offense ranked rows the clamp iterates: {len(eligible_non_offense)} "
        "(picks reach the loop and are dropped by having no anchor chain)"
    )
    capped = sum(1 for r in clamps if (r["marketCorridorClamp"] or {}).get("cappedByMaxBand"))
    bands = sorted({(r["marketCorridorClamp"] or {}).get("bandPct") for r in clamps})
    up = sum(1 for r in clamps if r["marketCorridorClamp"]["direction"] == "up")
    down = sum(1 for r in clamps if r["marketCorridorClamp"]["direction"] == "down")
    on_edge = 0
    for r in clamps:
        c = r["marketCorridorClamp"]
        sign = 1 if c["direction"] == "down" else -1
        edge = c["marketAnchor"] * (1.0 + sign * c["bandPct"])
        if abs(round(edge) - c["clampedValue"]) <= 1:
            on_edge += 1
    print(f"  cappedByMaxBand      {capped}/{len(clamps)} ({_pct(capped, len(clamps))})")
    print(f"  distinct bandPct     {bands}")
    print(f"  on the band edge     {on_edge}/{len(clamps)} ({_pct(on_edge, len(clamps))})")
    print(
        f"  direction            up {up} (value was BELOW anchor) / "
        f"down {down} (value was ABOVE anchor)"
    )

    # ── the empirical band the cap overrides ──
    print("\n== empirical bucket P90s the hard cap overrides ==")
    drifts_by_bucket: dict[str, list[float]] = {}
    overall: list[float] = []
    for r in rows_u.values():
        if not r.get("canonicalConsensusRank"):
            continue
        if str(r.get("assetClass") or "") == "offense":
            continue
        from src.api.data_contract import _market_anchor_for_row

        anchor, _src = _market_anchor_for_row(r)
        if anchor is None:
            continue
        try:
            v = float(r.get("rankDerivedValue") or 0.0)
        except (TypeError, ValueError):
            continue
        if v <= 0:
            continue
        d = abs(v - anchor) / anchor
        drifts_by_bucket.setdefault(str(r.get("confidenceBucket") or "low"), []).append(d)
        overall.append(d)
    cap = _MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS.get("idp")
    print(f"  overall  n={len(overall):<5} P90={_q(overall, 0.90):.4f}   (cap {cap})")
    for bucket, vals in sorted(drifts_by_bucket.items()):
        used_own = len(vals) >= _MARKET_CORRIDOR_MIN_BUCKET_N
        print(
            f"  {bucket:<8} n={len(vals):<5} P90={_q(vals, 0.90):.4f}   "
            f"{'own band' if used_own else 'FALLS BACK to overall'}   "
            f"cap wins={cap is not None and _q(vals, 0.90) > cap}"
        )

    # ── who gets clamped: by confidence bucket and by source count ──
    #
    # ``confidenceBucket`` is INTER-SOURCE agreement (high = >=2 sources
    # with a tight percentile spread). The corridor uses it to pick a
    # band. If high-confidence rows are clamped MORE, the corridor is
    # preferentially overriding the board's best-supported opinions with
    # a single dissenting source.
    print("\n== who gets clamped ==")
    print(f"  {'bucket':<10} {'ranked IDP':>10} {'clamped':>8} {'rate':>7} {'up/down':>9}")
    for bucket in ("high", "medium", "low", "none"):
        pop = [r for r in ranked_idp if str(r.get("confidenceBucket") or "") == bucket]
        cl = [r for r in pop if r.get("marketCorridorClamp")]
        if not pop:
            continue
        u = sum(1 for r in cl if r["marketCorridorClamp"]["direction"] == "up")
        print(
            f"  {bucket:<10} {len(pop):>10} {len(cl):>8} {_pct(len(cl), len(pop)):>7} "
            f"{f'{u}/{len(cl) - u}':>9}"
        )
    print(f"  {'sources':<10} {'ranked IDP':>10} {'clamped':>8} {'rate':>7}")
    for n in (1, 2, 3, 4, 5, 6):
        pop = [r for r in ranked_idp if len(r.get("sourceRankMeta") or {}) == n]
        if not pop:
            continue
        cl = [r for r in pop if r.get("marketCorridorClamp")]
        print(f"  {n:<10} {len(pop):>10} {len(cl):>8} {_pct(len(cl), len(pop)):>7}")

    # ── anchor lineage ──
    print("\n== anchor lineage on clamped rows ==")
    src_counts: dict[str, int] = {}
    anchor_also_voted = 0
    for r in clamps:
        s = str(r["marketCorridorClamp"].get("marketSource"))
        src_counts[s] = src_counts.get(s, 0) + 1
        meta = r.get("sourceRankMeta") or {}
        if s in meta:
            anchor_also_voted += 1
    for s, n in sorted(src_counts.items(), key=lambda kv: -kv[1]):
        print(f"  anchor={s:<24} {n:>4} rows")
    print(
        f"  rows where the anchor source ALSO voted in this row's blend: "
        f"{anchor_also_voted}/{len(clamps)} ({_pct(anchor_also_voted, len(clamps))})"
    )

    # ── how much of the served value the corridor owns ──
    print("\n== corridor's share of the served value ==")
    moved: list[tuple[str, float, float, float]] = []
    for name, rc in rows_c.items():
        ru = rows_u.get(name)
        if ru is None:
            continue
        vc, vu = rc.get("rankDerivedValue"), ru.get("rankDerivedValue")
        if vc is None or vu is None or vu == 0:
            continue
        if vc != vu:
            moved.append((name, vu, vc, 100.0 * (vc - vu) / vu))
    print(f"  rows whose SERVED value differs with the corridor on: {len(moved)}")
    if moved:
        pcts = [abs(m[3]) for m in moved]
        print(
            f"  |Δ%| mean={statistics.fmean(pcts):.2f} median={statistics.median(pcts):.2f} "
            f"p90={_q(pcts, 0.90):.2f} max={max(pcts):.2f}"
        )
        print("  largest 10:")
        for name, vu, vc, p in sorted(moved, key=lambda m: -abs(m[2] - m[1]))[:10]:
            print(f"    {name:<26} unclamped {vu:>5} → served {vc:>5}  ({p:+.1f}%)")

    # ── where the corridor leaves the row relative to the anchor ──
    #
    # The sharpest statement of the defect. By construction a clamped row
    # ends at exactly ``anchor × (1 ± band)``, so for those rows the blend
    # does not determine the value at all — the anchor does, to within a
    # fixed constant.
    print("\n== distance from the anchor, before and after the corridor ==")
    pre = [
        abs(r["marketCorridorClamp"]["originalValue"] - r["marketCorridorClamp"]["marketAnchor"])
        / r["marketCorridorClamp"]["marketAnchor"]
        for r in clamps
    ]
    post = [
        abs(r["marketCorridorClamp"]["clampedValue"] - r["marketCorridorClamp"]["marketAnchor"])
        / r["marketCorridorClamp"]["marketAnchor"]
        for r in clamps
    ]
    print(
        f"  unclamped |value − anchor| / anchor : median={statistics.median(pre):.4f} "
        f"p90={_q(pre, 0.90):.4f} max={max(pre):.4f}"
    )
    print(
        f"  clamped   |value − anchor| / anchor : median={statistics.median(post):.4f} "
        f"p90={_q(post, 0.90):.4f} max={max(post):.4f}"
    )
    print(
        f"  → {len(clamps)} of {len(ranked_idp)} ranked IDP rows "
        f"({_pct(len(clamps), len(ranked_idp))}) are served at exactly "
        "idpTradeCalc × 0.85 or × 1.15"
    )

    # ── IDPTC's DIRECT share of the vote it then vetoes ──
    #
    # Uses the stamped per-source contributions — the actual inputs to
    # aggregation — rather than rebuilding the board, so the IDP ladder
    # (which idpTradeCalc also seeds as backbone) stays intact. This
    # isolates the vote, which the whole-board rebuild below cannot.
    print("\n== idpTradeCalc's direct share of the vote on clamped rows ==")
    ratios: list[float] = []
    n_sources: list[int] = []
    for r in clamps:
        meta = r.get("sourceRankMeta") or {}
        own = (meta.get("idpTradeCalc") or {}).get("valueContribution")
        peers = [
            m["valueContribution"]
            for k, m in meta.items()
            if k != "idpTradeCalc"
            and isinstance(m, dict)
            and isinstance(m.get("valueContribution"), (int, float))
            and m["valueContribution"] > 0
        ]
        n_sources.append(len(meta))
        if own and peers:
            ratios.append(float(own) / statistics.median(peers))
    print(
        f"  sources stamped per clamped row: median={statistics.median(n_sources):.0f} "
        f"min={min(n_sources)} max={max(n_sources)}"
    )
    print(
        f"  idpTradeCalc contribution ÷ median of the other sources: n={len(ratios)} "
        f"median={statistics.median(ratios):.3f} p10={_q(ratios, 0.10):.3f} "
        f"p90={_q(ratios, 0.90):.3f}"
    )
    print(
        "  (>1 means IDPTC prices the row ABOVE its peers — and the corridor "
        "then pulls the blend back toward IDPTC as well)"
    )

    # ── leave-IDPTC-out diagnostic (B3 section 5 / 11) ──
    print("\n== leave-IDPTC-out WHOLE-BOARD rebuild (DIAGNOSTIC ONLY) ==")
    print(
        "  CAVEAT, load-bearing: idpTradeCalc is also the IDP BACKBONE, so\n"
        "  dropping it empties the shared-market ladder and every translated\n"
        "  IDP source falls back to a raw IDP-local rank. This board is\n"
        "  therefore NOT 'the same model minus one vote' — it is an UPPER\n"
        "  BOUND on idpTradeCalc's influence, and the vote-share block above\n"
        "  is the isolate."
    )
    no_idptc = build(
        board,
        suppress_market_corridor_clamp=True,
        source_overrides={"idpTradeCalc": {"include": False}},
    )
    rows_n = {r.get("displayName"): r for r in no_idptc.get("playersArray") or []}
    print(f"  {'player':<26} {'blend':>7} {'LOO':>7} {'anchor':>7} {'unclamp':>7} {'served':>7}")
    sample = sorted(clamps, key=lambda r: -(r["marketCorridorClamp"]["originalValue"]))[:12]
    for r in sample:
        name = str(r.get("displayName"))
        c = r["marketCorridorClamp"]
        ru = rows_u.get(name) or {}
        rn = rows_n.get(name) or {}
        print(
            f"  {name[:26]:<26} {c['originalValue']:>7} "
            f"{(rn.get('rankDerivedValue') or 0):>7} {c['marketAnchor']:>7} "
            f"{(ru.get('rankDerivedValue') or 0):>7} {(r.get('rankDerivedValue') or 0):>7}"
        )

    payload = {
        "pin": snap,
        "corridorConfig": {
            "primaryAnchors": _MARKET_ANCHOR_BY_ASSET_CLASS,
            "fallbackChains": _MARKET_ANCHOR_FALLBACKS,
            "percentile": _MARKET_CORRIDOR_PERCENTILE,
            "minBucketN": _MARKET_CORRIDOR_MIN_BUCKET_N,
            "maxBand": _MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS,
            "idpChainAllVoting": all(k in voting for k in idp_chain),
        },
        "reproduction": {
            "clampedRows": len(clamps),
            "rankedIdpRows": len(ranked_idp),
            "clampRate": len(clamps) / len(ranked_idp) if ranked_idp else None,
            "cappedByMaxBand": capped,
            "onBandEdge": on_edge,
            "distinctBandPct": [b for b in bands],
            "up": up,
            "down": down,
            "anchorAlsoVoted": anchor_also_voted,
            "anchorSourceCounts": src_counts,
            "servedRowsMovedByCorridor": len(moved),
            "bucketP90": {k: _q(v, 0.90) for k, v in drifts_by_bucket.items()},
            "bucketN": {k: len(v) for k, v in drifts_by_bucket.items()},
            "overallP90": _q(overall, 0.90),
        },
    }
    (OUT / "b3_corridor_report.json").write_text(json.dumps(payload, indent=1))
    print(f"\nwrote {OUT / 'b3_corridor_report.json'}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pin", action="store_true")
    ap.add_argument("--reproduce", action="store_true")
    args = ap.parse_args()
    if args.pin:
        print(json.dumps(pin(), indent=1))
        return 0
    if args.reproduce:
        reproduce()
        return 0
    ap.error("pass --pin or --reproduce")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
