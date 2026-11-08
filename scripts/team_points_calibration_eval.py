#!/usr/bin/env python3
"""Team-level points calibration of the best-ball playoff simulator — RESEARCH ONLY.

Preregistration: ``docs/league-intelligence/TEAM_POINTS_CALIBRATION_PREREGISTRATION_2026-11-08.md``
(committed alone, before this script existed).  Results:
``docs/league-intelligence/TEAM_POINTS_CALIBRATION_RESULTS_2026-11-08.md``.

Follow-up to MATH_AUDIT_2026-11-08 finding F2 (RPA-LGI-008).  Evaluates, on point-in-time
inputs and a rolling origin, the served team weekly score distribution (incumbent ``I``:
production ``_bestball_presim`` under ``PointsModel()`` fallback constants, then
``_team_distributions_from_inputs(..., ros_counted_once=False)``) against simple baselines
(B1, B2), a reference (B0) and challengers (A, S) from ``src/ros_calibration/team_points.py``.

It changes nothing served.  It never writes ``data/league_intel/``, ``config/league_intel/`` or
``data/ros/``; it writes ONLY under ``docs/league-intelligence/evidence/team_points_calibration/``
and the gitignored cache ``data/team_points_calibration/cache/``.  Every output carries
``promotes: false``.

    python scripts/team_points_calibration_eval.py evaluate     # gates (preregistration §5)
    python scripts/team_points_calibration_eval.py diagnose     # contributor decomposition (§6)
    python scripts/team_points_calibration_eval.py evaluate --offline   # cache only

Exit codes: 0 when a run completed (whatever the verdict), 2 when it refused (fingerprint
mismatch, a week not final, missing input, a forbidden output path).
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import sim_calibration_study as v1  # noqa: E402
from src.league_comparison.sleeper_scoring import scoring_fingerprint  # noqa: E402
from src.league_intel.sim_calibration import PointsModel, load_points_model  # noqa: E402
from src.ros import playoff_sim  # noqa: E402
from src.ros.game_day_sim import median_threshold  # noqa: E402
from src.ros.lineup import (  # noqa: E402
    RosterPlayer,
    load_league_starter_slots,
    solve_optimal_assignment,
)
from src.ros.team_strength import compute_team_strength, hydrate_roster_players  # noqa: E402
from src.ros_calibration import conversion as cv  # noqa: E402
from src.ros_calibration import team_points as tp  # noqa: E402

PREREGISTRATION = "docs/league-intelligence/TEAM_POINTS_CALIBRATION_PREREGISTRATION_2026-11-08.md"
LEAGUE_KEY = v1.LEAGUE_KEY
LEAGUE_ID = v1.LEAGUE_ID
PINNED_SCORING_FINGERPRINT = v1.PINNED_SCORING_FINGERPRINT
SEASON = 2026
TEAMS_EXPECTED = 12

#: Preregistered split (§2).
HOLDOUT = (5, 6, 7, 8)
DEVELOPMENT = (3, 4)
FINAL_WEEKS = tuple(range(1, 9))
LIVE_WEEK = 9
DIAGNOSE_WEEKS = tuple(range(2, 10))

#: Seeds and sizes (§3, §4).
PRESIM_SEED = 20260428  # production's own presim seed (playoff_sim._build_team_distributions)
MEDIAN_DRAWS = 20_000
MEDIAN_SEED_BASE = 20261108
BOOTSTRAP_B = 2_000
BOOTSTRAP_SEED = 20261108

SLEEPER = v1.SLEEPER
CACHE_DIR = REPO / "data" / "team_points_calibration" / "cache"
GAMES_CACHE = CACHE_DIR / "nflverse_games.csv"
OUT_DIR = REPO / "docs" / "league-intelligence" / "evidence" / "team_points_calibration"
FORBIDDEN_DIRS = (
    REPO / "data" / "league_intel",
    REPO / "config" / "league_intel",
    REPO / "data" / "ros",
)

ARMS_GATED = ("I", "B0", "B1", "B2", "A", "S")


class Refusal(v1.StudyRefusal):
    """The run refuses rather than score incomplete or unpinned inputs."""


def assert_safe_output(path: Path) -> Path:
    p = Path(path).resolve()
    for bad in FORBIDDEN_DIRS:
        b = bad.resolve()
        if p == b or b in p.parents:
            raise Refusal(f"refusing to write inside {b}: {p}")
    allowed = OUT_DIR.resolve()
    if allowed not in p.parents:
        raise Refusal(f"refusing to write outside {allowed}: {p}")
    return p


def write_json(path: Path, payload: Any) -> Path:
    p = assert_safe_output(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return p


def team_id(roster_id: Any) -> str:
    """Anonymous team index (no manager name, no league id)."""
    return f"T{int(roster_id):02d}"


def redacted_receipts(receipts: Mapping[str, Any]) -> dict[str, Any]:
    """Cache receipts with the Sleeper league id replaced by the registry key (preregistration §7)."""
    return {
        url.replace(LEAGUE_ID, f"<{LEAGUE_KEY}>"): body for url, body in sorted(receipts.items())
    }


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True, timeout=30, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip()


def code_identity() -> dict[str, Any]:
    lib = REPO / "src" / "ros_calibration" / "team_points.py"
    sha = _git("rev-parse", "HEAD")
    dirty = _git(
        "status",
        "--porcelain",
        "--",
        "scripts/team_points_calibration_eval.py",
        "src/ros_calibration",
        "src/ros",
        "src/league_intel",
    )
    prereg_commit = _git("log", "--diff-filter=A", "--format=%H", "-n", "1", "--", PREREGISTRATION)
    touched = _git("show", "--name-only", "--format=", prereg_commit) if prereg_commit else None
    ancestor = None
    if prereg_commit and sha:
        try:
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", prereg_commit, sha],
                cwd=REPO,
                check=True,
                capture_output=True,
                timeout=30,
            )
            ancestor = True
        except subprocess.CalledProcessError:
            ancestor = False
        except (OSError, subprocess.SubprocessError):
            ancestor = None
    return {
        "codeSha": sha or "UNKNOWN",
        "codeDirty": None if dirty is None else bool(dirty),
        "scriptSha256": v1.sha256_file(Path(__file__)),
        "librarySha256": v1.sha256_file(lib),
        "preregistration": PREREGISTRATION,
        "preregistrationCommit": prereg_commit or "UNKNOWN",
        "preregistrationCommitFiles": touched.splitlines() if touched else None,
        "preregistrationIsAncestor": ancestor,
    }


# ── inputs ──────────────────────────────────────────────────────────────────────────


@dataclass
class Inputs:
    card: dict[str, Any]
    fingerprint: str
    schedule: dict[int, v1.WeekSchedule]
    directory: dict[str, Any]
    matchups: dict[int, list[dict[str, Any]]]
    current_rosters: list[dict[str, Any]]
    stats: dict[int, dict[str, Any]]


def load_inputs(fetcher: v1.CachedFetcher, *, need_stats: bool) -> Inputs:
    league = fetcher.get_json(f"{SLEEPER}/league/{LEAGUE_ID}")
    card = dict(league.get("scoring_settings") or {})
    fp = scoring_fingerprint(card)
    if fp != PINNED_SCORING_FINGERPRINT:
        raise Refusal(f"scoring fingerprint {fp} != pinned {PINNED_SCORING_FINGERPRINT}")
    settings = league.get("settings") or {}
    if int(settings.get("best_ball") or 0) != 1:
        raise Refusal("league is not best ball")
    if int(settings.get("league_average_match") or 0) != 1:
        raise Refusal("preregistration assumes the weekly median game is ON")
    games = fetcher.get_csv(v1.NFLVERSE_GAMES, GAMES_CACHE)
    schedule = v1.schedule_by_week(games, SEASON)
    matchups: dict[int, list[dict[str, Any]]] = {}
    for w in FINAL_WEEKS:
        sw = schedule.get(w)
        if sw is None or not sw.is_final:
            raise Refusal(f"week {w} is not final in the schedule")
        rows = fetcher.get_json(f"{SLEEPER}/league/{LEAGUE_ID}/matchups/{w}") or []
        if len(rows) != TEAMS_EXPECTED or any(
            not isinstance(r.get("points"), (int, float)) or r.get("matchup_id") is None
            for r in rows
        ):
            raise Refusal(f"week {w} matchups incomplete")
        if all(float(r["points"]) == 0.0 for r in rows):
            raise Refusal(f"week {w} has no scored points")
        matchups[w] = rows
    if LIVE_WEEK not in schedule:
        raise Refusal("live week missing from schedule")
    current = fetcher.get_json(f"{SLEEPER}/league/{LEAGUE_ID}/rosters") or []
    directory = fetcher.get_json(f"{SLEEPER}/players/nfl") or {}
    if not isinstance(directory, dict) or len(directory) < 1000:
        raise Refusal("player directory unusable")
    stats: dict[int, dict[str, Any]] = {}
    if need_stats:
        for w in FINAL_WEEKS:
            stats[w] = fetcher.get_json(f"{SLEEPER}/stats/nfl/regular/{SEASON}/{w}") or {}
    return Inputs(card, fp, schedule, directory, matchups, current, stats)


def realized_scores(inputs: Inputs) -> dict[int, dict[str, float]]:
    return {
        w: {team_id(r["roster_id"]): float(r["points"]) for r in rows}
        for w, rows in inputs.matchups.items()
    }


def pairs_by_week(inputs: Inputs) -> dict[int, list[tuple[str, str]]]:
    out: dict[int, list[tuple[str, str]]] = {}
    for w, rows in inputs.matchups.items():
        by_mid: dict[Any, list[str]] = {}
        for r in rows:
            by_mid.setdefault(r["matchup_id"], []).append(team_id(r["roster_id"]))
        pairs = [tuple(sorted(v)) for v in by_mid.values()]
        if any(len(p) != 2 for p in pairs):
            raise Refusal(f"week {w} has a matchup without exactly two teams")
        out[w] = sorted(pairs)  # type: ignore[arg-type]
    return out


@dataclass
class AsOf:
    week: int
    snapshot: Path
    snapshot_sha256: str
    snapshot_players: list[dict[str, Any]]
    rows: list[dict[str, Any]]  # production team-strength rows, ownerId = anonymous team id
    roster_source: str


def as_of(inputs: Inputs, week: int, slots: list[str]) -> AsOf:
    """Week ``week``'s pre-kickoff snapshot + that week's roster, through the production join."""
    kickoff = inputs.schedule[week].first_kickoff_utc
    snap = v1.snapshot_before(kickoff)
    players = v1.load_snapshot_players(snap)
    if week in inputs.matchups:
        src = inputs.matchups[week]
        source = f"matchups_week_{week}"
    elif week == LIVE_WEEK:
        src = inputs.current_rosters
        source = "current_rosters"
    else:
        raise Refusal(f"no roster source for week {week}")
    teams = [
        {
            "ownerId": team_id(r["roster_id"]),
            "rosterId": r["roster_id"],
            "teamName": "",
            "players": hydrate_roster_players(
                [str(p) for p in (r.get("players") or [])], inputs.directory
            ),
        }
        for r in src
    ]
    rows = compute_team_strength(teams, aggregated_players=players, starter_slots=slots)
    return AsOf(week, snap, v1.sha256_file(snap), players, rows, source)


def presim(asof_k: AsOf, slots: list[str], model: Any, rosters: Any = None) -> dict[str, Any]:
    """Production presim for one week, production seed, no availability calendar (§1)."""
    rr = playoff_sim._rosters_from_rows(asof_k.rows) if rosters is None else rosters
    return playoff_sim._bestball_presim(rr, slots, random.Random(PRESIM_SEED), model)


def production_distributions(
    asof_k: AsOf,
    presim_k: Mapping[str, tuple[float, float]],
    view: tp.RealizedView,
    *,
    ros_counted_once: bool,
) -> dict[str, tuple[float, float]]:
    """The served equation on point-in-time inputs (``ros_counted_once=False`` is the incumbent)."""
    teams = sorted(r["ownerId"] for r in asof_k.rows)
    per_owner = {t: view.team_scores(t) for t in teams}
    pool = [x for xs in per_owner.values() for x in xs]
    dists, _ = playoff_sim._team_distributions_from_inputs(
        per_owner,
        pool,
        playoff_sim._ros_strength_from_rows(asof_k.rows),
        depth_ratios=playoff_sim._depth_ratios_from_rows(asof_k.rows),
        bestball_dists=dict(presim_k),
        best_ball=True,
        ros_counted_once=ros_counted_once,
    )
    return {t: (d.mean, d.sd) for t, d in dists.items()}


def _r(x: float | None, nd: int = 4) -> float | None:
    return None if x is None or not math.isfinite(x) else round(float(x), nd)


def _fit_dict(fit: tp.OlsFit | None) -> dict[str, Any] | None:
    if fit is None:
        return None
    return {"coef": [_r(c, 6) for c in fit.coef], "s": _r(fit.s), "n": fit.n, "dof": fit.dof}


# ── evaluate (§3-§5) ────────────────────────────────────────────────────────────────


def build_week_forecasts(
    k: int,
    realized: Mapping[int, Mapping[str, float]],
    presim_by_week: Mapping[int, Mapping[str, tuple[float, float]]],
    asof_k: AsOf,
) -> tuple[dict[str, dict[str, tuple[float, float] | None]], dict[str, Any]]:
    """Every arm's week-``k`` forecast from point-in-time views only."""
    teams = sorted(r["ownerId"] for r in asof_k.rows)
    presim_means = {j: {t: m for t, (m, _s) in d.items()} for j, d in presim_by_week.items()}
    cands, fits = tp.candidate_forecasts(realized, presim_means, teams, k)
    view = tp.RealizedView(realized, k)
    inc = production_distributions(asof_k, presim_by_week[k], view, ros_counted_once=False)
    out: dict[str, dict[str, tuple[float, float] | None]] = {"I": dict(inc)}
    out.update(cands)
    return out, {name: _fit_dict(f) for name, f in fits.items()}


