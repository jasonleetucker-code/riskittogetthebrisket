#!/usr/bin/env python3
"""Roster Construction V1 host-parity census (owner decision D1, 2026-11-01).

For every finalized team-week of one league-season, compare the points the host
(Sleeper) AWARDED with the points of the legal optimal lineup Roster
Construction recomputes from the same week's roster and per-player points
(``src.roster_intel.construction.solve_team_week`` — the one solver, through
``src.ros.lineup``).  It reads exactly what ``GET /api/roster-construction``
reads: the league snapshot (``build_public_snapshot``, Sleeper's public
read-only API) converted by
``src.api.roster_construction_api.season_input_from_snapshot``.

Per team-week it records: Sleeper points, recomputed points, absolute
discrepancy, the slot configuration used, coverage (roster size, players
without a recorded score, host lineup size), and the exclusion / contradiction
label.  Every mismatch is diagnosed against the host's own counted lineup.

MISSING IS NEVER ZERO: a team-week without a host score, or with a rostered
player whose score is absent, is reported with ``null`` fields and a named
reason — it is never counted as a 0-point match.

Exit codes: 0 = every comparable team-week of every requested season matches
within tolerance; 1 = at least one comparable mismatch; 2 = input unavailable
(snapshot could not be loaded or fetched, unknown season).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.api import roster_construction_api as rc_api  # noqa: E402
from src.public_league import metrics  # noqa: E402
from src.public_league import player_impact as pi  # noqa: E402
from src.roster_intel import construction as rc  # noqa: E402

DEFAULT_OUT_DIR = REPO_ROOT / "docs" / "roster_construction" / "evidence"

# Census classifications (one per team-week).
C_MATCH = "match"
C_MISMATCH = "mismatch"
C_WITHHELD = "withheld"


def _load_snapshot(path: Path | None, league_id: str):
    from src.public_league.snapshot_store import snapshot_from_dict

    if path is not None:
        return snapshot_from_dict(json.loads(path.read_text(encoding="utf-8")))
    from src.public_league.snapshot import build_public_snapshot

    return build_public_snapshot(league_id)


def _diagnose_mismatch(sol: rc.TeamWeekSolution, team: rc.TeamWeekIn, si) -> dict[str, Any]:
    """Root-cause evidence for one host-score mismatch."""
    counted = list(team.counted)
    counted_pts = [team.points.get(p) for p in counted]
    counted_sum = (
        round(sum(float(p) for p in counted_pts), 2)
        if counted and all(p is not None for p in counted_pts)
        else None
    )
    ours = sol.assigned_ids
    host = set(counted)
    return {
        "hostCountedSum": counted_sum,
        "hostCountedMatchesHostScore": (
            None
            if counted_sum is None or team.score is None
            else abs(counted_sum - float(team.score)) <= 0.011
        ),
        "hostLineupSize": len(counted),
        "configuredSlotCount": len(si.slots),
        "onlyInRecomputed": sorted(ours - host),
        "onlyInHostLineup": sorted(host - ours),
        "hostLineupPlayersNotOnRoster": sorted(host - set(team.roster)),
        "unobservedRosterPlayers": list(sol.unobserved),
    }


def census_season(
    snapshot,
    season,
    *,
    tolerance: float,
    include_playoffs: bool,
    nfl_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # The route's own week-finality rule: weeks the host has not finalized are
    # removed before the contradiction test and reported, never compared.
    finality = metrics.host_lineups_open_from_week(season, nfl_state)
    si = rc_api.season_input_from_snapshot(
        snapshot, season, include_playoffs=include_playoffs, host_finality=finality
    )
    host_open = {
        int(e["week"]): e["reason"]
        for e in si.excluded_weeks
        if str(e.get("reason", "")).startswith("host_week_")
    }
    si_all = rc_api.season_input_from_snapshot(snapshot, season, include_playoffs=include_playoffs)
    rows: list[dict[str, Any]] = []
    for wk in sorted(si_all.weeks):
        for team in sorted(si_all.weeks[wk], key=lambda t: t.roster_id):
            if wk in host_open:
                # Evidence only: what the host recorded vs the optimum, while
                # the host still displays the week.  Never served, never a
                # contradiction.
                pre = rc.solve_team_week(
                    team,
                    wk,
                    rc.SeasonInput(
                        season=si_all.season,
                        slots=si_all.slots,
                        slot_source=si_all.slot_source,
                        lineup_mode=si_all.lineup_mode,
                        weeks=si_all.weeks,
                        players=si_all.players,
                    ),
                    tolerance=tolerance,
                )
                rows.append(
                    {
                        "week": wk,
                        "rosterId": team.roster_id,
                        "sleeperPoints": team.score,
                        "recomputedPoints": pre.score,
                        "absDiscrepancy": (
                            None
                            if team.score is None or pre.score is None
                            else round(abs(float(pre.score) - float(team.score)), 4)
                        ),
                        "classification": C_WITHHELD,
                        "label": host_open[wk],
                        "lineupIdenticalToHost": None,
                        "coverage": {
                            "rosterSize": len(set(team.roster)),
                            "unobservedPlayers": len(pre.unobserved),
                            "hostLineupSize": len(team.counted),
                            "configuredSlots": len(si_all.slots),
                            "unfilledSlots": list(pre.unfilled_slots),
                        },
                    }
                )
                continue
            sol = rc.solve_team_week(team, wk, si, tolerance=tolerance)
            # Recompute even for a contradicted week, for evidence only: the
            # product never serves this number (the week is withheld).
            recomputed = sol.score
            if recomputed is None and si.slots:
                unlabelled = rc.SeasonInput(
                    season=si.season,
                    slots=si.slots,
                    slot_source=si.slot_source,
                    lineup_mode=si.lineup_mode,
                    weeks=si.weeks,
                    players=si.players,
                )
                recomputed = rc.solve_team_week(team, wk, unlabelled, tolerance=tolerance).score
            host = team.score
            diff = (
                None
                if host is None or recomputed is None
                else round(abs(float(recomputed) - float(host)), 4)
            )
            lineup_size = len(team.counted)
            if sol.reason == rc.X_CONTRADICTED:
                classification = C_WITHHELD
                label = "contradicted_settings:" + ",".join(si.contradicted.get(wk, ()))
            elif host is None:
                classification, label = C_WITHHELD, "host_score_missing"
            elif sol.unobserved:
                classification, label = C_WITHHELD, rc.X_POINTS_INCOMPLETE
            elif sol.valid:
                classification, label = C_MATCH, sol.parity
            else:
                classification, label = C_MISMATCH, sol.reason
            row = {
                "week": wk,
                # Keyed by rosterId only: the evidence is committed to a
                # public repository, so no manager display name is written.
                "rosterId": team.roster_id,
                "sleeperPoints": host,
                "recomputedPoints": recomputed,
                "absDiscrepancy": diff,
                "classification": classification,
                "label": label,
                # Same players as the host's awarded lineup (position attribution
                # follows the lineup, so this is the attribution check).
                "lineupIdenticalToHost": (
                    sol.assigned_ids == frozenset(team.counted) if sol.valid else None
                ),
                "coverage": {
                    "rosterSize": len(set(team.roster)),
                    "unobservedPlayers": len(sol.unobserved),
                    "hostLineupSize": lineup_size,
                    "configuredSlots": len(si.slots),
                    "unfilledSlots": list(sol.unfilled_slots),
                },
            }
            if classification == C_MISMATCH or (
                classification == C_WITHHELD and diff is not None and diff > tolerance
            ):
                row["diagnosis"] = _diagnose_mismatch(sol, team, si)
            rows.append(row)
    counts = Counter(r["classification"] for r in rows)
    labels = Counter(r["label"] for r in rows if r["classification"] != C_MATCH)
    comparable = [r for r in rows if r["classification"] in (C_MATCH, C_MISMATCH)]
    diffs = [r["absDiscrepancy"] for r in comparable if r["absDiscrepancy"] is not None]
    return {
        "season": si.season,
        "leagueId": season.league_id,
        "slotConfig": {
            "slots": list(si.slots),
            "slotCount": len(si.slots),
            "slotSource": si.slot_source,
            "lineupMode": si.lineup_mode,
        },
        "weeksIncluded": sorted(si.weeks),
        "hostFinality": {"openFromWeek": finality[0], "reason": finality[1]},
        "lineupConfigStatus": rc_api.lineup_config_status(
            si, is_current=season is snapshot.current_season
        ),
        "weeksNotFinal": sorted(e["week"] for e in si.excluded_weeks),
        "contradictedWeeks": {str(k): list(v) for k, v in sorted(si.contradicted.items())},
        "summary": {
            "teamWeeks": len(rows),
            "comparable": len(comparable),
            "matches": counts.get(C_MATCH, 0),
            "mismatches": counts.get(C_MISMATCH, 0),
            "withheld": counts.get(C_WITHHELD, 0),
            "lineupIdenticalToHost": sum(1 for r in rows if r["lineupIdenticalToHost"] is True),
            "withheldOrMismatchLabels": dict(sorted(labels.items())),
            "maxAbsDiscrepancyComparable": max(diffs) if diffs else None,
        },
        "teamWeeks": rows,
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Roster Construction host-parity census — {report['generatedAt'][:10]}",
        "",
        "Generated by `scripts/roster_construction_parity_census.py` "
        f"(snapshot `{report['snapshotGeneratedAt']}`, league `{report['leagueKey']}`, "
        f"tolerance {report['tolerance']} points from `config/roster_construction/v1.json`).",
        "Full per-team-week data: the sibling `.json` file.",
        "",
        "| season | slots | team-weeks | comparable | match | mismatch | withheld "
        "| lineup = host | max abs diff |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s in report["seasons"]:
        sm = s["summary"]
        lines.append(
            f"| {s['season']} | {s['slotConfig']['slotCount']} | {sm['teamWeeks']} | "
            f"{sm['comparable']} | {sm['matches']} | {sm['mismatches']} | {sm['withheld']} | "
            f"{sm['lineupIdenticalToHost']} | {sm['maxAbsDiscrepancyComparable']} |"
        )
    for s in report["seasons"]:
        sm = s["summary"]
        lines += [
            "",
            f"## {s['season']}",
            "",
            f"- Configured slots ({s['slotConfig']['slotCount']}, "
            f"source `{s['slotConfig']['slotSource']}`, mode `{s['slotConfig']['lineupMode']}`): "
            + ", ".join(s["slotConfig"]["slots"]),
            f"- Finalized weeks included: {s['weeksIncluded']}; not final: {s['weeksNotFinal']}",
            f"- Contradicted weeks: {s['contradictedWeeks'] or 'none'}",
            f"- Withheld / mismatch labels: {sm['withheldOrMismatchLabels'] or 'none'}",
        ]
        bad = [r for r in s["teamWeeks"] if r["classification"] == C_MISMATCH]
        if bad:
            lines += ["", "Mismatches:", ""]
            for r in bad:
                lines.append(
                    f"- week {r['week']} roster {r['rosterId']}: Sleeper {r['sleeperPoints']} vs "
                    f"recomputed {r['recomputedPoints']} (diff {r['absDiscrepancy']}); "
                    f"diagnosis {json.dumps(r.get('diagnosis'))}"
                )
    if report.get("findings"):
        lines += ["", "## Findings", ""] + [f"- {f}" for f in report["findings"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--league-key", default="dynasty_main")
    ap.add_argument("--season", action="append", help="season year (repeatable; default: all)")
    ap.add_argument("--snapshot", type=Path, help="saved snapshot JSON (else fetch from Sleeper)")
    ap.add_argument("--include-playoffs", action="store_true")
    ap.add_argument(
        "--nfl-state",
        type=Path,
        help="saved Sleeper /state/nfl JSON (else fetched live; unreadable = unknown)",
    )
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--stem", default=None, help="output file stem (default PARITY_CENSUS_<date>)")
    ap.add_argument("--finding", action="append", default=[], help="investigation note for .md")
    args = ap.parse_args(argv)

    from src.api import league_registry

    cfg = league_registry.get_league_by_key(args.league_key)
    if cfg is None or not cfg.sleeper_league_id:
        print(f"unknown league {args.league_key}", file=sys.stderr)
        return 2
    try:
        snapshot = _load_snapshot(args.snapshot, str(cfg.sleeper_league_id))
    except (OSError, ValueError) as exc:
        print(f"snapshot unavailable: {exc}", file=sys.stderr)
        return 2
    if not snapshot.seasons:
        print("snapshot has no seasons", file=sys.stderr)
        return 2
    wanted = args.season or [s.season for s in snapshot.seasons]
    tol = float(rc_api.load_priors().get("hostScoreTolerance", 0.011))
    if args.nfl_state is not None:
        nfl_state = json.loads(args.nfl_state.read_text(encoding="utf-8"))
    else:
        from src.public_league.sleeper_client import fetch_nfl_state

        nfl_state = fetch_nfl_state()
    seasons = []
    for year in wanted:
        target = snapshot.season_by_year(str(year))
        if target is None:
            print(f"unknown season {year}", file=sys.stderr)
            return 2
        seasons.append(
            census_season(
                snapshot,
                target,
                tolerance=tol,
                include_playoffs=args.include_playoffs,
                nfl_state=nfl_state if isinstance(nfl_state, dict) else None,
            )
        )
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report = {
        "schema": "roster_construction_parity_census.v1",
        "generatedAt": now,
        "snapshotGeneratedAt": snapshot.generated_at,
        "leagueKey": args.league_key,
        "tolerance": tol,
        "lineupSolver": "src.ros.lineup.solve_optimal_assignment via construction.solve_team_week",
        "contradictionOwner": "src.public_league.player_impact.detect_contradictions",
        "bestBallFlag": {s.season: pi.best_ball_rule(s) for s in snapshot.seasons},
        "hostNflState": {
            k: (nfl_state or {}).get(k)
            for k in ("season", "season_type", "week", "leg", "display_week")
        }
        if isinstance(nfl_state, dict)
        else None,
        "findings": list(args.finding),
        "seasons": seasons,
    }
    stem = args.stem or f"PARITY_CENSUS_{now[:10]}"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / f"{stem}.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (args.out_dir / f"{stem}.md").write_text(_markdown(report), encoding="utf-8")
    for s in seasons:
        print(s["season"], json.dumps(s["summary"]))
    return 1 if any(s["summary"]["mismatches"] for s in seasons) else 0


if __name__ == "__main__":
    raise SystemExit(main())
