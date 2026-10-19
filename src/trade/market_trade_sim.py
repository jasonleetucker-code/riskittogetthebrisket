"""Synthetic dynasty trade graphs for the chaseTradeMarket power study (P6a / G12s).

Owner directive 2026-10-19 (Chase Upside Trade Market, V2 wins on conflict):
before any real trade is used to fit a valuation, measure how many completed
trades and how many independent leagues a trade-derived value model needs to
reach a stated per-tier accuracy.  The only honest way to measure that is a
world where the TRUE values are known, so this module invents one.

Nothing here reads a store, a network, a canonical value or a real id.  Every
identifier it produces is a ``syn-`` string, so a synthetic world can never be
mistaken for (or joined to) a real league.  The estimator test bench that
consumes these worlds is :mod:`src.trade.market_trade_sim_bench`.

What the generator models, and why each piece exists:

* **Latent values.**  Offense, IDP and draft-pick assets, each with a true
  log value on a Hill-like 0-9,999 shape.  Values DRIFT week to week (a random
  walk), so an old trade describes an older market — the reason recency
  weighting has to earn its keep.
* **Packages with unequal counts.**  Trades are drawn from a declared topology
  mix (1-for-1, 2-for-1, 3-for-2, ...).  The counter-side is built to clear
  under the TRUE package aggregator (sorted geometric utility, ``q_true``),
  which need not equal the estimator's ``q`` — the aggregator-misspecification
  arm (plan X2).
* **Overpay noise.**  Heavy-tailed (Student-t) clearing noise, a small share
  of grossly lopsided (contaminated) trades, and a per-manager overpay effect.
  A completed trade is NOT assumed fair.
* **Clustering.**  Managers sit in more than one league with a declared
  probability (the snowball-built sharp graph), so leagues that share a
  manager form one manager-lineage COMPONENT — the plan's unit of
  independence for clustering, caps and held-out folds.
* **League activity.**  Lognormal trade counts per league, so a few very
  active leagues can dominate an uncapped fit.
* **Format strata.**  Superflex vs one-QB and TE premium vs none, with true
  positional log shifts.  The truth is stated in a declared REFERENCE format
  (SF, no TE premium) — the estimator must post-stratify to it.
* **League maturity.**  Completed dynasty seasons per league, reported under
  both of the plan's readings (league level as of the build, and point in
  time at the trade).  ``maturity_effect`` optionally makes older leagues less
  noisy, so the bench can measure the POWER to detect "does league age improve
  the signal" (directive V2 §2) — and its false-positive rate at 0.
* **Collection latency.**  ``collected`` is when the observation became
  available; a share is backfilled late.  Folds filter on ``collected``, never
  on the trade date (plan §5 point-in-time rule).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

DOMAINS: tuple[str, ...] = ("offense", "idp", "picks")
POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE", "DL", "LB", "DB", "PICK")
_POS = {p: i for i, p in enumerate(POSITIONS)}
_OFFENSE_POS_SHARE = (("QB", 0.20), ("RB", 0.30), ("WR", 0.35), ("TE", 0.15))
_IDP_POS_SHARE = (("DL", 0.35), ("LB", 0.35), ("DB", 0.30))

# Stratum code = 2 * is_one_qb + is_te_premium.  Code 0 is the REFERENCE
# format the truth is stated in.
STRATA: tuple[tuple[str, str], ...] = (
    ("SF", "NONE"),
    ("SF", "TEP"),
    ("1QB", "NONE"),
    ("1QB", "TEP"),
)
REFERENCE_STRATUM = 0
MAX_PACKAGE = 4

DEFAULT_TOPOLOGY: tuple[tuple[int, int, float], ...] = (
    (1, 1, 0.38),
    (2, 1, 0.24),
    (2, 2, 0.12),
    (3, 1, 0.08),
    (3, 2, 0.10),
    (4, 2, 0.04),
    (3, 3, 0.04),
)


@dataclass(frozen=True)
class SimConfig:
    """Every knob of a synthetic world.  Defaults are DECLARED ASSUMPTIONS for
    the study, not measurements of the real market; the on-box P6 run replaces
    the topology, activity, latency and component structure with the real
    trade graph's measured shape."""

    seed: int = 0
    n_offense: int = 160
    n_idp: int = 60
    pick_years: int = 3
    pick_rounds: int = 4
    n_leagues: int = 40
    trades_per_league: float = 30.0
    activity_sigma: float = 0.8
    teams_per_league: int = 12
    manager_multi_league_prob: float = 0.02
    idp_league_share: float = 0.3
    one_qb_share: float = 0.3
    tep_share: float = 0.4
    format_effects: tuple[tuple[str, str, float], ...] = (
        ("QB", "1QB", -0.55),
        ("TE", "TEP", 0.25),
    )
    topology: tuple[tuple[int, int, float], ...] = DEFAULT_TOPOLOGY
    q_true: float = 0.78
    noise_scale: float = 0.12
    noise_df: float = 4.0
    contamination_share: float = 0.03
    manager_effect_sd: float = 0.05
    maturity_effect: float = 0.0
    # P(completed dynasty seasons = 1..len) at the build date.
    maturity_probs: tuple[float, ...] = (0.20, 0.25, 0.20, 0.15, 0.10, 0.10)
    drift_sd_per_week: float = 0.03
    span_days: int = 364
    season_end_day: int = 120
    latency_mean_days: float = 2.0
    backfill_share: float = 0.05
    popularity_exponent: float = 0.6
    prior_feature_corr: float = 0.5