def evaluate(args: argparse.Namespace) -> int:
    fetcher = v1.CachedFetcher(CACHE_DIR, offline=args.offline)
    inputs = load_inputs(fetcher, need_stats=False)
    slots = load_league_starter_slots(LEAGUE_KEY)
    if not slots:
        raise Refusal("no starter slots for the league")
    model = PointsModel()  # the served model at freeze (MATH_AUDIT F2: fallback-constants)
    realized = realized_scores(inputs)
    pairs = pairs_by_week(inputs)

    asofs = {w: as_of(inputs, w, slots) for w in FINAL_WEEKS}
    presim_by_week = {w: presim(asofs[w], slots, model) for w in FINAL_WEEKS}
    for w, d in presim_by_week.items():
        if set(d) != set(realized[w]):
            raise Refusal(f"presim week {w} does not cover every team")

    weeks: dict[int, tp.WeekInputs] = {}
    week_detail: dict[str, Any] = {}
    # Development weeks are reported, never gated: an arm whose preregistered evidence
    # floor is not met there (S needs 24 training rows, i.e. k >= 5) is left out of the
    # development block and named, never filled in.  Holdout weeks fail closed.
    built = {
        k: build_week_forecasts(k, realized, presim_by_week, asofs[k])
        for k in DEVELOPMENT + HOLDOUT
    }
    dev_arms = [
        a
        for a in ARMS_GATED
        if all(d is not None for k in DEVELOPMENT for d in built[k][0][a].values())
    ]
    for k in DEVELOPMENT + HOLDOUT:
        forecasts, fits = built[k]
        arms_k = ARMS_GATED if k in HOLDOUT else tuple(dev_arms)
        complete = {a: {t: d for t, d in forecasts[a].items() if d is not None} for a in arms_k}
        wi = tp.WeekInputs(week=k, realized=realized[k], pairs=pairs[k], forecasts=complete)
        tp.require_complete(wi, arms_k)
        weeks[k] = wi
        week_detail[str(k)] = {
            "snapshot": asofs[k].snapshot.name,
            "rosterSource": asofs[k].roster_source,
            "fits": fits,
            "teams": {
                t: {
                    "realized": realized[k][t],
                    **{a: [_r(complete[a][t][0], 2), _r(complete[a][t][1], 2)] for a in arms_k},
                }
                for t in sorted(realized[k])
            },
        }

    def score_block(
        block: Sequence[int], arms: Sequence[str]
    ) -> tuple[list[tp.Record], dict[int, Any]]:
        recs: list[tp.Record] = []
        med: dict[int, Any] = {}
        for k in block:
            r, m = tp.score_week(
                weeks[k],
                arms,
                median_threshold,
                draws=MEDIAN_DRAWS,
                seed=MEDIAN_SEED_BASE + k,
            )
            recs.extend(r)
            med[k] = m
        return recs, med

    hold_recs, hold_med = score_block(HOLDOUT, ARMS_GATED)
    dev_recs, _ = score_block(DEVELOPMENT, dev_arms)
    hold_weeks = [weeks[k] for k in HOLDOUT]
    dev_weeks = [weeks[k] for k in DEVELOPMENT]
    summaries = {a: tp.summarize_arm(hold_recs, hold_weeks, a) for a in ARMS_GATED}
    dev_summaries = {a: tp.summarize_arm(dev_recs, dev_weeks, a) for a in dev_arms}

    tw = [r for r in hold_recs if r.kind == "team_week"]
    binary = [r for r in hold_recs if r.kind in ("h2h", "median")]
    deltas: dict[str, dict[str, dict[str, float]]] = {}
    for x in tp.CHALLENGERS:
        deltas[x] = {
            "crps": tp.paired_cluster_bootstrap(
                tw, "I", x, "crps", reps=BOOTSTRAP_B, seed=BOOTSTRAP_SEED
            ),
            "abs": tp.paired_cluster_bootstrap(
                tw, "I", x, "abs", reps=BOOTSTRAP_B, seed=BOOTSTRAP_SEED
            ),
            "ll": tp.paired_cluster_bootstrap(
                binary, "I", x, "ll", reps=BOOTSTRAP_B, seed=BOOTSTRAP_SEED
            ),
        }
    verdicts = {x: tp.evaluate_gates(summaries, deltas, x) for x in tp.CHALLENGERS}
    recommendation = tp.recommend(summaries, verdicts)

    horizon = {}
    for a in ARMS_GATED:
        horizon[a] = tp.horizon_errors(
            {k: weeks[k].forecasts[a] for k in HOLDOUT},
            {k: hold_med[k][a] for k in HOLDOUT},
            realized,
            pairs,
            median_threshold,
            last_week=max(HOLDOUT),
        )

    payload = {
        "promotes": False,
        "status": "RESEARCH_EVIDENCE_NOT_FOR_PROMOTION",
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "code": code_identity(),
        "league": {
            "key": LEAGUE_KEY,
            "scoringFingerprint": inputs.fingerprint,
            "slots": slots,
            "medianGame": True,
        },
        "pointsModel": {
            "incumbentModel": model.to_dict(),
            "loaderSourceInThisCheckout": load_points_model().source,
        },
        "split": {"holdout": list(HOLDOUT), "development": list(DEVELOPMENT)},
        "seeds": {
            "presim": PRESIM_SEED,
            "medianBase": MEDIAN_SEED_BASE,
            "medianDraws": MEDIAN_DRAWS,
            "bootstrap": BOOTSTRAP_SEED,
            "bootstrapReps": BOOTSTRAP_B,
        },
        "receipts": {
            "snapshots": {
                str(w): {"file": a.snapshot.name, "sha256": a.snapshot_sha256}
                for w, a in asofs.items()
            },
            "cache": redacted_receipts(fetcher.receipts),
            "networkCalls": fetcher.network_calls,
        },
        "holdout": {
            "summaries": {a: {k: _r(v) for k, v in s.items()} for a, s in summaries.items()},
            "deltasIncumbentMinusChallenger": {
                x: {m: {k: _r(v, 5) for k, v in d.items()} for m, d in dd.items()}
                for x, dd in deltas.items()
            },
            "gates": verdicts,
            "recommendation": recommendation,
            "horizon": {a: {k: _r(v) for k, v in h.items()} for a, h in horizon.items()},
        },
        "development": {
            "summaries": {a: {k: _r(v) for k, v in s.items()} for a, s in dev_summaries.items()},
            "armsWithoutEvidence": [a for a in ARMS_GATED if a not in dev_arms],
        },
        "weeks": week_detail,
        "downstreamPlayoffTitle": "INSUFFICIENT_BY_CONSTRUCTION: no completed 2026 season",
    }
    out = write_json(Path(args.out) if args.out else OUT_DIR / "evaluation.json", payload)
    print(json.dumps({x: v["verdict"] for x, v in verdicts.items()}, indent=1))
    print("recommendation:", recommendation)
    print("wrote", out)
    return 0


