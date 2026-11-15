"""Player identity by Sleeper id in the trade simulator (Brisket Trade Advisor B0-b).

The defect: the simulator keyed players by DISPLAY NAME — the legs, and the
before-roster (built from ``team["players"]``).  Two real players share the
name "Byron Murphy": the rostered cornerback (Sleeper 5864) has no board row,
so by name he priced as the OTHER Byron Murphy's DL row.  And the name list
can omit a rostered player whose id is present (roster 6 on the 2026-10-19
board: 57 names for 58 ids).  Now:

* ``player_ids_in`` / ``player_ids_out`` resolve by id only — no row for the
  id is unresolved, never retried by name;
* the before-roster is built from ``playerIds`` (joined by id); a rostered
  player with no row is listed in ``rosterUnpriced`` and priced nowhere;
* entries without an id keep the name lookup (unchanged for old callers).
"""

from __future__ import annotations

from src.api import trade_simulator as ts


def _row(name, pid, value, pos):
    return {
        "playerId": pid,
        "displayName": name,
        "canonicalName": name,
        "assetClass": "idp" if pos in ("DL", "LB", "DB") else "offense",
        "pos": pos,
        "position": pos,
        "rankDerivedValue": value,
        "values": {"full": value},
    }


def _contract(*, ids_on_rows=True):
    rows = [
        _row("Byron Murphy", "11668", 2400, "DL"),  # the OTHER Byron Murphy
        _row("Alim McNeill", "7000", 1800, "DL"),
        _row("Josh Allen", "4984", 9000, "QB"),
        _row("Ja'Marr Chase", "7564", 9500, "WR"),
    ]
    if not ids_on_rows:
        for r in rows:
            r.pop("playerId")
    us = {
        "name": "Us",
        "ownerId": "o1",
        "roster_id": 1,
        # The name list collides (5864 is a different Byron Murphy) and
        # omits Alim McNeill, whose id IS rostered.
        "players": ["Byron Murphy", "Josh Allen"],
        "playerIds": ["5864", "4984", "7000"],
        "picks": [],
    }
    them = {
        "name": "Them",
        "ownerId": "o2",
        "roster_id": 2,
        "players": ["Ja'Marr Chase", "Byron Murphy"],
        "playerIds": ["7564", "11668"],
        "picks": [],
    }
    idp = {"5864": "Byron Murphy", "4984": "Josh Allen", "7000": "Alim McNeill"}
    idp.update({"7564": "Ja'Marr Chase", "11668": "Byron Murphy"})
    return {"playersArray": rows, "sleeper": {"teams": [us, them], "idToPlayer": idp}}


def _us(c):
    return c["sleeper"]["teams"][0]


def test_before_roster_is_built_from_player_ids():
    c = _contract()
    sim = ts.simulate_trade(c, resolved_team=_us(c))
    # Josh Allen + Alim McNeill priced; the CB with no row is NOT priced as
    # the DL Byron Murphy (2400).
    assert sim["before"]["totalValue"] == 9000 + 1800
    assert sim["rosterUnpriced"] == [{"playerId": "5864", "name": "Byron Murphy"}]


def test_name_path_is_kept_when_the_board_carries_no_ids():
    c = _contract(ids_on_rows=False)
    sim = ts.simulate_trade(c, resolved_team=_us(c))
    # Legacy behaviour, unchanged: names, including the collision.
    assert sim["before"]["totalValue"] == 2400 + 9000
    assert "rosterUnpriced" not in sim


def test_a_leg_with_an_id_resolves_by_id_only():
    c = _contract()
    sim = ts.simulate_trade(
        c,
        resolved_team=_us(c),
        players_out=["Byron Murphy"],
        player_ids_out=["5864"],
        players_in=["Ja'Marr Chase"],
        player_ids_in=["7564"],
    )
    assert sim["unresolvedOut"] == ["Byron Murphy"]
    assert sim["sending"] == []
    assert [a["name"] for a in sim["receiving"]] == ["Ja'Marr Chase"]
    assert sim["receiving"][0]["playerId"] == "7564"


def test_a_leg_without_an_id_keeps_the_name_lookup():
    c = _contract()
    sim = ts.simulate_trade(c, resolved_team=_us(c), players_out=["Byron Murphy"])
    assert [(a["name"], a["value"]) for a in sim["sending"]] == [("Byron Murphy", 2400)]


def test_an_id_leg_removes_exactly_that_player_whatever_name_was_typed():
    c = _contract()
    sim = ts.simulate_trade(c, resolved_team=_us(c), players_out=["Alim"], player_ids_out=["7000"])
    assert [a["name"] for a in sim["sending"]] == ["Alim McNeill"]
    assert sim["delta"]["totalValue"] == -1800
    assert sim["after"]["totalValue"] == 9000


def test_an_id_carried_by_two_rows_is_ambiguous_not_guessed():
    c = _contract()
    c["playersArray"].append(_row("Josh Allen (dup)", "4984", 100, "QB"))
    sim = ts.simulate_trade(
        c, resolved_team=_us(c), players_out=["Josh Allen"], player_ids_out=["4984"]
    )
    assert sim["unresolvedOut"] == ["Josh Allen"]
    assert {"playerId": "4984", "name": "Josh Allen"} in sim["rosterUnpriced"]


def test_rows_by_player_id_reads_the_backfilled_sleeper_id():
    rows = [{"displayName": "X", "_sleeperId": "42"}, {"displayName": "P", "assetClass": "pick"}]
    idx = ts.rows_by_player_id(rows)
    assert idx == {"42": rows[0]}
    assert ts.row_player_id(rows[0]) == "42"


def test_public_resolver_matches_the_simulator():
    c = _contract()
    assert ts.resolve_trade_asset("x", contract=c, player_id="7564")["name"] == "Ja'Marr Chase"
    assert ts.resolve_trade_asset("Byron Murphy", contract=c, player_id="5864") is None
    assert ts.resolve_trade_asset("Byron Murphy", contract=c)["value"] == 2400
    idx = ts.asset_row_index(c)
    assert ts.resolve_trade_asset("Josh Allen", contract=c, row_index=idx)["value"] == 9000


def test_an_id_leg_is_removed_from_a_name_built_roster_on_backfilled_ids():
    # Rows carrying only the backfilled ``_sleeperId`` and a team with no
    # ``playerIds`` (name-built before-roster): the id-sent player must still
    # leave the after-state, or ``delta`` and ``equity`` disagree.
    c = _contract()
    for r in c["playersArray"]:
        r["_sleeperId"] = r.pop("playerId")
    us = _us(c)
    us.pop("playerIds")
    us["players"] = ["Josh Allen", "Alim McNeill"]
    sim = ts.simulate_trade(c, resolved_team=us, players_out=["Alim"], player_ids_out=["7000"])
    assert [a["name"] for a in sim["sending"]] == ["Alim McNeill"]
    assert sim["after"]["totalValue"] == 9000
    assert sim["delta"]["totalValue"] == -1800
