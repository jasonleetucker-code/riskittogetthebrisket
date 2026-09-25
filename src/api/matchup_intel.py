"""Private Week-N matchup intelligence for one team (W1-14 / W1-15).

**It computes nothing of its own.** Every number here is produced by a
canonical owner and copied:

| quantity | owner |
|---|---|
| which players are on the roster, IR/taxi subtraction | `src/ros/game_day_capture.py` |
| the league's starter slots and who is legal in each | `src/ros/lineup.py` |
| the expected best-ball lineup | `src/ros/lineup.solve_optimal_assignment` |
| per-player weekly distribution, win % / beat-median %, lineup %, leverage | `src/ros/game_day_sim.py` |
| resolving a live league-week into those inputs | `src/ros/game_day_week.py` |
| observed NFL quarter / clock / status | `src/nfl_data/live_game_state.py` |
| which weekly baseline each player uses | `src/ros/game_day_estimates.py` |
| weekly projections (RotoWire via Sleeper) | `src/ros/sleeper_weekly_projections.py` |
| preseason fallback projections | `src/ros/projection_ensemble.py` |
| roster strength / weakness / age-value | `src/api/roster_intelligence.py` |
| the league's identity and rules | `src/api/league_registry.py` + the host |

This module is the assembly, and its own contribution is the **lineage**:
naming, for every number it hands back, which owner produced it and how
fresh its inputs were. W1-15 asks for exactly that, and it is the half a
private decision surface cannot omit — a win probability with no stated
projection source or coverage is not intelligence, it is a number.

**Scheduled, live and final assembly.** Actual scores and canonical lineups
remain available while game-state coverage is incomplete. The remaining-
production policy lives in `game_day_week` (observed clock first, labelled
wall-time fallback, withheld with a named reason otherwise); nothing here
selects one. Final results need complete factual scoring evidence.

**Three different lineup quantities, never conflated.** ``actualLineup`` is
the CURRENT scoring lineup (points already scored); ``expectedLineup`` is
the ILLUSTRATIVE lineup that optimizing individual MEAN projections implies;
``outcome.expectedFinalBestBall`` is the mean of the OPTIMIZED lineup over
simulation draws. The last is not the total of the second — optimizing
means and averaging optimized outcomes are different statistics.

**Acquisition seams.** ``_observe_live_state`` and
``_weekly_projection_fetches`` are the only places live inputs are
acquired. Both are flag-gated (default OFF), bounded, and memoised
in-process as an INTERIM until the shared background collector (Game Day
U5) supplies them; a collector replaces these two functions and nothing
else.

**Private, and league-scoped.** Projections, win probabilities and roster
weaknesses are proprietary decision intelligence under CLAUDE.md §5 — this
never routes through `/api/public/league/*` and nothing here is added to the
public contract.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from src.api import roster_intelligence as _roster_intelligence
from src.public_league import sleeper_client
from src.ros.game_day_estimates import (
    BASIS_LABELS,
    WEEKLY_FEATURE_DISABLED,
    WEEKLY_SOURCE_LABEL,
    GameDayEstimates,
    resolve_game_day_estimates,
)
from src.ros.game_day_sim import (
    DEFAULT_SEED,
    LEVERAGE_DEFINITION,
    TeamWeekOutcome,
    get_cached_league_week_simulation,
)
from src.ros.game_day_week import (
    GameDayWeekRefusal,
    ObservedSlate,
    actual_lineup,
    merge_game_evidence,
    observed_game_evidence,
    resolve_scoring_week,
    schedule_game_evidence,
)
from src.ros.lineup import (
    OBJECTIVE_REALIZED_POINTS,
    RosterPlayer,
    player_eligible_for_slot,
    resolve_starter_slots,
    solve_optimal_assignment,
)

#: Draws for the league-week simulation. NOT `game_day_sim.DEFAULT_DRAWS`
#: (10,000) — this endpoint runs synchronously in a web request, so it uses
#: a smaller count named explicitly here, so the payload can report what it
#: actually ran rather than implying a precision it did not buy.  The SEED
#: is `game_day_sim.DEFAULT_SEED` — one default, not two.
DEFAULT_DRAWS = 2000

__all__ = ["DEFAULT_DRAWS", "DEFAULT_SEED", "build_matchup_intel"]

# ── Interim acquisition memo (replaced by the U5 collector) ──────────────
#
# A browser polls every 60 s; without a memo every poll would hit ESPN and
# Sleeper.  Both memos are process-local and bounded.  They are NOT the
# durable store the collector will be: a restart after kickoff forgets the
# pre-kickoff weekly observations, and those players then fall back to the
# preseason basis (counted in lineage as ``noPreKickoffObservation``) rather
# than being given an in-game observation as their baseline.

#: Reuse one scoreboard observation for this long (well inside
#: ``game_day_week.LIVE_STATE_MAX_AGE_SECONDS``).
_LIVE_STATE_TTL_SEC = 20.0
#: Refetch weekly projections at most this often.
_WEEKLY_FETCH_TTL_SEC = 600.0

_memo_lock = threading.Lock()
_live_state_memo: dict[tuple[int, int], tuple[float, Any]] = {}
_weekly_memo: dict[tuple[int, int], list[Any]] = {}


class MatchupIntelError(RuntimeError):
    """Base for a request that cannot be answered as asked."""


class WeekInProgress(MatchupIntelError):
    """The week has begun; pregame intelligence is no longer the question."""


class TeamNotInLeague(MatchupIntelError):
    """The requested owner holds no roster in this league."""


@dataclass(frozen=True)
class _LeagueFetch:
    league: dict[str, Any]
    users: list[dict[str, Any]]
    rosters: list[dict[str, Any]]
    matchups: list[dict[str, Any]]
    players: dict[str, Any]
    fetched_at: float


def _fetch_league_week(sleeper_league_id: str, week: int) -> _LeagueFetch:
    """Everything the resolver needs, through the shared cached client.

    `sleeper_client` holds a 60s in-process TTL cache, so a burst of
    requests for the same league-week costs one round trip. Nothing new
    is fetched here that some other surface does not already fetch.
    """
    return _LeagueFetch(
        league=sleeper_client.fetch_league(sleeper_league_id) or {},
        users=sleeper_client.fetch_users(sleeper_league_id),
        rosters=sleeper_client.fetch_rosters(sleeper_league_id),
        matchups=sleeper_client.fetch_matchups(sleeper_league_id, week),
        players=sleeper_client.fetch_nfl_players(),
        fetched_at=time.time(),
    )


def _schedule_context(season: int) -> tuple[list[Mapping[str, Any]], float | None, float]:
    """``(rows, observed_at, now)`` for this season's cached nflverse schedule.

    One shared read so `_game_evidence` and the NFL slate below never fetch
    the same cache twice for one request. Read-only against the existing
    schedule cache; no request-path acquisition owner.
    """
    from src.bdvm.schedule import fetch_schedule_rows
    from src.nfl_data.cache import entry_age_seconds
    from src.nfl_data.ingest import cache_key

    now = time.time()
    rows = fetch_schedule_rows(season, cache_only=True)
    age = entry_age_seconds(cache_key("schedules", [season]))
    observed = now - age if age is not None else None
    return rows, observed, now


def _game_evidence(
    season: int, week: int, rows: list[Mapping[str, Any]], observed_at: float | None, now: float
):
    """Read the existing schedule cache; no request-path acquisition owner.

    nflverse is a schedule/result feed, not a live opportunity feed.
    Its age is published and a passed kickoff alone stays unknown.
    """
    return schedule_game_evidence(rows, season=season, week=week, observed_at=observed_at, now=now)


def _observe_live_state(season: int, week: int):
    """One ESPN scoreboard observation for ``week`` (flag ``game_day_live_game_state``).

    Flag off -> an explicit disabled snapshot with no network call.  On,
    one observation is reused for ``_LIVE_STATE_TTL_SEC``; a failed read is
    returned as the failure it is (never memoised as "no games").
    """
    from src.nfl_data.live_game_state import fetch_live_game_state

    key = (int(season), int(week))
    now = time.time()
    with _memo_lock:
        hit = _live_state_memo.get(key)
        if hit is not None and now - hit[0] <= _LIVE_STATE_TTL_SEC:
            return hit[1]
    snapshot = fetch_live_game_state(week=int(week), season_type=2)
    if snapshot.ok and snapshot.enabled:
        with _memo_lock:
            _live_state_memo[key] = (now, snapshot)
    return snapshot


def _prune_weekly_history(fetches: list[Any], kickoffs: Sequence[float]) -> list[Any]:
    """Keep only fetches that can still be some game's last pre-kickoff read.

    Fetch ``i`` (ordered by ``observed_at``) is needed iff a kickoff lies in
    ``[observed_i, observed_{i+1})``; the newest fetch is always kept.
    """
    from datetime import datetime

    ordered = sorted(fetches, key=lambda f: f.observed_at or "")
    stamps = [datetime.fromisoformat(f.observed_at).timestamp() for f in ordered]
    keep = []
    for i, fetch in enumerate(ordered):
        if i == len(ordered) - 1:
            keep.append(fetch)
            continue
        if any(stamps[i] <= k < stamps[i + 1] for k in kickoffs):
            keep.append(fetch)
    return keep


def _weekly_projection_fetches(
    season: int, week: int, kickoffs: Sequence[float]
) -> tuple[tuple[Any, ...], str, str | None]:
    """``(fetches, state, reason)`` — weekly projection observations for the lock.

    Flag ``sleeper_weekly_projections`` off -> ``feature_disabled`` with no
    network call (the fetcher refuses by itself).  On, at most one fetch per
    ``_WEEKLY_FETCH_TTL_SEC``; rows without a game id (Sleeper's
    no-projection placeholders) are not retained.
    """
    from dataclasses import replace
    from datetime import datetime

    from src.ros.sleeper_weekly_projections import fetch_weekly_projection_rows

    key = (int(season), int(week))
    now = time.time()
    with _memo_lock:
        history = list(_weekly_memo.get(key, ()))
    newest = history[-1] if history else None
    fresh = newest is not None and (
        now - datetime.fromisoformat(newest.observed_at).timestamp() <= _WEEKLY_FETCH_TTL_SEC
    )
    if not fresh:
        result = fetch_weekly_projection_rows(int(season), int(week))
        if result.status == "feature_disabled":
            return (), WEEKLY_FEATURE_DISABLED, result.reason
        if result.status != "ok":
            if not history:
                return (result,), result.status, result.reason
        else:
            slim = replace(result, rows=tuple(r for r in result.rows if r.get("game_id")))
            history = _prune_weekly_history([*history, slim], kickoffs)
            with _memo_lock:
                _weekly_memo[key] = history
    return tuple(history), "ok", None


def _nfl_slate(
    *,
    season: int,
    week: int,
    rows: list[Mapping[str, Any]],
    observed_at: float | None,
    now: float,
    team_week: Mapping[str, Any],
    my_roster_id: str,
    opponent_roster_id: str | None,
    players_meta: Mapping[str, Any],
    observed: ObservedSlate | None = None,
) -> dict[str, Any]:
    """The week's complete real NFL schedule, this matchup's players attached to their game.

    Where the live feed observed a game, its observed state, phase, period
    and clock replace the schedule cache's (``stateSource`` names
    which), so the slate and the probabilities read the same game state.

    Never reorders by fantasy relevance (the ordering is `schedule_games`'s
    own chronological one, taken verbatim). A bye-week player and a player
    with no resolvable NFL team are both real, distinct facts — neither is
    silently dropped, and neither is guessed into a game it is not in.
    """
    from src.ros.game_day_week import _normalize_nfl_team, schedule_games

    if not rows:
        return {
            "scheduleState": "unavailable",
            "scheduleUnavailableReason": "no cached nflverse schedule for this season",
            "observedAt": observed_at,
            "games": [],
            "byeWeek": [],
            "unattributed": [],
        }

    games = schedule_games(rows, season=season, week=week, now=now)
    game_payloads = {
        g.game_id: {
            "gameId": g.game_id,
            "homeTeam": g.home_team,
            "awayTeam": g.away_team,
            "kickoffAt": g.kickoff_at,
            "state": g.state,
            "homeScore": g.home_score,
            "awayScore": g.away_score,
            "stateSource": "nflverse:schedules",
            "phase": None,
            "period": None,
            "clockSeconds": None,
            "remainingFraction": None,
            "remainingReason": None,
            "players": [],
        }
        for g in games
    }
    for ev in observed.evidence.values() if observed else ():
        row = game_payloads.get(ev.game_id)
        if row is None or row["stateSource"] != "nflverse:schedules":
            continue
        row.update(
            state=ev.state,
            stateSource=ev.source,
            phase=ev.phase,
            period=ev.period,
            clockSeconds=ev.clock_seconds,
            remainingFraction=ev.remaining_fraction,
            remainingReason=ev.remaining_reason,
        )
    payload_by_team: dict[str, dict[str, Any]] = {}
    for g in games:
        payload_by_team[g.home_team] = game_payloads[g.game_id]
        payload_by_team[g.away_team] = game_payloads[g.game_id]

    bye_week: list[dict[str, Any]] = []
    unattributed: list[dict[str, Any]] = []
    for side_label, roster_id in (("team", my_roster_id), ("opponent", opponent_roster_id)):
        tw = team_week.get(roster_id) if roster_id else None
        if not tw:
            continue
        for p in tw.players:
            meta = players_meta.get(p.player_id) or {}
            nfl_team = _normalize_nfl_team(meta.get("team"))
            entry = {
                "playerId": p.player_id,
                "name": str(meta.get("full_name") or p.player_id),
                "side": side_label,
                "nflTeam": nfl_team or None,
                "state": p.state,
                "pointsScored": p.points_scored,
                "projectedRemaining": p.projected_remaining,
                "fantasyPositions": list(p.fantasy_positions),
            }
            if not nfl_team:
                unattributed.append({**entry, "reason": "no NFL team on file for this player"})
            elif nfl_team in payload_by_team:
                payload_by_team[nfl_team]["players"].append(entry)
            else:
                bye_week.append(entry)

    return {
        "scheduleState": "available",
        "observedAt": observed_at,
        "games": [game_payloads[g.game_id] for g in games],
        "byeWeek": bye_week,
        "unattributed": unattributed,
    }


def _live_state_lineage(observed: ObservedSlate) -> dict[str, Any]:
    return {
        "source": "espn:scoreboard",
        "flag": "game_day_live_game_state",
        "state": observed.state,
        "reason": observed.reason,
        "observedAt": observed.observed_at,
        "stale": observed.stale,
        "maxAgeSeconds": _live_state_max_age(),
        "unmatchedGameIds": list(observed.unmatched_game_ids),
    }


def _weekly_census_field(name: str) -> str | None:
    """A field of the weekly source's census entry (``None`` if absent)."""
    try:
        from src.ros import projection_source_census as census

        entry = census.get_source("sleeperWeeklyProjections") or {}
    except Exception:  # noqa: BLE001 — lineage detail, never fatal
        return None
    return entry.get(name)


