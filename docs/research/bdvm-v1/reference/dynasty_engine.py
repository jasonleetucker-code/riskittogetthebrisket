"""
dynasty_engine.py — Reference implementation of the Brisket Dynasty Valuation Model (v1.0)

Design goals:
  * Glass-box: every number is traceable to a named parameter.
  * Projection-source agnostic: swap the projection file, keep the model.
  * League-format agnostic: scoring, lineup slots and replacement levels are config.
  * Offense and IDP are the same code path; only parameters differ.

No third-party dependencies (stdlib only) so it can run anywhere, including the VPS.

ALL PARAMETERS BELOW ARE STARTING PRIORS. They are informed by published research
but are NOT backtested truth. Treat params.py as the thing you tune, not the code.
"""

from __future__ import annotations
import math
import json
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

SQRT2 = math.sqrt(2.0)
SQRT2PI = math.sqrt(2.0 * math.pi)


def _phi(z: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * z * z) / SQRT2PI


def _Phi(z: float) -> float:
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(z / SQRT2))


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


# ---------------------------------------------------------------------------
# 1. LEAGUE CONFIGURATION
# ---------------------------------------------------------------------------

POSITIONS = ["QB", "RB", "WR", "TE", "DT", "EDGE", "LB", "CB", "S"]

# Fantasy-slot groups. Real position -> lineup group. Configurable for leagues
# that collapse DT/EDGE into "DL" or CB/S into "DB".
DEFAULT_POS_GROUPS = {
    "QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE",
    "DT": "DL", "EDGE": "DL", "LB": "LB", "CB": "DB", "S": "DB",
}


@dataclass
class ScoringConfig:
    # offense
    pass_yd: float = 0.04
    pass_td: float = 4.0
    interception: float = -2.0
    rush_yd: float = 0.1
    rush_td: float = 6.0
    rec: float = 1.0                    # PPR
    rec_te_bonus: float = 0.5           # TE premium (additional per reception)
    rec_yd: float = 0.1
    rec_td: float = 6.0
    fumble_lost: float = -2.0
    first_down: float = 0.0
    # IDP
    tackle_solo: float = 1.5
    tackle_assist: float = 0.75
    sack: float = 4.0
    tfl: float = 1.0
    qb_hit: float = 0.5
    pass_defended: float = 1.5
    interception_def: float = 4.0
    forced_fumble: float = 3.0
    fumble_recovery: float = 2.0
    def_td: float = 6.0
    safety: float = 2.0


@dataclass
class LeagueConfig:
    teams: int = 12
    # starting lineup: fixed slots by group
    starters: Dict[str, int] = field(default_factory=lambda: {
        "QB": 1, "RB": 2, "WR": 3, "TE": 1, "DL": 2, "LB": 3, "DB": 3
    })
    # flex slots: name -> (count_per_team, eligible groups)
    flex: Dict[str, Tuple[int, List[str]]] = field(default_factory=lambda: {
        "FLEX": (1, ["RB", "WR", "TE"]),
        "SUPERFLEX": (1, ["QB", "RB", "WR", "TE"]),
        "IDP_FLEX": (1, ["DL", "LB", "DB"]),
    })
    # waiver buffer: how many extra players per team beyond starters are rostered
    # AND startable-quality at that group. Drives replacement level.
    waiver_buffer: Dict[str, float] = field(default_factory=lambda: {
        "QB": 0.85, "RB": 0.75, "WR": 1.00, "TE": 0.40,
        "DL": 0.50, "LB": 0.50, "DB": 0.50
    })
    roster_size: int = 35
    taxi_size: int = 5
    best_ball: bool = False
    pos_groups: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_POS_GROUPS))
    scoring: ScoringConfig = field(default_factory=ScoringConfig)

    def group(self, pos: str) -> str:
        return self.pos_groups[pos]

    @property
    def superflex(self) -> bool:
        return any("QB" in elig for _, elig in self.flex.values())


# ---------------------------------------------------------------------------
# 2. SCORING ENGINE — raw projected stats -> fantasy points
# ---------------------------------------------------------------------------

