"""C1-U9 RED — `C1-SRC-01`, the multi-format dynasty source archive.

WHY AN ARCHIVE AT ALL
─────────────────────
``docs/MULTI_FORMAT_SOURCE_NORMALIZATION_SPEC.md`` §2: historical paired
format observations "have option value that cannot reliably be recreated
later". Today ``CSVs/site_raw/*.csv`` is **overwritten in place on every
fetch**, so no per-run version of any source board survives, and the
``data/raw*`` trees have been frozen since April 2026.

The specific opportunity: KTC's four TE-premium states already ship in
**every** scrape response (``superflexValues: {value, tep, tepp, teppp}``
— the scraper reads ``tepp`` and discards the other three). Capturing the
ladder costs no extra request; discarding it loses paired data that
cannot be reconstructed.

THE BOUNDARY THIS FILE EXISTS TO ENFORCE
────────────────────────────────────────
**Archival existence is not production eligibility.** §16 item 9 and §19
are explicit: alternate variants must not be routed into canonical
ranking/value calculations, and collecting them is not authorization to
serve them.

That has to be structural. "Nobody calls this yet" is the state C1-U8's
audit already caught being mistaken for a guarantee, so these tests
assert the property rather than the absence of a caller.

And the trap the spec names twice (§4.2, §6): KTC's four states are
**one provider family**, algorithmically derived from one base crowd
value. Counting them as four votes would manufacture agreement out of a
single opinion — the B10 circularity defect class, reopened through a
new door.
"""

from __future__ import annotations

import pytest

pytest.importorskip(
    "src.source_archive",
    reason="C1-SRC-01 archive not implemented yet — this is the RED",
)

from src.source_archive import (  # noqa: E402
    ARCHIVE_ELIGIBLE,
    PRODUCTION_ELIGIBLE,
    ArchivedBoard,
    archive_board,
    read_boards,
)


LEAGUE_FORMATS = ("1qb", "superflex")


def _board(variant: str, *, game_type: str = "DYNASTY", run_id: str = "run-1") -> ArchivedBoard:
    return ArchivedBoard(
        provider="ktc",
        provider_family="ktc",
        endpoint="keeptradecut.com/dynasty-rankings",
        format_key=variant,
        game_type=game_type,
        run_id=run_id,
        rows={"Josh Allen": 9999.0, "Bijan Robinson": 8000.0},
    )


class TestAnAlternateBoardCanBeArchived:
    def test_a_variant_round_trips(self, tmp_path):
        archive_board(_board("sf_tepp"), path=tmp_path / "a.sqlite")
        boards = read_boards(path=tmp_path / "a.sqlite")
        assert len(boards) == 1
        assert boards[0].format_key == "sf_tepp"
        assert boards[0].rows["Josh Allen"] == 9999.0

    def test_all_four_ktc_states_archive_side_by_side(self, tmp_path):
        db = tmp_path / "a.sqlite"
        for variant in ("sf_off", "sf_tep", "sf_tepp", "sf_teppp"):
            archive_board(_board(variant), path=db)
        assert {b.format_key for b in read_boards(path=db)} == {
            "sf_off",
            "sf_tep",
            "sf_tepp",
            "sf_teppp",
        }

    def test_the_run_id_ties_simultaneous_variants_together(self, tmp_path):
        """§8: paired comparisons must not be contaminated by market
        movement between scrape dates."""
        db = tmp_path / "a.sqlite"
        archive_board(_board("sf_off", run_id="r1"), path=db)
        archive_board(_board("sf_tepp", run_id="r1"), path=db)
        archive_board(_board("sf_off", run_id="r2"), path=db)
        r1 = [b for b in read_boards(path=db) if b.run_id == "r1"]
        assert len(r1) == 2

    def test_reingesting_the_same_board_is_idempotent(self, tmp_path):
        db = tmp_path / "a.sqlite"
        archive_board(_board("sf_tepp"), path=db)
        archive_board(_board("sf_tepp"), path=db)
        assert len(read_boards(path=db)) == 1

    def test_provenance_survives(self, tmp_path):
        db = tmp_path / "a.sqlite"
        archive_board(_board("sf_tepp"), path=db)
        got = read_boards(path=db)[0]
        assert got.endpoint == "keeptradecut.com/dynasty-rankings"
        assert got.provider_family == "ktc"
        assert got.content_hash


class TestGameTypeFailsClosedAtTheArchiveToo:
    def test_an_unknown_game_type_is_refused(self, tmp_path):
        with pytest.raises(Exception):
            archive_board(_board("sf_tepp", game_type="UNKNOWN"), path=tmp_path / "a.sqlite")

    def test_a_redraft_board_is_refused(self, tmp_path):
        with pytest.raises(Exception):
            archive_board(_board("sf_tepp", game_type="REDRAFT"), path=tmp_path / "a.sqlite")


class TestArchiveIsNotProductionEligibility:
    """The load-bearing boundary. It must not be satisfiable by deleting
    one conditional."""

    def test_the_two_sets_are_distinct_concepts(self):
        assert ARCHIVE_ELIGIBLE != PRODUCTION_ELIGIBLE

    def test_no_archived_variant_is_registered_for_voting(self):
        from src.api.data_contract import _RANKING_SOURCES

        voting = {s["key"] for s in _RANKING_SOURCES}
        assert not (ARCHIVE_ELIGIBLE & voting), (
            f"archive-only variants reached the blend registry: "
            f"{ARCHIVE_ELIGIBLE & voting}. Archiving a board is not authorization to "
            f"price with it."
        )

    def test_the_archive_module_cannot_reach_the_blend(self):
        """Structural, not 'nobody calls it': the archive must not be
        importable from the module that computes canonical value."""
        import ast
        from pathlib import Path

        repo = Path(__file__).resolve().parents[2]
        tree = ast.parse((repo / "src" / "api" / "data_contract.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
        assert not any(n.startswith("src.source_archive") for n in imported), (
            "the canonical valuation path imports the source archive — an archived "
            "alternate-format board is one edit away from voting"
        )


class TestFourKtcStatesRemainOneProviderFamily:
    """§4.2 and §6. The four states are algorithmic transformations of
    one base crowd value; counting them separately manufactures
    agreement out of a single opinion (the B10 defect class)."""

    def test_every_ktc_variant_declares_the_same_family(self, tmp_path):
        db = tmp_path / "a.sqlite"
        for variant in ("sf_off", "sf_tep", "sf_tepp", "sf_teppp"):
            archive_board(_board(variant), path=db)
        assert {b.provider_family for b in read_boards(path=db)} == {"ktc"}

    def test_archiving_all_four_does_not_add_independent_families(self, tmp_path):
        from src.api.data_contract import _RANKING_SOURCES, correlation_group_for

        before = {correlation_group_for(s["key"]) for s in _RANKING_SOURCES}
        db = tmp_path / "a.sqlite"
        for variant in ("sf_off", "sf_tep", "sf_tepp", "sf_teppp"):
            archive_board(_board(variant), path=db)
        after = {correlation_group_for(s["key"]) for s in _RANKING_SOURCES}
        assert before == after, (
            "archiving KTC's TEP ladder changed the independent-family set — four "
            "calibration states of one crowd became more than one opinion"
        )