@dataclass
class AssetTable:
    """Synthetic assets.  ``theta_path[:, w]`` is the TRUE reference-format log
    value in week ``w``; the last column is the value at the end of the span."""

    ids: list[str]
    domain: np.ndarray  # int index into DOMAINS
    position: np.ndarray  # int index into POSITIONS
    theta_path: np.ndarray  # (n_assets, n_weeks)
    prior_feature: np.ndarray  # consensus-free covariate (age / draft-capital stand-in)
    pick_round: np.ndarray  # 0 for non-picks

    @property
    def n(self) -> int:
        return len(self.ids)

    def theta_at(self, day: float) -> np.ndarray:
        week = int(np.clip(np.floor(day / 7.0), 0, self.theta_path.shape[1] - 1))
        return self.theta_path[:, week]


@dataclass
class LeagueTable:
    ids: list[str]
    stratum: np.ndarray
    idp: np.ndarray  # bool
    maturity: np.ndarray  # completed dynasty seasons at the build date
    component: np.ndarray  # manager-lineage component index
    noise_scale: np.ndarray
    seats: list[list[int]]  # manager index per seat

    @property
    def n(self) -> int:
        return len(self.ids)


@dataclass
class TradeSet:
    """Columnar trades.  Side arrays are ``(n, MAX_PACKAGE)`` asset indices
    padded with -1.  ``mgr_a`` SENDS side A and receives side B."""

    side_a: np.ndarray
    side_b: np.ndarray
    league: np.ndarray
    stratum: np.ndarray
    date: np.ndarray
    collected: np.ndarray
    mgr_a: np.ndarray
    mgr_b: np.ndarray
    component: np.ndarray
    maturity_now: np.ndarray
    maturity_pit: np.ndarray
    true_residual: np.ndarray
    contaminated: np.ndarray

    @property
    def n(self) -> int:
        return int(self.side_a.shape[0])

    def subset(self, mask: np.ndarray) -> "TradeSet":
        mask = np.asarray(mask)
        return TradeSet(**{k: getattr(self, k)[mask] for k in _TRADE_FIELDS})

    def counts(self) -> np.ndarray:
        """``(n, 2)`` asset counts per side."""
        return np.stack([(self.side_a >= 0).sum(1), (self.side_b >= 0).sum(1)], axis=1)


_TRADE_FIELDS = tuple(TradeSet.__dataclass_fields__)


@dataclass
class SimWorld:
    config: SimConfig
    assets: AssetTable
    leagues: LeagueTable
    trades: TradeSet
    manager_ids: list[str]
    manager_effect: np.ndarray
    component_ids: list[str]
    true_format_offset: np.ndarray = field(repr=False)  # (n_positions, n_strata)

    @property
    def n_weeks(self) -> int:
        return int(self.assets.theta_path.shape[1])


# --------------------------------------------------------------------------- #
# Deterministic seeds
# --------------------------------------------------------------------------- #