def score_stats(stats: Dict[str, float], pos: str, sc: ScoringConfig) -> float:
    """Convert a raw projected stat line into fantasy points for this league."""
    p = 0.0
    p += stats.get("pass_yd", 0) * sc.pass_yd
    p += stats.get("pass_td", 0) * sc.pass_td
    p += stats.get("int", 0) * sc.interception
    p += stats.get("rush_yd", 0) * sc.rush_yd
    p += stats.get("rush_td", 0) * sc.rush_td
    rec = stats.get("rec", 0)
    p += rec * sc.rec
    if pos == "TE":
        p += rec * sc.rec_te_bonus
    p += stats.get("rec_yd", 0) * sc.rec_yd
    p += stats.get("rec_td", 0) * sc.rec_td
    p += stats.get("fum_lost", 0) * sc.fumble_lost
    p += stats.get("first_down", 0) * sc.first_down
    # IDP
    p += stats.get("tkl_solo", 0) * sc.tackle_solo
    p += stats.get("tkl_ast", 0) * sc.tackle_assist
    p += stats.get("sack", 0) * sc.sack
    p += stats.get("tfl", 0) * sc.tfl
    p += stats.get("qb_hit", 0) * sc.qb_hit
    p += stats.get("pd", 0) * sc.pass_defended
    p += stats.get("int_def", 0) * sc.interception_def
    p += stats.get("ff", 0) * sc.forced_fumble
    p += stats.get("fr", 0) * sc.fumble_recovery
    p += stats.get("def_td", 0) * sc.def_td
    p += stats.get("safety", 0) * sc.safety
    return p


# ---------------------------------------------------------------------------
# 3. PROJECTION BLENDING
# ---------------------------------------------------------------------------

@dataclass
class ProjectionSource:
    name: str
    fpg: float                         # projected fantasy points per game (league scoring)
    games: float = 16.0
    weight: float = 1.0                # from historical MAE-based accuracy, per position


def blend_projections(sources: List[ProjectionSource],
                      trim_frac: float = 0.10) -> Tuple[float, float, float]:
    """
    Weighted trimmed mean of per-game projections.
    Returns (mu_fpg, sigma_source, games).

    sigma_source = weighted SD across sources = the *disagreement* component of
    projection uncertainty. It is NOT the full outcome distribution.
    """
    if not sources:
        raise ValueError("no projection sources")
    if len(sources) >= 5 and trim_frac > 0:
        s = sorted(sources, key=lambda x: x.fpg)
        k = max(1, int(len(s) * trim_frac))
        s = s[k:-k] if len(s) - 2 * k >= 3 else s
    else:
        s = list(sources)
    W = sum(x.weight for x in s)
    mu = sum(x.fpg * x.weight for x in s) / W
    games = sum(x.games * x.weight for x in s) / W
    var = sum(x.weight * (x.fpg - mu) ** 2 for x in s) / W
    return mu, math.sqrt(var), games


# ---------------------------------------------------------------------------
# 4. REPLACEMENT-LEVEL ENGINE
# ---------------------------------------------------------------------------

class ReplacementEngine:
    """
    Dynamic replacement level driven by lineup requirements, flex eligibility,
    league size and waiver depth.

    pool: group -> callable(rank:int) -> projected FPG at that positional rank.
    In production this is the sorted projection list. Here it can also be a
    synthetic decay curve for demos.
    """

    def __init__(self, cfg: LeagueConfig, pool: Dict[str, callable]):
        self.cfg = cfg
        self.pool = pool
        self.counts: Dict[str, int] = {}
        self.replacement: Dict[str, float] = {}
        self._solve()

    def _solve(self):
        cfg = self.cfg
        groups = list(cfg.starters.keys())
        counts = {g: cfg.teams * cfg.starters.get(g, 0) for g in groups}

        # Greedy flex allocation: each flex slot goes to whichever eligible group
        # currently offers the best next-available player.
        for _slot, (n_per_team, elig) in cfg.flex.items():
            for _ in range(n_per_team * cfg.teams):
                best_g, best_v = None, -1e9
                for g in elig:
                    if g not in self.pool:
                        continue
                    v = self.pool[g](counts.get(g, 0) + 1)
                    if v > best_v:
                        best_g, best_v = g, v
                if best_g:
                    counts[best_g] = counts.get(best_g, 0) + 1

        # Waiver buffer -> the true replacement rank
        for g in counts:
            buf = int(round(cfg.teams * cfg.waiver_buffer.get(g, 0.5)))
            rank = counts[g] + buf
            self.counts[g] = counts[g]
            self.replacement[g] = self.pool[g](rank) if g in self.pool else 0.0

    def R(self, group: str) -> float:
        return self.replacement.get(group, 0.0)


