"""Champion and opportunity challengers: stat line first, then the canonical scorer.

Models (preregistration §2):

* ``C0`` — champion: per-key expanding mean over the player's prior played weeks.
* ``M1`` — C0 × opponent matchup factor (allowed league-card points per defensive snap
  to the player's true-position sub-group, by key class).
* ``M2`` — snaps / role: per-snap rates shrunk toward the sub-group rate (κ_vol for
  tackles, κ_splash for every other IDP key — the splash regression) × expected snaps.
* ``M3`` — M2 + injury / replacement snaps (week-W report, PIT unverified).
* ``M4`` — M2 + family-specific opponent opportunity (CB pass volume; LB/S tackle
  opportunity allowed to the sub-group; EDGE/DT dropbacks × pressure allowed).
* ``M5`` — M2 + M3 + M4, the designated challenger.

Every hyper-parameter is fit on weeks before the target week only
(:func:`fit_params`), from a grid declared in the preregistration; when no fit week
exists the declared PRIORS apply.  A missing input is a named fallback reason, never
a zero.  Pure: no I/O, no clock; deterministic (sorted iteration everywhere).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from src.league_intel.scorer import score_stat_line
from src.ros.idp_opportunity.leakage import AsOfView
from src.ros.idp_opportunity.positions import UNKNOWN, challenger_family

__all__ = [
    "CLASSES",
    "MODELS",
    "PRIORS",
    "Card",
    "Context",
    "Params",
    "Row",
    "build_context",
    "build_rows",
    "fast_points",
    "fit_params",
    "played",
    "project_points",
    "project_stat_line",
]

MODELS = ("C0", "M1", "M2", "M3", "M4", "M5")
CLASSES = ("vol", "pr", "oth")
VOLUME_KEYS = frozenset({"idp_tkl_solo", "idp_tkl_ast", "idp_tkl"})
PASS_RUSH_KEYS = frozenset({"idp_sack", "idp_sack_yd", "idp_qb_hit"})
RECENT_WEEKS = 3

KAPPA_GRID = (0.0, 25.0, 50.0, 100.0, 200.0, 400.0, 800.0, 1600.0)
KAPPA_OPP_GRID = (50.0, 200.0, 800.0)
ALPHA_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)


def key_class(key: str) -> str:
    if key in VOLUME_KEYS:
        return "vol"
    if key in PASS_RUSH_KEYS:
        return "pr"
    return "oth"


def played(line: Mapping[str, Any] | None) -> bool:
    """A defender PLAYED a week when the payload carries ``def_snp > 0``."""
    if not line:
        return False
    try:
        return float(line.get("def_snp") or 0.0) > 0.0
    except (TypeError, ValueError):
        return False


def _f(line: Mapping[str, Any], key: str) -> float:
    v = line.get(key)
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True)
class Card:
    """A league scoring card: the full settings map (what the scorer reads) plus the
    nonzero-rate keys split into IDP and other."""

    settings: Mapping[str, float]
    rates: Mapping[str, float]
    idp_keys: tuple[str, ...]
    other_keys: tuple[str, ...]

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any]) -> Card:
        clean: dict[str, float] = {}
        for k, v in settings.items():
            try:
                clean[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
        rates = {k: v for k, v in sorted(clean.items()) if v != 0.0}
        idp = tuple(k for k in rates if k.startswith("idp_"))
        other = tuple(k for k in rates if not k.startswith("idp_"))
        return cls(settings=clean, rates=rates, idp_keys=idp, other_keys=other)

    def points(self, line: Mapping[str, Any]) -> float:
        """THE score: the canonical scorer, nothing else."""
        return score_stat_line(line, self.settings).total_points


@dataclass(frozen=True)
class Params:
    kappa_vol: float = 100.0
    kappa_splash: float = 400.0
    kappa_opp: float = 200.0
    alpha: float = 0.5
    beta: Mapping[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kappaVol": self.kappa_vol,
            "kappaSplash": self.kappa_splash,
            "kappaOpp": self.kappa_opp,
            "alpha": self.alpha,
            "beta": dict(sorted(self.beta.items())),
        }


#: Declared PRIORS (preregistration §2), used when no fit week exists.
PRIORS = Params()


# ── context: everything knowable before the cutoff week ──────────────────────


@dataclass
class Context:
    cutoff: int
    history: dict[str, list[tuple[int, Mapping[str, Any]]]]
    group_sums: dict[str, dict[str, float]]
    group_snaps: dict[str, float]
    last_team: dict[str, str]
    recent_snaps: dict[str, float]
    team_members: dict[tuple[str, str], list[str]]
    # opponent aggregates, keyed by the OFFENSE faced
    snaps_faced: dict[str, float]
    allowed_pts: dict[tuple[str, str, str], float]
    tackles_allowed: dict[tuple[str, str], float]
    pressure_allowed: dict[str, float]
    off_games: dict[str, int]
    off_dropbacks: dict[str, float]
    off_wr_targets: dict[str, float]
    league: dict[str, float]
    diagnostics: dict[str, int]


def _group_of(view: AsOfView, pid: str) -> tuple[str, str, str]:
    pos = view.position(pid)
    if pos is None:
        return ("", UNKNOWN, "")
    family, subgroup = pos
    rate_group = subgroup if subgroup != UNKNOWN else f"FAM:{family}"
    return family, subgroup, rate_group


def build_context(view: AsOfView, card: Card) -> Context:
    """Aggregate weeks ``< view.cutoff`` only (every read goes through the view)."""
    history: dict[str, list[tuple[int, Mapping[str, Any]]]] = defaultdict(list)
    group_sums: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    group_snaps: dict[str, float] = defaultdict(float)
    last_team: dict[str, str] = {}
    snaps_faced: dict[str, float] = defaultdict(float)
    allowed_pts: dict[tuple[str, str, str], float] = defaultdict(float)
    tackles_allowed: dict[tuple[str, str], float] = defaultdict(float)
    pressure_allowed: dict[str, float] = defaultdict(float)
    off_games: dict[str, int] = defaultdict(int)
    off_db: dict[str, float] = defaultdict(float)
    off_wr: dict[str, float] = defaultdict(float)
    diag = {"statRowsUnattributedToTeam": 0}
    team_game_snaps: list[float] = []
    last_week_of_team: dict[str, int] = {}
    team_week_players: dict[tuple[int, str], list[str]] = defaultdict(list)

    for w in view.weeks_before():
        stats = view.stats_week(w)
        teams = view.team_week(w)
        tm_snaps: dict[str, float] = {}
        for pid in sorted(stats):
            line = stats[pid]
            pos = view.position(pid)
            if pos is None or not played(line):
                continue
            history[pid].append((w, line))
            _, subgroup, rate_group = _group_of(view, pid)
            snp = _f(line, "def_snp")
            group_snaps[rate_group] += snp
            gs = group_sums[rate_group]
            for k in card.idp_keys:
                gs[k] += _f(line, k)
            tv = teams.get(pid)
            if tv is None:
                if any(_f(line, k) for k in card.idp_keys):
                    diag["statRowsUnattributedToTeam"] += 1
                continue
            team, opp = tv
            last_team[pid] = team
            team_week_players[(w, team)].append(pid)
            last_week_of_team[team] = max(last_week_of_team.get(team, 0), w)
            tm = _f(line, "tm_def_snp")
            if tm > 0:
                tm_snaps[(team)] = max(tm_snaps.get(team, 0.0), tm)
            if subgroup != UNKNOWN:
                vol = sum(
                    card.rates[k] * _f(line, k) for k in card.idp_keys if key_class(k) == "vol"
                )
                spl = sum(
                    card.rates[k] * _f(line, k) for k in card.idp_keys if key_class(k) != "vol"
                )
                allowed_pts[(opp, subgroup, "vol")] += vol
                allowed_pts[(opp, subgroup, "spl")] += spl
                tackles_allowed[(opp, subgroup)] += _f(line, "idp_tkl_solo") + _f(
                    line, "idp_tkl_ast"
                )
            pressure_allowed[opp] += _f(line, "idp_sack") + _f(line, "idp_qb_hit")
        for team, tm in sorted(tm_snaps.items()):
            opp = next((teams[p][1] for p in team_week_players[(w, team)] if p in teams), None)
            if opp is None:
                continue
            snaps_faced[opp] += tm
            team_game_snaps.append(tm)
        for off_team, vol in sorted(view.offense_week(w).items()):
            off_games[off_team] += 1
            off_db[off_team] += float(vol.get("dropbacks") or 0.0)
            off_wr[off_team] += float(vol.get("wr_targets") or 0.0)

    # recent snaps (last RECENT_WEEKS played) and recent team membership
    recent_snaps: dict[str, float] = {}
    for pid, rows in history.items():
        tail = rows[-RECENT_WEEKS:]
        recent_snaps[pid] = sum(_f(r, "def_snp") for _, r in tail) / len(tail)
    team_members: dict[tuple[str, str], list[str]] = defaultdict(list)
    for (w, team), pids in sorted(team_week_players.items()):
        if w < last_week_of_team.get(team, 0) - 1:
            continue
        for pid in pids:
            _, subgroup, _ = _group_of(view, pid)
            key = (team, subgroup)
            if subgroup != UNKNOWN and pid not in team_members[key]:
                team_members[key].append(pid)

    n_tg = len(team_game_snaps)
    snaps_pg = sum(team_game_snaps) / n_tg if n_tg else 0.0
    games_total = sum(off_games.values())
    db_pg = sum(off_db.values()) / games_total if games_total else 0.0
    total_faced = sum(snaps_faced.values())
    league: dict[str, float] = {
        "snapsPerGame": snaps_pg,
        "dropbacksPerGame": db_pg,
        "wrTargetsPerGame": sum(off_wr.values()) / games_total if games_total else 0.0,
        "pressurePerDropback": (
            sum(pressure_allowed.values()) / sum(off_db.values()) if sum(off_db.values()) else 0.0
        ),
        "snapsFaced": total_faced,
    }
    for (opp, sg, c), v in allowed_pts.items():
        league[f"pts:{sg}:{c}"] = league.get(f"pts:{sg}:{c}", 0.0) + v
    for (opp, sg), v in tackles_allowed.items():
        league[f"tkl:{sg}"] = league.get(f"tkl:{sg}", 0.0) + v

    return Context(
        cutoff=view.cutoff,
        history=dict(history),
        group_sums={g: dict(v) for g, v in group_sums.items()},
        group_snaps=dict(group_snaps),
        last_team=last_team,
        recent_snaps=recent_snaps,
        team_members=dict(team_members),
        snaps_faced=dict(snaps_faced),
        allowed_pts=dict(allowed_pts),
        tackles_allowed=dict(tackles_allowed),
        pressure_allowed=dict(pressure_allowed),
        off_games=dict(off_games),
        off_dropbacks=dict(off_db),
        off_wr_targets=dict(off_wr),
        league=league,
        diagnostics=diag,
    )


# ── per-player ingredients ────────────────────────────────────────────────────

#: A factor ingredient: (numerator, denominator, league mean rate, κ unit multiplier).
Factor = tuple[float, float, float, float]


@dataclass
class Row:
    pid: str
    week: int
    family: str
    subgroup: str
    challenger: str | None
    c0: dict[str, float]
    snp: float
    sums: dict[str, float]
    grate: dict[str, float]
    exp_snaps: float | None
    x_vac: float
    factors: dict[str, Factor]
    opponent: str | None
    reasons: tuple[str, ...]
    # fast-path aggregates (weighted by card rates)
    a: dict[str, float] = field(default_factory=dict)
    b: dict[str, float] = field(default_factory=dict)
    c0_cls: dict[str, float] = field(default_factory=dict)
    c0_other: float = 0.0


def _vacated(ctx: Context, view: AsOfView, pid: str, team: str, subgroup: str) -> float:
    report = view.pregame_injury_report(team)
    if not report or subgroup == UNKNOWN:
        return 0.0
    members = ctx.team_members.get((team, subgroup), [])
    out = [m for m in members if m != pid and str(report.get(m, "")).lower() in {"out", "doubtful"}]
    if not out:
        return 0.0
    vac = sum(ctx.recent_snaps.get(m, 0.0) for m in out)
    recipients = [m for m in members if m not in out]
    return vac / len(recipients) if recipients else 0.0


def build_rows(view: AsOfView, ctx: Context, card: Card, candidates: Iterable[str]) -> list[Row]:
    """Ingredients for week ``view.cutoff``, built only from the view and its context."""
    if ctx.cutoff != view.cutoff:
        raise ValueError("context and view disagree on the cutoff week")
    rows: list[Row] = []
    lg = ctx.league
    snaps_pg = lg.get("snapsPerGame") or 0.0
    for pid in sorted(set(candidates)):
        hist = ctx.history.get(pid)
        family, subgroup, rate_group = _group_of(view, pid)
        if not hist or not family:
            continue
        reasons: list[str] = []
        n = len(hist)
        keys = card.idp_keys + card.other_keys
        c0 = {k: sum(_f(r, k) for _, r in hist) / n for k in keys}
        snp = sum(_f(r, "def_snp") for _, r in hist)
        sums = {k: sum(_f(r, k) for _, r in hist) for k in card.idp_keys}
        gsn = ctx.group_snaps.get(rate_group, 0.0)
        gsum = ctx.group_sums.get(rate_group, {})
        grate = {k: (gsum.get(k, 0.0) / gsn if gsn > 0 else 0.0) for k in card.idp_keys}
        if subgroup == UNKNOWN:
            reasons.append("subgroup_unknown")
        tail = hist[-RECENT_WEEKS:]
        shares = [
            _f(r, "def_snp") / _f(r, "tm_def_snp") for _, r in tail if _f(r, "tm_def_snp") > 0
        ]
        team_snaps = [_f(r, "tm_def_snp") for _, r in hist if _f(r, "tm_def_snp") > 0]
        exp_snaps = (
            (sum(shares) / len(shares)) * (sum(team_snaps) / len(team_snaps))
            if shares and team_snaps
            else None
        )
        if exp_snaps is None:
            reasons.append("team_snaps_missing")
        team = ctx.last_team.get(pid)
        opponent = view.pregame_opponent(team) if team else None
        if team is None:
            reasons.append("team_unknown")
        elif opponent is None:
            reasons.append("opponent_unknown")
        x_vac = _vacated(ctx, view, pid, team, subgroup) if team else 0.0
        factors: dict[str, Factor] = {}
        if opponent is not None and snaps_pg > 0:
            faced = ctx.snaps_faced.get(opponent, 0.0)
            tot_faced = lg.get("snapsFaced") or 0.0
            if subgroup != UNKNOWN and tot_faced > 0:
                for c in ("vol", "spl"):
                    mean = lg.get(f"pts:{subgroup}:{c}", 0.0) / tot_faced
                    num = ctx.allowed_pts.get((opponent, subgroup, c), 0.0)
                    factors[f"mv_{c}"] = (num, faced, mean, 1.0)
                factors["tackle"] = (
                    ctx.tackles_allowed.get((opponent, subgroup), 0.0),
                    faced,
                    lg.get(f"tkl:{subgroup}", 0.0) / tot_faced,
                    1.0,
                )
            games = float(ctx.off_games.get(opponent, 0))
            factors["dropbacks"] = (
                ctx.off_dropbacks.get(opponent, 0.0),
                games,
                lg.get("dropbacksPerGame", 0.0),
                1.0 / snaps_pg,
            )
            factors["wr"] = (
                ctx.off_wr_targets.get(opponent, 0.0),
                games,
                lg.get("wrTargetsPerGame", 0.0),
                1.0 / snaps_pg,
            )
            factors["pressure"] = (
                ctx.pressure_allowed.get(opponent, 0.0),
                ctx.off_dropbacks.get(opponent, 0.0),
                lg.get("pressurePerDropback", 0.0),
                (lg.get("dropbacksPerGame", 0.0) / snaps_pg),
            )
        row = Row(
            pid=pid,
            week=view.cutoff,
            family=family,
            subgroup=subgroup,
            challenger=challenger_family(subgroup),
            c0=c0,
            snp=snp,
            sums=sums,
            grate=grate,
            exp_snaps=exp_snaps,
            x_vac=x_vac,
            factors=factors,
            opponent=opponent,
            reasons=tuple(reasons),
        )
        for c in CLASSES:
            ks = [k for k in card.idp_keys if key_class(k) == c]
            row.a[c] = sum(card.rates[k] * sums[k] for k in ks)
            row.b[c] = sum(card.rates[k] * grate[k] for k in ks)
            row.c0_cls[c] = sum(card.rates[k] * c0[k] for k in ks)
        row.c0_other = sum(card.rates[k] * c0[k] for k in card.other_keys)
        rows.append(row)
    return rows


# ── projection ────────────────────────────────────────────────────────────────


def _ratio(f: Factor | None, kappa_opp: float) -> float:
    if f is None:
        return 1.0
    num, den, mean, unit = f
    if mean <= 0:
        return 1.0
    k = kappa_opp * unit
    if den + k <= 0:
        return 1.0
    return ((num + k * mean) / (den + k)) / mean


def class_factors(row: Row, model: str, p: Params) -> dict[str, float]:
    out = {c: 1.0 for c in CLASSES}
    if model == "M1":
        if "mv_vol" in row.factors:
            out["vol"] = _ratio(row.factors["mv_vol"], p.kappa_opp) ** p.alpha
            spl = _ratio(row.factors["mv_spl"], p.kappa_opp) ** p.alpha
            out["pr"] = out["oth"] = spl
        return out
    if model not in ("M4", "M5") or not row.factors:
        return out
    fam = row.challenger
    if fam == "CB":
        g = math.sqrt(
            _ratio(row.factors.get("dropbacks"), p.kappa_opp)
            * _ratio(row.factors.get("wr"), p.kappa_opp)
        )
        out = {c: g**p.alpha for c in CLASSES}
    elif fam == "LB_S":
        out["vol"] = _ratio(row.factors.get("tackle"), p.kappa_opp) ** p.alpha
    elif fam == "EDGE_DT":
        out["pr"] = (
            _ratio(row.factors.get("dropbacks"), p.kappa_opp)
            * _ratio(row.factors.get("pressure"), p.kappa_opp)
        ) ** p.alpha
    return out


def effective_model(row: Row, model: str) -> str:
    """The model actually used for a row (a missing input falls back, named)."""
    if model in ("M2", "M3", "M4", "M5") and row.exp_snaps is None:
        return "C0"
    return model


def _snaps(row: Row, model: str, p: Params) -> float:
    es = float(row.exp_snaps or 0.0)
    if model in ("M3", "M5") and row.x_vac:
        es += p.beta.get(row.subgroup, 0.0) * row.x_vac
    return max(es, 0.0)


def _kappa(p: Params, c: str) -> float:
    return p.kappa_vol if c == "vol" else p.kappa_splash


def project_stat_line(row: Row, model: str, p: Params, card: Card) -> dict[str, float]:
    """The projected stat line (card keys only)."""
    m = effective_model(row, model)
    line = {k: row.c0[k] for k in card.other_keys}
    fac = class_factors(row, m, p)
    if m in ("C0", "M1"):
        for k in card.idp_keys:
            line[k] = row.c0[k] * fac[key_class(k)]
        return line
    es = _snaps(row, m, p)
    for k in card.idp_keys:
        c = key_class(k)
        kap = _kappa(p, c)
        den = row.snp + kap
        rate = (row.sums[k] + kap * row.grate[k]) / den if den > 0 else 0.0
        line[k] = es * rate * fac[c]
    return line


def project_points(row: Row, model: str, p: Params, card: Card) -> float:
    """Projected league-card points through the CANONICAL scorer."""
    return card.points(project_stat_line(row, model, p, card))


def fast_points(row: Row, model: str, p: Params) -> float:
    """Linear fast path used inside the fit grid; equal to :func:`project_points`
    (pinned by test) because the scorer is a pure dot product."""
    m = effective_model(row, model)
    fac = class_factors(row, m, p)
    if m in ("C0", "M1"):
        return row.c0_other + sum(row.c0_cls[c] * fac[c] for c in CLASSES)
    es = _snaps(row, m, p)
    total = row.c0_other
    for c in CLASSES:
        kap = _kappa(p, c)
        den = row.snp + kap
        if den > 0:
            total += es * (row.a[c] + kap * row.b[c]) / den * fac[c]
    return total


# ── fitting (weeks < W only) ─────────────────────────────────────────────────


@dataclass(frozen=True)
class FitRow:
    row: Row
    actual: float
    actual_snaps: float


def _mae(rows: Sequence[FitRow], model: str, p: Params) -> float:
    if not rows:
        return math.inf
    return sum(abs(fast_points(r.row, model, p) - r.actual) for r in rows) / len(rows)


def _grid_opp(rows: Sequence[FitRow], model: str, base: Params) -> Params:
    best = (math.inf, base)
    for ko in KAPPA_OPP_GRID:
        for al in ALPHA_GRID:
            cand = replace(base, kappa_opp=ko, alpha=al)
            score = _mae(rows, model, cand)
            if score < best[0] - 1e-12:
                best = (score, cand)
    return best[1]


def fit_params(rows: Sequence[FitRow]) -> dict[str, Params]:
    """Per-model parameters from pseudo-out-of-sample rows of earlier weeks."""
    if not rows:
        return {m: PRIORS for m in MODELS}
    best = (math.inf, PRIORS)
    for kv in KAPPA_GRID:
        for ks in KAPPA_GRID:
            cand = replace(PRIORS, kappa_vol=kv, kappa_splash=ks)
            score = _mae(rows, "M2", cand)
            if score < best[0] - 1e-12:
                best = (score, cand)
    m2 = best[1]
    # β_g: least squares through the origin of the snaps residual on vacated snaps
    num: dict[str, float] = defaultdict(float)
    den: dict[str, float] = defaultdict(float)
    for r in rows:
        if r.row.x_vac > 0 and r.row.exp_snaps is not None:
            num[r.row.subgroup] += r.row.x_vac * (r.actual_snaps - r.row.exp_snaps)
            den[r.row.subgroup] += r.row.x_vac**2
    beta = {g: num[g] / den[g] for g in sorted(den) if den[g] > 0}
    m3 = replace(m2, beta=beta)
    return {
        "C0": PRIORS,
        "M1": _grid_opp(rows, "M1", PRIORS),
        "M2": m2,
        "M3": m3,
        "M4": _grid_opp(rows, "M4", m2),
        "M5": _grid_opp(rows, "M5", m3),
    }


def residual_quantiles(
    rows: Sequence[FitRow], model: str, p: Params, *, min_n: int = 30
) -> dict[str, tuple[float, float] | None]:
    """Per family, the 10th / 90th percentile of (actual − projection)."""
    by_fam: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by_fam[r.row.family].append(r.actual - fast_points(r.row, model, p))
    out: dict[str, tuple[float, float] | None] = {}
    for fam, res in sorted(by_fam.items()):
        out[fam] = (_quantile(res, 0.10), _quantile(res, 0.90)) if len(res) >= min_n else None
    return out


def _quantile(values: Sequence[float], q: float) -> float:
    s = sorted(values)
    if not s:
        return math.nan
    pos = q * (len(s) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)
