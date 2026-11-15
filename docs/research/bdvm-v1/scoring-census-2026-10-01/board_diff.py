#!/usr/bin/env python3
"""LOCAL before/after BDVM board diff for the ``bonus_rec_wr/_rb`` mapping.

The only value-affecting change in the scoring-census unit is
``src/nfl_data/realized_points.py`` (the reception-bonus family; every other
edited module changes wording or adds a metadata block).  This harness
therefore runs the SAME pinned inputs through the SAME head code twice, once
with the merge-base copy of ``realized_points.py`` installed in its place
(read with ``git show <base-ref>:...``, blob sha recorded) and once with the
head copy, each in its own subprocess so no module binding leaks between
the two.

What is built, per variant (mirrors ``scripts/bdvm_build_baseline.py`` +
``src/api/bdvm_api.py``, minus the network):

* the reconstructed-baseline projection snapshot from the pinned weekly rows
  under the contract's own ``sleeper.scoringSettings`` (applied to every
  season, as production does), with the PBP supplement for the seasons
  whose artifact is supplied;
* ``run_valuation`` for ``dynasty_main`` on the pinned contract —
  preseason (no actuals) and, when ``--actuals-json`` is given, in-season
  with those weeks' actuals.

NOT built (stated in the output): rookie draft-slot priors and the player
context feed (both need network context fetches), Clay / IDP Show real
projections (no local snapshot), events.  Clay offense records WOULD move
by the same mechanism (BDVM rescoring reads ``receptions``); that path is
not measured here.

Usage::

    python docs/research/bdvm-v1/scoring-census-2026-10-01/board_diff.py \\
        --weekly-json weekly_2023_2025.json.gz --pbp-dir pbp/ \\
        --contract exports/latest/dynasty_data_2026-09-30.json \\
        --actuals-json weekly_2026_wk1_3.json.gz --base-ref 61af3f953 \\
        --out docs/research/bdvm-v1/scoring-census-2026-10-01/board_diff.json
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
RP_PATH = "src/nfl_data/realized_points.py"
LEAGUE_KEY = "dynasty_main"
SEASON = 2026
AS_OF = "2026-10-01"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout


def _load_json(path: Path) -> Any:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Child: build one board with a given realized_points.py
# ---------------------------------------------------------------------------


def _install_realized_points(path: Path) -> None:
    sys.path.insert(0, str(REPO_ROOT))
    import src.nfl_data  # noqa: F401, PLC0415

    name = "src.nfl_data.realized_points"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    sys.modules["src.nfl_data"].realized_points = mod


def _board(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for p in payload.get("players") or []:
        name = str(p.get("name") or p.get("displayName") or "")
        tv = p.get("tradeValue") or p.get("trade_value") or {}
        # Keyed by name + playerId: two players sharing a name stay distinct.
        out[f"{name} [{p.get('playerId')}]"] = {
            "position": p.get("position"),
            "fpg": (p.get("projection") or {}).get("fpg"),
            "balanced": tv.get("balanced") if isinstance(tv, dict) else None,
            "score": p.get("dynastyScore0to100"),
        }
    return out


def child(args: argparse.Namespace) -> int:
    _install_realized_points(Path(args.rp_file))
    from src.api.bdvm_api import _registry_settings_for  # noqa: PLC0415
    from src.bdvm.actuals import weekly_points_from_rows  # noqa: PLC0415
    from src.bdvm.baseline import build_baseline_records  # noqa: PLC0415
    from src.bdvm.params import load_param_set  # noqa: PLC0415
    from src.bdvm.service import run_valuation  # noqa: PLC0415
    from src.nfl_data.pbp_weekly import SeasonPbpIndex  # noqa: PLC0415
    from src.utils.name_clean import normalize_player_name  # noqa: PLC0415

    contract = _load_json(Path(args.contract))
    card = (contract.get("sleeper") or {}).get("scoringSettings") or {}
    rows = _load_json(Path(args.weekly_json))
    pbp = SeasonPbpIndex(out_dir=Path(args.pbp_dir)) if args.pbp_dir else None
    records, summary = build_baseline_records(
        season=SEASON,
        as_of=AS_OF,
        weekly_rows=rows,
        scoring_settings=card,
        name_normalizer=normalize_player_name,
        pbp_for_season=pbp.for_season if pbp else None,
    )
    roster_settings, idp_enabled, scoring_profile = _registry_settings_for(LEAGUE_KEY)
    common = dict(
        league_key=LEAGUE_KEY,
        params=load_param_set(),
        registry_roster_settings=roster_settings,
        idp_enabled=idp_enabled,
        scoring_profile=scoring_profile,
        projection_records=records,
        snapshot_as_of=AS_OF,
        season=SEASON,
        write_snapshot_files=False,
        context={},
        events=[],
    )
    boards = {"preseason": _board(run_valuation(contract, **common))}
    if args.actuals_json:
        actuals = weekly_points_from_rows(
            _load_json(Path(args.actuals_json)),
            card,
            season=SEASON,
            name_normalizer=normalize_player_name,
            pbp_stats=None,
        )
        boards["inSeason"] = _board(run_valuation(contract, actuals=actuals, **common))
    fpg = {r.player_key: r.fpg for r in records if r.fpg is not None}
    Path(args.child_out).write_text(
        json.dumps(
            {
                "boards": boards,
                "baselineSummary": summary,
                "records": len(records),
                "recordFpg": fpg,
                "pbpSeasonsMissing": list(pbp.seasons_missing) if pbp else None,
            }
        ),
        encoding="utf-8",
    )
    return 0


# ---------------------------------------------------------------------------
# Parent: run both variants and diff
# ---------------------------------------------------------------------------


def _ranks(board: dict[str, dict[str, Any]]) -> dict[str, int]:
    priced = [(n, b["balanced"]) for n, b in board.items() if b.get("balanced") is not None]
    priced.sort(key=lambda t: (-t[1], t[0]))
    return {n: i + 1 for i, (n, _v) in enumerate(priced)}


def _diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    rb, ra = _ranks(before), _ranks(after)
    common = sorted(set(rb) & set(ra))
    changed = []
    by_pos: dict[str, dict[str, Any]] = {}
    for n in common:
        b, a = before[n], after[n]
        dv = (a["balanced"] or 0) - (b["balanced"] or 0)
        dfpg = None
        if a.get("fpg") is not None and b.get("fpg") is not None:
            dfpg = a["fpg"] - b["fpg"]
        dr = ra[n] - rb[n]
        if abs(dv) > 1e-9 or dr or (dfpg and abs(dfpg) > 1e-9):
            changed.append(
                {
                    "name": n,
                    "position": a.get("position"),
                    "fpgDelta": round(dfpg, 4) if dfpg is not None else None,
                    "balancedBefore": round(b["balanced"], 3),
                    "balancedAfter": round(a["balanced"], 3),
                    "balancedDelta": round(dv, 3),
                    "rankBefore": rb[n],
                    "rankAfter": ra[n],
                }
            )
            pos = str(a.get("position"))
            s = by_pos.setdefault(pos, {"changed": 0, "rankMoves": 0, "maxAbsBalancedDelta": 0.0})
            s["changed"] += 1
            s["rankMoves"] += 1 if dr else 0
            s["maxAbsBalancedDelta"] = round(max(s["maxAbsBalancedDelta"], abs(dv)), 3)
    changed.sort(key=lambda e: -abs(e["balancedDelta"]))
    return {
        "pricedBefore": len(rb),
        "pricedAfter": len(ra),
        "pricedInBoth": len(common),
        "onlyBefore": sorted(set(rb) - set(ra)),
        "onlyAfter": sorted(set(ra) - set(rb)),
        "playersChanged": len(changed),
        "playersWithRankChange": sum(1 for e in changed if e["rankBefore"] != e["rankAfter"]),
        "maxAbsBalancedDelta": changed[0]["balancedDelta"] if changed else 0.0,
        "maxAbsRankMove": max((abs(e["rankAfter"] - e["rankBefore"]) for e in changed), default=0),
        "top200MembershipChanges": sorted(
            n for n in set(rb) | set(ra) if (rb.get(n, 10**9) <= 200) != (ra.get(n, 10**9) <= 200)
        ),
        "byPosition": dict(sorted(by_pos.items())),
        "largestChanges": changed[:25],
    }


def parent(args: argparse.Namespace) -> int:
    head_sha = _git("rev-parse", "HEAD").strip()
    dirty = bool(_git("status", "--porcelain", "--untracked-files=no").strip())
    results = {}
    with tempfile.TemporaryDirectory() as td:
        # The export is the raw scraper bundle; the BDVM reads the built
        # contract (``playersArray``).  Built ONCE, at head, and handed to both
        # variants as the same input file.
        raw = _load_json(Path(args.contract))
        contract_path = Path(args.contract)
        built_note = "input is already a built contract"
        if not raw.get("playersArray"):
            sys.path.insert(0, str(REPO_ROOT))
            from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

            contract_path = Path(td) / "contract.json"
            contract_path.write_text(json.dumps(build_api_data_contract(raw)), encoding="utf-8")
            built_note = "built from the raw export with build_api_data_contract at head"
        args.built_contract = str(contract_path)
        built_sha = _sha256(contract_path)
        base_file = Path(td) / "realized_points_base.py"
        base_file.write_text(_git("show", f"{args.base_ref}:{RP_PATH}"), encoding="utf-8")
        variants = {"before": base_file, "after": REPO_ROOT / RP_PATH}
        blobs = {}
        for label, rp in variants.items():
            blobs[label] = _git("hash-object", str(rp)).strip()
            out = Path(td) / f"{label}.json"
            cmd = [
                sys.executable,
                __file__,
                "--child",
                "--rp-file",
                str(rp),
                "--child-out",
                str(out),
                "--weekly-json",
                args.weekly_json,
                "--contract",
                args.built_contract,
            ]
            if args.pbp_dir:
                cmd += ["--pbp-dir", args.pbp_dir]
            if args.actuals_json:
                cmd += ["--actuals-json", args.actuals_json]
            subprocess.run(cmd, cwd=REPO_ROOT, check=True)
            results[label] = json.loads(out.read_text(encoding="utf-8"))
    fb, fa = results["before"]["recordFpg"], results["after"]["recordFpg"]
    fpg_moves = sorted(
        ((k, fa[k] - fb[k]) for k in set(fb) & set(fa) if abs(fa[k] - fb[k]) > 1e-12),
        key=lambda t: -abs(t[1]),
    )
    pins = {
        "code": {"sha": head_sha, "dirty": dirty, "baseRef": args.base_ref},
        "realizedPointsBlob": blobs,
        "weeklyJson": {
            "path": Path(args.weekly_json).name,
            "sha256": _sha256(Path(args.weekly_json)),
        },
        "contract": {
            "path": Path(args.contract).name,
            "sha256": _sha256(Path(args.contract)),
            "note": built_note,
            "builtSha256": built_sha,
        },
        "pbpDir": (
            {p.name: _sha256(p) for p in sorted(Path(args.pbp_dir).glob("pbp_weekly_*.jsonl"))}
            if args.pbp_dir
            else None
        ),
        "actualsJson": (
            {"path": Path(args.actuals_json).name, "sha256": _sha256(Path(args.actuals_json))}
            if args.actuals_json
            else None
        ),
    }
    doc = {
        "scope": "LOCAL",
        "leagueKey": LEAGUE_KEY,
        "season": SEASON,
        "asOf": AS_OF,
        "pins": pins,
        "notBuilt": [
            "rookie draft-slot priors (network context fetch)",
            "player context feed: context={} (age/draft capital from the contract rows only)",
            "Clay / IDP Show real projections (no local snapshot) — Clay offense would move "
            "by the same mechanism and is NOT measured here",
            "events (events=[])",
        ],
        "pbpSeasonsMissing": results["after"]["pbpSeasonsMissing"],
        "baselineRecords": results["after"]["records"],
        "baselineRecordFpgMoves": {
            "count": len(fpg_moves),
            "maxAbs": round(abs(fpg_moves[0][1]), 4) if fpg_moves else 0.0,
            "positionalMeansBefore": results["before"]["baselineSummary"].get("positionalMeans"),
            "positionalMeansAfter": results["after"]["baselineSummary"].get("positionalMeans"),
        },
        "boards": {
            k: _diff(results["before"]["boards"][k], results["after"]["boards"][k])
            for k in results["after"]["boards"]
        },
    }
    Path(args.out).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {k: {kk: v[kk] for kk in list(v)[:9]} for k, v in doc["boards"].items()}, indent=2
        )
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--rp-file", help=argparse.SUPPRESS)
    ap.add_argument("--child-out", help=argparse.SUPPRESS)
    ap.add_argument("--weekly-json", required=True)
    ap.add_argument("--pbp-dir")
    ap.add_argument("--contract", required=True)
    ap.add_argument("--actuals-json")
    ap.add_argument("--base-ref", default="61af3f953")
    ap.add_argument("--out")
    args = ap.parse_args()
    return child(args) if args.child else parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
