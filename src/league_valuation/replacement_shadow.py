"""Replacement-level SHADOW methodology (IDP accuracy, Lane B).

Authority: ``docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md`` section 7.
Record: ``docs/valuation/idp_accuracy/B_REPLACEMENT.md``.

Shadow only and unwired.  Nothing here is served, flagged, or read by a
route, contract field, engine or page (``tests/league_valuation/test_isolation.py``).
It changes no value, anchor, scoring rule or consumer.  The module imports
nothing from ``src`` outside this package: the one canonical lineup solver
(``src.ros.lineup``) is INJECTED through :class:`LineupPort`, so this file can
never become a second lineup engine and can never drift from its owner.

Replacement is not one number.  Six definitions are kept apart on purpose,
because no single one is valid for every consumer (directive section 7):

``D1``  league-wide starter threshold: what the weakest starter at a position
        produces, measured by the exact solver over every real roster
        (FLEX and SUPER_FLEX compete endogenously).  Starter median and the
        deepest any team dips (the LI-5 ``starter`` / ``bestBallStarter`` pair).
``D2``  best viable free agent (viable = unrostered, healthy, an established
        role, positive production).
``D3``  the production-qualified free-agent pool (viable AND at or above a
        production bar derived from the league's own production starters).
``D4``  the 3rd-best, and the median of the top-k, qualified free agents.
``D5``  dynamic league-wide allocation: each free agent can go to ONE team.
``D6``  team-specific replacement after a hypothetical transaction.

Units never mix: ``ppg`` (league-scored points per game played) and ``board
value`` (``rankDerivedValue``).  MISSING IS NEVER ZERO, in every direction:

* a player the board does not price has NO value (counted, never 0);
* a player with no games has NO ppg and is not a weekly replacement
  (an unrostered prospect with zero production is excluded and counted);
* a missing ``status`` is health UNKNOWN, never healthy;
* a definition with too small a pool is UNDEFINED with a reason, never
  silently falling back to a different definition or to 0.

Whole-roster evaluation only: a package is judged on the before/after roster
through the exact solver, never as a sum of per-player deltas (players compete
for the same slots); the naive sum is published only to expose the
interaction.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

import numpy as np

__all__ = [
    "AVAILABLE",
    "UNCERTAIN",
    "UNAVAILABLE",
    "UNKNOWN",
    "POSITIONS",
    "ALL_POSITIONS",
    "ELIG_SLEEPER",
    "ELIG_NOMINAL",
    "EST_RAW",
    "EST_EB",
    "EbFit",
    "fit_eb",
    "projection_records",
    "board_value_of",
    "total_points",
    "Health",
    "PlayerRecord",
    "LineupPlayer",
    "LineupPort",
    "PoolRule",
    "PoolEntry",
    "PositionPool",
    "Census",
    "Level",
    "WeeklyEngine",
    "StarterThresholds",
    "Allocation",
    "TeamReplacement",
    "ReplacementSpec",
    "PackageResult",
    "load_config",
    "param_set_id_for",
    "classify_health",
    "classify_health_loose",
    "ppg_of",
    "games_in",
    "availability_rate",
    "build_census",
    "starter_thresholds",
    "production_bars",
    "weekly_starter_profile",
    "level_best",
    "level_rank",
    "level_topk_median",
    "level_pool_mean",
    "level_banded_top",
    "compute_level_set",
    "reselection_bootstrap",
    "conditional_level_cis",
    "selection_regression",
    "allocate_free_agents",
    "apply_claims",
    "Claim",
    "team_replacement_after",
    "synthetic_pool_mean",
    "marginal_contributions",
    "evaluate_package",
    "eligibility_uncertainty",
    "assert_public_artifact",
    "percentile_ci",
    "cluster_bootstrap_mean",
]

AVAILABLE = "available"
UNCERTAIN = "uncertain"
UNAVAILABLE = "unavailable"
UNKNOWN = "unknown"

POSITIONS = ("QB", "RB", "WR", "TE", "DL", "LB", "DB")
KICKER = "K"
ALL_POSITIONS = POSITIONS + (KICKER,)

ELIG_SLEEPER = "sleeper_fantasy_positions"
ELIG_NOMINAL = "nominal"

ATTR_SLOT = "slot"
ATTR_NOMINAL = "nominal"

CONFIG_PATH = "config/league_valuation/replacement_shadow_v1.json"
PARAM_SET_NAME = "replacement_shadow_v1"


# ── configuration ────────────────────────────────────────────────────────────


def param_set_id_for(payload: Mapping[str, Any]) -> str:
    """Content hash of a config payload, excluding its own ``paramSetId``."""
    body = {k: v for k, v in payload.items() if k != "paramSetId"}
    blob = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"{PARAM_SET_NAME}:{hashlib.sha256(blob).hexdigest()[:12]}"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load the PRIOR/CONVENTION parameter set and verify its content id."""
    target = Path(path) if path else Path(__file__).resolve().parents[2] / CONFIG_PATH
    payload = json.loads(target.read_text(encoding="utf-8"))
    expected = param_set_id_for(payload)
    if payload.get("paramSetId") != expected:
        raise ValueError(
            f"{target}: paramSetId {payload.get('paramSetId')!r} does not match its "
            f"content ({expected!r}); regenerate it with param_set_id_for()"
        )
    return payload


# ── records ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Health:
    """A health reading.  ``UNKNOWN`` is not healthy and is not injured."""

    state: str
    reason: str

    @property
    def usable(self) -> bool:
        return self.state in (AVAILABLE, UNCERTAIN)


@dataclass(frozen=True)
class PlayerRecord:
    """One player as the replacement shadow sees him.  Public NFL facts only.

    ``weekly`` maps week -> league-scored points for the weeks in which the
    player HAS a stat line.  A week absent from the map is "no game" (bye,
    inactive, injured, not on a roster) -- never a zero score.
    ``board_value`` is ``None`` when the board does not price the player.
    ``team_weeks`` is the set of weeks his NFL team played (``None`` =
    schedule unknown); it separates a bye from a missed game.
    """

    player_id: str
    name: str
    position: str
    fantasy_positions: tuple[str, ...] = ()
    nfl_team: str | None = None
    status: str | None = None
    injury_status: str | None = None
    years_exp: int | None = None
    board_value: float | None = None
    weekly: Mapping[int, float] = field(default_factory=dict)
    team_weeks: frozenset[int] | None = None

    def eligible_positions(self, mode: str = ELIG_SLEEPER) -> tuple[str, ...]:
        """Positions this player may fill.  ``nominal`` is his listed position only."""
        base = [self.position] if self.position else []
        if mode == ELIG_SLEEPER:
            for p in self.fantasy_positions:
                if p and p not in base:
                    base.append(p)
        return tuple(base)


def classify_health(
    *,
    nfl_team: str | None,
    status: str | None,
    injury_status: str | None,
    cfg: Mapping[str, Any],
) -> Health:
    """The STRICT rule (Investigation B ``is_healthy_strict``, made explicit).

    An NFL team, an explicit ``status`` of ``Active``, and no unavailable injury
    designation.  A missing or unrecognised ``status`` is ``UNKNOWN`` -- never
    healthy.  Sleeper publishes no ``injury_status`` for an undesignated active
    player, so an absent injury designation on an explicitly Active player is
    healthy, while an absent ``status`` is not.
    """
    h = cfg["health"]
    if not nfl_team:
        return Health(UNAVAILABLE, "no_nfl_team")
    st = "" if status is None else str(status).strip()
    if not st:
        return Health(UNKNOWN, "status_missing")
    if st != "Active":
        if st in h["unavailableStatuses"]:
            return Health(UNAVAILABLE, f"status_{st}")
        return Health(UNKNOWN, f"status_unrecognised:{st}")
    inj = "" if injury_status is None else str(injury_status).strip()
    if inj in h["unavailableInjury"]:
        return Health(UNAVAILABLE, f"injury_{inj}")
    if inj in h["uncertainInjury"]:
        return Health(UNCERTAIN, f"injury_{inj}")
    if inj == "":
        return Health(AVAILABLE, "active_no_designation")
    return Health(UNKNOWN, f"injury_unrecognised:{inj}")


def classify_health_loose(
    *,
    nfl_team: str | None,
    status: str | None,
    injury_status: str | None,
    cfg: Mapping[str, Any],
) -> Health:
    """Investigation B's SHADOW rule (``IA.is_healthy``), kept ONLY to reproduce it.

    It treats a missing ``status`` as healthy when the player has an NFL team.
    That is the behaviour the strict rule exists to refuse; do not use it for a
    decision.
    """
    h = cfg["health"]
    if not nfl_team:
        return Health(UNAVAILABLE, "no_nfl_team")
    if status in ("Inactive", "Injured Reserve", "Physically Unable to Perform"):
        return Health(UNAVAILABLE, f"status_{status}")
    inj = "" if injury_status is None else str(injury_status).strip()
    if inj in h["unavailableInjury"]:
        return Health(UNAVAILABLE, f"injury_{inj}")
    return Health(AVAILABLE, "loose_rule")


def ppg_of(rec: PlayerRecord, weeks: Iterable[int], *, min_games: int = 1) -> float | None:
    """Mean league-scored points over the games he PLAYED in ``weeks``.

    ``None`` -- not 0 -- when he played fewer than ``min_games`` games.
    """
    vals = [rec.weekly[w] for w in weeks if w in rec.weekly]
    if len(vals) < max(1, int(min_games)):
        return None
    return sum(vals) / len(vals)


def games_in(rec: PlayerRecord, weeks: Iterable[int]) -> int:
    return sum(1 for w in weeks if w in rec.weekly)


def availability_rate(rec: PlayerRecord, weeks: Iterable[int]) -> float | None:
    """Games played / games his team played.  ``None`` when the schedule is unknown."""
    if rec.team_weeks is None:
        return None
    possible = sum(1 for w in weeks if w in rec.team_weeks)
    if possible == 0:
        return None
    return games_in(rec, weeks) / possible


def total_points(rec: PlayerRecord, weeks: Iterable[int]) -> float | None:
    vals = [rec.weekly[w] for w in weeks if w in rec.weekly]
    return sum(vals) if vals else None


# ── expected ppg: empirical-Bayes shrinkage ──────────────────────────────────

GROUP_ROSTERED = "rostered"
GROUP_FREE_AGENT = "free_agent"
EST_RAW = "raw"
EST_EB = "eb"