def _weekly_licensing_status() -> str | None:
    """The census's own licensing status for the weekly source."""
    return _weekly_census_field("licensingStatus")


def _live_state_max_age() -> float:
    from src.ros.game_day_week import LIVE_STATE_MAX_AGE_SECONDS

    return LIVE_STATE_MAX_AGE_SECONDS


def _resolve_estimates(
    season: int, scoring_settings: Mapping[str, Any]
) -> tuple[dict[str, float], str | None, tuple[str, ...], tuple[str, ...]]:
    """``(name -> per-game points, source label, loaded, unavailable)``.

    Deliberately the SAME resolution `scripts/capture_game_day_predictions.py`
    performs, including its honesty: the only live `PROJECTION_MODEL` sources
    are `PRESEASON_FULL_SEASON` horizon, so this is a full-season
    projection's per-game figure and the label says so rather than implying
    a weekly projection exists. Any failure yields no estimates, which the
    resolver records as `unknown` throughout — never 0.0.
    """
    try:
        from src.ros.game_day_capture import estimate_index_from_ensemble
        from src.ros.projection_ensemble import build_ros_full_season_ensemble

        result = build_ros_full_season_ensemble(
            season=season, scoring_settings=dict(scoring_settings or {})
        )
    except Exception:  # noqa: BLE001 — a missing snapshot must not lose the matchup
        return {}, None, (), ()

    if not result.ensemble:
        return (
            {},
            None,
            tuple(result.sources_loaded),
            tuple(result.sources_unavailable),
        )
    return (
        estimate_index_from_ensemble(result.ensemble),
        f"ros_ensemble:{result.horizon}:equal_family_mean",
        tuple(result.sources_loaded),
        tuple(result.sources_unavailable),
    )