# ── diagnose (§6) ───────────────────────────────────────────────────────────────────


class _ConversionModel(PointsModel):
    """Presim draw with a ``src/ros_calibration`` conversion for the mean, fallback CV for spread.

    Diagnosis only: answers "how much of the incumbent's error is the rosValue→points conversion".
    An unpriced or family-less player draws 0, exactly as the served presim skips him.
    """

    def __init__(self, conversion: cv.ConversionModel, ladders: Mapping[str, Sequence[float]]):
        super().__init__()
        self.conversion = conversion
        self.ladders = ladders
        self.source = f"diagnosis:{conversion.model_id}"

    def draw(self, ros_value: float, position: str, rng: Any) -> float:
        fam = cv.family_of(position)
        mu = self.conversion.predict(
            fam, ros_value, cv.rank_in_family(self.ladders, fam, ros_value)
        )
        if mu is None:
            return 0.0
        return self.draw_from_mean(mu, position, rng)


def deterministic_lineup(asof_k: AsOf, slots: list[str], per_point: float) -> dict[str, float]:
    """Σ of ``rosValue / per_point`` over the exact lineup of expected values (no noise)."""
    out = {}
    for r in asof_k.rows:
        pool = [
            RosterPlayer(
                player_id=p["playerId"],
                canonical_name=p["canonicalName"],
                position=p["position"],
                ros_value=float(p["rosValue"]) / per_point,
                fantasy_positions=tuple(p.get("fantasyPositions") or ()),
            )
            for p in r.get("fullRoster") or []
            if float(p.get("rosValue") or 0.0) > 0
        ]
        out[r["ownerId"]] = float(
            sum(x.ros_value for x in solve_optimal_assignment(pool, slots).values())
        )
    return out