@dataclass(frozen=True)
class EbFit:
    """Posterior expectation of each player's true points per game.

    Observed season-to-date ppg over three to six games is a noisy estimate, and
    "the best of many noisy estimates" is biased upward (the winner's curse): a
    free agent who has had three big games looks like a better replacement than
    he will be.  The posterior mean shrinks each player toward his group's
    average by the amount the data say is noise.

    One random-effects model per (position, group) with groups ``rostered`` and
    ``free_agent`` (a free-agent pool is a selected, lower-producing population
    and must not be shrunk toward the rostered mean)::

        y_ij ~ N(mu_i, sigma2),   mu_i ~ N(mu, tau2)

    ``sigma2`` is the pooled within-player variance, ``tau2`` the
    method-of-moments between-player variance (floored at 0; ``tau2 == 0``
    means the window cannot tell the group's players apart, so every posterior
    mean is the group mean -- reported, not hidden), and ``mu`` the
    precision-weighted mean.  Nothing is fitted on a board, nothing is tuned.
    """

    mean: Mapping[str, float]
    sd: Mapping[str, float]
    params: Mapping[str, Mapping[str, Any]]


def fit_eb(
    records: Mapping[str, PlayerRecord],
    rostered: Iterable[str],
    weeks: Sequence[int],
    *,
    min_games: int,
    positions: Sequence[str] = ALL_POSITIONS,
) -> EbFit:
    ros = set(rostered)
    groups: dict[tuple[str, str], list[tuple[str, list[float]]]] = defaultdict(list)
    for pid in sorted(records):
        rec = records[pid]
        if rec.position not in positions:
            continue
        ys = [rec.weekly[w] for w in weeks if w in rec.weekly]
        if not ys:
            continue
        groups[(rec.position, GROUP_ROSTERED if pid in ros else GROUP_FREE_AGENT)].append((pid, ys))
    mean: dict[str, float] = {}
    sd: dict[str, float] = {}
    params: dict[str, dict[str, Any]] = {}
    for (pos, grp), rows in sorted(groups.items()):
        ss = sum(sum((y - sum(ys) / len(ys)) ** 2 for y in ys) for _pid, ys in rows if len(ys) >= 2)
        df = sum(len(ys) - 1 for _pid, ys in rows if len(ys) >= 2)
        sigma2 = (ss / df) if df > 0 else None
        fit_rows = [(len(ys), sum(ys) / len(ys)) for _pid, ys in rows if len(ys) >= min_games]
        tag = f"{pos}|{grp}"
        if sigma2 is None or sigma2 <= 0 or len(fit_rows) < 3:
            # not enough information to separate signal from noise: fall back to the raw mean
            params[tag] = {"state": "raw_fallback", "players": len(rows), "sigma2": sigma2}
            for pid, ys in rows:
                mean[pid] = sum(ys) / len(ys)
                if sigma2:
                    sd[pid] = math.sqrt(sigma2 / len(ys))
            continue
        means = np.asarray([m for _n, m in fit_rows], dtype=float)
        ns = np.asarray([n for n, _m in fit_rows], dtype=float)
        s2 = float(np.var(means, ddof=1))
        tau2 = max(0.0, s2 - float(np.mean(sigma2 / ns)))
        w = 1.0 / (tau2 + sigma2 / ns)
        mu = float(np.sum(w * means) / np.sum(w))
        params[tag] = {
            "state": "fitted",
            "players": len(rows),
            "fitPlayers": len(fit_rows),
            "mu": round(mu, 4),
            "sigma2": round(float(sigma2), 4),
            "tau2": round(tau2, 4),
        }
        for pid, ys in rows:
            n = len(ys)
            b = tau2 / (tau2 + sigma2 / n)
            m = mu + b * (sum(ys) / n - mu)
            mean[pid] = m
            sd[pid] = math.sqrt(b * sigma2 / n)
    return EbFit(mean, sd, params)


def projection_records(
    records: Mapping[str, PlayerRecord], expected: Mapping[str, float], *, week: int = 1
) -> dict[str, PlayerRecord]:
    """One pseudo-week of EXPECTED ppg per player (the projected-roster engine's
    input).  A player with no expectation has an empty ``weekly`` and so is not a
    candidate -- unknown, never zero."""
    return {
        pid: replace(
            rec, weekly=({week: float(expected[pid])} if pid in expected else {}), team_weeks=None
        )
        for pid, rec in records.items()
    }


# ── lineup port (the ONE solver is injected) ─────────────────────────────────


@dataclass(frozen=True)
class LineupPlayer:
    player_id: str
    position: str
    fantasy_positions: tuple[str, ...]
    points: float


class LineupPort(Protocol):
    """The canonical lineup owner, as this module is allowed to see it.

    ``solve`` must be the EXACT maximum-weight assignment on the points given
    (``src.ros.lineup.solve_optimal_assignment`` under the realized-points
    objective); a greedy or heuristic port would silently change every number
    here.  It returns ``{slot_index: player_id}``.  ``slot_family`` normalises a
    slot name (the owner's ``normalize_slot``).
    """

    def solve(self, players: Sequence[LineupPlayer], slots: Sequence[str]) -> Mapping[int, str]: ...

    def slot_family(self, slot: str) -> str: ...


def _lineup_player(rec: PlayerRecord, points: float, mode: str) -> LineupPlayer:
    fps = rec.fantasy_positions if mode == ELIG_SLEEPER else ()
    return LineupPlayer(rec.player_id, rec.position, tuple(fps), float(points))


def _attribute(port: LineupPort, slot: str, rec: PlayerRecord) -> str:
    """The position a started player is counted at: his slot's family for a
    dedicated slot, his own position inside a shared flex slot."""
    fam = port.slot_family(slot)
    if fam in ALL_POSITIONS:
        return fam
    return rec.position or "UNK"


@dataclass(frozen=True)
class WeekSolution:
    score: float
    starters: Mapping[int, str]


class WeeklyEngine:
    """Best-ball weekly scoring of a roster through the injected exact solver.

    Two modes, both explicit:

    * ``zero_fill_rostered=True`` (REALISED weeks, the host's rule): a rostered
      player with no stat line that week did not play and scores 0.0, and the
      host may start him -- which matters only when every alternative scored
      below zero.  Sleeper's own awarded lineup does exactly this (measured: a
      team-week where it started two non-players rather than a -2.9 fumbler).
      This is a fact about a played week, not an imputation of missing data; it
      is never applied to a projection.
    * ``zero_fill_rostered=False`` (PROJECTIONS, one pseudo-week of expected
      ppg): a player with no projection is UNKNOWN and simply not a candidate.

    A slot nobody can fill scores nothing.  Solutions are memoised by
    ``(roster, week)``.
    """

    def __init__(
        self,
        records: Mapping[str, PlayerRecord],
        port: LineupPort,
        slots: Sequence[str],
        weeks: Sequence[int],
        *,
        eligibility: str = ELIG_SLEEPER,
        zero_fill_rostered: bool = True,
    ) -> None:
        self.records = records
        self.port = port
        self.slots = tuple(slots)
        self.weeks = tuple(weeks)
        self.eligibility = eligibility
        self.zero_fill_rostered = zero_fill_rostered
        self._cache: dict[tuple[tuple[str, ...], int], WeekSolution] = {}

    def extended(self, extra: Mapping[str, PlayerRecord]) -> WeeklyEngine:
        merged = dict(self.records)
        merged.update(extra)
        return WeeklyEngine(
            merged,
            self.port,
            self.slots,
            self.weeks,
            eligibility=self.eligibility,
            zero_fill_rostered=self.zero_fill_rostered,
        )

    def has_line(self, pid: str, week: int) -> bool:
        rec = self.records.get(pid)
        return rec is not None and week in rec.weekly

    def solve(self, roster: Iterable[str], week: int) -> WeekSolution:
        key = (tuple(sorted(set(roster))), week)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        players: list[LineupPlayer] = []
        for pid in key[0]:
            rec = self.records.get(pid)
            if rec is None:
                continue
            if week in rec.weekly:
                players.append(_lineup_player(rec, rec.weekly[week], self.eligibility))
            elif self.zero_fill_rostered:
                players.append(_lineup_player(rec, 0.0, self.eligibility))
        assignment = self.port.solve(players, self.slots) if players else {}
        pts = {p.player_id: p.points for p in players}
        score = 0.0
        for idx in sorted(assignment):
            score += pts[assignment[idx]]
        sol = WeekSolution(score=score, starters=dict(assignment))
        if len(self._cache) > 300_000:
            self._cache.clear()
        self._cache[key] = sol
        return sol

    def score(self, roster: Iterable[str], weeks: Iterable[int] | None = None) -> float:
        ids = tuple(roster)
        return sum(self.solve(ids, w).score for w in (self.weeks if weeks is None else weeks))

    def per_week(self, roster: Iterable[str], weeks: Iterable[int] | None = None) -> list[float]:
        ids = tuple(roster)
        return [self.solve(ids, w).score for w in (self.weeks if weeks is None else weeks)]

    def starter_weeks(
        self, roster: Iterable[str], weeks: Iterable[int] | None = None
    ) -> dict[str, list[int]]:
        """player -> weeks in which he is in the optimal lineup WITH a stat line.

        A non-player the host zero-fills into a slot is not a starter here: he
        scores 0.0 and dropping him changes nothing.
        """
        ids = tuple(roster)
        out: dict[str, list[int]] = defaultdict(list)
        for w in self.weeks if weeks is None else weeks:
            for pid in self.solve(ids, w).starters.values():
                if self.has_line(pid, w):
                    out[pid].append(w)
        return out


# ── population: who is a free agent we could count ───────────────────────────


@dataclass(frozen=True)
class PoolRule:
    """How pools are keyed and who they admit.

    The default is the NEW definition.  :meth:`legacy_b` reproduces
    Investigation B: pools keyed by LISTED position, B's health rule, no
    games/production requirement for membership, but ``ppg`` is still ``None``
    below the minimum games (B's ``ppg()`` demanded 3).  Pool keying
    (``eligibility``) and the solver's slot eligibility (``lineup_eligibility``)
    are separate on purpose: B keyed pools nominally while its lineups used
    Sleeper's ``fantasy_positions``.
    """

    eligibility: str = ELIG_SLEEPER
    lineup_eligibility: str = ELIG_SLEEPER
    attribution: str = ATTR_SLOT
    health: str = "strict"  # strict | loose | none
    include_uncertain: bool = True
    require_min_games: bool = True
    require_positive_ppg: bool = True
    #: Production-optimal lineups (total points) may start a rostered player with
    #: no games at 0.0 -- Investigation B did (``sum({}) == 0.0``), the new rule
    #: leaves him out (production unknown is not a score).
    lineup_zero_fill: bool = False

    @classmethod
    def legacy_b(cls, *, health: str = "loose") -> PoolRule:
        return cls(
            eligibility=ELIG_NOMINAL,
            lineup_eligibility=ELIG_SLEEPER,
            attribution=ATTR_NOMINAL,
            health=health,
            include_uncertain=True,
            require_min_games=False,
            require_positive_ppg=False,
            lineup_zero_fill=True,
        )

    @classmethod
    def nominal_only(cls) -> PoolRule:
        """Hybrids may fill only their listed position (the eligibility-uncertainty comparison)."""
        return cls(eligibility=ELIG_NOMINAL, lineup_eligibility=ELIG_NOMINAL)


