#!/usr/bin/env python3
"""B4-FINAL — pin, reproduce, and re-verify the boundary on current HEAD.

Separate from ``b4_tail_measure.py`` / ``b4_candidate_measure.py`` on
purpose. Those recorded the BLOCKED experiment, whose conclusion was
"903 is right but landing it drives the B3 market corridor onto rows its
own criteria forbid". The corridor is gone (#799), so that conclusion is
historical and its outputs are historical evidence. They are not edited
here; this harness writes ``b4f_*`` files alongside them.

Nothing here changes production.

  ``--pin``         record the exact B4-final inputs
  ``--reproduce``   measure W30-F023 on the fresh pin
  ``--boundary``    re-verify the candidate boundary against source evidence
  ``--equivalence`` prove the bounded tail is the same function on the head

Three things this harness is careful about, all of which the previous
round got wrong at least once:

**Path-gated population.** W30-F023 is a rank -> percentile -> Hill
defect. A stamped ``effectiveRank`` past the boundary is NOT evidence of
saturation on its own: ``_VALUE_BASED_SOURCES`` price from the raw site
value and never reach ``percentile_to_value``. Counting those inflated
the first headline and mis-attributed the collapse to ``idpTradeCalc``,
whose live contributions are value-direct on every row.

**The counterfactual evaluates the Hill directly.** ``percentile_to_value``
clamps a second time, so feeding it an unclamped coordinate silently
reproduces the saturated answer and the whole measurement becomes a
tautology.

**Saturation is probed behaviourally, not textually.** An earlier version
grepped for two literal clamp expressions and would have reported "no
clamps found" on a tree whose saturation was completely unchanged, the
moment those clamps became calls to the canonical owner.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent
CSV_DIR = ROOT / "CSVs" / "site_raw"

POSITION_BUCKETS = (
    ("QB", {"QB"}),
    ("RB", {"RB"}),
    ("WR", {"WR"}),
    ("TE", {"TE"}),
    ("DL/EDGE", {"DL", "EDGE", "DE", "DT"}),
    ("LB", {"LB"}),
    ("DB", {"DB", "CB", "S"}),
)


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


def bucket_for(position: str, asset_class: str) -> str:
    if asset_class == "pick":
        return "picks"
    pos = (position or "").upper()
    for name, members in POSITION_BUCKETS:
        if pos in members:
            return name
    return "other"


def build(raw: dict):
    from src.api.data_contract import build_api_data_contract

    with contextlib.redirect_stdout(io.StringIO()):
        return build_api_data_contract(raw)


# ── observations ────────────────────────────────────────────────────────


def observations(rows: list[dict]) -> list[dict]:
    """Every per-source stamp on the board, with its path and rank.

    One record per (row, source). ``served`` means the board published a
    consensus rank for the row — the distinction the previous round was
    asked to add, because "rows touched" and "rows a user can see" are
    different numbers.
    """
    out = []
    for r in rows:
        meta = r.get("sourceRankMeta")
        if not isinstance(meta, dict):
            continue
        served = r.get("canonicalConsensusRank") is not None
        for key, m in meta.items():
            if not isinstance(m, dict):
                continue
            eff = m.get("effectiveRank")
            if not isinstance(eff, (int, float)):
                continue
            out.append(
                {
                    "row": str(r.get("displayName")),
                    "source": str(key),
                    "effectiveRank": float(eff),
                    "path": str(m.get("valueContributionPath") or "unknown"),
                    "served": served,
                    "bucket": bucket_for(
                        str(r.get("position") or ""), str(r.get("assetClass") or "")
                    ),
                    "consensusRank": r.get("canonicalConsensusRank"),
                }
            )
    return out


def pin() -> dict:
    from src.api.data_contract import (
        _PERCENTILE_REFERENCE_N,
        _RANKING_SOURCES,
        _VALUE_BASED_SOURCES,
        OVERALL_RANK_LIMIT,
    )
    from src.canonical import tail_policy
    from src.model_registry.hill_masters import MODEL_ID, load_or_seed_registry

    board = latest_board()
    raw = json.loads(board.read_bytes())
    contract = build(raw)
    rows = contract.get("playersArray") or []
    obs = observations(rows)
    rank_hill = [o for o in obs if o["path"] == "rank_hill"]
    served_rows = [r for r in rows if r.get("canonicalConsensusRank") is not None]

    reg = load_or_seed_registry()
    champ = reg.champion
    dirty = [ln.split(maxsplit=1)[-1] for ln in _git("status", "--porcelain").splitlines()]
    return {
        "phase": "B4-final",
        "codeSha": _git("rev-parse", "HEAD"),
        "codeSubject": _git("log", "-1", "--format=%s"),
        "mainTip": _git("rev-parse", "origin/main"),
        "commitsAheadOfMain": _git("log", "--oneline", "origin/main..HEAD").splitlines(),
        # Self-referential unless classified: a run rewrites its own output.
        "dirtyPaths": dirty,
        "dirtyIsEvidenceOnly": all(p.startswith("docs/master-site-audit/evidence/") for p in dirty),
        "corridorMergeSha": "52d48b6e5cf7a5e09a8bf174b6a5af3d191c8719",
        "board": {
            "path": str(board.relative_to(ROOT)),
            "sha256": _sha(board),
            "bytes": board.stat().st_size,
            "scrapeTimestamp": raw.get("scrapeTimestamp"),
            "date": raw.get("date"),
            "playerCount": len(raw.get("players") or {}),
        },
        "sourceCsvs": {
            p.name: {"sha256": _sha(p), "bytes": p.stat().st_size}
            for p in sorted(CSV_DIR.glob("*.csv"))
        },
        "sourceRegistry": [
            {
                "key": str(s.get("key")),
                "depth": s.get("depth"),
                "scope": str(s.get("scope")),
                "valueDirect": str(s.get("key")) in _VALUE_BASED_SOURCES,
            }
            for s in _RANKING_SOURCES
        ],
        "valueDirectSources": sorted(_VALUE_BASED_SOURCES),
        "championModel": {
            "modelId": MODEL_ID,
            "version": champ.version,
            "status": champ.status,
            "params": dict(champ.params),
        },
        "registryVersions": [v.version for v in reg.versions],
        "tailConstants": {
            "PERCENTILE_REFERENCE_N": _PERCENTILE_REFERENCE_N,
            "OVERALL_RANK_LIMIT": OVERALL_RANK_LIMIT,
            "TAIL_SATURATION_RANK": tail_policy.TAIL_SATURATION_RANK,
        },
        "boardShape": {
            "rows": len(rows),
            "servedRows": len(served_rows),
            "observations": len(obs),
            "rankHillObservations": len(rank_hill),
            "deepestEffectiveRank": max((o["effectiveRank"] for o in obs), default=None),
            "deepestRankHillObservation": max(
                (o["effectiveRank"] for o in rank_hill), default=None
            ),
            "deepestEffectiveRankOnServedRow": max(
                (o["effectiveRank"] for o in obs if o["served"]), default=None
            ),
        },
    }


def cmd_pin() -> None:
    snap = pin()
    (OUT / "b4f_pin.json").write_text(json.dumps(snap, indent=1, default=str))
    b, sh = snap["board"], snap["boardShape"]
    print("== B4-FINAL pin ==")
    print(f"  code    {snap['codeSha'][:9]}  ({snap['codeSubject'][:60]})")
    print(f"  main    {snap['mainTip'][:9]}")
    print(f"  corridor removed by  {snap['corridorMergeSha'][:9]}")
    print(
        "  dirty   "
        + (
            "none — clean tree"
            if not snap["dirtyPaths"]
            else f"{len(snap['dirtyPaths'])} path(s), evidence-only={snap['dirtyIsEvidenceOnly']}"
        )
    )
    print(f"  board   {b['path']}")
    print(f"          sha256={b['sha256']}")
    print(f"          {b['bytes']} B  scraped={b['scrapeTimestamp']}  players={b['playerCount']}")
    print(f"  csvs    {len(snap['sourceCsvs'])} hashed")
    print(f"  sources {len(snap['sourceRegistry'])}  value-direct={snap['valueDirectSources']}")
    print(f"  champ   v{snap['championModel']['version']} {snap['championModel']['params']}")
    print(f"  tail    {snap['tailConstants']}")
    print(
        f"  shape   rows={sh['rows']} served={sh['servedRows']} obs={sh['observations']} "
        f"rankHill={sh['rankHillObservations']}"
    )
    print(
        f"          deepest effective rank      {sh['deepestEffectiveRank']}\n"
        f"          deepest rank-Hill rank      {sh['deepestRankHillObservation']}\n"
        f"          deepest on a served row     {sh['deepestEffectiveRankOnServedRow']}"
    )
    print(f"\nwrote {OUT / 'b4f_pin.json'}")


# ── step 3: reproduce ───────────────────────────────────────────────────


def saturation_still_live() -> list[str]:
    """Behavioural probe: do genuinely distinct ranks still price alike?"""
    from src.canonical.player_valuation import percentile_to_value, rank_to_percentile
    from src.canonical.rank_coordinates import RANK_POOL_SHARED_MARKET, curve_for_pool

    c, s = curve_for_pool(RANK_POOL_SHARED_MARKET)
    live = []
    if rank_to_percentile(501.0) == rank_to_percentile(877.0):
        live.append("rank_to_percentile")
    if percentile_to_value(1.0, midpoint=c, slope=s) == percentile_to_value(
        876.0 / 499.0, midpoint=c, slope=s
    ):
        live.append("percentile_to_value")
    return live


def cmd_reproduce(boundary: int) -> None:
    snap = pin()
    raw = json.loads(latest_board().read_bytes())
    contract = build(raw)
    rows = contract.get("playersArray") or []
    obs = observations(rows)

    rank_hill = [o for o in obs if o["path"] == "rank_hill"]
    value_direct = [o for o in obs if o["path"] == "value_direct"]
    past = [o for o in rank_hill if o["effectiveRank"] > boundary]
    vd_past = [o for o in value_direct if o["effectiveRank"] > boundary]

    touched = {o["row"] for o in past}
    touched_served = {o["row"] for o in past if o["served"]}
    touched_unserved = touched - touched_served
    served_rows = {str(r.get("displayName")) for r in rows if r.get("canonicalConsensusRank")}

    print("== B4-FINAL step 3: reproduce W30-F023 on current HEAD ==")
    print(f"   board {snap['board']['path']}  code {snap['codeSha'][:9]}")
    live = saturation_still_live()
    print(f"   saturation observable at: {live}")
    if len(live) < 2:
        print("   !! the tail no longer saturates at both sites — RED is not established")

    print(f"\n-- population (path-gated at rank > {boundary}) --")
    print(f"   total rank-Hill observations          {len(rank_hill)}")
    print(f"   rank-Hill observations past boundary  {len(past)}")
    pct = 100.0 * len(past) / len(rank_hill) if rank_hill else 0.0
    print(f"   percentage of rank-Hill observations  {pct:.2f}%")
    print(f"   distinct rows touched                 {len(touched)}")
    print(f"   ... served                            {len(touched_served)}")
    print(f"   ... unserved                          {len(touched_unserved)}")
    print(f"\n   value-direct observations             {len(value_direct)}")
    print(f"   value-direct past 500                 {len(vd_past)}")
    print("   (value-direct rows are NOT part of the defect: they price from")
    print("    the raw site value and never reach percentile_to_value)")

    print(
        f"\n   deepest effective rank overall        {snap['boardShape']['deepestEffectiveRank']}"
    )
    print(
        f"   deepest rank-Hill effective rank      "
        f"{snap['boardShape']['deepestRankHillObservation']}"
    )
    print(
        f"   deepest consumed by a served row      "
        f"{snap['boardShape']['deepestEffectiveRankOnServedRow']}"
    )

    print("\n-- per-source path mix --")
    mix: dict[str, Counter] = defaultdict(Counter)
    deepest: dict[str, float] = defaultdict(float)
    for o in obs:
        mix[o["source"]][o["path"]] += 1
        deepest[o["source"]] = max(deepest[o["source"]], o["effectiveRank"])
    past_by_source = Counter(o["source"] for o in past)
    print(
        f"   {'source':<26}{'rank_hill':>10}{'value_direct':>14}{'other':>7}{'past':>7}{'max':>7}"
    )
    for src in sorted(mix, key=lambda k: -past_by_source[k]):
        c = mix[src]
        other = sum(v for k, v in c.items() if k not in ("rank_hill", "value_direct"))
        print(
            f"   {src:<26}{c['rank_hill']:>10}{c['value_direct']:>14}{other:>7}"
            f"{past_by_source[src]:>7}{int(deepest[src]):>7}"
        )

    print("\n-- positional concentration of touched rows --")
    by_bucket = Counter()
    by_bucket_served = Counter()
    for name in touched:
        o = next(x for x in past if x["row"] == name)
        by_bucket[o["bucket"]] += 1
        if o["served"]:
            by_bucket_served[o["bucket"]] += 1
    total_rows = len(rows)
    total_served = len(served_rows)
    print(f"   {'bucket':<10}{'rows':>7}{'% all rows':>12}{'served':>8}{'% served':>10}")
    for name in [b[0] for b in POSITION_BUCKETS] + ["picks", "other"]:
        n, ns = by_bucket.get(name, 0), by_bucket_served.get(name, 0)
        if not n and not ns:
            continue
        print(
            f"   {name:<10}{n:>7}{100.0 * n / total_rows:>11.2f}%"
            f"{ns:>8}{100.0 * ns / total_served:>9.2f}%"
        )
    print(
        f"   {'TOTAL':<10}{len(touched):>7}{100.0 * len(touched) / total_rows:>11.2f}%"
        f"{len(touched_served):>8}{100.0 * len(touched_served) / total_served:>9.2f}%"
    )

    report = {
        "pin": snap,
        "boundary": boundary,
        "saturationObservableAt": live,
        "rankHillObservations": len(rank_hill),
        "rankHillPastBoundary": len(past),
        "rankHillPastBoundaryPct": round(pct, 4),
        "rowsTouched": len(touched),
        "rowsTouchedServed": len(touched_served),
        "rowsTouchedUnserved": len(touched_unserved),
        "valueDirectObservations": len(value_direct),
        "valueDirectPastBoundary": len(vd_past),
        "totalRows": total_rows,
        "totalServedRows": total_served,
        "perSourcePathMix": {
            s: {**dict(c), "pastBoundary": past_by_source[s], "deepest": deepest[s]}
            for s, c in mix.items()
        },
        "positionalConcentration": {
            "rows": dict(by_bucket),
            "servedRows": dict(by_bucket_served),
        },
        "touchedRowNames": sorted(touched),
    }
    (OUT / "b4f_reproduce.json").write_text(json.dumps(report, indent=1, default=str))
    print(f"\nwrote {OUT / 'b4f_reproduce.json'}")


# ── step 4: boundary re-verification ────────────────────────────────────


def cmd_boundary() -> None:
    """Is 903 still the deepest evidence-backed source domain?

    Three different questions, deliberately reported apart:

    * what each source DECLARES it publishes (``depth`` in the registry) —
      a list length, not a coordinate;
    * what effective rank is actually OBSERVED today — the ladder
      translation can carry a shallow list to a deep overall coordinate,
      which is why declared depth is not the boundary;
    * what has been observed historically in retained evidence.
    """
    from src.api.data_contract import _RANKING_SOURCES, _VALUE_BASED_SOURCES

    raw = json.loads(latest_board().read_bytes())
    contract = build(raw)
    rows = contract.get("playersArray") or []
    obs = observations(rows)

    declared = {str(s.get("key")): s.get("depth") for s in _RANKING_SOURCES}
    observed: dict[str, float] = defaultdict(float)
    observed_hill: dict[str, float] = defaultdict(float)
    for o in obs:
        observed[o["source"]] = max(observed[o["source"]], o["effectiveRank"])
        if o["path"] == "rank_hill":
            observed_hill[o["source"]] = max(observed_hill[o["source"]], o["effectiveRank"])

    print("== B4-FINAL step 4: re-verify the boundary ==")
    print(f"   {'source':<26}{'declared':>9}{'observed':>10}{'obs(hill)':>11}  path")
    for key in sorted(declared, key=lambda k: -observed.get(k, 0)):
        vd = "value_direct" if key in _VALUE_BASED_SOURCES else "rank_hill"
        print(
            f"   {key:<26}{str(declared[key]):>9}{int(observed.get(key, 0)):>10}"
            f"{int(observed_hill.get(key, 0)):>11}  {vd}"
        )

    deepest_now = max(observed.values(), default=0)
    deepest_hill_now = max(observed_hill.values(), default=0)
    print(f"\n   deepest observed effective rank today      {int(deepest_now)}")
    print(f"   deepest rank-Hill effective rank today     {int(deepest_hill_now)}")

    # ── historical maxima ──
    #
    # Load-bearing, and the reason this section exists at all. A boundary
    # justified as "the deepest rank any source publishes" cannot be
    # decided from ONE board: the quantity moves with source coverage, and
    # on these 17 days it ranges 784..904. An earlier version of this
    # command read only today's board and duly printed "903 still covers
    # everything" — a conclusion the historical evidence refutes.
    historical: dict[str, float] = {}
    for fname in ("b4f_historical_depths.json", "b4f_historical_sensitivity.json"):
        f = OUT / fname
        if not f.is_file():
            continue
        payload = json.loads(f.read_text())
        for rec in payload.get("days") or []:
            historical[str(rec["day"])] = float(rec["deepestEffectiveRank"])

    hist_max = max(historical.values(), default=0.0)
    hist_day = next((d for d, v in historical.items() if v == hist_max), None)
    evidence_max = max(deepest_now, hist_max)

    print(
        f"\n   deepest observed across {len(historical)} retained historical days  "
        f"{int(hist_max) if hist_max else 'none recorded'}"
        + (f"  (on {hist_day})" if hist_day else "")
    )
    print(f"   deepest across ALL retained evidence        {int(evidence_max)}")

    verdict = {
        "declaredDepths": declared,
        "observedMaxEffectiveRank": {k: v for k, v in sorted(observed.items())},
        "observedMaxRankHill": {k: v for k, v in sorted(observed_hill.items())},
        "deepestObservedToday": deepest_now,
        "deepestRankHillToday": deepest_hill_now,
        "historicalDeepestByDay": historical,
        "historicalDeepest": hist_max,
        "historicalDeepestDay": hist_day,
        "evidenceBackedBoundary": evidence_max,
        "priorCandidate": 903,
        "priorCandidateCoversEvidence": evidence_max <= 903,
        "daysExceeding903": sorted(d for d, v in historical.items() if v > 903),
    }
    (OUT / "b4f_boundary.json").write_text(json.dumps(verdict, indent=1, default=str))

    if not historical:
        print(
            "\n   !! no historical evidence loaded — run b4f_historical.py first.\n"
            "      A boundary decided from a single board is not evidence-backed."
        )
    elif verdict["priorCandidateCoversEvidence"]:
        print("\n   903 covers every retained observation — the prior candidate stands")
    else:
        print(
            f"\n   !! 903 does NOT cover the retained evidence: {verdict['daysExceeding903']}\n"
            f"      deepest observed is {int(evidence_max)}. The prior candidate came from a\n"
            f"      COMMENT (src/api/source_history.py:353) with no executable definition and\n"
            f"      no retained measurement behind it. Evidence-backed boundary: {int(evidence_max)}."
        )
    print(f"\nwrote {OUT / 'b4f_boundary.json'}")


# ── step 5: head equivalence ────────────────────────────────────────────


def cmd_equivalence(boundary: int) -> None:
    """The bounded tail must be the SAME function on the supported head.

    A tail-policy change that quietly reshapes the fitted head would be a
    refit wearing a tail-policy label. This evaluates every master curve at
    every integer rank from 1 to the boundary under both policies and
    reports the maximum deviation, which must be exactly zero below the old
    saturation point.
    """
    from src.canonical import tail_policy
    from src.canonical.player_valuation import percentile_to_value, rank_to_percentile
    from src.canonical.rank_coordinates import (
        RANK_POOL_IDP,
        RANK_POOL_OFFENSE,
        RANK_POOL_SHARED_MARKET,
        curve_for_pool,
    )

    pools = (RANK_POOL_SHARED_MARKET, RANK_POOL_OFFENSE, RANK_POOL_IDP)

    def board_value(rank: int, c: float, s: float) -> int:
        return int(round(percentile_to_value(rank_to_percentile(float(rank)), midpoint=c, slope=s)))

    prev = tail_policy.TAIL_SATURATION_RANK
    results = {}
    try:
        for pool in pools:
            c, s = curve_for_pool(pool)
            tail_policy.TAIL_SATURATION_RANK = None
            base = {r: board_value(r, c, s) for r in range(1, boundary + 1)}
            tail_policy.TAIL_SATURATION_RANK = boundary
            cand = {r: board_value(r, c, s) for r in range(1, boundary + 1)}

            # The head is everything up to the OLD saturation point.
            head_max = 0
            head_arg = None
            tail_changed = 0
            for r in range(1, boundary + 1):
                d = abs(cand[r] - base[r])
                if r <= 500:
                    if d > head_max:
                        head_max, head_arg = d, r
                elif d:
                    tail_changed += 1
            distinct_base = len({base[r] for r in range(501, boundary + 1)})
            distinct_cand = len({cand[r] for r in range(501, boundary + 1)})
            results[pool] = {
                "curve": {"midpoint": c, "slope": s},
                "maxHeadDeviation": head_max,
                "maxHeadDeviationAtRank": head_arg,
                "tailRanksChanged": tail_changed,
                "distinctValuesInTailBefore": distinct_base,
                "distinctValuesInTailAfter": distinct_cand,
                "midpointRankSpace": c * (500 - 1),
            }
    finally:
        tail_policy.TAIL_SATURATION_RANK = prev

    print("== B4-FINAL step 5: head equivalence ==")
    print(f"   boundary={boundary}; head defined as ranks 1..500 (the OLD saturation point)")
    print(
        f"   {'pool':<18}{'max head Δ':>11}{'at rank':>9}{'tail Δ':>8}"
        f"{'distinct before':>17}{'after':>7}{'M = c(N-1)':>12}"
    )
    ok = True
    for pool, r in results.items():
        ok = ok and r["maxHeadDeviation"] == 0
        print(
            f"   {pool:<18}{r['maxHeadDeviation']:>11}{str(r['maxHeadDeviationAtRank']):>9}"
            f"{r['tailRanksChanged']:>8}{r['distinctValuesInTailBefore']:>17}"
            f"{r['distinctValuesInTailAfter']:>7}{r['midpointRankSpace']:>12.2f}"
        )
    print(
        f"\n   head preserved exactly on every master: {ok}"
        + ("" if ok else "  !! a head deviation means this is a refit, not a tail policy")
    )
    (OUT / "b4f_equivalence.json").write_text(
        json.dumps({"boundary": boundary, "pools": results, "headPreserved": ok}, indent=1)
    )
    print(f"\nwrote {OUT / 'b4f_equivalence.json'}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pin", action="store_true")
    ap.add_argument("--reproduce", action="store_true")
    ap.add_argument("--boundary", action="store_true")
    ap.add_argument("--equivalence", action="store_true")
    ap.add_argument("--at", type=int, default=500, help="current saturation boundary")
    ap.add_argument("--candidate", type=int, default=903)
    args = ap.parse_args()
    if not any((args.pin, args.reproduce, args.boundary, args.equivalence)):
        ap.error("pass at least one of --pin/--reproduce/--boundary/--equivalence")
    if args.pin:
        cmd_pin()
    if args.reproduce:
        cmd_reproduce(args.at)
    if args.boundary:
        cmd_boundary()
    if args.equivalence:
        cmd_equivalence(args.candidate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