def derive_seed(*parts: object) -> int:
    """A stable 63-bit seed from arbitrary parts — ``hashlib``, never ``hash()``,
    so replicates are byte-reproducible across processes (plan §7)."""
    h = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return int(h[:15], 16)


# --------------------------------------------------------------------------- #
# Format offsets
# --------------------------------------------------------------------------- #


def format_offset_matrix(effects: Sequence[tuple[str, str, float]]) -> np.ndarray:
    """``(n_positions, n_strata)`` true log shift of a position in a stratum,
    relative to the reference stratum (which is always 0)."""
    out = np.zeros((len(POSITIONS), len(STRATA)))
    for pos, value, shift in effects:
        for s, names in enumerate(STRATA):
            if value in names:
                out[_POS[pos], s] += float(shift)
    out[:, REFERENCE_STRATUM] = 0.0
    return out


def format_effect_design(
    effects: Sequence[tuple[str, str, float]],
) -> np.ndarray:
    """``(n_positions * n_strata, n_effects)`` 0/1 map from a (position,
    stratum) combo to the format effects that apply to it — the estimator's
    view of the same structure, with the shift sizes unknown."""
    m = np.zeros((len(POSITIONS) * len(STRATA), len(effects)))
    for k, (pos, value, _shift) in enumerate(effects):
        for s, names in enumerate(STRATA):
            if s != REFERENCE_STRATUM and value in names:
                m[_POS[pos] * len(STRATA) + s, k] = 1.0
    return m


def geom_log_utility(values: np.ndarray, q: float) -> float:
    """``log sum q**i v_i`` over positive values sorted descending — the same
    utility as ``src.valuation_math.package_model.geom_utility`` (parity is
    pinned by test), in log space."""
    v = np.sort(np.asarray(values, dtype=float))[::-1]
    v = v[v > 0]
    if v.size == 0:
        return float("-inf")
    return float(np.log(np.sum(v * q ** np.arange(v.size))))


# --------------------------------------------------------------------------- #
# World generation
# --------------------------------------------------------------------------- #


def _hill_values(n: int, top: float, c: float, k: float) -> np.ndarray:
    r = np.arange(1, n + 1, dtype=float)
    return top * (1.0 + r / c) ** (-k)


def _make_assets(cfg: SimConfig, rng: np.random.Generator) -> AssetTable:
    ids: list[str] = []
    dom: list[int] = []
    pos: list[int] = []
    logv: list[float] = []
    rounds: list[int] = []

    def _positions(share: tuple[tuple[str, float], ...], n: int) -> list[int]:
        names = [p for p, _ in share]
        probs = np.array([s for _, s in share], dtype=float)
        return [_POS[names[i]] for i in rng.choice(len(names), size=n, p=probs / probs.sum())]

    off = _hill_values(cfg.n_offense, 9999.0, 40.0, 1.2)
    for i, p in enumerate(_positions(_OFFENSE_POS_SHARE, cfg.n_offense)):
        ids.append(f"syn-asset-o{i:04d}")
        dom.append(0)
        pos.append(p)
        logv.append(float(np.log(off[i])))
        rounds.append(0)
    idp = _hill_values(cfg.n_idp, 4000.0, 15.0, 1.2)
    for i, p in enumerate(_positions(_IDP_POS_SHARE, cfg.n_idp)):
        ids.append(f"syn-asset-d{i:04d}")
        dom.append(1)
        pos.append(p)
        logv.append(float(np.log(idp[i])))
        rounds.append(0)
    j = 0
    for y in range(1, cfg.pick_years + 1):
        for rnd in range(1, cfg.pick_rounds + 1):
            for tier_mult in (1.25, 1.0, 0.8):
                v = 6500.0 * 0.45 ** (rnd - 1) * tier_mult * 0.88 ** (y - 1)
                ids.append(f"syn-asset-p{j:04d}")
                dom.append(2)
                pos.append(_POS["PICK"])
                logv.append(float(np.log(v)))
                rounds.append(rnd)
                j += 1

    n = len(ids)
    theta_end = np.asarray(logv) + rng.normal(0.0, 0.05, size=n)
    n_weeks = cfg.span_days // 7 + 1
    steps = rng.normal(0.0, cfg.drift_sd_per_week, size=(n, n_weeks - 1))
    # theta(w) = theta_end - sum of the steps after week w (a walk ending at theta_end).
    tail = np.cumsum(steps[:, ::-1], axis=1)[:, ::-1]
    path = np.empty((n, n_weeks))
    path[:, -1] = theta_end
    path[:, :-1] = theta_end[:, None] - tail

    # Consensus-free prior covariate: correlated with the truth WITHIN each
    # domain at the declared strength, never derived from any market value.
    x = np.zeros(n)
    dom_arr = np.asarray(dom)
    rho = float(np.clip(cfg.prior_feature_corr, 0.0, 1.0))
    for d in range(len(DOMAINS)):
        m = dom_arr == d
        if m.sum() < 2:
            continue
        z = (theta_end[m] - theta_end[m].mean()) / (theta_end[m].std() or 1.0)
        x[m] = rho * z + np.sqrt(1.0 - rho**2) * rng.normal(size=int(m.sum()))
    return AssetTable(
        ids=ids,
        domain=dom_arr,
        position=np.asarray(pos),
        theta_path=path,
        prior_feature=x,
        pick_round=np.asarray(rounds),
    )


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, a: int) -> int:
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def manager_lineage_components(seats: Sequence[Sequence[int]]) -> np.ndarray:
    """League -> component index: leagues that share any manager are one
    component (union-find; transitive).  Component indices are dense and
    ordered by their smallest league index, so the labelling is deterministic."""
    uf = _UnionFind(len(seats))
    first_league: dict[int, int] = {}
    for league, mgrs in enumerate(seats):
        for m in mgrs:
            if m in first_league:
                uf.union(league, first_league[m])
            else:
                first_league[m] = league
    roots = [uf.find(i) for i in range(len(seats))]
    dense: dict[int, int] = {}
    return np.asarray([dense.setdefault(r, len(dense)) for r in roots], dtype=int)