@dataclass(frozen=True)
class PoolEntry:
    rec: PlayerRecord
    ppg: float | None  # None below the minimum games: production is unestablished, not 0
    games: int
    availability: float | None
    health: Health

    @property
    def value(self) -> float | None:
        return self.rec.board_value

    @property
    def player_id(self) -> str:
        return self.rec.player_id

    @property
    def name(self) -> str:
        return self.rec.name


@dataclass
class PositionPool:
    position: str
    entries: list[PoolEntry] = field(default_factory=list)
    candidates: int = 0
    excluded: Counter = field(default_factory=Counter)

    def by_ppg(self) -> list[PoolEntry]:
        """Production order.  Entries with no ppg are not ordered (never 0)."""
        return sorted(
            (e for e in self.entries if e.ppg is not None), key=lambda e: (-e.ppg, e.player_id)
        )

    def by_value(self) -> list[PoolEntry]:
        """Board-value order over PRICED entries only; unpriced are counted, not zeroed."""
        return sorted(
            (e for e in self.entries if e.value is not None), key=lambda e: (-e.value, e.player_id)
        )

    @property
    def unpriced(self) -> int:
        return sum(1 for e in self.entries if e.value is None)

    def qualified(self, bar: float | None) -> list[PoolEntry]:
        """Entries at or above a production bar.  No bar => none qualifies (undefined)."""
        if bar is None:
            return []
        return [e for e in self.by_ppg() if e.ppg >= bar]


@dataclass
class Census:
    pools: dict[str, PositionPool]
    rule: PoolRule
    weeks: tuple[int, ...]
    unrostered_considered: int = 0

    def pool(self, position: str) -> PositionPool:
        return self.pools[position]


def _health_for(rec: PlayerRecord, rule: PoolRule, cfg: Mapping[str, Any]) -> Health:
    if rule.health == "none":
        return Health(AVAILABLE, "health_not_applied")
    fn = classify_health_loose if rule.health == "loose" else classify_health
    return fn(nfl_team=rec.nfl_team, status=rec.status, injury_status=rec.injury_status, cfg=cfg)


def build_census(
    records: Mapping[str, PlayerRecord],
    rostered: Iterable[str],
    *,
    weeks: Sequence[int],
    cfg: Mapping[str, Any],
    rule: PoolRule | None = None,
    positions: Sequence[str] = ALL_POSITIONS,
    ppg_fn: Callable[[PlayerRecord], float | None] | None = None,
) -> Census:
    """Unrostered players grouped into per-position pools, with every exclusion counted.

    Exclusion categories are mutually exclusive and ordered (first failing
    wins): ``health_unavailable``, ``health_unknown``, ``health_uncertain``
    (only when ``include_uncertain`` is off), ``no_games`` (production unknown --
    a prospect with no stat line), ``below_min_games`` (role not established),
    ``zero_production`` (played enough, produced nothing positive: decided on
    OBSERVED points, never on a shrunk estimate).

    ``ppg_fn`` is the estimator an entry carries as ``ppg`` (raw season-to-date
    by default; the empirical-Bayes expectation when the caller supplies it).
    """
    rule = rule or PoolRule()
    taken = set(rostered)
    min_games = int(cfg["window"]["minGames"]["value"])
    pools = {p: PositionPool(p) for p in positions}
    considered = 0
    for pid in sorted(records):
        rec = records[pid]
        if pid in taken:
            continue
        elig = [p for p in rec.eligible_positions(rule.eligibility) if p in pools]
        if not elig:
            continue
        considered += 1
        health = _health_for(rec, rule, cfg)
        games = games_in(rec, weeks)
        observed = ppg_of(rec, weeks, min_games=min_games)
        mean = ppg_fn(rec) if ppg_fn is not None else observed
        avail = availability_rate(rec, weeks)
        for p in elig:
            pool = pools[p]
            pool.candidates += 1
            if health.state == UNAVAILABLE:
                pool.excluded["health_unavailable"] += 1
                continue
            if health.state == UNKNOWN:
                pool.excluded["health_unknown"] += 1
                continue
            if health.state == UNCERTAIN and not rule.include_uncertain:
                pool.excluded["health_uncertain"] += 1
                continue
            if rule.require_min_games:
                if games == 0:
                    pool.excluded["no_games"] += 1
                    continue
                if games < min_games:
                    pool.excluded["below_min_games"] += 1
                    continue
            if rule.require_positive_ppg and (observed is None or observed <= 0):
                pool.excluded["zero_production"] += 1
                continue
            pool.entries.append(PoolEntry(rec, mean, games, avail, health))
    return Census(pools=pools, rule=rule, weeks=tuple(weeks), unrostered_considered=considered)


# ── levels ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Level:
    """One replacement level.  ``value is None`` means UNDEFINED, with ``reason``.

    ``ids`` are the players whose own numbers set the level and ``kind`` how they
    combine (``single`` / ``mean`` / ``median``): enough to recompute the level
    from resampled games of exactly those players (the conditional interval).
    """

    value: float | None
    n: int
    reason: str | None = None
    set_by: tuple[str, ...] = ()
    ids: tuple[str, ...] = ()
    kind: str = "single"

    def as_dict(self, nd: int = 3) -> dict[str, Any]:
        return {
            "value": None if self.value is None else round(self.value, nd),
            "n": self.n,
            "reason": self.reason,
            "setBy": list(self.set_by),
        }


def _undefined(n: int, reason: str) -> Level:
    return Level(None, n, reason, ())


def _key(unit: str) -> Callable[[PoolEntry], float | None]:
    if unit == "ppg":
        return lambda e: e.ppg
    if unit == "value":
        return lambda e: e.value
    raise ValueError(f"unknown unit {unit!r}")


def _ordered(entries: Sequence[PoolEntry], unit: str) -> list[PoolEntry]:
    f = _key(unit)
    rows = [e for e in entries if f(e) is not None]
    return sorted(rows, key=lambda e: (-f(e), e.player_id))


def level_best(entries: Sequence[PoolEntry], unit: str) -> Level:
    """The single best entry in ``unit`` (rank 1)."""
    return level_rank(entries, unit, 1)


def level_rank(entries: Sequence[PoolEntry], unit: str, rank: int) -> Level:
    """The ``rank``-th best entry in ``unit``.  Fewer than ``rank`` => UNDEFINED."""
    rows = _ordered(entries, unit)
    if len(rows) < rank:
        return _undefined(len(rows), f"pool_smaller_than_rank_{rank}")
    e = rows[rank - 1]
    return Level(float(_key(unit)(e)), len(rows), None, (e.name,), (e.player_id,), "single")


def level_topk_median(entries: Sequence[PoolEntry], unit: str, k: int) -> Level:
    """Median of the ``k`` best entries.  Fewer than ``k`` => UNDEFINED (no padding)."""
    rows = _ordered(entries, unit)
    if len(rows) < k:
        return _undefined(len(rows), f"pool_smaller_than_k_{k}")
    top = rows[:k]
    f = _key(unit)
    return Level(
        float(statistics.median(f(e) for e in top)),
        len(rows),
        None,
        tuple(e.name for e in top),
        tuple(e.player_id for e in top),
        "median",
    )


def level_pool_mean(entries: Sequence[PoolEntry], unit: str) -> Level:
    """Mean over the whole pool (D3).  An empty pool => UNDEFINED."""
    rows = _ordered(entries, unit)
    if not rows:
        return _undefined(0, "empty_pool")
    f = _key(unit)
    return Level(
        float(statistics.fmean(f(e) for e in rows)),
        len(rows),
        None,
        (),
        tuple(e.player_id for e in rows),
        "mean",
    )


def level_banded_top(entries: Sequence[PoolEntry], unit: str, band: int = 2) -> Level:
    """LI-5's waiver tier: mean of ranks 1..1+band, using what exists (a pool of
    one or two uses what exists and ``n`` says how many).  Empty => UNDEFINED."""
    rows = _ordered(entries, unit)
    if not rows:
        return _undefined(0, "empty_pool")
    f = _key(unit)
    window = rows[: 1 + band]
    return Level(
        float(statistics.fmean(f(e) for e in window)),
        len(rows),
        None,
        tuple(e.name for e in window),
        tuple(e.player_id for e in window),
        "mean",
    )


# ── D1: league-wide starter threshold ────────────────────────────────────────


@dataclass
class PositionThreshold:
    position: str
    starters: list[float] = field(default_factory=list)  # every started value, all teams
    marginals: list[float] = field(default_factory=list)  # each team's weakest started value
    starter_ids: list[str] = field(default_factory=list)  # who the started values belong to
    marginal_ids: list[str] = field(default_factory=list)  # who each team's weakest starter is
    teams_starting: int = 0

    def starter_mean(self) -> float | None:
        return statistics.fmean(self.starters) if self.starters else None

    def starter_median(self) -> float | None:
        return statistics.median(self.starters) if self.starters else None

    def median_marginal(self) -> float | None:
        return statistics.median(self.marginals) if self.marginals else None

    def floor(self, band: int) -> float | None:
        """The deepest anyone dips: mean of the lowest ``band`` team marginals."""
        if not self.marginals:
            return None
        low = sorted(self.marginals)[: max(1, band)]
        return statistics.fmean(low)

    def min_marginal(self) -> float | None:
        return min(self.marginals) if self.marginals else None


@dataclass
class StarterThresholds:
    by_position: dict[str, PositionThreshold]
    team_count: int
    slot_fill: dict[str, Counter]
    starters_by_team: dict[str, list[tuple[str, str, float]]]  # team -> (pid, position, value)

    def starters_per_team(self, position: str) -> float:
        t = self.by_position.get(position)
        return (len(t.starters) / self.team_count) if t and self.team_count else 0.0