def _archive_evidence(league_key: str, season: int, week: int) -> dict[str, Any]:
    """When the perishable pregame archive last recorded this league-week.

    Spec §7 / row W1-26 ask the Game Day surface to show an archive
    timestamp, and the reason is worth stating: the archive is the ONLY
    record of what was knowable before the outcome, and a surface that
    silently shows nothing when nothing was captured cannot be told apart
    from one whose capture ran. So the three states stay distinct —
    captured (with the real `captured_at`), not captured, and unreadable.

    `captured_at` is stamped by `record_snapshot` from the real clock and
    is never accepted from a caller, so it proves WHEN a capture ran. It
    does not prove the week was unplayed when it did; `capture_kind` is
    what carries that claim, and it travels here unchanged.
    """
    try:
        from src.ros.game_day_archive import load_snapshots_for_week

        snaps = load_snapshots_for_week(league_key, int(season), int(week))
    except Exception as exc:  # noqa: BLE001 — optional evidence, never fatal
        return {"state": "unreadable", "reason": f"{type(exc).__name__}: {exc}"}
    if not snaps:
        # NOT an error: a week before the capture unit was deployed, or
        # before this week's capture window, genuinely has none.
        return {"state": "not_captured", "teamsCaptured": 0}
    kinds = sorted({s.capture_kind for s in snaps})
    return {
        "state": "captured",
        "teamsCaptured": len(snaps),
        "captureKinds": kinds,
        # The EARLIEST capture is the pregame evidence; a later one is a
        # different observation, not a fresher version of the same one.
        "capturedAt": min(s.captured_at for s in snaps),
        "latestCapturedAt": max(s.captured_at for s in snaps),
    }


