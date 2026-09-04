"""CE-20 — THE canonical league-aware current-week scoring simulation.

Governed by `docs/GAME_DAY_PROBABILITY_SPEC.md`; contract rows
`W1-18`…`W1-24` in `docs/season-launch/WEEK_1_LAUNCH_CONTRACT.md`.

**One simulation, two outcomes.** The spec's §2/§3 requirement is that
`Win Matchup %` and `Beat League Median %` are correlated descendants of
the same simulated week, never two formulas. That is structural here:
:func:`simulate_league_week` draws the whole league's scores together,
and for each draw computes the threshold **from that draw's own
league-wide scores** before deciding either outcome. There is no code
path that produces one without the other from the same draws.

**It is not a new engine.** The per-player weekly distribution is
`src.league_intel.sim_calibration.PointsModel` — the per-position CV
measured under this league's own scoring by the golden-validated scorer
— and the best-ball lineup is `src.ros.lineup.solve_optimal_assignment`,
the exact solver that goes 10/10 against Sleeper's own awarded lineups.
This module owns the WEEK: which players can still move, what a draw
means for each of them, and how a league-wide draw becomes two
probabilities.

**Best ball is a league FACT, not this league's default.** `best_ball`
and `league_average_match` are read per league and passed in
(:class:`LeagueWeekRules`). Measured 2026-09-04: `dynasty_main` is
`best_ball=1, league_average_match=1` with 12 teams, and `dynasty_new`
is `best_ball=0, league_average_match=0` with 10. Assuming either
would serve one league the other's game.

**Missing is never zero, and neither is unknown.**
`median_enabled=None` means the standings rule was not verifiable and
yields `STANDINGS_RULE_UNVERIFIED` — distinct from `False`, which yields
`NOT_APPLICABLE`, and both distinct from a fabricated `0.0`. A player
whose remaining production cannot be estimated is EXCLUDED from the
lineup pool and reported in `unsimulable_player_ids`, never drawn as
zero. A team with no opponent is `UNSIMULABLE`, never 50%.

**Host semantics for the threshold are NOT yet verified**, and this
module says so rather than implying otherwise. `THRESHOLD_SEMANTICS`
carries the statistic actually used and
`threshold_semantics_verified=False` travels on every result. The
attempt and why it failed are recorded in
`docs/game-day/MEDIAN_SEMANTICS_VERIFICATION.md`: reconciling 2025's
records against Sleeper's own reported records reproduced at most 3 of
10 teams under six variants, because Sleeper's stored historical
matchup points no longer reproduce Sleeper's own season totals (a
best-ball league recomputes the optimal lineup from current player
stats, so accumulated stat corrections move the history). Swapping the
statistic is a one-constant change once a human reads it off the host.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from src.league_intel.sim_calibration import PointsModel, load_points_model
from src.ros.lineup import RosterPlayer, solve_optimal_assignment

#: A player's state within the scoring period. Every one of these is a
#: DIFFERENT statement about what is still uncertain, and collapsing any
#: two of them is what produces double-projection (spec §6: "do not
#: treat already-scored points as uncertain or completed players as
#: still having a full projection remaining").
PLAYER_STATES: frozenset[str] = frozenset(
    {"completed", "in_progress", "not_started", "inactive", "unknown"}
)

#: The statistic the extra weekly result is decided against. NOT yet
#: verified against the host — see the module docstring.
THRESHOLD_SEMANTICS: str = "median"

#: Default draws. Matches the playoff sim's own 10,000 rather than
#: introducing a second number for the same kind of question.
DEFAULT_DRAWS: int = 10_000

#: Fixed so a probability does not flicker between identical requests.
#: A re-render is not new evidence.
DEFAULT_SEED: int = 20260910

MODEL_VERSION: str = "game-day-sim-v1"


class GameDaySimError(ValueError):
    """Raised for a request that cannot be simulated as asked."""


@dataclass(frozen=True)
class PlayerWeek:
    """One player's contribution to one team-week.

    ``points_scored`` is what is ALREADY BANKED — a fact, not an
    estimate. ``projected_remaining`` is the MEAN of what is still to
    come, in points. ``None`` there means genuinely unknown; it is never
    coerced to 0.0, because "expected to score nothing more" and "we
    cannot say" are different claims and only the first is evidence.
    """

    player_id: str
    position: str
    state: str
    points_scored: float | None = None
    projected_remaining: float | None = None
    fantasy_positions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.state not in PLAYER_STATES:
            raise GameDaySimError(
                f"{self.player_id}: state {self.state!r} not in {sorted(PLAYER_STATES)}"
            )


@dataclass(frozen=True)
class TeamWeek:
    """One team's roster for one scoring period."""

    team_id: str
    players: tuple[PlayerWeek, ...]
    #: Only consulted in a MANAGED-lineup league, where the manager's
    #: submitted lineup is the lineup. Ignored under best ball, where the
    #: host optimizes and no start/sit decision exists.
    declared_starters: tuple[str, ...] = ()


