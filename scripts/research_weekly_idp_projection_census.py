"""Weekly IDP projection source census by DL / LB / DB (read-only research).

For each reachable weekly IDP projection source: coverage, MAE / RMSE / bias,
calibration, freshness (point-in-time lineage) and incremental accuracy over
the live source, scored under the league's exact card.  Seasons are never
pooled (2025 was not best ball; see the 2026-10-29 backtest).

Changes nothing: no ensemble weight, flag or config is touched.  FPTrack is
fetched in THIS process only (its flag is forced on in-process for the read),
one GET per week, 1 s apart.

    python scripts/research_weekly_idp_projection_census.py \
        --out docs/waivers/evidence/idp_streaming/projection_census_2026-11-01.json
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.waivers.streaming_backtest import (  # noqa: E402
    IDP_GROUPS,
    RESEARCH_DIR,
    DiskCache,
    _rounded,
    _season_weeks,
    load_season,
)
from src.waivers.streaming_point_in_time import (  # noqa: E402
    POST_KICKOFF,
    PRE_KICKOFF,
    UNSTAMPED,
    archive_snapshot_audit,
    classify_projection_timestamp,
    error_summary,
    projection_error_rows,
)


def _calibration(pairs: list[tuple[float, float]]) -> dict[str, Any]:
    """Quintiles of projected points: mean projected vs mean realized, plus
    the OLS slope of realized on projected (1.0 = calibrated scale)."""
    if len(pairs) < 25:
        return {"n": len(pairs), "bins": None, "slope": None}
    pairs = sorted(pairs)
    k = 5
    bins = []
    for i in range(k):
        chunk = pairs[i * len(pairs) // k : (i + 1) * len(pairs) // k]
        bins.append(
            {
                "n": len(chunk),
                "meanProjected": statistics.fmean(p for p, _ in chunk),
                "meanRealized": statistics.fmean(r for _, r in chunk),
            }
        )
    mx = statistics.fmean(p for p, _ in pairs)
    my = statistics.fmean(r for _, r in pairs)
    sxx = sum((p - mx) ** 2 for p, _ in pairs)
    slope = sum((p - mx) * (r - my) for p, r in pairs) / sxx if sxx else None
    return {"n": len(pairs), "bins": bins, "slope": slope}


def _rotowire_cells(data: Any, dump: Any) -> dict[str, Any]:
    rows = projection_error_rows(data, dump)
    out: dict[str, Any] = {"byGroup": {}, "byTimestampClass": {}, "subgroups": {}}
    played_by_group: dict[str, int] = {g: 0 for g in IDP_GROUPS}
    for w in data.weeks:
        for pid in data.played.get(w, ()):
            info = data.players.get(pid)
            if info and info.group:
                played_by_group[info.group] += 1
    for g in IDP_GROUPS:
        sel = [r for r in rows if r.group == g and r.realized is not None]
        errs = [r.projected - r.realized for r in sel]
        out["byGroup"][g] = {
            **error_summary(errs),
            "coverageOfPlayedPlayerWeeks": (len(sel) / played_by_group[g])
            if played_by_group[g]
            else None,
            "playedPlayerWeeks": played_by_group[g],
            "lateInactives": sum(1 for r in rows if r.group == g and r.late_inactive),
            "calibration": _calibration([(r.projected, r.realized) for r in sel]),
        }
        for cls in (PRE_KICKOFF, POST_KICKOFF, UNSTAMPED):
            cs = [r.projected - r.realized for r in sel if r.timestamp_class == cls]
            out["byTimestampClass"].setdefault(cls, {})[g] = error_summary(cs)
        sub: dict[str, Any] = {}
        for name, pred in (
            ("afterBye", lambda r: r.after_bye is True),
            ("notAfterBye", lambda r: r.after_bye is False),
            ("rookie", lambda r: r.rookie is True),
            ("veteran", lambda r: r.rookie is False),
            ("firstAppearance", lambda r: r.first_appearance),
            ("returningPlayer", lambda r: not r.first_appearance),
        ):
            sub[name] = error_summary([r.projected - r.realized for r in sel if pred(r)])
        late = [r for r in rows if r.group == g and r.late_inactive]
        sub["lateInactiveHostRule"] = {
            **error_summary([r.projected for r in late]),
            "note": "projected > 0, no stat line; the host scores 0, so the error is the projection",
        }
        out["subgroups"][g] = sub
    stamps = [r.timestamp_class for r in rows]
    out["timestampClassCounts"] = {
        c: stamps.count(c) for c in (PRE_KICKOFF, POST_KICKOFF, UNSTAMPED)
    }
    return out


def _fptrack(data: Any, weeks: list[int], season: int, dump: Any) -> dict[str, Any]:
    os.environ.setdefault("RISKIT_FEATURE_FPTRACK_WEEKLY_PROJECTIONS", "1")
    from src.api import feature_flags
    from src.identity.directory_cache import get_default_sleeper_index
    from src.ros import fptrack_weekly_projections as fp

    feature_flags.reload()
    from src.identity.resolution import build_sleeper_index

    index = get_default_sleeper_index()
    index_source = "directory_cache"
    if index is None and dump:
        index, index_source = build_sleeper_index(dump), "cached_players_nfl_dump"
    out: dict[str, Any] = {"weeks": {}, "identityIndex": index_source if index else None}
    errs: dict[str, list[float]] = {g: [] for g in IDP_GROUPS}
    overlap: dict[str, list[tuple[float, float, float]]] = {g: [] for g in IDP_GROUPS}
    fill: dict[str, list[float]] = {g: [] for g in IDP_GROUPS}
    if index is None:
        out["status"] = "identity_directory_unavailable"
        return out
    resolver = fp.exact_identity_resolver(index)
    for w in weeks:
        res = fp.fetch_weekly_projection_payload(season, w)
        cell: dict[str, Any] = {"status": res.status}
        time.sleep(1.0)
        if res.status != "ok":
            cell["reason"] = getattr(res, "reason", None)
            out["weeks"][str(w)] = cell
            continue
        try:
            mapped, parsed = fp.build_weekly_observations(
                res.payload,
                season=season,
                week=w,
                observed_at=res.observed_at,
                scoring_settings=dict(data.scoring),
                resolve_player=resolver,
            )
        except Exception as exc:  # noqa: BLE001 — reported, never guessed
            cell.update(status="unusable", reason=str(exc)[:200])
            out["weeks"][str(w)] = cell
            continue
        obs = {o.sleeper_player_id: o for o in mapped.batch.observations}
        cell.update(
            observations=len(obs),
            refused=dict(mapped.batch.refused),
            unresolved=len(mapped.unresolved_players),
            observedAt=mapped.batch.observed_at,
            timestampClass=classify_projection_timestamp(mapped.batch.observed_at, data.cutoffs[w]),
        )
        played = data.played.get(w, frozenset())
        rw = data.projections.get(w, {})
        for pid, o in obs.items():
            info = data.players.get(pid)
            if not info or not info.group or pid not in played:
                continue
            real = data.realized(w, pid)
            e = o.league_scored_points - real
            errs[info.group].append(e)
            if pid in rw:
                overlap[info.group].append((o.league_scored_points, rw[pid].points, real))
            else:
                fill[info.group].append(e)
        out["weeks"][str(w)] = cell
    out["byGroup"] = {}
    for g in IDP_GROUPS:
        ov = overlap[g]
        out["byGroup"][g] = {
            "fptrack": error_summary(errs[g]),
            "overlapWithRotowire": {
                "fptrack": error_summary([f - r for f, _, r in ov]),
                "rotowire": error_summary([s - r for _, s, r in ov]),
                "meanOfBoth_DIAGNOSTIC_shared_lineage": error_summary(
                    [(f + s) / 2 - r for f, s, r in ov]
                ),
                "correlationOfErrors": _corr([f - r for f, _, r in ov], [s - r for _, s, r in ov]),
            },
            "fillInWhereRotowireSilent": error_summary(fill[g]),
        }
    return out


def _corr(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3:
        return None
    try:
        return statistics.correlation(a, b)
    except statistics.StatisticsError:
        return None


def main(argv: list[str] | None = None) -> int:
    from src.public_league import sleeper_client

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seasons", default="2026,2025")
    ap.add_argument("--weeks-2026", default="1,2,3,4,5,6,7")
    ap.add_argument("--no-fptrack", action="store_true")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    registry = json.loads((REPO / "config/leagues/registry.json").read_text(encoding="utf-8"))
    start_id = next(
        str(lg["sleeperLeagueId"]) for lg in registry["leagues"] if lg.get("key") == "dynasty_main"
    )
    cache = DiskCache(RESEARCH_DIR / "raw")
    chain = cache.get("chain", lambda: sleeper_client.walk_league_chain(start_id))
    dump = cache.get("players_nfl", sleeper_client.fetch_nfl_players)
    evidence: dict[str, Any] = {
        "schema": "weekly_idp_projection_census_v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": (
            "Read-only. Every locally available provider row was fetched after its "
            "week's kickoff, so every error here is a POST-KICKOFF (hindsight-exposed) "
            "error, not a historical forecast error. Seasons are never pooled."
        ),
        "seasons": {},
    }
    for season in (int(s) for s in args.seasons.split(",")):
        league = next(lg for lg in chain if int(lg["season"]) == season)
        weeks = _season_weeks(league)
        if season == 2026:
            pinned = [int(w) for w in args.weeks_2026.split(",")]
            weeks = [w for w in weeks if w in pinned]
        data, _priv = load_season(league, weeks, cache=cache, players_dump=dump)
        cell: dict[str, Any] = {
            "weeks": list(data.weeks),
            "lineupQuantity": "host_awarded_best_ball_points"
            if data.best_ball_verified
            else "optimal_lineup_POTENTIAL_points",
            "rotowireViaSleeper": _rotowire_cells(data, dump),
            "w1ArchiveAudit": archive_snapshot_audit(season, list(data.weeks), data.cutoffs),
        }
        if season == 2026 and not args.no_fptrack:
            cell["fptrack"] = _fptrack(data, list(data.weeks), season, dump)
        evidence["seasons"][str(season)] = cell
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(_rounded(evidence), indent=1, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(f"census -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
