"""``src.identity.gsis_directory`` — the directory the mapper needs.

The unified mapper resolves *through* a Sleeper player directory, and
the only live caller handed it ``sleeper_block["players"]`` — a key no
writer in this repo has ever produced (audit W06-F003).  These tests pin
the replacement: build the directory from what the contract actually
carries, join GSIS by exact normalized name, and REFUSE on ambiguity
rather than merging two humans.
"""

from __future__ import annotations

from src.identity import gsis_directory as gd

_BLOCK = {
    "idToPlayer": {
        "5859": "A.J. Brown",
        "4984": "Josh Allen",
        "9509": "Bijan Robinson",
    },
    "positions": {
        "A.J. Brown": "WR",
        "Josh Allen": "QB",
        "Bijan Robinson": "RB",
    },
}


def _weekly(gsis: str, name: str, position: str, week: int = 1) -> dict:
    return {
        "player_id": gsis,
        "player_display_name": name,
        "position": position,
        "season": 2025,
        "week": week,
    }


def test_directory_is_built_from_the_keys_the_producer_actually_writes():
    """``idToPlayer`` + ``positions``, not ``players``/``playerDict``."""
    out = gd.directory_from_sleeper_block(_BLOCK)
    assert set(out) == {"5859", "4984", "9509"}
    assert out["5859"]["full_name"] == "A.J. Brown"
    assert out["5859"]["position"] == "WR"
    assert out["5859"]["player_id"] == "5859"


def test_a_block_without_the_key_yields_an_empty_directory_not_a_crash():
    assert gd.directory_from_sleeper_block(None) == {}
    assert gd.directory_from_sleeper_block({"players": {"1": {}}}) == {}


def test_gsis_is_attached_from_the_nflverse_rows_already_in_hand():
    rows = [
        _weekly("00-0035676", "A.J. Brown", "WR"),
        _weekly("00-0035676", "A.J. Brown", "WR", week=2),
        _weekly("00-0034857", "Josh Allen", "QB"),
    ]
    build = gd.build_directory(_BLOCK, weekly_rows=rows)
    assert build.directory["5859"]["gsis_id"] == "00-0035676"
    assert build.directory["4984"]["gsis_id"] == "00-0034857"
    assert build.with_gsis == 2
    assert build.status_for("5859") == gd.STATUS_OK


def test_an_absent_player_is_counted_not_invented():
    rows = [_weekly("00-0035676", "A.J. Brown", "WR")]
    build = gd.build_directory(_BLOCK, weekly_rows=rows)
    assert build.directory["9509"]["gsis_id"] == ""
    assert build.status_for("9509") == gd.STATUS_UNMATCHED
    assert build.unmatched == 2
    assert build.as_meta()["gsisUnmatched"] == 2


def test_a_colliding_name_refuses_rather_than_merging_two_players():
    """The Josh Allen case: QB/BUF and LB/JAX share a normalized name.

    Picking either would attribute one man's stat line to the other, and
    which one you get depends on dict order.  Refusal is the answer.
    """
    rows = [
        _weekly("00-0034857", "Josh Allen", "QB"),
        _weekly("00-0034868", "Josh Allen", "LB"),
    ]
    block = {
        "idToPlayer": {"4984": "Josh Allen"},
        "positions": {"Josh Allen": "DB"},  # a vocabulary that matches neither
    }
    build = gd.build_directory(block, weekly_rows=rows)
    assert build.directory["4984"]["gsis_id"] == ""
    assert build.status_for("4984") == gd.STATUS_AMBIGUOUS
    assert build.ambiguous == 1


def test_position_narrows_a_collision_only_when_exactly_one_survives():
    rows = [
        _weekly("00-0034857", "Josh Allen", "QB"),
        _weekly("00-0034868", "Josh Allen", "LB"),
    ]
    index = gd.build_gsis_name_index(rows)
    assert gd.gsis_for_name(index, "Josh Allen", "QB") == ("00-0034857", gd.STATUS_OK)
    assert gd.gsis_for_name(index, "Josh Allen", "LB") == ("00-0034868", gd.STATUS_OK)
    assert gd.gsis_for_name(index, "Josh Allen", None)[0] is None
    assert gd.gsis_for_name(index, "Josh Allen", "WR")[0] is None


def test_no_fuzzy_fallback():
    """A near-miss name resolves to nothing.  Two different players
    merged is worse than one player missing."""
    index = gd.build_gsis_name_index([_weekly("00-0000001", "Kevin Coleman", "WR")])
    assert gd.gsis_for_name(index, "Tevin Coleman", "RB") == (None, gd.STATUS_UNMATCHED)


def test_the_cached_sleeper_dump_wins_because_it_is_an_id_join():
    """When the real ``/v1/players/nfl`` dump is cached it carries GSIS
    natively — no name is consulted for those ids."""
    cached = {
        "5859": {
            "player_id": "5859",
            "full_name": "AJ Brown",
            "position": "WR",
            "team": "PHI",
            "gsis_id": "00-0035676",
            "espn_id": "4047646",
        }
    }
    build = gd.build_directory(_BLOCK, weekly_rows=[], cached_directory=cached)
    assert build.directory["5859"]["gsis_id"] == "00-0035676"
    assert build.directory["5859"]["espn_id"] == "4047646"
    assert "sleeper_directory" in build.sources
    # The other two ids still come from the block, unpriced but present.
    assert build.directory["4984"]["gsis_id"] == ""


def test_the_checked_in_stub_directory_contributes_nothing():
    """``data/public_league/nfl_players.json`` ships a 15-row stub whose
    entries carry no GSIS id.  Treating it as a directory would erase
    the block-derived entries it shadows."""
    stub = {"p-qb1": {"player_id": None, "gsis_id": None, "position": "QB"}}
    build = gd.build_directory(_BLOCK, weekly_rows=[], cached_directory=stub)
    assert "sleeper_directory" not in build.sources
    assert set(build.directory) == {"5859", "4984", "9509"}


def test_unknown_ids_report_as_unknown_not_as_a_failed_join():
    build = gd.build_directory(_BLOCK, weekly_rows=[])
    assert build.status_for("999999") == gd.STATUS_UNKNOWN_ID
