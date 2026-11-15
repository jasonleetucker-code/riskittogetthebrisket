"""Synthetic two-team league for the depth-disclosure shadow tests (not a test module).

Values mirror design worked example 1 (Hurts 5,919 for Egbuka 5,197 + Hodgins
897; ``docs/trade/LOW_VALUE_DEPTH_DISCLOSURE_DESIGN_2026-10-20.md`` §4.4) on a
board small enough to read: the WR floor is the best unrostered WR (1,802), so
the 897 receiver is low-value depth and nothing else in the trade is.
"""

from __future__ import annotations

SETTINGS = {
    "teamCount": 2,
    "rosterSize": 10,
    "taxiSize": 0,
    "starters": {"QB": 1, "RB": 1, "WR": 1, "TE": 1},
}

FILLER = "Wr Filler"  # the low-value depth piece; must never reach the store


def _row(name, value, pos, *, cls="offense", quarantined=False):
    return {
        "displayName": name,
        "canonicalName": name,
        "assetClass": cls,
        "position": pos,
        "pos": pos,
        "team": "FA",
        "rankDerivedValue": value,
        "values": {"full": value} if value else {},
        "quarantined": quarantined,
    }


def _lineup(starters, bench):
    return {
        "available": True,
        "slotSource": "registry_starters",
        "slots": ["QB", "RB", "WR", "TE"],
        "starters": sorted(starters),
        "bench": sorted(bench),
    }


def contract(*, league_key="main", lineups=True):
    rows = [
        _row("Qb Us", 6000, "QB"),
        _row("Rb Us", 3000, "RB"),
        _row("Wr Us Star", 5919, "WR"),
        _row("Te Us", 2500, "TE"),
        _row("Qb Them", 5500, "QB"),
        _row("Rb Them", 2800, "RB"),
        _row("Wr Them Star", 5197, "WR"),
        _row("Te Them", 2400, "TE"),
        _row(FILLER, 897, "WR"),
        _row("Wr Them Depth", 2100, "WR"),
        # Free agents: the replacement levels.
        _row("Qb Free", 1923, "QB"),
        _row("Rb Free", 1626, "RB"),
        _row("Wr Free", 1802, "WR"),
        _row("Te Free", 2061, "TE"),
        _row("Lb Free", 2149, "LB"),
        _row("2029 Late 4th", 1325, "PICK", cls="pick"),
        _row("2027 Pick 1.04", 5090, "PICK", cls="pick"),
    ]
    us_players = ["Qb Us", "Rb Us", "Wr Us Star", "Te Us"]
    them_players = ["Qb Them", "Rb Them", "Wr Them Star", "Te Them", FILLER, "Wr Them Depth"]
    us = {
        "ownerId": "o1",
        "name": "Us",
        "roster_id": 1,
        "players": us_players,
        "playerIds": [n.lower() for n in us_players],
        "picks": [],
    }
    them = {
        "ownerId": "o2",
        "name": "Them",
        "roster_id": 2,
        "players": them_players,
        "playerIds": [n.lower() for n in them_players],
        "picks": [],
    }
    if lineups:
        us["optimalLineup"] = _lineup(us_players, [])
        them["optimalLineup"] = _lineup(them_players[:4], them_players[4:])
    out = {
        "playersArray": rows,
        "sleeper": {"teams": [us, them]},
        "generatedAt": "2026-10-21T00:00:00+00:00",
    }
    if league_key:
        out["meta"] = {"leagueKey": league_key}
    return out


def asset(name, value, pos, *, cls=None, quarantined=False, asset_id=None):
    return {
        "name": name,
        "sourceLabel": name,
        "pos": "PICK" if pos == "PICK" else pos,
        "basePos": pos,
        "value": value,
        "assetClass": cls or ("pick" if pos == "PICK" else "offense"),
        "quarantined": quarantined,
        "assetId": asset_id,
        "playerId": None,
    }


def simulation(receiving, sending, **extra):
    return {"receiving": list(receiving), "sending": list(sending), **extra}


#: Design worked example 1: us give the star WR, receive the WR + the filler.
HURTS_FOR_EGBUKA_HODGINS = simulation(
    [asset("Wr Them Star", 5197, "WR"), asset(FILLER, 897, "WR")],
    [asset("Wr Us Star", 5919, "WR")],
)

TRADE_BODY = {
    "leagueKey": "main",
    "team": "o1",
    "playersIn": ["Wr Them Star", FILLER],
    "playersOut": ["Wr Us Star"],
}
