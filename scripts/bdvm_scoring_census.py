#!/usr/bin/env python3
"""Pinned LOCAL census of BDVM scoring coverage per league card.

For every NONZERO rule on each league's real Sleeper scoring card: its weight
and sign, which projection sources can supply the statistic (probed against
each adapter's own parser — see ``src/bdvm/scoring_census.py``), the
classification, affected families, and — when realized history is supplied —
the rule's measured 2025 impact under that card.

This SCRIPT is reporting only: it changes no projection, value or snapshot,
and it is a LOCAL census: no production session is used.  (The unit that
added it separately changed ``realized_points``'s reception-bonus mapping,
which DOES move values — see the census README.)  Production
``/api/bdvm/values`` publishes ``meta.scoringCoverage`` for the PBP-only rules
it can see; this census covers the source-vocabulary rules it cannot.

Inputs (all read-only):

* league cards — ``<leagues-dir>/scoring_<sleeperLeagueId>.json`` for each
  active league in ``config/leagues/registry.json``;
* optional realized history — ``--weekly-json`` (a JSON list, ``.gz`` ok, of
  nflverse weekly rows) or ``--fetch-season`` (network, nflverse release);
* optional play-by-play supplement — ``--pbp-dir`` holding
  ``pbp_weekly_<season>.jsonl`` from ``scripts/build_pbp_weekly.py``.

Without realized history the census is vocabulary-level only and says so.

Usage::

    python scripts/bdvm_scoring_census.py --out-dir docs/research/bdvm-v1/scoring-census-2026-10-01 \\
        --leagues-dir ../data/leagues --weekly-json weekly_2025.json.gz --pbp-dir pbp/ --season 2025

Exit codes: 0 written, 1 no league card found, 2 error.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.bdvm.scoring_census import (  # noqa: E402
    CENSUS_VERSION,
    census_for_card,
    measure_realized,
)

_CLASS_ORDER = (
    "MAPPING_ERROR",
    "UNSUPPORTED_VOCABULARY",
    "ABSENT_FIELD",
    "SUPPORTED_IMPUTED",
    "SUPPORTED",
    "NOT_APPLICABLE",
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_head() -> dict[str, Any]:
    def _run(*args: str) -> str | None:
        try:
            return subprocess.run(
                ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    status = _run("status", "--porcelain", "--untracked-files=no")
    return {"sha": _run("rev-parse", "HEAD"), "dirty": None if status is None else bool(status)}


def _load_rows(path: Path) -> list[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        rows = json.load(fh)
    if not isinstance(rows, list):
        raise ValueError(f"{path}: expected a JSON list of weekly rows")
    return rows


def _active_leagues() -> list[dict[str, Any]]:
    reg = json.loads((REPO_ROOT / "config" / "leagues" / "registry.json").read_text("utf-8"))
    return [lg for lg in reg.get("leagues", []) if lg.get("active")]


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:g}" if abs(v) >= 0.01 or v == 0 else f"{v:.4f}"
    return str(v)


def render_markdown(doc: dict[str, Any]) -> str:
    out: list[str] = [
        f"# BDVM scoring census ({doc['scope']})",
        "",
        f"- census: `{doc['censusVersion']}` · generated `{doc['generatedAt']}`",
        f"- code: `{doc['code']['sha']}` (dirty={doc['code']['dirty']})",
        f"- realized history: {doc['realizedInput']['status']}",
        "",
        "Weights are the card's own rates; `points` are SIGNED realized 2025 REG points "
        "under that card. A partial total is not a lower bound: omitted penalties "
        "(negative weights) overstate it. SUPPORTED_IMPUTED points are not omitted; "
        "they rest on an estimate (first downs imputed from yards).",
        "",
    ]
    for lg in doc["leagues"]:
        out += [
            f"## {lg['leagueKey']} (Sleeper {lg['sleeperLeagueId']})",
            "",
            f"Card fetched `{lg['card']['fetchedAt']}`, fingerprint `{lg['card']['fingerprint']}`, "
            f"{lg['card']['nonzeroRules']} nonzero rules, idpEnabled={lg['idpEnabled']}. "
            f"Classes: {lg['classCounts']}.",
            "",
            "| priority | key | weight | class | families | sources | capability | "
            "realized pts | affected / eligible | share | silent? |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for e in lg["rules"]:
            if e["classification"] == "NOT_APPLICABLE":
                continue
            r = e.get("realized") or {}
            src = ", ".join(f"{k}:{v}" for k, v in (e.get("sources") or {}).items())
            cap = ", ".join(f"{k}:{v}" for k, v in (e.get("capability") or {}).items())
            cls = e["classification"] + (
                " +baselineMapErr" if e.get("baselineMappingError") else ""
            )
            share = r.get("shareOfAffectedFamilyPoints")
            if e.get("reportedInUnscoredKeys"):
                silent = "reported"
            elif e["classification"] == "SUPPORTED_IMPUTED":
                silent = "IMPUTED (estimated, not omitted)"
            elif e["classification"] != "SUPPORTED":
                silent = "SILENT"
            else:
                silent = ""
            out.append(
                f"| {e['priority']:.1f} | `{e['key']}` | {_fmt(e['weight'])} | {cls} | "
                f"{','.join(e.get('affectedFamilies') or [])} | {src} | {cap} | "
                f"{_fmt(r.get('points'))} | {_fmt(r.get('affectedPlayers'))} / "
                f"{_fmt(r.get('eligiblePlayers'))} | "
                f"{'—' if share is None else f'{share:.2%}'} | {silent} |"
            )
        na = [e["key"] for e in lg["rules"] if e["classification"] == "NOT_APPLICABLE"]
        out += ["", f"NOT_APPLICABLE ({len(na)}): " + ", ".join(f"`{k}`" for k in na), ""]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--leagues-dir", type=Path, default=REPO_ROOT / "data" / "leagues")
    ap.add_argument("--weekly-json", type=Path, default=None)
    ap.add_argument("--fetch-season", type=int, default=None, help="fetch nflverse weekly rows")
    ap.add_argument("--pbp-dir", type=Path, default=None)
    ap.add_argument("--season", type=int, default=2025, help="realized season to measure")
    args = ap.parse_args(argv)

    rows: list[dict[str, Any]] | None = None
    realized_input: dict[str, Any] = {"status": "unavailable — vocabulary-level census only"}
    try:
        if args.weekly_json:
            rows = _load_rows(args.weekly_json)
            realized_input = {"path": args.weekly_json.name, "sha256": _sha256(args.weekly_json)}
        elif args.fetch_season:
            from src.nfl_data.nflverse_direct import (  # noqa: PLC0415
                _URL_TEMPLATES,
                fetch_weekly_stats,
            )

            rows = fetch_weekly_stats([args.fetch_season])
            realized_input = {"url": _URL_TEMPLATES["weekly_stats"].format(year=args.fetch_season)}
    except (OSError, ValueError) as exc:
        print(f"ERROR: realized history unreadable: {exc}", file=sys.stderr)
        return 2
    attach = None
    if rows is not None:
        rows = [r for r in rows if int(float(r.get("season") or 0)) == args.season]
        realized_input.update(season=args.season, rows=len(rows))
        realized_input["status"] = f"{len(rows)} nflverse weekly rows, season {args.season}"
        if args.pbp_dir:
            from src.nfl_data.pbp_weekly import (  # noqa: PLC0415
                PbpWeeklyStats,
                attach_supplement,
                load_pbp_weekly,
                pbp_weekly_path,
            )

            stats = PbpWeeklyStats.from_payload(load_pbp_weekly(args.season, out_dir=args.pbp_dir))
            pbp_path = pbp_weekly_path(args.season, out_dir=args.pbp_dir)
            if stats is None:
                realized_input["pbp"] = "missing — play-by-play rules unmeasured"
            else:
                realized_input["pbp"] = {"path": pbp_path.name, "sha256": _sha256(pbp_path)}
                realized_input["status"] += " + play-by-play supplement"

                def attach(row, _s=stats):
                    return attach_supplement(row, _s)

    leagues_out: list[dict[str, Any]] = []
    for lg in _active_leagues():
        lid = str(lg.get("sleeperLeagueId") or "")
        path = args.leagues_dir / f"scoring_{lid}.json"
        if not path.exists():
            print(f"WARN: no scoring card for {lg.get('key')} at {path}", file=sys.stderr)
            continue
        snap = json.loads(path.read_text("utf-8"))
        card = snap.get("scoringSettings") or snap.get("scoring_settings") or {}
        nonzero = {k: v for k, v in card.items() if isinstance(v, (int, float)) and v}
        realized = (
            measure_realized(rows, card, nonzero.keys(), attach=attach)
            if rows is not None
            else None
        )
        rules = census_for_card(card, realized=realized, idp_enabled=bool(lg.get("idpEnabled")))
        counts = {c: sum(1 for e in rules if e["classification"] == c) for c in _CLASS_ORDER}
        leagues_out.append(
            {
                "leagueKey": lg.get("key"),
                "sleeperLeagueId": lid,
                "idpEnabled": bool(lg.get("idpEnabled")),
                "card": {
                    "file": path.name,
                    "sha256": _sha256(path),
                    "fetchedAt": snap.get("fetchedAt"),
                    "season": snap.get("season"),
                    "fingerprint": snap.get("scoringFingerprint"),
                    "nonzeroRules": len(nonzero),
                },
                "classCounts": counts,
                "realizedFamilies": (realized or {}).get("families"),
                "engineColumnTotals": (realized or {}).get("columnTotals"),
                "rules": rules,
            }
        )
    if not leagues_out:
        print("ERROR: no league card found", file=sys.stderr)
        return 1

    doc = {
        "censusVersion": CENSUS_VERSION,
        "scope": "LOCAL",
        "scopeNote": (
            "Local census over the real league cards and public nflverse history; no "
            "production/owner session was used. Production coverage remains the "
            "/api/bdvm/values meta.scoringCoverage block."
        ),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "code": _git_head(),
        "realizedInput": realized_input,
        "leagues": leagues_out,
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "census.json").write_text(
        json.dumps(doc, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    (args.out_dir / "census.md").write_text(render_markdown(doc), encoding="utf-8")
    print(f"wrote {args.out_dir / 'census.json'} and census.md ({len(leagues_out)} leagues)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
