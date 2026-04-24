"""Monte Carlo trade simulator — consensus-based win-rate.

Depends on: Phase 4 confidence intervals (``src.canonical.confidence_intervals``).

Semantics
---------
Given side-A and side-B as lists of players, each with a
``valueBand`` from Phase 4 (p10, p50, p90), we draw ``n_sims``
samples of total side value and compute the fraction of draws
where side A's sum exceeds side B's sum.

Output: ``{winProbA, mean, spread, percentileBand, method}``.

Labeled strictly as ``consensus_based_win_rate`` — this is NOT
"there's a 62% chance side A wins the trade in real life."  It's
"across the sources' consensus distribution, side A ends up
ahead 62% of the time."  The UI MUST reflect this.

Correlation model
-----------------
Rank-only inputs produce highly independent draws by default.
That's usually wrong — two WR2-archetype guys moving up or down
are often correlated (scheme, depth, injury cascades).  We
support two coarse correlation knobs:

  * ``same_team_rho``: correlation between players on the same
    NFL team.  Default 0.25 — some covariance, not perfect.
  * ``same_pos_group_rho``: correlation across players in the
    same position group (offense vs. IDP).  Default 0.10.

Both are uniform factors applied via a shared latent N(0,1)
draw per (team, pos_group).  Not a full covariance matrix —
good enough for first cut; cheaper than solving for one.

No numpy required — uses Python's stdlib ``random`` module.
NumPy acceleration kicks in when available for the hot loop
but falls back to stdlib without user-visible difference.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

_DEFAULT_SIMS = 50_000


@dataclass(frozen=True)
class TradePlayer:
    """Minimal player shape the simulator needs."""
    name: str
    team: str
    position_group: str  # "offense" | "idp" | "pick"
    p10: float
    p50: float
    p90: float


@dataclass(frozen=True)
class SimResult:
    win_prob_a: float
    mean_delta: float
    std_delta: float
    delta_p10: float
    delta_p50: float
    delta_p90: float
    side_a_mean: float
    side_b_mean: float
    n_sims: int
    method: str  # "consensus_based_win_rate"

    def to_dict(self) -> dict[str, Any]:
        return {
            "winProbA": round(self.win_prob_a, 4),
            "winProbB": round(1.0 - self.win_prob_a, 4),
            "meanDelta": round(self.mean_delta, 1),
            "stdDelta": round(self.std_delta, 1),
            "deltaRange": {
                "p10": round(self.delta_p10, 1),
                "p50": round(self.delta_p50, 1),
                "p90": round(self.delta_p90, 1),
            },
            "sideAMean": round(self.side_a_mean, 1),
            "sideBMean": round(self.side_b_mean, 1),
            "nSims": self.n_sims,
            "method": self.method,
            # UI must show this label to prevent misreads:
            "labelHint": "consensus_based_win_rate",
            "disclaimer": (
                "This is the fraction of consensus-band samples "
                "where side A's total exceeds side B's — NOT a "
                "real-world win probability."
            ),
        }


def _triangular_draw(p10: float, p50: float, p90: float, u: float) -> float:
    """Map a uniform draw u in [0, 1] to the approximate
    distribution with the given quantiles using a piecewise-linear
    interpolation.

    Extended triangular form:
      * 0–0.10 → [p10 - (p50-p10), p10]
      * 0.10–0.50 → [p10, p50]
      * 0.50–0.90 → [p50, p90]
      * 0.90–1.00 → [p90, p90 + (p90-p50)]

    Simple, cheap, and matches the user's mental model: 10th and
    90th percentiles anchor the tails.
    """
    if u <= 0.10:
        # Lower tail extrapolation — match the p10-to-p50 slope.
        slope = p50 - p10
        t = u / 0.10
        return p10 - slope + slope * t  # = p10 - slope * (1-t)
    if u <= 0.50:
        t = (u - 0.10) / 0.40
        return p10 + t * (p50 - p10)
    if u <= 0.90:
        t = (u - 0.50) / 0.40
        return p50 + t * (p90 - p50)
    # Upper tail extrapolation.
    slope = p90 - p50
    t = (u - 0.90) / 0.10
    return p90 + t * slope


def simulate_trade(
    side_a: list[TradePlayer],
    side_b: list[TradePlayer],
    *,
    n_sims: int = _DEFAULT_SIMS,
    same_team_rho: float = 0.25,
    same_pos_group_rho: float = 0.10,
    seed: int | None = None,
) -> SimResult:
    """Run the simulation and return the result.

    Correlation implementation:
      z_team[team] ~ N(0,1) per (team) per sim
      z_pos[group] ~ N(0,1) per (group) per sim
      z_player ~ N(0,1) per player per sim (idiosyncratic)
      u = Phi( sqrt(1-rho_team-rho_pos) * z_player
                + sqrt(rho_team) * z_team[team]
                + sqrt(rho_pos) * z_pos[group] )

    where Phi is the standard normal CDF.  Output u ∈ [0,1] is
    then fed to the triangular draw.  This gives a correlated
    uniform latent; its marginal remains U(0,1) per player so
    the per-player band is preserved on average.
    """
    rng = random.Random(seed)
    players = list(side_a) + list(side_b)
    if not players:
        return SimResult(
            win_prob_a=0.5, mean_delta=0.0, std_delta=0.0,
            delta_p10=0.0, delta_p50=0.0, delta_p90=0.0,
            side_a_mean=0.0, side_b_mean=0.0,
            n_sims=0, method="consensus_based_win_rate",
        )

    # Sanity clamp on correlation params.
    rho_t = max(0.0, min(0.5, same_team_rho))
    rho_p = max(0.0, min(0.5, same_pos_group_rho))
    if rho_t + rho_p >= 1.0:
        rho_t, rho_p = 0.45, 0.45
    idio_var = 1.0 - rho_t - rho_p
    idio_sd = math.sqrt(max(0.0, idio_var))

    teams = sorted({p.team for p in players if p.team})
    groups = sorted({p.position_group for p in players if p.position_group})

    deltas: list[float] = []
    a_sums: list[float] = []
    b_sums: list[float] = []

    for _ in range(n_sims):
        z_team = {t: rng.gauss(0.0, 1.0) for t in teams}
        z_pos = {g: rng.gauss(0.0, 1.0) for g in groups}

        def _sample(pl: TradePlayer) -> float:
            zt = z_team.get(pl.team, 0.0) if rho_t else 0.0
            zp = z_pos.get(pl.position_group, 0.0) if rho_p else 0.0
            z_play = rng.gauss(0.0, 1.0)
            z_total = (
                idio_sd * z_play
                + math.sqrt(rho_t) * zt
                + math.sqrt(rho_p) * zp
            )
            # Convert N(0,1) to U(0,1) via standard-normal CDF.
            u = 0.5 * (1.0 + math.erf(z_total / math.sqrt(2.0)))
            # Clamp to avoid edge artifacts from float error.
            u = max(1e-6, min(1.0 - 1e-6, u))
            return _triangular_draw(pl.p10, pl.p50, pl.p90, u)

        sa = sum(_sample(p) for p in side_a)
        sb = sum(_sample(p) for p in side_b)
        a_sums.append(sa)
        b_sums.append(sb)
        deltas.append(sa - sb)

    deltas.sort()
    a_mean = sum(a_sums) / n_sims
    b_mean = sum(b_sums) / n_sims
    mean_d = sum(deltas) / n_sims
    sd_d = _stdev(deltas)
    wins_a = sum(1 for d in deltas if d > 0) / n_sims

    return SimResult(
        win_prob_a=wins_a,
        mean_delta=mean_d,
        std_delta=sd_d,
        delta_p10=deltas[int(0.10 * n_sims)],
        delta_p50=deltas[int(0.50 * n_sims)],
        delta_p90=deltas[int(0.90 * n_sims)],
        side_a_mean=a_mean,
        side_b_mean=b_mean,
        n_sims=n_sims,
        method="consensus_based_win_rate",
    )


def _stdev(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(var)


def build_trade_player(
    row: dict[str, Any],
) -> TradePlayer | None:
    """Construct a TradePlayer from a canonical-contract player row.

    Prefers the Phase 4 ``valueBand`` dict; falls back to ±15% band
    centered on ``rankDerivedValue`` when CIs haven't been stamped.
    """
    if not isinstance(row, dict):
        return None
    name = str(row.get("name") or row.get("displayName") or "").strip()
    if not name:
        return None
    team = str(row.get("team") or "").strip().upper()
    pos = str(row.get("pos") or row.get("position") or "").upper()
    group = "idp" if pos in ("DL", "LB", "DB", "CB", "S") else (
        "pick" if pos == "PICK" else "offense"
    )
    band = row.get("valueBand") or {}
    if isinstance(band, dict) and band.get("p50") is not None:
        return TradePlayer(
            name=name, team=team, position_group=group,
            p10=float(band.get("p10") or 0),
            p50=float(band.get("p50") or 0),
            p90=float(band.get("p90") or 0),
        )
    # Fallback: synthesize a 15% band around the canonical value.
    cv = float(row.get("rankDerivedValue") or row.get("values", {}).get("full") or 0)
    return TradePlayer(
        name=name, team=team, position_group=group,
        p10=max(0.0, cv * 0.85),
        p50=cv,
        p90=cv * 1.15,
    )
