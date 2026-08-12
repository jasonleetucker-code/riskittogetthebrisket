#!/usr/bin/env python3
"""B5 — canonical identity metrics, before and after.

One harness for every dimension B5 has to report on, so "did identity
repair move something" is answered by re-running one command rather than
by assembling a fresh argument each time.

Deliberately reports UNRESOLVED as its own category everywhere. The point
of this phase is not a higher match rate — a confident wrong match is
worse than an explicit miss — so any metric that could be improved by
matching more aggressively is paired with one that gets worse when the
matching is wrong.

  ``--out NAME``   write ``b5_metrics_NAME.json`` (default ``baseline``)
  ``--compare A B``  diff two previously written snapshots

Nothing here changes production.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import re
import subprocess
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent
CSV_DIR = ROOT / "CSVs" / "site_raw"

SUFFIX_RE = re.compile(r"\b(jr|sr|ii|iii|iv|v)\.?$", re.IGNORECASE)
PUNCT_RE = re.compile(r"[.'\-]")


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def latest_board() -> Path:
    return sorted((ROOT / "exports" / "latest").glob("dynasty_data_*.json"), reverse=True)[0]


def build():
    from src.api.data_contract import build_api_data_contract

    raw = json.loads(latest_board().read_bytes())
    with contextlib.redirect_stdout(io.StringIO()):
        return build_api_data_contract(raw)


def _norm(name: str) -> str:
    from src.utils import normalize_player_name

    return normalize_player_name(name or "")


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def csv_id_columns() -> dict[str, dict]:
    """Which source CSVs ship a provider ID, and whether the loader sees it.

    The alias tuple is imported rather than restated: a copy here would
    keep passing after the production tuple changed, which is the whole
    failure mode W06-F009 is about.
    """
    from src.api import data_contract as dc
    from src.api.data_contract import _SOURCE_CSV_PATHS

    # Read the production resolver, never a copy of it. Before W06-F009
    # this scraped a literal tuple out of the loader's source text, which
    # is exactly the brittleness the repair removed — and it duly went
    # stale the moment the tuple did.
    tokens = sorted(dc._SLEEPER_ID_TOKENS)

    out = {}
    for key, spec in _SOURCE_CSV_PATHS.items():
        rel = spec if isinstance(spec, str) else spec.get("path")
        p = ROOT / str(rel)
        if not p.is_file():
            continue
        hdr = next(csv.reader(p.open(encoding="utf-8-sig")), [])
        idish = [c for c in hdr if "sleeper" in c.lower() or c.lower().endswith("_id")]
        if not idish:
            continue
        rows = sum(1 for _ in p.open(encoding="utf-8-sig")) - 1
        out[key] = {
            "columns": idish,
            "rows": rows,
            "visibleToLoader": [
                c for c in idish if dc._normalize_header_token(c) in dc._SLEEPER_ID_TOKENS
            ],
        }
    return {"acceptedTokens": tokens, "sources": out}


def metrics() -> dict:
    contract = build()
    rows = contract.get("playersArray") or []
    players = contract.get("players") or {}

    served = [r for r in rows if r.get("canonicalConsensusRank") is not None]
    picks = [r for r in rows if str(r.get("assetClass") or "") == "pick"]
    idp = [r for r in rows if str(r.get("assetClass") or "") == "idp"]
    offense = [r for r in rows if str(r.get("assetClass") or "") == "offense"]
    rookies = [r for r in rows if r.get("rookie")]

    # ── identity resolution state ──
    with_pid = [r for r in rows if str(r.get("playerId") or "").strip()]
    without_pid = [r for r in rows if not str(r.get("playerId") or "").strip()]
    # A pick legitimately has no Sleeper id; separate it out so "unresolved"
    # counts players only.
    player_rows = [r for r in rows if str(r.get("assetClass") or "") != "pick"]
    players_without_pid = [r for r in player_rows if not str(r.get("playerId") or "").strip()]

    quarantined = [r for r in rows if r.get("quarantined")]
    flag_counts = Counter()
    for r in rows:
        for f in r.get("anomalyFlags") or []:
            flag_counts[str(f)] += 1

    # ── duplicate / ghost detection, independent of the contract's own ──
    #
    # Computed here rather than read off the contract, because whether the
    # contract's detectors can fire is itself a B5 finding (W06-F002). A
    # metric sourced from the mechanism under test proves nothing.
    from src.utils.name_clean import canonical_position_group

    by_posaware: dict[str, list[str]] = defaultdict(list)
    by_norm: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        if str(r.get("assetClass") or "") == "pick":
            continue
        nm = str(r.get("canonicalName") or r.get("displayName") or "")
        n = _norm(nm)
        if not n:
            continue
        grp = canonical_position_group(r.get("position"))
        by_posaware[f"{n}::{grp}"].append(nm)
        by_norm[n].append(nm)

    dup_posaware = {k: v for k, v in by_posaware.items() if len(v) > 1}
    dup_norm = {k: v for k, v in by_norm.items() if len(v) > 1}

    # Ghost pairs: same normalized name, one row resolved (has a playerId
    # and a value) and another not — the W06-F001 shape.
    pid_by_norm: dict[str, list[dict]] = defaultdict(list)
    for r in player_rows:
        n = _norm(str(r.get("canonicalName") or r.get("displayName") or ""))
        if n:
            pid_by_norm[n].append(r)
    ghost_pairs = []
    for n, group in pid_by_norm.items():
        if len(group) < 2:
            continue
        resolved = [g for g in group if str(g.get("playerId") or "").strip()]
        unresolved = [g for g in group if not str(g.get("playerId") or "").strip()]
        if resolved and unresolved:
            ghost_pairs.append(
                {
                    "norm": n,
                    "resolved": [str(g.get("displayName")) for g in resolved],
                    "ghost": [str(g.get("displayName")) for g in unresolved],
                }
            )

    # ── name-shape cohorts ──
    suffixed, punctuated, accented = [], [], []
    for r in player_rows:
        nm = str(r.get("displayName") or "")
        if SUFFIX_RE.search(nm.strip()):
            suffixed.append(nm)
        if PUNCT_RE.search(nm):
            punctuated.append(nm)
        if _strip_accents(nm) != nm:
            accented.append(nm)

    # Similar-but-distinct: same last name + same first initial, different
    # normalized name. The population a careless fuzzy matcher would merge.
    surname_initial: dict[str, set[str]] = defaultdict(set)
    for r in player_rows:
        n = _norm(str(r.get("displayName") or ""))
        parts = n.split()
        if len(parts) >= 2:
            surname_initial[f"{parts[-1]}|{parts[0][:1]}"].add(n)
    near_name_clusters = {k: sorted(v) for k, v in surname_initial.items() if len(v) > 1}

    # ── source coverage ──
    coverage = {}
    for r in rows:
        for k, v in (r.get("canonicalSiteValues") or {}).items():
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv > 0:
                coverage[str(k)] = coverage.get(str(k), 0) + 1

    matched_via = Counter()
    for r in rows:
        audit = r.get("sourceAudit")
        if isinstance(audit, dict):
            matched_via[str(audit.get("reason") or "none")] += 1

    return {
        "codeSha": _git("rev-parse", "HEAD"),
        "board": latest_board().name,
        "counts": {
            "rows": len(rows),
            "servedRows": len(served),
            "legacyPlayersDict": len(players),
            "playerRows": len(player_rows),
            "picks": len(picks),
            "offense": len(offense),
            "idp": len(idp),
            "rookies": len(rookies),
        },
        "identity": {
            "rowsWithPlayerId": len(with_pid),
            "rowsWithoutPlayerId": len(without_pid),
            "playerRowsWithoutPlayerId": len(players_without_pid),
            "playerRowsWithoutPlayerIdNames": sorted(
                str(r.get("displayName")) for r in players_without_pid
            )[:60],
            "quarantined": len(quarantined),
            "anomalyFlags": dict(flag_counts),
        },
        "duplicates": {
            "positionAwareDuplicateKeys": len(dup_posaware),
            "positionAwareDuplicates": {k: v for k, v in list(dup_posaware.items())[:40]},
            "crossUniverseNameCollisions": len(dup_norm) - len(dup_posaware),
            "ghostPairs": len(ghost_pairs),
            "ghostPairDetail": ghost_pairs[:40],
        },
        "nameShapes": {
            "suffixed": len(suffixed),
            "suffixedSample": sorted(suffixed)[:20],
            "punctuated": len(punctuated),
            "accented": len(accented),
            "accentedSample": sorted(accented)[:20],
            "nearNameClusters": len(near_name_clusters),
            "nearNameClusterSample": dict(list(near_name_clusters.items())[:15]),
        },
        "sourceCoverage": dict(sorted(coverage.items())),
        "matchedVia": dict(matched_via),
        "providerIdColumns": csv_id_columns(),
    }


def compare(a: dict, b: dict) -> None:
    def walk(pa, pb, path=""):
        if isinstance(pa, dict) and isinstance(pb, dict):
            for k in sorted(set(pa) | set(pb)):
                walk(pa.get(k), pb.get(k), f"{path}.{k}" if path else k)
            return
        if isinstance(pa, (int, float)) and isinstance(pb, (int, float)) and pa != pb:
            print(f"  {path:<52}{pa} -> {pb}  ({pb - pa:+})")
        elif isinstance(pa, list) and isinstance(pb, list) and len(pa) != len(pb):
            print(f"  {path:<52}len {len(pa)} -> {len(pb)}")

    print("== identity metric deltas ==")
    walk(a, b)
    print("  (no line above = every numeric metric identical)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="baseline")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"))
    args = ap.parse_args()

    if args.compare:
        a = json.loads((OUT / f"b5_metrics_{args.compare[0]}.json").read_text())
        b = json.loads((OUT / f"b5_metrics_{args.compare[1]}.json").read_text())
        compare(a, b)
        return 0

    m = metrics()
    path = OUT / f"b5_metrics_{args.out}.json"
    path.write_text(json.dumps(m, indent=1, default=str))

    c, i, d, n = m["counts"], m["identity"], m["duplicates"], m["nameShapes"]
    print(f"== B5 identity metrics ({args.out}) — {m['board']} @ {m['codeSha'][:9]} ==")
    print(
        f"  rows {c['rows']}  served {c['servedRows']}  players {c['playerRows']}  picks {c['picks']}"
    )
    print(f"  offense {c['offense']}  idp {c['idp']}  rookies {c['rookies']}")
    print(f"\n  rows with playerId          {i['rowsWithPlayerId']}")
    print(f"  rows without playerId       {i['rowsWithoutPlayerId']}  (picks {c['picks']})")
    print(f"  PLAYER rows without id      {i['playerRowsWithoutPlayerId']}   <- unresolved")
    print(f"  quarantined                 {i['quarantined']}")
    print(f"  anomaly flags               {i['anomalyFlags'] or 'none'}")
    print(f"\n  position-aware duplicates   {d['positionAwareDuplicateKeys']}")
    print(f"  cross-universe collisions   {d['crossUniverseNameCollisions']}")
    print(f"  ghost pairs                 {d['ghostPairs']}")
    for g in d["ghostPairDetail"][:10]:
        print(f"    {g['norm']:<28}resolved={g['resolved']}  ghost={g['ghost']}")
    print(f"\n  suffixed names              {n['suffixed']}")
    print(f"  punctuated names            {n['punctuated']}")
    print(f"  accented names              {n['accented']}")
    print(f"  near-name clusters          {n['nearNameClusters']}")
    pid = m["providerIdColumns"]
    print(f"\n  accepted id tokens          {pid['acceptedTokens']}")
    for k, v in pid["sources"].items():
        print(
            f"    {k:<22}rows={v['rows']:<5}cols={v['columns']}  "
            f"visible={v['visibleToLoader'] or 'NONE'}"
        )
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