def _owner_by_roster(rosters: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    return {
        str(r.get("roster_id")): str(r.get("owner_id") or "")
        for r in rosters
        if r.get("roster_id") is not None
    }


def _team_labels(users: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, str]]:
    """ownerId -> display/team name, from the host's own fields.

    Same fallback ladder `src/public_league/identity.py` uses, because a
    manager with no custom team name must read the same on both surfaces.
    """
    out: dict[str, dict[str, str]] = {}
    for u in users:
        oid = str(u.get("user_id") or "")
        if not oid:
            continue
        meta = u.get("metadata") or {}
        display = str(u.get("display_name") or "")
        out[oid] = {
            "displayName": display or f"Owner {oid}",
            "teamName": str(meta.get("team_name") or "") or display or f"Owner {oid}",
        }
    return out


def _expected_lineup(
    players: Sequence[Any],
    starter_slots: Sequence[str],
    players_meta: Mapping[str, Any],
) -> dict[str, Any]:
    """The ILLUSTRATIVE lineup that optimizing individual MEAN projections implies.

    A DIFFERENT quantity from the simulation, and labelled as one: the
    simulation re-solves the assignment on every draw, so no single lineup
    is "the" answer, and ``projectedTotal`` here is NOT the expected final
    best-ball total (that is ``outcome.expectedFinalBestBall``, the mean of
    optimized draws). Each player's value is banked points plus the mean of
    his remaining production (pregame: just the mean projection).

    A player with no estimate is not in the pool at all; he is reported so
    the reader can see the lineup was chosen from an incomplete board.
    """
    pool: list[RosterPlayer] = []
    unpriced: list[str] = []
    for p in players:
        if p.projected_remaining is None:
            unpriced.append(p.player_id)
            continue
        banked = float(p.points_scored) if p.points_scored is not None else 0.0
        pool.append(
            RosterPlayer(
                player_id=p.player_id,
                canonical_name=str(
                    (players_meta.get(p.player_id) or {}).get("full_name") or p.player_id
                ),
                position=p.position,
                ros_value=banked + float(p.projected_remaining),
                fantasy_positions=p.fantasy_positions,
            )
        )
    if not pool:
        return {
            "slots": [],
            "projectedTotal": None,
            "unpricedPlayerIds": tuple(unpriced),
            "basis": "optimized_individual_means",
        }

    slot_list = list(starter_slots)
    assignment = solve_optimal_assignment(pool, slot_list, objective=OBJECTIVE_REALIZED_POINTS)
    slots = []
    total = 0.0
    # The solver returns ``{slot_INDEX: player}``. The index is meaningless
    # to a reader, and two RB seats share the name "RB", so publish both:
    # the name to read and the index to disambiguate them.
    for slot_index, player in sorted(assignment.items()):
        # `ros_value` CANNOT be None here — only priced players entered the
        # pool above, and each carries its estimate. Reading it directly
        # rather than `or 0.0` keeps that an invariant: if it is ever broken
        # this raises, instead of quietly publishing a fabricated 0.0 point
        # projection for a player nobody priced.
        value = float(player.ros_value)
        total += value
        slots.append(
            {
                "slot": slot_list[slot_index],
                "slotIndex": slot_index,
                "playerId": player.player_id,
                "name": player.canonical_name,
                "position": player.position,
                "projectedPoints": round(value, 2),
            }
        )
    return {
        "slots": slots,
        "projectedTotal": round(total, 2),
        "unpricedPlayerIds": tuple(unpriced),
        # Named so a reader never mistakes this for the expected final
        # best-ball total (the mean of optimized draws).
        "basis": "optimized_individual_means",
    }


