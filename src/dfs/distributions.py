"""Player outcome distributions + JOINT sampling (DFS-MOD-03).

One interface for "how might this player score": ``PlayerDistribution`` holds
the forecast used (``mean``), a spread, optional quantiles, the family that
turns a uniform draw into points, and where it came from.  Marginals:

* ``normal`` — from an imported standard deviation;
* ``quantile`` — piecewise-linear inverse CDF through imported percentiles;
  tails beyond the outermost percentiles extend the outer segments' slope, at
  most ``TAIL_STRETCH`` of their spread (a stated, conservative choice);
* ``prior`` — sport/position coefficient-of-variation PRIORS, only when the
  caller explicitly allows them, and always flagged ``uncalibrated``.

No range and no permission for priors → no distribution: a missing spread is
never zero variance.

Joint sampling is a **Gaussian copula**: correlated standard normals (the
correlation model's matrix, repaired to the nearest valid correlation matrix if
the priors conflict) → uniforms → each player's own inverse CDF.  Marginals are
exactly preserved; dependence comes only from the correlation model.  Rows that
are the SAME athlete (Showdown CPT + FLEX) share one draw.  Seeded, bounded, and
numpy-only — never the MILP (ADR-DFS-012).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Any

_STD = NormalDist()
TAIL_STRETCH = 1.0  # tails extend at most one outer-segment width past the outer percentiles
MAX_SIMS = 20_000
MAX_PLAYERS = 1_000

# Coefficient-of-variation PRIORS (sd / mean) by sport and position.  Declared,
# not fitted: DFS scoring is right-skewed and volatile, and these only stand in
# until imported ranges or fitted values exist.  Every use is flagged.
CV_PRIORS: dict[str, dict[str, float]] = {
    "nfl": {"QB": 0.40, "RB": 0.55, "WR": 0.65, "TE": 0.70, "DST": 0.85, "K": 0.60},
    "nba": {"PG": 0.30, "SG": 0.33, "SF": 0.33, "PF": 0.32, "C": 0.30, "G": 0.32, "F": 0.32},
    "nhl": {"C": 0.75, "W": 0.75, "D": 0.80, "G": 0.70},
    # MMA is bimodal (win vs loss) — a unimodal prior is misleading, so none is given.
}


@dataclass
class PlayerDistribution:
    player_id: str
    identity: str
    mean: float
    family: str  # normal | quantile | prior
    sd: float | None = None
    quantiles: list[tuple[float, float]] = field(default_factory=list)
    basis: str = ""
    uncalibrated: bool = False

    def inverse_cdf(self, u: float) -> float:
        if self.family in ("normal", "prior"):
            return self.mean + (self.sd or 0.0) * _STD.inv_cdf(min(max(u, 1e-9), 1 - 1e-9))
        qs = self.quantiles
        if u <= qs[0][0]:
            (q0, v0), (q1, v1) = qs[0], qs[1]
            slope = (v1 - v0) / (q1 - q0)
            return max(v0 - slope * (q0 - u), v0 - TAIL_STRETCH * (v1 - v0))
        if u >= qs[-1][0]:
            (q0, v0), (q1, v1) = qs[-2], qs[-1]
            slope = (v1 - v0) / (q1 - q0)
            return min(v1 + slope * (u - q1), v1 + TAIL_STRETCH * (v1 - v0))
        for (q0, v0), (q1, v1) in zip(qs, qs[1:]):
            if q0 <= u <= q1:
                return v0 + (v1 - v0) * (u - q0) / (q1 - q0)
        return qs[-1][1]  # unreachable: u lies inside the covered range


def build(
    athlete: Any, sport: str, *, mean: float | None = None, allow_priors: bool = False
) -> PlayerDistribution | None:
    """The athlete's distribution, or None when there is no honest spread."""
    m = mean if mean is not None else athlete.projection
    if m is None:
        return None
    d = getattr(athlete, "distribution", None) or {}
    ident = getattr(athlete, "identity", athlete.player_id)
    if d.get("sd") is not None:
        return PlayerDistribution(
            athlete.player_id, ident, float(m), "normal", sd=float(d["sd"]), basis="imported_sd"
        )
    qs = sorted((float(q), float(v)) for q, v in (d.get("quantiles") or {}).items())
    if len(qs) >= 2:
        return PlayerDistribution(
            athlete.player_id, ident, float(m), "quantile", quantiles=qs, basis="imported_quantiles"
        )
    if allow_priors:
        cv = next(
            (
                CV_PRIORS.get(sport, {}).get(p)
                for p in athlete.positions
                if p in CV_PRIORS.get(sport, {})
            ),
            None,
        )
        if cv is not None:
            return PlayerDistribution(
                athlete.player_id,
                ident,
                float(m),
                "prior",
                sd=abs(float(m)) * cv,
                basis=f"cv_prior:{sport}",
                uncalibrated=True,
            )
    return None


