"""Per-team ROS strength composite for power rankings + buyer/seller.

Composes:

    team_ros_strength
        = 0.72 * starting_lineup_strength
        + 0.18 * best_ball_depth_strength
        + 0.05 * positional_coverage_score
        + 0.05 * health_availability_score

Inputs are pulled live from the league registry + Sleeper overlay (the
same identity layer dynasty rankings use) so a roster change picks up
on the next /api/ros/team-strength call.

The output shape mirrors what ``frontend/app/league/sections/ros-team-strength.jsx``
will render: one row per team, with starter + bench breakdown for the
"why is this team here?" expandable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from src.ros import ROS_DATA_DIR
from src.ros.aggregate import _evidence_basis as _agg_evidence_basis
from src.ros.lineup import RosterPlayer, optimize_lineup
from src.utils.name_clean import resolve_canonical_name


# Composite weights — can be overridden per-league via settings later;
# PR1 hard-codes the spec-defined defaults.
WEIGHT_STARTING = 0.72
WEIGHT_DEPTH = 0.18
WEIGHT_COVERAGE = 0.05
WEIGHT_HEALTH = 0.05


def _team_evidence_basis(proxy_value_share: float | None) -> str:
    """Classify a TEAM by how much of its priced value is a dynasty proxy.

    Reuses the per-row vocabulary from ``aggregate`` so a reader does not
    have to learn two, and adds one state that only exists here:
    ``unpriced``, for a roster with nothing priced at all.  That is not
    ``rest_of_season`` — it is the absence of any evidence, and calling
    it the clean state would be exactly the coercion this unit removes.
    """
    if proxy_value_share is None:
        return "unpriced"
    return _agg_evidence_basis(proxy_value_share)


def compute_team_strength(
    teams: Iterable[dict[str, Any]],
    *,
    aggregated_players: list[dict[str, Any]],
    starter_slots: list[str],
    league: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Compute per-team ROS strength.

    Args:
        teams: each entry must carry ``ownerId`` (or ``rosterId``),
            ``teamName``, and ``players`` (list of {player_id, name, position}
            dicts as produced by the Sleeper overlay).
        aggregated_players: the output of ``src.ros.aggregate.aggregate``;
            we lookup each team's player by ``canonicalName``.
        starter_slots: from the league's roster_settings — the list of
            slot tokens that count toward "starting lineup".
        league: optional league context (currently unused but threaded
            through for future positional-scarcity adjustments).

    Returns:
        A list of team dicts ordered by ``teamRosStrength`` descending,
        ready to serialize as ``data/ros/team_strength/latest.json``.
    """
    _ = league  # placeholder for PR2 scarcity adjustments

    # Index aggregated values by canonical name for O(1) lookup per
    # team-player pair.
    #
    # BOTH SIDES go through ``resolve_canonical_name`` because neither
    # is reliably canonical on its own.  ``src/ros/aggregate.py`` copies
    # each source parser's ``canonical_name`` verbatim, so 16 of 1,087
    # aggregate rows are stored non-lowercase; the roster side falls
    # back to ``displayName`` / ``name``, which never were.  An exact
    # string join therefore drops players for two different reasons.
    #
    # Measured 2026-07-27 on the live 12-team snapshot: 36 roster
    # players were unmapped, and **8 of them map once both sides are
    # canonicalised** — "kam curl" -> "kamren curl", "chig okonkwo" ->
    # "chigoziem okonkwo", plus casing-only misses like "Dax Hill" and
    # "Sauce Gardner".  The other 28 are genuinely unranked by every
    # ROS source, which is the state ``unmapped`` exists to report.
    #
    # This matters beyond the roster page: an unmapped player scores
    # ZERO toward ``teamRosStrength``, which sets the projected
    # reverse-standings draft order behind the Pick Projector. Eight
    # phantom zeroes biased that order.
    #
    # Note ``.lower()`` alone would fix only 14 of the 16 stored names.
    # "Greg Rousseau" and "Chig Okonkwo" need the alias map, which is
    # exactly what ``resolve_canonical_name`` is for, and why the fix
    # is not a casefold.
    #
    # NOT fixed at the writer on purpose: ``canonicalName`` doubles as a
    # DISPLAY fallback (``displayName or canonicalName``) in
    # ``src/api/terminal.py`` and three frontend modules, so
    # normalising what is written would render "cam skattebo" wherever
    # ``displayName`` is absent. The field serves two jobs that want
    # different normalisation; the join is the one that wants this.
    by_name: dict[str, dict[str, Any]] = {}
    for p in aggregated_players:
        key = resolve_canonical_name(p.get("canonicalName") or "")
        if key:
            by_name.setdefault(key, p)

    out: list[dict[str, Any]] = []
    for team in teams:
        roster_players = team.get("players") or []
        roster: list[RosterPlayer] = []
        # Value-weighted dynasty-proxy exposure for this roster.
        priced_value = 0.0
        proxy_value = 0.0
        unmapped: list[str] = []
        for p in roster_players:
            name = p.get("canonicalName") or p.get("displayName") or p.get("name") or ""
            position = (p.get("position") or "").upper()
            # Sleeper's own slot-eligibility field; wider than `position`
            # for hybrids (DL/LB, DB/LB).  Absent for callers that predate
            # LI-3 — RosterPlayer falls back to `position` then.
            fantasy_positions = tuple(
                str(fp).strip().upper()
                for fp in (p.get("fantasyPositions") or ())
                if str(fp or "").strip()
            )
            # ``name`` stays raw for the unmapped list — that list is
            # rendered, so it wants the readable form, not the join key.
            agg = by_name.get(resolve_canonical_name(name))
            if not agg or agg.get("rosValue", 0) <= 0:
                # Player isn't ranked by any ROS source — represented
                # as zero contribution but kept on the unmapped list
                # so the UI can flag "we don't have an ROS read on N
                # of your players".
                #
                # KNOWN BOUNDARY (C2-U1 → C2-U4).  This is a real
                # missing-is-zero coercion and it is left in place
                # DELIBERATELY, not overlooked.  ``RosterPlayer.ros_value``
                # is now ``float | None`` and the canonical owner would
                # treat ``None`` as UNPRICED — excluded from starters and
                # bench, its slot reported unfilled — which is the honest
                # answer.  Passing ``None`` here would therefore change
                # ``health_availability_score`` (its denominator is the
                # starter count) and ``unfilled_slots`` on the live
                # /terminal team-strength composite.
                #
                # That composite is C2-U4's unit ("canonical Team
                # Strength"), which will redefine it against its own
                # evidence.  Moving the number from inside C2-U1 would
                # change a live surface on a lineup unit's authority.
                # Named here so the next reader inherits a decision
                # rather than discovering an accident.
                unmapped.append(name)
                roster.append(
                    RosterPlayer(
                        player_id=str(p.get("playerId") or name),
                        canonical_name=name,
                        position=position,
                        ros_value=0.0,
                        confidence=0.0,
                        injured=bool(p.get("injured")),
                        bye=bool(p.get("bye")),
                        fantasy_positions=fantasy_positions,
                    )
                )
                continue
            # V1-53 / C5-ROS-01.  Carry how much of this player's
            # rest-of-season value rests on a DYNASTY board standing in
            # for rest-of-season evidence.  Weighted by VALUE below, not
            # headcount: a dynasty-priced QB1 and a dynasty-priced 30th
            # man are not the same exposure.
            # No ``or 0.0`` here, and that is a retirement rather than a
            # move.  The guard above already ``continue``s on
            # ``agg.get("rosValue", 0) <= 0``, so by this line the key is
            # present and positive and the coercion was unreachable
            # defensive code.  Hoisting it out of the ``RosterPlayer(...)``
            # call is what made that visible — the baseline had carried it
            # as accepted debt inline.
            _ros_value = float(agg["rosValue"])
            _proxy_share = agg.get("dynastyProxyWeightShare")
            if _proxy_share is not None:
                priced_value += _ros_value
                proxy_value += _ros_value * float(_proxy_share)
            roster.append(
                RosterPlayer(
                    player_id=str(p.get("playerId") or name),
                    canonical_name=name,
                    position=position or (agg.get("position") or "").upper(),
                    ros_value=_ros_value,
                    confidence=float(agg.get("confidence") or 0.0),
                    injured=bool(p.get("injured")),
                    bye=bool(p.get("bye")),
                    fantasy_positions=fantasy_positions,
                )
            )

        # Share of the roster's PRICED value that rests on dynasty
        # proxies.  ``None`` — never 0.0 — when nothing was priced:
        # "measured, and none of it is dynasty" and "we could not
        # measure" are different claims, and 0.0 already means the
        # first.  Unpriced players are in neither numerator nor
        # denominator; they are reported by ``unmappedPlayerCount``, and
        # inventing a basis for a player we could not price would be the
        # original defect under a new name.
        proxy_value_share = (proxy_value / priced_value) if priced_value > 0 else None

        solution = optimize_lineup(roster, starter_slots=starter_slots)
        composite = (
            WEIGHT_STARTING * solution.starting_lineup_score
            + WEIGHT_DEPTH * solution.bench_depth_score
            + WEIGHT_COVERAGE * solution.positional_coverage_score
            + WEIGHT_HEALTH * solution.health_availability_score
        )
        out.append(
            {
                "ownerId": team.get("ownerId"),
                "rosterId": team.get("rosterId"),
                "teamName": team.get("teamName") or team.get("displayName") or "",
                "teamRosStrength": round(composite, 2),
                "startingLineupScore": solution.starting_lineup_score,
                "benchDepthScore": solution.bench_depth_score,
                "positionalCoverageScore": solution.positional_coverage_score,
                "healthAvailabilityScore": solution.health_availability_score,
                # What this team's rest-of-season number rests on.  It is
                # a statement ABOUT the composite, and moves none of it.
                "dynastyProxyValueShare": (
                    None if proxy_value_share is None else round(proxy_value_share, 4)
                ),
                "evidenceBasis": _team_evidence_basis(proxy_value_share),
                "startingLineup": solution.starting_lineup,
                "benchDepth": solution.bench_depth,
                # FULL roster, for consumers that must not read a
                # truncated one.  ``benchDepth`` is capped at
                # ``lineup.DEPTH_BENCH_LIMIT`` (8) because it exists to
                # score depth, not to enumerate the roster — but
                # ``playoff_sim`` was reading starters+bench as if it
                # were the whole team, simulating 29 of 44-58 players.
                # Best ball is exactly the format where the deep bench
                # matters: measured on the 12 real rosters that
                # understates the weekly mean by +1.1 to +9.4 points,
                # varying ~8x by team (deep rosters lose most).  It does
                # NOT reorder any team today — all 12 hold rank under
                # both inputs — so this is "wrong input to a
                # tail-sensitive format", not "wrong answer on screen".
                # Carries fantasyPositions so hybrids keep their real
                # slot eligibility downstream.
                "fullRoster": [
                    {
                        "playerId": p.player_id,
                        "canonicalName": p.canonical_name,
                        "position": p.position,
                        "rosValue": round(float(p.ros_value), 2),
                        "fantasyPositions": list(p.fantasy_positions),
                        "injured": p.injured,
                        "bye": p.bye,
                    }
                    for p in roster
                ],
                "unfilledSlots": solution.unfilled_slots,
                "unmappedPlayerCount": len(unmapped),
                "unmappedPlayers": unmapped[:10],  # cap for payload size
                "weights": {
                    "starting": WEIGHT_STARTING,
                    "depth": WEIGHT_DEPTH,
                    "coverage": WEIGHT_COVERAGE,
                    "health": WEIGHT_HEALTH,
                },
            }
        )

    out.sort(key=lambda t: -float(t.get("teamRosStrength") or 0.0))
    for i, team in enumerate(out, start=1):
        team["rank"] = i
    return out