def _arm_stats(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    ys = [r["realized"] for r in rows]
    mus = [r[arm][0] for r in rows]
    sds = [r[arm][1] for r in rows]
    per_mu: dict[str, list[float]] = {}
    per_y: dict[str, list[float]] = {}
    for r in rows:
        per_mu.setdefault(r["team"], []).append(r[arm][0])
        per_y.setdefault(r["team"], []).append(r["realized"])
    sd_mu = statistics.pstdev([statistics.fmean(v) for v in per_mu.values()])
    sd_y = statistics.pstdev([statistics.fmean(v) for v in per_y.values()])
    return {
        "n": len(rows),
        "bias": _r(statistics.fmean(y - m for y, m in zip(ys, mus)), 2),
        "mae": _r(statistics.fmean(abs(y - m) for y, m in zip(ys, mus)), 2),
        "calibrationSlope": _r(tp.calibration_slope(mus, ys), 3),
        "zRms": _r(
            math.sqrt(statistics.fmean(((y - m) / s) ** 2 for y, m, s in zip(ys, mus, sds))), 3
        ),
        "meanSd": _r(statistics.fmean(sds), 2),
        "meanPredicted": _r(statistics.fmean(mus), 2),
        "meanRealized": _r(statistics.fmean(ys), 2),
        "betweenTeamSdPredicted": _r(sd_mu, 2),
        "betweenTeamSdRealized": _r(sd_y, 2),
        "betweenTeamSpreadRatio": _r(sd_mu / sd_y, 3) if sd_y > 0 else None,
    }


def diagnose(args: argparse.Namespace) -> int:
    fetcher = v1.CachedFetcher(CACHE_DIR, offline=args.offline)
    inputs = load_inputs(fetcher, need_stats=True)
    slots = load_league_starter_slots(LEAGUE_KEY)
    model = PointsModel()
    realized = realized_scores(inputs)
    weeks_all = tuple(range(1, LIVE_WEEK + 1))
    asofs = {w: as_of(inputs, w, slots) for w in weeks_all}

    # Player-week fit rows (appeared, priced at as-of) + receipts.
    fit_rows: dict[int, list[cv.FitRow]] = {}
    appeared: dict[int, set[str]] = {}
    scorer = {"n": 0, "within002": 0}
    lineup = {"n": 0, "within005": 0, "misses": []}
    unpriced: dict[str, Any] = {}
    for w in FINAL_WEEKS:
        rv = {
            p["playerId"]: float(p["rosValue"])
            for r in asofs[w].rows
            for p in r.get("fullRoster") or []
        }
        ladders = cv.family_ladders(asofs[w].snapshot_players)
        rows_w: list[cv.FitRow] = []
        app: set[str] = set()
        un_pts = tot_pts = 0.0
        for m in inputs.matchups[w]:
            pp = {str(k): float(v) for k, v in (m.get("players_points") or {}).items()}
            pids = [str(p) for p in (m.get("players") or [])]
            for pid in pids:
                pw = v1.classify_player_week(
                    pid, inputs.stats[w].get(pid), inputs.directory.get(pid), inputs.card, SEASON, w
                )
                if pw.points is not None:
                    scorer["n"] += 1
                    if abs(pw.points - pp.get(pid, 0.0)) <= 0.02:
                        scorer["within002"] += 1
                if pw.status == v1.APPEARED:
                    app.add(pid)
                    r = rv.get(pid, 0.0)
                    if r > 0:
                        rows_w.append(
                            cv.FitRow(
                                pw.family, r, cv.rank_in_family(ladders, pw.family, r), pw.points
                            )
                        )
            pool = [
                RosterPlayer(
                    player_id=pid,
                    canonical_name=pid,
                    position=str((inputs.directory.get(pid) or {}).get("position") or "").upper(),
                    ros_value=pp[pid],
                    fantasy_positions=tuple(
                        str(x).upper()
                        for x in ((inputs.directory.get(pid) or {}).get("fantasy_positions") or ())
                    ),
                )
                for pid in pids
                if pid in pp
            ]
            assign = solve_optimal_assignment(pool, slots)
            total = float(sum(p.ros_value for p in assign.values()))
            lineup["n"] += 1
            if abs(total - float(m["points"])) <= 0.05:
                lineup["within005"] += 1
            else:
                lineup["misses"].append(
                    {
                        "week": w,
                        "team": team_id(m["roster_id"]),
                        "solver": round(total, 2),
                        "host": float(m["points"]),
                    }
                )
            un_pts += sum(p.ros_value for p in assign.values() if rv.get(p.player_id, 0.0) <= 0)
            tot_pts += float(m["points"])
        fit_rows[w] = rows_w
        appeared[w] = app
        unpriced[str(w)] = _r(un_pts / tot_pts if tot_pts else None, 4)

    per_week: dict[str, Any] = {}
    rows_by_week: dict[int, list[dict[str, Any]]] = {}
    conversions: dict[str, Any] = {}
    live_candidates: dict[str, Any] = {}
    presim_f_by_week: dict[int, dict[str, tuple[float, float]]] = {}
    for w in weeks_all:
        presim_f_by_week[w] = presim(asofs[w], slots, model)
    for k in DIAGNOSE_WEEKS:
        a = asofs[k]
        ladders = cv.family_ladders(a.snapshot_players)
        train = [r for j in FINAL_WEEKS if j < k for r in fit_rows[j]]
        convs = {mid: cv.fit_model(mid, train) for mid in ("C0", "CF", "CR")}
        conversions[str(k)] = {mid: c.to_dict() for mid, c in convs.items()}
        view = tp.RealizedView(realized, k)
        p_f = presim_f_by_week[k]
        arms: dict[str, dict[str, tuple[float, float]]] = {
            "L_F": {t: (v, 0.0) for t, v in deterministic_lineup(a, slots, 2.7).items()},
            "P_F": p_f,
            "I": production_distributions(a, p_f, view, ros_counted_once=False),
            "P_once": production_distributions(a, p_f, view, ros_counted_once=True),
        }
        for mid, conv in convs.items():
            arms[f"P_{mid}"] = presim(a, slots, _ConversionModel(conv, ladders))
        if k in FINAL_WEEKS:
            base = playoff_sim._rosters_from_rows(a.rows)
            oracle = {
                o: {
                    "starters": [p for p in b["starters"] if p["playerId"] in appeared[k]],
                    "bench": [],
                }
                for o, b in base.items()
            }
            arms["P_F_oracle"] = presim(a, slots, model, oracle)
            arms["P_CF_oracle"] = presim(a, slots, _ConversionModel(convs["CF"], ladders), oracle)
        ros_map = playoff_sim._ros_strength_from_rows(a.rows)
        depth = playoff_sim._depth_ratios_from_rows(a.rows)
        vals = list(ros_map.values())
        rmean = statistics.fmean(vals)
        rsd = statistics.pstdev(vals) or 1.0
        teams = sorted(p_f)
        rows = []
        for t in teams:
            row = {
                "team": t,
                "realized": realized.get(k, {}).get(t),
                "rosMultiplier": _r(1 + playoff_sim.ROS_BLEND * (ros_map[t] - rmean) / rsd, 4),
                "depthSdMultiplier": _r(
                    playoff_sim.BEST_BALL_VARIANCE_BUMP
                    + playoff_sim.DEPTH_VARIANCE_LIFT_MAX * depth.get(t, 0.0),
                    4,
                ),
            }
            for arm, d in arms.items():
                row[arm] = [_r(d[t][0], 2), _r(d[t][1], 2)]
            rows.append(row)
        per_week[str(k)] = {
            "snapshot": a.snapshot.name,
            "rosterSource": a.roster_source,
            "teams": rows,
        }
        rows_by_week[k] = rows
        if k == LIVE_WEEK:
            presim_means = {
                j: {t: m for t, (m, _s) in presim_f_by_week[j].items()} for j in weeks_all
            }
            cands, fits = tp.candidate_forecasts(realized, presim_means, teams, k)
            live_candidates = {
                "note": "descriptive only: week-9 forward forecasts under each arm (§4 M9)",
                "fits": {n: _fit_dict(f) for n, f in fits.items()},
                "teams": {
                    t: {
                        "I": [_r(arms["I"][t][0], 2), _r(arms["I"][t][1], 2)],
                        **{
                            n: (
                                None
                                if cands[n][t] is None
                                else [_r(cands[n][t][0], 2), _r(cands[n][t][1], 2)]
                            )
                            for n in cands
                        },
                        "realizedWeeks1to8": [
                            _r(statistics.fmean(realized[j][t] for j in FINAL_WEEKS), 2),
                            _r(statistics.stdev(realized[j][t] for j in FINAL_WEEKS), 2),
                        ],
                    }
                    for t in teams
                },
            }

    def block(ws: Sequence[int], arm: str) -> dict[str, Any] | None:
        rs = [r for k in ws for r in rows_by_week[k] if r["realized"] is not None and arm in r]
        if not rs or any(r[arm][1] is None for r in rs):
            return None
        if arm == "L_F":
            # A deterministic sum has no spread: z-RMS and sd are undefined, not zero.
            st = _arm_stats([{**r, arm: [r[arm][0], 1.0]} for r in rs], arm)
            return {**st, "zRms": None, "meanSd": None}
        return _arm_stats(rs, arm)

    arm_names = ("L_F", "P_F", "I", "P_once", "P_C0", "P_CF", "P_CR", "P_F_oracle", "P_CF_oracle")
    summaries = {
        label: {arm: block(ws, arm) for arm in arm_names}
        for label, ws in (("weeks5to8", HOLDOUT), ("weeks2to8", tuple(range(2, 9))))
    }
    hold_rows = [r for k in HOLDOUT for r in rows_by_week[k]]
    within = tp.pooled_within_sd(
        [[realized[j][t] for j in FINAL_WEEKS] for t in sorted(realized[1])]
    )
    lifts = [r["P_F"][0] - r["L_F"][0] for r in hold_rows]
    mults = [r["rosMultiplier"] for r in hold_rows]
    depth_m = [r["depthSdMultiplier"] for r in hold_rows]
    s = summaries["weeks5to8"]

    def delta(a: str, b: str, key: str) -> float | None:
        if s.get(a) is None or s.get(b) is None:
            return None
        return _r(s[b][key] - s[a][key], 3)

    contributors = [
        {
            "contributor": "ROS multiplier on the presim (double count, D11; flag OFF)",
            "from": "P_F",
            "to": "I",
            "deltaSpreadRatio": delta("P_F", "I", "betweenTeamSpreadRatio"),
            "deltaSlope": delta("P_F", "I", "calibrationSlope"),
            "deltaMae": delta("P_F", "I", "mae"),
            "deltaBias": delta("P_F", "I", "bias"),
            "multiplierRange": [_r(min(mults), 3), _r(max(mults), 3)],
        },
        {
            "contributor": "unit conversion rosValue/2.7 through origin vs one fitted affine scale (C0)",
            "from": "P_F",
            "to": "P_C0",
            "deltaSpreadRatio": delta("P_F", "P_C0", "betweenTeamSpreadRatio"),
            "deltaSlope": delta("P_F", "P_C0", "calibrationSlope"),
            "deltaMae": delta("P_F", "P_C0", "mae"),
            "deltaBias": delta("P_F", "P_C0", "bias"),
        },
        {
            "contributor": "position (family) scale: one scale (C0) vs per-family (CF / CR)",
            "from": "P_C0",
            "to": "P_CF",
            "deltaSpreadRatio": delta("P_C0", "P_CF", "betweenTeamSpreadRatio"),
            "deltaSlope": delta("P_C0", "P_CF", "calibrationSlope"),
            "deltaMae": delta("P_C0", "P_CF", "mae"),
            "deltaMaeCR": delta("P_C0", "P_CR", "mae"),
            "deltaBias": delta("P_C0", "P_CF", "bias"),
        },
        {
            "contributor": "availability not modelled (ORACLE arm, not knowable at forecast time)",
            "from": "P_CF",
            "to": "P_CF_oracle",
            "deltaMae": delta("P_CF", "P_CF_oracle", "mae"),
            "deltaBias": delta("P_CF", "P_CF_oracle", "bias"),
            "deltaBiasUnderFallback": delta("P_F", "P_F_oracle", "bias"),
        },
        {
            "contributor": "best-ball lineup max over noisy draws (P_F - L_F)",
            "meanLift": _r(statistics.fmean(lifts), 2),
            "liftRange": [_r(min(lifts), 2), _r(max(lifts), 2)],
            "liftShareOfPresimMean": _r(
                statistics.fmean(r["P_F"][0] - r["L_F"][0] for r in hold_rows)
                / statistics.fmean(r["P_F"][0] for r in hold_rows),
                4,
            ),
        },
        {
            "contributor": "spread: independent per-player draws with fallback CVs; depth lift",
            "presimMeanSd": s["P_F"]["meanSd"] if s.get("P_F") else None,
            "incumbentMeanSd": s["I"]["meanSd"] if s.get("I") else None,
            "depthSdMultiplierRange": [_r(min(depth_m), 3), _r(max(depth_m), 3)],
            "realizedPooledWithinTeamSdWeeks1to8": _r(within, 2),
            "zRmsAfterConversionCF": s["P_CF"]["zRms"] if s.get("P_CF") else None,
        },
        {
            "contributor": "unpriced roster players draw 0 (missing treated as zero in the presim)",
            "realizedStarterPointShareByWeek": unpriced,
        },
    ]

    payload = {
        "promotes": False,
        "status": "RESEARCH_EVIDENCE_NOT_FOR_PROMOTION",
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "code": code_identity(),
        "league": {"key": LEAGUE_KEY, "scoringFingerprint": inputs.fingerprint, "slots": slots},
        "receipts": {
            "scorerVsHostPlayersPoints": scorer,
            "canonicalSolverVsHostTeamPoints": lineup,
            "snapshots": {
                str(w): {"file": a.snapshot.name, "sha256": a.snapshot_sha256}
                for w, a in asofs.items()
            },
            "cache": redacted_receipts(fetcher.receipts),
            "networkCalls": fetcher.network_calls,
        },
        "summaries": summaries,
        "contributors": contributors,
        "conversions": conversions,
        "liveWeek9": live_candidates,
        "weeks": per_week,
    }
    out = write_json(Path(args.out) if args.out else OUT_DIR / "diagnosis.json", payload)
    print(json.dumps(summaries["weeks5to8"], indent=1))
    print("wrote", out)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("evaluate", "diagnose"):
        p = sub.add_parser(name)
        p.add_argument("--offline", action="store_true", help="cache only, never the network")
        p.add_argument("--out", default=None, help="output path (must be under the evidence dir)")
    args = parser.parse_args(argv)
    try:
        return evaluate(args) if args.cmd == "evaluate" else diagnose(args)
    except (v1.StudyRefusal, tp.InsufficientEvidence) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