def starter_thresholds(
    teams: Mapping[str, Sequence[str]],
    records: Mapping[str, PlayerRecord],
    port: LineupPort,
    slots: Sequence[str],
    *,
    value_of: Callable[[PlayerRecord], float | None],
    attribution: str = ATTR_SLOT,
    eligibility: str = ELIG_SLEEPER,
) -> StarterThresholds:
    """D1.  Run the exact solver on every real roster and read who started.

    ``value_of`` is the objective: season-to-date ppg (D1 in ppg), total points
    (the production-optimal lineups behind the qualification bar), or board
    value.  A player it returns ``None`` for is not a candidate (UNKNOWN is not
    assignable and is not a zero).

    ``attribution='slot'`` counts a started player at the position of the slot
    he fills (a DL/LB hybrid in a DL slot is a DL starter), which is the truth
    about demand; ``'nominal'`` counts him at his listed position, which is what
    LI-5 does (``src.league_intel.replacement``) and is kept for parity.  FLEX
    and SUPER_FLEX occupants are always counted at their own position, so
    flex competition is measured, not preassigned.
    """
    by_pos: dict[str, PositionThreshold] = {}
    slot_fill: dict[str, Counter] = defaultdict(Counter)
    starters_by_team: dict[str, list[tuple[str, str, float]]] = {}
    n_teams = 0
    for team in sorted(teams):
        lps: list[LineupPlayer] = []
        vals: dict[str, float] = {}
        for pid in teams[team]:
            rec = records.get(pid)
            if rec is None:
                continue
            v = value_of(rec)
            if v is None:
                continue
            vals[pid] = float(v)
            lps.append(_lineup_player(rec, float(v), eligibility))
        if not lps:
            continue
        n_teams += 1
        assignment = port.solve(lps, slots)
        per_pos: dict[str, list[tuple[float, str]]] = defaultdict(list)
        started: list[tuple[str, str, float]] = []
        for idx in sorted(assignment):
            pid = assignment[idx]
            rec = records[pid]
            pos = (
                _attribute(port, slots[idx], rec)
                if attribution == ATTR_SLOT
                else (rec.position or "UNK")
            )
            per_pos[pos].append((vals[pid], pid))
            slot_fill[port.slot_family(slots[idx])][pos] += 1
            started.append((pid, pos, vals[pid]))
        starters_by_team[team] = started
        for pos, vp in per_pos.items():
            t = by_pos.setdefault(pos, PositionThreshold(pos))
            t.starters.extend(v for v, _p in vp)
            t.starter_ids.extend(p for _v, p in vp)
            lo = min(vp)
            t.marginals.append(lo[0])
            t.marginal_ids.append(lo[1])
            t.teams_starting += 1
    return StarterThresholds(by_pos, n_teams, dict(slot_fill), starters_by_team)


def production_bars(
    thresholds_total: StarterThresholds,
    records: Mapping[str, PlayerRecord],
    weeks: Sequence[int],
    percentile: float,
    *,
    ppg_fn: Callable[[PlayerRecord], float | None] | None = None,
) -> dict[str, float | None]:
    """The production bar per position: the ``percentile`` of the ppg of the
    players the league's PRODUCTION-optimal lineups (objective: total points)
    start at the position.  Investigation B's A4 bar at ``percentile=10`` with
    the raw estimator.

    ``None`` when a position has no production starter (a bar nobody can be
    measured against is undefined, not 0).
    """
    f = ppg_fn or (lambda rec: ppg_of(rec, weeks))
    out: dict[str, float | None] = {}
    for pos in thresholds_total.by_position:
        vals = [
            f(records[pid])
            for team in thresholds_total.starters_by_team.values()
            for pid, p, _v in team
            if p == pos
        ]
        vals = [v for v in vals if v is not None]
        out[pos] = float(np.percentile(vals, percentile)) if vals else None
    return out


def weekly_starter_profile(
    teams: Mapping[str, Sequence[str]],
    engine: WeeklyEngine,
    *,
    weeks: Sequence[int] | None = None,
) -> dict[str, Any]:
    """What the league actually starts, week by week, from the realised points.

    A season-long mean erases weekly spikes, so LI-5's own docstring warns its
    mean-based flex allocation understates flex demand at high-variance
    positions.  This reads the real weekly lineups: per position, how many
    slots it filled per team-week (dedicated + flex), its share of the FLEX and
    SUPER_FLEX slots, and the points of the weakest started player at the
    position in each team-week it started anyone.
    """
    wk = tuple(engine.weeks if weeks is None else weeks)
    flex_slots = Counter()
    flex_total = 0
    per_pos_slots: dict[str, int] = defaultdict(int)
    marginals: dict[str, list[float]] = defaultdict(list)
    team_weeks = 0
    zero_filled = 0
    zero_by_slot: Counter = Counter()
    for t in sorted(teams):
        for w in wk:
            sol = engine.solve(teams[t], w)
            if not sol.starters:
                continue
            team_weeks += 1
            pts: dict[str, list[float]] = defaultdict(list)
            filled = set(sol.starters)
            for idx in range(len(engine.slots)):
                if idx not in filled:
                    zero_by_slot[engine.port.slot_family(engine.slots[idx])] += (
                        1  # nobody could fill it
                    )
            for idx, pid in sol.starters.items():
                if not engine.has_line(pid, w):
                    zero_filled += 1  # the host started a non-player at 0.0; not a started player
                    zero_by_slot[engine.port.slot_family(engine.slots[idx])] += 1
                    continue
                rec = engine.records[pid]
                pos = _attribute(engine.port, engine.slots[idx], rec)
                pts[pos].append(rec.weekly[w])
                per_pos_slots[pos] += 1
                if engine.port.slot_family(engine.slots[idx]) not in ALL_POSITIONS:
                    flex_slots[pos] += 1
                    flex_total += 1
            for pos, vs in pts.items():
                marginals[pos].append(min(vs))
    return {
        "teamWeeks": team_weeks,
        "zeroFilledSlots": zero_filled,
        "slotsScoringNothingBecauseNoPlayerByFamily": dict(sorted(zero_by_slot.items())),
        "startersPerTeamWeek": {
            p: round(n / team_weeks, 3) for p, n in sorted(per_pos_slots.items())
        }
        if team_weeks
        else {},
        "flexShare": {p: round(n / flex_total, 3) for p, n in sorted(flex_slots.items())}
        if flex_total
        else {},
        "weeklyMarginalStarterMeanPoints": {
            p: round(statistics.fmean(v), 3) for p, v in sorted(marginals.items()) if v
        },
        "weeklyMarginalStarterN": {p: len(v) for p, v in sorted(marginals.items())},
    }


# ── level set (everything bootstrapped together) ─────────────────────────────


def _ppg_value_of(weeks: Sequence[int], min_games: int) -> Callable[[PlayerRecord], float | None]:
    return lambda rec: ppg_of(rec, weeks, min_games=min_games)


def _total_value_of(
    weeks: Sequence[int], min_games: int, *, zero_fill: bool = False
) -> Callable[[PlayerRecord], float | None]:
    def f(rec: PlayerRecord) -> float | None:
        n = games_in(rec, weeks)
        if n == 0 and zero_fill:
            return 0.0
        return total_points(rec, weeks) if n >= min_games else None

    return f


def board_value_of(rec: PlayerRecord) -> float | None:
    """The board value, or ``None`` (UNPRICED) -- never 0."""
    return rec.board_value if rec.board_value and rec.board_value > 0 else None


def compute_level_set(
    records: Mapping[str, PlayerRecord],
    teams: Mapping[str, Sequence[str]],
    port: LineupPort,
    slots: Sequence[str],
    *,
    weeks: Sequence[int],
    cfg: Mapping[str, Any],
    rule: PoolRule | None = None,
    bar_percentile: float | None = None,
    positions: Sequence[str] = ALL_POSITIONS,
    value_thresholds: StarterThresholds | None = None,
    estimator: str = EST_RAW,
    detail: bool = False,
) -> Any:
    """D1-D4 for every position, in both units, from one consistent pass.

    Returns ``{position: {metric: float | None}}`` -- every metric a number or
    ``None`` (UNDEFINED), never 0 -- or ``(flat, detail, aux)`` with ``detail =
    {position: {metric: Level}}`` (pool sizes, reasons, who sets each level)
    and ``aux`` (the thresholds, bars and census behind them) when
    ``detail=True``.  Pure and deterministic, which is what lets
    :func:`bootstrap_level_set` recompute it on resampled games.

    Metrics (``Ppg`` / ``Value`` suffixes are the two units): ``starterMean``,
    ``starterMedian``, ``d1_medianMarginal``, ``d1_bestBallFloor``,
    ``d2_best``, ``d2_rank<r>``, ``d2_bandedTop``, ``d3_poolMean``,
    ``d4_rank<r>``, ``d4_top<k>Median``, ``productionBarPpg``, pool sizes, and
    ``gap_*`` (median production starter minus each ppg level).
    """
    rule = rule or PoolRule()
    min_games = int(cfg["window"]["minGames"]["value"])
    lv = cfg["levels"]
    rank = int(lv["rank"]["value"])
    k = int(lv["topK"]["value"])
    band = int(lv["band"]["value"])
    pct = float(
        bar_percentile
        if bar_percentile is not None
        else cfg["qualification"]["primary"]["percentile"]
    )
    lineup_min = min_games if rule.require_min_games else 1
    rostered = {pid for team in teams.values() for pid in team}

    if estimator == EST_EB:
        eb = fit_eb(records, rostered, weeks, min_games=min_games)

        def ppg_fn(rec: PlayerRecord) -> float | None:
            return eb.mean.get(rec.player_id) if games_in(rec, weeks) >= min_games else None

    elif estimator == EST_RAW:
        ppg_fn = _ppg_value_of(weeks, min_games)
    else:
        raise ValueError(f"unknown estimator {estimator!r}")

    th_ppg = starter_thresholds(
        teams,
        records,
        port,
        slots,
        value_of=ppg_fn,
        attribution=rule.attribution,
        eligibility=rule.lineup_eligibility,
    )
    th_total = starter_thresholds(
        teams,
        records,
        port,
        slots,
        value_of=_total_value_of(weeks, lineup_min, zero_fill=rule.lineup_zero_fill),
        attribution=rule.attribution,
        eligibility=rule.lineup_eligibility,
    )
    th_val = value_thresholds or starter_thresholds(
        teams,
        records,
        port,
        slots,
        value_of=board_value_of,
        attribution=rule.attribution,
        eligibility=rule.lineup_eligibility,
    )
    bars = production_bars(th_total, records, weeks, pct, ppg_fn=ppg_fn)
    census = build_census(
        records, rostered, weeks=weeks, cfg=cfg, rule=rule, positions=positions, ppg_fn=ppg_fn
    )

    flat: dict[str, dict[str, Any]] = {}
    det: dict[str, dict[str, Level]] = {}
    for p in positions:
        pool = census.pool(p)
        qual = pool.qualified(bars.get(p))
        t = th_ppg.by_position.get(p)
        tv = th_val.by_position.get(p)
        m: dict[str, Any] = {
            "starterMeanPpg": t.starter_mean() if t else None,
            "starterMedianPpg": t.starter_median() if t else None,
            "d1_medianMarginalPpg": t.median_marginal() if t else None,
            "d1_bestBallFloorPpg": t.floor(band) if t else None,
            "d1_medianMarginalValue": tv.median_marginal() if tv else None,
            "d1_bestBallFloorValue": tv.floor(band) if tv else None,
            "productionBarPpg": bars.get(p),
            "viableN": len(pool.entries),
            "qualifiedN": len(qual),
            "candidatesN": pool.candidates,
            "unpricedViableN": pool.unpriced,
        }
        d: dict[str, Level] = {}
        for unit, tag in (("ppg", "Ppg"), ("value", "Value")):
            d[f"d2_best{tag}"] = level_best(pool.entries, unit)
            d[f"d2_rank{rank}{tag}"] = level_rank(pool.entries, unit, rank)
            d[f"d2_bandedTop{tag}"] = level_banded_top(pool.entries, unit, band)
            d[f"d3_poolMean{tag}"] = level_pool_mean(qual, unit)
            d[f"d3_bestQualified{tag}"] = level_best(qual, unit)
            d[f"d4_rank{rank}{tag}"] = level_rank(qual, unit, rank)
            d[f"d4_top{k}Median{tag}"] = level_topk_median(qual, unit, k)
        for name, lvl in d.items():
            m[name] = lvl.value
        sm = m["starterMedianPpg"]
        for key in (
            "d1_medianMarginalPpg",
            "d1_bestBallFloorPpg",
            "d2_bestPpg",
            f"d2_rank{rank}Ppg",
            "d3_poolMeanPpg",
            f"d4_rank{rank}Ppg",
            f"d4_top{k}MedianPpg",
        ):
            lvl_v = m[key]
            m[f"gap_{key}"] = (sm - lvl_v) if (sm is not None and lvl_v is not None) else None
        flat[p] = m
        det[p] = d
    if detail:
        return flat, det, {"th_ppg": th_ppg, "bars": bars, "census": census, "band": band}
    return flat


