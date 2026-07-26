#!/usr/bin/env python3
"""Audit source-CSV → player-pool identity matching across all sources.

For every source CSV registered in
``src.api.data_contract._SOURCE_CSV_PATHS`` this script replays the
exact join the live contract build performs (same parser, same
``_canonical_match_key`` cascade, same position-group pool that
``_enrich_from_source_csvs`` builds via ``row_groups_by_key``) and
reports, per source:

  * total raw CSV rows and rows the parser accepted
  * rows whose canonical key matches a player-pool row (name join)
  * rows recovered ONLY by the sleeper_id join (name drift the
    canonical cascade missed — e.g. PFK "Kenneth Gainwell" vs
    Sleeper "Kenny Gainwell")
  * unmatched rows, each with a best-guess fuzzy near-miss against
    the pool (rapidfuzz when installed, difflib otherwise) so a human
    can triage TRUE aliases vs genuinely-absent players

It also runs an **alias collision-delta check**: the
``CANONICAL_NAME_ALIASES`` table must never merge two DISTINCT pool
players onto one canonical key.  For every pool row we compute the
pre-alias key (``normalize_player_name`` + position group) and the
post-alias key (``canonical_player_key``); any post-alias key that
absorbs more than one pre-alias key is reported as an
alias-introduced collision.  ``tests/utils/test_name_clean.py`` pins
this set empty against the committed exports.

This is an AUDIT, not a gate: the script always exits 0 (unless the
payload itself cannot be loaded).

Usage:
    python scripts/audit_identity_matches.py [--json-path PATH]
                                             [--json OUT.json]
                                             [--near-miss-cutoff 0.84]
                                             [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.api.data_contract import (  # noqa: E402
    _SOURCE_CSV_PATHS,
    _canonical_match_key,
    _derive_current_draft_year_from_names,
    _derive_player_row,
    _inject_far_future_pick_sources,
    _parse_source_csv_cached,
    current_rookie_draft_year,
    set_observed_current_draft_year,
)
from src.utils.name_clean import (  # noqa: E402
    canonical_player_key,
    canonical_position_group,
    normalize_player_name,
)

try:  # optional accelerator — requirements do not pin it
    from rapidfuzz import fuzz as _rapidfuzz  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - environment-dependent
    _rapidfuzz = None

if _rapidfuzz is None:
    from difflib import SequenceMatcher

    def _similarity(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio()
else:  # pragma: no cover - environment-dependent

    def _similarity(a: str, b: str) -> float:
        return _rapidfuzz.ratio(a, b) / 100.0


_PICK_NAME_RE = re.compile(r"^\d{4}\s+(pick|round|[1-6](st|nd|rd|th)?)\b", re.IGNORECASE)


def _load_payload(json_path: str | None) -> tuple[Path, dict[str, Any]]:
    if json_path:
        p = Path(json_path)
        if not p.exists():
            print(f"ERROR: payload not found: {p}", file=sys.stderr)
            sys.exit(1)
    else:
        candidates = sorted((REPO / "exports" / "latest").glob("dynasty_data_*.json"))
        for extra in (
            REPO / "exports" / "latest" / "dynasty_data.json",
            REPO / "data" / "latest.json",
        ):
            if extra.exists():
                candidates.append(extra)
        if not candidates:
            print(
                "ERROR: no exports/latest/dynasty_data_*.json found; pass --json-path.",
                file=sys.stderr,
            )
            sys.exit(1)
        p = candidates[-1]
    with p.open("r", encoding="utf-8") as f:
        return p, json.load(f)


def _build_pool(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the player-row pool the same way ``build_api_data_contract``
    does before calling ``_enrich_from_source_csvs``.

    Mirrors the pre-enrichment steps: draft-year derivation, far-future
    pick injection, then ``_derive_player_row`` per player.
    """
    players_by_name = dict(payload.get("players") or {})
    set_observed_current_draft_year(_derive_current_draft_year_from_names(players_by_name.keys()))
    _inject_far_future_pick_sources(players_by_name, current_rookie_draft_year())

    sleeper = payload.get("sleeper") or {}
    pos_map = sleeper.get("positions") if isinstance(sleeper, dict) else {}
    if not isinstance(pos_map, dict):
        pos_map = {}
    sites = payload.get("sites")
    site_keys = (
        [str(s.get("key")) for s in sites if isinstance(s, dict) and s.get("key")]
        if isinstance(sites, list)
        else []
    )

    rows: list[dict[str, Any]] = []
    for name in sorted(players_by_name.keys(), key=lambda x: str(x).lower()):
        p_data = players_by_name.get(name)
        if not isinstance(p_data, dict):
            continue
        rows.append(_derive_player_row(str(name), p_data, pos_map, site_keys))
    return rows