def _outcome_payload(
    outcome: TeamWeekOutcome | None, opponent: TeamWeekOutcome | None = None
) -> dict[str, Any] | None:
    if outcome is None:
        return None
    return {
        # The mean of the OPTIMIZED best-ball total over draws — the expected
        # final score.  Deliberately distinct from expectedLineup.projectedTotal.
        "expectedFinalBestBall": round(outcome.projected_mean, 2),
        # Expected final margin over the scheduled opponent: the difference
        # of the two expected finals from the SAME joint draws (the mean of
        # the per-draw margin equals the difference of the means).  A pure
        # projection of values computed above, published so the UI never
        # subtracts; ``None`` when there is no simulated opponent.
        "expectedMarginVsOpponent": (
            round(outcome.projected_mean - opponent.projected_mean, 2)
            if opponent is not None
            else None
        ),
        "playerLineupPct": dict(outcome.player_lineup_pct),
        "gameLeverage": [dict(row) for row in outcome.game_leverage],
        "winMatchupPct": outcome.win_matchup_pct,
        "tieMatchupPct": outcome.tie_matchup_pct,
        "beatMedianPct": outcome.beat_median_pct,
        "beatMedianState": outcome.beat_median_state,
        "projectedMean": round(outcome.projected_mean, 2),
        "projectedP10": round(outcome.projected_p10, 2),
        "projectedP50": round(outcome.projected_p50, 2),
        "projectedP90": round(outcome.projected_p90, 2),
        "pointsBanked": round(outcome.points_banked, 2),
        "jointTwoZeroPct": outcome.joint_2_0_pct,
        "jointOneOneH2hPct": outcome.joint_1_1_h2h_pct,
        "jointOneOneMedianPct": outcome.joint_1_1_median_pct,
        "jointZeroTwoPct": outcome.joint_0_2_pct,
        "unsimulablePlayerIds": list(outcome.unsimulable_player_ids),
        "notes": list(outcome.notes),
    }


