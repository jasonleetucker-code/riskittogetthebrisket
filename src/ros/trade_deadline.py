"""Per-team buyer/seller deadline dashboard.

Combines:
  - Cached ROS team-strength snapshot (data/ros/team_strength/latest.json)
  - Cached ROS playoff sim output (or recomputes if cache is missing)
  - Cached ROS championship sim output
  - Sleeper roster age profile (from the live overlay)

Returns one row per team with the direction label + recommendation.
Lazy-section friendly — call ``build_section(snapshot)`` from the
public contract.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.ros import ROS_DATA_DIR
from src.ros.direction import build_roster_age_profile, classify_team
from src.ros.team_strength import load_or_compute_team_strength
from src.utils.unknown import Unknown, stamp

LOG = logging.getLogger("ros.trade_deadline")


#: Availability states of one league's cached simulation file.
SIM_LOADED = "loaded"
SIM_MISSING = "missing"
SIM_UNREADABLE = "unreadable"

#: Why a section has no simulation at all: the snapshot's league could not be
#: resolved to a registry key, so there is no league whose file to read.
SIM_REASON_LEAGUE_UNRESOLVED = "league_unresolved"


def _sim_file(kind: str, league_key: str | None) -> Path:
    """This league's cached ``kind`` ("playoff" / "championship") sim file.

    The filename rule is the WRITER's (``src.ros.scrape._sim_paths``): the
    default league keeps the historical ``latest_*.json`` names, every other
    league its own ``<leagueKey>_*.json``.  Reused, never restated -- the
    same arrangement ``playoff_sim._cached_payload_path`` has -- and rooted
    at this module's ``ROS_DATA_DIR`` so the reader and the writer agree.

    LI1842-DEFECT-12: this used to read ``latest_*.json`` for EVERY league, so
    a non-default league's teams were classified from the default league's
    simulation.  A league with no file of its own now reads as missing.
    """
    from src.ros.scrape import _sim_paths  # noqa: PLC0415 - heavy module

    try:
        from src.api.league_registry import default_league_key  # noqa: PLC0415

        default_key = default_league_key()
    except Exception:  # noqa: BLE001 - registry trouble reads the default file
        default_key = None
    playoff, championship = _sim_paths(league_key, default_key)
    name = playoff.name if kind == "playoff" else championship.name
    return ROS_DATA_DIR / "sims" / name


def _load_sim_map(
    kind: str, rows_key: str, league_key: str | None
) -> tuple[dict[str, dict[str, float]], str]:
    """``(rows keyed by ownerId, availability state)`` for one league's sim."""
    path = _sim_file(kind, league_key)
    if not path.exists():
        return {}, SIM_MISSING
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}, SIM_UNREADABLE
    if not isinstance(payload, dict):
        return {}, SIM_UNREADABLE
    rows = payload.get(rows_key) or []
    return {str(r.get("ownerId") or ""): r for r in rows if r.get("ownerId")}, SIM_LOADED


def _load_playoff_odds_map(league_key: str | None = None) -> dict[str, dict[str, float]]:
    """This league's cached ROS playoff-odds output, keyed by ownerId."""
    return _load_sim_map("playoff", "playoffOdds", league_key)[0]


def _load_championship_map(league_key: str | None = None) -> dict[str, dict[str, float]]:
    """This league's cached ROS championship output, keyed by ownerId."""
    return _load_sim_map("championship", "championshipOdds", league_key)[0]


def simulation_availability(league_key: str | None, *, resolved: bool = True) -> dict[str, Any]:
    """Which league's simulation the section read, and whether it exists.

    Published beside the rows so "this league has no simulation" and "every
    team is covered" cannot read alike; an empty row list alone says neither.

    ``resolved=False`` means the caller could not resolve its league at all:
    nothing is read (the default league's ``latest_*.json`` is NOT this
    league's simulation), both kinds are ``missing`` and the reason names the
    unresolved league.
    """
    if not resolved:
        return {
            "leagueKey": None,
            "leagueResolved": False,
            "playoff": SIM_MISSING,
            "championship": SIM_MISSING,
            "reason": SIM_REASON_LEAGUE_UNRESOLVED,
        }
    return {
        "leagueKey": league_key,
        "leagueResolved": True,
        "playoff": _load_sim_map("playoff", "playoffOdds", league_key)[1],
        "championship": _load_sim_map("championship", "championshipOdds", league_key)[1],
    }


