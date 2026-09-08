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
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from src.ros import ROS_DATA_DIR
from src.ros.lineup import RosterPlayer, flatten_starter_slots, optimize_lineup
from src.utils.name_clean import resolve_canonical_name

if TYPE_CHECKING:
    from src.public_league.snapshot import PublicLeagueSnapshot

LOG = logging.getLogger("ros.team_strength")


# Composite weights — can be overridden per-league via settings later;
# PR1 hard-codes the spec-defined defaults.
WEIGHT_STARTING = 0.72
WEIGHT_DEPTH = 0.18
WEIGHT_COVERAGE = 0.05
WEIGHT_HEALTH = 0.05


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
            roster.append(
                RosterPlayer(
                    player_id=str(p.get("playerId") or name),
                    canonical_name=name,
                    position=position or (agg.get("position") or "").upper(),
                    ros_value=float(agg.get("rosValue") or 0.0),
                    confidence=float(agg.get("confidence") or 0.0),
                    injured=bool(p.get("injured")),
                    bye=bool(p.get("bye")),
                    fantasy_positions=fantasy_positions,
                )
            )

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


def hydrate_roster_players(
    player_ids: Iterable[Any],
    nfl_players: dict[str, Any],
) -> list[dict[str, Any]]:
    """Convert a raw Sleeper player-id list into the player-dict shape
    ``compute_team_strength`` expects, with ``canonicalName`` resolved
    against the dynasty identity layer so the lookup matches the
    aggregate's keying.

    Canonical hydration core — moved verbatim (2026-09) from
    ``src/ros/scrape.py::_hydrate_overlay_players``'s inner loop so the
    live-snapshot fallback below and the overlay-based scrape refresh
    share one implementation instead of drifting.
    """
    from src.utils.name_clean import normalize_player_name  # noqa: PLC0415

    out: list[dict[str, Any]] = []
    for pid in player_ids:
        pid_str = str(pid or "")
        meta = nfl_players.get(pid_str) or {}
        # Prefer NFL-dump full name over any caller-supplied name — a
        # caller with an empty id_map would otherwise poison the
        # canonical lookup with a raw player id.
        full_name = (meta.get("full_name") or "").strip()
        if not full_name:
            full_name = (
                f"{meta.get('first_name', '')} {meta.get('last_name', '')}".strip() or pid_str
            )
        position = (meta.get("position") or "").upper()
        # Sleeper evaluates slot eligibility against fantasy_positions,
        # which is often wider than `position` (a DL/LB hybrid is legal
        # in either slot).  Passing it through lets the lineup optimizer
        # reproduce the host's own best-ball choices (LI-3).
        raw_fp = meta.get("fantasy_positions") or []
        fantasy_positions = [str(p).strip().upper() for p in raw_fp if str(p or "").strip()]
        injury = (meta.get("injury_status") or "").upper()
        canonical = normalize_player_name(full_name) or full_name.lower()
        out.append(
            {
                "playerId": pid_str,
                "name": full_name,
                "displayName": full_name,
                "canonicalName": canonical,
                "position": position,
                "fantasyPositions": fantasy_positions,
                "injured": injury in {"OUT", "IR", "PUP", "DOUBTFUL"},
                "bye": False,
            }
        )
    return out


def hydrate_overlay_players(
    teams: list[dict[str, Any]],
    nfl_players: dict[str, Any],
) -> list[dict[str, Any]]:
    """Convert overlay teams (with playerIds + name strings) into the
    shape ``compute_team_strength`` expects.

    Public form of the function formerly private to
    ``src/ros/scrape.py``, which now re-exports this under its old name
    so its one call site is unchanged.
    """
    out: list[dict[str, Any]] = []
    for team in teams:
        ids = team.get("playerIds") or []
        out.append(
            {
                "ownerId": team.get("ownerId"),
                "rosterId": team.get("roster_id") or team.get("rosterId"),
                "teamName": team.get("name") or team.get("teamName") or "",
                "players": hydrate_roster_players(ids, nfl_players),
            }
        )
    return out


def load_ros_aggregate_players() -> list[dict[str, Any]]:
    """Load ``data/ros/aggregate/latest.json``'s player list.

    THE shared loader for that file — ``src/ros/api.py`` previously
    inlined this read at two call sites (``/player-values``, ``/health``)
    with no third owner; this is that owner, added so the live
    team-strength fallback below does not become a third copy.
    """
    path = ROS_DATA_DIR / "aggregate" / "latest.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    players = payload.get("players") if isinstance(payload, dict) else None
    return players if isinstance(players, list) else []


