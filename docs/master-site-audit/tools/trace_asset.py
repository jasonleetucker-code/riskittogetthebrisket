"""Audit-only: trace one asset from raw source rows to the served contract row.

Answers, for a named player or pick, the question the audit brief asks 24 times:
what did each source say, what did the pipeline do to it, and what number does the
API actually serve? Every number printed is read from a live response or a
committed source CSV — nothing is recomputed from memory.

Usage:
    .venv/bin/python docs/master-site-audit/tools/trace_asset.py "Ja'Marr Chase"
    .venv/bin/python docs/master-site-audit/tools/trace_asset.py --json out.json "Player A" "Player B"
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[3]
SCRATCH = Path(
    "/tmp/claude-0/-home-user-riskittogetthebrisket/"
    "0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad"
)
API = "http://127.0.0.1:8000"
RAW_CSV_DIR = ROOT / "CSVs/site_raw"

_contract_cache: dict | None = None


def cookie() -> dict:
    secret = (SCRATCH / "e2e_secret.txt").read_text().strip()
    r = requests.post(
        f"{API}/api/test/create-session", headers={"Authorization": f"Bearer {secret}"}, timeout=60
    )
    r.raise_for_status()
    return r.cookies.get_dict()


def contract(ck: dict) -> dict:
    global _contract_cache
    if _contract_cache is None:
        r = requests.get(f"{API}/api/data?view=app", cookies=ck, timeout=300)
        r.raise_for_status()
        _contract_cache = r.json()
    return _contract_cache


def raw_source_rows(name: str) -> dict[str, dict]:
    """What each committed source CSV says about this asset, verbatim."""
    hits: dict[str, dict] = {}
    if not RAW_CSV_DIR.exists():
        return hits
    needle = name.lower().replace(".", "").replace("'", "")
    for csv_path in sorted(RAW_CSV_DIR.glob("*.csv")):
        try:
            with csv_path.open(newline="", encoding="utf-8", errors="replace") as fh:
                for row in csv.DictReader(fh):
                    blob = " ".join(str(v) for v in row.values()).lower()
                    if needle in blob.replace(".", "").replace("'", ""):
                        hits[csv_path.stem] = row
                        break
        except Exception as exc:  # noqa: BLE001
            hits[csv_path.stem] = {"_error": str(exc)[:120]}
    return hits


def find_row(payload: dict, name: str) -> dict | None:
    """Find an asset in either contract shape.

    ``?view=app`` serves the LEGACY dict (``players``, keyed by display name,
    underscore-prefixed stamps) and carries no ``playersArray`` at all — the
    array shape only appears in the full view. Both are handled here so a trace
    does not silently return nothing on the view the frontend actually consumes.
    """
    needle = name.lower()
    rows = payload.get("playersArray") or []
    if rows:
        exact = [r for r in rows if str(r.get("displayName", "")).lower() == needle]
        if exact:
            return exact[0]
        partial = [r for r in rows if needle in str(r.get("displayName", "")).lower()]
        if partial:
            return partial[0]

    legacy = payload.get("players") or {}
    for key, row in legacy.items():
        if str(key).lower() == needle:
            return {**row, "displayName": key}
    for key, row in legacy.items():
        if needle in str(key).lower():
            return {**row, "displayName": key}
    return None


PIPELINE_FIELDS = [
    # Four coexisting value fields — the served one is rankDerivedValue, but
    # _finalAdjusted / _composite / _rawComposite / _offenseOnlyFinalAdjusted all
    # sit beside it carrying different numbers. Printing all of them is the point.
    ("_rawComposite", "raw scraper composite"),
    ("_composite", "composite"),
    ("_finalAdjusted", "legacy adjusted (what the finder used to read)"),
    ("_offenseOnlyFinalAdjusted", "offense-only adjusted"),
    ("sourceRanks", "rank each source gave it"),
    ("sourceOriginalRanks", "pre-normalization source ranks"),
    ("effectiveSourceRanks", "ranks actually used after Hampel/ejection"),
    ("droppedSources", "sources ejected as outliers"),
    ("canonicalSiteValues", "per-source values on the canonical scale"),
    ("sourceCount", "surviving source count"),
    ("isSingleSource", "single-source haircut applied?"),
    ("isStructurallySingleSource", "structurally single-source"),
    ("softFallbackCount", "soft fallback (diagnostic only)"),
    ("blendedSourceRank", "blended rank"),
    ("anchorValue", "hierarchical anchor"),
    ("alphaShrinkage", "alpha shrinkage applied"),
    ("subgroupBlendValue", "subgroup blend"),
    ("subgroupDelta", "subgroup delta"),
    ("_blendedValueUncapped", "blend BEFORE clamps"),
    ("madPenaltyApplied", "MAD penalty (retired, expect 0/False)"),
    ("hillValueSpread", "hill spread"),
    ("sourceSpread", "source spread (diagnostic)"),
    ("rankDerivedValue", ">>> THE SERVED VALUE <<<"),
    # The array shape stamps `canonicalConsensusRank`; the legacy dict that
    # ?view=app actually serves stamps `_canonicalConsensusRank`. Print both.
    ("canonicalConsensusRank", ">>> THE SERVED RANK (array shape) <<<"),
    ("_canonicalConsensusRank", ">>> THE SERVED RANK (legacy dict shape) <<<"),
    ("canonicalTierId", "tier"),
    ("confidenceBucket", "confidence bucket"),
    ("confidenceLabel", "confidence label"),
    ("marketConfidence", "market confidence"),
    ("marketGapDirection", "market gap direction"),
    ("marketGapMagnitude", "market gap magnitude"),
    ("quarantined", "quarantined?"),
    ("anomalyFlags", "anomaly flags"),
    ("identityMethod", "how identity was resolved"),
    ("identityConfidence", "identity confidence"),
    ("assetClass", "asset class"),
    ("rookie", "rookie?"),
]


def trace(name: str, ck: dict) -> dict:
    payload = contract(ck)
    row = find_row(payload, name)
    out: dict = {"query": name, "found": bool(row)}
    print(f"\n{'=' * 78}\nTRACE: {name}\n{'=' * 78}")
    if not row:
        print("  NOT FOUND in playersArray — the board does not carry this asset.")
        return out

    out["displayName"] = row.get("displayName")
    out["position"] = row.get("position")
    out["team"] = row.get("team")
    out["playerId"] = row.get("playerId")
    print(
        f"  {row.get('displayName')}  pos={row.get('position')} team={row.get('team')} "
        f"playerId={row.get('playerId')!r} assetClass={row.get('assetClass')}"
    )

    print("\n  --- STAGE 1: what the raw committed source CSVs say ---")
    raws = raw_source_rows(str(row.get("displayName") or name))
    out["rawSources"] = raws
    if not raws:
        print("    (no committed CSV row matched)")
    for src, r in raws.items():
        keep = {k: v for k, v in r.items() if k and v not in (None, "")}
        print(f"    {src:16} {json.dumps(keep)[:150]}")

    print("\n  --- STAGE 2: pipeline fields on the served row ---")
    stages = {}
    for field, label in PIPELINE_FIELDS:
        if field in row:
            val = row[field]
            stages[field] = val
            shown = json.dumps(val) if isinstance(val, (dict, list)) else val
            print(f"    {field:32} = {str(shown)[:120]}   ({label})")
    out["pipeline"] = stages

    print("\n  --- STAGE 3: what other surfaces serve for the same asset ---")
    cross = {}
    try:
        lg = requests.get(f"{API}/api/valuation/league-adjusted", cookies=ck, timeout=120).json()
        entries = lg.get("ranks") or lg.get("players") or {}
        if isinstance(entries, dict):
            hit = entries.get(str(row.get("displayName")))
            cross["leagueAdjusted"] = hit
            print(f"    league-adjusted overlay: {json.dumps(hit)[:160] if hit else 'absent'}")
    except Exception as exc:  # noqa: BLE001
        cross["leagueAdjusted"] = f"error: {exc}"
        print(f"    league-adjusted overlay: error {exc}")
    out["crossSurface"] = cross
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+")
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args()
    ck = cookie()
    results = [trace(n, ck) for n in args.names]
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(results, indent=1))
        print(f"\nwrote {args.json_out}")


if __name__ == "__main__":
    main()
