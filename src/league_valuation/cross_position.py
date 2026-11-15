"""Candidate D -- common league-utility scale, independently calibrated (SHADOW).

Authority: ``docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md`` section 9
(cross-position value).  Definition: ``docs/valuation/idp_accuracy/G_PREREGISTRATION.md``
section 4.5.  Record: ``docs/valuation/idp_accuracy/F_CANDIDATES.md``.

Shadow only and unwired.  Nothing here is served, flagged, or read by a route, a
contract field, an engine or a page (``tests/league_valuation/test_isolation.py``).
It imports nothing from ``src`` outside this package: the one canonical lineup
solver is INJECTED through :class:`~src.league_valuation.replacement_shadow.LineupPort`,
so this file can never become a second lineup engine.

**What D is.**  The ex-ante *expected league-average marginal best-ball contribution*
of a player, in expected league points per week::

    V_i = (1/S) sum_s (1/T) sum_t [ L(R_t U {i}, x_s) - L(R_t \\ {i}, x_s) ]

``L`` is the optimal best-ball lineup total of a roster under weekly scores ``x_s``
(the exact solver), ``R_t`` is team ``t``'s cutoff roster (for a player on ``R_t``
the union is ``R_t``; for one not on it the difference is ``R_t``), and every
simulated week draws each player independently::

    played  ~ Bernoulli(a_i)
    score   = mu_i + eps     if played,   eps drawn uniformly from his residual set
            = 0              if not

There is **no replacement constant**: replacement emerges from who is on each
roster.  There is **no market input**: D is an identity transform on the league
points scale, never mapped to 1-9999, never fitted to any price, never quantile
matched to any board (directive section 9: when no independent transform exists
the estimate stays uncalibrated).  It is compared with other candidates only
through RANKS, and with outcomes only on the same points scale.

**Missing is never zero.**  A rostered player with no ``mu`` is UNKNOWN in the
ex-ante environment: he is not a candidate for a lineup slot (the exact solver's
``None`` semantics) and no value is imputed.  A player with no residual set (none
of his own and an empty pooled set for his stratum) cannot be simulated and is
reported, not drawn from a made-up distribution.

**Reproducible in parallel.**  Each simulated week owns an independent child
stream, ``PCG64(SeedSequence([seed, week]))``, so the result is a function of the
seed alone, never of how the weeks were chunked across workers.

Simplifications, declared: independent draws across players and weeks (no game-script
correlation); the roster cap is ignored when a player is added; no injury status at
the cutoff.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from src.league_valuation.replacement_shadow import LineupPlayer, LineupPort

__all__ = [
    "MODEL_VERSION",
    "DEFAULT_WEEKS",
    "DEFAULT_SEED",
    "DEFAULT_PSEUDO_GAMES",
    "DEFAULT_MIN_OWN_RESIDUALS",
    "SimInputs",
    "WeekMarginals",
    "DResult",
    "availability_rate",
    "residuals_of",
    "pooled_residual_sets",
    "week_rng",
    "draw_week",
    "lineup_total",
    "league_average_marginals",
    "simulate_week",
    "summarize_weeks",
    "run_serial",
    "inputs_fingerprint",
    "stable_hash",
]

MODEL_VERSION = "cross_position_d_v1"

#: Preregistered (G_PREREGISTRATION.md section 4.5 / 15): 200 simulated weeks,
#: a seed on a stream separate from the bootstrap's, a quarter-season pseudo-count
#: (a declared PRIOR), and six own residuals before a player's own set is used.
DEFAULT_WEEKS = 200
DEFAULT_SEED = 20261027
DEFAULT_PSEUDO_GAMES = 4.0
DEFAULT_MIN_OWN_RESIDUALS = 6


# ── availability and residuals ───────────────────────────────────────────────


def availability_rate(
    games: float, team_games: float, position_mean: float, pseudo: float = DEFAULT_PSEUDO_GAMES
) -> float:
    """``a_i = (g_i + pseudo * abar_p) / (G_i + pseudo)``, bounded to [0, 1].

    ``g`` is the games the player played in the admissible history, ``G`` the team
    games while he could have, ``abar_p`` the cohort mean of ``g / G`` at his
    position, and ``pseudo`` a declared PRIOR pseudo-count.  With ``pseudo == 0`` it
    is the raw rate ``g / G`` (and undefined, hence an error, when ``G == 0``).
    """
    if games < 0 or team_games < 0 or pseudo < 0:
        raise ValueError("games, team_games and pseudo must be non-negative")
    if not (0.0 <= position_mean <= 1.0):
        raise ValueError(f"position_mean must lie in [0, 1]: {position_mean}")
    denom = team_games + pseudo
    if denom <= 0:
        raise ValueError("availability is undefined with no team games and no pseudo-count")
    a = (games + pseudo * position_mean) / denom
    return min(1.0, max(0.0, a))


def residuals_of(scores: Sequence[float]) -> tuple[float, ...]:
    """``E_i = {y_k - ybar}`` over the games the player played.  Empty for no games."""
    ys = [float(y) for y in scores]
    if not ys:
        return ()
    mean = math.fsum(ys) / len(ys)
    return tuple(y - mean for y in ys)


def pooled_residual_sets(
    own: Mapping[str, Sequence[float]],
    stratum: Mapping[str, str],
    *,
    eligible_ids: Iterable[str],
    min_own: int = DEFAULT_MIN_OWN_RESIDUALS,
) -> dict[str, tuple[float, ...]]:
    """Per stratum, the union of the residuals of eligible players with ``>= min_own``.

    ``eligible_ids`` is the cohort the pool is drawn from (the preregistration's
    "cohort players j with i's cutoff position and ``|E_j| >= 6``").  A stratum with
    no such player maps to the empty tuple, never to a fabricated set.
    """
    pools: dict[str, list[float]] = {}
    for pid in sorted(set(eligible_ids)):
        e = own.get(pid) or ()
        if len(e) < min_own:
            continue
        pools.setdefault(stratum[pid], []).extend(float(x) for x in e)
    return {k: tuple(v) for k, v in sorted(pools.items())}


# ── inputs ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SimInputs:
    """Everything the simulation reads.  Public NFL facts and anonymous team labels only.

    ``mu`` maps ``player_id -> projected league points per game`` and its keys are the
    players the ex-ante environment KNOWS about.  A rostered id absent from it is
    UNKNOWN.  ``teams`` maps an anonymous label to roster ids.  ``position`` /
    ``fantasy_positions`` feed the lineup solver's eligibility.
    """

    mu: Mapping[str, float]
    availability: Mapping[str, float]
    own_residuals: Mapping[str, tuple[float, ...]]
    pooled: Mapping[str, tuple[float, ...]]
    stratum: Mapping[str, str]
    position: Mapping[str, str]
    fantasy_positions: Mapping[str, tuple[str, ...]]
    teams: Mapping[str, Sequence[str]]
    slots: Sequence[str]
    min_own_residuals: int = DEFAULT_MIN_OWN_RESIDUALS

    def residual_set(self, pid: str) -> tuple[float, ...]:
        """Own residuals when ``>= min_own``, otherwise the pooled set for his stratum."""
        own = self.own_residuals.get(pid, ())
        if len(own) >= self.min_own_residuals:
            return own
        return self.pooled.get(self.stratum.get(pid, ""), ())

    def simulable(self) -> list[str]:
        """Players with a ``mu``, an availability and a non-empty residual set, sorted."""
        return sorted(
            pid for pid in self.mu if pid in self.availability and len(self.residual_set(pid)) > 0
        )

    def unsimulable(self) -> dict[str, str]:
        """Players with a ``mu`` that cannot be drawn, with the reason (never a made-up draw)."""
        out: dict[str, str] = {}
        for pid in sorted(self.mu):
            if pid not in self.availability:
                out[pid] = "no_availability"
            elif len(self.residual_set(pid)) == 0:
                out[pid] = "no_residual_set"
        return out


def inputs_fingerprint(inputs: SimInputs) -> str:
    """A content hash of the inputs, so a result can name exactly what produced it."""
    payload = {
        "mu": sorted((k, round(float(v), 9)) for k, v in inputs.mu.items()),
        "a": sorted((k, round(float(v), 9)) for k, v in inputs.availability.items()),
        "own": sorted((k, [round(x, 9) for x in v]) for k, v in inputs.own_residuals.items()),
        "pooled": sorted((k, [round(x, 9) for x in v]) for k, v in inputs.pooled.items()),
        "stratum": sorted(inputs.stratum.items()),
        "teams": sorted((k, sorted(v)) for k, v in inputs.teams.items()),
        "slots": list(inputs.slots),
        "minOwn": inputs.min_own_residuals,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ── simulation ───────────────────────────────────────────────────────────────


def week_rng(seed: int, week_index: int) -> np.random.Generator:
    """The independent child stream of simulated week ``week_index``."""
    return np.random.Generator(
        np.random.PCG64(np.random.SeedSequence([int(seed), int(week_index)]))
    )


def draw_week(
    inputs: SimInputs, rng: np.random.Generator, *, sigma: bool = True
) -> dict[str, float]:
    """One simulated week of scores for every simulable player.

    Draw order is fixed (sorted ids; one uniform for ``played``, one for the residual
    index, both ALWAYS drawn so the stream does not depend on who played), so the same
    stream gives the same week.  ``sigma=False`` is the declared ablation D(sigma=0):
    residuals are set to zero, availability still varies.
    """
    ids = inputs.simulable()
    n = len(ids)
    u_play = rng.random(n)
    u_res = rng.random(n)
    out: dict[str, float] = {}
    for i, pid in enumerate(ids):
        if u_play[i] >= inputs.availability[pid]:
            out[pid] = 0.0
            continue
        if sigma:
            pool = inputs.residual_set(pid)
            eps = pool[min(len(pool) - 1, int(u_res[i] * len(pool)))]
        else:
            eps = 0.0
        out[pid] = float(inputs.mu[pid]) + eps
    return out


def lineup_total(
    port: LineupPort,
    slots: Sequence[str],
    roster: Iterable[str],
    scores: Mapping[str, float],
    meta: Mapping[str, tuple[str, tuple[str, ...]]],
) -> float:
    """``L(R, x)``: the exact best-ball lineup total of ``roster`` under ``scores``.

    A roster member with no entry in ``scores`` is UNKNOWN and not a candidate.  A slot
    nobody can fill scores nothing.
    """
    players: list[LineupPlayer] = []
    for pid in roster:
        if pid in scores:
            position, fps = meta[pid]
            players.append(LineupPlayer(pid, position, fps, float(scores[pid])))
    if not players:
        return 0.0
    assignment = port.solve(players, list(slots))
    pts = {p.player_id: p.points for p in players}
    return math.fsum(pts[pid] for pid in assignment.values())


@dataclass(frozen=True)
class WeekMarginals:
    """One simulated (or realized) week: ``player -> league-average marginal``."""

    week: int
    marginal: Mapping[str, float]


def league_average_marginals(
    port: LineupPort,
    slots: Sequence[str],
    teams: Mapping[str, Sequence[str]],
    scores: Mapping[str, float],
    evaluate_ids: Iterable[str],
    meta: Mapping[str, tuple[str, tuple[str, ...]]],
    *,
    own_team_only: bool = False,
) -> dict[str, float]:
    """``(1/T) sum_t [ L(R_t U {i}) - L(R_t \\ {i}) ]`` for each evaluated player, one week.

    ``scores`` is the week's scores for every assignable player; a player absent from it
    is not assignable.  ``own_team_only`` restricts a ROSTERED player to his own team
    (the declared roster-context ablation); an unrostered player is always averaged over
    every team.  Players with no entry in ``scores`` are skipped (no value, never 0).
    """
    labels = sorted(teams)
    n_teams = len(labels)
    rosters = {t: tuple(teams[t]) for t in labels}
    members = {t: set(rosters[t]) for t in labels}
    base = {t: lineup_total(port, slots, rosters[t], scores, meta) for t in labels}
    out: dict[str, float] = {}
    for pid in evaluate_ids:
        if pid not in scores:
            continue
        owner = next((t for t in labels if pid in members[t]), None)
        total = 0.0
        if own_team_only and owner is not None:
            without = tuple(x for x in rosters[owner] if x != pid)
            total = base[owner] - lineup_total(port, slots, without, scores, meta)
            out[pid] = total
            continue
        for t in labels:
            if pid in members[t]:
                without = tuple(x for x in rosters[t] if x != pid)
                total += base[t] - lineup_total(port, slots, without, scores, meta)
            else:
                total += lineup_total(port, slots, rosters[t] + (pid,), scores, meta) - base[t]
        out[pid] = total / n_teams
    return out


def simulate_week(
    inputs: SimInputs,
    port: LineupPort,
    week_index: int,
    evaluate_ids: Iterable[str],
    *,
    seed: int = DEFAULT_SEED,
    sigma: bool = True,
    own_team_only: bool = False,
) -> WeekMarginals:
    """Simulated week ``week_index``: draw scores, then every evaluated player's marginal."""
    scores = draw_week(inputs, week_rng(seed, week_index), sigma=sigma)
    meta = {
        pid: (inputs.position.get(pid, ""), tuple(inputs.fantasy_positions.get(pid, ())))
        for pid in set(scores)
    }
    marg = league_average_marginals(
        port,
        inputs.slots,
        inputs.teams,
        scores,
        evaluate_ids,
        meta,
        own_team_only=own_team_only,
    )
    return WeekMarginals(week=int(week_index), marginal=marg)