def synthetic_pool(top_fpg: float, decay: float):
    """Exponential rank-decay curve used for demos until real projections land."""
    return lambda rank: top_fpg * math.exp(-decay * max(0, rank - 1))


# ---------------------------------------------------------------------------
# 5. AGING / TRAJECTORY ENGINE
# ---------------------------------------------------------------------------

# (peak_age, curvature_before_peak, curvature_after_peak)
AGE_CURVES: Dict[str, Tuple[float, float, float]] = {
    "QB_pocket": (30.0, 0.006, 0.010),
    "QB_dual":   (26.0, 0.010, 0.028),
    "RB":        (25.0, 0.012, 0.030),
    "WR":        (27.0, 0.014, 0.024),
    "TE":        (27.5, 0.030, 0.018),
    "DT":        (27.5, 0.016, 0.020),
    "EDGE":      (27.0, 0.014, 0.022),
    "LB":        (26.5, 0.012, 0.030),
    "CB":        (26.0, 0.010, 0.030),
    "S":         (27.0, 0.012, 0.026),
}

# career-load mileage: (reference_load, load_per_effective_year, cap_years)
MILEAGE = {
    "RB":   ("touches", 750.0, 500.0, 2.5),
    "WR":   ("targets", 500.0, 450.0, 1.5),
    "TE":   ("targets", 400.0, 450.0, 1.5),
    "QB":   ("dropbacks", 2000.0, 2500.0, 1.0),
    "LB":   ("snaps", 3000.0, 2200.0, 1.5),
    "EDGE": ("snaps", 3000.0, 2400.0, 1.5),
    "DT":   ("snaps", 3000.0, 2400.0, 1.0),
    "CB":   ("snaps", 3000.0, 2400.0, 1.5),
    "S":    ("snaps", 3000.0, 2400.0, 1.5),
}


def curve_key(pos: str, archetype: Optional[str]) -> str:
    if pos == "QB":
        return "QB_dual" if archetype == "dual" else "QB_pocket"
    return pos


def aging_mult(pos: str, age: float, archetype: Optional[str] = None) -> float:
    """Multiplicative production factor, conditional on the player still playing."""
    peak, c_up, c_dn = AGE_CURVES[curve_key(pos, archetype)]
    if age <= peak:
        return math.exp(-c_up * (peak - age) ** 2)
    return math.exp(-c_dn * (age - peak) ** 2)


def effective_age(pos: str, age: float, career_load: float) -> float:
    """Chronological age + mileage penalty (applied only on the decline side)."""
    if pos not in MILEAGE:
        return age
    _unit, ref, per_year, cap = MILEAGE[pos]
    extra = _clamp((career_load - ref) / per_year, 0.0, cap)
    return age + extra


def ascension_mult(kappa: float, t: int, tau: float = 1.5) -> float:
    """Role growth for ascending young players. Saturating, bounded by kappa."""
    if kappa <= 0 or t <= 0:
        return 1.0
    return 1.0 + kappa * (1.0 - math.exp(-t / tau))


# ---------------------------------------------------------------------------
# 6. SURVIVAL / LONGEVITY ENGINE
# ---------------------------------------------------------------------------

