"""Rank, tier, position and value survive preservation without coercion.

Schema v1 stored ``dict[str, float]`` — one number per name.  A source whose
entire content is *rank, positional rank and tier* (Dynasty Nerds' IDP
Top-275) could be "archived" under that shape while losing everything it
said, and a source publishing both a rank and a value had to discard one.

These tests pin the v2 record end to end, and pin that v1 boards are
unaffected — because the extension is only safe if it is additive.
"""

from __future__ import annotations

import pytest

from src.source_archive.records import ArchivedRow, ArchivedRowError
from src.source_archive.store import (
    ArchivedBoard,
    _reset_setup_cache_for_tests,
    archive_board,
    read_boards,
)


@pytest.fixture()
def archive_path(tmp_path):
    _reset_setup_cache_for_tests()
    yield tmp_path / "boards.sqlite"
    _reset_setup_cache_for_tests()


def _board(**over) -> ArchivedBoard:
    base = dict(
        provider="dynastyNerds",
        provider_family="dynastyNerds",
        endpoint="https://example.invalid/idp",
        format_key="idp_top275",
        game_type="DYNASTY",
        run_id="run-1",
        rows={"Aidan Hutchinson": 1.0},
        captured_at="2026-08-20T00:00:00+00:00",
    )
    base.update(over)
    return ArchivedBoard(**base)


class TestARankTierBoardSurvives:
    def test_rank_positional_rank_and_tier_round_trip(self, archive_path) -> None:
        row = ArchivedRow(
            source_name="Aidan Hutchinson",
            source_position="DL",
            position_family="DL",
            team="DET",
            age=25.0,
            overall_rank=1,
            positional_rank=1,
            tier="Tier 1",
        )
        archive_board(_board(records=(row,)), path=archive_path)
        (stored,) = read_boards(path=archive_path)
        assert stored.records == (row,)
        assert stored.records[0].overall_rank == 1
        assert stored.records[0].tier == "Tier 1"
        assert stored.records[0].positional_rank == 1

    def test_a_rank_and_a_value_can_coexist(self, archive_path) -> None:
        """The v1 shape had room for exactly one of these."""
        row = ArchivedRow(
            source_name="Myles Garrett",
            overall_rank=1,
            value=5121.0,
            value_unit="0-10000",
        )
        archive_board(_board(records=(row,)), path=archive_path)
        (stored,) = read_boards(path=archive_path)
        assert stored.records[0].overall_rank == 1
        assert stored.records[0].value == 5121.0
        assert stored.records[0].value_unit == "0-10000"

    def test_the_vendors_native_position_is_not_replaced_by_our_family(self, archive_path) -> None:
        """ "EDGE" is information that "DL" discards, so both are kept."""
        row = ArchivedRow(
            source_name="Aidan Hutchinson", source_position="EDGE", position_family="DL"
        )
        archive_board(_board(records=(row,)), path=archive_path)
        (stored,) = read_boards(path=archive_path)
        assert stored.records[0].source_position == "EDGE"
        assert stored.records[0].position_family == "DL"


class TestMissingIsNeverZero:
    def test_absent_quantities_stay_absent(self, archive_path) -> None:
        row = ArchivedRow(source_name="Unranked Player")
        archive_board(_board(records=(row,)), path=archive_path)
        (stored,) = read_boards(path=archive_path)
        got = stored.records[0]
        assert got.overall_rank is None
        assert got.value is None
        assert got.tier is None
        assert "overallRank" not in got.to_dict()
        assert "value" not in got.to_dict()

    def test_a_zero_rank_is_refused_rather_than_stored(self) -> None:
        with pytest.raises(ArchivedRowError) as exc:
            ArchivedRow(source_name="X", overall_rank=0)
        assert "must not stand in for it" in str(exc.value)

    def test_a_real_zero_value_is_preserved(self) -> None:
        """0.0 is an observation; only absence is None."""
        row = ArchivedRow(source_name="X", value=0.0, value_unit="0-10000")
        assert row.value == 0.0
        assert row.to_dict()["value"] == 0.0

    def test_a_unit_without_a_number_is_refused(self) -> None:
        with pytest.raises(ArchivedRowError):
            ArchivedRow(source_name="X", value_unit="0-10000")


class TestUnresolvedIdentityStaysUnresolved:
    def test_an_unresolved_row_carries_no_canonical_id(self, archive_path) -> None:
        row = ArchivedRow(source_name="Ambiguous Name", source_player_id="v-42")
        archive_board(_board(records=(row,)), path=archive_path)
        (stored,) = read_boards(path=archive_path)
        assert stored.records[0].canonical_player_id is None
        assert stored.records[0].resolved is False
        assert (
            stored.records[0].source_player_id == "v-42"
        ), "the vendor id must survive so the join can be revisited"


class TestTheExtensionIsAdditive:
    def test_a_board_with_no_records_still_archives_and_reads(self, archive_path) -> None:
        archive_board(_board(), path=archive_path)
        (stored,) = read_boards(path=archive_path)
        assert stored.rows == {"Aidan Hutchinson": 1.0}
        assert stored.records == ()

    def test_records_do_not_change_a_v1_boards_hash(self) -> None:
        """Re-archiving an existing board must stay the no-op it was."""
        assert _board().compute_hash() == _board().compute_hash()

    def test_records_do_change_the_hash_when_present(self) -> None:
        """Otherwise a content change inside the records would be invisible."""
        plain = _board()
        with_rows = _board(records=(ArchivedRow(source_name="A", overall_rank=1),))
        assert plain.compute_hash() != with_rows.compute_hash()

    def test_a_v1_database_is_migrated_in_place(self, archive_path) -> None:
        """A database created before v2 gains the column instead of breaking."""
        import sqlite3

        archive_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(archive_path))
        conn.execute(
            "CREATE TABLE archived_boards (provider TEXT NOT NULL, provider_family TEXT "
            "NOT NULL, endpoint TEXT NOT NULL, format_key TEXT NOT NULL, game_type TEXT "
            "NOT NULL, run_id TEXT NOT NULL, captured_date TEXT NOT NULL, captured_at TEXT "
            "NOT NULL, source_as_of TEXT, row_count INTEGER NOT NULL, rows_json TEXT NOT "
            "NULL, content_hash TEXT NOT NULL, first_seen_at TEXT NOT NULL, "
            "PRIMARY KEY (provider, endpoint, format_key, run_id, captured_date))"
        )
        conn.commit()
        conn.close()
        _reset_setup_cache_for_tests()

        archive_board(
            _board(records=(ArchivedRow(source_name="A", overall_rank=1),)), path=archive_path
        )
        (stored,) = read_boards(path=archive_path)
        assert stored.records[0].overall_rank == 1