def build_team_directions(
    *,
    league_key: str | None = None,
    teams: list[dict[str, Any]] | None = None,
    playoff_odds_map: dict[str, dict[str, float]] | None = None,
    championship_map: dict[str, dict[str, float]] | None = None,
    team_strength_map: dict[str, dict[str, Any]] | None = None,
    read_simulations: bool = True,
) -> list[dict[str, Any]]:
    """Compose direction labels for every team that has any input data.

    All maps are keyed by ownerId.  When a map is empty (e.g. no
    cached sim yet), the missing dimension defaults to 0 — the
    classifier degrades cleanly.

    ``read_simulations=False`` (the caller's league is unresolved) reads no
    cached sim file: an unresolved league has no simulation of its own, and
    the default league's is never substituted.
    """
    if read_simulations:
        playoffs = playoff_odds_map or _load_playoff_odds_map(league_key)
        champs = championship_map or _load_championship_map(league_key)
    else:
        playoffs = playoff_odds_map or {}
        champs = championship_map or {}
    strengths = team_strength_map or {}
    if not strengths:
        snap = load_or_compute_team_strength(league_key) or []
        strengths = {str(r.get("ownerId") or ""): r for r in snap if r.get("ownerId")}

    owner_ids = sorted(set(playoffs) | set(champs) | set(strengths))
    if not owner_ids:
        return []

    out: list[dict[str, Any]] = []
    for owner in owner_ids:
        # AUDIT N-2 — the worst single finding in the 2026-08-04 audit.
        #
        # ``owner_ids`` unions three maps, so an owner present in only
        # ONE of them still gets a row. The odds were then read with
        # ``or 0.0``, and 0% playoff odds routes straight to "Seller":
        # "Sell aging win-now players. Prioritize 2026/2027 picks."
        #
        # Measured on the live file: data/ros/sims/latest_playoff.json
        # carries 8 rows for a 12-team league, so FOUR managers were
        # told to sell for no reason other than absence from an input —
        # and one of them was ranked #1 in the league on ROS strength
        # (percentile 1.000). Missing data did not merely degrade the
        # answer; it produced a confident, inverted instruction about
        # the best team in the league, on two surfaces.
        #
        # An owner we cannot measure now gets NO direction rather than
        # a fabricated one. The row is still emitted — the manager
        # exists and hiding them would be its own lie — but it carries
        # nulls, a machine-readable reason, and a label that says so.
        po_raw = (playoffs.get(owner) or {}).get("playoffOdds")
        co_raw = (champs.get(owner) or {}).get("championshipOdds")
        missing_inputs = [
            name
            for name, value in (("playoffOdds", po_raw), ("championshipOdds", co_raw))
            if not isinstance(value, (int, float))
        ]
        if missing_inputs:
            out.append(
                _unmeasurable_team(owner, strengths.get(owner) or {}, champs, missing_inputs)
            )
            continue

        po = float(po_raw)
        co = float(co_raw)
        strength_row = strengths.get(owner) or {}
        # team_strength snapshot doesn't carry a percentile by itself;
        # rank/length is the cheapest proxy.
        rank = float(strength_row.get("rank") or 0.0)
        total = max(1.0, float(len(strengths) or 1))
        strength_pct = (total - rank + 1) / total if rank > 0 else 0.0
        team_obj = next((t for t in (teams or []) if t.get("ownerId") == owner), None)
        roster_age = build_roster_age_profile(team_obj.get("players") or []) if team_obj else {}
        direction = classify_team(
            playoff_odds_pct=po,
            championship_odds_pct=co,
            team_ros_strength_percentile=strength_pct,
            roster_age_profile=roster_age,
        )
        out.append(
            {
                "ownerId": owner,
                "displayName": strength_row.get("teamName")
                or (champs.get(owner) or {}).get("displayName")
                or owner,
                "playoffOdds": po,
                "championshipOdds": co,
                "rosStrengthPercentile": round(strength_pct, 4),
                "rank": rank,
                **direction,
            }
        )

    # Unmeasurable teams sort last in every direction rather than
    # sorting as if they were the worst — a null championship chance is
    # not a zero one, and the audit's whole point is that the two must
    # not render alike.
    def _sort_key(row: dict[str, Any]) -> tuple[int, float]:
        odds = row.get("championshipOdds")
        if not isinstance(odds, (int, float)):
            # Sorted by the leading 1, never by this number — but it is
            # written as the best possible odds rather than ``or 0.0``
            # so that if the leading term is ever dropped, unmeasurable
            # teams surface at the top where someone notices, instead of
            # sinking to the bottom where they read as the worst.
            return (1, -1.0)
        return (0, -float(odds))

    out.sort(key=_sort_key)
    return out