@dataclass(frozen=True)
class LeagueWeekRules:
    """The requested league's own rules. Never another league's."""

    league_key: str
    starter_slots: tuple[str, ...]
    best_ball: bool
    #: True / False / **None**. ``None`` is "the standings rule could not
    #: be verified", which is not the same as the median game being off.
    median_enabled: bool | None
    team_count: int

    def __post_init__(self) -> None:
        if not self.starter_slots:
            raise GameDaySimError(
                f"{self.league_key}: no starter slots — a lineup cannot be filled from "
                "an empty slot list, and defaulting one would simulate a different league."
            )


@dataclass
class TeamWeekOutcome:
    """Simulated outcomes for one team. Percentages are 0-100 floats, or
    ``None`` with a reason when the question does not apply."""

    team_id: str
    opponent_id: str | None
    draws: int

    win_matchup_pct: float | None
    tie_matchup_pct: float | None
    #: ``None`` with ``beat_median_state`` naming why.
    beat_median_pct: float | None
    beat_median_state: str

    projected_mean: float
    projected_p10: float
    projected_p50: float
    projected_p90: float
    points_banked: float

    #: Joint outcomes, spec §8. Present only when both legs are live.
    joint_2_0_pct: float | None = None
    joint_1_1_h2h_pct: float | None = None
    joint_1_1_median_pct: float | None = None
    joint_0_2_pct: float | None = None

    unsimulable_player_ids: tuple[str, ...] = ()
    notes: list[str] = field(default_factory=list)


@dataclass
class LeagueWeekSimulation:
    """Every team's outcome for one league-week, plus the provenance the
    UI needs to tell a fresh estimate from a degraded one (spec §9)."""

    league_key: str
    season: int
    week: int
    draws: int
    teams: tuple[TeamWeekOutcome, ...]
    model_version: str
    points_model_source: str
    threshold_semantics: str
    threshold_semantics_verified: bool
    median_enabled: bool | None
    best_ball: bool
    seed: int
    notes: list[str] = field(default_factory=list)


def _drawable(player: PlayerWeek) -> bool:
    """Can this player's week be simulated at all?

    A ``completed`` player needs a real banked score; a player who still
    has football left needs a remaining estimate. Neither is invented.
    """
    if player.state in ("completed", "inactive"):
        return player.points_scored is not None or player.state == "inactive"
    if player.state in ("in_progress", "not_started"):
        return player.projected_remaining is not None
    return False  # "unknown"


def _banked_points(player: PlayerWeek) -> float:
    """Points this player has ALREADY scored this week.

    An absent ``points_scored`` here is a REAL zero, not missing data,
    and the distinction is worth writing out rather than leaving to an
    ``or 0.0`` a reader has to take on trust. A player whose game has not
    kicked off has scored nothing — that is an observation, not a gap.
    The genuinely-unknown case never reaches this function: ``_drawable``
    already refuses a ``completed`` player with no score, and an
    ``unknown`` player is excluded from the pool entirely.
    """
    scored = player.points_scored
    return 0.0 if scored is None else float(scored)


def _draw_player(player: PlayerWeek, model: PointsModel, rng: random.Random) -> float:
    """One player's simulated final total for this week.

    The state decides what is random, and that is the whole point:

    * ``completed`` — banked points, NO draw. Re-projecting a finished
      game would put uncertainty on a fact.
    * ``inactive`` — whatever is banked (usually nothing) and no more. A
      player who will not play is a known zero, not a missing estimate.
    * ``in_progress`` — banked points are kept as certain and only the
      REMAINDER is drawn, so a player mid-game is neither double-counted
      nor treated as finished.
    * ``not_started`` — the full remaining distribution.
    """
    banked = _banked_points(player)
    if player.state in ("completed", "inactive"):
        return banked
    remaining = player.projected_remaining
    if remaining is None:  # guarded by _drawable; defensive
        return banked
    return banked + model.draw_from_mean(float(remaining), player.position, rng)


