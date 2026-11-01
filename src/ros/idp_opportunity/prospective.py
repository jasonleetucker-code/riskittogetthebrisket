"""Prospective (frozen-parameter) weekly IDP models — SHADOW ONLY.

Preregistration: ``docs/projections/IDP_OPPORTUNITY_PROSPECTIVE_PREREGISTRATION_2026-11-01.md``.

The five in-package models (the sixth, the Sleeper/RotoWire provider champion, is
scored from the immutable pre-kickoff archive by the evaluation runner, never here):

========  =====================================================================
``S0``    properly shrunk baseline: per-key weekly mean shrunk toward the
          true-position group's per-game mean (pseudo-count κ_games).
``SNAP``  snap-weighted opportunity (retrospective M2: shrunk per-snap rates ×
          expected snaps).
``OPP``   SNAP × family-specific opponent opportunity (retrospective M4).
``ROLE``  SNAP with expected snap share moved toward the most recent week by γ
          (:func:`src.ros.idp_opportunity.features.role_change`).  The injury-report
          replacement term (retrospective M3) is DROPPED: it hurt.
``HYB``   ROLE × the OPP opponent factors.
========  =====================================================================

Parameters are FROZEN: :func:`fit_frozen` fits once on weeks before the first
evaluation week, and :func:`predict_week` only applies them.  Nothing refits on an
evaluated week.  Features still read every week < W through the
:class:`~src.ros.idp_opportunity.leakage.AsOfView` guard.  Pure: no I/O, no clock.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from src.ros.idp_opportunity.features import RoleChange, role_change
from src.ros.idp_opportunity.leakage import AsOfView, SeasonData
from src.ros.idp_opportunity.model import (
    ALPHA_GRID,
    KAPPA_GRID,
    KAPPA_OPP_GRID,
    RECENT_WEEKS,
    Card,
    FitRow,
    Params,
    Row,
    _f,
    _group_of,
    build_context,
    build_rows,
    class_factors,
    fit_params,
    key_class,
    opt_float,
    played,
)

__all__ = [
    "GAMMA_GRID",
    "KAPPA_GAMES_GRID",
    "PROSPECTIVE_MODELS",
    "FrozenParams",
    "ProspectiveRow",
    "build_prospective_rows",
    "fit_frozen",
    "predict_week",
    "project_line",
]

PROSPECTIVE_MODELS = ("S0", "SNAP", "OPP", "ROLE", "HYB")
KAPPA_GAMES_GRID = (0.0, 0.5, 1.0, 2.0, 4.0, 8.0)
GAMMA_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)


@dataclass(frozen=True)
class FrozenParams:
    snap: Params
    opp: Params
    kappa_games: float
    gamma: float
    hyb: Params

    def to_dict(self) -> dict[str, Any]:
        return {
            "S0": {"kappaGames": self.kappa_games},
            "SNAP": self.snap.to_dict(),
            "OPP": self.opp.to_dict(),
            "ROLE": {**self.snap.to_dict(), "gamma": self.gamma},
            "HYB": {**self.hyb.to_dict(), "gamma": self.gamma},
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> FrozenParams:
        def _p(x: Mapping[str, Any]) -> Params:
            return Params(
                kappa_vol=float(x["kappaVol"]),
                kappa_splash=float(x["kappaSplash"]),
                kappa_opp=float(x["kappaOpp"]),
                alpha=float(x["alpha"]),
                beta={},
            )

        return cls(
            snap=_p(d["SNAP"]),
            opp=_p(d["OPP"]),
            kappa_games=float(d["S0"]["kappaGames"]),
            gamma=float(d["ROLE"]["gamma"]),
            hyb=_p(d["HYB"]),
        )


@dataclass
class ProspectiveRow:
    base: Row
    n_games: int
    group_per_game: dict[str, float]
    share3: float | None
    team_mean: float | None
    role: RoleChange


def _group_per_game(
    view: AsOfView, ctx_history: Mapping[str, Any], card: Card
) -> dict[str, dict[str, float]]:
    sums: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    games: dict[str, int] = defaultdict(int)
    for pid in sorted(ctx_history):
        _, _, rg = _group_of(view, pid)
        for _, line in ctx_history[pid]:
            games[rg] += 1
            for k in card.idp_keys:
                sums[rg][k] += _f(line, k)
    return {g: {k: sums[g][k] / games[g] for k in card.idp_keys} for g in games if games[g] > 0}


def build_prospective_rows(
    view: AsOfView, card: Card, candidates: Iterable[str]
) -> list[ProspectiveRow]:
    ctx = build_context(view, card)
    gpg = _group_per_game(view, ctx.history, card)
    out: list[ProspectiveRow] = []
    for r in build_rows(view, ctx, card, candidates):
        hist = ctx.history[r.pid]
        _, _, rg = _group_of(view, r.pid)
        tms = [(line, opt_float(line, "tm_def_snp")) for _, line in hist]
        shares = [_f(line, "def_snp") / tm for line, tm in tms[-RECENT_WEEKS:] if tm and tm > 0]
        team = [tm for _, tm in tms if tm and tm > 0]
        out.append(
            ProspectiveRow(
                base=r,
                n_games=len(hist),
                group_per_game=gpg.get(rg, {}),
                share3=sum(shares) / len(shares) if shares else None,
                team_mean=sum(team) / len(team) if team else None,
                role=role_change(view, r.pid),
            )
        )
    return out


def _expected_snaps(pr: ProspectiveRow, model: str, gamma: float) -> float | None:
    es = pr.base.exp_snaps
    if es is None:
        return None
    if model in ("ROLE", "HYB") and pr.role.state == "ok" and pr.team_mean is not None:
        last = pr.role.last_share
        share3 = pr.share3
        if last is not None and share3 is not None:
            return ((1.0 - gamma) * share3 + gamma * last) * pr.team_mean
    return es


def effective(pr: ProspectiveRow, model: str) -> str:
    """Model actually applied; a missing input falls back to ``S0`` (named)."""
    if model in ("SNAP", "OPP", "ROLE", "HYB") and pr.base.exp_snaps is None:
        return "S0"
    return model


def project_line(pr: ProspectiveRow, model: str, fp: FrozenParams, card: Card) -> dict[str, float]:
    """Projected stat line over the card keys; score it with ``card.points``."""
    m = effective(pr, model)
    r = pr.base
    line = {k: r.c0[k] for k in card.other_keys}
    if m == "S0":
        kg = fp.kappa_games
        n = pr.n_games
        for k in card.idp_keys:
            prior = pr.group_per_game.get(k)
            if prior is None:
                line[k] = r.c0[k]  # no group evidence: the raw mean, never 0
            else:
                line[k] = (r.sums[k] + kg * prior) / (n + kg) if (n + kg) > 0 else r.c0[k]
        return line
    p = {"SNAP": fp.snap, "OPP": fp.opp, "ROLE": fp.snap, "HYB": fp.hyb}[m]
    es = _expected_snaps(pr, m, fp.gamma)
    if es is None:  # unreachable: effective() routed it to S0
        raise ValueError(f"{m} needs expected snaps")
    es = max(es, 0.0)
    fac = class_factors(r, "M4" if m in ("OPP", "HYB") else "M2", p)
    for k in card.idp_keys:
        c = key_class(k)
        kap = p.kappa_vol if c == "vol" else p.kappa_splash
        den = r.snp + kap
        rate = (r.sums[k] + kap * r.grate[k]) / den if den > 0 else 0.0
        line[k] = es * rate * fac[c]
    return line


def _linear(line: Mapping[str, float], card: Card) -> float:
    return sum(card.rates.get(k, 0.0) * v for k, v in line.items())


# ── fitting (once, before the first evaluation week) ─────────────────────────


def _fit_rows(data: SeasonData, card: Card, fit_weeks: Sequence[int], outcome_cutoff: int):
    """``(retrospective FitRows, prospective rows with outcomes)`` for ``fit_weeks``;
    outcomes read through the ``outcome_cutoff`` view (all fit weeks < cutoff)."""
    from src.ros.idp_opportunity.evaluate import population  # noqa: PLC0415

    outcome_view = data.view(outcome_cutoff)
    retro: list[FitRow] = []
    pros: list[tuple[ProspectiveRow, float]] = []
    for w in sorted(fit_weeks):
        outcomes = outcome_view.stats_week(w)
        prs = build_prospective_rows(data.view(w), card, population(data, w))
        for pr in prs:
            line = outcomes.get(pr.base.pid) or {}
            y = card.points(line)
            retro.append(FitRow(pr.base, y, opt_float(line, "def_snp")))
            pros.append((pr, y))
    return retro, pros


def _mae(
    pros: Sequence[tuple[ProspectiveRow, float]], model: str, fp: FrozenParams, card: Card
) -> float:
    if not pros:
        return math.inf
    return sum(abs(_linear(project_line(pr, model, fp, card), card) - y) for pr, y in pros) / len(
        pros
    )


def fit_frozen(
    data: SeasonData, card: Card, fit_weeks: Sequence[int]
) -> tuple[FrozenParams, dict[str, Any]]:
    """Fit every prospective parameter on ``fit_weeks`` (all before evaluation)."""
    if not fit_weeks:
        raise ValueError("no fit weeks")
    cutoff = max(fit_weeks) + 1
    for w in fit_weeks:
        if not played_any(data, w):
            raise ValueError(f"fit week {w} has no played rows")
    retro, pros = _fit_rows(data, card, fit_weeks, cutoff)
    retro_params = fit_params(retro)
    snap, opp = retro_params["M2"], retro_params["M4"]
    fp = FrozenParams(snap=snap, opp=opp, kappa_games=KAPPA_GAMES_GRID[0], gamma=0.0, hyb=opp)
    best = (math.inf, fp.kappa_games)
    for kg in KAPPA_GAMES_GRID:
        s = _mae(pros, "S0", replace(fp, kappa_games=kg), card)
        if s < best[0] - 1e-12:
            best = (s, kg)
    fp = replace(fp, kappa_games=best[1])
    best = (math.inf, 0.0)
    for g in GAMMA_GRID:
        s = _mae(pros, "ROLE", replace(fp, gamma=g), card)
        if s < best[0] - 1e-12:
            best = (s, g)
    fp = replace(fp, gamma=best[1])
    best_h = (math.inf, fp.hyb)
    for ko in KAPPA_OPP_GRID:
        for al in ALPHA_GRID:
            cand = replace(snap, kappa_opp=ko, alpha=al)
            s = _mae(pros, "HYB", replace(fp, hyb=cand), card)
            if s < best_h[0] - 1e-12:
                best_h = (s, cand)
    fp = replace(fp, hyb=best_h[1])
    diag = {
        "residualQuantiles80": _residual_quantiles(pros, fp, card),
        "fitWeeks": sorted(fit_weeks),
        "fitRows": len(pros),
        "fitMae": {m: _mae(pros, m, fp, card) for m in PROSPECTIVE_MODELS},
        "grids": {
            "kappaVolSplash": list(KAPPA_GRID),
            "kappaOpp": list(KAPPA_OPP_GRID),
            "alpha": list(ALPHA_GRID),
            "kappaGames": list(KAPPA_GAMES_GRID),
            "gamma": list(GAMMA_GRID),
        },
    }
    return fp, diag


def _residual_quantiles(
    pros: Sequence[tuple[ProspectiveRow, float]], fp: FrozenParams, card: Card, *, min_n: int = 30
) -> dict[str, dict[str, list[float] | None]]:
    """FROZEN per model x family 10th / 90th percentiles of (realized - projection),
    used for 80% interval coverage on evaluated weeks (no refit)."""
    from src.ros.idp_opportunity.model import _quantile  # noqa: PLC0415

    out: dict[str, dict[str, list[float] | None]] = {}
    for m in PROSPECTIVE_MODELS:
        by: dict[str, list[float]] = defaultdict(list)
        for pr, y in pros:
            by[pr.base.family].append(y - _linear(project_line(pr, m, fp, card), card))
        out[m] = {
            f: ([_quantile(v, 0.10), _quantile(v, 0.90)] if len(v) >= min_n else None)
            for f, v in sorted(by.items())
        }
    return out


def played_any(data: SeasonData, week: int) -> bool:
    return any(played(v) for v in data.stats.get(week, {}).values())


# ── prediction (frozen parameters, no refit) ─────────────────────────────────


def predict_week(data: SeasonData, card: Card, fp: FrozenParams, week: int) -> list[dict[str, Any]]:
    """Pre-kickoff forecasts for week ``week``: every IDP player with at least one
    played week before it (who will play is NOT known pre-kickoff)."""
    view = data.view(week)
    candidates = sorted(
        {
            pid
            for w in view.weeks_before()
            for pid, line in view.stats_week(w).items()
            if view.position(pid) is not None and played(line)
        }
    )
    out = []
    for pr in build_prospective_rows(view, card, candidates):
        rec: dict[str, Any] = {
            "pid": pr.base.pid,
            "family": pr.base.family,
            "subgroup": pr.base.subgroup,
            "opponent": pr.base.opponent,
            "reasons": list(pr.base.reasons),
            "roleState": pr.role.state,
            "points": {},
            "effectiveModel": {},
        }
        for m in PROSPECTIVE_MODELS:
            rec["points"][m] = round(card.points(project_line(pr, m, fp, card)), 6)
            rec["effectiveModel"][m] = effective(pr, m)
        out.append(rec)
    return out
