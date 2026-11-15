"""Synthetic, deterministic season data for the IDP opportunity tests (no network)."""

from __future__ import annotations

from src.ros.idp_opportunity.leakage import SeasonData
from src.ros.idp_opportunity.model import Card

CARD_SETTINGS = {
    "idp_tkl_solo": 1.33,
    "idp_tkl_ast": 0.8,
    "idp_tkl_loss": 4.24,
    "idp_sack": 2.92,
    "idp_sack_yd": 0.1111111111111111,
    "idp_qb_hit": 2.12,
    "idp_pass_def": 5.3,
    "idp_int": 5.3,
    "idp_ff": 4.24,
    "idp_tkl": 0.0,
    "rec": 1.0,
    "fum_lost": -2.0,
}

#: pid -> (team, family, subgroup)
PLAYERS = {
    "1": ("AAA", "LB", "LB"),
    "2": ("AAA", "DB", "CB"),
    "3": ("AAA", "DL", "EDGE"),
    "4": ("AAA", "DB", "S"),
    "5": ("BBB", "LB", "LB"),
    "6": ("BBB", "DB", "CB"),
    "7": ("BBB", "DL", "DT"),
    "8": ("BBB", "DB", "UNKNOWN"),
    "9": ("BBB", "DL", "EDGE"),  # never plays before week 4 -> no champion
}


def card() -> Card:
    return Card.from_settings(CARD_SETTINGS)


def _line(pid: str, week: int) -> dict:
    seed = int(pid) * 7 + week * 3
    snp = 30 + (seed % 37)
    return {
        "def_snp": float(snp),
        "tm_def_snp": 70.0,
        "idp_tkl_solo": float(seed % 6),
        "idp_tkl_ast": float((seed // 2) % 4),
        "idp_tkl_loss": float(seed % 3 == 0),
        "idp_sack": float(seed % 5 == 0),
        "idp_sack_yd": 7.0 if seed % 5 == 0 else 0.0,
        "idp_qb_hit": float(seed % 4 == 1),
        "idp_pass_def": float(seed % 4 == 2),
        "gp": 1.0,
    }


def season(weeks: int = 5) -> SeasonData:
    stats: dict = {}
    team_of: dict = {}
    offense: dict = {}
    schedule: dict = {}
    for w in range(1, weeks + 1):
        stats[w] = {}
        team_of[w] = {}
        for pid, (team, _, _) in PLAYERS.items():
            if pid == "9" and w < 4:
                continue
            stats[w][pid] = _line(pid, w)
            opp = "BBB" if team == "AAA" else "AAA"
            team_of[w][pid] = (team, opp)
        offense[w] = {
            "AAA": {"dropbacks": 30.0 + w, "wr_targets": 18.0 + w},
            "BBB": {"dropbacks": 40.0 - w, "wr_targets": 22.0},
        }
        schedule[w] = {"AAA": "BBB", "BBB": "AAA"}
    injury = {3: {"AAA": {"4": "Out"}}, 4: {"BBB": {"6": "Doubtful"}}}
    positions = {pid: (fam, sg) for pid, (_, fam, sg) in PLAYERS.items()}
    return SeasonData(
        season=2026,
        stats=stats,
        team_of=team_of,
        offense=offense,
        schedule=schedule,
        injury_report=injury,
        positions=positions,
    )