def _count_csv_rows(csv_path: Path) -> int:
    try:
        with csv_path.open("r", encoding="utf-8-sig") as f:
            return sum(1 for _ in csv.DictReader(f))
    except Exception:  # noqa: BLE001 — count is informational only
        return 0


def alias_collision_delta(pool_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return alias-introduced collisions among distinct pool players.

    A collision is a post-alias ``canonical_player_key`` that absorbs
    more than one distinct pre-alias key (``normalize_player_name`` +
    position group).  The alias table must be collision-free: each
    entry may only re-label a name, never merge two real pool rows.
    """
    post_to_pre: dict[str, dict[str, list[str]]] = {}
    for row in pool_rows:
        nm = str(row.get("canonicalName") or row.get("displayName") or "")
        if not nm:
            continue
        grp = canonical_position_group(row.get("position"))
        pre_key = f"{normalize_player_name(nm)}::{grp}"
        post_key = canonical_player_key(nm, row.get("position"))
        if not post_key:
            continue
        post_to_pre.setdefault(post_key, {}).setdefault(pre_key, []).append(nm)

    collisions: list[dict[str, Any]] = []
    for post_key, pre_map in sorted(post_to_pre.items()):
        if len(pre_map) > 1:
            collisions.append(
                {
                    "canonicalKey": post_key,
                    "mergedNames": sorted(nm for names in pre_map.values() for nm in names),
                    "preAliasKeys": sorted(pre_map.keys()),
                }
            )
    return collisions


def audit_sources(
    pool_rows: list[dict[str, Any]],
    *,
    near_miss_cutoff: float = 0.84,
    fuzzy_floor: float = 0.60,
) -> dict[str, Any]:
    """Run the per-source match audit against ``pool_rows``."""
    # Pool indexes — mirrors row_groups_by_key in _enrich_from_source_csvs.
    row_groups_by_key: dict[str, set[str]] = {}
    pool_names_by_key: dict[str, set[str]] = {}
    pool_ids: dict[str, str] = {}
    for row in pool_rows:
        nm = str(row.get("canonicalName") or row.get("displayName") or "")
        if not nm:
            continue
        cname = _canonical_match_key(nm)
        if not cname:
            continue
        grp = canonical_position_group(row.get("position"))
        row_groups_by_key.setdefault(cname, set()).add(grp)
        pool_names_by_key.setdefault(cname, set()).add(nm)
        sid = str(row.get("playerId") or "").strip()
        if sid:
            pool_ids[sid] = nm

    pool_keys = list(row_groups_by_key.keys())

    sources: dict[str, Any] = {}
    for source_key, cfg in _SOURCE_CSV_PATHS.items():
        if isinstance(cfg, str):
            csv_rel, signal = cfg, "value"
        elif isinstance(cfg, dict):
            csv_rel = str(cfg.get("path") or "")
            signal = str(cfg.get("signal") or "value").lower()
        else:
            continue
        if not csv_rel:
            continue
        csv_path = REPO / csv_rel
        if not csv_path.exists():
            sources[source_key] = {"path": csv_rel, "error": "file_not_found"}
            continue
        csv_lookup, schema_err = _parse_source_csv_cached(csv_path, source_key, signal, csv_rel)
        if schema_err is not None:
            sources[source_key] = {"path": csv_rel, "error": schema_err.get("error")}
            continue

        raw_rows = _count_csv_rows(csv_path)
        parsed_rows = sum(len(v) for v in csv_lookup.values())
        matched_rows = 0
        matched_keys = 0
        id_matched_rows = 0
        unmatched: list[dict[str, Any]] = []
        for cname, entries in sorted(csv_lookup.items()):
            if cname in row_groups_by_key:
                matched_keys += 1
                matched_rows += len(entries)
                continue
            # Name join failed — try the sleeper_id join the enrichment
            # loop performs first (only CSVs that carry sleeper_id).
            sid_hits = [e for e in entries if e[4] and str(e[4]) in pool_ids]
            if sid_hits:
                id_matched_rows += len(sid_hits)
            leftover = [e for e in entries if not (e[4] and str(e[4]) in pool_ids)]
            for entry in leftover:
                display = str(entry[0])
                is_pick = bool(_PICK_NAME_RE.match(display))
                best: list[dict[str, Any]] = []
                if not is_pick:
                    scored = sorted(
                        ((k, _similarity(cname, k)) for k in pool_keys),
                        key=lambda t: -t[1],
                    )[:3]
                    best = [
                        {
                            "poolKey": k,
                            "poolNames": sorted(pool_names_by_key.get(k, set())),
                            "groups": sorted(row_groups_by_key.get(k, set())),
                            "score": round(score, 4),
                        }
                        for k, score in scored
                        if score >= fuzzy_floor
                    ]
                top_score = best[0]["score"] if best else 0.0
                category = (
                    "pick"
                    if is_pick
                    else ("near_miss" if top_score >= near_miss_cutoff else "no_close_match")
                )
                unmatched.append(
                    {
                        "sourceName": display,
                        "canonicalKey": cname,
                        "sleeperId": entry[4],
                        "category": category,
                        "nearMisses": best,
                    }
                )
        total_considered = matched_rows + id_matched_rows + len(unmatched)
        sources[source_key] = {
            "path": csv_rel,
            "signal": signal,
            "csvRows": raw_rows,
            "parsedRows": parsed_rows,
            "matchedRows": matched_rows,
            "matchedKeys": matched_keys,
            "idOnlyMatchedRows": id_matched_rows,
            "unmatchedRows": len(unmatched),
            "matchRate": (
                round((matched_rows + id_matched_rows) / total_considered, 4)
                if total_considered
                else None
            ),
            "unmatched": sorted(
                unmatched,
                key=lambda u: -(u["nearMisses"][0]["score"] if u["nearMisses"] else 0.0),
            ),
        }

    return {
        "poolRows": len(pool_rows),
        "poolKeys": len(pool_keys),
        "sources": sources,
    }


def build_report(
    payload: dict[str, Any],
    *,
    near_miss_cutoff: float = 0.84,
) -> dict[str, Any]:
    pool_rows = _build_pool(payload)
    report = audit_sources(pool_rows, near_miss_cutoff=near_miss_cutoff)
    report["aliasCollisions"] = alias_collision_delta(pool_rows)
    report["generatedAt"] = datetime.now(timezone.utc).isoformat()
    return report


def _print_human(report: dict[str, Any], *, limit: int) -> None:
    print(f"Pool: {report['poolRows']} rows / {report['poolKeys']} canonical keys")
    print()
    header = f"{'source':<24}{'csv':>6}{'parsed':>8}{'match':>7}{'id':>5}{'unmat':>7}{'rate':>8}"
    print(header)
    print("-" * len(header))
    for key, info in report["sources"].items():
        if "error" in info:
            print(f"{key:<24}  ERROR: {info['error']} ({info['path']})")
            continue
        rate = info["matchRate"]
        print(
            f"{key:<24}{info['csvRows']:>6}{info['parsedRows']:>8}"
            f"{info['matchedRows']:>7}{info['idOnlyMatchedRows']:>5}"
            f"{info['unmatchedRows']:>7}"
            f"{('' if rate is None else format(rate * 100, '.1f') + '%'):>8}"
        )
    print()
    for key, info in report["sources"].items():
        unmatched = info.get("unmatched") or []
        if not unmatched:
            continue
        print(f"── {key}: {len(unmatched)} unmatched ──")
        for u in unmatched[:limit]:
            best = u["nearMisses"][0] if u["nearMisses"] else None
            if best:
                print(
                    f"  [{u['category']:<14}] {u['sourceName']!r} → "
                    f"{best['poolNames']} ({'/'.join(best['groups'])}) "
                    f"score={best['score']}"
                )
            else:
                print(f"  [{u['category']:<14}] {u['sourceName']!r} → no candidate")
        if len(unmatched) > limit:
            print(f"  ... {len(unmatched) - limit} more")
        print()
    collisions = report.get("aliasCollisions") or []
    if collisions:
        print(f"!! ALIAS-INTRODUCED COLLISIONS: {len(collisions)}")
        for c in collisions:
            print(f"  {c['canonicalKey']}: merges {c['mergedNames']}")
    else:
        print("Alias collision-delta check: clean (0 alias-introduced pool collisions)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--json-path", help="raw dynasty_data payload JSON (default: newest export)")
    ap.add_argument("--json", dest="json_out", help="write the full machine-readable report here")
    ap.add_argument(
        "--near-miss-cutoff",
        type=float,
        default=0.84,
        help="similarity at/above which an unmatched row is flagged near_miss (default 0.84)",
    )
    ap.add_argument(
        "--limit", type=int, default=15, help="max unmatched rows printed per source (default 15)"
    )
    args = ap.parse_args()

    path, payload = _load_payload(args.json_path)
    print(f"Loading: {path}")
    report = build_report(payload, near_miss_cutoff=args.near_miss_cutoff)
    report["payload"] = str(path)
    _print_human(report, limit=args.limit)
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"\nJSON report written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