def _make_leagues(
    cfg: SimConfig, rng: np.random.Generator
) -> tuple[LeagueTable, list[str], np.ndarray]:
    n = cfg.n_leagues
    seats: list[list[int]] = []
    n_mgr = 0
    for league in range(n):
        row: list[int] = []
        for _ in range(cfg.teams_per_league):
            if league > 0 and n_mgr > 0 and rng.random() < cfg.manager_multi_league_prob:
                cand = int(rng.integers(0, n_mgr))
                if cand not in row:
                    row.append(cand)
                    continue
            row.append(n_mgr)
            n_mgr += 1
        seats.append(row)
    qb1 = rng.random(n) < cfg.one_qb_share
    tep = rng.random(n) < cfg.tep_share
    stratum = (2 * qb1 + tep).astype(int)
    idp = rng.random(n) < cfg.idp_league_share
    probs = np.asarray(cfg.maturity_probs, dtype=float)
    maturity = 1 + rng.choice(len(probs), size=n, p=probs / probs.sum())
    noise = cfg.noise_scale * np.exp(-cfg.maturity_effect * (maturity - 3.0))
    comp = manager_lineage_components(seats)
    leagues = LeagueTable(
        ids=[f"syn-league-{i:04d}" for i in range(n)],
        stratum=stratum,
        idp=idp,
        maturity=maturity.astype(int),
        component=comp,
        noise_scale=noise,
        seats=seats,
    )
    mgr_ids = [f"syn-mgr-{i:05d}" for i in range(n_mgr)]
    mgr_effect = rng.normal(0.0, cfg.manager_effect_sd, size=n_mgr)
    return leagues, mgr_ids, mgr_effect


def _pick_by_value(
    rng: np.random.Generator,
    pool: np.ndarray,
    values: np.ndarray,
    lo: float,
    hi: float,
    popularity: np.ndarray,
) -> int | None:
    m = (values[pool] >= lo) & (values[pool] <= hi)
    if not m.any():
        return None
    cand = pool[m]
    p = popularity[cand]
    return int(rng.choice(cand, p=p / p.sum()))


def _closest(pool: np.ndarray, values: np.ndarray, target: float, cap: float) -> int | None:
    m = values[pool] <= cap
    if not m.any() or target <= 0:
        return None
    cand = pool[m]
    return int(cand[np.argmin(np.abs(np.log(values[cand]) - np.log(target)))])


