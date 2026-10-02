"""DraftKings / FanDuel NFL scoring as Sleeper-stat-key rate cards (DFS-AUTO-09).

These let the Calculator's existing raw-stat projections (Sleeper/RotoWire weekly
stat lines, and the keyed SportsDataIO / Fantasy Nerds lanes) be RESCORED per
platform by the existing scorer (``league_intel.scorer`` via
``ros.sleeper_weekly_projections.build_weekly_observations``) instead of
averaging website fantasy totals built on different scoring.

UNVERIFIED — the commonly documented platform scoring, encoded for research
mode.  The official scoring pages refused automated access on 2026-09-30, the
same blocker the rule sets carry.  Known approximation: yardage bonuses
(DraftKings 300 pass / 100 rush / 100 receiving yards) are scored against the
AVERAGE projected stat line, so a projection rarely triggers them — the rescored
DraftKings number is biased LOW for high-volume players, and that is disclosed
on every projection built from these cards.
"""

from __future__ import annotations

_DST_POINTS_ALLOWED = {
    "pts_allow_0": 10.0,
    "pts_allow_1_6": 7.0,
    "pts_allow_7_13": 4.0,
    "pts_allow_14_20": 1.0,
    "pts_allow_21_27": 0.0,
    "pts_allow_28_34": -1.0,
    "pts_allow_35p": -4.0,
}
_DST_EVENTS = {
    "sack": 1.0,
    "int": 2.0,
    "fum_rec": 2.0,
    "safe": 2.0,
    "blk_kick": 2.0,
    "def_td": 6.0,
    "def_st_td": 6.0,
}

DRAFTKINGS_NFL = {
    "pass_yd": 0.04,
    "pass_td": 4.0,
    "pass_int": -1.0,
    "pass_2pt": 2.0,
    "bonus_pass_yd_300": 3.0,
    "rush_yd": 0.1,
    "rush_td": 6.0,
    "rush_2pt": 2.0,
    "bonus_rush_yd_100": 3.0,
    "rec": 1.0,
    "rec_yd": 0.1,
    "rec_td": 6.0,
    "rec_2pt": 2.0,
    "bonus_rec_yd_100": 3.0,
    "fum_lost": -1.0,
    "st_td": 6.0,
    **_DST_EVENTS,
    **_DST_POINTS_ALLOWED,
}

FANDUEL_NFL = {
    "pass_yd": 0.04,
    "pass_td": 4.0,
    "pass_int": -1.0,
    "pass_2pt": 2.0,
    "rush_yd": 0.1,
    "rush_td": 6.0,
    "rush_2pt": 2.0,
    "rec": 0.5,
    "rec_yd": 0.1,
    "rec_td": 6.0,
    "rec_2pt": 2.0,
    "fum_lost": -2.0,
    "st_td": 6.0,
    **_DST_EVENTS,
    **_DST_POINTS_ALLOWED,
}

CARDS = {("draftkings", "nfl"): DRAFTKINGS_NFL, ("fanduel", "nfl"): FANDUEL_NFL}
VERIFICATION = {
    "state": "unverified",
    "checkedOn": "2026-09-30",
    "blocker": "Official DraftKings/FanDuel scoring pages refused automated access (2026-09-30).",
    "approximation": "Yardage bonuses scored on the average stat line (biased low for high-volume players).",
}