def percentile_ci(values: Sequence[float | None], level: float = 0.95) -> dict[str, Any]:
    """Percentile interval over the DEFINED replicates; undefined ones are
    reported as ``definedShare`` and never counted as 0."""
    xs = [
        float(v) for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))
    ]
    total = len(values)
    if len(xs) < 20:
        return {
            "ci95": None,
            "definedShare": round(len(xs) / total, 3) if total else 0.0,
            "reps": len(xs),
        }
    a = (1.0 - level) / 2.0 * 100.0
    lo, hi = np.percentile(xs, [a, 100.0 - a])
    return {
        "ci95": [round(float(lo), 3), round(float(hi), 3)],
        "definedShare": round(len(xs) / total, 3),
        "reps": len(xs),
    }


def cluster_bootstrap_mean(
    values: Sequence[float | None], *, replicates: int, seed: int, level: float = 0.95
) -> dict[str, Any]:
    """Mean of the DEFINED cluster values with a percentile interval from
    resampling clusters (teams or players), conditional on the realised estimates."""
    xs = np.asarray([float(v) for v in values if v is not None], dtype=float)
    n = int(xs.size)
    if n == 0:
        return {"mean": None, "n": 0, "ci95": None}
    rng = np.random.default_rng(seed)
    means = [float(xs[rng.integers(0, n, n)].mean()) for _ in range(replicates)]
    a = (1.0 - level) / 2.0 * 100.0
    lo, hi = np.percentile(means, [a, 100.0 - a])
    return {
        "mean": round(float(xs.mean()), 3),
        "n": n,
        "ci95": [round(float(lo), 3), round(float(hi), 3)] if n >= 3 else None,
    }


def _resample_games(
    records: Mapping[str, PlayerRecord], rng: np.random.Generator
) -> dict[str, PlayerRecord]:
    """Resample each player's OWN played weeks with replacement (game-level noise)."""
    out: dict[str, PlayerRecord] = {}
    for pid in sorted(records):
        rec = records[pid]
        wk = sorted(rec.weekly)
        if len(wk) <= 1:
            out[pid] = rec
            continue
        draw = rng.integers(0, len(wk), len(wk))
        out[pid] = replace(rec, weekly={w: rec.weekly[wk[i]] for w, i in zip(wk, draw)})
    return out


def _jaccard(a: Sequence[str], b: Sequence[str]) -> float:
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb) if (sa or sb) else 1.0


def reselection_bootstrap(
    records: Mapping[str, PlayerRecord],
    teams: Mapping[str, Sequence[str]],
    port: LineupPort,
    slots: Sequence[str],
    *,
    weeks: Sequence[int],
    cfg: Mapping[str, Any],
    rule: PoolRule | None = None,
    replicates: int | None = None,
    seed: int | None = None,
    positions: Sequence[str] = ALL_POSITIONS,
    estimator: str = EST_RAW,
) -> dict[str, dict[str, Any]]:
    """How stable is the definition itself?  Full-procedure game-level bootstrap.

    Each replicate resamples every player's own played weeks with replacement
    and recomputes the WHOLE definition set (thresholds, production bars, pools,
    levels).  This is NOT a confidence interval, and the output says so:
    "best of a noisy pool" and "the lineup optimiser's starters" are maxima, and
    a maximum of resampled noisy values is biased UPWARD, so the replicate
    distribution sits above the observed point (``meanMinusPoint`` is that
    inflation, the winner's curse made visible).  What it measures well is
    SELECTION STABILITY: how often the same player (or set) sets the level
    again (``sameChoiceShare``, ``meanJaccard``).  The interval to quote is
    :func:`conditional_level_cis`.
    """
    rule = rule or PoolRule()
    b = int(replicates if replicates is not None else cfg["bootstrap"]["replicates"]["value"])
    s = int(seed if seed is not None else cfg["bootstrap"]["seed"])
    rng = np.random.default_rng(s)
    th_val = starter_thresholds(
        teams,
        records,
        port,
        slots,
        value_of=board_value_of,
        attribution=rule.attribution,
        eligibility=rule.lineup_eligibility,
    )
    kw = dict(
        weeks=weeks,
        cfg=cfg,
        rule=rule,
        positions=positions,
        value_thresholds=th_val,
        estimator=estimator,
    )
    point, point_det, _aux = compute_level_set(records, teams, port, slots, detail=True, **kw)
    draws: dict[str, dict[str, list[Any]]] = {p: defaultdict(list) for p in positions}
    ids: dict[str, dict[str, list[tuple[str, ...]]]] = {p: defaultdict(list) for p in positions}
    for _ in range(b):
        resampled = _resample_games(records, rng)
        ls, ld, _a = compute_level_set(resampled, teams, port, slots, detail=True, **kw)
        for p in positions:
            for metric, val in ls[p].items():
                draws[p][metric].append(val)
            for name, lvl in ld[p].items():
                ids[p][name].append(lvl.ids)
    out: dict[str, dict[str, Any]] = {}
    for p in positions:
        out[p] = {}
        for metric, val in point[p].items():
            defined = [float(v) for v in draws[p][metric] if v is not None]
            cell: dict[str, Any] = {
                "point": None if val is None else round(float(val), 3),
                "definedShare": round(len(defined) / b, 3) if b else None,
                "reps": len(defined),
            }
            if defined and val is not None:
                q05, q50, q95 = np.percentile(defined, [5, 50, 95])
                cell["reselection"] = {
                    "p05": round(float(q05), 3),
                    "p50": round(float(q50), 3),
                    "p95": round(float(q95), 3),
                    "meanMinusPoint": round(float(np.mean(defined)) - float(val), 3),
                }
            lvl = point_det[p].get(metric)
            if lvl is not None and lvl.ids:
                same = sum(1 for x in ids[p][metric] if x == lvl.ids)
                cell["identityStability"] = {
                    "sameChoiceShare": round(same / b, 3),
                    "meanJaccard": round(
                        float(np.mean([_jaccard(x, lvl.ids) for x in ids[p][metric]])), 3
                    ),
                }
            out[p][metric] = cell
    return out


def _stat_of(kind: str, vals: Sequence[float]) -> float | None:
    if not vals:
        return None
    if kind == "single":
        return float(vals[0])
    if kind == "mean":
        return float(statistics.fmean(vals))
    if kind == "median":
        return float(statistics.median(vals))
    raise ValueError(kind)