def _team_score(
    team: TeamWeek,
    drawn: Mapping[str, float],
    rules: LeagueWeekRules,
) -> float:
    """One team's simulated weekly score under its OWN lineup rules.

    Best ball re-solves the exact optimal assignment against THIS draw's
    scores, which is what makes lineup displacement real: a player
    outside the provisional best lineup still matters, because a big
    draw can displace someone already in it. A managed league sums the
    lineup its manager actually submitted — re-optimizing there would
    award points nobody could have earned.
    """
    if rules.best_ball:
        pool = [
            RosterPlayer(
                player_id=p.player_id,
                canonical_name="",
                position=p.position,
                ros_value=drawn[p.player_id],
                fantasy_positions=p.fantasy_positions,
            )
            for p in team.players
            if p.player_id in drawn
        ]
        if not pool:
            return 0.0
        assignment = solve_optimal_assignment(pool, list(rules.starter_slots))
        return float(sum(pl.ros_value or 0.0 for pl in assignment.values()))
    return float(sum(drawn.get(pid, 0.0) for pid in team.declared_starters))


def _threshold(scores: Sequence[float], semantics: str = THRESHOLD_SEMANTICS) -> float:
    if semantics == "median":
        return float(statistics.median(scores))
    if semantics == "mean":
        return float(statistics.fmean(scores))
    raise GameDaySimError(f"unknown threshold semantics {semantics!r}")


def _pct(count: int, draws: int) -> float:
    return round(100.0 * count / draws, 2) if draws else 0.0


