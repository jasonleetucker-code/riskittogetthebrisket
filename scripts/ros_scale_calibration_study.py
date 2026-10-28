#!/usr/bin/env python3
"""ROS scale calibration study (offense vs IDP) — RESEARCH ONLY, promotes nothing.

Preregistration: ``docs/league-intelligence/ROS_SCALE_CALIBRATION_PREREGISTRATION_2026-10-28.md``.
Results:         ``docs/league-intelligence/ROS_SCALE_CALIBRATION_RESULTS_2026-10-28.md``.

Measures whether ``rosValue`` (a per-board 0-100 log-rank index) puts offense and IDP on a
comparable scale against realized host-native points, and evaluates champion/challenger
conversions to expected weekly points (``src/ros_calibration``).  Reuses the v1 study's
loaders, production join and host-native scorer — no second copy.

Writes ONLY under ``docs/league-intelligence/evidence/ros_scale_calibration/`` (evidence) and the
gitignored cache ``data/ros_calibration/cache/``.  Never writes ``data/ros/`` or
``data/league_intel/``.

    python scripts/ros_scale_calibration_study.py evaluate     # rolling-origin evaluation + gates
    python scripts/ros_scale_calibration_study.py downstream   # latest-snapshot shadow tables
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

from scripts import sim_calibration_study as v1  # noqa: E402
from src.league_comparison.sleeper_scoring import scoring_fingerprint  # noqa: E402
from src.ros import team_strength as ts  # noqa: E402
from src.ros.lineup import RosterPlayer, optimize_lineup, starter_slots_from_roster_positions  # noqa: E402
from src.ros_calibration import conversion as cv  # noqa: E402
from src.ros_calibration import metrics as mt  # noqa: E402
from src.ros_calibration import par as par_mod  # noqa: E402

PREREGISTRATION = "docs/league-intelligence/ROS_SCALE_CALIBRATION_PREREGISTRATION_2026-10-28.md"
SEASON = 2026
SEED = 20261028
BOOTSTRAP_B = 2000
GATE_MIN_N = 50
MIN_CROSS_PAIRS = 1000
MIN_TEAM_WEEKS = 36
HOLDOUT = (5, 6, 7)
DEVELOPMENT = (3, 4)
STABILITY_PAIRS = ((4, 5), (5, 6), (6, 7))
FINAL_FIT_WEEKS = tuple(range(1, 8))
CONFIRM_WEEK = 8
EVAL_MODELS = ("C0", "CG", "CF", "CR", "F")

# Preregistered gate thresholds (labelled PRIORs, §5).
G1_D_TOL = 0.10
G1_R_BAND = (0.85, 1.15)
G4_TOL = 0.02
G5_TOL = 0.01
G6_TOL = 0.02
MAE_TIE = 0.05

CACHE_DIR = REPO / "data" / "ros_calibration" / "cache"
GAMES_CACHE = CACHE_DIR / "nflverse" / "games_20261028.csv"
OUT_DIR = REPO / "docs" / "league-intelligence" / "evidence" / "ros_scale_calibration"


def assert_safe_output(path: Path) -> Path:
    p = Path(path).resolve()
    allowed = OUT_DIR.resolve()
    if allowed not in p.parents and p != allowed:
        raise v1.StudyRefusal(f"refusing to write outside {allowed}: {p}")
    return p


def write_json(path: Path, payload: Any) -> Path:
    p = assert_safe_output(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return p


# ── data ───────────────────────────────────────────────────────────────────────────────────────


@dataclass
class PW:
    """One rostered player-week with as-of inputs (and realized points when final)."""

    week: int
    pid: str
    roster_id: int
    family: str | None
    position: str
    fantasy_positions: tuple[str, ...]
    ros_value: float | None  # None = unpriced by the as-of snapshot
    status: str | None  # v1 classification, None when the week has no stat lines
    points: float | None
    host_points: float | None  # Sleeper matchups ``players_points`` (receipt only)


@dataclass
class WeekData:
    week: int
    snapshot: Path
    snapshot_players: list[dict[str, Any]]
    ladders: dict[str, list[float]]
    rows: list[PW]
    team_points: dict[int, float]
    awarded_starters: dict[int, list[str]]
    live_composite: dict[int, float]
    live_starting_idp_share: dict[int, float | None]


class Study:
    def __init__(self, offline: bool = False) -> None:
        self.f = v1.CachedFetcher(CACHE_DIR, offline=offline)
        league = self.f.get_json(f"{v1.SLEEPER}/league/{v1.LEAGUE_ID}")
        self.card = {str(k): float(v) for k, v in (league.get("scoring_settings") or {}).items()}
        fp = scoring_fingerprint(league.get("scoring_settings"))
        if fp != v1.PINNED_SCORING_FINGERPRINT:
            raise v1.StudyRefusal(
                f"card fingerprint {fp} != pinned {v1.PINNED_SCORING_FINGERPRINT}"
            )
        self.fingerprint = fp
        self.slots = starter_slots_from_roster_positions(league.get("roster_positions"))
        self.roster_positions = list(league.get("roster_positions") or [])
        games = self.f.get_csv(v1.NFLVERSE_GAMES, GAMES_CACHE)
        self.sched = v1.schedule_by_week(games, SEASON)
        self.directory = self.f.get_json(f"{v1.SLEEPER}/players/nfl")
        self._weeks: dict[int, WeekData] = {}

    def is_final(self, week: int) -> bool:
        s = self.sched.get(week)
        return bool(s and s.is_final)

    def week(self, w: int) -> WeekData:
        if w in self._weeks:
            return self._weeks[w]
        cutoff = self.sched[w].first_kickoff_utc
        snap = v1.snapshot_before(cutoff)
        snap_players = v1.load_snapshot_players(snap)
        ladders = cv.family_ladders(snap_players)
        matchups = self.f.get_json(f"{v1.SLEEPER}/league/{v1.LEAGUE_ID}/matchups/{w}")
        rosters = v1.rostered_by_week(matchups)
        final = self.is_final(w)
        stats = {}
        if final:
            got = v1.sc.fetch_stat_lines(str(SEASON), [w], fetcher=self.f.get_json, sleep_s=0.0)
            if w not in got:
                raise v1.StudyRefusal(f"stat lines unavailable for week {w}")
            stats = got[w]
        full = v1.as_of_full_rosters(rosters, self.directory, snap_players, self.slots)
        host_pts: dict[str, float] = {}
        team_points: dict[int, float] = {}
        awarded: dict[int, list[str]] = {}
        for m in matchups or []:
            rid = int(m.get("roster_id"))
            for pid, pts in (m.get("players_points") or {}).items():
                host_pts[str(pid)] = float(pts)
            if final:
                team_points[rid] = float(m.get("points") or 0.0)
                awarded[rid] = [str(p) for p in (m.get("starters") or []) if p and str(p) != "0"]
        rows: list[PW] = []
        for rid, roster_rows in full.items():
            for r in roster_rows:
                pid = str(r.get("playerId"))
                meta = self.directory.get(pid) or {}
                family = v1.lineup_family(meta)
                rv = float(r.get("rosValue") or 0.0)
                status = points = None
                if final:
                    pw = v1.classify_player_week(pid, stats.get(pid), meta, self.card, SEASON, w)
                    status, points = pw.status, pw.points
                rows.append(
                    PW(
                        week=w,
                        pid=pid,
                        roster_id=int(rid),
                        family=family,
                        position=str(meta.get("position") or r.get("position") or "").upper(),
                        fantasy_positions=tuple(
                            str(p).upper() for p in (meta.get("fantasy_positions") or ()) if p
                        ),
                        ros_value=rv if rv > 0 else None,
                        status=status,
                        points=points,
                        host_points=host_pts.get(pid),
                    )
                )
        # The LIVE composite, verbatim (production ``compute_team_strength`` over rosValue).
        teams = [
            {
                "ownerId": str(rid),
                "rosterId": rid,
                "teamName": "",
                "players": ts.hydrate_roster_players(list(pids), self.directory),
            }
            for rid, pids in rosters.items()
        ]
        live = ts.compute_team_strength(
            teams, aggregated_players=snap_players, starter_slots=self.slots
        )
        live_comp = {int(t["rosterId"]): float(t["teamRosStrength"]) for t in live}
        idp_share: dict[int, float | None] = {}
        for t in live:
            tot = sum(float(s.get("rosValue") or 0.0) for s in t.get("startingLineup") or [])
            idp = sum(
                float(s.get("rosValue") or 0.0)
                for s in t.get("startingLineup") or []
                if cv.family_of(s.get("position")) in cv.IDP_FAMILIES
            )
            idp_share[int(t["rosterId"])] = (idp / tot) if tot > 0 else None
        wd = WeekData(
            week=w,
            snapshot=snap,
            snapshot_players=snap_players,
            ladders=ladders,
            rows=rows,
            team_points=team_points,
            awarded_starters=awarded,
            live_composite=live_comp,
            live_starting_idp_share=idp_share,
        )
        self._weeks[w] = wd
        return wd


# ── fitting / prediction ───────────────────────────────────────────────────────────────────────


def in_population(r: PW) -> bool:
    return (
        r.status == v1.APPEARED
        and r.family in cv.GROUP_OF
        and r.ros_value is not None
        and r.points is not None
    )


def fit_rows(study: Study, weeks: Sequence[int]) -> list[cv.FitRow]:
    out = []
    for w in weeks:
        wd = study.week(w)
        for r in wd.rows:
            if in_population(r):
                out.append(
                    cv.FitRow(
                        r.family,
                        float(r.ros_value),
                        cv.rank_in_family(wd.ladders, r.family, r.ros_value) or 1,
                        float(r.points),
                    )
                )
    return out


def fit_all(study: Study, fit_weeks: Sequence[int]) -> dict[str, cv.ConversionModel]:
    rows = fit_rows(study, fit_weeks)
    return {m: cv.fit_model(m, rows) for m in EVAL_MODELS}


def predict_row(model: cv.ConversionModel, wd: WeekData, r: PW) -> float | None:
    return model.predict(
        r.family, r.ros_value, cv.rank_in_family(wd.ladders, r.family, r.ros_value)
    )


# ── metrics per evaluated week ─────────────────────────────────────────────────────────────────


def lineup_for(rows: Sequence[PW], values: Mapping[str, float | None], slots: list[str]):
    pool = [
        RosterPlayer(
            player_id=r.pid,
            canonical_name=r.pid,
            position=r.position,
            ros_value=values.get(r.pid),
            fantasy_positions=r.fantasy_positions,
        )
        for r in rows
    ]
    return optimize_lineup(pool, starter_slots=slots)


def composite(solution) -> float:
    return (
        ts.WEIGHT_STARTING * solution.starting_lineup_score
        + ts.WEIGHT_DEPTH * solution.bench_depth_score
        + ts.WEIGHT_COVERAGE * solution.positional_coverage_score
        + ts.WEIGHT_HEALTH * solution.health_availability_score
    )


def evaluate_week(study: Study, h: int, models: Mapping[str, cv.ConversionModel]) -> dict[str, Any]:
    wd = study.week(h)
    preds: dict[str, dict[str, float | None]] = {m: {} for m in models}
    for r in wd.rows:
        for m, model in models.items():
            preds[m][r.pid] = predict_row(model, wd, r)
    records = []
    for r in wd.rows:
        if not in_population(r):
            continue
        records.append(
            {
                "week": h,
                "pid": r.pid,
                "family": r.family,
                "group": cv.GROUP_OF[r.family],
                "y": float(r.points),
                "mu": {m: preds[m][r.pid] for m in models},
            }
        )
    by_rid: dict[int, list[PW]] = defaultdict(list)
    for r in wd.rows:
        by_rid[r.roster_id].append(r)
    team = {}
    for rid, rows in sorted(by_rid.items()):
        entry: dict[str, Any] = {
            "realized": wd.team_points.get(rid),
            "awarded": wd.awarded_starters.get(rid) or [],
            "liveComposite": wd.live_composite.get(rid),
        }
        for m in models:
            sol = lineup_for(rows, preds[m], study.slots)
            starters = [str(s.get("playerId")) for s in sol.starting_lineup if s.get("playerId")]
            entry[m] = {
                "starters": starters,
                "lineupTotal": float(sol.starting_lineup_score),
                "composite": float(composite(sol)),
            }
        team[rid] = entry
    return {"week": h, "records": records, "teams": team, "preds": preds}


# ── aggregation over the holdout ───────────────────────────────────────────────────────────────


def _stat_mae(model: str):
    return lambda rs: mt.mae([r["mu"][model] for r in rs], [r["y"] for r in rs])


def _stat_dmae(champ: str, chal: str):
    def f(rs):
        a = mt.mae([r["mu"][champ] for r in rs], [r["y"] for r in rs])
        b = mt.mae([r["mu"][chal] for r in rs], [r["y"] for r in rs])
        return None if a is None or b is None else a - b

    return f


def _stat_ratio(model: str, group: str):
    def f(rs):
        g = [r for r in rs if r["group"] == group]
        return mt.ratio([r["y"] for r in g], [r["mu"][model] for r in g])

    return f


def _stat_d(model: str):
    def f(rs):
        ro = _stat_ratio(model, "OFF")(rs)
        ri = _stat_ratio(model, "IDP")(rs)
        return None if not ro or ri is None else ri / ro

    return f


def accuracy_block(records: list[dict[str, Any]], models: Sequence[str]) -> dict[str, Any]:
    pid = lambda r: r["pid"]  # noqa: E731
    out: dict[str, Any] = {"n": len(records), "byModel": {}, "families": {}, "groups": {}}
    usable = [r for r in records if all(r["mu"][m] is not None for m in models)]
    out["nScoredByEveryModel"] = len(usable)
    for m in models:
        ys = [r["y"] for r in usable]
        ps = [r["mu"][m] for r in usable]
        out["byModel"][m] = {
            "mae": mt.mae(ps, ys),
            "rmse": mt.rmse(ps, ys),
            "ratioOFF": _stat_ratio(m, "OFF")(usable),
            "ratioIDP": _stat_ratio(m, "IDP")(usable),
            "ratioK": _stat_ratio(m, "K")(usable),
            "D": mt.cluster_bootstrap(usable, pid, _stat_d(m), b=BOOTSTRAP_B, seed=SEED),
            "slopeOFF": mt.calibration_slope(
                [r["mu"][m] for r in usable if r["group"] == "OFF"],
                [r["y"] for r in usable if r["group"] == "OFF"],
            ),
            "slopeIDP": mt.calibration_slope(
                [r["mu"][m] for r in usable if r["group"] == "IDP"],
                [r["y"] for r in usable if r["group"] == "IDP"],
            ),
        }
        if m != "C0":
            out["byModel"][m]["dMAEvsC0"] = mt.cluster_bootstrap(
                usable, pid, _stat_dmae("C0", m), b=BOOTSTRAP_B, seed=SEED
            )
    for fam in cv.FAMILIES:
        fr = [r for r in usable if r["family"] == fam]
        fb: dict[str, Any] = {"n": len(fr), "gated": len(fr) >= GATE_MIN_N, "meanPoints": None}
        if fr:
            fb["meanPoints"] = statistics.fmean(r["y"] for r in fr)
        for m in models:
            fb[m] = {
                "mae": mt.mae([r["mu"][m] for r in fr], [r["y"] for r in fr]),
                "ratio": mt.ratio([r["y"] for r in fr], [r["mu"][m] for r in fr]),
                "meanMu": statistics.fmean(r["mu"][m] for r in fr) if fr else None,
            }
            if m != "C0" and fr:
                fb[m]["dMAEvsC0"] = mt.cluster_bootstrap(
                    fr, pid, _stat_dmae("C0", m), b=BOOTSTRAP_B, seed=SEED
                )
        out["families"][fam] = fb
    # decile table per model (pooled)
    deciles: dict[str, list[dict[str, Any]]] = {}
    for m in models:
        srt = sorted(usable, key=lambda r: r["mu"][m])
        n = len(srt)
        rows = []
        for d in range(10):
            chunk = srt[d * n // 10 : (d + 1) * n // 10]
            if not chunk:
                continue
            rows.append(
                {
                    "decile": d + 1,
                    "n": len(chunk),
                    "meanMu": statistics.fmean(r["mu"][m] for r in chunk),
                    "meanY": statistics.fmean(r["y"] for r in chunk),
                    "idpShare": sum(1 for r in chunk if r["group"] == "IDP") / len(chunk),
                }
            )
        deciles[m] = rows
    out["deciles"] = deciles
    return out


def concordance_block(evals: list[dict[str, Any]], models: Sequence[str]) -> dict[str, Any]:
    """M4: OFF x IDP pair concordance (single week) with a player-cluster bootstrap."""
    weeks_mats: dict[str, dict[int, tuple[np.ndarray, np.ndarray]]] = {m: {} for m in models}
    members: dict[int, tuple[list[str], list[str]]] = {}
    for ev in evals:
        recs = [r for r in ev["records"] if all(r["mu"][m] is not None for m in models)]
        off = [r for r in recs if r["group"] == "OFF"]
        idp = [r for r in recs if r["group"] == "IDP"]
        members[ev["week"]] = ([r["pid"] for r in off], [r["pid"] for r in idp])
        for m in models:
            weeks_mats[m][ev["week"]] = mt.cross_group_concordance_matrices(
                [(r["mu"][m], r["y"]) for r in off], [(r["mu"][m], r["y"]) for r in idp]
            )
    pairs = int(sum(v[1].sum() for v in weeks_mats[models[0]].values()))
    out: dict[str, Any] = {
        "validPairs": pairs,
        "sufficient": pairs >= MIN_CROSS_PAIRS,
        "byModel": {},
    }
    point = {m: mt.concordance_from_weeks(weeks_mats[m]) for m in models}
    all_pids = sorted({p for o, i in members.values() for p in o + i})
    rng = random.Random(SEED)
    boot: dict[str, list[float]] = {m: [] for m in models if m != "C0"}
    for _ in range(BOOTSTRAP_B):
        mult = Counter(all_pids[rng.randrange(len(all_pids))] for _j in range(len(all_pids)))
        weights = {
            wk: (
                np.array([mult.get(p, 0) for p in o], dtype=float),
                np.array([mult.get(p, 0) for p in i], dtype=float),
            )
            for wk, (o, i) in members.items()
        }
        c0 = mt.concordance_from_weeks(weeks_mats["C0"], weights)
        for m in boot:
            cm = mt.concordance_from_weeks(weeks_mats[m], weights)
            if c0 is not None and cm is not None:
                boot[m].append(cm - c0)
    for m in models:
        out["byModel"][m] = {"concordance": point[m]}
        if m != "C0":
            out["byModel"][m]["deltaVsC0"] = {
                "estimate": (point[m] - point["C0"]) if point[m] is not None else None,
                "ci95": mt.percentile_ci(boot[m]),
            }
    return out


def ros_horizon_concordance(
    study: Study, evals: list[dict[str, Any]], models: Sequence[str]
) -> dict[str, Any]:
    """M4 (reported): pairs ordered by realized mean over weeks h..7, players with ≥ 2 appearances."""
    out: dict[str, Any] = {}
    for m in models:
        num = den = 0.0
        for ev in evals:
            h = ev["week"]
            real: dict[str, list[float]] = defaultdict(list)
            for w in range(h, 8):
                for r in study.week(w).rows:
                    if r.status == v1.APPEARED and r.points is not None:
                        real[r.pid].append(float(r.points))
            off, idp = [], []
            for r in study.week(h).rows:
                mu = ev["preds"][m].get(r.pid)
                if mu is None or r.family not in cv.GROUP_OF or len(real.get(r.pid, [])) < 2:
                    continue
                item = (mu, statistics.fmean(real[r.pid]))
                if cv.GROUP_OF[r.family] == "OFF":
                    off.append(item)
                elif cv.GROUP_OF[r.family] == "IDP":
                    idp.append(item)
            if off and idp:
                c, v = mt.cross_group_concordance_matrices(off, idp)
                num += float(c.sum())
                den += float(v.sum())
        out[m] = {"concordance": (num / den) if den else None, "validPairs": int(den)}
    return out


def stability_block(
    study: Study, fits_by_week: Mapping[int, Mapping[str, cv.ConversionModel]], models
) -> dict[str, Any]:
    """M3: Spearman of μ between consecutive pre-week snapshots (inputs only)."""
    out: dict[str, Any] = {"pairs": {}, "mean": {}}
    for a, b in STABILITY_PAIRS:
        wa, wb = study.week(a), study.week(b)
        ra = {r.pid: r for r in wa.rows}
        res = {}
        for m in models:
            xs, ys = [], []
            for r in wb.rows:
                prev = ra.get(r.pid)
                if prev is None:
                    continue
                pa = predict_row(fits_by_week[a][m], wa, prev)
                pb = predict_row(fits_by_week[b][m], wb, r)
                if pa is None or pb is None:
                    continue
                xs.append(pa)
                ys.append(pb)
            res[m] = {"rho": mt.spearman(xs, ys), "n": len(xs)}
        out["pairs"][f"{a}->{b}"] = res
    for m in models:
        vals = [
            out["pairs"][k][m]["rho"] for k in out["pairs"] if out["pairs"][k][m]["rho"] is not None
        ]
        out["mean"][m] = statistics.fmean(vals) if vals else None
    return out


def team_block(evals: list[dict[str, Any]], models: Sequence[str]) -> dict[str, Any]:
    """M5 lineup agreement + M6 team ordering."""
    tw = []
    for ev in evals:
        for rid, t in ev["teams"].items():
            if t["realized"] is None or not t["awarded"]:
                continue
            tw.append((ev["week"], rid, t))
    out: dict[str, Any] = {
        "teamWeeks": len(tw),
        "sufficient": len(tw) >= MIN_TEAM_WEEKS,
        "byModel": {},
    }
    key = lambda x: f"{x[0]}:{x[1]}"  # noqa: E731

    def agreement(m):
        def f(items):
            vals = [
                len(set(t[m]["starters"]) & set(t["awarded"])) / len(t["awarded"])
                for _w, _r, t in items
            ]
            return statistics.fmean(vals) if vals else None

        return f

    weeks = sorted({w for w, _r, _t in tw})
    arms = list(models) + ["liveComposite"]
    for m in arms:
        conc_num = conc_den = 0.0
        rhos, crhos = [], []
        for w in weeks:
            items = [t for ww, _r, t in tw if ww == w]
            realized = [t["realized"] for t in items]
            if m == "liveComposite":
                pred = [t["liveComposite"] or 0.0 for t in items]
            else:
                pred = [t[m]["lineupTotal"] for t in items]
            c, d = mt.all_play_concordance(pred, realized)
            if d:
                conc_num += c * d
                conc_den += d
            rhos.append(mt.spearman(pred, realized))
            if m != "liveComposite":
                crhos.append(mt.spearman([t[m]["composite"] for t in items], realized))
        block: dict[str, Any] = {
            "allPlayConcordance": conc_num / conc_den if conc_den else None,
            "meanWeeklySpearman": statistics.fmean([r for r in rhos if r is not None])
            if rhos
            else None,
        }
        if m != "liveComposite":
            block["lineupAgreement"] = mt.cluster_bootstrap(
                tw, key, agreement(m), b=BOOTSTRAP_B, seed=SEED
            )
            block["compositeMeanWeeklySpearman"] = (
                statistics.fmean([r for r in crhos if r is not None]) if crhos else None
            )
        out["byModel"][m] = block
    return out


# ── gates ──────────────────────────────────────────────────────────────────────────────────────


def gates(acc, conc, stab, team) -> dict[str, Any]:
    out: dict[str, Any] = {}
    c0 = acc["byModel"]["C0"]
    out["championDiagnosis"] = {
        "D": c0["D"],
        "ratioOFF": c0["ratioOFF"],
        "ratioIDP": c0["ratioIDP"],
        "distortionConfirmed": (
            c0["D"]["ci95"][0] is not None and (c0["D"]["ci95"][0] > 1 or c0["D"]["ci95"][1] < 1)
        ),
    }
    verdicts = {}
    for x in cv.CHALLENGERS:
        bx = acc["byModel"][x]
        g: dict[str, Any] = {}
        d = bx["D"]["estimate"]
        g["G1"] = bool(
            d is not None
            and abs(d - 1) <= G1_D_TOL
            and bx["ratioOFF"] is not None
            and G1_R_BAND[0] <= bx["ratioOFF"] <= G1_R_BAND[1]
            and bx["ratioIDP"] is not None
            and G1_R_BAND[0] <= bx["ratioIDP"] <= G1_R_BAND[1]
        )
        dm = bx["dMAEvsC0"]
        fam_worse = [
            f
            for f, fb in acc["families"].items()
            if fb["gated"] and fb[x].get("dMAEvsC0") and (fb[x]["dMAEvsC0"]["ci95"][1] or 0) < 0
        ]
        g["G2"] = bool(
            dm["estimate"] and dm["estimate"] > 0 and (dm["ci95"][0] or 0) > 0 and not fam_worse
        )
        g["G2_familiesSignificantlyWorse"] = fam_worse
        if not conc["sufficient"]:
            g["G3"] = "INSUFFICIENT"
        else:
            lo = conc["byModel"][x]["deltaVsC0"]["ci95"][0]
            g["G3"] = bool(lo is not None and lo > 0)
        sx, s0 = stab["mean"][x], stab["mean"]["C0"]
        g["G4"] = bool(sx is not None and s0 is not None and sx >= s0 - G4_TOL)
        if not team["sufficient"]:
            g["G5"] = g["G6"] = "INSUFFICIENT"
        else:
            ax = team["byModel"][x]["lineupAgreement"]["estimate"]
            a0 = team["byModel"]["C0"]["lineupAgreement"]["estimate"]
            g["G5"] = bool(ax is not None and a0 is not None and ax >= a0 - G5_TOL)
            cx = team["byModel"][x]["allPlayConcordance"]
            c0c = team["byModel"]["C0"]["allPlayConcordance"]
            g["G6"] = bool(cx is not None and c0c is not None and cx >= c0c - G6_TOL)
        failing = [k for k in ("G1", "G2", "G3", "G4", "G5", "G6") if g[k] is not True]
        g["verdict"] = "PASSES_ALL_GATES" if not failing else "DOES_NOT_PASS"
        g["failing"] = failing
        verdicts[x] = g
    out["challengers"] = verdicts
    passing = [x for x in cv.CHALLENGERS if verdicts[x]["verdict"] == "PASSES_ALL_GATES"]
    rec = None
    if passing:
        order = {"CG": 0, "CR": 1, "CF": 2}
        best = min(acc["byModel"][x]["mae"] for x in passing)
        near = [x for x in passing if acc["byModel"][x]["mae"] - best <= MAE_TIE]
        rec = min(near, key=lambda x: order[x])
    out["recommendation"] = rec
    return out


# ── commands ───────────────────────────────────────────────────────────────────────────────────


def _model_meta(models: Mapping[str, cv.ConversionModel]) -> dict[str, Any]:
    return {m: model.to_dict() for m, model in models.items()}


def run_evaluate(args) -> dict[str, Any]:
    study = Study(offline=args.offline)
    for w in range(1, 8):
        if not study.is_final(w):
            raise v1.StudyRefusal(f"week {w} not final")
    fits_by_week: dict[int, dict[str, cv.ConversionModel]] = {}
    evals: dict[int, dict[str, Any]] = {}
    for h in sorted(set(DEVELOPMENT + HOLDOUT)):
        fit_weeks = tuple(range(1, h))
        assert all(w < h for w in fit_weeks)
        fits_by_week[h] = fit_all(study, fit_weeks)
        evals[h] = evaluate_week(study, h, fits_by_week[h])
    receipts = {}
    for w in range(1, 8):
        wd = study.week(w)
        rost = [r for r in wd.rows if r.points is not None and r.host_points is not None]
        match = sum(1 for r in rost if abs(r.points - r.host_points) <= 0.02)
        cens = Counter(
            "unpriced"
            if r.status == v1.APPEARED and r.family in cv.GROUP_OF and r.ros_value is None
            else (r.status or "none")
            for r in wd.rows
        )
        receipts[w] = {
            "snapshot": wd.snapshot.relative_to(REPO).as_posix(),
            "snapshotSha256": v1.sha256_file(wd.snapshot),
            "rosterPlayerWeeks": len(wd.rows),
            "population": sum(1 for r in wd.rows if in_population(r)),
            "census": dict(cens),
            "hostPointsReconciled": {"match": match, "of": len(rost)},
        }

    def block(weeks):
        evs = [evals[w] for w in weeks]
        recs = [r for ev in evs for r in ev["records"]]
        acc = accuracy_block(recs, EVAL_MODELS)
        conc = concordance_block(evs, EVAL_MODELS)
        team = team_block(evs, EVAL_MODELS)
        return acc, conc, team, evs

    acc, conc, team, hevs = block(HOLDOUT)
    stab = stability_block(study, fits_by_week, EVAL_MODELS)
    horizon = ros_horizon_concordance(study, hevs, EVAL_MODELS)
    g = gates(acc, conc, stab, team)
    dacc, dconc, dteam, _ = block(DEVELOPMENT)

    # Descriptive: as-of points per rosValue unit by family over weeks 1-7 (no model).
    ppu = {}
    for fam in cv.FAMILIES:
        ys, rs = [], []
        for w in range(1, 8):
            for r in study.week(w).rows:
                if in_population(r) and r.family == fam:
                    ys.append(r.points)
                    rs.append(r.ros_value)
        ppu[fam] = {
            "n": len(ys),
            "meanPoints": statistics.fmean(ys) if ys else None,
            "meanRosValue": statistics.fmean(rs) if rs else None,
            "pointsPerRosUnit": (sum(ys) / sum(rs)) if rs and sum(rs) > 0 else None,
        }
    # Descriptive: IDP share of the live starting-lineup score vs IDP share of awarded points.
    shares = []
    for w in range(1, 8):
        wd = study.week(w)
        pts = {r.pid: r.host_points for r in wd.rows}
        fam = {r.pid: r.family for r in wd.rows}
        for rid, starters in wd.awarded_starters.items():
            tot = sum(pts.get(p) or 0.0 for p in starters)
            idp = sum(pts.get(p) or 0.0 for p in starters if fam.get(p) in cv.IDP_FAMILIES)
            shares.append(
                {
                    "week": w,
                    "liveIdpShareOfStartingScore": wd.live_starting_idp_share.get(rid),
                    "awardedIdpShareOfPoints": (idp / tot) if tot > 0 else None,
                }
            )
    live_sh = [
        s["liveIdpShareOfStartingScore"]
        for s in shares
        if s["liveIdpShareOfStartingScore"] is not None
    ]
    real_sh = [
        s["awardedIdpShareOfPoints"] for s in shares if s["awardedIdpShareOfPoints"] is not None
    ]
    # Residual SD per family (holdout, CR) — descriptive spread.
    resid = {}
    for fam in cv.FAMILIES:
        for m in ("C0", "CR"):
            e = [
                r["y"] - r["mu"][m]
                for r in acc_records(hevs)
                if r["family"] == fam and r["mu"][m] is not None
            ]
            resid.setdefault(fam, {})[m] = statistics.pstdev(e) if len(e) > 1 else None

    payload = {
        "promotes": False,
        "status": "RESEARCH_EVIDENCE_NOT_FOR_PROMOTION",
        "preregistration": PREREGISTRATION,
        "code": v1.code_identity(),
        "scriptSha256": v1.sha256_file(Path(__file__)),
        "cardFingerprint": study.fingerprint,
        "slots": study.slots,
        "seed": SEED,
        "bootstrapB": BOOTSTRAP_B,
        "holdoutWeeks": list(HOLDOUT),
        "developmentWeeks": list(DEVELOPMENT),
        "receipts": receipts,
        "fits": {str(h): _model_meta(fits_by_week[h]) for h in fits_by_week},
        "holdout": {
            "accuracy": acc,
            "concordance": conc,
            "rosHorizonConcordance": horizon,
            "teams": team,
        },
        "stability": stab,
        "gates": g,
        "development": {"accuracy": dacc, "concordance": dconc, "teams": dteam},
        "descriptive": {
            "pointsPerRosUnitWeeks1to7": ppu,
            "idpShare": {
                "teamWeeks": len(shares),
                "liveMeanIdpShareOfStartingScore": statistics.fmean(live_sh) if live_sh else None,
                "awardedMeanIdpShareOfPoints": statistics.fmean(real_sh) if real_sh else None,
            },
            "holdoutResidualSdByFamily": resid,
        },
        "networkCalls": study.f.network_calls,
    }
    write_json(OUT_DIR / "evaluation.json", payload)
    # Frozen week-8 confirmation fits (weeks 1-7).
    final = fit_all(study, FINAL_FIT_WEEKS)
    write_json(
        OUT_DIR / "fits_week8_frozen.json",
        {
            "promotes": False,
            "preregistration": PREREGISTRATION,
            "fitWeeks": list(FINAL_FIT_WEEKS),
            "confirmWeek": CONFIRM_WEEK,
            "models": _model_meta(final),
        },
    )
    return payload


def acc_records(evs):
    return [r for ev in evs for r in ev["records"]]


def run_downstream(args) -> dict[str, Any]:
    """Latest snapshot + current rosters under fits on weeks 1-7 (preregistration §6)."""
    study = Study(offline=args.offline)
    models = fit_all(study, FINAL_FIT_WEEKS)
    wd = study.week(CONFIRM_WEEK)
    preds = {m: {r.pid: predict_row(models[m], wd, r) for r in wd.rows} for m in models}
    by_rid: dict[int, list[PW]] = defaultdict(list)
    for r in wd.rows:
        by_rid[r.roster_id].append(r)
    # anonymous team index by roster id order
    idx = {rid: i + 1 for i, rid in enumerate(sorted(by_rid))}
    teams_out = []
    lineup_changes = {m: [] for m in models if m != "C0"}
    for rid, rows in sorted(by_rid.items()):
        entry = {"team": idx[rid], "liveComposite": wd.live_composite.get(rid)}
        base = lineup_for(rows, preds["C0"], study.slots)
        base_starters = {str(s.get("playerId")) for s in base.starting_lineup}
        for m in models:
            sol = lineup_for(rows, preds[m], study.slots)
            entry[m] = {
                "expectedLineupPoints": round(sol.starting_lineup_score, 2),
                "composite": round(composite(sol), 2),
            }
            if m != "C0":
                st = {str(s.get("playerId")) for s in sol.starting_lineup}
                lineup_changes[m].append(len(st - base_starters))
        teams_out.append(entry)

    def ranks(key):
        vals = sorted(teams_out, key=lambda t: -(key(t) or 0.0))
        return {t["team"]: i + 1 for i, t in enumerate(vals)}

    live_rank = ranks(lambda t: t["liveComposite"])
    rank_tables = {"liveComposite": live_rank}
    for m in models:
        rank_tables[f"{m}:composite"] = ranks(lambda t, m=m: t[m]["composite"])
        rank_tables[f"{m}:expectedLineupPoints"] = ranks(
            lambda t, m=m: t[m]["expectedLineupPoints"]
        )
    for t in teams_out:
        t["ranks"] = {k: v[t["team"]] for k, v in rank_tables.items()}

    # Whole-snapshot view: top-100 IDP share by rosValue / μ / PAR (snapshot family).
    snap = wd.snapshot_players
    snap_rows = []
    for p in snap:
        fam = cv.family_of(p.get("position"))
        rv = float(p.get("rosValue") or 0.0)
        if fam is None or rv <= 0:
            continue
        rank = cv.rank_in_family(wd.ladders, fam, rv)
        snap_rows.append(
            {
                "name": p.get("canonicalName"),
                "family": fam,
                "rosValue": rv,
                "rosRankOverall": p.get("rosRankOverall"),
                "mu": {m: models[m].predict(fam, rv, rank) for m in models},
            }
        )
    # PAR per model from replacement over the current rosters (production owner).
    rosters_for_par = [
        {
            "players": [
                {
                    "playerId": r.pid,
                    "position": r.family or r.position,
                    "fantasyPositions": list(r.fantasy_positions),
                    "_mu": {m: preds[m][r.pid] for m in models},
                }
                for r in rows
            ]
        }
        for rows in by_rid.values()
    ]
    replacement = {}
    for m in models:
        sub = par_mod.substitute_values(rosters_for_par, lambda p, m=m: p["_mu"][m])
        replacement[m] = par_mod.replacement_points(sub, study.slots)
    for r in snap_rows:
        r["par"] = {m: par_mod.par_for(r["family"], r["mu"][m], replacement[m]) for m in models}

    def idp_share_top(key, n=100):
        ranked = sorted([r for r in snap_rows if key(r) is not None], key=lambda r: -key(r))[:n]
        return (
            sum(1 for r in ranked if r["family"] in cv.IDP_FAMILIES) / len(ranked)
            if ranked
            else None
        )

    top100 = {"rosRankOverall<=100": idp_share_top(lambda r: -(r["rosRankOverall"] or 1e9))}
    for m in models:
        top100[f"{m}:mu"] = idp_share_top(lambda r, m=m: r["mu"][m])
        top100[f"{m}:par"] = idp_share_top(lambda r, m=m: r["par"][m])

    # Representative players: best by rosValue per family, plus deep bench samples.
    reps = []
    for fam in cv.FAMILIES:
        fr = sorted([r for r in snap_rows if r["family"] == fam], key=lambda r: -r["rosValue"])
        for pos in (0, 11, 35):
            if pos < len(fr):
                r = fr[pos]
                reps.append(
                    {
                        "family": fam,
                        "familyRank": pos + 1,
                        "name": r["name"],
                        "rosValue": round(r["rosValue"], 2),
                        "mu": {
                            m: (round(v, 2) if v is not None else None) for m, v in r["mu"].items()
                        },
                        "par": {
                            m: (round(v, 2) if v is not None else None) for m, v in r["par"].items()
                        },
                    }
                )
    payload = {
        "promotes": False,
        "status": "RESEARCH_EVIDENCE_NOT_FOR_PROMOTION",
        "preregistration": PREREGISTRATION,
        "code": v1.code_identity(),
        "snapshot": wd.snapshot.relative_to(REPO).as_posix(),
        "snapshotSha256": v1.sha256_file(wd.snapshot),
        "fitWeeks": list(FINAL_FIT_WEEKS),
        "models": _model_meta(models),
        "teams": teams_out,
        "lineupStarterChangesVsC0": {
            m: {"meanChanged": statistics.fmean(v) if v else None, "max": max(v) if v else None}
            for m, v in lineup_changes.items()
        },
        "replacementStarterTier": replacement,
        "idpShareOfTop100": top100,
        "representativePlayers": reps,
        "playoffSim": "INSUFFICIENT_BY_CONSTRUCTION (no completed season with as-of ROS snapshots; see V3 C2)",
    }
    write_json(OUT_DIR / "downstream.json", payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("command", choices=("evaluate", "downstream"))
    p.add_argument("--offline", action="store_true", help="use only cached bodies")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "evaluate":
            out = run_evaluate(args)
            print(json.dumps(out["gates"], indent=2, sort_keys=True))
        else:
            out = run_downstream(args)
            print(json.dumps(out["idpShareOfTop100"], indent=2, sort_keys=True))
    except v1.StudyRefusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