def compute_team_strength_from_snapshot(
    snapshot: "PublicLeagueSnapshot",
    *,
    league_key: str | None = None,
) -> list[dict[str, Any]]:
    """Compute team strength LIVE from a ``PublicLeagueSnapshot`` already
    in hand — no network I/O, no dependency on the scheduled scrape.

    This is the PRIMARY fallback for ``load_or_compute_team_strength``:
    ``snapshot.current_season.rosters`` carries ``owner_id`` / ``roster_id``
    / ``players`` (a raw Sleeper player-id list) and ``snapshot.nfl_players``
    is already populated on the same object, so every input this needs is
    already loaded on any request that has a snapshot at all. Returns
    ``[]`` on any missing precondition; never raises — a fallback that can
    itself fail the request would defeat its own purpose.
    """
    try:
        current = snapshot.current_season
        if current is None or not current.rosters:
            return []

        from src.api.league_registry import get_default_league, get_league_by_key  # noqa: PLC0415
        from src.public_league import metrics  # noqa: PLC0415

        cfg = (get_league_by_key(league_key) if league_key else None) or get_default_league()
        starter_slots = flatten_starter_slots((getattr(cfg, "roster_settings", None) or {}).get("starters"))
        if not starter_slots:
            LOG.warning("[ros] team-strength live fallback: no starter slots for %s", league_key)
            return []

        aggregated = load_ros_aggregate_players()
        if not aggregated:
            LOG.warning("[ros] team-strength live fallback: no ROS aggregate available")
            return []

        nfl_players = snapshot.nfl_players or {}
        teams: list[dict[str, Any]] = []
        for roster in current.rosters:
            owner_id = str(roster.get("owner_id") or "").strip()
            if not owner_id:
                continue
            teams.append(
                {
                    "ownerId": owner_id,
                    "rosterId": roster.get("roster_id"),
                    "teamName": metrics.display_name_for(snapshot, owner_id),
                    "players": hydrate_roster_players(roster.get("players") or [], nfl_players),
                }
            )
        if not teams:
            return []

        return compute_team_strength(
            teams,
            aggregated_players=aggregated,
            starter_slots=starter_slots,
        )
    except Exception as exc:  # noqa: BLE001
        LOG.warning("[ros] team-strength live-from-snapshot failed: %s", exc)
        return []


