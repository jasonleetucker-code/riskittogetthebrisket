"""Pinned synthetic 12-team league for the team-semantics census (2026-11-08).

Synthetic-but-realistic: fixed numbers, no clock, no network, no live board.
The same league is fed to every backend classifier that claims to say
something about a team's strength, direction or equity, so disagreements can
be attributed (different concept vs genuine contradiction) on identical input.
"""

from __future__ import annotations

from typing import Any

from src.bdvm.roster import _directions_relative
from src.roster_intel.marginal import to_roster_players
from src.roster_intel.window import competitive_posture, compute_window, season_timing
from src.ros.championship import _contender_tier
from src.ros.direction import build_roster_age_profile, classify_team

SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"]

# (owner, playoff odds, title odds, lineup scale, lineup age, bdvm now, bdvm future,
#  player equity, pick equity or None=unpriced)
_TEAMS: list[tuple[str, float, float, float, float, float, float, int, int | None]] = [
    ("t01", 0.97, 0.24, 1.00, 27.0, 120.0, 80.0, 61000, 9000),
    ("t02", 0.90, 0.15, 0.95, 26.0, 110.0, 95.0, 58000, 12000),
    ("t03", 0.82, 0.09, 0.90, 30.5, 105.0, 60.0, 55000, 4000),
    ("t04", 0.70, 0.06, 0.85, 25.0, 98.0, 110.0, 52000, 15000),
    ("t05", 0.58, 0.03, 0.80, 28.0, 95.0, 85.0, 50000, 8000),
    ("t06", 0.50, 0.02, 0.75, 31.0, 100.0, 55.0, 49000, None),
    ("t07", 0.41, 0.01, 0.70, 24.5, 80.0, 120.0, 47000, 21000),
    ("t08", 0.33, 0.01, 0.65, 29.5, 85.0, 70.0, 45000, 6000),
    ("t09", 0.22, 0.005, 0.60, 26.5, 75.0, 90.0, 43000, 11000),
    ("t10", 0.12, 0.002, 0.50, 32.0, 90.0, 50.0, 41000, 3000),
    ("t11", 0.06, 0.001, 0.45, 23.5, 60.0, 130.0, 38000, 26000),
    ("t12", 0.03, 0.000, 0.40, 28.5, 70.0, 65.0, 36000, None),
]
OWNERS = [t[0] for t in _TEAMS]
WEEK, IN_SEASON, TRADE_DEADLINE = 9, True, 12


def _roster(scale: float, age: float):
    base = {"qb1": 90, "qb2": 70, "rb1": 60, "rb2": 55, "wr1": 58, "wr2": 52, "te1": 40}
    rows = [
        {
            "playerId": k,
            "canonicalName": k,
            "position": k[:2].upper(),
            "rosValue": v * scale,
            "fantasyPositions": (),
        }
        for k, v in base.items()
    ]
    meta = {k: {"age": age} for k in base}
    return to_roster_players(rows), meta


def build_league() -> dict[str, dict[str, Any]]:
    odds = [{"ownerId": o, "playoffOdds": po, "championshipOdds": co} for o, po, co, *_ in _TEAMS]
    timing = season_timing(WEEK, IN_SEASON, TRADE_DEADLINE)
    ratios = [now / fut for *_, now, fut, _pe, _ke in _TEAMS]
    bdvm_dirs = dict(zip(OWNERS, _directions_relative(ratios)))
    out: dict[str, dict[str, Any]] = {}
    for o, po, co, scale, age, now, fut, player_eq, pick_eq in _TEAMS:
        pool, meta = _roster(scale, age)
        window = compute_window(o, pool, SLOTS, playoff_odds=odds, player_meta=meta)
        posture = competitive_posture(window, timing)
        profile = build_roster_age_profile(
            [{"position": p.position, "age": meta[p.player_id]["age"]} for p in pool]
        )
        direction = classify_team(
            playoff_odds_pct=po,
            championship_odds_pct=co,
            team_ros_strength_percentile=scale,
            roster_age_profile=profile,
        )
        out[o] = {
            "posture": posture.label,  # roster_intel.window (CANONICAL competitive posture)
            "deadlineDirection": direction["label"],  # ros.direction.classify_team
            "contenderTier": _contender_tier(co, po),  # ros.championship presentation label
            "bdvmDirection": bdvm_dirs[o],  # bdvm.roster (fundamental horizon mix)
            "playerEquity": player_eq,
            "pickEquity": pick_eq,
        }
    return out


# Which family each label's vocabulary belongs to, for agreement scoring.
_FAMILY = {
    "PUSH": "contend",
    "RETOOL": "middle",
    "REBUILD": "rebuild",
    "HOLD": "middle",
    "Strong Buyer": "contend",
    "Buyer": "contend",
    "Selective Buyer": "contend",
    "Hold / Evaluate": "middle",
    "Selective Seller": "rebuild",
    "Seller": "rebuild",
    "Strong Seller / Rebuilder": "rebuild",
    "Favorite": "contend",
    "Serious Contender": "contend",
    "Dangerous Playoff Team": "contend",
    "Fringe Playoff Team": "middle",
    "Long Shot": "rebuild",
    "Rebuilder / Seller": "rebuild",
    "contend": "contend",
    "retool": "middle",
    "rebuild": "rebuild",
}


def family(label: str) -> str:
    return _FAMILY[label]


def census_table() -> list[dict[str, Any]]:
    rows = []
    for owner, r in build_league().items():
        fams = {
            "posture": family(r["posture"]),
            "deadline": family(r["deadlineDirection"]),
            "tier": family(r["contenderTier"]),
            "bdvm": family(r["bdvmDirection"]),
        }
        rows.append({"owner": owner, **r, "families": fams, "agree": len(set(fams.values())) == 1})
    return rows
