"""The BDVM dynasty engine: season paths → strategy values → outputs.

    DV(i,s) = Σ_t u_s(t) · d_s^t · S_i(t) · SSV_i(t)  −  λ_s · 0.35 · Ψ_i
    TV(i,s) = 10000 · (DV / anchor_s)^γ

Every future-year value decomposes as
current mean × trajectory × ascension × games × survival × scarcity ×
strategy — the Phase-3 gate.  The market is NOT an input anywhere in
this module; the market layer (``market.py``) runs strictly afterward.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping

from src.bdvm.curves import aging_mult, ascension_mult, draft_capital_decay, effective_age
from src.bdvm.league_config import BdvmLeagueConfig
from src.bdvm.params import ParamSet
from src.bdvm.pool import PoolFn
from src.bdvm.replacement import ReplacementEngine
from src.bdvm.surplus import norm_cdf, probability_above, season_starter_value
from src.bdvm.survival import RiskProfile, hazard
from src.bdvm.uncertainty import sigma_fpg

# Quantile z-scores for the floor/ceiling outputs.
_Z_P20 = -0.8416212335729143
_Z_P85 = 1.0364333894937898


@dataclass(frozen=True)
class PlayerInput:
    """Everything the fundamental engine may read about one player.

    NO market fields here, by construction — fundamental value must be
    computable with market tables unavailable (Phase-5 gate).
    """

    player_id: str
    name: str
    position: str  # true position if known, else platform group
    age: float
    nfl_season: int  # 1 = rookie year
    fpg: float  # blended projected FPG (league scoring)
    games: float = 17.0
    sigma_source: float = 0.0
    archetype: str | None = None  # "dual"/"pocket", "box"/"deep", ...
    dual_blend: float | None = None  # continuous QB pocket/dual weight
    career_load: float = 0.0
    kappa: float = 0.0
    risk: RiskProfile = field(default_factory=RiskProfile)
    true_position_known: bool = True
    n_sources: int = 1
    any_proxy: bool = False
    stale_source_count: int = 0
    # Structured-event hooks (src/bdvm/events.py).  Defaults are inert.
    event_sigma_mult: float = 1.0
    event_hazard_mult: float = 1.0


@dataclass(frozen=True)
class Valuation:
    player_id: str
    name: str
    position: str
    group: str
    raw: dict[str, Any]
    seasons: list[dict[str, float]]  # balanced-horizon path (career chart)
    fundamental: dict[str, float]  # strategy -> raw discounted value
    trade_value: dict[str, float]  # strategy -> 0-10000
    probs: dict[str, float]
    explain: dict[str, float]
    range_: dict[str, float]  # floor/median/ceiling + confidence + volatility
    quality: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "playerId": self.player_id,
            "name": self.name,
            "position": self.position,
            "group": self.group,
            "raw": self.raw,
            "path": self.seasons,
            "fundamental": self.fundamental,
            "tradeValue": self.trade_value,
            "probs": self.probs,
            "explain": self.explain,
            "range": self.range_,
            "quality": self.quality,
        }


def _under_ceiling(
    value: float, ceiling: float, *, knee_fraction: float = 0.99, decay_scale: float = 3000.0
) -> float:
    """Bring ``value`` under ``ceiling`` without collapsing distinct inputs.

    Identity below ``knee = ceiling * knee_fraction``; above it, a
    strictly increasing map asymptotic to ``ceiling`` from below:

        v <= knee  ->  v
        v >  knee  ->  ceiling - span * exp(-(v - knee) / decay_scale)

    with ``span = ceiling - knee``.  Continuous at the knee and nothing
    below it moves at all, so the board — pinned by ``calibrate`` at
    ``target_top_value`` (9800), under the 9900 knee — is untouched.

    ``decay_scale`` is deliberately NOT ``span``.  Tying them makes the
    map C1 at the knee, which is tidier, but the exponential then decays
    so fast that it underflows float64 a few hundred points above the
    cap — and this band's inputs run to ~22k against a 10k ceiling, so
    the whole top would flatten onto one value again, reintroducing the
    tie this function exists to prevent.  A wider decay keeps every
    reachable input distinct at the cost of a slope kink at the knee,
    which is invisible: the kink sits above every board value.

    The result is held one representable step under ``ceiling`` so the
    bound is strict even for absurd inputs.

    See ``src/api/data_contract.py::_te_lift_under_ceiling`` — same
    construction, same reason (math audit finding C4): a hard clamp is
    not injective, so it turns a resolution problem into a tie.  That
    one can afford ``decay_scale == span`` because its inputs are
    bounded at ~1.21x its ceiling rather than ~2.2x.
    """
    v = float(value)
    cap = float(ceiling)
    if cap <= 0:
        return v
    knee = cap * knee_fraction
    if v <= knee:
        return v
    span = cap - knee
    if span <= 0:
        return min(v, cap)
    scale = decay_scale if decay_scale > 0 else span
    return min(cap - span * math.exp(-(v - knee) / scale), cap - 1e-9)


class DynastyEngine:
    def __init__(
        self,
        cfg: BdvmLeagueConfig,
        repl: ReplacementEngine,
        params: ParamSet,
        *,
        pools: Mapping[str, PoolFn] | None = None,
        surplus_mode: str = "option",
        anchors: Mapping[str, float] | None = None,
    ):
        self.cfg = cfg
        self.repl = repl
        self.params = params
        self.pools = dict(pools or {})
        self.surplus_mode = surplus_mode
        names = params.strategy_names()
        self.anchors: dict[str, float] = dict(anchors) if anchors else {k: 1.0 for k in names}
        self._gamma = float(params["scale"]["stud_gamma"])
        self._value_max = float(params["scale"]["trade_value_max"])
        self._lambda_disp = float(params["risk_lambda_dispersion_coeff"])

    # ------------------------------------------------------------------
    def modelling_position(self, p: PlayerInput) -> str:
        return self.params.modelling_position(p.position)

    def group_for(self, p: PlayerInput) -> str:
        return self.cfg.group(p.position)

    def _load_rate(self, pos: str) -> float:
        rates = self.params["annual_load_rate"]
        return float(rates.get(pos, rates["default"]))

    # ------------------------------------------------------------------
    def season_path(
        self, p: PlayerInput, horizon: int, *, mu_shift_z: float = 0.0
    ) -> list[dict[str, float]]:
        """Season-by-season expected path.

        ``mu_shift_z`` shifts each season's realized outcome by z·σ(t)
        for quantile (floor/ceiling) paths; 0 gives the expected path.
        """
        pos = self.modelling_position(p)
        group = self.group_for(p)
        R = self.repl.R(group)
        games_cfg = self.params["games"]

        a0_eff = effective_age(self.params, pos, p.age, p.career_load)
        A0 = aging_mult(self.params, pos, a0_eff, p.archetype, dual_blend=p.dual_blend)
        dc_decay = draft_capital_decay(self.params, p.nfl_season)
        load_rate = self._load_rate(pos)

        rows: list[dict[str, float]] = []
        s_survive = 1.0
        for t in range(0, horizon + 1):
            age_t = p.age + t
            a_eff = effective_age(self.params, pos, age_t, p.career_load + t * load_rate)
            A = aging_mult(self.params, pos, a_eff, p.archetype, dual_blend=p.dual_blend)
            mu = p.fpg * (A / A0) * ascension_mult(self.params, p.kappa, t)
            sigma = (
                sigma_fpg(
                    self.params,
                    pos,
                    max(mu, 0.1),
                    p.risk,
                    p.sigma_source,
                    t,
                    true_position_known=p.true_position_known,
                )
                * p.event_sigma_mult
            )
            games = (
                p.games
                if t == 0
                else float(games_cfg["season_length"])
                * (
                    float(games_cfg["future_games_base"])
                    + float(games_cfg["future_games_durability_coeff"]) * p.risk.durability
                )
            )
            # Quantile paths shift the season's MEAN by z·σ and then price
            # the same surplus functional the expected path uses.  They used
            # to switch to truncated surplus (max(0, µ_z − R)·G) on the
            # reading that a quantile outcome is "pinned", but that made the
            # band a different quantity from the median it brackets:
            # E[max(0, X−R)] ≥ max(0, E[X]−R) by Jensen, so a high-σ player
            # near replacement got a p85 CEILING below his median — measured
            # floor 0 / median 41 / ceiling 0 (audit H6).  Sharing the
            # functional makes the band monotone by construction: σ, games
            # and survival do not depend on z, so ssv is non-decreasing in
            # µ_eval, the discounted sum has non-negative weights, Ψ is
            # identical across the three paths, and to_trade_value is
            # monotone — floor ≤ median ≤ ceiling falls out, it is not
            # clamped in afterwards.
            mu_eval = mu + mu_shift_z * sigma
            ssv = season_starter_value(mu_eval, sigma, R, games, mode=self.surplus_mode)
            if t > 0:
                h = hazard(self.params, pos, age_t, p.risk, dc_decay)
                if p.event_hazard_mult != 1.0:
                    clip = self.params["hazard_adjusters"]
                    h = max(
                        float(clip["clip_lo"]), min(float(clip["clip_hi"]), h * p.event_hazard_mult)
                    )
                s_survive *= 1.0 - h
            rows.append(
                {
                    "t": t,
                    "age": age_t,
                    "age_eff": a_eff,
                    "mu": mu,
                    "sigma": sigma,
                    "games": games,
                    "R": R,
                    "ssv": ssv,
                    "survival": s_survive,
                    "expected": ssv * s_survive,
                }
            )
        return rows

    # ------------------------------------------------------------------
    def _discounted_value(
        self, rows: list[dict[str, float]], strategy: Mapping[str, Any]
    ) -> tuple[float, float]:
        """(risk-adjusted DV, path dispersion Ψ) for one strategy."""
        usability = list(strategy["usability"])
        discount = float(strategy["discount"])
        lam = float(strategy["risk_lambda"])
        v = 0.0
        for r in rows:
            t = int(r["t"])
            u = usability[min(t, len(usability) - 1)]
            v += u * (discount**t) * r["expected"]
        disp = math.sqrt(
            sum(
                ((discount ** int(r["t"])) * r["sigma"] * r["games"] * r["survival"]) ** 2
                for r in rows
            )
        )
        return max(0.0, v - lam * self._lambda_disp * disp), disp

    def fundamental_values(self, p: PlayerInput) -> dict[str, float]:
        out: dict[str, float] = {}
        for name in self.params.strategy_names():
            st = self.params.strategy(name)
            rows = self.season_path(p, int(st["horizon"]))
            out[name], _ = self._discounted_value(rows, st)
        return out

    def calibrate(self, players: list[PlayerInput]) -> None:
        """Anchor each strategy so the top asset scores ``target_top_value``."""
        target = float(self.params["scale"]["target_top_value"])
        maxima = {k: 1e-9 for k in self.params.strategy_names()}
        for p in players:
            for k, v in self.fundamental_values(p).items():
                maxima[k] = max(maxima[k], v)
        self.anchors = {
            k: m / ((target / 10000.0) ** (1.0 / self._gamma)) for k, m in maxima.items()
        }

    def to_trade_value(self, v: float, strategy: str) -> float:
        """DV → the bounded 0-``trade_value_max`` display scale.

        The cap is enforced HERE, on the transform, rather than on any
        one output: every number the engine puts on the 0-10000 scale —
        the per-strategy trade values AND the floor/median/ceiling band —
        leaves through this function, so this is the only place that
        makes ``scale.trade_value_max`` mean anything (before this it had
        exactly one reference in the repo: its own declaration).

        Capping the transform is deliberately NOT the same as capping the
        display: ``calibrate`` solves the anchors on raw DV and never
        calls this function, so the cap bounds outputs without touching
        the calibration target.  ``target_top_value`` (9800) sits below
        the cap by design, so the per-strategy board values are
        uncapped-in-practice; what the bound actually acts on is the
        floor/median/ceiling band, whose p85 path measured near 20k.

        The bound is a strictly increasing squash, NOT ``min(cap, x)``.
        A hard clamp is not injective, and that matters here precisely
        because the band is where it binds: on an elite-heavy ladder a
        plain clamp collapsed seven distinct ceilings — spanning an
        ~1.8x range on the uncapped scale — onto exactly 10000.0, which
        ``frontend/lib/bdvm.js`` then renders as a tie. Losing the
        ordering of the top of the board to enforce its bound trades one
        defect for another.

        Same shape and same reasoning as
        ``src/api/data_contract.py::_te_lift_under_ceiling`` (math audit
        finding C4), which exists for exactly this: identity below the
        knee, asymptotic to the cap above it, never reaching it, so
        distinct inputs stay distinct.
        """
        anchor = self.anchors.get(strategy, 1.0)
        raw = 10000.0 * ((max(0.0, v) / anchor) ** self._gamma)
        return _under_ceiling(raw, ceiling=self._value_max)

    # ------------------------------------------------------------------
    def value(self, p: PlayerInput) -> Valuation:
        pos = self.modelling_position(p)
        group = self.group_for(p)
        fundamental: dict[str, float] = {}
        balanced_rows: list[dict[str, float]] | None = None
        dispersion = 0.0
        for name in self.params.strategy_names():
            st = self.params.strategy(name)
            rows = self.season_path(p, int(st["horizon"]))
            if name == "balanced":
                balanced_rows = rows
            fundamental[name], disp = self._discounted_value(rows, st)
            if name == "balanced":
                dispersion = disp
        if balanced_rows is None:  # params without a balanced profile
            balanced_rows = self.season_path(p, 6)

        trade_value = {k: self.to_trade_value(v, k) for k, v in fundamental.items()}
        R = balanced_rows[0]["R"]
        probs = self._probabilities(p, balanced_rows, R, group)
        explain = self._explain(balanced_rows)
        range_ = self._range(p, fundamental, dispersion)
        quality = self._quality(p)

        return Valuation(
            player_id=p.player_id,
            name=p.name,
            position=p.position,
            group=group,
            raw={
                "fpg": p.fpg,
                "replacement": R,
                "vorg": p.fpg - R,
                "age": p.age,
                "age_eff": balanced_rows[0]["age_eff"],
                "modellingPosition": pos,
            },
            seasons=balanced_rows,
            fundamental=fundamental,
            trade_value=trade_value,
            probs=probs,
            explain=explain,
            range_=range_,
            quality=quality,
        )

    # ------------------------------------------------------------------
    def _probabilities(
        self, p: PlayerInput, rows: list[dict[str, float]], R: float, group: str
    ) -> dict[str, float]:
        pcfg = self.params["probabilities"]
        r0 = rows[0]
        p_above = probability_above(r0["mu"], r0["sigma"], R)
        pool = self.pools.get(group)
        if pool is not None:
            elite_line = pool(max(1, self.cfg.teams // int(pcfg["elite_pool_rank_divisor"])))
        else:
            elite_line = R + float(pcfg["elite_fallback_mult"]) * max(
                1.0, float(pcfg["elite_fallback_floor_frac"]) * R
            )
        p_elite = 1.0 - norm_cdf((elite_line - r0["mu"]) / r0["sigma"])
        idx3 = min(3, len(rows) - 1)
        r3 = rows[idx3]
        p_start3 = r3["survival"] * norm_cdf((r3["mu"] - R) / r3["sigma"])
        r1 = rows[min(1, len(rows) - 1)]
        p_start1 = r1["survival"] * norm_cdf((r1["mu"] - R) / r1["sigma"])
        p_collapse = 1.0 - p_start1
        breakout_mult = float(pcfg["breakout_mult"])
        p_break = 1.0 - norm_cdf((breakout_mult * r0["mu"] - r1["mu"]) / r1["sigma"])
        return {
            "p_above_replacement": p_above,
            "p_elite_season": p_elite,
            "p_starter_in_1y": p_start1,
            "p_starter_in_3y": p_start3,
            "p_bust_year1": 1.0 - p_above,
            "p_value_collapse_1y": p_collapse,
            "p_breakout": p_break,
        }

    def _explain(self, rows: list[dict[str, float]]) -> dict[str, float]:
        st = self.params.strategy("balanced")
        usability = list(st["usability"])
        discount = float(st["discount"])
        contrib = [
            usability[min(int(r["t"]), len(usability) - 1)]
            * (discount ** int(r["t"]))
            * r["expected"]
            for r in rows
        ]
        s = sum(contrib) or 1.0
        return {
            "year_0_share": contrib[0] / s,
            "years_1_2_share": sum(contrib[1:3]) / s,
            "years_3_plus_share": sum(contrib[3:]) / s,
            "survival_drag": 1.0
            - (sum(r["expected"] for r in rows) / max(1e-9, sum(r["ssv"] for r in rows))),
            "traj_5y": (rows[min(5, len(rows) - 1)]["mu"] / max(1e-9, rows[0]["mu"])) - 1.0,
            "scarcity_leverage": rows[0]["R"],
        }

    def _range(
        self, p: PlayerInput, fundamental: dict[str, float], dispersion: float
    ) -> dict[str, float]:
        """Floor/median/ceiling on the trade-value scale.

        Approximation (documented): quantile paths shift every season's
        mean by the same z — i.e. perfectly correlated seasons — which
        widens the band vs. independent draws.  Honest until the Phase-10
        simulation replaces it.  (Ψ, the dispersion the risk penalty in
        ``_discounted_value`` reads, assumes the opposite — independent
        seasons.  The two risk representations do not agree; see the
        "known divergences" section of the BDVM implementation report.)

        The ordering floor ≤ median ≤ ceiling holds by construction —
        see the monotonicity argument in ``season_path`` — and is pinned
        by ``tests/bdvm/test_dynasty_math.py``.
        """
        st = self.params.strategy("balanced")
        horizon = int(st["horizon"])
        floor_rows = self.season_path(p, horizon, mu_shift_z=_Z_P20)
        ceil_rows = self.season_path(p, horizon, mu_shift_z=_Z_P85)
        dv_floor, _ = self._discounted_value(floor_rows, st)
        dv_ceil, _ = self._discounted_value(ceil_rows, st)
        median_tv = self.to_trade_value(fundamental.get("balanced", 0.0), "balanced")
        vol = dispersion / max(1e-9, fundamental.get("balanced", 0.0) + dispersion)
        return {
            "floor_p20": self.to_trade_value(dv_floor, "balanced"),
            "median": median_tv,
            "ceiling_p85": self.to_trade_value(dv_ceil, "balanced"),
            "volatility": min(1.0, vol),
        }

    def _quality(self, p: PlayerInput) -> dict[str, Any]:
        """Confidence POLICY (§12.3): coarse labels until calibration exists."""
        score = 1.0
        reasons: list[str] = []
        if p.any_proxy:
            score -= 0.35
            reasons.append("proxy_projection")
        if p.n_sources <= 1:
            score -= 0.25
            reasons.append("single_projection_source")
        if not p.true_position_known:
            score -= 0.15
            reasons.append("true_position_unknown")
        if p.stale_source_count:
            score -= 0.10
            reasons.append("stale_projection_sources")
        if p.risk.small_sample >= 0.5:
            score -= 0.10
            reasons.append("small_nfl_sample")
        score = max(0.0, min(1.0, score))
        label = "high" if score >= 0.75 else ("medium" if score >= 0.45 else "low")
        return {
            "confidenceScore": round(score, 3),
            "confidenceLabel": label,
            "provisional": True,  # priors not yet backtested — always true in v1
            "reasons": reasons,
        }
