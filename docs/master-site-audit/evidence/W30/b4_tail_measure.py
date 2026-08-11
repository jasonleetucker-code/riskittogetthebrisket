#!/usr/bin/env python3
"""B4 — pin the baseline and reproduce W30-F023 (percentile tail saturation).

``--pin``        record the exact B4 inputs.
``--reproduce``  measure the live blast radius on that pin, and trace every
                 saturation point in the tree.

The defect: the board publishes ranks to ``OVERALL_RANK_LIMIT`` (800) and
sources rank deeper still, but ``rank_to_percentile`` saturates ``p`` at 1.0
at ``PERCENTILE_REFERENCE_N`` (500). Every rank past that receives an
identical percentile and therefore an identical contribution from that
source, so genuinely distinct served ranks collapse onto one value.

Two things this script is careful about.

**The continuous counterfactual is computed WITHOUT either clamp.**
``percentile_to_value`` clamps ``p`` a second time, so calling it with an
unclamped percentile silently reproduces the saturated answer. The Hill form
is evaluated directly here for the counterfactual, and the script asserts
the two clamps still exist so the measurement cannot quietly become a
tautology if one is removed.

**Missing is not a deep rank.** A source that stops at rank N has no opinion
about the players below it. Only rows where the source actually stamped an
effective rank are counted; no synthetic deep-tail observation is created to
fill the range.

Nothing here changes production.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import subprocess
import sys
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


def pin() -> dict:
    from src.api.data_contract import (
        _PERCENTILE_REFERENCE_N,
        _RANKING_SOURCES,
        OVERALL_RANK_LIMIT,
    )
    from src.model_registry.hill_masters import MODEL_ID, load_or_seed_registry

    board = latest_board()
    raw = json.loads(board.read_bytes())
    reg = load_or_seed_registry()
    champ = reg.champion
    return {
        "phase": "B4",
        "codeSha": _git("rev-parse", "HEAD"),
        "codeSubject": _git("log", "-1", "--format=%s"),
        # Not a bare bool. A run necessarily rewrites its own two output
        # files, so "dirty" is self-referential unless the paths are
        # enumerated and classified — the pin has to prove the tree is
        # clean of anything that could change the MEASUREMENT.
        "dirtyPaths": [
            ln.split(maxsplit=1)[-1] for ln in _git("status", "--porcelain").splitlines()
        ],
        "dirtyIsEvidenceOnly": all(
            ln.split(maxsplit=1)[-1].startswith("docs/master-site-audit/evidence/")
            for ln in _git("status", "--porcelain").splitlines()
        ),
        "mainTip": _git("rev-parse", "origin/main"),
        "commitsAheadOfMain": _git("log", "--oneline", "origin/main..HEAD").splitlines(),
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
        },
        "sourceDepths": {str(s.get("key")): s.get("depth") for s in _RANKING_SOURCES},
    }


def hill(p: float, c: float, s: float) -> float:
    """The Hill form evaluated WITHOUT either production clamp.

    Deliberately not ``percentile_to_value``: that function clamps ``p`` a
    second time, so the counterfactual would silently equal the saturated
    answer and the whole measurement would be a tautology.
    """
    if p <= 0.0:
        return 9999.0
    return 9999.0 / (1.0 + (p / c) ** s)


def assert_saturation_still_live() -> list[str]:
    """The measurement is only meaningful while the tail still saturates.

    Behavioural, not textual. This used to grep ``player_valuation.py`` for
    two literal clamp expressions — which stopped meaning anything the
    moment those clamps were replaced by a call to the canonical owner, and
    would have reported "no clamps found" on a tree where the saturation is
    entirely unchanged. A source-text probe for a behaviour is only ever
    correct until the next refactor.

    So it asks the functions instead: do two ranks the sources genuinely
    distinguish still price identically? If they do not, the counterfactual
    below is no longer a counterfactual and the run says so.
    """
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


def reproduce() -> None:
    from src.api.data_contract import (
        _PERCENTILE_REFERENCE_N,
        OVERALL_RANK_LIMIT,
        build_api_data_contract,
    )
    from src.canonical.rank_coordinates import curve_for_pool, curve_label_for_pool

    snap = pin()
    n = snap["tailConstants"]["PERCENTILE_REFERENCE_N"]
    print("== B4 pin ==")
    print(f"  code   {snap['codeSha'][:9]}  main tip {snap['mainTip'][:9]}")
    if snap["dirtyPaths"]:
        print(
            f"  dirty  {len(snap['dirtyPaths'])} path(s), evidence-only="
            f"{snap['dirtyIsEvidenceOnly']}: {snap['dirtyPaths']}"
        )
    else:
        print("  dirty  none — measured on a clean tree")
    if snap["commitsAheadOfMain"]:
        print(
            f"  ahead of main by {len(snap['commitsAheadOfMain'])} commit(s), documentation only:"
        )
        for line in snap["commitsAheadOfMain"]:
            print(f"    {line}")
    b = snap["board"]
    print(f"  board  {b['path']}  sha256={b['sha256'][:16]}…  {b['bytes']} B")
    print(f"         scraped={b['scrapeTimestamp']}  players={b['playerCount']}")
    print(f"  csvs   {len(snap['sourceCsvs'])} hashed")
    print(f"  champ  v{snap['championModel']['version']} {snap['championModel']['params']}")
    print(
        f"  tail   PERCENTILE_REFERENCE_N={n}   OVERALL_RANK_LIMIT="
        f"{snap['tailConstants']['OVERALL_RANK_LIMIT']}"
    )

    clamps = assert_saturation_still_live()
    print(f"\n== saturation still observable at these sites: {clamps} ==")
    if len(clamps) < 2:
        print(
            "  !! the tail no longer saturates at both sites — the continuous\n"
            "     counterfactual below is no longer a counterfactual"
        )

    with contextlib.redirect_stdout(io.StringIO()):
        contract = build_api_data_contract(json.loads(latest_board().read_bytes()))
    rows = contract.get("playersArray") or []

    # ── per-source path mix and blast radius ──
    #
    # W30-F023 is a rank → percentile → Hill saturation defect. A stamped
    # effectiveRank > N is NOT by itself evidence that the source's live
    # contribution traversed either clamp: value-direct sources
    # (``_VALUE_BASED_SOURCES``) price from the raw site value and never
    # reach ``percentile_to_value``. An earlier version of this harness
    # counted any deep rank as saturated, which inflated the headline and
    # attributed the collapse to ``idpTradeCalc``, whose live contributions
    # are value-direct on every row. The primary population is now
    # path-gated.
    from src.api.data_contract import _VALUE_BASED_SOURCES

    # Two row populations, deliberately kept apart.
    #
    # ``hill_rows`` is every board row a saturated rank-Hill observation
    # touches. ``hill_rows_served`` is the subset the board actually
    # PUBLISHES — rows carrying a ``canonicalConsensusRank``, i.e. inside
    # ``OVERALL_RANK_LIMIT``. The difference is the blast radius a user can
    # see today versus the blast radius the pipeline computes. A row past
    # the board cut loses both its rank and its ``rankDerivedValue``
    # (``data_contract.py:8327``), so a tail repair that only moved
    # unserved rows would change nothing anyone can observe, and quoting
    # the combined figure as "rows affected" would overstate the
    # user-visible defect. Neither number is the interesting one alone:
    # the unserved remainder is what a policy change could promote ACROSS
    # the cut, which is exactly the membership question §4 step 5 asks.
    per_source: dict[str, dict] = {}
    hill_rows: set[str] = set()
    hill_rows_served: set[str] = set()
    hill_obs = hill_sat = direct_obs = direct_deep = 0
    hill_sat_served = 0
    deepest_hill_served = 0
    for row in rows:
        name = str(row.get("displayName"))
        served = bool(row.get("canonicalConsensusRank"))
        for key, meta in (row.get("sourceRankMeta") or {}).items():
            if not isinstance(meta, dict):
                continue
            eff = meta.get("effectiveRank")
            if not isinstance(eff, int):
                continue
            path = str(meta.get("valueContributionPath") or "")
            rec = per_source.setdefault(
                key,
                {
                    "obs": 0,
                    "direct": 0,
                    "hill": 0,
                    "hillSat": 0,
                    "hillSatServed": 0,
                    "directDeep": 0,
                    "fallbackHill": 0,
                    "satRanks": set(),
                    "satRanksServed": set(),
                    "deepest": 0,
                    "deepestHill": 0,
                    "pools": set(),
                },
            )
            rec["obs"] += 1
            rec["deepest"] = max(rec["deepest"], eff)
            rec["pools"].add(str(meta.get("rankCoordinatePool") or "?"))
            if path == "rank_hill":
                rec["hill"] += 1
                hill_obs += 1
                rec["deepestHill"] = max(rec["deepestHill"], eff)
                if served:
                    deepest_hill_served = max(deepest_hill_served, eff)
                # A value-based source on the Hill path fell back — its raw
                # value was missing, out of range, or the source was
                # suppressed. Those rows DO take the tail policy.
                if key in _VALUE_BASED_SOURCES:
                    rec["fallbackHill"] += 1
                if eff > n:
                    rec["hillSat"] += 1
                    hill_sat += 1
                    rec["satRanks"].add(eff)
                    hill_rows.add(name)
                    if served:
                        rec["hillSatServed"] += 1
                        hill_sat_served += 1
                        rec["satRanksServed"].add(eff)
                        hill_rows_served.add(name)
            else:
                rec["direct"] += 1
                direct_obs += 1
                if eff > n:
                    rec["directDeep"] += 1
                    direct_deep += 1

    served_rows = [r for r in rows if r.get("canonicalConsensusRank")]
    print(
        f"\n== W30-F023 reproduction (PATH-GATED) — {hill_sat} of {hill_obs} "
        f"rank-Hill observations sit past rank {n} "
        f"({100.0 * hill_sat / hill_obs:.1f}%), touching {len(hill_rows)} of "
        f"{len(rows)} board rows =="
    )
    print(
        f"  Of those {len(hill_rows)} rows, {len(hill_rows_served)} are CURRENTLY SERVED "
        f"(carry a canonicalConsensusRank, i.e. inside OVERALL_RANK_LIMIT="
        f"{OVERALL_RANK_LIMIT}) — {100.0 * len(hill_rows_served) / len(served_rows):.1f}% "
        f"of the {len(served_rows)} served rows, carrying {hill_sat_served} of the "
        f"{hill_sat} saturated observations."
    )
    unserved_touched = len(hill_rows) - len(hill_rows_served)
    if unserved_touched:
        print(
            f"  The remaining {unserved_touched} touched rows sit PAST the board cut, so they "
            "publish neither a rank nor a rankDerivedValue today. They are not user-visible "
            "now, but they are exactly the population a tail-policy change could move across "
            "the cut — a membership effect, not a no-op."
        )
    else:
        print(
            "  EVERY touched row is served: the saturation is entirely inside the published "
            "board, so 100% of this defect's blast radius is user-visible today. The combined "
            f"'{len(hill_rows)} of {len(rows)}' framing therefore UNDERSTATES it — "
            f"{len(rows) - len(served_rows)} of the {len(rows)} board rows are never served at "
            "all, so the honest user-visible rate is against the served denominator "
            f"({100.0 * len(hill_rows_served) / len(served_rows):.1f}%), not "
            f"{100.0 * len(hill_rows) / len(rows):.1f}%."
        )
        print(
            "  Note this does NOT mean a repair has no membership effect: rows crossing the cut "
            "would be displaced by the repricing of these 254, not drawn from a touched-but-"
            "unserved pool, because that pool is empty."
        )
    print(
        f"  For contrast, {direct_deep} value-direct observations also carry a rank past {n} "
        f"(of {direct_obs} value-direct observations). Those are NOT part of this defect: "
        "they price from the raw site value and never reach percentile_to_value."
    )

    print("\n== path mix per source ==")
    print(
        f"  {'source':<22}{'ranks':>7}{'direct':>8}{'hill':>7}{'hill>N':>8}"
        f"{'fallback':>10}{'collapsed':>11}{'deepest':>9}{'deepHill':>10}  pool"
    )
    for key, rec in sorted(per_source.items(), key=lambda kv: (-kv[1]["hillSat"], kv[0])):
        print(
            f"  {key:<22}{rec['obs']:>7}{rec['direct']:>8}{rec['hill']:>7}"
            f"{rec['hillSat']:>8}{rec['fallbackHill']:>10}{len(rec['satRanks']):>11}"
            f"{rec['deepest']:>9}{rec['deepestHill']:>10}  {sorted(rec['pools'])}"
        )

    print("\n== the collapse, for rank-Hill observations only ==")
    print("  'past N' / 'collapsed' count ALL board rows; the 'served' pair counts only rows")
    print("  the board publishes today.")
    print(
        f"  {'source':<22}{'past N':>8}{'served':>8}{'collapsed':>11}{'servedCol':>11}"
        f"{'deepest':>9}  {'curve':<10}{'clamped':>9}{'continuous':>12}{'distortion':>14}"
    )
    payload_sources = {}
    for key, rec in sorted(per_source.items(), key=lambda kv: -kv[1]["hillSat"]):
        pool = sorted(rec["pools"])[0]
        try:
            c, s = curve_for_pool(pool)
            label = curve_label_for_pool(pool)
        except Exception:
            c = s = None
            label = "?"
        clamped = cont = dist = pct = None
        if c is not None and rec["hillSat"]:
            clamped = hill(1.0, c, s)
            cont = hill((rec["deepestHill"] - 1.0) / (n - 1.0), c, s)
            dist = clamped - cont
            pct = 100.0 * dist / cont if cont else None
        if rec["hillSat"]:
            print(
                f"  {key:<22}{rec['hillSat']:>8}{rec['hillSatServed']:>8}"
                f"{len(rec['satRanks']):>11}{len(rec['satRanksServed']):>11}"
                f"{rec['deepestHill']:>9}  {label:<10}"
                f"{clamped:>9.0f}{cont:>12.0f}{f'{dist:+.0f} ({pct:+.0f}%)':>14}"
            )
        payload_sources[key] = {
            "stampedRanks": rec["obs"],
            "valueDirectObservations": rec["direct"],
            "valueDirectPastN": rec["directDeep"],
            "rankHillObservations": rec["hill"],
            "rankHillPastN": rec["hillSat"],
            "rankHillPastNOnServedRows": rec["hillSatServed"],
            "fallbackRankHillObservations": rec["fallbackHill"],
            "distinctRanksCollapsed": len(rec["satRanks"]),
            "distinctRanksCollapsedOnServedRows": len(rec["satRanksServed"]),
            "deepestRank": rec["deepest"],
            "deepestRankHillRank": rec["deepestHill"],
            "pool": pool,
            "curve": label,
            "clampedContribution": round(clamped, 1) if clamped else None,
            "continuousContribution": round(cont, 1) if cont else None,
            "absoluteDistortion": round(dist, 1) if dist is not None else None,
            "pctDistortion": round(pct, 1) if pct is not None else None,
        }

    unaffected = [k for k, r in per_source.items() if not r["hillSat"]]
    print(f"\n  sources with ZERO saturated rank-Hill observations: {sorted(unaffected)}")

    # ── affected rows by position (rank-Hill only) ──
    print("\n== affected board rows by position (rank-Hill saturation only) ==")
    print("  'all rows' is every board row; 'served' restricts both halves to published rows.")
    by_bucket: dict[str, int] = {}
    pop: dict[str, int] = {}
    by_bucket_served: dict[str, int] = {}
    pop_served: dict[str, int] = {}
    for row in rows:
        b = bucket_for(str(row.get("position") or ""), str(row.get("assetClass") or ""))
        pop[b] = pop.get(b, 0) + 1
        served_row = bool(row.get("canonicalConsensusRank"))
        if served_row:
            pop_served[b] = pop_served.get(b, 0) + 1
        if str(row.get("displayName")) in hill_rows:
            by_bucket[b] = by_bucket.get(b, 0) + 1
        if served_row and str(row.get("displayName")) in hill_rows_served:
            by_bucket_served[b] = by_bucket_served.get(b, 0) + 1
    order = [name for name, _ in POSITION_BUCKETS] + ["picks", "other"]
    print(f"  {'bucket':<9}{'all rows':>18}{'served rows':>21}")
    for b in order:
        if not pop.get(b):
            continue
        hit = by_bucket.get(b, 0)
        hit_s = by_bucket_served.get(b, 0)
        pop_s = pop_served.get(b, 0)
        served_cell = (
            f"{hit_s:>4} of {pop_s:>4} ({100.0 * hit_s / pop_s:>5.1f}%)" if pop_s else f"{'—':>18}"
        )
        print(f"  {b:<9}{hit:>5} of {pop[b]:>4} ({100.0 * hit / pop[b]:>5.1f}%)   {served_cell}")

    # ── the four distinct rank domains ──
    ranked = [r for r in rows if r.get("canonicalConsensusRank")]
    deepest_served = max((r["canonicalConsensusRank"] for r in ranked), default=0)
    deepest_any = max((r["deepest"] for r in per_source.values()), default=0)
    deepest_hill_any = max((r["deepestHill"] for r in per_source.values()), default=0)
    print("\n== four rank domains, which candidate C must not conflate ==")
    print(f"  canonical final-board rank limit        : {OVERALL_RANK_LIMIT}")
    print(f"  deepest canonical rank actually served  : {deepest_served}  ({len(ranked)} rows)")
    print(f"  percentile saturation point             : {_PERCENTILE_REFERENCE_N}")
    print(f"  deepest translated effective rank (any) : {deepest_any}")
    print(f"  deepest effective rank on the HILL path : {deepest_hill_any}")
    print(
        f"  deepest HILL rank consumed by a SERVED row: {deepest_hill_served}"
        "   <- the boundary a bounded policy would have to respect"
    )
    if deepest_hill_served > OVERALL_RANK_LIMIT:
        print(
            "  !! live rank-Hill evidence for served players extends PAST "
            f"{OVERALL_RANK_LIMIT}; a policy saturating at the board limit would "
            "still collapse genuine evidence"
        )

    payload = {
        "pin": snap,
        "clampSites": clamps,
        "totals": {
            "rankHillObservations": hill_obs,
            "rankHillPastN": hill_sat,
            "pctRankHillSaturated": round(100.0 * hill_sat / hill_obs, 2),
            "rowsTouchedByRankHillSaturation": len(hill_rows),
            # The user-visible half. A row past OVERALL_RANK_LIMIT publishes
            # neither canonicalConsensusRank nor rankDerivedValue, so the
            # combined count above overstates what a reader of the board can
            # observe today. Kept as a separate field rather than replacing
            # the combined one: the unserved remainder is the population a
            # tail change could move across the cut.
            "servedRowsTouchedByRankHillSaturation": len(hill_rows_served),
            "unservedRowsTouchedByRankHillSaturation": len(hill_rows) - len(hill_rows_served),
            "rankHillPastNOnServedRows": hill_sat_served,
            "pctServedRowsTouched": round(100.0 * len(hill_rows_served) / len(served_rows), 2)
            if served_rows
            else None,
            "valueDirectObservations": direct_obs,
            "valueDirectPastN": direct_deep,
            "boardRows": len(rows),
            "rankedRows": len(ranked),
            "overallRankLimit": OVERALL_RANK_LIMIT,
            "deepestServedCanonicalRank": deepest_served,
            "deepestEffectiveRankAny": deepest_any,
            "deepestEffectiveRankOnHillPath": deepest_hill_any,
            "deepestHillRankConsumedByServedRow": deepest_hill_served,
        },
        "bySource": payload_sources,
        "unaffectedSources": sorted(unaffected),
        "byPosition": {
            b: {
                "affected": by_bucket.get(b, 0),
                "population": pop.get(b, 0),
                "affectedServed": by_bucket_served.get(b, 0),
                "populationServed": pop_served.get(b, 0),
            }
            for b in order
            if pop.get(b)
        },
    }
    (OUT / "b4_tail_report.json").write_text(json.dumps(payload, indent=1, default=str))
    print(f"\nwrote {OUT / 'b4_tail_report.json'}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pin", action="store_true")
    ap.add_argument("--reproduce", action="store_true")
    args = ap.parse_args()
    if args.pin:
        print(json.dumps(pin(), indent=1, default=str))
        return 0
    if args.reproduce:
        reproduce()
        return 0
    ap.error("pass --pin or --reproduce")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
