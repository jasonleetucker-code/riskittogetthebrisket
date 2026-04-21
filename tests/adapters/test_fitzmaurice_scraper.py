"""Unit tests for scripts/fetch_fantasypros_fitzmaurice.py

The live fetcher hits FantasyPros + Datawrapper over HTTP, so the
tests here exercise the offline-safe pure functions: URL candidate
generation, chart-ID extraction from a page snippet, per-position
column selection, and trailing-filler-row filtering.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def fz_module():
    repo = Path(__file__).resolve().parents[2]
    path = repo / "scripts" / "fetch_fantasypros_fitzmaurice.py"
    spec = importlib.util.spec_from_file_location(
        "fetch_fantasypros_fitzmaurice", path
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["fetch_fantasypros_fitzmaurice"] = module
    spec.loader.exec_module(module)
    return module


def test_build_candidate_urls_current_month_first(fz_module):
    urls = fz_module._build_candidate_urls(date(2026, 4, 21))
    assert urls[0].endswith("april-2026-update/")
    assert urls[1].endswith("march-2026-update/")
    assert urls[2].endswith("february-2026-update/")
    assert urls[3].endswith("january-2026-update/")
    # URL path format
    assert "/2026/04/" in urls[0]
    assert "/2026/03/" in urls[1]


def test_build_candidate_urls_wraps_year_boundary(fz_module):
    urls = fz_module._build_candidate_urls(date(2026, 2, 3))
    assert urls[0].endswith("february-2026-update/")
    assert urls[1].endswith("january-2026-update/")
    assert urls[2].endswith("december-2025-update/")
    assert urls[3].endswith("november-2025-update/")
    assert "/2025/12/" in urls[2]
    assert "/2025/11/" in urls[3]


FAKE_ARTICLE_HTML = """
<html><body>
<article>
  <h2>Dynasty Trade Value Chart</h2>
  <h3>Dynasty Rookie Draft Pick Values</h3>
  <table>
    <tr><th>Round 1</th><th>1QB</th><th>SF</th></tr>
    <tr><td>1.01</td><td>68</td><td>68</td></tr>
  </table>

  <h3>Dynasty Trade Values: Quarterbacks</h3>
  <iframe src="https://datawrapper.dwcdn.net/yqKj2/1/"></iframe>

  <h3>Dynasty Trade Values: Running Backs</h3>
  <iframe src="https://datawrapper.dwcdn.net/ZVpNh/1/"></iframe>

  <h3>Dynasty Trade Values: Wide Receivers</h3>
  <iframe src="https://datawrapper.dwcdn.net/yuwfA/1/"></iframe>

  <h3>Dynasty Trade Value Chart: Tight Ends</h3>
  <iframe src="https://datawrapper.dwcdn.net/GFqDz/1/"></iframe>

  <h3>About Author</h3>
</article>
</body></html>
"""


def test_extract_chart_ids_by_position(fz_module):
    ids = fz_module._extract_chart_ids_by_position(FAKE_ARTICLE_HTML)
    assert ids == {
        "QB": "yqKj2",
        "RB": "ZVpNh",
        "WR": "yuwfA",
        "TE": "GFqDz",
    }


def test_extract_chart_ids_ignores_non_position_iframes(fz_module):
    html = """
    <html><body><article>
      <h3>Dynasty Trade Values: Quarterbacks</h3>
      <iframe src="https://datawrapper.dwcdn.net/qbCHARTID/1/"></iframe>
      <h3>About Author</h3>
      <iframe src="https://datawrapper.dwcdn.net/shouldNotMatch/1/"></iframe>
    </article></body></html>
    """
    ids = fz_module._extract_chart_ids_by_position(html)
    assert ids == {"QB": "qbCHARTID"}
    assert "shouldNotMatch" not in ids.values()


QB_CSV_TSV = (
    "Name\tTeam\tTrade Value\tSF Value\tValue Change\n"
    "Josh Allen\tBUF\t51\t101\t- / -\n"
    "Drake Maye\tNE\t51\t101\t- / -\n"
    "Jayden Daniels\tWAS\t46\t91\t- / +1\n"
    "All Other QBs\t\t1\t4\t\n"
)

RB_CSV_TSV = (
    "Name\tTeam\tTrade Value\tValue Change\n"
    "Bijan Robinson\tATL\t84\t+1\n"
    "Jahmyr Gibbs\tDET\t81\t-\n"
    "All Other RBs\t\t1\t-\n"
)

TE_CSV_TSV = (
    "Name\tTeam\tTrade Value\tTEP Value\tValue Change\n"
    "Brock Bowers\tLV\t69\t82\t- / -\n"
    "Trey McBride\tARI\t67\t81\t- / -\n"
    "All Other TEs\t\t1\t\t\n"
)


def test_parse_chart_rows_qb_uses_sf_value(fz_module):
    rows = fz_module._parse_chart_rows(QB_CSV_TSV, "QB")
    assert len(rows) == 3  # "All Other QBs" dropped
    assert rows[0]["name"] == "Josh Allen"
    assert rows[0]["value"] == 101  # SF Value, not 1QB Trade Value
    assert rows[0]["position"] == "QB"
    assert rows[0]["team"] == "BUF"


def test_parse_chart_rows_rb_uses_trade_value(fz_module):
    rows = fz_module._parse_chart_rows(RB_CSV_TSV, "RB")
    assert len(rows) == 2
    assert rows[0]["name"] == "Bijan Robinson"
    assert rows[0]["value"] == 84


def test_parse_chart_rows_te_uses_tep_value(fz_module):
    rows = fz_module._parse_chart_rows(TE_CSV_TSV, "TE")
    assert len(rows) == 2
    assert rows[0]["name"] == "Brock Bowers"
    assert rows[0]["value"] == 82  # TEP Value, not 69 baseline Trade Value
    assert rows[1]["name"] == "Trey McBride"
    assert rows[1]["value"] == 81


def test_parse_chart_rows_drops_filler_value_1_rows(fz_module):
    csv_text = (
        "Name\tTeam\tTrade Value\tValue Change\n"
        "Real Player\tSF\t50\t-\n"
        "All Other RBs\t\t1\t-\n"
        "Fluke Row\t\t1\t-\n"
    )
    rows = fz_module._parse_chart_rows(csv_text, "RB")
    assert len(rows) == 1
    assert rows[0]["name"] == "Real Player"


def test_write_csv_sorts_by_value_desc_and_preserves_position(fz_module, tmp_path: Path):
    out = tmp_path / "fitz_test.csv"
    rows = [
        {"name": "WR1", "team": "A", "position": "WR", "value": 80},
        {"name": "QB1", "team": "B", "position": "QB", "value": 101},
        {"name": "RB1", "team": "C", "position": "RB", "value": 95},
    ]
    count = fz_module._write_csv(out, rows)
    assert count == 3
    import csv
    with out.open() as f:
        written = list(csv.DictReader(f))
    # Top-value first.
    assert written[0]["name"] == "QB1"
    assert written[0]["value"] == "101"
    assert written[0]["position"] == "QB"
    assert written[-1]["name"] == "WR1"


def test_position_value_columns_registered_for_all_four(fz_module):
    assert set(fz_module._POSITION_VALUE_COLUMNS) == {"QB", "RB", "WR", "TE"}
    # QB must prefer SF Value; TE must prefer TEP Value — the whole
    # point of the per-position priority list.
    assert fz_module._POSITION_VALUE_COLUMNS["QB"][0] == "SF Value"
    assert fz_module._POSITION_VALUE_COLUMNS["TE"][0] == "TEP Value"
