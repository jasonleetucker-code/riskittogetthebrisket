"""Terminal re-derives a Sleeper id it was already handed.

``_players_array`` backfills each row's ``_sleeperId`` from the
lowercased display name, even though every row already carries the same
value under ``playerId`` (``data_contract`` maps ``_sleeperId`` onto it).
Measured on the live payload: 1,092 rows, 937 ids recovered, 0 rows
where a ``playerId`` was present and the name join failed — correct
today only because both surfaces are minted from one build and spell
every name identically (audit W06-F013).

A name join standing in for an id already on the row is one vendor
rename away from dropping the row silently, so it becomes the fallback
rather than the method.
"""

from __future__ import annotations

from src.api import terminal


def test_terminal_prefers_the_id_already_on_the_row():
    contract = {
        "playersArray": [
            {"displayName": "A.J. Brown", "playerId": "5859"},
        ],
        "players": {},
    }
    rows = terminal._players_array(contract)
    assert rows[0]["_sleeperId"] == "5859"


def test_terminal_id_join_survives_a_display_name_that_does_not_match():
    """The name join needs both surfaces to spell the player identically.
    The id does not."""
    contract = {
        "playersArray": [{"displayName": "AJ Brown", "playerId": "5859"}],
        "players": {"A.J. Brown": {"_sleeperId": "5859"}},
    }
    rows = terminal._players_array(contract)
    assert rows[0]["_sleeperId"] == "5859"


def test_terminal_still_falls_back_to_the_name_join():
    """Rows without a playerId — picks, and anything the scraper could
    not resolve — keep the old path."""
    contract = {
        "playersArray": [{"displayName": "A.J. Brown"}],
        "players": {"A.J. Brown": {"_sleeperId": "5859"}},
    }
    rows = terminal._players_array(contract)
    assert rows[0]["_sleeperId"] == "5859"