def conditional_level_cis(
    records: Mapping[str, PlayerRecord],
    det: Mapping[str, Mapping[str, Level]],
    aux: Mapping[str, Any],
    *,
    weeks: Sequence[int],
    cfg: Mapping[str, Any],
    replicates: int | None = None,
    seed: int | None = None,
    positions: Sequence[str] = ALL_POSITIONS,
) -> dict[str, dict[str, Any]]:
    """The interval to quote: sampling noise of the players who set each level.

    CONDITIONAL on the identities the definition selected: each replicate
    resamples the played weeks (with replacement) of exactly the players behind a
    number -- the level-setting free agents, the league's starters at the
    position -- and teams are resampled as clusters for the league-wide
    thresholds.  Every replicate recomputes the level from those fixed players,
    so the point lies inside its interval and the gaps (median starter minus a
    level) are paired within a replicate.

    What it does NOT include is the selection itself.  A free agent was chosen
    BECAUSE his noisy ppg was high, so his true mean is on average lower than
    his observed ppg; that regression is measured separately
    (:func:`selection_regression`) and should be read beside every free-agent
    level.  Board-value levels have no game noise (a value is an observation,
    not an estimate) and get no interval here; what is uncertain about them is
    WHICH player sets them (see :func:`reselection_bootstrap`).
    """
    b = int(replicates if replicates is not None else cfg["bootstrap"]["replicates"]["value"])
    s = int(seed if seed is not None else cfg["bootstrap"]["seed"]) + 101
    level = float(cfg["bootstrap"]["level"])
    band = int(aux["band"])
    th: StarterThresholds = aux["th_ppg"]
    rng = np.random.default_rng(s)

    teams_sorted = sorted(th.starters_by_team)
    by_team_pos: dict[str, dict[str, list[str]]] = {}
    marg_by_team_pos: dict[
        str, dict[str, str]
    ] = {}  # the player who IS each team's weakest starter
    for t in teams_sorted:
        d: dict[str, list[str]] = defaultdict(list)
        low: dict[str, tuple[float, str]] = {}
        for pid, pos, v in th.starters_by_team[t]:
            d[pos].append(pid)
            if pos not in low or (v, pid) < low[pos]:
                low[pos] = (v, pid)
        by_team_pos[t] = d
        marg_by_team_pos[t] = {pos: lv[1] for pos, lv in low.items()}
    floor_ids: dict[str, list[str]] = {}
    for p in positions:
        t = th.by_position.get(p)
        if t and t.marginals:
            order = sorted(zip(t.marginals, t.marginal_ids))
            floor_ids[p] = [pid for _v, pid in order[: max(1, band)]]

    ppg_levels = {p: {n: lv for n, lv in det[p].items() if n.endswith("Ppg")} for p in positions}
    needed: set[str] = set()
    for t in teams_sorted:
        for pid, _pos, _v in th.starters_by_team[t]:
            needed.add(pid)
    for p in positions:
        for lvl in ppg_levels[p].values():
            needed.update(lvl.ids)
        needed.update(floor_ids.get(p, ()))
    for t in teams_sorted:
        needed.update(marg_by_team_pos[t].values())

    def replicate(
        recs: Mapping[str, PlayerRecord], team_idx: Sequence[int]
    ) -> dict[str, dict[str, float | None]]:
        cache: dict[str, float | None] = {}

        def pg(pid: str) -> float | None:
            if pid not in cache:
                cache[pid] = ppg_of(recs[pid], weeks)
            return cache[pid]

        out: dict[str, dict[str, float | None]] = {}
        drawn = [teams_sorted[i] for i in team_idx]
        for p in positions:
            starter_vals = [
                v for t in drawn for pid in by_team_pos[t].get(p, ()) if (v := pg(pid)) is not None
            ]
            # the marginal starters are FIXED players (re-taking a minimum of resampled noisy
            # values would bias it downward), resampled only through their own games
            marg = [
                v
                for t in drawn
                if (mid := marg_by_team_pos[t].get(p)) and (v := pg(mid)) is not None
            ]
            floor_vals = [v for pid in floor_ids.get(p, ()) if (v := pg(pid)) is not None]
            m: dict[str, float | None] = {
                "starterMeanPpg": float(statistics.fmean(starter_vals)) if starter_vals else None,
                "starterMedianPpg": float(statistics.median(starter_vals))
                if starter_vals
                else None,
                "d1_medianMarginalPpg": float(statistics.median(marg)) if marg else None,
                "d1_bestBallFloorPpg": float(statistics.fmean(floor_vals)) if floor_vals else None,
            }
            for name, lvl in ppg_levels[p].items():
                vals = [v for pid in lvl.ids if (v := pg(pid)) is not None]
                m[name] = _stat_of(lvl.kind, vals) if lvl.ids else None
            sm = m["starterMedianPpg"]
            for name in list(m):
                if name.startswith(("d1_", "d2_", "d3_", "d4_")) and name.endswith("Ppg"):
                    m[f"gap_{name}"] = (
                        (sm - m[name]) if (sm is not None and m[name] is not None) else None
                    )
            out[p] = m
        return out

    point = replicate({pid: records[pid] for pid in needed}, list(range(len(teams_sorted))))
    draws: dict[str, dict[str, list[float]]] = {p: defaultdict(list) for p in positions}
    for _ in range(b):
        recs = _resample_games({pid: records[pid] for pid in sorted(needed)}, rng)
        idx = rng.integers(0, len(teams_sorted), len(teams_sorted)).tolist()
        for p, m in replicate(recs, idx).items():
            for k, v in m.items():
                if v is not None:
                    draws[p][k].append(float(v))
    a = (1.0 - level) / 2.0 * 100.0
    out: dict[str, dict[str, Any]] = {}
    for p in positions:
        out[p] = {}
        for k, v in point[p].items():
            xs = draws[p].get(k, [])
            cell: dict[str, Any] = {
                "point": None if v is None else round(float(v), 3),
                "ci95": None,
                "reps": len(xs),
            }
            if v is not None and len(xs) >= 20:
                lo, hi = np.percentile(xs, [a, 100.0 - a])
                cell["ci95"] = [round(float(lo), 3), round(float(hi), 3)]
            out[p][k] = cell
    return out


def selection_regression(
    records: Mapping[str, PlayerRecord],
    teams: Mapping[str, Sequence[str]],
    *,
    cfg: Mapping[str, Any],
    top_k: int | None = None,
    rule: PoolRule | None = None,
    positions: Sequence[str] = POSITIONS,
) -> dict[str, Any]:
    """The winner's curse, measured out of sample.

    For each evaluation week ``w`` (config ``walkForwardEvalWeeks``): rank the
    viable free agents at a position by ppg over weeks BEFORE ``w`` only, take
    the top ``top_k``, and compare their history ppg (the number a level would
    publish), the empirical-Bayes expectation fitted on that history, and what
    they actually scored in week ``w`` (only players who played ``w`` can be
    scored; the survivorship is reported).  The pooled ratio realised / history
    is the empirical shrinkage a raw free-agent level needs before it is read as
    a forecast.  Also scores the two estimators over EVERY viable free agent who
    played ``w`` (mean squared error, raw vs shrunk).
    """
    rule = rule or PoolRule()
    k = int(top_k if top_k is not None else cfg["levels"]["topK"]["value"])
    mg = int(cfg["window"]["minGames"]["value"])
    rostered = {pid for t in teams.values() for pid in t}
    eval_weeks = list(cfg["window"]["walkForwardEvalWeeks"]["value"])
    rows: list[dict[str, Any]] = []
    selected_n: Counter = Counter()
    se_raw: list[float] = []
    se_eb: list[float] = []
    all_weeks = sorted({wk for r in records.values() for wk in r.weekly})
    for w in eval_weeks:
        hist = [x for x in all_weeks if x < w]
        if not hist:
            continue
        eb = fit_eb(records, rostered, hist, min_games=mg)
        census = build_census(
            records, rostered, weeks=hist, cfg=cfg, rule=rule, positions=positions
        )
        for p in positions:
            pool = census.pool(p)
            for e in pool.entries:
                actual = e.rec.weekly.get(w)
                if actual is None or e.ppg is None:
                    continue
                se_raw.append((e.ppg - actual) ** 2)
                se_eb.append((eb.mean.get(e.player_id, e.ppg) - actual) ** 2)
            top = pool.by_ppg()[:k]
            selected_n[p] += len(top)
            for e in top:
                if w in e.rec.weekly:
                    rows.append(
                        {
                            "pid": e.player_id,
                            "position": p,
                            "hist": float(e.ppg),
                            "eb": float(eb.mean.get(e.player_id, e.ppg)),
                            "realised": float(e.rec.weekly[w]),
                        }
                    )

    seed = int(cfg["bootstrap"]["seed"]) + 7
    reps = int(cfg["bootstrap"]["replicates"]["value"])

    def agg(rs_: Sequence[Mapping[str, Any]], sel: int) -> dict[str, Any]:
        if not rs_:
            return {"playerWeeks": 0, "selected": sel}
        h = float(np.mean([r["hist"] for r in rs_]))
        e = float(np.mean([r["eb"] for r in rs_]))
        a = float(np.mean([r["realised"] for r in rs_]))
        # cluster bootstrap over PLAYERS (a player is scored in up to three eval weeks)
        by_p: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for r in rs_:
            by_p[r["pid"]].append(r)
        keys = sorted(by_p)
        rng = np.random.default_rng(seed)
        ratios = []
        for _ in range(reps):
            draw = [by_p[keys[i]] for i in rng.integers(0, len(keys), len(keys))]
            hh = sum(x["hist"] for g in draw for x in g)
            aa = sum(x["realised"] for g in draw for x in g)
            if hh > 0:
                ratios.append(aa / hh)
        ci = (
            [round(float(v), 3) for v in np.percentile(ratios, [2.5, 97.5])]
            if len(keys) >= 5 and ratios
            else None
        )
        return {
            "playerWeeks": len(rs_),
            "distinctPlayers": len(keys),
            "selected": sel,
            "historyPpg": round(h, 3),
            "ebPredictedPpg": round(e, 3),
            "realisedNextWeekPpg": round(a, 3),
            "realisedOverHistory": round(a / h, 3) if h else None,
            "realisedOverHistoryCi95": ci,
        }

    groups: dict[str, tuple[list[dict[str, Any]], int]] = {
        "all": (rows, sum(selected_n.values())),
        "idp": (
            [r for r in rows if r["position"] in ("DL", "LB", "DB")],
            sum(selected_n[p] for p in ("DL", "LB", "DB")),
        ),
        "offense": (
            [r for r in rows if r["position"] in ("QB", "RB", "WR", "TE")],
            sum(selected_n[p] for p in ("QB", "RB", "WR", "TE")),
        ),
    }
    for p in positions:
        groups[p] = ([r for r in rows if r["position"] == p], selected_n[p])
    n_se = len(se_raw)
    return {
        "topK": k,
        "evalWeeks": eval_weeks,
        "rule": "free agents ranked by ppg over weeks before w only; scored on week w",
        "byGroup": {g: agg(rs_, sel) for g, (rs_, sel) in groups.items()},
        "estimatorMse": {
            "playerWeeks": n_se,
            "raw": round(float(np.mean(se_raw)), 3) if n_se else None,
            "empiricalBayes": round(float(np.mean(se_eb)), 3) if n_se else None,
            "ebBeatsRaw": bool(n_se and np.mean(se_eb) < np.mean(se_raw)),
            "pairedMseDifferenceRawMinusEb": (
                round(float(np.mean(np.asarray(se_raw) - np.asarray(se_eb))), 3) if n_se else None
            ),
        },
    }


# ── D5: dynamic league-wide allocation ───────────────────────────────────────


@dataclass(frozen=True)
class Claim:
    round: int
    team: str
    player_id: str
    name: str
    position: str
    ppg: float | None
    value: float | None
    gain_per_week: float
    drop: str | None = None  # the cheapest legal release that makes room (None: no release needed)


def apply_claims(
    teams: Mapping[str, Sequence[str]], claims: Sequence[Claim]
) -> dict[str, list[str]]:
    """The rosters after the claims, replayed in order (release first, then add)."""
    out = {t: list(r) for t, r in teams.items()}
    for c in claims:
        if c.drop is not None and c.drop in out[c.team]:
            out[c.team].remove(c.drop)
        out[c.team].append(c.player_id)
    return out


@dataclass
class Allocation:
    """The planner allocation.  Teams are anonymous labels; no id leaves this object."""

    claims: list[Claim]
    rounds_run: int
    round1_top_choice_collisions: int  # free agents that were more than one team's best claim
    round1_independent_gain: float  # sum of each team's best gain if all could take the same player
    round1_matched_gain: float  # what the one-owner-per-player matching achieves
    teams_without_free_drop: int
    leftover: dict[str, Level]  # best remaining viable ppg per position

    def by_position(self, round_no: int | None = None) -> dict[str, list[Claim]]:
        out: dict[str, list[Claim]] = defaultdict(list)
        for c in self.claims:
            if round_no is None or c.round == round_no:
                out[c.position].append(c)
        return out