# Base annual hazard of losing fantasy-startable status, by position and age band.
BASE_HAZARD = {
    "QB":   [(24, 0.16), (27, 0.10), (30, 0.09), (33, 0.14), (36, 0.24), (99, 0.38)],
    "RB":   [(24, 0.11), (26, 0.15), (27, 0.22), (28, 0.30), (29, 0.38), (99, 0.50)],
    "WR":   [(24, 0.13), (27, 0.09), (29, 0.13), (31, 0.22), (33, 0.34), (99, 0.46)],
    "TE":   [(24, 0.16), (27, 0.10), (30, 0.12), (32, 0.20), (34, 0.32), (99, 0.44)],
    "DT":   [(24, 0.14), (27, 0.10), (30, 0.14), (32, 0.24), (99, 0.38)],
    "EDGE": [(24, 0.14), (27, 0.10), (30, 0.15), (32, 0.26), (99, 0.40)],
    "LB":   [(24, 0.15), (27, 0.12), (29, 0.18), (31, 0.28), (99, 0.42)],
    "CB":   [(24, 0.18), (27, 0.15), (29, 0.22), (31, 0.32), (99, 0.46)],
    "S":    [(24, 0.16), (27, 0.13), (29, 0.19), (31, 0.29), (99, 0.44)],
}


def base_hazard(pos: str, age: float) -> float:
    for cutoff, h in BASE_HAZARD[pos]:
        if age < cutoff:
            return h
    return 0.5


@dataclass
class RiskProfile:
    """All 0-1 scores. Higher = better/safer unless noted."""
    role_security: float = 0.6         # snap/route/target-share lock on the job
    draft_capital: float = 0.5         # 1.0 = top-10 pick, 0.0 = UDFA
    contract_security: float = 0.6     # years remaining x guarantees
    durability: float = 0.6            # inverse of injury burden
    production_z: float = 0.0          # z-score of current VOR vs position
    scheme_stability: float = 0.6
    role_uncertainty: float = 0.25     # 0 = role fully known, 1 = total unknown (RISK: higher=worse)
    event_volatility: float = 0.30     # dependence on TDs/sacks/INTs (RISK: higher=worse)
    small_sample: float = 0.0          # 1.0 = no NFL sample at all (RISK: higher=worse)
    designation_risk: float = 0.0      # IDP position-eligibility change risk (higher=worse)


def hazard(pos: str, age: float, rp: RiskProfile, dc_decay: float) -> float:
    """Annual hazard, base rate adjusted by role/contract/durability/production."""
    h = base_hazard(pos, age)
    adj = 1.0
    adj *= (1.0 + 0.55 * (0.6 - rp.role_security))
    adj *= (1.0 + 0.30 * dc_decay * (0.5 - rp.draft_capital))
    adj *= (1.0 + 0.25 * (0.6 - rp.contract_security))
    adj *= (1.0 + 0.35 * (0.6 - rp.durability))
    adj *= (1.0 - 0.18 * _clamp(rp.production_z, -2.0, 2.0))
    adj *= (1.0 + 0.20 * rp.designation_risk)
    return _clamp(h * adj, 0.02, 0.85)


# ---------------------------------------------------------------------------
# 7. UNCERTAINTY MODEL
# ---------------------------------------------------------------------------

# Baseline coefficient of variation of a player's SEASONAL PPG outcome
# (not week-to-week noise), and per-year drift volatility for future seasons.
CV_BASE = {"QB": 0.26, "RB": 0.36, "WR": 0.34, "TE": 0.36,
           "DT": 0.32, "EDGE": 0.34, "LB": 0.26, "CB": 0.40, "S": 0.30}
DRIFT_VOL = {"QB": 0.16, "RB": 0.30, "WR": 0.22, "TE": 0.22,
             "DT": 0.20, "EDGE": 0.22, "LB": 0.22, "CB": 0.30, "S": 0.24}


