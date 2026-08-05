"""A source ships a stable Sleeper id and the parser cannot see it.

``dynastyNerdsSfTep.csv``'s header is ``Name,Rank,Value,SleeperId,Pos,
Team``.  ``_SLEEPER_ID_ALIASES`` lists ``sleeper_id`` / ``sleeperId`` /
``sleeper_player_id`` and ``_pick`` does an exact, case-SENSITIVE dict
lookup, so the column was invisible: 0 of 294 rows carried a sleeper id
into the enrichment, versus 496 of 496 for ``pfkDynasty``, and the whole
source joined by name only (audit W06-F009).

It is losing no rows today, which is exactly why it is worth pinning.
The ID join exists because vendor and Sleeper spellings drift
("Kenneth Gainwell" vs "Kenny Gainwell"); a source that cannot reach it
is one rename away from silently dropping a vote.
"""

from __future__ import annotations

from pathlib import Path

from src.api.data_contract import _parse_source_csv_cached


def test_a_capitalised_sleeper_id_header_is_read(tmp_path: Path):
    csv_path = tmp_path / "dynastyNerdsSfTep.csv"
    csv_path.write_text(
        "Name,Rank,Value,SleeperId,Pos,Team\n"
        "Josh Allen,1,10256,4984,QB,BUF\n"
        "Bijan Robinson,2,10018,9509,RB,ATL\n",
        encoding="utf-8",
    )
    lookup, err = _parse_source_csv_cached(csv_path, "dynastyNerdsSfTep", "value", str(csv_path))
    assert err is None
    ids = {entries[0][0]: entries[0][4] for entries in lookup.values()}
    assert ids == {"Josh Allen": "4984", "Bijan Robinson": "9509"}


def test_the_conventional_lowercase_header_still_wins(tmp_path: Path):
    """The case-folded pass is a FALLBACK — an exact alias hit must keep
    taking precedence, in alias order."""
    csv_path = tmp_path / "src.csv"
    csv_path.write_text(
        "name,value,sleeper_id,SleeperId\nJosh Allen,10256,4984,9999\n",
        encoding="utf-8",
    )
    lookup, err = _parse_source_csv_cached(csv_path, "any", "value", str(csv_path))
    assert err is None
    entry = next(iter(lookup.values()))[0]
    assert entry[4] == "4984"
