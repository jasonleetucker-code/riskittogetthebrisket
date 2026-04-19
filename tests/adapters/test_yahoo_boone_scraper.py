"""Unit tests for scripts/fetch_yahoo_boone.py

The live fetcher exercises four real Yahoo article URLs via HTTP, so
the tests here inject a fake fetcher and feed it hand-written HTML
fixtures that mirror the real ``<table class="content-table">``
structure.  That keeps the test suite offline-safe while still
exercising the parser, column-picker (2QB for QB, TE Prem. for TE),
cross-position rank assignment (with ties), and CSV writer.
"""
from __future__ import annotations

import csv
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


# The script lives at scripts/fetch_yahoo_boone.py — not on the
# default import path — so load it via importlib and cache the module.
@pytest.fixture(scope="module")
def yb_module():
    repo = Path(__file__).resolve().parents[2]
    path = repo / "scripts" / "fetch_yahoo_boone.py"
    spec = importlib.util.spec_from_file_location("fetch_yahoo_boone", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["fetch_yahoo_boone"] = module
    spec.loader.exec_module(module)
    return module


# ── HTML fixtures ─────────────────────────────────────────────────────

QB_HTML = """
<html><body>
  <table class="content-table">
    <tr><th>Rank</th><th>Player</th><th>1QB</th><th>2QB</th></tr>
    <tr><td>1</td><td>Josh Allen</td><td>66</td><td>141</td></tr>
    <tr><td>2</td><td>Drake Maye</td><td>62</td><td>130</td></tr>
    <tr><td>3</td><td>Lamar Jackson</td><td>59</td><td>122</td></tr>
    <tr><td>4</td><td>De&#39;Von Achane</td><td>10</td><td>20</td></tr>
  </table>
</body></html>
"""

RB_HTML = """
<html><body>
  <table class="content-table">
    <tr><th>Rank</th><th>Player</th><th>PPR</th></tr>
    <tr><td>1</td><td>Bijan Robinson</td><td>109</td></tr>
    <tr><td>2</td><td>Jahmyr Gibbs</td><td>108</td></tr>
    <tr><td>3</td><td>Ashton Jeanty</td><td>98</td></tr>
  </table>
</body></html>
"""

WR_HTML = """
<html><body>
  <table class="content-table">
    <tr><th>Rank</th><th>Player</th><th>PPR</th></tr>
    <tr><td>1</td><td>Jaxon Smith-Njigba</td><td>106</td></tr>
    <tr><td>2</td><td>Ja&#39;Marr Chase</td><td>105</td></tr>
    <tr><td>3</td><td>Puka Nacua</td><td>103</td></tr>
  </table>
</body></html>
"""

TE_HTML = """
<html><body>
  <table class="content-table">
    <tr><th>Rank</th><th>Player</th><th>PPR</th><th>TE Prem.</th></tr>
    <tr><td>1</td><td>Trey McBride</td><td>76</td><td>108</td></tr>
    <tr><td>2</td><td>Brock Bowers</td><td>75</td><td>107</td></tr>
    <tr><td>3</td><td>Colston Loveland</td><td>69</td><td>97</td></tr>
  </table>
</body></html>
"""

# HTML with JSON-LD dateModified inline; the parser should pick it up.
TE_HTML_WITH_DATE = TE_HTML.replace(
    "</body>",
    (
        '<script type="application/ld+json">'
        '{"dateModified":"2025-01-15T12:00:00Z"}'
        "</script></body>"
    ),
)


# ── Fake fetcher: returns canned HTML per URL keyword ─────────────────
def _make_fake_fetcher(mapping: dict[str, str]):
    def fake_fetch(url, *, timeout=30):
        for key, body in mapping.items():
            if key in url:
                return url, body
        raise RuntimeError(f"unexpected url: {url}")
    # match (final_url, body) signature of _fetch_html
    return lambda url, *, timeout=30: fake_fetch(url, timeout=timeout)


# ── Column picker ─────────────────────────────────────────────────────

class TestColumnPicker:
    def test_qb_picks_2qb_not_1qb(self, yb_module):
        rows = yb_module._parse_position_table(QB_HTML, "QB")
        allen = next(r for r in rows if r.name == "Josh Allen")
        # 2QB column = 141, 1QB column = 66 — must pick 141.
        assert allen.value == 141
        assert allen.pos == "QB"

    def test_te_picks_tep_not_ppr(self, yb_module):
        rows = yb_module._parse_position_table(TE_HTML, "TE")
        mcbride = next(r for r in rows if r.name == "Trey McBride")
        # TE Prem. = 108, PPR = 76 — must pick 108.
        assert mcbride.value == 108
        assert mcbride.pos == "TE"

    def test_rb_picks_ppr(self, yb_module):
        rows = yb_module._parse_position_table(RB_HTML, "RB")
        bijan = next(r for r in rows if r.name == "Bijan Robinson")
        assert bijan.value == 109

    def test_wr_picks_ppr(self, yb_module):
        rows = yb_module._parse_position_table(WR_HTML, "WR")
        jsn = next(r for r in rows if "Smith-Njigba" in r.name)
        assert jsn.value == 106

    def test_html_entities_decoded(self, yb_module):
        rows = yb_module._parse_position_table(WR_HTML, "WR")
        # Ja&#39;Marr → Ja'Marr after html.unescape
        chase = next(r for r in rows if "Marr" in r.name)
        assert chase.name == "Ja'Marr Chase"

    def test_missing_column_raises(self, yb_module):
        # RB HTML has no 2QB column — should fail clearly.
        with pytest.raises(yb_module.YahooBooneSchemaError, match="2QB"):
            yb_module._parse_position_table(RB_HTML, "QB")

    def test_no_table_raises(self, yb_module):
        with pytest.raises(yb_module.YahooBooneSchemaError, match="no <table"):
            yb_module._parse_position_table("<html><body>nope</body></html>", "QB")


# ── Rank assignment ───────────────────────────────────────────────────

class TestRankAssignment:
    def test_descending_by_value(self, yb_module):
        Row = yb_module.YahooRow
        rows = [Row("A", "QB", 100), Row("B", "RB", 80), Row("C", "WR", 60)]
        ranked = yb_module._assign_ranks(rows)
        names = [r.name for r, _ in ranked]
        ranks = [rank for _, rank in ranked]
        assert names == ["A", "B", "C"]
        assert ranks == [1, 2, 3]

    def test_ties_share_rank_competition_style(self, yb_module):
        Row = yb_module.YahooRow
        rows = [
            Row("A", "QB", 10),
            Row("B", "RB", 5),
            Row("C", "WR", 5),
            Row("D", "TE", 3),
        ]
        ranked = yb_module._assign_ranks(rows)
        by_name = {r.name: rank for r, rank in ranked}
        # Competition ranking: B and C are tied → both rank 2, next rank is 4.
        assert by_name["A"] == 1
        assert by_name["B"] == 2
        assert by_name["C"] == 2
        assert by_name["D"] == 4

    def test_cross_position_ranking_mixes_positions(self, yb_module):
        Row = yb_module.YahooRow
        # Josh Allen 2QB=141 beats Bijan Robinson PPR=109.
        rows = [Row("Bijan Robinson", "RB", 109), Row("Josh Allen", "QB", 141)]
        ranked = yb_module._assign_ranks(rows)
        assert [r.name for r, _ in ranked] == ["Josh Allen", "Bijan Robinson"]

    def test_deterministic_tie_ordering(self, yb_module):
        """Ties sort by (position, name) so the CSV is reproducible."""
        Row = yb_module.YahooRow
        rows = [
            Row("Zeke", "QB", 5),
            Row("Abby", "WR", 5),
            Row("Bo", "RB", 5),
        ]
        ranked1 = yb_module._assign_ranks(rows)
        ranked2 = yb_module._assign_ranks(list(reversed(rows)))
        # Both orderings produce the same output sequence.
        assert [(r.name, rank) for r, rank in ranked1] == [
            (r.name, rank) for r, rank in ranked2
        ]


# ── End-to-end: fetch_all orchestration ───────────────────────────────

class TestFetchAll:
    def test_combines_all_four_positions(self, yb_module):
        fake = _make_fake_fetcher(
            {
                "justin-boone-qb": QB_HTML,
                "running-back": RB_HTML,
                "wide-receiver": WR_HTML,
                "justin-boone-te": TE_HTML,
            }
        )
        seeds = {
            "QB": ["https://example.test/justin-boone-qb-1.html"],
            "RB": ["https://example.test/running-back-1.html"],
            "WR": ["https://example.test/wide-receiver-1.html"],
            "TE": ["https://example.test/justin-boone-te-1.html"],
        }
        rows, warnings = yb_module.fetch_all(seeds, fetcher=fake)
        assert len(rows) == 4 + 3 + 3 + 3
        assert warnings == []
        positions = {r.pos for r in rows}
        assert positions == {"QB", "RB", "WR", "TE"}

    def test_falls_back_to_next_seed_on_error(self, yb_module):
        attempts: list[str] = []

        def broken_then_ok(url, *, timeout=30):
            attempts.append(url)
            if "broken" in url:
                raise RuntimeError("HTTP 500")
            return url, QB_HTML

        seeds = {
            "QB": [
                "https://example.test/broken.html",
                "https://example.test/ok-qb.html",
            ],
        }
        rows, warnings = yb_module.fetch_all(seeds, fetcher=broken_then_ok)
        assert len(rows) == 4  # QB fixture has 4 players
        assert warnings == []
        assert len(attempts) == 2

    def test_stale_article_emits_warning(self, yb_module):
        old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
        stale_html = TE_HTML.replace(
            "</body>",
            (
                '<script type="application/ld+json">'
                f'{{"dateModified":"{old}"}}'
                "</script></body>"
            ),
        )
        fake = _make_fake_fetcher({"te": stale_html})
        seeds = {"TE": ["https://example.test/te.html"]}
        rows, warnings = yb_module.fetch_all(seeds, fetcher=fake)
        assert len(rows) == 3
        assert any("old" in w.lower() for w in warnings), warnings

    def test_fresh_article_no_stale_warning(self, yb_module):
        fake = _make_fake_fetcher({"te": TE_HTML_WITH_DATE})
        # dateModified = 2025-01-15 — the age-check uses time.now()
        # which is beyond 45 days, so expect a warning here.  This
        # test documents that we only warn, we never fail.
        seeds = {"TE": ["https://example.test/te.html"]}
        rows, warnings = yb_module.fetch_all(seeds, fetcher=fake)
        assert len(rows) == 3  # still parses successfully despite warning

    def test_failure_emits_warning_but_other_positions_still_return(self, yb_module):
        def mixed_fetcher(url, *, timeout=30):
            if "qb" in url:
                raise RuntimeError("boom")
            return url, RB_HTML

        seeds = {
            "QB": ["https://example.test/qb-broken.html"],
            "RB": ["https://example.test/rb.html"],
        }
        rows, warnings = yb_module.fetch_all(seeds, fetcher=mixed_fetcher)
        assert {r.pos for r in rows} == {"RB"}
        assert any("QB" in w for w in warnings)


# ── CSV writer ────────────────────────────────────────────────────────

class TestCsvWriter:
    def test_value_column_holds_rank_signal(self, yb_module, tmp_path):
        """``value`` is the rank (signal for the pipeline).
        ``boone_value`` preserves the published chart number for humans."""
        Row = yb_module.YahooRow
        rows = [Row("Josh Allen", "QB", 141), Row("Trey McBride", "TE", 108)]
        ranked = yb_module._assign_ranks(rows)
        path = tmp_path / "yahooBoone.csv"
        yb_module._write_csv(path, ranked)

        with path.open() as f:
            data = list(csv.DictReader(f))
        assert data[0]["name"] == "Josh Allen"
        assert data[0]["pos"] == "QB"
        assert data[0]["value"] == "1"           # rank (signal)
        assert data[0]["boone_value"] == "141"  # original chart number
        assert data[1]["value"] == "2"

    def test_csv_is_readable_by_scraper_bridge(self, yb_module, tmp_path):
        """The resulting CSV must be loadable by ScraperBridgeAdapter
        with signal_type='rank'."""
        from src.adapters.scraper_bridge_adapter import ScraperBridgeAdapter

        Row = yb_module.YahooRow
        rows = [Row("Josh Allen", "QB", 141), Row("Bijan Robinson", "RB", 109)]
        ranked = yb_module._assign_ranks(rows)
        path = tmp_path / "yahooBoone.csv"
        yb_module._write_csv(path, ranked)

        adapter = ScraperBridgeAdapter(
            source_id="YAHOO_BOONE",
            source_bucket="offense_vet",
            signal_type="rank",
        )
        result = adapter.load(path)
        assert len(result.records) == 2
        allen = next(r for r in result.records if r.display_name == "Josh Allen")
        # signal_type=rank → rank_raw filled, value_raw None.
        assert allen.rank_raw == 1.0
        assert allen.value_raw is None
        assert allen.position_raw == "QB"