@dataclass(frozen=True)
class DResult:
    """``V^D`` per player with its Monte-Carlo standard error.

    ``value`` is in expected league points per week.  ``mc_se`` is the standard error of
    the mean over simulated weeks; ties inside it are not broken artificially.
    """

    value: Mapping[str, float]
    mc_se: Mapping[str, float]
    weeks: int
    seed: int
    model_version: str = MODEL_VERSION
    promotes: bool = False
    transform: str = "identity_league_points_per_week"
    notes: tuple[str, ...] = field(default_factory=tuple)


def summarize_weeks(weeks: Sequence[WeekMarginals], *, seed: int = DEFAULT_SEED) -> DResult:
    """Average the weekly marginals.  A player missing from some week is averaged over
    the weeks he was evaluated in (he is never given a 0 for a week he was not drawn)."""
    sums: dict[str, float] = {}
    sq: dict[str, float] = {}
    counts: dict[str, int] = {}
    for wk in weeks:
        for pid, m in wk.marginal.items():
            sums[pid] = sums.get(pid, 0.0) + m
            sq[pid] = sq.get(pid, 0.0) + m * m
            counts[pid] = counts.get(pid, 0) + 1
    value: dict[str, float] = {}
    se: dict[str, float] = {}
    for pid in sorted(sums):
        n = counts[pid]
        mean = sums[pid] / n
        value[pid] = mean
        var = max(0.0, (sq[pid] - n * mean * mean) / (n - 1)) if n > 1 else 0.0
        se[pid] = math.sqrt(var / n) if n > 1 else float("nan")
    return DResult(value=value, mc_se=se, weeks=len(weeks), seed=int(seed))


def run_serial(
    inputs: SimInputs,
    port: LineupPort,
    evaluate_ids: Iterable[str],
    *,
    weeks: int = DEFAULT_WEEKS,
    seed: int = DEFAULT_SEED,
    sigma: bool = True,
    own_team_only: bool = False,
) -> DResult:
    """The whole simulation in one process (a parallel driver must equal this exactly)."""
    ids = list(evaluate_ids)
    done = [
        simulate_week(inputs, port, s, ids, seed=seed, sigma=sigma, own_team_only=own_team_only)
        for s in range(int(weeks))
    ]
    return summarize_weeks(done, seed=seed)


def stable_hash(values: Mapping[str, float], *, nd: int = 9) -> str:
    """Order-independent sha256 of a ``player -> value`` map (a score-vector pin)."""
    blob = json.dumps(
        [[k, round(float(v), nd)] for k, v in sorted(values.items())], separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
