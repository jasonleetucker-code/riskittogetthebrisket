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
from dataclasses import dataclass, replace
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
#: The incumbent as first run, with TODAY's directory injury flags in its team-strength
#: inputs (not knowable at a past kickoff).  Scored and reported, never gated.
INCUMBENT_TODAY_INJURY = "I_todayInjury"
ARMS_SCORED = ARMS_GATED + (INCUMBENT_TODAY_INJURY,)


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
    #: The same rows hydrated with TODAY's directory injury flags.  Not knowable at a
    #: past kickoff: kept only to report the pre-correction incumbent (results §5).
    rows_today_injury: list[dict[str, Any]] | None = None


#: Directory fields that describe a player's CURRENT health.  ``hydrate_roster_players``
#: reads ``injury_status`` into ``injured``, which moves team strength (lineup and bench
#: scores, health) and therefore the incumbent's ROS multiplier and depth lift.  Today's
#: value is not knowable at a past week's kickoff and no as-of injury source is archived,
#: so the point-in-time join strips these fields: injury state is UNKNOWN, read as not
#: flagged.  Post-freeze correction to the incumbent's inputs (results §5, prereg addendum).
CURRENT_HEALTH_FIELDS = (
    "injury_status",
    "injury_body_part",
    "injury_notes",
    "injury_start_date",
    "practice_participation",
    "practice_description",
)


def point_in_time_directory(directory: Mapping[str, Any]) -> dict[str, Any]:
    """The player directory without today's health fields (identity and eligibility kept)."""
    return {
        pid: (
            {k: v for k, v in meta.items() if k not in CURRENT_HEALTH_FIELDS}
            if isinstance(meta, dict)
            else meta
        )
        for pid, meta in directory.items()
    }


def team_strength_rows(
    roster_rows: Sequence[Mapping[str, Any]],
    directory: Mapping[str, Any],
    snapshot_players: list[dict[str, Any]],
    slots: list[str],
) -> list[dict[str, Any]]:
    """Production join (``hydrate_roster_players`` + ``compute_team_strength``) for one week."""
    teams = [
        {
            "ownerId": team_id(r["roster_id"]),
            "rosterId": r["roster_id"],
            "teamName": "",
            "players": hydrate_roster_players(
                [str(p) for p in (r.get("players") or [])],
                directory,  # type: ignore[arg-type]
            ),
        }
        for r in roster_rows
    ]
    return compute_team_strength(teams, aggregated_players=snapshot_players, starter_slots=slots)


