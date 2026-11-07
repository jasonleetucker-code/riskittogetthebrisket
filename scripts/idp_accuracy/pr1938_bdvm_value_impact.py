"""BDVM value-level impact of PR #1938's scorer change, on ONE identical snapshot.

Research/measurement only.  Imports production code, changes none of it, writes
only ``--out``.  It never writes a projection snapshot, the player context, the
events file, a user_kv alert state or anything under ``data/bdvm/``.

Two arms share EVERYTHING except the realized-points scorer that feeds BDVM's
in-season posterior (``src.bdvm.actuals.weekly_points_from_rows``):

* ``current``   -- ``src/nfl_data/realized_points.py`` as of ``--base-ref``
  (default ``origin/main``: what production runs today);
* ``corrected`` -- the working tree's ``realized_points.py`` (PR #1938).

Same contract, same projection records, same nflverse weekly rows, same
play-by-play artifact, same scoring card (the contract's
``sleeper.scoringSettings``, exactly what ``bdvm_api._actuals_for`` reads), same
player context / schedule / events / params.  It reports, per arm and as a diff:
balanced fundamental values, BDVM rank, replacement levels, BUY/HOLD/SELL
signals, the alert transitions the daily sweep would raise for rostered players
(``bdvm_signal_alerts.ACTIONABLE_BDVM_SIGNALS``), per-roster strategy capitals
and the double-positive trade scan (``/api/bdvm/trades``).

Two modes:

Box (production) mode: ``--app-dir`` + ``--corrected-scorer-file``
    Run ON THE BOX against the deployed app, read-only.  ``current`` is the
    deployed ``src/nfl_data/realized_points.py``; ``corrected`` is PR #1938's
    copy of that file, loaded from ``--corrected-scorer-file`` under a private
    module name.  The snapshot is the box's own latest snapshot (or
    ``--snapshot``); weekly rows, the play-by-play artifact, player context,
    schedule and events are the deployed app's own (``--cache-only`` reads the
    weekly feed the refresh owner materialised and never fetches).  This
    script and the PR file live outside the app directory, and nothing is
    written except ``--out`` and ``--scratch`` (default: the system temp dir).
Dev mode (default): ``current`` is ``realized_points.py`` at ``--base-ref``
    (``git show``), ``corrected`` the working tree's.  No production snapshot
    exists off the box, so ``--proxy-baseline`` builds the reconstructed
    baseline IN MEMORY with the builder the weekly ``dynasty-bdvm-refresh``
    timer runs first (``fetch_and_build_baseline``, public nflverse data),
    scored with the ``current`` scorer so it stands in for a snapshot
    production already holds.  It has no Clay / IDP-Show real records, no
    materialised player context and no events file, so its VALUES are not
    production's -- only the mechanism, its direction and its rough size.
    ``--proxy-rebuilt-arm`` adds a third arm that rebuilds that baseline with
    the corrected scorer (the state after the next weekly rebuild).

Box usage (exact; read-only)::

    PYTHONDONTWRITEBYTECODE=1 /home/dynasty/trade-calculator/venv/bin/python \
        /tmp/pr1938/pr1938_bdvm_value_impact.py --app-dir /home/dynasty/trade-calculator \
        --corrected-scorer-file /tmp/pr1938/realized_points.py \
        --cache-only --out /tmp/pr1938/bdvm_impact_box.json
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


def _app_dir_from_argv() -> Path:
    if "--app-dir" in sys.argv:
        return Path(sys.argv[sys.argv.index("--app-dir") + 1]).resolve()
    return Path(__file__).resolve().parents[2]


REPO = _app_dir_from_argv()
sys.path.insert(0, str(REPO))

ACTUALS_SCORER_PATH = "src/nfl_data/realized_points.py"


def _sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _sha256_file(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    return _sha256_bytes(path.read_bytes())


def load_scorer_at(ref: str, scratch: Path):
    """``realized_points.py`` as of ``ref``, importable under a private name."""
    src = subprocess.run(
        ["git", "show", f"{ref}:{ACTUALS_SCORER_PATH}"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    scratch.mkdir(parents=True, exist_ok=True)
    path = scratch / "_pr1938_current_realized_points.py"
    path.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("_pr1938_current_realized_points", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_pr1938_current_realized_points"] = mod
    spec.loader.exec_module(mod)
    return mod, _sha256_bytes(src.encode("utf-8"))


def load_scorer_file(path: Path, name: str):
    """A ``realized_points.py`` copy at ``path``, importable under ``name``."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod, _sha256_file(path)