def sigma_fpg(pos: str, mu: float, rp: RiskProfile, sigma_source: float, t: int) -> float:
    """Dispersion of a player's realised seasonal PPG, t years from now."""
    cv = CV_BASE[pos]
    cv *= (1.0 + 0.90 * rp.role_uncertainty)
    cv *= (1.0 + 0.45 * rp.event_volatility)
    cv *= (1.0 + 0.60 * rp.small_sample)
    s0 = math.sqrt((cv * mu) ** 2 + sigma_source ** 2)
    drift = DRIFT_VOL[pos] * mu * math.sqrt(max(0, t))
    return math.sqrt(s0 ** 2 + drift ** 2)


# ---------------------------------------------------------------------------
# 8. SEASON VALUE — expected starter surplus (option-value formulation)
# ---------------------------------------------------------------------------

def season_starter_value(mu: float, sigma: float, R: float, games: float) -> float:
    """
    E[ max(0, FPG - R) ] * games, under FPG ~ Normal(mu, sigma).

    Why max(0, .): you are never forced to start a below-replacement player, so
    downside is truncated. This is what gives an uncertain, low-projected young
    player real dynasty value without hand-tuned "upside bonuses", and what makes
    a 250-point projection with a narrow range differ from a wide one.
    """
    if sigma <= 1e-9:
        return max(0.0, mu - R) * games
    z = (mu - R) / sigma
    return ((mu - R) * _Phi(z) + sigma * _phi(z)) * games


# ---------------------------------------------------------------------------
# 9. STRATEGY PROFILES
# ---------------------------------------------------------------------------

@dataclass
class Strategy:
    name: str
    discount: float                  # per-year discount factor
    horizon: int                     # seasons modelled beyond the current one
    usability: List[float]           # weight on each future season's points to THIS roster
    risk_lambda: float               # >0 risk averse, <0 risk seeking


STRATEGIES = {
    "contender": Strategy("contender", 0.72, 4, [1.00, 0.95, 0.80, 0.65, 0.55], 0.20),
    "balanced":  Strategy("balanced", 0.85, 6, [1.00, 1.00, 1.00, 0.95, 0.90, 0.85, 0.80], 0.10),
    "rebuilder": Strategy("rebuilder", 0.93, 8, [0.45, 0.75, 1.00, 1.00, 1.00, 0.95, 0.90, 0.85, 0.80], -0.10),
}


# ---------------------------------------------------------------------------
# 10. PLAYER + CORE VALUATION
# ---------------------------------------------------------------------------

@dataclass
class Player:
    player_id: str
    name: str
    pos: str
    age: float
    nfl_season: int                             # 1 = rookie year
    fpg: float                                  # blended projected FPG, this season
    games: float = 16.0
    sigma_source: float = 0.0
    archetype: Optional[str] = None             # "dual"/"pocket" QB; "box"/"deep" S; "slot"/"boundary" CB
    career_load: float = 0.0                    # touches / targets / snaps per MILEAGE
    kappa: float = 0.0                          # ascension coefficient (role growth ahead)
    risk: RiskProfile = field(default_factory=RiskProfile)
    market_value: Optional[float] = None        # 0-10000 external market value
    market_dispersion: float = 0.20             # expert/market disagreement, 0-1


@dataclass
class Valuation:
    player_id: str
    name: str
    pos: str
    raw: Dict[str, float]
    seasons: List[Dict[str, float]]
    fundamental: Dict[str, float]               # strategy -> raw discounted value
    trade_value: Dict[str, float]               # strategy -> 0-10000
    blended_value: Optional[float]
    market_gap: Optional[float]
    probs: Dict[str, float]
    explain: Dict[str, float]


