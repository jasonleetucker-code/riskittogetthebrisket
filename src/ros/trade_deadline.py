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
from typing import Any

from src.ros import ROS_DATA_DIR
from src.ros.direction import build_roster_age_profile, classify_team
from src.ros.team_strength import load_team_strength_snapshot

LOG = logging.getLogger("ros.trade_deadline")

# Where a row's odds came from.  Borrowed verbatim from the vocabulary
# ``src/api/gameplan.py`` already stamps as ``oddsSource`` so the two
# surfaces describe the same state with the same word.
ODDS_SOURCE_SIMULATED = "simulated"
ODDS_SOURCE_NOT_SIMULATED = "owner_not_in_simulation"

# The direction payload for a manager the simulator never saw.  Shaped
# like ``classify_team``'s return so consumers spread it identically, but
# it deliberately carries no buy/sell verb: there is nothing to base one
# on, and the previous behaviour — coercing absence to 0.0 odds — is what
# told the league's strongest roster to sell.
DIRECTION_NOT_SIMULATED: dict[str, Any] = {
    "label": "Not simulated",
    "summary": "This manager was not in the simulated season, so there are no odds to read.",
    "recommendation": (
        "No direction call. This team joined after the most recent simulated "
        "season, so the playoff and championship sims never included it — that "
        "is missing input, not a 0% forecast. It will get a call once a season "
        "it played in is simulated."
    ),
    "ageProfile": {},
}


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
        # ── "absent from the sim" is not "0% chance" ──────────────────
        # ``owner_ids`` is the UNION of the two sim maps and the
        # team-strength snapshot, so an owner can arrive here with a
        # roster and no simulated season at all — four of this league's
        # twelve managers joined after the most recent simulated year.
        # Coercing that absence to 0.0 handed ``classify_team`` a
        # confident zero and it duly returned "Seller — sell aging
        # win-now players" to the strongest roster in the league.
        # Say "not simulated" instead of inventing a number.
        po_row = playoffs.get(owner)
        co_row = champs.get(owner)
        strength_row = strengths.get(owner) or {}
        if po_row is None and co_row is None:
            out.append(
                {
                    "ownerId": owner,
                    "displayName": strength_row.get("teamName") or owner,
                    "playoffOdds": None,
                    "championshipOdds": None,
                    "oddsSource": ODDS_SOURCE_NOT_SIMULATED,
                    "rosStrengthPercentile": None,
                    "rank": float(strength_row.get("rank") or 0.0),
                    **DIRECTION_NOT_SIMULATED,
                }
            )
            continue

        # Present in the sim: a missing field here really is zero.
        po = float((po_row or {}).get("playoffOdds") or 0.0)
        co = float((co_row or {}).get("championshipOdds") or 0.0)
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
                # Stamped on BOTH branches: "these odds are simulated" and
                # "this field is missing" must not read the same.
                "oddsSource": ODDS_SOURCE_SIMULATED,
                "rosStrengthPercentile": round(strength_pct, 4),
                "rank": rank,
                **direction,
            }
        )

    # Unsimulated teams have no odds to rank by, so they sort last rather
    # than sorting as if they were the worst team in the league.
    out.sort(key=lambda r: (r["championshipOdds"] is None, -(r["championshipOdds"] or 0.0)))
    return out


def build_section(snapshot: Any) -> dict[str, Any]:
    """Lazy-section builder for /api/public/league/rosTradeDeadline."""
    _ = snapshot  # roster ages come from team_strength snapshot directly
    return {
        "teams": build_team_directions(),
    }
