#!/usr/bin/env python3
"""Preregistered D11 comparison: playoff/title odds with ROS evidence counted once.

Owner Decision 11 (2026-10-18).  The preregistration — arms, data, metrics,
gates and the disposition rule — is
``docs/research/PLAYOFF_ROS_D11_PREREGISTRATION.md`` and was committed before
this script was first run.  This script implements it; it does not decide
anything the preregistration did not already decide.

Two subcommands:

``capture``   reads Sleeper's public API for every active registry league and
              writes one compact, reproducible input file: league settings,
              roster→owner map, every FINAL regular-season week's matchups
              (roster players and points) and the metadata of every player
              those rosters name.
``evaluate``  reads only that file plus tracked repository data
              (``data/ros/aggregate/history``) and scores the three arms
              (incumbent, corrected, mean-only) through the PRODUCTION
              equations in ``src.ros.playoff_sim``.  ``--current`` additionally
              builds each league's live public snapshot and simulates today's
              playoff / title odds under the incumbent and the corrected arm.

Exit code 0 on a completed evaluation regardless of the verdict (the verdict
is data in the output), 2 when inputs are missing or unusable.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.api.league_registry import active_leagues, get_league_by_key  # noqa: E402
from src.league_intel.sim_calibration import load_points_model  # noqa: E402
from src.public_league import sleeper_client  # noqa: E402
from src.ros import playoff_sim  # noqa: E402
from src.ros.game_day_sim import median_threshold  # noqa: E402
from src.ros.lineup import load_league_starter_slots  # noqa: E402
from src.ros.team_strength import compute_team_strength, hydrate_roster_players  # noqa: E402

AGG_HISTORY = REPO_ROOT / "data" / "ros" / "aggregate" / "history"
AGG_LATEST = REPO_ROOT / "data" / "ros" / "aggregate" / "latest.json"
SIMS_DIR = REPO_ROOT / "data" / "ros" / "sims"

# ── Preregistered constants (§3, §6) ────────────────────────────────────────
DRAWS_PER_WEEK = 20_000
DRAW_SEED_BASE = 20261018
BOOTSTRAP_REPS = 10_000
BOOTSTRAP_SEED = 20261018
PROB_CLIP = 1e-6
CUTOFF_UTC = time(22, 0, tzinfo=timezone.utc)
G2_MARGIN = 0.03
G3_SLACK = 0.05
G4_SLACK = 0.05
G5_MARGIN = 0.03
G6_SUM_TOL = 0.005
CURRENT_SIMS = 20_000
CURRENT_SEED = 7

ARM_I = "incumbent"
ARM_C = "corrected"
ARM_CM = "mean_only"
ARMS = (ARM_I, ARM_C, ARM_CM)

_PLAYER_KEYS = ("full_name", "first_name", "last_name", "position", "fantasy_positions")


# ── capture ─────────────────────────────────────────────────────────────────


def _final_weeks(league_id: str, state_week: int, playoff_start: int) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for week in range(1, min(state_week, playoff_start)):
        rows = sleeper_client.fetch_matchups(league_id, week) or []
        if not rows or any(
            not isinstance(r.get("points"), (int, float)) or r.get("matchup_id") is None
            for r in rows
        ):
            continue
        out[week] = [
            {
                "roster_id": r.get("roster_id"),
                "matchup_id": r.get("matchup_id"),
                "points": float(r.get("points")),
                "players": [str(p) for p in (r.get("players") or [])],
            }
            for r in rows
        ]
    return out


def capture(out_path: Path) -> int:
    state = sleeper_client.fetch_nfl_state() or {}
    state_week = int(state.get("week") or 0)
    if not state_week:
        print("capture: Sleeper NFL state unavailable", file=sys.stderr)
        return 2
    leagues: dict[str, Any] = {}
    needed: set[str] = set()
    for cfg in active_leagues():
        lid = str(cfg.sleeper_league_id)
        league = sleeper_client.fetch_league(lid) or {}
        settings = league.get("settings") or {}
        rosters = sleeper_client.fetch_rosters(lid) or []
        weeks = _final_weeks(lid, state_week, int(settings.get("playoff_week_start") or 15))
        for rows in weeks.values():
            for r in rows:
                needed.update(r["players"])
        leagues[cfg.key] = {
            "sleeperLeagueId": lid,
            "season": league.get("season"),
            "bestBall": bool(cfg.best_ball),
            "settings": {
                k: settings.get(k)
                for k in ("best_ball", "league_average_match", "playoff_week_start", "num_teams")
            },
            "rosterOwners": {
                str(r.get("roster_id")): str(r.get("owner_id") or "") for r in rosters
            },
            "finalWeeks": {str(w): rows for w, rows in weeks.items()},
        }
    dump = sleeper_client.fetch_nfl_players() or {}
    players = {
        pid: {k: (dump.get(pid) or {}).get(k) for k in _PLAYER_KEYS}
        for pid in sorted(needed)
        if pid in dump
    }
    payload = {
        "capturedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sleeperState": {
            k: state.get(k) for k in ("season", "week", "season_type", "season_start_date")
        },
        "leagues": leagues,
        "players": players,
        "playersMissingFromDump": sorted(needed - set(players)),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"capture: wrote {out_path} ({len(players)} players, {len(leagues)} leagues)")
    return 0


# ── point-in-time inputs ────────────────────────────────────────────────────


def week_cutoff(season_start: str, week: int) -> datetime:
    """Thursday of ``week``, 22:00 UTC (preregistration §2)."""
    start = date.fromisoformat(season_start)
    thursday = start + timedelta(days=(3 - start.weekday()) % 7)
    return datetime.combine(thursday + timedelta(days=7 * (week - 1)), CUTOFF_UTC)


def _stamp_of(path: Path) -> datetime:
    # 2026-04-28T04-29-48.019999+00-00.json → ISO
    stem = path.stem
    day, clock = stem.split("T", 1)
    clock = clock.replace("+00-00", "+00:00")
    hh, mm, rest = clock.split("-", 2)
    return datetime.fromisoformat(f"{day}T{hh}:{mm}:{rest}")


def nearest_prior_aggregate(cutoff: datetime) -> Path | None:
    best: tuple[datetime, Path] | None = None
    for path in AGG_HISTORY.glob("*.json"):
        try:
            stamp = _stamp_of(path)
        except ValueError:
            continue
        if stamp <= cutoff and (best is None or stamp > best[0]):
            best = (stamp, path)
    return best[1] if best else None


def _agg_players(path: Path) -> list[dict[str, Any]]:
    blob = json.loads(path.read_text(encoding="utf-8"))
    players = blob.get("players") if isinstance(blob, dict) else None
    return players if isinstance(players, list) else []


def _team_strength_rows(
    rows_by_roster: dict[str, list[str]],
    owners: dict[str, str],
    players_meta: dict[str, Any],
    aggregate: list[dict[str, Any]],
    slots: list[str],
) -> list[dict[str, Any]]:
    teams = []
    for rid, pids in rows_by_roster.items():
        oid = owners.get(rid) or ""
        if not oid:
            continue
        teams.append(
            {
                "ownerId": oid,
                "rosterId": rid,
                "teamName": oid,
                "players": hydrate_roster_players(pids, players_meta),
            }
        )
    return compute_team_strength(teams, aggregated_players=aggregate, starter_slots=slots)


def arm_distributions(
    per_owner: dict[str, list[float]],
    pool: list[float],
    rows: list[dict[str, Any]],
    *,
    best_ball: bool,
    slots: list[str],
    points_model: Any,
    weeks: list[int] | None = None,
    unavailable: set[tuple[str, int]] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """``{arm: {owner: _TeamDist}}`` and ``{owner: basis}`` — production equations."""
    ros_map = playoff_sim._ros_strength_from_rows(rows)
    depth = playoff_sim._depth_ratios_from_rows(rows)
    presim: dict[str, tuple[float, float]] = {}
    if best_ball:
        presim = playoff_sim._bestball_presim(
            playoff_sim._rosters_from_rows(rows),
            slots,
            random.Random(20260428),
            points_model,
            weeks=weeks,
            unavailable=unavailable,
        )
    out: dict[str, dict[str, Any]] = {}
    for arm, once in ((ARM_I, False), (ARM_C, True)):
        dists, _ = playoff_sim._team_distributions_from_inputs(
            per_owner,
            pool,
            ros_map,
            depth_ratios=depth,
            bestball_dists=presim,
            best_ball=best_ball,
            ros_counted_once=once,
        )
        out[arm] = dists
    # Cm: the corrected mean with the incumbent spread (reported, never gated).
    out[ARM_CM] = {
        o: playoff_sim._TeamDist(
            owner_id=o,
            mean=out[ARM_C][o].mean,
            sd=out[ARM_I][o].sd,
            pf_to_date=d.pf_to_date,
            basis=d.basis,
        )
        for o, d in out[ARM_I].items()
    }
    basis = {o: d.basis for o, d in out[ARM_I].items()}
    return out, basis


# ── scoring ─────────────────────────────────────────────────────────────────


def _ll(p: float, y: float) -> float:
    p = min(1.0 - PROB_CLIP, max(PROB_CLIP, p))
    return -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))


def _draw_matrix(dists: dict[str, Any], owners: list[str], seed: int) -> list[list[float]]:
    rng = random.Random(seed)
    return [
        [max(0.0, rng.gauss(dists[o].mean, dists[o].sd)) for o in owners]
        for _ in range(DRAWS_PER_WEEK)
    ]


def score_week(
    dists: dict[str, Any],
    realized: dict[str, float],
    pairs: list[tuple[str, str]],
    median_on: bool,
    seed: int,
) -> dict[str, list[dict[str, Any]]]:
    owners = sorted(realized)
    idx = {o: i for i, o in enumerate(owners)}
    draws = _draw_matrix(dists, owners, seed)
    out: dict[str, list[dict[str, Any]]] = {"h2h": [], "median": [], "score": []}
    for a, b in pairs:
        ia, ib = idx[a], idx[b]
        p = sum(
            1.0 if row[ia] > row[ib] else 0.5 if row[ia] == row[ib] else 0.0 for row in draws
        ) / len(draws)
        xa, xb = realized[a], realized[b]
        y = 1.0 if xa > xb else 0.5 if xa == xb else 0.0
        out["h2h"].append({"a": a, "b": b, "p": p, "y": y})
    if median_on:
        thresholds = [median_threshold(row) for row in draws]
        real_thr = median_threshold([realized[o] for o in owners])
        for o in owners:
            i = idx[o]
            p = sum(
                1.0 if row[i] > t else 0.5 if row[i] == t else 0.0
                for row, t in zip(draws, thresholds)
            ) / len(draws)
            x = realized[o]
            y = 1.0 if x > real_thr else 0.5 if x == real_thr else 0.0
            out["median"].append({"owner": o, "p": p, "y": y})
    for o in owners:
        i = idx[o]
        x = realized[o]
        u = sum(1 for row in draws if row[i] <= x) / len(draws)
        out["score"].append({"owner": o, "u": u, "x": x})
    return out


def _summary(records: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    h2h, med, sc = records["h2h"], records["median"], records["score"]
    binary = h2h + med

    def mean(xs: list[float]) -> float | None:
        return statistics.fmean(xs) if xs else None

    fav_p = [max(r["p"], 1 - r["p"]) for r in h2h]
    fav_y = [r["y"] if r["p"] >= 0.5 else 1 - r["y"] for r in h2h]
    us = [r["u"] for r in sc]
    return {
        "nH2h": len(h2h),
        "nMedian": len(med),
        "nScores": len(sc),
        "llH2h": mean([_ll(r["p"], r["y"]) for r in h2h]),
        "llMedian": mean([_ll(r["p"], r["y"]) for r in med]),
        "llBinary": mean([_ll(r["p"], r["y"]) for r in binary]),
        "brierBinary": mean([(r["p"] - r["y"]) ** 2 for r in binary]),
        "favMeanP": mean(fav_p),
        "favWinRate": mean(fav_y),
        "favCalibrationGap": (abs(mean(fav_p) - mean(fav_y)) if h2h else None),
        "pitMean": mean(us),
        "pitVar": statistics.pvariance(us) if len(us) > 1 else None,
        "cov80": mean([1.0 if 0.1 <= u <= 0.9 else 0.0 for u in us]),
    }


def _cluster_bootstrap(clusters: list[tuple[list[float], list[float]]]) -> dict[str, float]:
    """Δ = mean LL(C) − mean LL(I) over outcomes, resampling whole clusters."""
    rng = random.Random(BOOTSTRAP_SEED)

    def delta(sample: list[tuple[list[float], list[float]]]) -> float:
        c = [x for cl in sample for x in cl[0]]
        i = [x for cl in sample for x in cl[1]]
        return statistics.fmean(c) - statistics.fmean(i)

    point = delta(clusters)
    reps = sorted(
        delta([clusters[rng.randrange(len(clusters))] for _ in clusters])
        for _ in range(BOOTSTRAP_REPS)
    )
    return {
        "delta": point,
        "lo95": reps[int(0.025 * BOOTSTRAP_REPS)],
        "hi95": reps[int(0.975 * BOOTSTRAP_REPS) - 1],
        "clusters": len(clusters),
    }


# ── current state (§5) ──────────────────────────────────────────────────────


def _title_entropy(probs: list[float]) -> float:
    return -sum(p * math.log(p) for p in probs if p > 0)


def current_state(league_key: str, points_model: Any) -> dict[str, Any]:
    from src.public_league.snapshot import build_public_snapshot  # noqa: PLC0415

    cfg = get_league_by_key(league_key)
    snapshot = build_public_snapshot(str(cfg.sleeper_league_id))
    season = playoff_sim._simulated_season(snapshot)
    owners = {str(r.get("roster_id")): str(r.get("owner_id") or "") for r in (season.rosters or [])}
    rows = _team_strength_rows(
        {str(r.get("roster_id")): list(r.get("players") or []) for r in season.rosters or []},
        owners,
        snapshot.nfl_players,
        _agg_players(AGG_LATEST),
        load_league_starter_slots(league_key),
    )
    per_owner, pool = playoff_sim.playoff_odds._season_weekly_scores(season, snapshot.managers)
    weeks, unavailable, avail_basis = playoff_sim._presim_availability(
        league_key,
        (season.league or {}).get("settings"),
        season.season,
        playoff_sim._rosters_from_rows(rows),
    )
    arms, basis = arm_distributions(
        per_owner,
        pool,
        rows,
        best_ball=bool(cfg.best_ball),
        slots=load_league_starter_slots(league_key),
        points_model=points_model,
        weeks=weeks,
        unavailable=unavailable,
    )
    ros_map = playoff_sim._ros_strength_from_rows(rows)
    result: dict[str, Any] = {"availability": avail_basis, "basis": basis, "arms": {}}
    for arm in (ARM_I, ARM_C):
        dists = arms[arm]
        with (
            mock.patch.object(
                playoff_sim,
                "_build_team_distributions",
                lambda *a, _d=dists, **k: (_d, {o: d.pf_to_date for o, d in _d.items()}),
            ),
            mock.patch.object(playoff_sim, "_load_ros_strength_map", lambda *a, **k: ros_map),
        ):
            sim = playoff_sim.simulate_playoff_odds(
                snapshot,
                n_simulations=CURRENT_SIMS,
                rng=random.Random(CURRENT_SEED),
                points_model=points_model,
                distributions=dists,
            )
        teams = [
            {
                "ownerId": r.get("ownerId"),
                "displayName": r.get("displayName"),
                "playoffOdds": r.get("playoffOdds"),
                "championshipOdds": r.get("championshipOdds"),
                "mean": round(dists[r.get("ownerId")].mean, 2)
                if r.get("ownerId") in dists
                else None,
                "sd": round(dists[r.get("ownerId")].sd, 2) if r.get("ownerId") in dists else None,
            }
            for r in sim.get("playoffOdds") or []
        ]
        titles = [t["championshipOdds"] for t in teams if t["championshipOdds"] is not None]
        result["arms"][arm] = {
            "teams": teams,
            "nSimulations": sim.get("n_simulations"),
            "unsimulable": sim.get("unsimulable"),
            "championshipUnavailable": sim.get("championshipUnavailable"),
            "titleSum": round(sum(titles), 6) if titles else None,
            "maxTitle": max(titles) if titles else None,
            "titleEntropy": round(_title_entropy(titles), 4) if titles else None,
            "playoffInRange": all(
                t["playoffOdds"] is not None and 0.0 <= t["playoffOdds"] <= 1.0 for t in teams
            ),
        }
    published = SIMS_DIR / (
        "latest_championship.json"
        if league_key == "dynasty_main"
        else f"{league_key}_championship.json"
    )
    if published.exists():
        blob = json.loads(published.read_text(encoding="utf-8"))
        rows = blob.get("championshipOdds") or []
        result["publishedIncumbent"] = {
            "path": str(published.relative_to(REPO_ROOT)),
            "computedAt": blob.get("computedAt"),
            "unsimulable": blob.get("unsimulable"),
            "maxTitle": max(
                (
                    float(t.get("championshipOdds"))
                    for t in rows
                    if isinstance(t, dict) and isinstance(t.get("championshipOdds"), (int, float))
                ),
                default=None,
            ),
        }
    return result


# ── evaluate ────────────────────────────────────────────────────────────────


def evaluate(inputs_path: Path, out_path: Path, *, with_current: bool) -> int:
    if not inputs_path.exists():
        print(f"evaluate: {inputs_path} missing", file=sys.stderr)
        return 2
    inputs = json.loads(inputs_path.read_text(encoding="utf-8"))
    season_start = (inputs.get("sleeperState") or {}).get("season_start_date")
    if not season_start:
        print("evaluate: inputs carry no season_start_date", file=sys.stderr)
        return 2
    players_meta = inputs.get("players") or {}
    points_model = load_points_model()

    per_league: dict[str, Any] = {}
    records: dict[str, dict[str, dict[str, list]]] = {}
    clusters: list[tuple[str, int, dict[str, dict[str, list]]]] = []
    identical_by_league: dict[str, dict[str, float]] = {}
    pit_inputs: list[dict[str, Any]] = []

    for key, lg in sorted((inputs.get("leagues") or {}).items()):
        best_ball = bool(lg.get("bestBall"))
        median_on = int((lg.get("settings") or {}).get("league_average_match") or 0) == 1
        slots = load_league_starter_slots(key)
        owners = lg.get("rosterOwners") or {}
        weeks = sorted(int(w) for w in (lg.get("finalWeeks") or {}))
        realized_by_week: dict[int, dict[str, float]] = {}
        for w in weeks:
            realized_by_week[w] = {
                owners[str(r["roster_id"])]: float(r["points"])
                for r in lg["finalWeeks"][str(w)]
                if owners.get(str(r["roster_id"]))
            }
        league_records = {arm: {"h2h": [], "median": [], "score": []} for arm in ARMS}
        max_dmean = max_dsd = 0.0
        week_meta = []
        for w in weeks:
            cutoff = week_cutoff(season_start, w)
            agg_path = nearest_prior_aggregate(cutoff)
            if agg_path is None:
                week_meta.append({"week": w, "skipped": "no_aggregate_before_cutoff"})
                continue
            rows = _team_strength_rows(
                {str(r["roster_id"]): r["players"] for r in lg["finalWeeks"][str(w)]},
                owners,
                players_meta,
                _agg_players(agg_path),
                slots,
            )
            per_owner = {
                o: [realized_by_week[pw][o] for pw in weeks if pw < w and o in realized_by_week[pw]]
                for o in realized_by_week[w]
            }
            pool = [x for xs in per_owner.values() for x in xs]
            arms, basis = arm_distributions(
                per_owner, pool, rows, best_ball=best_ball, slots=slots, points_model=points_model
            )
            for o in realized_by_week[w]:
                max_dmean = max(max_dmean, abs(arms[ARM_C][o].mean - arms[ARM_I][o].mean))
                max_dsd = max(max_dsd, abs(arms[ARM_C][o].sd - arms[ARM_I][o].sd))
            by_matchup: dict[Any, list[str]] = {}
            for r in lg["finalWeeks"][str(w)]:
                oid = owners.get(str(r["roster_id"]))
                if oid:
                    by_matchup.setdefault(r["matchup_id"], []).append(oid)
            pairs = [tuple(sorted(v)) for v in by_matchup.values() if len(v) == 2]
            week_records = {}
            for arm in ARMS:
                week_records[arm] = score_week(
                    arms[arm], realized_by_week[w], pairs, median_on, DRAW_SEED_BASE + w
                )
                for kind in ("h2h", "median", "score"):
                    league_records[arm][kind].extend(week_records[arm][kind])
            if best_ball:
                clusters.append((key, w, week_records))
            week_meta.append(
                {
                    "week": w,
                    "cutoff": cutoff.isoformat(),
                    "aggregate": str(agg_path.relative_to(REPO_ROOT)),
                    "fidelity": "nearest-prior",
                    "bases": sorted(set(basis.values())),
                    "teams": {
                        o: {
                            arm: [round(arms[arm][o].mean, 2), round(arms[arm][o].sd, 2)]
                            for arm in ARMS
                        }
                        for o in sorted(realized_by_week[w])
                    },
                }
            )
            for o, x in realized_by_week[w].items():
                pit_inputs.append({"league": key, "week": w, "owner": o, "realized": x})
        records[key] = league_records
        identical_by_league[key] = {"maxAbsDeltaMean": max_dmean, "maxAbsDeltaSd": max_dsd}
        per_league[key] = {
            "bestBall": best_ball,
            "medianGame": median_on,
            "weeks": week_meta,
            "summary": {arm: _summary(league_records[arm]) for arm in ARMS},
            "identicalCheck": identical_by_league[key],
        }

    bb_keys = [k for k, v in per_league.items() if v["bestBall"]]
    pooled = {
        arm: _summary(
            {
                kind: [x for k in bb_keys for x in records[k][arm][kind]]
                for kind in ("h2h", "median", "score")
            }
        )
        for arm in ARMS
    }

    def ll_list(week_records: dict, arm: str) -> list[float]:
        return [_ll(r["p"], r["y"]) for r in week_records[arm]["h2h"] + week_records[arm]["median"]]

    boot = _cluster_bootstrap([(ll_list(wr, ARM_C), ll_list(wr, ARM_I)) for _, _, wr in clusters])
    boot_cm = _cluster_bootstrap(
        [(ll_list(wr, ARM_CM), ll_list(wr, ARM_I)) for _, _, wr in clusters]
    )

    pi, pc = pooled[ARM_I], pooled[ARM_C]
    gates: dict[str, Any] = {
        "G1": {
            "rule": "structural test",
            "status": "SEE_TEST tests/ros/test_playoff_ros_counted_once.py",
        },
        "G2": {
            "rule": f"cluster-bootstrap hi95 of Δ binary LL ≤ +{G2_MARGIN}",
            **boot,
            "status": "PASS" if boot["hi95"] <= G2_MARGIN else "FAIL",
        },
        "G3": {
            "rule": f"fav gap(C) ≤ fav gap(I) + {G3_SLACK}",
            "incumbent": pi["favCalibrationGap"],
            "corrected": pc["favCalibrationGap"],
            "status": "PASS"
            if pc["favCalibrationGap"] <= pi["favCalibrationGap"] + G3_SLACK
            else "FAIL",
        },
        "G4": {
            "rule": f"|PIT−.5| and |cov80−.8| not worse by more than {G4_SLACK}",
            "pitMean": {"incumbent": pi["pitMean"], "corrected": pc["pitMean"]},
            "cov80": {"incumbent": pi["cov80"], "corrected": pc["cov80"]},
            "status": "PASS"
            if abs(pc["pitMean"] - 0.5) <= abs(pi["pitMean"] - 0.5) + G4_SLACK
            and abs(pc["cov80"] - 0.8) <= abs(pi["cov80"] - 0.8) + G4_SLACK
            else "FAIL",
        },
    }
    g5a = all(
        v["identicalCheck"]["maxAbsDeltaMean"] == 0.0
        and v["identicalCheck"]["maxAbsDeltaSd"] == 0.0
        for v in per_league.values()
        if not v["bestBall"]
    )
    g5b = {}
    for k in bb_keys:
        s_i = per_league[k]["summary"][ARM_I]["llBinary"]
        s_c = per_league[k]["summary"][ARM_C]["llBinary"]
        g5b[k] = s_c - s_i
    gates["G5"] = {
        "rule": f"start/sit identical; each best-ball league Δ ≤ +{G5_MARGIN}",
        "startSitIdentical": g5a,
        "bestBallDelta": g5b,
        "status": "PASS" if g5a and all(d <= G5_MARGIN for d in g5b.values()) else "FAIL",
    }

    current: dict[str, Any] = {}
    if with_current:
        for key in sorted(per_league):
            try:
                current[key] = current_state(key, points_model)
            except Exception as exc:  # noqa: BLE001 — reported, never hidden
                current[key] = {"error": f"{type(exc).__name__}: {exc}"}
        g6_ok = True
        g6_detail = {}
        for key, cur in current.items():
            arm = (cur.get("arms") or {}).get(ARM_C)
            if not arm:
                g6_ok = False
                g6_detail[key] = "not_evaluated"
                continue
            if arm.get("championshipUnavailable") or arm.get("unsimulable"):
                g6_detail[key] = "bracket_not_playable"
                continue
            ok = (
                arm["titleSum"] is not None
                and abs(arm["titleSum"] - 1.0) <= G6_SUM_TOL
                and arm["playoffInRange"]
            )
            g6_detail[key] = "PASS" if ok else "FAIL"
            g6_ok = g6_ok and ok
        gates["G6"] = {
            "rule": "title odds sum to 1 ± 0.005; playoff odds in [0,1]",
            "perLeague": g6_detail,
            "status": "PASS" if g6_ok else "FAIL",
        }
    else:
        gates["G6"] = {"status": "NOT_EVALUATED"}

    result = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": str(inputs_path),
        "inputsCapturedAt": inputs.get("capturedAt"),
        "preregistration": "docs/research/PLAYOFF_ROS_D11_PREREGISTRATION.md",
        "pointsModel": points_model.to_dict(),
        "perLeague": per_league,
        "pooledBestBall": pooled,
        "meanOnlyBootstrap": boot_cm,
        "gates": gates,
        "current": current,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v.get("status") for k, v in gates.items()}, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    cap = sub.add_parser("capture")
    cap.add_argument("--out", type=Path, required=True)
    ev = sub.add_parser("evaluate")
    ev.add_argument("--inputs", type=Path, required=True)
    ev.add_argument("--out", type=Path, required=True)
    ev.add_argument("--current", action="store_true")
    args = parser.parse_args(argv)
    if args.cmd == "capture":
        return capture(args.out)
    return evaluate(args.inputs, args.out, with_current=args.current)


if __name__ == "__main__":
    raise SystemExit(main())