def build_matchup_intel(
    *,
    league_key: str,
    sleeper_league_id: str,
    owner_id: str,
    season: int,
    week: int,
    contract: Mapping[str, Any] | None = None,
    team_count: int | None = None,
    roster_settings: Mapping[str, Any] | None = None,
    draws: int = DEFAULT_DRAWS,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """One team's scheduled, live, or final matchup intelligence for ``week``."""
    fetched = _fetch_league_week(sleeper_league_id, week)
    if not fetched.rosters:
        raise MatchupIntelError(f"{league_key}: the host returned no rosters")

    owner_by_roster = _owner_by_roster(fetched.rosters)
    roster_by_owner = {v: k for k, v in owner_by_roster.items() if v}
    my_roster_id = roster_by_owner.get(str(owner_id))
    if not my_roster_id:
        raise TeamNotInLeague(str(owner_id))

    slots, slot_source = resolve_starter_slots(
        roster_positions=fetched.league.get("roster_positions"),
        roster_settings=dict(roster_settings or {}) or None,
    )
    if not slots:
        raise MatchupIntelError(
            f"{league_key}: no starter slots resolved from the host or the registry"
        )

    scoring_card = fetched.league.get("scoring_settings") or {}
    preseason, preseason_source, sources_loaded, sources_unavailable = _resolve_estimates(
        season, scoring_card
    )

    schedule_rows, schedule_observed_at, schedule_now = _schedule_context(season)
    schedule_evidence = _game_evidence(
        season, week, schedule_rows, schedule_observed_at, schedule_now
    )
    observed = observed_game_evidence(
        _observe_live_state(season, week),
        schedule_rows=schedule_rows,
        season=season,
        week=week,
        now=schedule_now,
    )
    evidence = merge_game_evidence(schedule_evidence, observed)
    kickoffs_by_team = {t: g.kickoff_at for t, g in evidence.items() if g.kickoff_at is not None}
    weekly_fetches, weekly_state, weekly_reason = _weekly_projection_fetches(
        season, week, sorted(set(kickoffs_by_team.values()))
    )
    rostered_ids = sorted(
        {str(pid) for r in fetched.rosters for pid in (r.get("players") or ()) if pid}
    )
    try:
        estimates = resolve_game_day_estimates(
            player_ids=rostered_ids,
            players_meta=fetched.players,
            scoring_settings=scoring_card,
            season=season,
            week=week,
            now=schedule_now,
            preseason_by_name=preseason,
            preseason_source=preseason_source,
            sources_loaded=sources_loaded,
            sources_unavailable=sources_unavailable,
            weekly_fetches=weekly_fetches,
            weekly_state=weekly_state,
            weekly_reason=weekly_reason,
            kickoffs_by_team=kickoffs_by_team,
        )
    except Exception as exc:  # noqa: BLE001 — a bad input must not lose the matchup
        estimates = GameDayEstimates(
            by_player_id={},
            weekly_state="error",
            weekly_reason=f"{type(exc).__name__}: {exc}",
            preseason_source=None,
        )
    estimate_source = estimates.source_label

    try:
        scoring = resolve_scoring_week(
            league_key=league_key,
            league_payload=fetched.league,
            rosters=fetched.rosters,
            matchups=fetched.matchups,
            players_meta=fetched.players,
            starter_slots=slots,
            estimates_by_player_id=estimates.points_by_player_id(),
            estimate_source=estimate_source,
            game_evidence=evidence,
            now=schedule_now,
        )
    except GameDayWeekRefusal as exc:
        if "already begun" in str(exc):
            raise WeekInProgress(str(exc)) from exc
        raise MatchupIntelError(str(exc)) from exc

    resolution = scoring.week
    opponent_roster_id = resolution.opponents.get(my_roster_id)

    # The simulation runs over the WHOLE league because the median leg's
    # threshold is derived from every team's drawn score in the same
    # iteration; simulating two teams would answer a different question.
    #
    # Every manager in this league asking about the SAME week is asking
    # this identical question, so this goes through the shared cache
    # rather than `simulate_league_week` directly — measured at
    # dynasty_main's real scale (12 teams, ~45 active players each,
    # draws=2000), a cold call takes ~19s and a cache hit ~1ms. See
    # `get_cached_league_week_simulation`'s own docstring for the
    # invalidation rule and why the cache cannot live under `data/ros/`.
    simulation = None
    sim_error: str | None = None
    # Do not simulate while any player's remaining production cannot be
    # stated (overtime, delay, stale feed …) or while any player's game
    # STATE is unknown (a passed kickoff with no live observation): either
    # would draw a number for football we cannot see. An UNPRICED player
    # (no baseline from any source) is excluded and reported, exactly as
    # pregame — that is a coverage gap, not an unknown game state.
    unknown_state = [
        p.player_id for t in resolution.teams for p in t.players if p.state == "unknown"
    ]
    can_simulate = not scoring.progress_unavailable_player_ids and (
        scoring.mode == "pregame" or not unknown_state
    )
    if scoring.mode != "final" and can_simulate and resolution.estimate_coverage[0] > 0:
        try:
            simulation = get_cached_league_week_simulation(
                rules=resolution.rules,
                teams=resolution.teams,
                opponents=resolution.opponents,
                season=season,
                week=week,
                draws=draws,
                seed=seed,
            )
        except Exception as exc:  # noqa: BLE001 — report, never fabricate
            sim_error = f"{type(exc).__name__}: {exc}"

    outcomes = {t.team_id: t for t in (simulation.teams if simulation else ())}
    labels = _team_labels(fetched.users)
    team_week = {t.team_id: t for t in resolution.teams}
    est_by_id = estimates.by_player_id

    def _player_row(p: Any, outcome: TeamWeekOutcome | None) -> dict[str, Any]:
        est = est_by_id.get(p.player_id)
        return {
            "playerId": p.player_id,
            "name": str((fetched.players.get(p.player_id) or {}).get("full_name") or p.player_id),
            "state": p.state,
            "nflGameId": p.nfl_game_id,
            "pointsScored": p.points_scored,
            "projectedRemaining": p.projected_remaining,
            "remainingBasis": scoring.remaining_basis.get(p.player_id),
            "progressUnavailableReason": scoring.progress_unavailable_reasons.get(p.player_id),
            # The PROVIDER's pregame weekly baseline, kept separate from
            # our derived rest-of-game forecast (projectedRemaining).
            "projectionBasis": est.basis if est else None,
            "projectionFamilies": list(est.families) if est else [],
            "providerBaselinePoints": round(est.provider_points, 2) if est else None,
            "imputedPoints": round(est.imputed_points, 2) if est else None,
            "imputedScoringKeys": list(est.imputed_keys) if est else [],
            "uncoveredScoringKeys": list(est.uncovered_keys) if est else [],
            "providerAsOf": est.provider_as_of if est else None,
            "finalLineupPct": (outcome.player_lineup_pct.get(p.player_id) if outcome else None),
            "fantasyPositions": list(p.fantasy_positions),
        }

    def _side(roster_id: str | None) -> dict[str, Any] | None:
        if not roster_id:
            return None
        oid = owner_by_roster.get(roster_id) or ""
        label = labels.get(oid, {"displayName": f"Roster {roster_id}", "teamName": ""})
        tw = team_week.get(roster_id)
        side: dict[str, Any] = {
            "ownerId": oid or None,
            "rosterId": roster_id,
            "displayName": label["displayName"],
            "teamName": label["teamName"],
            "outcome": _outcome_payload(
                outcomes.get(roster_id), outcomes.get(resolution.opponents.get(roster_id) or "")
            ),
            "expectedLineup": (
                _expected_lineup(tw.players, slots, fetched.players)
                if tw and scoring.mode != "final"
                else None
            ),
            "unpricedPlayerIds": list(resolution.unpriced_player_ids.get(roster_id, ())),
            "ineligiblePlayerIds": list(resolution.ineligible_player_ids.get(roster_id, ())),
        }
        if tw:
            outcome = outcomes.get(roster_id)
            side["players"] = [_player_row(p, outcome) for p in tw.players]
            side["uncoveredScoringKeys"] = sorted(
                {
                    k
                    for p in tw.players
                    for k in (
                        est_by_id[p.player_id].uncovered_keys if p.player_id in est_by_id else ()
                    )
                }
            )
        if tw and scoring.mode != "pregame":
            side["actualScore"] = scoring.host_scores.get(roster_id)
            side["actualLineup"] = actual_lineup(tw, resolution.rules, fetched.players)
            side["pointsBanked"] = side["actualLineup"]["total"]
            current_ids = {s["playerId"] for s in side["actualLineup"]["slots"]}
            possibilities = []
            for p in tw.players:
                if p.state not in {"not_started", "in_progress", "unknown"}:
                    continue
                candidate = RosterPlayer(
                    player_id=p.player_id,
                    canonical_name=str(
                        (fetched.players.get(p.player_id) or {}).get("full_name") or p.player_id
                    ),
                    position=p.position,
                    ros_value=p.points_scored,
                    fantasy_positions=p.fantasy_positions,
                )
                eligible_slots = [
                    {"slot": slot, "slotIndex": i}
                    for i, slot in enumerate(slots)
                    if player_eligible_for_slot(slot, candidate)
                ]
                if eligible_slots:
                    possibilities.append(
                        {
                            "playerId": p.player_id,
                            "name": candidate.canonical_name,
                            "state": p.state,
                            "currentOptimal": p.player_id in current_ids,
                            "eligibleSlots": eligible_slots,
                        }
                    )
            side["remainingLineupPossibilities"] = possibilities
            side["remainingEligiblePlayerIds"] = [p["playerId"] for p in possibilities]
            side["result"] = None
            if scoring.mode == "final":
                other = scoring.host_scores.get(resolution.opponents.get(roster_id))
                own = side["actualScore"]
                if own is not None and other is not None:
                    side["result"] = "WIN" if own > other else "LOSS" if own < other else "TIE"
                # A final result is a fact, not a forecast distribution.
                side["outcome"] = None
        if contract and oid:
            # REUSE, not recomputation: the canonical roster-intelligence
            # owner's own answer for this team. `TeamNotInLeague` here means
            # the CONTRACT does not hold the team (a different fact from the
            # host not holding it), so it degrades to null rather than
            # failing the whole matchup.
            try:
                intel = _roster_intelligence.get_team_roster_intelligence(
                    contract, oid, team_count=team_count
                )
                side["rosterIntelligence"] = intel.get("team")
            except _roster_intelligence.TeamNotInLeague:
                side["rosterIntelligence"] = None
            except Exception:  # noqa: BLE001 — optional context, never fatal
                side["rosterIntelligence"] = None
        else:
            side["rosterIntelligence"] = None
        return side

    priced, active = resolution.estimate_coverage
    notes = list(resolution.notes)
    reasons_by_kind: dict[str, list[str]] = {}
    for pid, why in sorted(scoring.progress_unavailable_reasons.items()):
        reasons_by_kind.setdefault(why, []).append(pid)
    basis_counts: dict[str, int] = {}
    for est in est_by_id.values():
        basis_counts[est.basis] = basis_counts.get(est.basis, 0) + 1
    if sim_error:
        notes.append(f"simulation unavailable: {sim_error}")
    if opponent_roster_id is None:
        notes.append("no scheduled opponent for this team in this week")

    return {
        "leagueKey": league_key,
        "season": season,
        "week": week,
        "mode": scoring.mode,
        "probabilityState": (
            "FINAL"
            if scoring.mode == "final"
            else "LIVE_PROGRESS_UNAVAILABLE"
            if scoring.progress_unavailable_player_ids
            else "GAME_STATE_OR_SCORING_UNAVAILABLE"
            if not can_simulate
            else "AVAILABLE"
            if simulation
            else "UNAVAILABLE"
        ),
        "progressUnavailablePlayerIds": list(scoring.progress_unavailable_player_ids),
        # reason -> player ids, e.g. {"overtime": [...]} — a withheld
        # probability always names why.
        "progressUnavailableReasons": reasons_by_kind,
        "unknownStatePlayerIds": unknown_state if scoring.mode != "pregame" else [],
        "recapUrl": f"/league/articles/{season}/{week}" if scoring.mode == "final" else None,
        "team": _side(my_roster_id),
        "opponent": _side(opponent_roster_id),
        "nflSlate": _nfl_slate(
            season=season,
            week=week,
            rows=schedule_rows,
            observed_at=schedule_observed_at,
            now=schedule_now,
            team_week=team_week,
            my_roster_id=my_roster_id,
            opponent_roster_id=opponent_roster_id,
            players_meta=fetched.players,
            observed=observed,
        ),
        # Everything a reader needs to decide how much to trust the numbers
        # above, and which owner produced each of them. W1-15.
        "lineage": {
            "projectionSource": estimate_source,
            "projectionHorizonNote": (
                (
                    f"weekly projections ({WEEKLY_SOURCE_LABEL}) locked at each game's "
                    "kickoff; players without one use a preseason full-season "
                    "per-game average — a FALLBACK, NOT a current-week forecast — "
                    "labelled per player"
                )
                if estimates.weekly_state == "ok"
                else "preseason full-season per-game average — a FALLBACK, NOT a "
                "current-week forecast; no WEEKLY-horizon projection is in use"
                f" (weekly source: {estimates.weekly_state})"
            )
            if estimate_source
            else None,
            "projectionBasisCounts": basis_counts,
            # How many INDEPENDENT weekly projection families actually
            # contribute (one per census providerFamily). 1 today (RotoWire
            # via Sleeper): a one-family state is never a multi-source ensemble.
            "projectionFamiliesContributing": len(
                {f for e in est_by_id.values() for f in e.families}
            ),
            # Human wording for each basis, so the fallback can never be read
            # as the weekly projection.
            "projectionBasisLabels": {b: BASIS_LABELS[b] for b in sorted(basis_counts)},
            # The ensemble behind the preseason FALLBACK basis, by its own name.
            "preseasonProjectionSource": estimates.preseason_source,
            "weeklyProjection": {
                "sourceLabel": WEEKLY_SOURCE_LABEL,
                "flag": "sleeper_weekly_projections",
                "state": estimates.weekly_state,
                "reason": estimates.weekly_reason,
                "asOf": estimates.weekly_as_of,
                "observedAt": estimates.weekly_observed_at,
                "counts": dict(estimates.weekly_counts),
                # Read from the census, never restated here.
                "licensingStatus": _weekly_licensing_status(),
                "accessPosture": _weekly_census_field("accessPosture"),
                # Per weekly source (family, state, lock counts); one family
                # is one vote however many of its products are wired.
                "sources": {k: dict(v) for k, v in estimates.weekly_sources.items()},
            },
            "ambiguousNamePlayerIds": list(estimates.ambiguous_name_player_ids),
            "remainingProductionMethod": (
                "remaining = pregame provider baseline x observed share of regulation "
                "left (observed_clock); banked points are never subtracted from the "
                "baseline; overtime/delay/postponement/stale feed withhold the "
                "probability with a named reason"
            ),
            "leverageDefinition": LEVERAGE_DEFINITION,
            "projectionSourcesLoaded": list(sources_loaded),
            "projectionSourcesUnavailable": list(sources_unavailable),
            "estimateCoverage": {"priced": priced, "active": active},
            "starterSlotSource": slot_source,
            "starterSlots": list(slots),
            "bestBall": resolution.rules.best_ball,
            "medianEnabled": resolution.rules.median_enabled,
            "teamCount": resolution.rules.team_count,
            "sleeperFetchedAt": fetched.fetched_at,
            "gameEvidence": {
                team: {
                    "state": g.state,
                    "source": g.source,
                    "observedAt": g.observed_at,
                    "kickoffAt": g.kickoff_at,
                    "gameId": g.game_id,
                    "phase": g.phase,
                    "period": g.period,
                    "clockSeconds": g.clock_seconds,
                    "remainingFraction": g.remaining_fraction,
                    "remainingReason": g.remaining_reason,
                }
                for team, g in scoring.game_evidence.items()
            },
            "liveGameState": _live_state_lineage(observed),
            "gameStateLimitation": (
                "observed ESPN scoreboard (quarter/clock/status) where available; "
                "nflverse schedule/result cache otherwise"
                if observed.state == "observed"
                else "nflverse schedule/result cache only; live game state "
                f"{observed.state} ({observed.reason}) — a passed kickoff stays unknown"
            ),
            # W1-26: the perishable pregame archive's own timestamp, with
            # "nothing was captured" kept distinct from "we could not read
            # the archive".
            "archive": _archive_evidence(league_key, int(season), int(week)),
            "contractScrapeTimestamp": (
                ((contract or {}).get("meta") or {}).get("scrapeTimestamp")
                if isinstance(contract, Mapping)
                else None
            ),
            "simulation": (
                {
                    "modelVersion": simulation.model_version,
                    "pointsModelSource": simulation.points_model_source,
                    "draws": simulation.draws,
                    "seed": simulation.seed,
                    "thresholdSemantics": simulation.threshold_semantics,
                    "thresholdSemanticsVerified": simulation.threshold_semantics_verified,
                    "notes": list(simulation.notes),
                    # Honest freshness, matching this module's own stated
                    # purpose: a number computed 90 minutes ago and one
                    # computed 30 seconds ago should not read the same.
                    "cached": simulation.cached,
                    "cacheComputedAt": simulation.cache_computed_at,
                }
                if simulation
                else None
            ),
        },
        "notes": notes,
    }