def compute_team_strength_live(
    league_key: str | None = None,
    *,
    nfl_players: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """SECOND-TIER fallback for callers with no ``PublicLeagueSnapshot`` in
    hand (e.g. ``/api/ros/pick-projections``).  Fetches the Sleeper
    overlay (cached, ``force_refresh=False`` — 15-min TTL + stale-serve +
    per-league single-flight lock, so this rarely hits the network cold)
    and hydrates it the same way the scheduled scrape does.  ``nfl_players``
    is injectable so a caller that already has the ~5 MB NFL dump in hand
    (a snapshot-backed caller should prefer ``compute_team_strength_from_snapshot``
    instead, which never needs it) does not force a second fetch.
    Returns ``[]`` on any failure; never raises.
    """
    try:
        from src.api.league_registry import get_default_league, get_league_by_key  # noqa: PLC0415
        from src.api.sleeper_overlay import fetch_sleeper_overlay  # noqa: PLC0415

        cfg = (get_league_by_key(league_key) if league_key else None) or get_default_league()
        sleeper_league_id = getattr(cfg, "sleeper_league_id", None)
        if not cfg or not sleeper_league_id:
            return []
        starter_slots = flatten_starter_slots((getattr(cfg, "roster_settings", None) or {}).get("starters"))
        if not starter_slots:
            return []

        aggregated = load_ros_aggregate_players()
        if not aggregated:
            return []

        overlay = fetch_sleeper_overlay(sleeper_league_id=sleeper_league_id, force_refresh=False)
        if not overlay or not overlay.get("teams"):
            return []

        if nfl_players is None:
            from src.public_league.sleeper_client import fetch_nfl_players  # noqa: PLC0415

            nfl_players = fetch_nfl_players() or {}

        teams = hydrate_overlay_players(overlay["teams"], nfl_players)
        if not teams:
            return []

        return compute_team_strength(
            teams,
            aggregated_players=aggregated,
            starter_slots=starter_slots,
        )
    except Exception as exc:  # noqa: BLE001
        LOG.warning("[ros] team-strength live overlay fallback failed for %s: %s", league_key, exc)
        return []


# Short-lived memo (successes) + negative cache (failures) for the
# NETWORK-BOUND overlay tier only, keyed on league_key, so N concurrent
# public requests during a cold-start window don't each trigger their own
# overlay refetch.  Deliberately NOT applied to the snapshot tier: that
# tier is free (no network, the snapshot is already in memory), so
# caching it would buy nothing -- and sharing one cache slot between the
# two tiers would let a snapshot-less caller's failure suppress a
# snapshot-bearing caller's cheap, otherwise-successful attempt for up to
# the TTL, which is a worse outcome than the request-storm this guard
# exists to prevent.  Deliberately in-process and unpersisted — this is a
# guard, not a source of truth; the real cache is the snapshot file
# `load_or_compute_team_strength` writes back to disk.
_LIVE_COMPUTE_TTL_SECONDS = 120.0
_live_compute_cache: dict[str | None, tuple[float, list[dict[str, Any]]]] = {}


def load_or_compute_team_strength(
    league_key: str | None = None,
    *,
    snapshot: "PublicLeagueSnapshot | None" = None,
    persist: bool = True,
) -> list[dict[str, Any]]:
    """THE read-side entry point for ``team_ros_strength``.

    Order: the persisted snapshot file (fast path, unchanged behavior)
    → compute live from ``snapshot`` when one was supplied (no network,
    always attempted fresh, never cached — it's free) → compute live from
    the Sleeper overlay (network, TTL-cached).

    This closes the single point of failure where every consumer of
    ``team_ros_strength`` went dark for a full 2h refresh cycle whenever
    the scheduled scrape's write step failed or simply hadn't run yet
    (a fresh deploy, a cold-start window) — the same resilience pattern
    ``src/api/roster_intelligence.py`` already applies to the sibling
    dynasty-value Team Strength concept, applied here to the ROS-production
    concept this module owns.  Never raises; returns ``[]`` only when
    every tier is genuinely unable to answer.
    """
    persisted = load_team_strength_snapshot(league_key)
    if persisted:
        return persisted

    if snapshot is not None:
        rows = compute_team_strength_from_snapshot(snapshot, league_key=league_key)
        if rows:
            _persist_best_effort(rows, league_key=league_key, persist=persist)
            return rows
        # Falls through to the overlay tier below rather than returning
        # [] here -- a snapshot that failed to produce rows (e.g. no
        # roster_settings resolvable) doesn't mean the overlay tier will
        # fail too.

    now = time.monotonic()
    cached = _live_compute_cache.get(league_key)
    if cached is not None and now - cached[0] < _LIVE_COMPUTE_TTL_SECONDS:
        return cached[1]

    rows = compute_team_strength_live(league_key)
    _live_compute_cache[league_key] = (now, rows)

    if rows:
        _persist_best_effort(rows, league_key=league_key, persist=persist)

    return rows


def _persist_best_effort(
    rows: list[dict[str, Any]],
    *,
    league_key: str | None,
    persist: bool,
) -> None:
    if not persist:
        return
    try:
        write_team_strength_snapshot(rows, league_key=league_key)
        LOG.info(
            "[ros] team-strength live fallback: persisted %d rows for %s",
            len(rows),
            league_key,
        )
    except OSError as exc:  # noqa: BLE001
        # Best-effort: a write failure must never fail the request that
        # triggered this fallback -- it just means the next request
        # recomputes instead of reading the persisted file.
        LOG.warning("[ros] team-strength live fallback: persist failed: %s", exc)


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
    """Persist the latest team-strength snapshot to disk.

    Atomic (tmp file + ``Path.replace``, mirroring
    ``snapshot_store._atomic_write_json``): once a public request path
    can trigger a write via ``load_or_compute_team_strength``, a
    concurrent reader must never observe a partially-written file.
    """
    target = _team_strength_path(league_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + f".tmp-{int(time.time() * 1000)}")
    tmp.write_text(json.dumps(rows, indent=2))
    tmp.replace(target)
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