def _unmeasurable_team(
    owner: str,
    strength_row: dict[str, Any],
    champs: dict[str, Any],
    missing_inputs: list[str],
) -> dict[str, Any]:
    """A row for a manager the sim did not cover.

    Emitted rather than dropped: the manager is real, and silently
    omitting them would replace one wrong answer with a different one
    (the league would appear to have fewer teams than it does). What is
    withheld is the *recommendation*, which is the part that was
    fabricated.

    ``label`` deliberately does not reuse any of the seven buy/sell
    verbs. "Insufficient evidence" is not a position on the spectrum
    between buying and selling; it is a refusal to place the team on
    that spectrum at all, and a consumer switching on the label must
    not be able to mistake it for a mild one.
    """
    reason = Unknown(
        reason="team_absent_from_sim",
        detail=(
            "no rest-of-season simulation covers this manager, so buy/sell "
            "direction cannot be derived. Missing: " + ", ".join(missing_inputs)
        ),
        field="playoffOdds",
        context={"ownerId": owner, "missingInputs": missing_inputs},
    )
    row: dict[str, Any] = {
        "ownerId": owner,
        "displayName": strength_row.get("teamName")
        or (champs.get(owner) or {}).get("displayName")
        or owner,
        "rosStrengthPercentile": None,
        "rank": strength_row.get("rank"),
        "label": "Insufficient evidence",
        "recommendation": (
            "No rest-of-season simulation covers this team, so there is no "
            "basis for a buy or sell call. This is not a neutral rating."
        ),
        "summary": "Not covered by the current rest-of-season simulation.",
        "measurable": False,
    }
    stamp(row, "playoffOdds", reason)
    stamp(row, "championshipOdds", reason)
    return row


def build_section(snapshot: Any) -> dict[str, Any]:
    """Lazy-section builder for /api/public/league/rosTradeDeadline."""
    # Team-strength rows are roster-derived and therefore leagueKey-scoped
    # (see team_strength.resolve_snapshot_league_key's docstring) — this
    # used to discard `snapshot` entirely and read whichever league's
    # persisted team-strength file happened to be the DEFAULT one,
    # regardless of which league this section was being built for.
    #
    # The sim maps follow the same league (LI1842-DEFECT-12): they used to
    # be hardcoded to `data/ros/sims/latest_*.json` whatever the league.
    from src.ros.team_strength import resolve_snapshot_league_key  # noqa: PLC0415

    league_key = resolve_snapshot_league_key(snapshot)
    # An unresolved league (unknown root id, registry failure) has no
    # simulation file of its own: it reads as missing, named unresolved,
    # never as the default league's `latest_*.json`.
    resolved = league_key is not None
    return {
        "teams": build_team_directions(league_key=league_key, read_simulations=resolved),
        "simulation": simulation_availability(league_key, resolved=resolved),
    }