def _construct_side(
    rng: np.random.Generator,
    pool: np.ndarray,
    values: np.ndarray,
    popularity: np.ndarray,
    k: int,
    target_u: float,
    q: float,
) -> list[int] | None:
    """Build a ``k``-asset side whose sorted geometric utility is close to
    ``target_u``.  The realised mismatch becomes part of the clearing noise,
    which is what discrete markets look like."""
    if k == 1:
        a = _closest(pool, values, target_u, np.inf)
        return None if a is None else [a]
    chosen: list[int] = []
    remaining = target_u
    cap = np.inf
    avail = pool.copy()
    for i in range(k):
        weight = q**i
        slot_target = remaining / weight
        if i == 0:
            a = _pick_by_value(rng, avail, values, 0.45 * target_u, 0.92 * target_u, popularity)
        elif i < k - 1:
            hi = min(cap, slot_target)
            a = _pick_by_value(rng, avail, values, 0.30 * hi, hi, popularity)
        else:
            a = _closest(avail, values, slot_target, cap)
        if a is None:
            return None
        chosen.append(a)
        remaining -= weight * values[a]
        cap = values[a]
        avail = avail[avail != a]
        if remaining <= 0 and i < k - 1:
            return None
    return chosen


def generate_world(cfg: SimConfig) -> SimWorld:
    """Build one synthetic world, fully determined by ``cfg`` (incl. seed)."""
    rng = np.random.default_rng(cfg.seed)
    assets = _make_assets(cfg, rng)
    leagues, mgr_ids, mgr_effect = _make_leagues(cfg, rng)
    fx = format_offset_matrix(cfg.format_effects)

    topo = np.asarray([p for _, _, p in cfg.topology], dtype=float)
    topo = topo / topo.sum()
    kab = [(a, b) for a, b, _ in cfg.topology]

    activity = rng.lognormal(-0.5 * cfg.activity_sigma**2, cfg.activity_sigma, size=leagues.n)
    n_per_league = rng.poisson(cfg.trades_per_league * activity)

    rows: dict[str, list] = {k: [] for k in _TRADE_FIELDS}
    end_values = np.exp(assets.theta_path[:, -1])
    popularity = end_values**cfg.popularity_exponent
    for league in range(leagues.n):
        domains = [0, 2] + ([1] if leagues.idp[league] else [])
        pool = np.flatnonzero(np.isin(assets.domain, domains))
        s = int(leagues.stratum[league])
        seats = leagues.seats[league]
        made = 0
        attempts = 0
        while made < n_per_league[league] and attempts < 20 * max(1, n_per_league[league]):
            attempts += 1
            day = float(rng.uniform(0, cfg.span_days))
            values = np.exp(assets.theta_at(day) + fx[assets.position, s])
            ka, kb = kab[int(rng.choice(len(kab), p=topo))]
            if rng.random() < 0.5:  # randomise which side is the larger package
                ka, kb = kb, ka
            pa = popularity[pool] / popularity[pool].sum()
            side_a = [int(a) for a in rng.choice(pool, size=ka, replace=False, p=pa)]
            sa, sb = rng.choice(len(seats), size=2, replace=False)
            ma, mb = seats[int(sa)], seats[int(sb)]
            contaminated = bool(rng.random() < cfg.contamination_share)
            if contaminated:
                eps = float(rng.choice([-1.0, 1.0]) * rng.uniform(0.8, 1.6))
            else:
                eps = float(leagues.noise_scale[league] * rng.standard_t(cfg.noise_df))
            eps += float(mgr_effect[ma] - mgr_effect[mb])
            u_a = float(np.exp(geom_log_utility(values[side_a], cfg.q_true)))
            rest = pool[~np.isin(pool, side_a)]
            side_b = _construct_side(
                rng, rest, values, popularity, kb, u_a * np.exp(-eps), cfg.q_true
            )
            if side_b is None:
                continue
            realised = geom_log_utility(values[side_a], cfg.q_true) - geom_log_utility(
                values[side_b], cfg.q_true
            )
            if rng.random() < cfg.backfill_share:
                collected = float(cfg.span_days + rng.uniform(0, 7))
            else:
                collected = day + float(rng.exponential(cfg.latency_mean_days))
            mat = int(leagues.maturity[league])
            rows["side_a"].append(side_a + [-1] * (MAX_PACKAGE - ka))
            rows["side_b"].append(side_b + [-1] * (MAX_PACKAGE - kb))
            rows["league"].append(league)
            rows["stratum"].append(s)
            rows["date"].append(day)
            rows["collected"].append(collected)
            rows["mgr_a"].append(ma)
            rows["mgr_b"].append(mb)
            rows["component"].append(int(leagues.component[league]))
            rows["maturity_now"].append(mat)
            rows["maturity_pit"].append(mat if day >= cfg.season_end_day else mat - 1)
            rows["true_residual"].append(realised)
            rows["contaminated"].append(contaminated)
            made += 1

    order = np.lexsort((np.asarray(rows["league"]), np.asarray(rows["date"])))
    arrays = {
        "side_a": np.asarray(rows["side_a"], dtype=int).reshape(-1, MAX_PACKAGE),
        "side_b": np.asarray(rows["side_b"], dtype=int).reshape(-1, MAX_PACKAGE),
        "league": np.asarray(rows["league"], dtype=int),
        "stratum": np.asarray(rows["stratum"], dtype=int),
        "date": np.asarray(rows["date"], dtype=float),
        "collected": np.asarray(rows["collected"], dtype=float),
        "mgr_a": np.asarray(rows["mgr_a"], dtype=int),
        "mgr_b": np.asarray(rows["mgr_b"], dtype=int),
        "component": np.asarray(rows["component"], dtype=int),
        "maturity_now": np.asarray(rows["maturity_now"], dtype=int),
        "maturity_pit": np.asarray(rows["maturity_pit"], dtype=int),
        "true_residual": np.asarray(rows["true_residual"], dtype=float),
        "contaminated": np.asarray(rows["contaminated"], dtype=bool),
    }
    trades = TradeSet(**{k: v[order] for k, v in arrays.items()})
    n_comp = int(leagues.component.max()) + 1 if leagues.n else 0
    return SimWorld(
        config=cfg,
        assets=assets,
        leagues=leagues,
        trades=trades,
        manager_ids=mgr_ids,
        manager_effect=mgr_effect,
        component_ids=[f"syn-comp-{i:04d}" for i in range(n_comp)],
        true_format_offset=fx,
    )


