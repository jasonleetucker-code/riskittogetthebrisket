"""Per-team buyer/seller deadline dashboard.

Combines:
  - Cached ROS team-strength snapshot (data/ros/team_strength/latest.json)
  - Cached ROS playoff sim output (or recomputes if cache is missing)
  - Cached ROS championship sim output
  - Roster ages, joined from the team-strength snapshot's ``fullRoster``
    player ids against ``snapshot.nfl_players`` — see ``teams_with_ages``

Returns one row per team with the direction label + recommendation.
Lazy-section friendly — call ``build_section(snapshot)`` from the
public contract.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.ros import ROS_DATA_DIR
from src.ros.direction import build_roster_age_profile, classify_team
from src.ros.team_strength import load_team_strength_snapshot

LOG = logging.getLogger("ros.trade_deadline")

DIRECTION_ENGINE = "ros.direction"
"""Which team-direction model produced these rows.

The app has TWO, on purpose, and they are not interchangeable — see
``build_section``. Every direction-bearing payload stamps its engine so
"Seller" from simulated odds and "rebuild" from roster shape can never
be mistaken for the same claim about the same team (audit W20-F006)."""



def _load_playoff_odds_map() -> dict[str, dict[str, float]]:
    """Read the latest cached ROS playoff-odds output, keyed by ownerId."""
    path = ROS_DATA_DIR / "sims" / "latest_playoff.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    rows = payload.get("playoffOdds") or []
    return {str(r.get("ownerId") or ""): r for r in rows if r.get("ownerId")}


def _load_championship_map() -> dict[str, dict[str, float]]:
    path = ROS_DATA_DIR / "sims" / "latest_championship.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    rows = payload.get("championshipOdds") or []
    return {str(r.get("ownerId") or ""): r for r in rows if r.get("ownerId")}


def build_team_directions(
    *,
    teams: list[dict[str, Any]] | None = None,
    playoff_odds_map: dict[str, dict[str, float]] | None = None,
    championship_map: dict[str, dict[str, float]] | None = None,
    team_strength_map: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Compose direction labels for every team that has any input data.

    All maps are keyed by ownerId.  When a map is empty (e.g. no
    cached sim yet), the missing dimension defaults to 0 — the
    classifier degrades cleanly.
    """

    def _odds_or_none(row: dict[str, Any] | None, key: str) -> float | None:
        """Odds for one owner, or ``None`` when they were not simulated.

        Distinguishes three states the old ``or 0.0`` collapsed into one:
        the owner is missing from the map, the key is missing, and the
        value really is 0.0. Only the last is a fact about the team.
        """
        if not isinstance(row, dict) or key not in row:
            return None
        raw = row.get(key)
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    playoffs = playoff_odds_map or _load_playoff_odds_map()
    champs = championship_map or _load_championship_map()
    strengths = team_strength_map or {}
    if not strengths:
        snap = load_team_strength_snapshot() or []
        strengths = {str(r.get("ownerId") or ""): r for r in snap if r.get("ownerId")}

    owner_ids = sorted(set(playoffs) | set(champs) | set(strengths))
    if not owner_ids:
        return []

    out: list[dict[str, Any]] = []
    for owner in owner_ids:
        # ``None`` when this owner is absent from the simulation, so the
        # classifier can abstain. ``or 0.0`` used to turn "not simulated"
        # into a confident 0% and therefore into "Seller" — see
        # ``classify_team`` (W17-F002 / W20-F002). A genuine simulated 0.0
        # still reads as 0.0 and still classifies.
        po = _odds_or_none(playoffs.get(owner), "playoffOdds")
        co = _odds_or_none(champs.get(owner), "championshipOdds")
        strength_row = strengths.get(owner) or {}
        # team_strength snapshot doesn't carry a percentile by itself;
        # rank/length is the cheapest proxy.
        rank = float(strength_row.get("rank") or 0.0)
        total = max(1.0, float(len(strengths) or 1))
        # ``None`` when this owner has no strength row: a team we could
        # not rank is not a team ranked last. The summary renders it as
        # "unavailable" rather than "0%".
        strength_pct = (total - rank + 1) / total if rank > 0 else None
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
                "rosStrengthPercentile": (
                    round(strength_pct, 4) if strength_pct is not None else None
                ),
                "rank": rank,
                "directionEngine": DIRECTION_ENGINE,
                **direction,
            }
        )

    # Unsimulated teams sort last rather than crashing the sort or
    # masquerading as 0.0 contenders at the bottom of the board.
    out.sort(key=lambda r: (r["championshipOdds"] is None, -(r["championshipOdds"] or 0.0)))
    return out


def teams_with_ages(snapshot: Any) -> list[dict[str, Any]]:
    """Rosters shaped for ``build_team_directions(teams=...)``.

    ``[{ownerId, players: [{position, age}]}]``, joined from two things
    that were both already here and never introduced to each other:

    * the team-strength snapshot's ``fullRoster`` — ownerId + playerId +
      position for all 12 rosters (57 players on the live board), and
    * ``snapshot.nfl_players`` — Sleeper's player dump, which carries
      ``age``.  The public pipeline already reads it this way in
      ``awards.py``, ``records.py`` and ``player_journey.py``.

    ``build_section`` used to do ``_ = snapshot`` under a comment saying
    "roster ages come from team_strength snapshot directly".  They do
    not: ``fullRoster`` rows carry ``position`` and ``rosValue`` and no
    age at all, so ``build_roster_age_profile`` was never called on any
    production path and all 12 rows shipped ``ageProfile: {}``.  The
    "Strong Seller / Rebuilder" band, gated on ``vetCount >= 4``, was
    structurally unreachable (audit W17-F010 / W20-F016).

    Returns ``[]`` when either input is missing, so the caller keeps the
    empty age profile and the classifier keeps abstaining from the
    age-gated band — a missing age is not a young player.
    """
    rows = load_team_strength_snapshot() or []
    dump = getattr(snapshot, "nfl_players", None)
    if not rows or not isinstance(dump, dict) or not dump:
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        owner = str(row.get("ownerId") or "").strip()
        if not owner:
            continue
        players: list[dict[str, Any]] = []
        for entry in row.get("fullRoster") or []:
            if not isinstance(entry, dict):
                continue
            meta = dump.get(str(entry.get("playerId") or "")) or {}
            age = meta.get("age") if isinstance(meta, dict) else None
            # No age from Sleeper stays None. ``build_roster_age_profile``
            # skips it rather than counting it as young OR veteran.
            players.append({"position": entry.get("position"), "age": age})
        out.append({"ownerId": owner, "players": players})
    return out


def build_section(snapshot: Any) -> dict[str, Any]:
    """Lazy-section builder for /api/public/league/rosTradeDeadline.

    ``directionEngine`` stamps which of the app's direction models
    produced these labels.  There are two, they answer different
    questions from different input families, and until this stamp
    existed a consumer had no way to tell them apart:

    * ``ros.direction`` (here) — buyer/seller off SIMULATED playoff and
      championship odds.
    * ``roster_intel.window`` (``/api/gameplan``, ``/phases``,
      ``/rosters``) — a five-state distribution over measured roster
      shape (lineup competitiveness x starter age).
    """
    return {
        "teams": build_team_directions(teams=teams_with_ages(snapshot)),
        "directionEngine": DIRECTION_ENGINE,
    }