def _gain_of_adding(
    engine: WeeklyEngine, roster: Sequence[str], pid: str, base: Mapping[int, float]
) -> float:
    """Points per window-week gained by adding ``pid`` (adding changes only the
    weeks he has a stat line in)."""
    total = 0.0
    r = tuple(roster) + (pid,)
    for w in engine.weeks:
        if engine.has_line(pid, w):
            total += engine.solve(r, w).score - base[w]
    return total / len(engine.weeks)


def _free_drop(engine: WeeklyEngine, roster: Sequence[str]) -> str | None:
    """A rostered player who never starts in any window week.

    Dropping him changes no lineup now, and -- because adding a player can only
    displace starters, never promote a non-starter -- none after a claim either.
    So the drop is FREE and exact.  ``None`` if every rostered player starts at
    least once (then the cheapest-loss drop is used and the gain is net of it).
    """
    started = engine.starter_weeks(roster)
    bench = sorted(p for p in roster if p not in started)
    bench.sort(key=lambda p: (len(engine.records[p].weekly) if p in engine.records else 0, p))
    return bench[0] if bench else None


def _cheapest_drop(
    engine: WeeklyEngine, roster: Sequence[str], base: Mapping[int, float]
) -> tuple[str | None, float]:
    """``(player, lineup points per week lost)`` of the cheapest legal drop."""
    free = _free_drop(engine, roster)
    if free is not None:
        return free, 0.0
    sw = engine.starter_weeks(roster)
    best: tuple[float, str] | None = None
    for pid in sorted(roster):
        rest = tuple(x for x in roster if x != pid)
        loss = sum(base[w] - engine.solve(rest, w).score for w in sw.get(pid, ())) / len(
            engine.weeks
        )
        if best is None or (loss, pid) < best:
            best = (loss, pid)
    return (best[1], best[0]) if best else (None, 0.0)