# --------------------------------------------------------------------------- #
# Folds — clustered by manager-lineage component, split on collection time
# --------------------------------------------------------------------------- #


def reserved_components(component_ids: Sequence[str], *, salt: str, share: float) -> set[int]:
    """Components assigned to the locked reserve by
    ``sha256(componentId | salt)`` — the same rule the P1 reserve owner applies
    to real components (plan §5), so the bench exercises the real split
    semantics.  Deterministic and independent of component order."""
    out: set[int] = set()
    for i, cid in enumerate(component_ids):
        u = int(hashlib.sha256(f"{cid}|{salt}".encode("utf-8")).hexdigest()[:15], 16) / 16**15
        if u < share:
            out.add(i)
    return out


def chronological_split(
    trades: TradeSet, *, cutoff_day: float, purge_days: float
) -> tuple[np.ndarray, np.ndarray, float | None]:
    """``(train_mask, test_mask, evidence_cutoff)``.

    * train — observations COLLECTED by ``cutoff_day``.  A trade dated before
      the cutoff but collected after it is NOT training data: the model could
      not have seen it (plan §5, "filter on collectedAt ≤ T").
    * test — trades DATED after ``cutoff_day + purge_days``.
    * evidence_cutoff — the newest collection time in train; the anchor for
      recency ages and the as-of date of the truth (never the wall clock).
    """
    train = trades.collected <= cutoff_day
    test = trades.date > cutoff_day + purge_days
    cutoff = float(trades.collected[train].max()) if train.any() else None
    return train, test, cutoff


def maturity_cohort(maturity: np.ndarray) -> np.ndarray:
    """``A`` (>=3 completed seasons), ``B`` (exactly 2), ``below_B`` — the
    plan §3 cohorts.  Callers pass either reading (league level now, or point
    in time at the trade); the reading is never chosen here."""
    m = np.asarray(maturity)
    return np.where(m >= 3, "A", np.where(m == 2, "B", "below_B"))