def load_contract(path: Path) -> tuple[dict[str, Any], str]:
    """A served contract (``dynasty_data_*.json``) or an export zip holding one."""
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as zf:
            member = sorted(n for n in zf.namelist() if n.startswith("dynasty_data_"))[-1]
            blob = zf.read(member)
    else:
        blob = path.read_bytes()
    raw = json.loads(blob)
    contract = raw if raw.get("playersArray") else build_api_data_contract(raw)
    return contract, _sha256_bytes(blob)


def _default_contract() -> Path:
    candidates = sorted((REPO / "exports" / "latest").glob("dynasty_data_*.json"))
    if not candidates:
        raise SystemExit("no exports/latest/dynasty_data_*.json; pass --contract")
    return candidates[-1]


def _player_view(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    players = [p for p in payload.get("players") or [] if isinstance(p, dict)]
    ranked = sorted(players, key=lambda p: -float((p.get("tradeValue") or {}).get("balanced") or 0))
    out: dict[str, dict[str, Any]] = {}
    for rank, p in enumerate(ranked, start=1):
        key = str(p.get("playerId") or p.get("name"))
        out[key] = {
            "name": p.get("name"),
            "position": p.get("position"),
            "group": p.get("group"),
            "balanced": float((p.get("tradeValue") or {}).get("balanced") or 0.0),
            "fpg": (p.get("projection") or {}).get("fpg"),
            "rank": rank,
            "signal": str((p.get("signal") or {}).get("signal") or ""),
            "gap": (p.get("market") or {}).get("gap"),
        }
    return out


def _rostered(contract: Mapping[str, Any]) -> dict[str, str]:
    """playerId -> ``roster:<roster_id>`` (no manager name is written to the evidence)."""
    out: dict[str, str] = {}
    for team in (contract.get("sleeper") or {}).get("teams") or []:
        name = f"roster:{team.get('roster_id') or team.get('rosterId')}"
        for pid in team.get("playerIds") or []:
            if isinstance(pid, (str, int)):
                out[str(pid)] = name
    return out


def diff_payloads(
    base: Mapping[str, Any], new: Mapping[str, Any], rostered: Mapping[str, str]
) -> dict[str, Any]:
    from src.api.bdvm_signal_alerts import ACTIONABLE_BDVM_SIGNALS  # noqa: PLC0415

    b, n = _player_view(base), _player_view(new)
    by_pos: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "priced": 0,
            "valueChanged": 0,
            "up": 0,
            "down": 0,
            "absDeltas": [],
            "rankMoves": [],
        }
    )
    movers = []
    signal_flips = []
    alert_transitions = []
    for key in sorted(set(b) | set(n)):
        pb, pn = b.get(key), n.get(key)
        if pb is None or pn is None:
            movers.append({"key": key, "onlyIn": "current" if pn is None else "corrected"})
            continue
        s = by_pos[str(pn["position"])]
        s["priced"] += 1
        delta = pn["balanced"] - pb["balanced"]
        if abs(delta) > 0.5:  # values are published to whole points
            s["valueChanged"] += 1
            s["up" if delta > 0 else "down"] += 1
            s["absDeltas"].append(abs(delta))
        if pn["rank"] != pb["rank"]:
            s["rankMoves"].append(abs(pn["rank"] - pb["rank"]))
        movers.append(
            {
                "key": key,
                "name": pn["name"],
                "position": pn["position"],
                "balancedCurrent": round(pb["balanced"], 1),
                "balancedCorrected": round(pn["balanced"], 1),
                "delta": round(delta, 1),
                "deltaPct": round(100 * delta / pb["balanced"], 2) if pb["balanced"] else None,
                "rankCurrent": pb["rank"],
                "rankCorrected": pn["rank"],
                "fpgCurrent": pb["fpg"],
                "fpgCorrected": pn["fpg"],
                "rosteredBy": rostered.get(key),
            }
        )
        if pb["signal"] != pn["signal"]:
            flip = {
                "key": key,
                "name": pn["name"],
                "position": pn["position"],
                "from": pb["signal"],
                "to": pn["signal"],
                "rosteredBy": rostered.get(key),
            }
            signal_flips.append(flip)
            # The sweep fires when the NEW signal is actionable and differs
            # from the last-seen one (``_evaluate_bdvm``).  Roster-scoped.
            if pn["signal"] in ACTIONABLE_BDVM_SIGNALS and rostered.get(key):
                alert_transitions.append(flip)
    summary = {}
    for pos, s in sorted(by_pos.items()):
        deltas = s.pop("absDeltas")
        moves = s.pop("rankMoves")
        summary[pos] = {
            **s,
            "meanAbsDelta": round(sum(deltas) / len(deltas), 1) if deltas else None,
            "maxAbsDelta": round(max(deltas), 1) if deltas else None,
            "rankChanged": len(moves),
            "maxRankMove": max(moves) if moves else 0,
        }
    real = [m for m in movers if "delta" in m]
    pcts = sorted(
        abs(m["deltaPct"]) for m in real if m["deltaPct"] is not None and abs(m["delta"]) > 0.5
    )

    def _q(q: float) -> float | None:
        return round(pcts[min(len(pcts) - 1, int(q * len(pcts)))], 2) if pcts else None

    rank_moves = sorted(abs(m["rankCurrent"] - m["rankCorrected"]) for m in real)
    repl_b, repl_n = base.get("replacement") or {}, new.get("replacement") or {}
    return {
        "pricedCurrent": len(b),
        "pricedCorrected": len(n),
        "valueChanged": sum(1 for m in real if abs(m["delta"]) > 0.5),
        "rankChanged": sum(1 for m in real if m["rankCurrent"] != m["rankCorrected"]),
        "absDeltaPctAmongChanged": {
            "median": _q(0.5),
            "p90": _q(0.9),
            "max": pcts[-1] if pcts else None,
            "atLeast5pct": sum(1 for x in pcts if x >= 5),
            "atLeast10pct": sum(1 for x in pcts if x >= 10),
        },
        "rankMove": {
            "median": rank_moves[len(rank_moves) // 2] if rank_moves else 0,
            "p90": rank_moves[int(0.9 * len(rank_moves))] if rank_moves else 0,
            "max": rank_moves[-1] if rank_moves else 0,
            "top100Membership": {
                "entered": sum(1 for m in real if m["rankCorrected"] <= 100 < m["rankCurrent"]),
                "left": sum(1 for m in real if m["rankCurrent"] <= 100 < m["rankCorrected"]),
            },
        },
        "byPosition": summary,
        "replacementCurrent": repl_b,
        "replacementCorrected": repl_n,
        "replacementChanged": repl_b != repl_n,
        "topMoversByAbsDelta": sorted(real, key=lambda m: -abs(m["delta"]))[:30],
        "topMoversRosteredByAbsDelta": sorted(
            [m for m in real if m["rosteredBy"]], key=lambda m: -abs(m["delta"])
        )[:30],
        "onlyInOneArm": [m for m in movers if "onlyIn" in m],
        "signalFlips": {
            "count": len(signal_flips),
            "byTransition": dict(Counter(f"{f['from']}->{f['to']}" for f in signal_flips)),
            "rosteredCount": sum(1 for f in signal_flips if f["rosteredBy"]),
            "list": signal_flips,
        },
        "alertTransitionsRostered": {
            "count": len(alert_transitions),
            "byTeam": dict(Counter(f["rosteredBy"] for f in alert_transitions)),
            "list": alert_transitions,
            "caveat": "an upper bound for one sweep: a user whose last-seen state already holds "
            "the new signal, or who was notified inside the minimum interval, gets nothing",
        },
    }


def _trade_keys(scan: Mapping[str, Any]) -> list[str]:
    """Identity of each proposed trade: who gives what (``roster.py`` from/to)."""
    keys = []
    for t in scan.get("trades") or []:
        sides = []
        for side in ("from", "to"):
            blob = t.get(side) or {}
            gives = ",".join(sorted(str(x) for x in blob.get("gives") or []))
            sides.append(f"{blob.get('ownerId')}:{gives}")
        keys.append("|".join(sides))
    return keys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-ref", default="origin/main")
    ap.add_argument("--contract", type=Path, default=None)
    ap.add_argument("--snapshot", type=Path, default=None)
    ap.add_argument("--proxy-baseline", action="store_true")
    ap.add_argument("--proxy-rebuilt-arm", action="store_true")
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--league-key", default="dynasty_main")
    ap.add_argument("--cache-only", action="store_true")
    ap.add_argument("--app-dir", type=Path, default=None)
    ap.add_argument("--corrected-scorer-file", type=Path, default=None)
    ap.add_argument(
        "--scratch", type=Path, default=Path(tempfile.gettempdir()) / "pr1938_bdvm_impact"
    )
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    import src.bdvm.actuals as actuals  # noqa: PLC0415
    import src.bdvm.baseline as baseline  # noqa: PLC0415
    import src.bdvm.scoring as bdvm_scoring  # noqa: PLC0415
    import src.nfl_data.realized_points as rp  # noqa: PLC0415
    from src.api import bdvm_api  # noqa: PLC0415
    from src.bdvm.league_config import from_contract  # noqa: PLC0415
    from src.bdvm.params import load_param_set  # noqa: PLC0415
    from src.bdvm.projections import latest_snapshot_path, load_snapshot  # noqa: PLC0415
    from src.bdvm.roster import analyze_rosters, scan_double_positive_trades  # noqa: PLC0415
    from src.bdvm.service import run_valuation  # noqa: PLC0415
    from src.nfl_data import ingest  # noqa: PLC0415
    from src.nfl_data.pbp_weekly import (  # noqa: PLC0415
        SeasonPbpIndex,
        default_pbp_stats,
        pbp_weekly_path,
    )
    from src.utils.name_clean import normalize_player_name  # noqa: PLC0415

    if args.app_dir is not None:
        if args.corrected_scorer_file is None or args.proxy_baseline:
            raise SystemExit("--app-dir needs --corrected-scorer-file and no --proxy-baseline")
        current_mod, current_sha = rp, _sha256_file(REPO / ACTUALS_SCORER_PATH)
        corrected_mod, corrected_sha = load_scorer_file(
            args.corrected_scorer_file.resolve(), "_pr1938_corrected_realized_points"
        )
    else:
        current_mod, current_sha = load_scorer_at(args.base_ref, args.scratch)
        corrected_mod, corrected_sha = rp, _sha256_file(REPO / ACTUALS_SCORER_PATH)
    deployed_fn = rp.compute_weekly_points  # restored after every swap
    corrected_fn = corrected_mod.compute_weekly_points
    season = args.season or actuals.nfl_projection_season()
    actuals_season = actuals.current_nfl_season() or season
    contract_path = args.contract or _default_contract()
    contract, contract_sha = load_contract(contract_path)
    card = dict((contract.get("sleeper") or {}).get("scoringSettings") or {})
    if not card:
        raise SystemExit(f"{contract_path} carries no sleeper.scoringSettings")
    params = load_param_set()

    # ── projection records: the production snapshot, or an in-memory proxy ──
    def proxy_records(fn: Callable) -> tuple[list, str]:
        baseline.compute_weekly_points = fn
        try:
            records, _summary = baseline.fetch_and_build_baseline(
                season=season,
                as_of=datetime.now(timezone.utc).date().isoformat(),
                scoring_settings=card,
                seasons_back=3,
                pbp_for_season=SeasonPbpIndex().for_season,
            )
        finally:
            baseline.compute_weekly_points = deployed_fn
        return records, datetime.now(timezone.utc).date().isoformat()

    snapshot_path: Path | None = None
    if args.proxy_baseline:
        records, snap_as_of = proxy_records(current_mod.compute_weekly_points)
        snapshot_receipt = {
            "mode": "proxy_reconstructed_baseline_in_memory",
            "scoredWith": "current",
            "records": len(records),
            "proxyRecords": sum(1 for r in records if r.is_proxy),
        }
    else:
        snapshot_path = args.snapshot or latest_snapshot_path(season)
        if snapshot_path is None or not snapshot_path.exists():
            print(
                f"BLOCKED: no BDVM projection snapshot for season {season} "
                f"(looked in {args.snapshot or 'data/bdvm/projections/'}). "
                "On a machine without one, re-run with --proxy-baseline.",
                file=sys.stderr,
            )
            return 2
        snap_as_of, records = load_snapshot(snapshot_path)
        snapshot_receipt = {
            "mode": "production_snapshot_read_only",
            "path": str(snapshot_path),
            "sha256": _sha256_file(snapshot_path),
            "asOf": snap_as_of,
            "records": len(records),
            "proxyRecords": sum(1 for r in records if r.is_proxy),
        }

    # ── the in-season feed, scored twice ─────────────────────────────────────
    rows = ingest.fetch_weekly_stats([int(actuals_season)], cache_only=args.cache_only) or []
    pbp = default_pbp_stats(int(actuals_season))

    def feed(fn: Callable):
        actuals.compute_weekly_points = fn
        try:
            return actuals.weekly_points_from_rows(
                rows,
                card,
                season=int(actuals_season),
                name_normalizer=normalize_player_name,
                pbp_stats=pbp,
            )
        finally:
            actuals.compute_weekly_points = deployed_fn

    act_current = feed(current_mod.compute_weekly_points)
    act_corrected = feed(corrected_fn)
    if act_corrected[0] is None:
        # Both arms would be the preseason board and the diff a meaningless 0.
        print(
            f"BLOCKED: no {actuals_season} weekly rows "
            f"({'materialised cache empty' if args.cache_only else 'fetch returned none'}).",
            file=sys.stderr,
        )
        return 2

    roster_settings, idp_enabled, scoring_profile = bdvm_api._registry_settings_for(args.league_key)
    context = bdvm_api._context_for(season)
    schedule = bdvm_api._schedule_for(season)
    waiver_cfg = params["replacement"]
    cfg_meta = from_contract(
        contract,
        league_key=args.league_key,
        registry_roster_settings=roster_settings,
        idp_enabled=idp_enabled,
        scoring_profile=scoring_profile,
        waiver_buffer=waiver_cfg["waiver_buffer"],
        default_buffer=float(waiver_cfg["default_buffer"]),
    ).to_meta()

    def value(recs: list, act, fn: Callable) -> tuple[dict, dict, dict]:
        # Projection records that carry a stat line are re-scored inside
        # ``run_valuation`` by ``src.bdvm.scoring`` through the same function,
        # so each arm scores its projections with its own scorer too.
        bdvm_scoring.compute_weekly_points = fn
        try:
            payload = run_valuation(
                contract,
                league_key=args.league_key,
                params=params,
                registry_roster_settings=roster_settings,
                idp_enabled=idp_enabled,
                scoring_profile=scoring_profile,
                projection_records=recs,
                snapshot_as_of=snap_as_of,
                season=season,
                context=context,
                schedule_weeks=schedule,
                actuals=act,
            )
        finally:
            bdvm_scoring.compute_weekly_points = deployed_fn
        if payload.get("status") != "ok":
            raise SystemExit(
                f"run_valuation status {payload.get('status')}: {payload.get('message')}"
            )
        analysis = analyze_rosters(payload, contract, params, league_cfg_meta=cfg_meta)
        scan = scan_double_positive_trades(analysis, params)
        return payload, analysis, scan

    arms = {
        "current": value(records, act_current, current_mod.compute_weekly_points),
        "corrected": value(records, act_corrected, corrected_fn),
    }
    if args.proxy_baseline and args.proxy_rebuilt_arm:
        rebuilt, _ = proxy_records(corrected_fn)
        arms["correctedAfterBaselineRebuild"] = value(rebuilt, act_corrected, corrected_fn)

    rostered = _rostered(contract)

    def roster_diff(a: Mapping[str, Any], b: Mapping[str, Any]) -> list[dict]:
        out = []
        rb = {str(r.get("ownerId") or r.get("name")): r for r in a.get("rosters") or []}
        for r in b.get("rosters") or []:
            k = str(r.get("ownerId") or r.get("name"))
            prev = rb.get(k) or {}
            caps_b, caps_n = prev.get("capitals") or {}, r.get("capitals") or {}
            out.append(
                {
                    "team": f"roster:{r.get('rosterId') or r.get('roster_id') or '?'}",
                    "capitalCurrent": caps_b,
                    "capitalCorrected": caps_n,
                    "capitalDelta": {
                        s: round(float(caps_n.get(s) or 0) - float(caps_b.get(s) or 0), 1)
                        for s in sorted(set(caps_b) | set(caps_n))
                        if isinstance(caps_n.get(s, 0), (int, float))
                    },
                    "directionCurrent": prev.get("direction"),
                    "directionCorrected": r.get("direction"),
                    "starterFpgCurrent": prev.get("starterFpg"),
                    "starterFpgCorrected": r.get("starterFpg"),
                }
            )
        return out

    def scan_diff(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict:
        ka, kb = set(_trade_keys(a)), set(_trade_keys(b))
        return {
            "tradesCurrent": len(a.get("trades") or []),
            "tradesCorrected": len(b.get("trades") or []),
            "unchanged": len(ka & kb),
            "onlyCurrent": len(ka - kb),
            "onlyCorrected": len(kb - ka),
        }

    cur = arms["current"]
    out: dict[str, Any] = {
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "receipts": {
            "baseRef": None if args.app_dir is not None else args.base_ref,
            "currentScorerSha256": current_sha,
            "correctedScorerSha256": corrected_sha,
            "mode": "box" if args.app_dir is not None else "dev",
            "contract": {
                "path": str(contract_path.resolve().relative_to(REPO))
                if contract_path.resolve().is_relative_to(REPO)
                else str(contract_path),
                "sha256": contract_sha,
                "generatedAt": contract.get("generatedAt"),
            },
            "snapshot": snapshot_receipt,
            "season": season,
            "actualsSeason": actuals_season,
            "weeklyRows": len(rows),
            "weeklyRowsCanonicalSha256": _sha256_bytes(
                json.dumps(rows, sort_keys=True, default=str).encode()
            ),
            "maxWeekObserved": (act_corrected[0] - 1) if act_corrected[0] else None,
            "pbpArtifactSha256": _sha256_file(pbp_weekly_path(int(actuals_season))),
            "scoringCardEntries": len(card),
            "paramSetId": params.param_set_id,
            "contextPlayers": len(context or {}),
            "scheduleAvailable": bool(schedule),
            "cacheOnly": args.cache_only,
        },
        "actualsFeed": {
            "playersWithSamplesCurrent": len(act_current[1]),
            "playersWithSamplesCorrected": len(act_corrected[1]),
            "playersWhoseWeeklyPointsChanged": sum(
                1
                for k in set(act_current[1]) | set(act_corrected[1])
                if dict(act_current[1].get(k, [])) != dict(act_corrected[1].get(k, []))
            ),
        },
    }
    for tag, arm in arms.items():
        if tag == "current":
            continue
        out[f"current_vs_{tag}"] = {
            "values": diff_payloads(cur[0], arm[0], rostered),
            "rosters": roster_diff(cur[1], arm[1]),
            "tradeScan": scan_diff(cur[2], arm[2]),
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8")
    v = out["current_vs_corrected"]["values"]
    print(
        f"priced {v['pricedCurrent']}/{v['pricedCorrected']}; value changed {v['valueChanged']}; "
        f"rank changed {v['rankChanged']}; replacement changed {v['replacementChanged']}; "
        f"signal flips {v['signalFlips']['count']} (rostered {v['signalFlips']['rosteredCount']}); "
        f"alert transitions {v['alertTransitionsRostered']['count']}; "
        f"trades {out['current_vs_corrected']['tradeScan']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