def _claim_position(engine: WeeklyEngine, roster: Sequence[str], pid: str) -> str:
    """The position slot-family a claimed player fills most often after the claim."""
    rec = engine.records[pid]
    r = tuple(roster) + (pid,)
    fams: Counter = Counter()
    for w in engine.weeks:
        sol = engine.solve(r, w)
        for idx, who in sol.starters.items():
            if who == pid:
                fams[_attribute(engine.port, engine.slots[idx], rec)] += 1
    if fams:
        return sorted(fams.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return rec.position or "UNK"


def allocate_free_agents(
    teams: Mapping[str, Sequence[str]],
    engine: WeeklyEngine,
    census: Census,
    *,
    cfg: Mapping[str, Any],
    roster_cap: int | None,
) -> Allocation:
    """D5.  Serial maximum-gain matching: every free agent goes to at most ONE team.

    Round r builds the gain matrix G[t, f] = lineup points per week team t gains
    by adding free agent f (exact solver, net of the cheapest legal drop when the
    team is at the roster cap) and solves the assignment problem (each team at
    most one claim per round, each free agent at most one team).  Only
    positive-gain pairs are executed.  Winners leave the pool and join the
    roster; the next round recomputes only the rows that changed.

    This is a PLANNER allocation -- it maximises total points gained.  It is not
    a model of FAAB bidding and does not predict who wins a contested player;
    ``round1_top_choice_collisions`` and the independent-vs-matched gain
    difference measure how much competition for the same players matters.
    ``roster_cap=None`` (unknown) means no drop is charged, and says so.
    """
    from scipy.optimize import linear_sum_assignment  # noqa: PLC0415 — function-level on purpose

    rounds = int(cfg["allocation"]["rounds"]["value"])
    cap_n = int(cfg["allocation"]["candidateCapPerPosition"]["value"])
    team_ids = sorted(teams)
    rosters = {t: list(teams[t]) for t in team_ids}

    keep: dict[str, PoolEntry] = {}
    for pool in census.pools.values():
        for e in pool.by_ppg()[:cap_n]:
            keep.setdefault(e.player_id, e)
    cand_ids = sorted(keep, key=lambda k: (-(keep[k].ppg or 0.0), k))

    base: dict[str, dict[int, float]] = {}

    def base_of(t: str) -> dict[int, float]:
        if t not in base:
            base[t] = {w: engine.solve(rosters[t], w).score for w in engine.weeks}
        return base[t]

    claims: list[Claim] = []
    taken: set[str] = set()
    no_free_drop = 0
    r1_collisions = 0
    r1_indep = 0.0
    r1_matched = 0.0
    gains: dict[tuple[str, str], float] = {}
    drop_for: dict[str, tuple[str | None, float]] = {}
    dirty = set(team_ids)
    rounds_run = 0
    for rnd in range(1, rounds + 1):
        live_ids = [f for f in cand_ids if f not in taken]
        if not live_ids:
            break
        for t in sorted(dirty):
            at_cap = roster_cap is not None and len(rosters[t]) >= roster_cap
            drop_for[t] = _cheapest_drop(engine, rosters[t], base_of(t)) if at_cap else (None, 0.0)
            for f in cand_ids:
                gains.pop((t, f), None)
        dirty = set()
        for t in team_ids:
            for f in live_ids:
                if (t, f) not in gains:
                    gains[(t, f)] = (
                        _gain_of_adding(engine, rosters[t], f, base_of(t)) - drop_for[t][1]
                    )
        mat = np.array([[max(gains[(t, f)], 0.0) for f in live_ids] for t in team_ids], dtype=float)
        if mat.size == 0 or float(mat.max()) <= 0.0:
            break
        rounds_run = rnd
        rows, cols = linear_sum_assignment(-mat)
        if rnd == 1:
            top = [
                live_ids[int(np.argmax(mat[i]))] for i in range(len(team_ids)) if mat[i].max() > 0
            ]
            r1_collisions = sum(1 for c in Counter(top).values() if c > 1)
            r1_indep = float(sum(mat[i].max() for i in range(len(team_ids))))
            r1_matched = float(sum(mat[i, j] for i, j in zip(rows, cols)))
        for i, j in zip(rows, cols):
            g = float(mat[i, j])
            if g <= 0.0:
                continue
            t, f = team_ids[int(i)], live_ids[int(j)]
            e = keep[f]
            pos = _claim_position(engine, rosters[t], f)
            drop = drop_for[t][0]
            claims.append(Claim(rnd, t, f, e.name, pos, e.ppg, e.value, round(g, 6), drop))
            taken.add(f)
            if drop is not None:
                rosters[t].remove(drop)
            elif roster_cap is not None and len(rosters[t]) >= roster_cap:
                no_free_drop += 1
            rosters[t].append(f)
            base.pop(t, None)
            dirty.add(t)
    leftover = {
        p: level_best([e for e in pool.entries if e.player_id not in taken], "ppg")
        for p, pool in census.pools.items()
    }
    return Allocation(
        claims=claims,
        rounds_run=rounds_run,
        round1_top_choice_collisions=r1_collisions,
        round1_independent_gain=r1_indep,
        round1_matched_gain=r1_matched,
        teams_without_free_drop=no_free_drop,
        leftover=leftover,
    )


# ── D6: team-specific replacement after a hypothetical transaction ───────────


@dataclass
class TeamReplacement:
    """For one hypothetical roster: the best claim at each position, in lineup points."""

    roster_size: int
    over_cap_by: int | None
    by_position: dict[str, dict[str, Any]]


def team_replacement_after(
    roster_after: Sequence[str],
    pool: Sequence[PoolEntry],
    engine: WeeklyEngine,
    *,
    exclude: Iterable[str] = (),
    positions: Sequence[str] = POSITIONS,
    roster_cap: int | None = None,
    candidate_cap: int = 25,
) -> TeamReplacement:
    """D6.  The replacement THIS roster would use, after the transaction.

    ``roster_after`` is the roster the hypothetical leaves (the caller removed
    and added players).  For each position the candidates are the viable free
    agents eligible there who are not in ``exclude`` (players other teams have
    already taken); the best is the one that adds the most lineup points per
    week to ``roster_after`` through the exact solver.  No positive-gain claim
    => ``internal_promotion_only``: the roster's own depth already fills what
    it can, and the weakest started ppg at that position is reported (never 0,
    never a free agent who does not help).
    """
    ex = set(exclude)
    ros = tuple(roster_after)
    base = {w: engine.solve(ros, w).score for w in engine.weeks}
    started = engine.starter_weeks(ros)
    out: dict[str, dict[str, Any]] = {}
    for p in positions:
        elig = [
            e
            for e in pool
            if e.player_id not in ex and p in e.rec.eligible_positions(engine.eligibility)
        ]
        elig.sort(key=lambda e: (-(e.ppg or 0.0), e.player_id))
        scored = [
            (_gain_of_adding(engine, ros, e.player_id, base), e) for e in elig[:candidate_cap]
        ]
        scored = [(g, e) for g, e in scored if g > 0]
        scored.sort(key=lambda ge: (-ge[0], -(ge[1].ppg or 0.0), ge[1].player_id))
        mine = [
            ppg_of(engine.records[pid], engine.weeks)
            for pid, wks in started.items()
            if wks and engine.records[pid].position == p
        ]
        weakest = min((x for x in mine if x is not None), default=None)
        if not scored:
            out[p] = {
                "state": "internal_promotion_only",
                "claim": None,
                "ppg": None,
                "value": None,
                "gainPerWeek": 0.0,
                "weakestStartedPpg": weakest,
                "candidates": len(elig),
            }
        else:
            g, e = scored[0]
            out[p] = {
                "state": "claim",
                "claim": e.name,
                "ppg": e.ppg,
                "value": e.value,
                "gainPerWeek": g,
                "weakestStartedPpg": weakest,
                "candidates": len(elig),
            }
    over = None if roster_cap is None else max(0, len(ros) - roster_cap)
    return TeamReplacement(roster_size=len(ros), over_cap_by=over, by_position=out)


# ── marginal optimised best-ball contribution ────────────────────────────────


@dataclass(frozen=True)
class ReplacementSpec:
    """A free-agent series to use as the backfill: a real player or a labelled
    synthetic (the pool's week-by-week mean)."""

    label: str
    record: PlayerRecord
    synthetic: bool = False


def synthetic_pool_mean(
    position: str, entries: Sequence[PoolEntry], weeks: Sequence[int]
) -> PlayerRecord | None:
    """A synthetic backfill whose points each week are the pool's mean that week
    (over members who played).  ``None`` when no member played any week."""
    wk: dict[int, float] = {}
    for w in weeks:
        vals = [e.rec.weekly[w] for e in entries if w in e.rec.weekly]
        if vals:
            wk[w] = statistics.fmean(vals)
    if not wk:
        return None
    return PlayerRecord(
        player_id=f"__pool_mean_{position}",
        name=f"{position} qualified-pool mean (synthetic)",
        position=position,
        fantasy_positions=(position,),
        weekly=wk,
    )


def marginal_contributions(
    teams: Mapping[str, Sequence[str]],
    engine: WeeklyEngine,
    replacements: Mapping[str, Mapping[str, ReplacementSpec]],
    *,
    eval_weeks: Sequence[int] | None = None,
) -> dict[str, dict[str, Any]]:
    """Per rostered player: the best-ball lineup points per week he adds, with and without him.

    ``contribution_empty`` = S(R) - S(R - i): the next man up fills (no backfill).
    ``contribution_over_<label>`` = S(R) - S(R - i + r): the same with the
    position's free-agent backfill ``r``.  A bench player who is worse than the
    backfill has a NEGATIVE value over that replacement: holding him costs the
    roster spot's alternative use.  Each is a whole-roster solve per week by the
    exact solver -- never a sum of one-at-a-time deltas.

    ``replacements[position][label]`` supplies the backfill for a player at
    ``position``; a position with no entry for a label has no value for it
    (undefined, not 0).  Result: ``{player_id: {...}}`` in points per
    evaluated week.
    """
    weeks = tuple(engine.weeks if eval_weeks is None else eval_weeks)
    n = len(weeks)
    engines: dict[tuple[str, str], WeeklyEngine] = {}
    for pos, by_label in replacements.items():
        for label, spec in by_label.items():
            engines[(pos, label)] = engine.extended({spec.record.player_id: spec.record})
    out: dict[str, dict[str, Any]] = {}
    for t in sorted(teams):
        ros = tuple(teams[t])
        base = {w: engine.solve(ros, w) for w in weeks}
        started: dict[str, set[int]] = defaultdict(set)
        for w, sol in base.items():
            for pid in sol.starters.values():
                if engine.has_line(pid, w):  # a zero-filled non-player is not a starter
                    started[pid].add(w)
        for pid in ros:
            rec = engine.records.get(pid)
            if rec is None:
                continue
            without = tuple(x for x in ros if x != pid)
            empty_total = sum(
                base[w].score - engine.solve(without, w).score for w in started.get(pid, ())
            )
            row: dict[str, Any] = {
                "position": rec.position,
                "startWeeks": len(started.get(pid, ())),
                "contribution_empty": empty_total / n,
            }
            for label, spec in (replacements.get(rec.position) or {}).items():
                eng2 = engines[(rec.position, label)]
                with_r = without + (spec.record.player_id,)
                tot = 0.0
                for w in weeks:
                    i_starts = w in started.get(pid, ())
                    r_plays = w in spec.record.weekly
                    if not i_starts and not r_plays:
                        continue  # removing a non-starter changes nothing; r has no game
                    tot += base[w].score - eng2.solve(with_r, w).score
                row[f"contribution_over_{label}"] = tot / n
            out[pid] = row
    return out


# ── whole-roster package evaluator ───────────────────────────────────────────


@dataclass
class PackageResult:
    status: str  # ok | give_not_on_roster | get_already_on_roster | incomplete
    reason: str | None = None
    before_per_week: float | None = None
    after_per_week: float | None = None
    delta_per_week: float | None = None
    delta_with_backfill_per_week: float | None = None
    per_week_delta: list[float] = field(default_factory=list)
    forced_drops: list[str] = field(default_factory=list)
    over_cap_by: int = 0
    naive_sum_of_player_deltas: float | None = None
    interaction: float | None = None
    unpriced_get: list[str] = field(default_factory=list)
    backfill: list[str] = field(default_factory=list)


def evaluate_package(
    roster: Sequence[str],
    give: Sequence[str],
    get: Sequence[str],
    engine: WeeklyEngine,
    *,
    pool: Sequence[PoolEntry] = (),
    roster_cap: int | None = None,
    exclude: Iterable[str] = (),
    backfill_positions: Sequence[str] | None = None,
) -> PackageResult:
    """The WHOLE before/after roster.  Never a sum of per-player deltas.

    ``after = roster - give + get``; if that exceeds ``roster_cap`` the cheapest
    legal drops (least lineup points lost, exact solver, the free never-starter
    first) are removed -- this is the module's own lineup-points reading, not the
    production forced-drop owner.  ``delta_with_backfill`` additionally lets the
    after-roster make its best single free-agent claim (D6, net of its free
    drop).

    A ``get`` player with no stat line (production unknown) makes the result
    ``incomplete`` and is listed in ``unpriced_get`` -- he is NOT evaluated as a
    zero-point player.  ``naive_sum_of_player_deltas`` (each move alone against
    the ORIGINAL roster, added up) is published only so ``interaction`` = whole
    - naive exposes how much players compete for the same slots.
    """
    ros = list(roster)
    have = set(ros)
    missing = [g for g in give if g not in have]
    if missing:
        return PackageResult("give_not_on_roster", reason=",".join(missing))
    if any(g in have for g in get):
        return PackageResult("get_already_on_roster")
    unpriced = [g for g in get if g not in engine.records or not engine.records[g].weekly]
    if unpriced:
        return PackageResult(
            "incomplete", reason="get_player_has_no_production", unpriced_get=unpriced
        )

    after = [p for p in ros if p not in set(give)] + list(get)
    over = 0
    drops: list[str] = []
    if roster_cap is not None and len(after) > roster_cap:
        over = len(after) - roster_cap
        for _ in range(over):
            base = {w: engine.solve(after, w).score for w in engine.weeks}
            d, _loss = _cheapest_drop(engine, after, base)
            if d is None:
                break
            drops.append(d)
            after = [p for p in after if p != d]
    nweeks = len(engine.weeks)
    before_w = engine.per_week(ros)
    after_w = engine.per_week(after)
    before_pw = sum(before_w) / nweeks
    after_pw = sum(after_w) / nweeks

    naive = 0.0
    for g in give:
        naive += sum(engine.per_week([p for p in ros if p != g])) / nweeks - before_pw
    for g in get:
        naive += sum(engine.per_week(ros + [g])) / nweeks - before_pw

    backfill: list[str] = []
    with_backfill: float | None = None
    if pool:
        tr = team_replacement_after(
            after,
            pool,
            engine,
            exclude=set(exclude) | set(get) | set(give),
            positions=tuple(backfill_positions) if backfill_positions else POSITIONS,
        )
        best = max(
            (v for v in tr.by_position.values() if v["state"] == "claim"),
            key=lambda v: v["gainPerWeek"],
            default=None,
        )
        if best is not None:
            backfill = [best["claim"]]
            with_backfill = after_pw + best["gainPerWeek"] - before_pw
        else:
            with_backfill = after_pw - before_pw
    return PackageResult(
        status="ok",
        before_per_week=before_pw,
        after_per_week=after_pw,
        delta_per_week=after_pw - before_pw,
        delta_with_backfill_per_week=with_backfill,
        per_week_delta=[a - b for a, b in zip(after_w, before_w)],
        forced_drops=[engine.records[d].name for d in drops],
        over_cap_by=over,
        naive_sum_of_player_deltas=naive,
        interaction=(after_pw - before_pw) - naive,
        backfill=backfill,
    )


# ── eligibility uncertainty ──────────────────────────────────────────────────


def eligibility_uncertainty(
    records: Mapping[str, PlayerRecord],
    teams: Mapping[str, Sequence[str]],
    port: LineupPort,
    slots: Sequence[str],
    *,
    weeks: Sequence[int],
    cfg: Mapping[str, Any],
    positions: Sequence[str] = POSITIONS,
) -> dict[str, dict[str, Any]]:
    """How much a position's levels depend on HOW a hybrid may fill slots.

    Recomputes D1-D4 under Sleeper's ``fantasy_positions`` eligibility and under
    nominal position only (both pool keying and the solver); the difference per
    level is the eligibility uncertainty.  Also reports the share of rostered
    and free-agent players with more than one eligible position, and the
    free agents excluded for unknown health or no games.
    """
    a = compute_level_set(
        records, teams, port, slots, weeks=weeks, cfg=cfg, rule=PoolRule(), positions=positions
    )
    b = compute_level_set(
        records,
        teams,
        port,
        slots,
        weeks=weeks,
        cfg=cfg,
        rule=PoolRule.nominal_only(),
        positions=positions,
    )
    rostered = {pid for t in teams.values() for pid in t}
    out: dict[str, dict[str, Any]] = {}
    for p in positions:
        diffs: dict[str, float] = {}
        for k, va in a[p].items():
            vb = b[p].get(k)
            if k.endswith(("Ppg", "Value")) and va is not None and vb is not None:
                diffs[k] = round(va - vb, 3)
        r_all = [
            pid for pid in rostered if pid in records and p in records[pid].eligible_positions()
        ]
        hy_r = [pid for pid in r_all if len(records[pid].eligible_positions()) > 1]
        pool = build_census(
            records, rostered, weeks=weeks, cfg=cfg, rule=PoolRule(), positions=(p,)
        ).pool(p)
        hy_f = [e for e in pool.entries if len(e.rec.eligible_positions()) > 1]
        out[p] = {
            "sleeperMinusNominal": diffs,
            "rosteredEligible": len(r_all),
            "rosteredMultiEligible": len(hy_r),
            "viablePoolN": len(pool.entries),
            "viablePoolMultiEligible": len(hy_f),
            "freeAgentHealthUnknown": int(pool.excluded.get("health_unknown", 0)),
            "freeAgentNoGames": int(pool.excluded.get("no_games", 0)),
            "freeAgentBelowMinGames": int(pool.excluded.get("below_min_games", 0)),
        }
    return out


# ── public-artifact guard ────────────────────────────────────────────────────

_FORBIDDEN_KEYS = frozenset(
    {
        "user_id",
        "owner_id",
        "roster_id",
        "league_id",
        "display_name",
        "team_name",
        "username",
        "avatar",
        "co_owners",
        "sleeperLeagueId",
        "leagueId",
        "rosterId",
        "ownerId",
        "userId",
        "managerName",
    }
)


def assert_public_artifact(
    obj: Any, *, forbidden_values: Iterable[str] = (), _path: str = "$"
) -> None:
    """Fail loudly if an artifact carries a manager/team/user identifier.

    Allowed: aggregates and public NFL player names.  Checks keys against a
    forbidden set and every string against ``forbidden_values`` (for example the
    league id and any manager display names the caller knows).
    """
    fv = [v for v in forbidden_values if v]
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            if str(k) in _FORBIDDEN_KEYS:
                raise ValueError(f"public artifact carries forbidden key {k!r} at {_path}")
            assert_public_artifact(v, forbidden_values=fv, _path=f"{_path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            assert_public_artifact(v, forbidden_values=fv, _path=f"{_path}[{i}]")
    elif isinstance(obj, str):
        for bad in fv:
            if bad in obj:
                raise ValueError(f"public artifact carries forbidden value at {_path}")