def simulate_league_week(
    *,
    rules: LeagueWeekRules,
    teams: Sequence[TeamWeek],
    opponents: Mapping[str, str | None],
    season: int,
    week: int,
    draws: int = DEFAULT_DRAWS,
    seed: int = DEFAULT_SEED,
    points_model: PointsModel | None = None,
    threshold_semantics: str = THRESHOLD_SEMANTICS,
) -> LeagueWeekSimulation:
    """Simulate the whole league-week once and derive BOTH outcomes.

    ``opponents`` maps team_id → opponent team_id, or ``None`` for a team
    with no scheduled opponent. A missing opponent makes that team's
    matchup probability ``None`` / ``UNSIMULABLE`` (spec §9) — never 50%,
    which would be a claim about a game that is not on the schedule.

    The league-wide draw happens ONCE per iteration and both legs read
    it, so the threshold moves with the other teams' simulated scores
    exactly as spec §3 requires.
    """
    if draws <= 0:
        raise GameDaySimError("draws must be positive")
    if not teams:
        raise GameDaySimError(f"{rules.league_key}: no teams to simulate")

    model = points_model or load_points_model()
    rng = random.Random(seed)

    simulable: dict[str, tuple[PlayerWeek, ...]] = {}
    unsimulable: dict[str, tuple[str, ...]] = {}
    banked: dict[str, float] = {}
    for team in teams:
        ok = tuple(p for p in team.players if _drawable(p))
        simulable[team.team_id] = ok
        unsimulable[team.team_id] = tuple(p.player_id for p in team.players if not _drawable(p))
        # Banked points are reported from the players that COUNT toward
        # the lineup, so a completed-but-benched score is not advertised
        # as though it is on the board.
        banked[team.team_id] = float(sum(_banked_points(p) for p in ok))

    totals: dict[str, list[float]] = {t.team_id: [] for t in teams}
    h2h_win = {t.team_id: 0 for t in teams}
    h2h_tie = {t.team_id: 0 for t in teams}
    med_win = {t.team_id: 0 for t in teams}
    joint = {t.team_id: {"2_0": 0, "1_1_h2h": 0, "1_1_med": 0, "0_2": 0} for t in teams}

    median_live = rules.median_enabled is True

    for _ in range(draws):
        drawn_by_team: dict[str, dict[str, float]] = {}
        for team in teams:
            drawn_by_team[team.team_id] = {
                p.player_id: _draw_player(p, model, rng) for p in simulable[team.team_id]
            }
        scores = {t.team_id: _team_score(t, drawn_by_team[t.team_id], rules) for t in teams}
        for tid, sc in scores.items():
            totals[tid].append(sc)

        # THE SAME DRAW decides both legs. The threshold is computed from
        # this iteration's league-wide scores, so it moves with them.
        thr = _threshold(list(scores.values()), threshold_semantics) if median_live else None

        for team in teams:
            tid = team.team_id
            opp = opponents.get(tid)
            won_h2h: bool | None = None
            if opp is not None and opp in scores:
                if scores[tid] > scores[opp]:
                    h2h_win[tid] += 1
                    won_h2h = True
                elif scores[tid] == scores[opp]:
                    h2h_tie[tid] += 1
                    won_h2h = None
                else:
                    won_h2h = False
            if thr is None:
                continue
            beat_med = scores[tid] > thr
            if beat_med:
                med_win[tid] += 1
            if won_h2h is None:
                continue
            if won_h2h and beat_med:
                joint[tid]["2_0"] += 1
            elif won_h2h:
                joint[tid]["1_1_h2h"] += 1
            elif beat_med:
                joint[tid]["1_1_med"] += 1
            else:
                joint[tid]["0_2"] += 1

    out: list[TeamWeekOutcome] = []
    for team in teams:
        tid = team.team_id
        series = sorted(totals[tid])
        opp = opponents.get(tid)
        notes: list[str] = []

        if opp is None:
            win_pct: float | None = None
            tie_pct: float | None = None
            notes.append("UNSIMULABLE: no scheduled opponent this week")
        else:
            win_pct = _pct(h2h_win[tid], draws)
            tie_pct = _pct(h2h_tie[tid], draws)

        if rules.median_enabled is None:
            med_pct: float | None = None
            med_state = "STANDINGS_RULE_UNVERIFIED"
        elif rules.median_enabled is False:
            med_pct = None
            med_state = "NOT_APPLICABLE"
        else:
            med_pct = _pct(med_win[tid], draws)
            med_state = "OK"

        if unsimulable[tid]:
            notes.append(
                f"{len(unsimulable[tid])} player(s) had no estimable remaining "
                "production and were excluded rather than drawn as zero"
            )

        joint_live = med_state == "OK" and opp is not None
        out.append(
            TeamWeekOutcome(
                team_id=tid,
                opponent_id=opp,
                draws=draws,
                win_matchup_pct=win_pct,
                tie_matchup_pct=tie_pct,
                beat_median_pct=med_pct,
                beat_median_state=med_state,
                projected_mean=round(statistics.fmean(series), 2),
                projected_p10=round(series[int(0.10 * (len(series) - 1))], 2),
                projected_p50=round(statistics.median(series), 2),
                projected_p90=round(series[int(0.90 * (len(series) - 1))], 2),
                points_banked=round(banked[tid], 2),
                joint_2_0_pct=_pct(joint[tid]["2_0"], draws) if joint_live else None,
                joint_1_1_h2h_pct=_pct(joint[tid]["1_1_h2h"], draws) if joint_live else None,
                joint_1_1_median_pct=_pct(joint[tid]["1_1_med"], draws) if joint_live else None,
                joint_0_2_pct=_pct(joint[tid]["0_2"], draws) if joint_live else None,
                unsimulable_player_ids=unsimulable[tid],
                notes=notes,
            )
        )

    sim_notes: list[str] = []
    if rules.median_enabled is None:
        sim_notes.append(
            "median standings rule unverified for this league — reported as "
            "STANDINGS_RULE_UNVERIFIED, not as disabled"
        )
    if model.source == "fallback-constants":
        sim_notes.append(
            "points model is the documented FALLBACK, not this league's measured "
            "calibration — treat the spread as weaker evidence"
        )

    return LeagueWeekSimulation(
        league_key=rules.league_key,
        season=season,
        week=week,
        draws=draws,
        teams=tuple(out),
        model_version=MODEL_VERSION,
        points_model_source=model.source,
        threshold_semantics=threshold_semantics,
        # Deliberately hard-coded False: see the module docstring. It flips
        # when a human reads the rule off the host, not when a caller
        # would like it to be true.
        threshold_semantics_verified=False,
        median_enabled=rules.median_enabled,
        best_ball=rules.best_ball,
        seed=seed,
        notes=sim_notes,
    )


def rules_from_league(
    *,
    league_key: str,
    league_payload: Mapping[str, Any],
    starter_slots: Iterable[str],
) -> LeagueWeekRules:
    """Build the rules from the requested league's OWN Sleeper payload.

    ``best_ball`` and ``league_average_match`` are read; neither is
    defaulted. An absent ``league_average_match`` yields ``None``
    (unverified), not ``False`` — the spec is explicit that an unknown
    median setting is `STANDINGS_RULE_UNVERIFIED` rather than disabled.
    """
    settings = league_payload.get("settings") or {}
    raw_median = settings.get("league_average_match")
    median_enabled: bool | None
    if raw_median is None:
        median_enabled = None
    else:
        try:
            median_enabled = bool(int(raw_median))
        except (TypeError, ValueError):
            median_enabled = None
    try:
        team_count = int(settings.get("num_teams") or 0)
    except (TypeError, ValueError):
        team_count = 0
    return LeagueWeekRules(
        league_key=league_key,
        starter_slots=tuple(starter_slots),
        best_ball=bool(int(settings.get("best_ball") or 0)),
        median_enabled=median_enabled,
        team_count=team_count,
    )