def _quantile_inverse(d: PlayerDistribution, u: Any) -> Any:
    """Vectorized ``inverse_cdf`` for the quantile family (same tail rule)."""
    import numpy as np

    q = np.array([x for x, _ in d.quantiles])
    v = np.array([y for _, y in d.quantiles])
    out = np.interp(u, q, v)
    lo_slope = (v[1] - v[0]) / (q[1] - q[0])
    hi_slope = (v[-1] - v[-2]) / (q[-1] - q[-2])
    below, above = u < q[0], u > q[-1]
    out[below] = np.maximum(
        v[0] - lo_slope * (q[0] - u[below]), v[0] - TAIL_STRETCH * (v[1] - v[0])
    )
    out[above] = np.minimum(
        v[-1] + hi_slope * (u[above] - q[-1]), v[-1] + TAIL_STRETCH * (v[-1] - v[-2])
    )
    return out


def nearest_correlation(matrix: Any) -> tuple[Any, bool]:
    """Clip negative eigenvalues and rescale to unit diagonal; (matrix, repaired?)."""
    import numpy as np

    m = np.asarray(matrix, dtype=float)
    w, v = np.linalg.eigh((m + m.T) / 2)
    if w.min() >= 1e-10:
        return m, False
    w = np.clip(w, 1e-8, None)
    fixed = v @ np.diag(w) @ v.T
    d = np.sqrt(np.diag(fixed))
    return fixed / np.outer(d, d), True


def sample(
    dists: list[PlayerDistribution], corr: dict[tuple[str, str], float], n: int, seed: int
) -> dict[str, Any]:
    """Joint outcomes: {"points": ndarray (n × players, in ``dists`` order), ...}.

    ``corr`` maps an unordered pair of IDENTITIES to a correlation; absent pairs
    are 0.  Rows sharing an identity get the same draw.
    """
    import numpy as np

    if not 1 <= n <= MAX_SIMS:
        raise ValueError(f"simulation count must be 1..{MAX_SIMS}")
    idents = list(dict.fromkeys(d.identity for d in dists))
    if len(idents) > MAX_PLAYERS:
        raise ValueError(f"at most {MAX_PLAYERS} athletes per simulation")
    pos = {k: i for i, k in enumerate(idents)}
    c = np.eye(len(idents))
    for (a, b), rho in corr.items():
        if a in pos and b in pos and a != b:
            c[pos[a], pos[b]] = c[pos[b], pos[a]] = rho
    c, repaired = nearest_correlation(c)
    chol = np.linalg.cholesky(c + 1e-12 * np.eye(len(idents)))
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((n, len(idents))) @ chol.T
    from scipy.special import ndtr

    u = ndtr(z)
    points = np.empty((n, len(dists)))
    for j, d in enumerate(dists):
        if d.family in ("normal", "prior"):
            points[:, j] = d.mean + (d.sd or 0.0) * z[:, pos[d.identity]]
        else:
            points[:, j] = _quantile_inverse(d, u[:, pos[d.identity]])
    return {
        "points": points,
        "seed": seed,
        "n": n,
        "correlationRepaired": repaired,
        "uncalibratedPlayers": sum(1 for d in dists if d.uncalibrated),
    }