def as_of(inputs: Inputs, week: int, slots: list[str]) -> AsOf:
    """Week ``week``'s pre-kickoff snapshot + that week's roster, through the production join.

    ``rows`` use the point-in-time directory (no injury flags); ``rows_today_injury``
    reproduce the first run's join with today's flags, for the reported-only arm.
    """
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
    rows = team_strength_rows(src, point_in_time_directory(inputs.directory), players, slots)
    rows_today = team_strength_rows(src, inputs.directory, players, slots)
    return AsOf(week, snap, v1.sha256_file(snap), players, rows, source, rows_today)


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
    if asof_k.rows_today_injury is not None:
        leaky = replace(asof_k, rows=asof_k.rows_today_injury)
        out[INCUMBENT_TODAY_INJURY] = dict(
            production_distributions(leaky, presim_by_week[k], view, ros_counted_once=False)
        )
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
        for a in ARMS_SCORED
        if all(d is not None for k in DEVELOPMENT for d in built[k][0][a].values())
    ]
    for k in DEVELOPMENT + HOLDOUT:
        forecasts, fits = built[k]
        arms_k = ARMS_SCORED if k in HOLDOUT else tuple(dev_arms)
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

    hold_recs, hold_med = score_block(HOLDOUT, ARMS_SCORED)
    dev_recs, _ = score_block(DEVELOPMENT, dev_arms)
    hold_weeks = [weeks[k] for k in HOLDOUT]
    dev_weeks = [weeks[k] for k in DEVELOPMENT]
    summaries = {a: tp.summarize_arm(hold_recs, hold_weeks, a) for a in ARMS_SCORED}
    dev_summaries = {a: tp.summarize_arm(dev_recs, dev_weeks, a) for a in dev_arms}
    # Per-week reading (reported, never gated): the team-cluster bootstrap does not
    # resample week-wide shocks, so each holdout week is also shown on its own.
    per_week = {}
    for k in HOLDOUT:
        recs_k, _m = score_block((k,), ARMS_SCORED)
        per_week[str(k)] = {
            a: {
                m: _r(v)
                for m, v in tp.summarize_arm(recs_k, [weeks[k]], a).items()
                if m in ("bias", "mae", "crps", "logLossBinary", "brierBinary", "concordance")
            }
            for a in ARMS_SCORED
        }

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
    for a in ARMS_SCORED:
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
            "perWeek": per_week,
            "incumbentInputs": {
                "gated": "I: point-in-time join, no injury flags (post-freeze correction)",
                INCUMBENT_TODAY_INJURY: "first run: today's directory injury flags (look-ahead)",
                "strippedDirectoryFields": list(CURRENT_HEALTH_FIELDS),
            },
        },
        "development": {
            "summaries": {a: {k: _r(v) for k, v in s.items()} for a, s in dev_summaries.items()},
            "armsWithoutEvidence": [a for a in ARMS_SCORED if a not in dev_arms],
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
    zs = [(y - m) / s for y, m, s in zip(ys, mus, sds)]
    return {
        "n": len(rows),
        "bias": _r(statistics.fmean(y - m for y, m in zip(ys, mus)), 2),
        "mae": _r(statistics.fmean(abs(y - m) for y, m in zip(ys, mus)), 2),
        "calibrationSlope": _r(tp.calibration_slope(mus, ys), 3),
        "zRms": _r(
            math.sqrt(statistics.fmean(((y - m) / s) ** 2 for y, m, s in zip(ys, mus, sds))), 3
        ),
        "zSd": _r(statistics.pstdev(zs), 3),
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
        if a.rows_today_injury is not None:
            arms[INCUMBENT_TODAY_INJURY] = production_distributions(
                replace(a, rows=a.rows_today_injury), p_f, view, ros_counted_once=False
            )
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
            return {**st, "zRms": None, "zSd": None, "meanSd": None}
        return _arm_stats(rs, arm)

    arm_names = (
        "L_F",
        "P_F",
        "I",
        INCUMBENT_TODAY_INJURY,
        "P_once",
        "P_C0",
        "P_CF",
        "P_CR",
        "P_F_oracle",
        "P_CF_oracle",
    )
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

    # Each contributor is a (with, without) arm pair; its effect on each error metric is
    # computed from the summaries above, never typed in (rank_contributors).
    contributor_pairs = (
        ("ROS multiplier re-applied to the presim (D11 double count, flag OFF)", "I", "P_F"),
        ("through-origin rosValue/2.7 conversion (vs one fitted affine scale C0)", "P_F", "P_C0"),
        ("one scale for every position (vs per-family affine CF)", "P_C0", "P_CF"),
        ("one scale for every position (vs per-family rank curve CR)", "P_C0", "P_CR"),
        (
            "availability not modelled, CF means (vs ORACLE appeared-only pool)",
            "P_CF",
            "P_CF_oracle",
        ),
        ("availability not modelled, fallback means (vs ORACLE pool)", "P_F", "P_F_oracle"),
        ("best-ball max over noisy draws (vs deterministic lineup)", "P_F", "L_F"),
    )
    ranked = {
        label: tp.rank_contributors(block_summaries, contributor_pairs)
        for label, block_summaries in summaries.items()
    }
    for block_rank in ranked.values():
        for row in block_rank["effects"]:
            for metric in tp.CONTRIBUTOR_ERRORS:
                row[metric] = _r(row[metric], 3)
    s_hold = summaries["weeks5to8"]
    reported = {
        "rosMultiplierRange": [_r(min(mults), 3), _r(max(mults), 3)],
        "bestBallLift": {
            "mean": _r(statistics.fmean(lifts), 2),
            "range": [_r(min(lifts), 2), _r(max(lifts), 2)],
            "shareOfPresimMean": _r(
                statistics.fmean(lifts) / statistics.fmean(r["P_F"][0] for r in hold_rows), 4
            ),
        },
        "spread": {
            "presimMeanSd": s_hold["P_F"]["meanSd"],
            "incumbentMeanSd": s_hold["I"]["meanSd"],
            "depthSdMultiplierRange": [_r(min(depth_m), 3), _r(max(depth_m), 3)],
            "realizedPooledWithinTeamSdWeeks1to8": _r(within, 2),
            "zSdAfterConversionCF": s_hold["P_CF"]["zSd"],
        },
        "unpricedStarterPointShareByWeek": unpriced,
    }

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
        "contributors": {"ranked": ranked, "reportedQuantities": reported},
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
