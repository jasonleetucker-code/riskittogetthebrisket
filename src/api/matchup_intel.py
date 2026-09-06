"""Private Week-N matchup intelligence for one team (W1-14 / W1-15).

**It computes nothing of its own.** Every number here is produced by a
canonical owner and copied:

| quantity | owner |
|---|---|
| which players are on the roster, IR/taxi subtraction | `src/ros/game_day_capture.py` |
| the league's starter slots and who is legal in each | `src/ros/lineup.py` |
| the expected best-ball lineup | `src/ros/lineup.solve_optimal_assignment` |
| per-player weekly distribution, win % / beat-median % | `src/ros/game_day_sim.py` |
| resolving a live league-week into those inputs | `src/ros/game_day_week.py` |
| projections | `src/ros/projection_ensemble.py` |
| roster strength / weakness / age-value | `src/api/roster_intelligence.py` |
| the league's identity and rules | `src/api/league_registry.py` + the host |

This module is the assembly, and its own contribution is the **lineage**:
naming, for every number it hands back, which owner produced it and how
fresh its inputs were. W1-15 asks for exactly that, and it is the half a
private decision surface cannot omit — a win probability with no stated
projection source or coverage is not intelligence, it is a number.

**PREGAME. It refuses a week in progress**, because `game_day_week` does:
telling a finished player from a mid-game one needs a live game-state feed
this repo does not wire, and collapsing them double-projects. The refusal
is a distinct error code so a caller can say "come back after the games"
rather than rendering an error.

**Private, and league-scoped.** Projections, win probabilities and roster
weaknesses are proprietary decision intelligence under CLAUDE.md §5 — this
never routes through `/api/public/league/*` and nothing here is added to the
public contract.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from src.api import roster_intelligence as _roster_intelligence
from src.public_league import sleeper_client
from src.ros.game_day_sim import TeamWeekOutcome, simulate_league_week
from src.ros.game_day_week import GameDayWeekRefusal, resolve_pregame_week
from src.ros.lineup import RosterPlayer, resolve_starter_slots, solve_optimal_assignment

#: Draws for the league-week simulation. The simulator's own default; named
#: here so the payload can report what it ran rather than implying a
#: precision it did not buy.
DEFAULT_DRAWS = 2000
DEFAULT_SEED = 20260905


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
    """The best-ball lineup at the MEAN estimate.

    A DIFFERENT quantity from the simulation, and labelled as one: the
    simulation re-solves this assignment on every draw, so no single lineup
    is "the" answer. This is the lineup the mean projection implies — useful
    to a manager, and never presented as the simulated outcome.

    A player with no estimate is not in the pool at all; he is reported so
    the reader can see the lineup was chosen from an incomplete board.
    """
    pool: list[RosterPlayer] = []
    unpriced: list[str] = []
    for p in players:
        if p.projected_remaining is None:
            unpriced.append(p.player_id)
            continue
        pool.append(
            RosterPlayer(
                player_id=p.player_id,
                canonical_name=str(
                    (players_meta.get(p.player_id) or {}).get("full_name") or p.player_id
                ),
                position=p.position,
                ros_value=float(p.projected_remaining),
                fantasy_positions=p.fantasy_positions,
            )
        )
    if not pool:
        return {"slots": [], "projectedTotal": None, "unpricedPlayerIds": tuple(unpriced)}

    slot_list = list(starter_slots)
    assignment = solve_optimal_assignment(pool, slot_list)
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
    }


def _outcome_payload(outcome: TeamWeekOutcome | None) -> dict[str, Any] | None:
    if outcome is None:
        return None
    return {
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
    """One team's pregame matchup intelligence for ``week``."""
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

    estimates, estimate_source, sources_loaded, sources_unavailable = _resolve_estimates(
        season, fetched.league.get("scoring_settings") or {}
    )

    try:
        resolution = resolve_pregame_week(
            league_key=league_key,
            league_payload=fetched.league,
            rosters=fetched.rosters,
            matchups=fetched.matchups,
            players_meta=fetched.players,
            starter_slots=slots,
            estimates=estimates,
            estimate_source=estimate_source,
        )
    except GameDayWeekRefusal as exc:
        if "already begun" in str(exc):
            raise WeekInProgress(str(exc)) from exc
        raise MatchupIntelError(str(exc)) from exc

    opponent_roster_id = resolution.opponents.get(my_roster_id)

    # The simulation runs over the WHOLE league because the median leg's
    # threshold is derived from every team's drawn score in the same
    # iteration; simulating two teams would answer a different question.
    simulation = None
    sim_error: str | None = None
    if resolution.estimate_coverage[0] > 0:
        try:
            simulation = simulate_league_week(
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
            "outcome": _outcome_payload(outcomes.get(roster_id)),
            "expectedLineup": (
                _expected_lineup(tw.players, slots, fetched.players) if tw else None
            ),
            "unpricedPlayerIds": list(resolution.unpriced_player_ids.get(roster_id, ())),
            "ineligiblePlayerIds": list(resolution.ineligible_player_ids.get(roster_id, ())),
        }
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
    if sim_error:
        notes.append(f"simulation unavailable: {sim_error}")
    if opponent_roster_id is None:
        notes.append("no scheduled opponent for this team in this week")

    return {
        "leagueKey": league_key,
        "season": season,
        "week": week,
        "mode": "pregame",
        "team": _side(my_roster_id),
        "opponent": _side(opponent_roster_id),
        # Everything a reader needs to decide how much to trust the numbers
        # above, and which owner produced each of them. W1-15.
        "lineage": {
            "projectionSource": estimate_source,
            "projectionHorizonNote": (
                "per-game figure from a full-season projection; no live "
                "WEEKLY-horizon projection source exists"
                if estimate_source
                else None
            ),
            "projectionSourcesLoaded": list(sources_loaded),
            "projectionSourcesUnavailable": list(sources_unavailable),
            "estimateCoverage": {"priced": priced, "active": active},
            "starterSlotSource": slot_source,
            "starterSlots": list(slots),
            "bestBall": resolution.rules.best_ball,
            "medianEnabled": resolution.rules.median_enabled,
            "teamCount": resolution.rules.team_count,
            "sleeperFetchedAt": fetched.fetched_at,
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
                }
                if simulation
                else None
            ),
        },
        "notes": notes,
    }
