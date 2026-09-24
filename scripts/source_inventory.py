#!/usr/bin/env python3
"""Authoritative inventory of every valuation source we ingest, and what votes.

Answers "what exactly goes into our final dynasty values?" from the LIVE
registries and a built contract, never from prose, so it cannot drift:

* every key in ``_RANKING_SOURCES`` (registered voters), ``_SOURCE_CSV_PATHS``
  (loaded CSVs), ``_NON_VOTING_SOURCE_CSV_KEYS``, the retired-family map, and
  every ``CSVs/site_raw/*.csv`` on disk — the union, so an ingested file that
  nothing registers is listed rather than invisible;
* per source: role, scope, signal, translation, game type, correlation family,
  base weight and the freshness × health × coverage state the server uses
  (``src.sources.freshness.load_source_weightings``);
* per source, from the contract: rows observed, rows where it actually voted,
  rows it lost to its family head, Hampel drops and freshness exclusions, split
  by position group, current-class rookies and picks.

Usage::

    python scripts/source_inventory.py                 # markdown to stdout
    python scripts/source_inventory.py --json out.json
    python scripts/source_inventory.py --markdown docs/sources/SOURCE_INVENTORY.md

Exit 0 on success, 2 when no raw payload is available to build a contract.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

POSITION_GROUPS = {
    "QB": "QB",
    "RB": "RB",
    "WR": "WR",
    "TE": "TE",
    "DL": "DL",
    "DE": "DL",
    "DT": "DL",
    "EDGE": "DL",
    "LB": "LB",
    "DB": "DB",
    "CB": "DB",
    "S": "DB",
}
COVERAGE_COLUMNS = ("QB", "RB", "WR", "TE", "DL", "LB", "DB", "ROOKIE", "PICK")

# Files present in CSVs/site_raw that are deliberately NOT dynasty voters.  The
# reason is data, stated once here and printed, so "why isn't X voting" has an
# answer on the page instead of in someone's memory.
KNOWN_NON_VOTING_REASONS: dict[str, str] = {
    "ktcCrowdTradesSfTep": "KTC Market — benchmark only (src/sources/ktc_market.py); never a vote",
    "ktcSfTep": "mirror of KTC Crowd (TE++ board, identical values) — voting would double-count KTC Crowd",
    "ktc": "KTC Crowd at base (non-TEP) calibration — same crowd opinion, a calibration state not a vote",
    "idpShow": "IDP-only cut of idpShowCombined (same vendor board) — voting would double-count IDP Show",
    "draftSharksRosSf": "rest-of-season (redraft) board — seasonal lane only; barred from dynasty values",
    "draftSharksRosIdp": "rest-of-season (redraft) board — seasonal lane only; barred from dynasty values",
}


def _latest_raw_payload() -> dict[str, Any] | None:
    paths = sorted(glob.glob(str(REPO / "exports" / "latest" / "dynasty_data_*.json")))
    if not paths:
        return None
    return json.loads(Path(paths[-1]).read_text(encoding="utf-8"))


def _position_bucket(row: dict[str, Any]) -> str | None:
    if row.get("assetClass") == "pick":
        return "PICK"
    return POSITION_GROUPS.get(str(row.get("position") or "").upper())


def _coverage(contract: dict[str, Any]) -> dict[str, dict[str, Counter]]:
    """``{source: {"observed"|"voted"|"superseded"|"hampel"|"stale": Counter(col)}}``."""
    out: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    for row in contract.get("playersArray") or []:
        bucket = _position_bucket(row)
        cols = [bucket] if bucket else []
        if row.get("rookie") and row.get("assetClass") != "pick":
            cols.append("ROOKIE")
        meta = row.get("sourceRankMeta") or {}
        excluded = set(row.get("freshnessExcludedSources") or [])
        for key, m in meta.items():
            state = "voted"
            if m.get("hampelDropped"):
                state = "hampel"
            elif m.get("supersededBy"):
                state = "superseded"
            elif key in excluded or not float(m.get("appliedWeight") or 0.0) > 0.0:
                state = "stale"
            for col in cols:
                out[key]["observed"][col] += 1
                out[key][state][col] += 1
    return out


def build_inventory(contract: dict[str, Any], *, state_dir: Path | None = None) -> dict[str, Any]:
    from src.api import data_contract as dc
    from src.sources.freshness import load_source_weightings

    registry = {s["key"]: s for s in dc._RANKING_SOURCES}
    csv_paths = dict(dc._SOURCE_CSV_PATHS)
    retired = dict(getattr(dc, "_RETIRED_SOURCE_CORRELATION_GROUPS", {}))
    # A registered key's file is named by its CSV path, not by the key
    # (``draftSharks`` reads ``draftSharksSf.csv``), so on-disk files are
    # matched by path and only a file NO mapping reads becomes its own row.
    mapped_files = {
        Path(v if isinstance(v, str) else v.get("path", "")).name for v in csv_paths.values()
    }
    unmapped = {
        p.stem for p in (REPO / "CSVs" / "site_raw").glob("*.csv") if p.name not in mapped_files
    }
    keys = sorted(set(registry) | set(csv_paths) | set(retired) | unmapped)

    weightings = load_source_weightings(
        sorted(set(registry) | {"ktcCrowdTradesSfTep"}),
        state_dir=state_dir or (REPO / "data" / "scrape_state"),
        as_of=datetime.now(timezone.utc),
    )
    coverage = _coverage(contract)

    rows = []
    for key in keys:
        src = registry.get(key)
        if src is not None:
            role = "model_input"
            reason = "registered dynasty voter"
        elif key in dc._NON_VOTING_SOURCE_CSV_KEYS or key in KNOWN_NON_VOTING_REASONS:
            role = "benchmark" if key == "ktcCrowdTradesSfTep" else "non_voting"
            reason = KNOWN_NON_VOTING_REASONS.get(key, "declared non-voting")
        elif key in retired:
            role = "retired"
            reason = f"retired; historical family {retired[key]}"
        else:
            role = "UNCLASSIFIED"
            reason = "ingested file with no registry entry and no stated reason — REVIEW"
        w = weightings.get(key)
        subsets = {}
        if w is not None:
            for sub, sw in (getattr(w, "subsets", None) or {}).items():
                subsets[sub] = {
                    "freshness": getattr(sw, "freshness", None),
                    "health": getattr(sw, "health_factor", None),
                    "state": getattr(sw, "state", None),
                    "ageHours": getattr(sw, "age_hours", None),
                    "expectedCadenceHours": getattr(sw, "expected_cadence_hours", None),
                }
        cov = coverage.get(key, {})
        rows.append(
            {
                "key": key,
                "provider": (src or {}).get("display_name"),
                "role": role,
                "reason": reason,
                "scope": (src or {}).get("scope"),
                "signal": "value" if key in dc._VALUE_BASED_SOURCES else ("rank" if src else None),
                "translation": (
                    "rookie_ladder"
                    if (src or {}).get("needs_rookie_translation")
                    else "shared_market_idp"
                    if (src or {}).get("needs_shared_market_translation")
                    else ("direct" if src else None)
                ),
                "gameType": (src or {}).get("game_type"),
                "correlationGroup": dc.correlation_group_for(key) if src else retired.get(key),
                "baseWeight": (src or {}).get("weight"),
                "weighting": subsets,
                "coverage": {state: dict(counter) for state, counter in cov.items()},
            }
        )
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "registeredVoters": len(registry),
        "sources": rows,
    }


def to_markdown(inv: dict[str, Any]) -> str:
    lines = [
        "| source | provider | role | family | scope | signal | translation | base | "
        + " | ".join(f"{c} voted/obs" for c in COVERAGE_COLUMNS)
        + " | reason |",
        "|" + "---|" * (9 + len(COVERAGE_COLUMNS)),
    ]
    for r in inv["sources"]:
        cov = r["coverage"]
        cells = []
        for c in COVERAGE_COLUMNS:
            obs = (cov.get("observed") or {}).get(c, 0)
            voted = (cov.get("voted") or {}).get(c, 0)
            cells.append(f"{voted}/{obs}" if obs else "—")
        lines.append(
            f"| `{r['key']}` | {r['provider'] or '—'} | {r['role']} | {r['correlationGroup'] or '—'} "
            f"| {r['scope'] or '—'} | {r['signal'] or '—'} | {r['translation'] or '—'} "
            f"| {r['baseWeight'] if r['baseWeight'] is not None else '—'} | "
            + " | ".join(cells)
            + f" | {r['reason']} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--markdown", type=Path, default=None)
    ap.add_argument("--state-dir", type=Path, default=None)
    args = ap.parse_args(argv)

    raw = _latest_raw_payload()
    if raw is None:
        print("no exports/latest/dynasty_data_*.json to build a contract from", file=sys.stderr)
        return 2
    from src.api.data_contract import build_api_data_contract

    inv = build_inventory(build_api_data_contract(raw), state_dir=args.state_dir)
    md = to_markdown(inv)
    if args.json:
        args.json.write_text(json.dumps(inv, indent=2, default=str) + "\n", encoding="utf-8")
    if args.markdown:
        args.markdown.write_text(md, encoding="utf-8")
    if not args.json and not args.markdown:
        sys.stdout.write(md)
    unclassified = [r["key"] for r in inv["sources"] if r["role"] == "UNCLASSIFIED"]
    if unclassified:
        print(f"UNCLASSIFIED sources: {unclassified}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
