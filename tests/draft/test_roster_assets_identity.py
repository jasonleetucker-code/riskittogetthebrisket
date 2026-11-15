"""``build_roster_assets`` joins a roster to the board by IDENTITY first.

LANE-E-DEFECT-I9-DUPNAME.  The join used to be name-first, so two players that
share a display name collapsed onto one board row and one ``player_id`` - on one
roster, and across the league (a roster's "Byron Murphy" took the board's other
"Byron Murphy").  Names are now only the fallback.

The roster's ``players`` (names) and ``playerIds`` (ids) are NOT parallel lists in
the live contract - the names are sorted alphabetically, the ids by id, and 8 of
696 entries lined up on the 2026-10-25 board - so the ids are a SET that scopes
who a name can mean, never a position.  Every test here shuffles them.
"""

from __future__ import annotations

from src.draft.context import build_roster_assets, index_contract_rows


def _row(pid: str, name: str, position: str, value: float | None) -> dict:
    row: dict = {
        "playerId": pid,
        "displayName": name,
        "canonicalName": name,
        "legacyRef": name,
        "position": position,
        "assetClass": "offense",
    }
    if value is not None:
        row["rankDerivedValue"] = value
    return row


def _join(rows: list[dict], team: dict):
    by_id, by_name = index_contract_rows({"playersArray": rows})
    return build_roster_assets(team, by_name, by_id)


def test_names_and_ids_that_are_not_parallel_join_by_row():
    rows = [_row("1", "Alpha", "WR", 3000.0), _row("2", "Bravo", "RB", 2000.0)]
    rows.append(_row("3", "Charlie", "QB", 1000.0))
    assets, unmatched = _join(
        rows, {"players": ["Alpha", "Bravo", "Charlie"], "playerIds": ["3", "1", "2"]}
    )
    assert unmatched == []
    assert [(a.name, a.player_id, a.board_value) for a in assets] == [
        ("Alpha", "1", 3000.0),
        ("Bravo", "2", 2000.0),
        ("Charlie", "3", 1000.0),
    ]


def test_two_roster_players_sharing_a_display_name_stay_two_assets():
    rows = [_row("10", "Sam Smith", "WR", 3000.0), _row("11", "Sam Smith", "DB", 900.0)]
    assets, unmatched = _join(
        rows, {"players": ["Sam Smith", "Sam Smith"], "playerIds": ["11", "10"]}
    )
    assert unmatched == []
    assert sorted(a.player_id for a in assets) == ["10", "11"]
    assert sorted((a.player_id, a.position, a.board_value) for a in assets) == [
        ("10", "WR", 3000.0),
        ("11", "DB", 900.0),
    ]


def test_a_same_named_board_row_of_another_player_is_not_a_match():
    """The roster holds id 99; the board's only "Pat Jones" is id 20 (another
    player, perhaps on another roster).  Joining by name would price 99 at 20's
    value.  He is unmatched (priced nowhere) - missing is never another player's
    number - while the roster that really holds id 20 still joins."""
    rows = [_row("20", "Pat Jones", "DL", 2451.0)]
    mine, mine_unmatched = _join(rows, {"players": ["Pat Jones"], "playerIds": ["20"]})
    assert mine_unmatched == []
    assert (mine[0].player_id, mine[0].board_value) == ("20", 2451.0)

    theirs, theirs_unmatched = _join(rows, {"players": ["Pat Jones"], "playerIds": ["99"]})
    assert theirs_unmatched == ["Pat Jones"]
    assert (theirs[0].position, theirs[0].board_value) == ("", None)
    assert theirs[0].player_id == "99"  # the single id left over is his


def test_a_roster_without_ids_still_joins_by_name():
    """The fallback is unchanged for a source that publishes no ids at all."""
    rows = [_row("1", "Alpha", "WR", 3000.0)]
    assets, unmatched = _join(rows, {"players": ["Alpha", "Ghost"]})
    assert unmatched == ["Ghost"]
    assert (assets[0].player_id, assets[0].board_value) == ("1", 3000.0)
    assert assets[1].board_value is None
    assert (assets[0].on_board, assets[1].on_board) == (True, False)
    assert assets[1].player_id == "Ghost"  # no id anywhere: the name, as ever


def test_parallel_lists_keep_each_unmatched_entrys_positional_id():
    """The ``sleeper_overlay`` shape (every non-default league): ``players[i]``
    and ``playerIds[i]`` describe one entry.  Every id that resolves sits at an
    index whose name its row answers to, so the pairing is VERIFIED and each
    unmatched entry keeps its OWN id - even with several unmatched."""
    rows = [_row("1", "Alpha", "WR", 3000.0), _row("3", "Charlie", "QB", 1000.0)]
    assets, unmatched = _join(
        rows,
        {"players": ["Alpha", "Bravo", "Charlie", "Delta"], "playerIds": ["1", "2", "3", "4"]},
    )
    assert unmatched == ["Bravo", "Delta"]
    assert [(a.name, a.player_id, a.on_board) for a in assets] == [
        ("Alpha", "1", True),
        ("Bravo", "2", False),
        ("Charlie", "3", True),
        ("Delta", "4", False),
    ]


def test_sorted_lists_never_lend_an_unmatched_entry_another_entrys_id():
    """The scraper shape (the default league) sorts ``players`` and ``playerIds``
    independently, so no index means anything.  Here a positional read would
    hand "Delta" id 4 - which is Alpha's.  The pairing fails verification (the
    row for id 4 is not Delta), so two unmatched entries with two ids left
    over get NO guessed id: each keeps its name."""
    rows = [_row("4", "Alpha", "WR", 3000.0), _row("3", "Charlie", "QB", 1000.0)]
    assets, unmatched = _join(
        rows,
        {"players": ["Alpha", "Bravo", "Charlie", "Delta"], "playerIds": ["1", "2", "3", "4"]},
    )
    assert unmatched == ["Bravo", "Delta"]
    by_name = {a.name: a for a in assets}
    assert by_name["Alpha"].player_id == "4" and by_name["Charlie"].player_id == "3"
    assert by_name["Bravo"].player_id == "Bravo" and by_name["Delta"].player_id == "Delta"
    assert not by_name["Bravo"].on_board and not by_name["Delta"].on_board


def test_sorted_lists_with_one_leftover_id_still_name_it():
    """A sorted roster with exactly one unmatched entry and one id left over:
    that id is his, whatever the indexes say."""
    rows = [_row("4", "Alpha", "WR", 3000.0), _row("3", "Charlie", "QB", 1000.0)]
    assets, unmatched = _join(
        rows, {"players": ["Alpha", "Bravo", "Charlie"], "playerIds": ["2", "3", "4"]}
    )
    assert unmatched == ["Bravo"]
    assert {a.name: a.player_id for a in assets} == {"Alpha": "4", "Bravo": "2", "Charlie": "3"}


def test_an_unverifiable_pairing_is_read_as_sorted():
    """Nothing resolves, so nothing can verify the pairing: the safe reading is
    the scraper shape - a lone leftover id is named, several are not."""
    assets, unmatched = _join([], {"players": ["A", "B"], "playerIds": ["1", "2"]})
    assert unmatched == ["A", "B"]
    assert [a.player_id for a in assets] == ["A", "B"]
    assets, unmatched = _join([], {"players": ["A"], "playerIds": ["1"]})
    assert [a.player_id for a in assets] == ["1"]
