"""The U3 trailing ``position`` / ``team`` columns must not read as vendor content.

``scripts/check_source_health.py::measure_content_staleness`` answers "when did
this vendor last publish NEW data" by hashing each archived ``site_raw`` CSV.
Hashing whole file bytes made identity columns count as content, so:

* the U3 transition itself (same values, two new columns) read as a fresh
  publication, resetting every U3 source's content-staleness clock; and
* a frozen pick board (idpTradeCalc's pick rows, the case the pick-row hash was
  built for) read as "the pick market moved", because the pick lines grew
  trailing cells;
* afterwards, a team change alone (a trade, a signing) would keep a source whose
  values never move looking fresh.

The value lanes never had this problem: ``dataset_state`` (freshness weighting)
fingerprints only value/rank columns via ``dataset_integrity.parse_board``.
These tests pin both lanes.
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import pytest

from scripts import check_source_health as csh
from scripts import validate_scrape_sanity as vss
from src.sources.dataset_integrity import parse_board

REPO = Path(__file__).resolve().parents[2]

BEFORE = "name,value\nJosh Allen,9000\n2027 Early 1st,5000\n2027 Mid 1st,4500\n"
AFTER_SAME = (
    "name,value,position,team\nJosh Allen,9000,QB,BUF\n2027 Early 1st,5000,,\n2027 Mid 1st,4500,,\n"
)
AFTER_TEAM_ONLY = (
    "name,value,position,team\nJosh Allen,9000,QB,MIA\n2027 Early 1st,5000,,\n2027 Mid 1st,4500,,\n"
)
AFTER_VALUE = (
    "name,value,position,team\nJosh Allen,9100,QB,MIA\n2027 Early 1st,5000,,\n2027 Mid 1st,4500,,\n"
)
AFTER_PICK = (
    "name,value,position,team\nJosh Allen,9100,QB,MIA\n2027 Early 1st,5100,,\n2027 Mid 1st,4500,,\n"
)


def _archive(root: Path, stamp: str, text: str) -> None:
    arch = root / "exports" / "archive"
    arch.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(arch / f"dynasty_export_{stamp}.zip", "w") as zf:
        zf.writestr("site_raw/idpTradeCalc.csv", text)


def _measure(tmp_path: Path, versions: list[tuple[str, str]]) -> dict:
    for stamp, text in versions:
        _archive(tmp_path, stamp, text)
    return csh.measure_content_staleness(tmp_path)["idpTradeCalc"]


def test_the_u3_transition_is_not_a_content_change(tmp_path):
    got = _measure(tmp_path, [("20261020_000000", BEFORE), ("20261022_000000", AFTER_SAME)])
    assert got["lastChangedAt"] == "2026-10-20T00:00:00+00:00"
    assert got["pickRowsLastChangedAt"] == "2026-10-20T00:00:00+00:00"


def test_a_team_change_alone_is_not_a_content_change(tmp_path):
    got = _measure(
        tmp_path,
        [
            ("20261020_000000", BEFORE),
            ("20261022_000000", AFTER_SAME),
            ("20261024_000000", AFTER_TEAM_ONLY),
        ],
    )
    assert got["lastChangedAt"] == "2026-10-20T00:00:00+00:00"


def test_a_value_change_still_is_and_frozen_picks_stay_frozen(tmp_path):
    got = _measure(
        tmp_path,
        [
            ("20261020_000000", BEFORE),
            ("20261022_000000", AFTER_SAME),
            ("20261024_000000", AFTER_VALUE),
        ],
    )
    assert got["lastChangedAt"] == "2026-10-24T00:00:00+00:00"
    assert got["pickRowsLastChangedAt"] == "2026-10-20T00:00:00+00:00"


def test_a_pick_value_change_is_still_seen(tmp_path):
    got = _measure(
        tmp_path,
        [
            ("20261020_000000", BEFORE),
            ("20261022_000000", AFTER_SAME),
            ("20261024_000000", AFTER_PICK),
        ],
    )
    assert got["pickRowsLastChangedAt"] == "2026-10-24T00:00:00+00:00"


def test_boards_without_identity_columns_hash_exactly_as_before():
    raw = BEFORE.encode()
    assert csh._content_bytes(raw, "idpTradeCalc") == raw
    # a board U3 never touched keeps even a column named ``team``
    other = b"name,value,team\nA,1,DET\n"
    assert csh._content_bytes(other, "draftSharksSf") == other


def test_quoted_names_with_commas_survive_the_strip():
    raw = b'name,value,position,team\n"Smith, Jr.",10,WR,DET\n'
    assert csh._content_bytes(raw, "fantasyCalc") == b'name,value\n"Smith, Jr.",10\n'


def _write_like_the_scraper(rows: list[list[str]]) -> bytes:
    buf = io.StringIO(newline="")
    csv.writer(buf).writerows(rows)  # csv default: CRLF, minimal quoting
    return buf.getvalue().encode("utf-8")


def test_real_pre_u3_file_and_its_u3_successor_hash_identically():
    """The committed idpTradeCalc board (CRLF, written by the scraper) against the
    same values written the U3 way: one content, one digest."""
    raw = (REPO / "CSVs" / "site_raw" / "idpTradeCalc.csv").read_bytes()
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8"), newline="")))
    assert rows[0] == ["name", "value"] and b"\r\n" in raw
    widened = _write_like_the_scraper(
        [rows[0] + ["position", "team"]] + [r + ["DL", "DET"] for r in rows[1:]]
    )
    assert widened != raw
    assert csh._content_bytes(widened, "idpTradeCalc") == raw
    assert csh._content_bytes(raw, "idpTradeCalc") == raw


def test_ktc_capture_boards_keep_their_pre_u3_position_column():
    raw = (REPO / "CSVs" / "site_raw" / "ktcCrowdSfTep.csv").read_bytes()
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8"), newline="")))
    assert "position" in rows[0] and "team" not in rows[0]
    widened = _write_like_the_scraper([rows[0] + ["team"]] + [r + ["DET"] for r in rows[1:]])
    assert csh._content_bytes(widened, "ktcCrowdSfTep") == raw


def test_value_lane_fingerprint_ignores_identity_columns():
    """``dataset_state`` (freshness weighting, i.e. VALUES) reads parse_board rows."""
    for text in (AFTER_SAME, AFTER_TEAM_ONLY):
        assert parse_board(text, signal="value").rows == parse_board(BEFORE, signal="value").rows
    assert parse_board(AFTER_VALUE, signal="value").rows != parse_board(BEFORE, signal="value").rows


# ── the scrape sanity gate reads positionally; prove the columns cannot fool it ──


def test_identity_cells_are_never_a_numeric_signal():
    broken = "name,value,position,team\nA,,QB,BUF\nB,0,WR,DET\n"
    assert vss._has_any_numeric_signal(broken) is False
    level, _ = vss.evaluate("ktc", broken, None)
    assert level == "error"


@pytest.mark.parametrize("text", [BEFORE, AFTER_SAME])
def test_row_counts_are_unchanged_by_the_columns(text):
    assert len(vss._data_rows(text)) == 3


def test_sanity_gate_needs_no_header_change():
    """The gate counts rows and looks for any numeric cell; it never compares
    headers, so a wider header is accepted as long as values are present."""
    level, msg = vss.evaluate(
        "dlfIdp", "name,rank,value,position,team\n" + "A,1,,DL,DET\n" * 200, None
    )
    assert level == "ok", msg


def test_archive_reader_tolerates_bom_and_crlf():
    raw = "﻿name,value,position,team\r\nA,1,QB,BUF\r\n".encode()
    assert csh._content_bytes(raw, "fantasyCalc") == "﻿name,value\r\nA,1\r\n".encode()


def test_unparseable_bytes_fall_back_to_the_raw_bytes():
    raw = b"\xff\xfe\x00not csv"
    assert csh._content_bytes(raw, "fantasyCalc") == raw


def test_zip_member_round_trip(tmp_path):
    _archive(tmp_path, "20261020_000000", AFTER_SAME)
    with zipfile.ZipFile(next((tmp_path / "exports" / "archive").glob("*.zip"))) as zf:
        raw = zf.read("site_raw/idpTradeCalc.csv")
    assert csh._content_bytes(raw, "idpTradeCalc").startswith(b"name,value\n")