class DynastyModel:
    def __init__(self, cfg: LeagueConfig, repl: ReplacementEngine,
                 anchors: Optional[Dict[str, float]] = None,
                 stud_gamma: float = 1.20,
                 pool: Optional[Dict[str, callable]] = None):
        self.cfg = cfg
        self.repl = repl
        # one anchor per strategy: values are comparable WITHIN a profile
        self.anchors = anchors or {k: 1.0 for k in STRATEGIES}
        self.stud_gamma = stud_gamma
        self.pool = pool or {}

    def calibrate(self, players: List["Player"], target: float = 9800.0) -> None:
        """Set anchors so the most valuable asset in the pool scores `target`."""
        maxima = {k: 1e-9 for k in STRATEGIES}
        for p in players:
            for k, v in self._fundamental_only(p).items():
                maxima[k] = max(maxima[k], v)
        self.anchors = {k: m / ((target / 10000.0) ** (1.0 / self.stud_gamma))
                        for k, m in maxima.items()}

    def _fundamental_only(self, p: "Player") -> Dict[str, float]:
        out = {}
        for key, st in STRATEGIES.items():
            rows = self.season_path(p, st.horizon)
            v = 0.0
            for r in rows:
                t = int(r["t"])
                u = st.usability[min(t, len(st.usability) - 1)]
                v += u * (st.discount ** t) * r["expected"]
            disp = math.sqrt(sum(((st.discount ** int(r["t"])) * r["sigma"] * r["games"]
                                  * r["survival"]) ** 2 for r in rows))
            out[key] = max(0.0, v - st.risk_lambda * 0.35 * disp)
        return out

    # -- season path -------------------------------------------------------
    def season_path(self, p: Player, horizon: int) -> List[Dict[str, float]]:
        g = self.cfg.group(p.pos)
        R = self.repl.R(g)
        a0_eff = effective_age(p.pos, p.age, p.career_load)
        A0 = aging_mult(p.pos, a0_eff, p.archetype)
        dc_decay = math.exp(-0.45 * max(0, p.nfl_season - 1))        # draft capital fades

        rows, S = [], 1.0
        for t in range(0, horizon + 1):
            age_t = p.age + t
            a_eff = effective_age(p.pos, age_t, p.career_load + t * self._load_rate(p))
            A = aging_mult(p.pos, a_eff, p.archetype)
            mu = p.fpg * (A / A0) * ascension_mult(p.kappa, t)
            sig = sigma_fpg(p.pos, max(mu, 0.1), p.risk, p.sigma_source, t)
            games = p.games if t == 0 else 17.0 * (0.86 + 0.10 * p.risk.durability)
            ssv = season_starter_value(mu, sig, R, games)
            if t > 0:
                S *= (1.0 - hazard(p.pos, age_t, p.risk, dc_decay))
            rows.append({"t": t, "age": age_t, "age_eff": a_eff, "mu": mu,
                         "sigma": sig, "games": games, "R": R,
                         "ssv": ssv, "survival": S, "expected": ssv * S})
        return rows

    def _load_rate(self, p: Player) -> float:
        return {"RB": 260.0, "WR": 120.0, "TE": 90.0, "QB": 560.0}.get(p.pos, 700.0)

    # -- aggregate ---------------------------------------------------------
    def value(self, p: Player) -> Valuation:
        fundamental, seasons_cache = {}, None
        for key, st in STRATEGIES.items():
            rows = self.season_path(p, st.horizon)
            if key == "balanced":
                seasons_cache = rows
            v = 0.0
            for r in rows:
                t = int(r["t"])
                u = st.usability[min(t, len(st.usability) - 1)]
                v += u * (st.discount ** t) * r["expected"]
            # certainty equivalent: penalise (or reward) dispersion of the path
            disp = math.sqrt(sum(((st.discount ** int(r["t"])) * r["sigma"] * r["games"]
                                  * r["survival"]) ** 2 for r in rows))
            v_ce = max(0.0, v - st.risk_lambda * 0.35 * disp)
            fundamental[key] = v_ce

        rows = seasons_cache
        R = rows[0]["R"]
        probs = self._probabilities(p, rows, R)
        tv = {k: self.to_trade_value(v, k) for k, v in fundamental.items()}

        blended, gap = None, None
        if p.market_value is not None:
            blended = self.blend_market(p, tv["balanced"])
            gap = tv["balanced"] - p.market_value

        return Valuation(
            player_id=p.player_id, name=p.name, pos=p.pos,
            raw={"fpg": p.fpg, "replacement": R, "vorg": p.fpg - R,
                 "age": p.age, "age_eff": rows[0]["age_eff"]},
            seasons=rows, fundamental=fundamental, trade_value=tv,
            blended_value=blended, market_gap=gap, probs=probs,
            explain=self.explain(p, rows, fundamental["balanced"]),
        )

    # -- probability outputs -----------------------------------------------
    def _probabilities(self, p: Player, rows: List[Dict[str, float]], R: float) -> Dict[str, float]:
        r0 = rows[0]
        z0 = (r0["mu"] - R) / r0["sigma"]
        p_above = _Phi(z0)
        # "elite" = the FPG of a top-(teams/2) finisher at this group in the pool
        g = self.cfg.group(p.pos)
        if g in self.pool:
            elite_line = self.pool[g](max(1, self.cfg.teams // 2))
        else:
            elite_line = R + 1.75 * max(1.0, 0.45 * R)
        p_elite = 1.0 - _Phi((elite_line - r0["mu"]) / r0["sigma"])
        # starter in 3 years
        idx3 = min(3, len(rows) - 1)
        r3 = rows[idx3]
        p_start3 = r3["survival"] * _Phi((r3["mu"] - R) / r3["sigma"])
        # value collapse within one year
        r1 = rows[min(1, len(rows) - 1)]
        p_collapse = 1.0 - r1["survival"] * _Phi((r1["mu"] - R) / r1["sigma"])
        # breakout: exceeds current projection by >35% next year
        p_break = 1.0 - _Phi((1.35 * r0["mu"] - r1["mu"]) / r1["sigma"])
        return {"p_above_replacement": p_above, "p_elite_season": p_elite,
                "p_starter_in_3y": p_start3, "p_bust_year1": 1.0 - p_above,
                "p_value_collapse_1y": p_collapse, "p_breakout": p_break}

    # -- scaling -----------------------------------------------------------
    def to_trade_value(self, v: float, strategy: str = "balanced") -> float:
        a = self.anchors.get(strategy, 1.0)
        return 10000.0 * ((max(0.0, v) / a) ** self.stud_gamma)

    # -- market ------------------------------------------------------------
    def blend_market(self, p: Player, fundamental_tv: float) -> float:
        """
        Bayesian-style blend. Market precision is HIGHER for established
        offensive veterans (deep, liquid market) and LOWER for IDP, rookies and
        deep-bench assets (thin, hype-driven market).
        """
        tau_market = 1.0
        if self.cfg.group(p.pos) in ("DL", "LB", "DB"):
            tau_market *= 0.45
        if p.nfl_season <= 1:
            tau_market *= 0.55
        tau_market *= (1.0 - 0.5 * p.market_dispersion)
        tau_model = 0.85 * (1.0 - 0.4 * p.risk.small_sample)
        w = tau_model / (tau_model + tau_market)
        return w * fundamental_tv + (1 - w) * p.market_value

    # -- explainability ----------------------------------------------------
    def explain(self, p: Player, rows: List[Dict[str, float]], total: float) -> Dict[str, float]:
        st = STRATEGIES["balanced"]
        contrib = []
        for r in rows:
            t = int(r["t"])
            u = st.usability[min(t, len(st.usability) - 1)]
            contrib.append(u * (st.discount ** t) * r["expected"])
        s = sum(contrib) or 1.0
        return {
            "year_0_share": contrib[0] / s,
            "years_1_2_share": sum(contrib[1:3]) / s,
            "years_3_plus_share": sum(contrib[3:]) / s,
            "survival_drag": 1.0 - (sum(r["expected"] for r in rows) /
                                    max(1e-9, sum(r["ssv"] for r in rows))),
            "traj_5y": (rows[min(5, len(rows) - 1)]["mu"] / max(1e-9, rows[0]["mu"])) - 1.0,
            "scarcity_leverage": rows[0]["R"],
        }


# ---------------------------------------------------------------------------
# 11. TRADE / PACKAGE MATH
# ---------------------------------------------------------------------------

def package_value(values: List[float], theta: float = 1.20,
                  roster_spot_cost: float = 120.0, spots_available: int = 3) -> float:
    """
    CES aggregation: (sum v^theta)^(1/theta), theta>1 creates the stud premium and
    prevents 3-for-1 quantity dumps from automatically 'winning'. Then charge for
    roster spots consumed beyond what the receiving team has free.
    """
    if not values:
        return 0.0
    core = sum(v ** theta for v in values) ** (1.0 / theta)
    overflow = max(0, len(values) - max(1, spots_available))
    return core - roster_spot_cost * overflow


def trade_verdict(side_a: List[float], side_b: List[float], **kw) -> Dict[str, float]:
    a, b = package_value(side_a, **kw), package_value(side_b, **kw)
    total = max(1.0, a + b)
    return {"side_a": a, "side_b": b, "edge": a - b, "edge_pct": 100.0 * (a - b) / total}


# ---------------------------------------------------------------------------
# 12. ROOKIE PICKS
# ---------------------------------------------------------------------------

# Illustrative outcome distribution by rookie-draft slot: (P(hit), value_if_hit,
# P(mid), value_if_mid). Values are in the same 0-10000 trade-value units.
# REPLACE with backtested class-specific numbers.
PICK_OUTCOMES = {
    1: (0.62, 7200, 0.20, 2600), 2: (0.55, 6400, 0.22, 2400),
    3: (0.50, 5900, 0.23, 2300), 4: (0.46, 5500, 0.24, 2200),
    6: (0.38, 5000, 0.26, 2000), 8: (0.33, 4600, 0.27, 1800),
    12: (0.27, 4200, 0.28, 1600), 16: (0.20, 3600, 0.28, 1300),
    24: (0.13, 3000, 0.26, 1000), 36: (0.07, 2400, 0.20, 700),
}


def pick_value(overall_slot: int, class_strength: float = 1.0,
               years_out: int = 0, strategy: str = "balanced") -> Dict[str, float]:
    keys = sorted(PICK_OUTCOMES)
    k = min(keys, key=lambda x: abs(x - overall_slot))
    p_hit, v_hit, p_mid, v_mid = PICK_OUTCOMES[k]
    ev = (p_hit * v_hit + p_mid * v_mid) * class_strength
    disc = STRATEGIES[strategy].discount ** years_out
    # contenders discount picks harder; rebuilders pay a flexibility premium
    flex_prem = {"contender": 0.92, "balanced": 1.00, "rebuilder": 1.08}[strategy]
    return {"ev": ev * disc * flex_prem,
            "p_hit": p_hit, "ceiling": v_hit * class_strength,
            "median": v_mid * class_strength, "p_miss": 1 - p_hit - p_mid}


# ---------------------------------------------------------------------------
# 13. ROSTER-LEVEL ANALYSIS
# ---------------------------------------------------------------------------

def roster_report(vals: List[Valuation], cfg: LeagueConfig) -> Dict[str, object]:
    by_group: Dict[str, List[Valuation]] = {}
    for v in vals:
        by_group.setdefault(cfg.group(v.pos), []).append(v)
    for g in by_group:
        by_group[g].sort(key=lambda v: v.raw["fpg"], reverse=True)

    starters_pts, surplus = 0.0, {}
    for g, need in cfg.starters.items():
        grp = by_group.get(g, [])
        starters_pts += sum(v.raw["fpg"] for v in grp[:need])
        have = sum(1 for v in grp if v.raw["vorg"] > 0)
        surplus[g] = have - need
    now = sum(v.trade_value["contender"] for v in vals)
    future = sum(v.trade_value["rebuilder"] for v in vals)
    ages = [v.raw["age"] for v in vals] or [0]
    window = "contend" if now > 1.15 * future else ("rebuild" if future > 1.15 * now else "retool")
    return {"projected_starter_ppg": starters_pts,
            "contender_capital": now, "rebuilder_capital": future,
            "now_vs_future_ratio": now / max(1.0, future),
            "avg_age": sum(ages) / len(ages),
            "positional_surplus": surplus, "recommended_direction": window}
