"""Research readers predating U3 read every board exactly as before the cutover.

Two preregistered research tools read ``position`` from a ``site_raw`` CSV
whenever the column exists:

* ``src/source_quality/panel.py`` (point-in-time observation panel), whose
  registered identity rule classifies the IDP Trade Calculator by
  co-observation BECAUSE it publishes no position column;
* ``scripts/audit/lineage_integrity_sweep.py``.

Without a guard, U3 would silently switch both: idpTradeCalc rows would gain a
position group, a published ``K`` row would be dropped as non-fantasy, and the
version hash would change.  Both now ignore exactly the columns U3 added
(``capture_evidence.U3_ADDED_COLUMNS``), keeping columns a board carried before.
"""

from __future__ import annotations

import pytest

from scripts.audit import lineage_integrity_sweep as sweep
from src.identity import capture_evidence as ce
from src.source_quality import panel

PRE = "name,value\nJosh Allen,9000\nHarrison Butker,1200\nAidan Hutchinson,6000\n"
POST = (
    "name,value,position,team\n"
    "Josh Allen,9000,QB,BUF\nHarrison Butker,1200,K,KC\nAidan Hutchinson,6000,DL,DET\n"
)

KTC_PRE = "name,value,rank,player_id,position\nJosh Allen,9000,1,7,QB\nA Kicker,10,2,8,K\n"
KTC_POST = (
    "name,value,rank,player_id,position,team\nJosh Allen,9000,1,7,QB,BUF\nA Kicker,10,2,8,K,KC\n"
)


def _spec(csv_file: str, signal: str = "value") -> panel.SourceSpec:
    return panel.SourceSpec(
        key=csv_file.split(".")[0],
        family="f",
        csv_file=csv_file,
        signal=signal,
        universes=frozenset({panel.OFFENSE, panel.IDP}),
    )


def test_panel_reads_idptc_identically_across_the_cutover():
    spec = _spec("idpTradeCalc.csv")
    before = panel.parse_csv(PRE, spec)
    after = panel.parse_csv(POST, spec)
    assert after == before
    assert panel._hash_rows(after[0]) == panel._hash_rows(before[0])
    assert all(r.position_group is None for r in after[0])  # still co-observation
    assert "nonFantasyPosition" not in after[1]  # the K row is NOT dropped


def test_panel_keeps_a_position_column_a_board_had_before_u3():
    spec = _spec("ktcCrowdSfTep.csv")
    before = panel.parse_csv(KTC_PRE, spec)
    after = panel.parse_csv(KTC_POST, spec)
    assert after == before
    assert before[1].get("nonFantasyPosition") == 1  # pre-U3 behaviour, unchanged


@pytest.mark.parametrize("key", sorted(ce.U3_ADDED_COLUMNS))
def test_panel_is_byte_identical_for_every_u3_board(key):
    spec = _spec(f"{key}.csv")
    pre_header = "name,value"
    post = POST if "position" in ce.U3_ADDED_COLUMNS[key] else KTC_POST
    pre = PRE if "position" in ce.U3_ADDED_COLUMNS[key] else KTC_PRE
    assert pre.startswith(pre_header)
    assert panel.parse_csv(post, spec) == panel.parse_csv(pre, spec)


def _board_view(b: sweep.Board):
    return (b.header[:2], b.rows, b.rank_col, b.value_col, b.entries, b.duplicates, b.unnamed_rows)


def test_lineage_sweep_reads_idptc_identically_across_the_cutover():
    before = sweep.parse_board("idpTradeCalc", PRE)
    after = sweep.parse_board("idpTradeCalc", POST)
    assert _board_view(after) == _board_view(before)


def test_lineage_sweep_keeps_pre_u3_position_on_ktc_capture_boards():
    before = sweep.parse_board("ktcCrowdSfTep", KTC_PRE)
    after = sweep.parse_board("ktcCrowdSfTep", KTC_POST)
    assert _board_view(after) == _board_view(before)


def test_a_board_u3_never_touched_is_read_as_published():
    spec = _spec("draftSharksSf.csv")
    got = panel.parse_csv(POST, spec)
    assert got[1].get("nonFantasyPosition") == 1  # its own position column is used


def test_the_u3_table_covers_exactly_the_registered_boards():
    """Preregistration 3.7 U3 list, as CSV stems (+ the KTC capture boards, which
    gain ``team`` only)."""
    assert set(ce.U3_ADDED_COLUMNS) == {
        "ktc",
        "ktcSfTep",
        "idpTradeCalc",
        "dlfSf",
        "dlfIdp",
        "dlfRookieSf",
        "dlfRookieIdp",
        "fantasyCalc",
        "otcffbSf",
        "dynastyDaddySf",
        "flockFantasySf",
        "flockFantasySfRookies",
        "fantasyNavigatorSf",
        "ktcCrowdSfTep",
        "ktcTradesSfTep",
        "ktcCrowdTradesSfTep",
    }
    for key in ("ktcCrowdSfTep", "ktcTradesSfTep", "ktcCrowdTradesSfTep"):
        assert ce.U3_ADDED_COLUMNS[key] == ("team",)