def _team_strength_path(league_key: str | None = None) -> Path:
    """Resolve the team-strength snapshot path for the given league.

    Default-league snapshots live at the historical
    ``team_strength/latest.json`` path so existing readers (frontend
    cache, health endpoint, lazy section builders) keep working.
    Non-default leagues namespace under ``team_strength/<leagueKey>.json``.
    """
    base = ROS_DATA_DIR / "team_strength"
    if not league_key:
        return base / "latest.json"
    # Resolve aliases — caller may pass a league alias that maps to a
    # canonical key.  Failure-isolated: if the registry can't be read,
    # fall back to using the literal string as the filename.
    resolved = league_key
    try:
        from src.api.league_registry import get_league_by_key, default_league_key  # noqa: PLC0415

        cfg = get_league_by_key(league_key)
        if cfg and cfg.key:
            resolved = cfg.key
        if resolved == default_league_key():
            return base / "latest.json"
    except Exception:  # noqa: BLE001
        pass
    safe = "".join(c for c in resolved if c.isalnum() or c in {"_", "-"})
    return base / f"{safe or 'latest'}.json"


def write_team_strength_snapshot(
    rows: list[dict[str, Any]],
    *,
    league_key: str | None = None,
) -> Path:
    """Persist the latest team-strength snapshot to disk."""
    target = _team_strength_path(league_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(rows, indent=2))
    return target


def load_team_strength_snapshot(
    league_key: str | None = None,
) -> list[dict[str, Any]] | None:
    target = _team_strength_path(league_key)
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text())
    except (json.JSONDecodeError, OSError):
        return None
