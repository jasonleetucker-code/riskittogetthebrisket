"""Dynasty Nerds IDP Top-275 acquisition — Lane 8 preservation, no valuation.

Pins the schema this source is contracted to (275 rows, 10 named tiers,
Rank/Player/Position/Age/Team/<year> IDP Rank headers) against a real,
frozen fixture of the live page (captured 2026-08-20), and pins that a
shape violation is reported as SCHEMA_CHANGED / PARSE_FAILED rather than
silently producing a thin or wrong board.

The one invariant worth a dedicated test class: **no cardinal value is
ever manufactured**. This source publishes rank and tier only; a future
edit that starts inventing a value from rank position would be exactly
the class of defect Lane 8 exists to prevent on the acquisition side.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.fetch_dynasty_nerds_idp import _extract_source_as_of, _parse_tier_tables
from src.sources.acquisition_state import HEALTHY, SCHEMA_CHANGED
from src.source_archive.store import _reset_setup_cache_for_tests, read_boards

FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "dynasty_nerds"
    / "idp_top275_2026-08-20.html"
)


@pytest.fixture()
def archive_path(tmp_path):
    _reset_setup_cache_for_tests()
    yield tmp_path / "boards.sqlite"
    _reset_setup_cache_for_tests()


@pytest.fixture()
def live_html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


class TestSchemaPin:
    def test_275_rows_ten_tiers(self, live_html: str) -> None:
        rows, problems = _parse_tier_tables(live_html)
        assert problems == []
        assert len(rows) == 275
        assert len({r.tier for r in rows}) == 10

    def test_first_and_last_row_match_the_live_page(self, live_html: str) -> None:
        rows, _ = _parse_tier_tables(live_html)
        by_rank = {r.overall_rank: r for r in rows}
        assert by_rank[1].source_name == "Aidan Hutchinson"
        assert by_rank[1].positional_rank == 1
        assert by_rank[1].position_family == "DL"
        assert by_rank[275].positional_rank == 100

    def test_source_as_of_comes_from_vendor_jsonld_not_now(self, live_html: str) -> None:
        as_of = _extract_source_as_of(live_html)
        assert as_of == "2026-07-28T20:15:36-04:00"


class TestNoCardinalValueIsEverManufactured:
    def test_every_row_value_is_none(self, live_html: str) -> None:
        rows, _ = _parse_tier_tables(live_html)
        assert all(r.value is None for r in rows)
        assert all(r.value_unit is None for r in rows)

    def test_the_repair_is_what_makes_this_pass(self, live_html: str, monkeypatch) -> None:
        """Mutation proof: a version that fabricates value=rank must fail this test."""
        import scripts.fetch_dynasty_nerds_idp as mod

        original = mod.ArchivedRow

        def _fabricating_row(*args, **kwargs):
            kwargs["value"] = float(kwargs.get("overall_rank") or 0)
            kwargs["value_unit"] = "rank_as_value"
            return original(*args, **kwargs)

        monkeypatch.setattr(mod, "ArchivedRow", _fabricating_row)
        rows, _ = mod._parse_tier_tables(live_html)
        assert any(
            r.value is not None for r in rows
        ), "mutation did not take effect — test is not exercising the guard"
        with pytest.raises(AssertionError):
            assert all(r.value is None for r in rows)


class TestSchemaRegressionIsReportedNotSwallowed:
    def test_wrong_header_is_reported_as_a_problem(self) -> None:
        html = (
            """
        <script type="application/ld+json">{"datePublished":"2026-01-01"}</script>
        <h2>Tier 1 | Elite</h2>
        <table><tr><th>Rank</th><th>Player</th><th>Pos</th><th>Age</th><th>Squad</th></tr>
        <tr><td>1</td><td>Test Player</td><td>DL</td><td>25</td><td>DET</td></tr></table>
        """
            * 10
        )
        rows, problems = _parse_tier_tables(html)
        assert rows == []
        assert problems

    def test_thin_board_below_floor_is_schema_changed(self) -> None:
        html = (
            '<script type="application/ld+json">{"datePublished":"2026-01-01"}</script>\n'
            + "\n".join(
                f"""<h2>Tier {i} | X</h2>
                <table><tr><th>Rank</th><th>Player</th><th>Position</th><th>Age</th><th>Team</th><th>IDP Rank</th></tr>
                <tr><td>{i}</td><td>Player {i}</td><td>DL</td><td>25</td><td>DET</td><td>DL{i}</td></tr></table>"""
                for i in range(1, 11)
            )
        )
        rows, problems = _parse_tier_tables(html)
        assert len(rows) == 10
        assert any("floor" in p for p in problems)

    def test_no_tables_at_all_is_parse_failed(self, archive_path) -> None:
        rows, problems = _parse_tier_tables("<html><body>nothing here</body></html>")
        assert rows == []


class TestArchiveRoundTrip:
    def test_run_archives_a_healthy_board(self, archive_path, live_html, monkeypatch) -> None:
        import scripts.fetch_dynasty_nerds_idp as mod

        monkeypatch.setattr(mod, "_fetch", lambda timeout=20.0: live_html)
        outcome = mod.run(archive_path=archive_path)
        assert outcome.state == HEALTHY
        assert outcome.row_count == 275

        (stored,) = read_boards(path=archive_path)
        assert stored.provider == "dynastyNerds"
        assert stored.provider_family == "dynastyNerds"
        assert stored.format_key == "idp_top275"
        assert stored.game_type == "DYNASTY"
        assert len(stored.records) == 275
        assert all(r.value is None for r in stored.records)

    def test_fetch_failure_is_unavailable_not_a_healthy_empty_board(
        self, archive_path, monkeypatch
    ) -> None:
        import scripts.fetch_dynasty_nerds_idp as mod

        monkeypatch.setattr(mod, "_fetch", lambda timeout=20.0: None)
        outcome = mod.run(archive_path=archive_path)
        assert outcome.state == "UNAVAILABLE"
        assert outcome.row_count is None

        assert read_boards(path=archive_path) == []

    def test_schema_regression_does_not_archive(self, archive_path, monkeypatch) -> None:
        import scripts.fetch_dynasty_nerds_idp as mod

        broken_html = (
            '<script type="application/ld+json">{"datePublished":"2026-01-01"}</script>\n'
            + "\n".join(
                f"""<h2>Tier {i} | X</h2>
                <table><tr><th>Rank</th><th>Player</th><th>Position</th><th>Age</th><th>Team</th><th>IDP Rank</th></tr>
                <tr><td>{i}</td><td>Player {i}</td><td>DL</td><td>25</td><td>DET</td><td>DL{i}</td></tr></table>"""
                for i in range(1, 11)
            )
        )
        monkeypatch.setattr(mod, "_fetch", lambda timeout=20.0: broken_html)
        outcome = mod.run(archive_path=archive_path)
        assert outcome.state == SCHEMA_CHANGED
        assert outcome.row_count is None
        assert read_boards(path=archive_path) == []
