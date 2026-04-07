"""Tests for the canonical player pool builder."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.pool.builder import (
    CanonicalPoolRow,
    AdamidpRow,
    PoolAuditReport,
    build_canonical_pool,
    extract_ktc_structured,
    extract_sleeper_roster_names,
    dedupe_adamidp_rows,
    extract_adamidp_from_artifact,
    pool_clean_name,
    pool_normalize_lookup,
    normalize_position,
    KTC_UNIVERSE_LIMIT,
)


# ── Fixtures ──

def _sleeper_data(names_positions: dict[str, str], ids: dict[str, str] | None = None) -> dict:
    return {
        "positions": names_positions,
        "playerIds": ids or {},
    }


def _ktc_data(players: list[tuple[str, float]]) -> dict[str, float]:
    return {name: val for name, val in players}


# ── Pool builder: membership tests ──

class TestPoolMembership:
    def test_sleeper_fringe_player_outside_ktc_is_included(self):
        """A Sleeper-rostered player absent from KTC still enters the universe."""
        sleeper = _sleeper_data({"Tyler Lockett": "WR"})
        ktc = _ktc_data([("Josh Allen", 9000)])
        rows, report = build_canonical_pool(
            sleeper_roster_data=sleeper,
            full_data_ktc=ktc,
        )
        names = {r.canonical_name for r in rows}
        assert "Tyler Lockett" in names
        lockett = next(r for r in rows if r.canonical_name == "Tyler Lockett")
        assert lockett.in_sleeper is True
        assert lockett.in_ktc_top525 is False

    def test_ktc_top525_player_not_on_sleeper_is_included(self):
        """A KTC top-525 player not on the Sleeper roster still enters."""
        sleeper = _sleeper_data({"Josh Allen": "QB"})
        ktc = _ktc_data([("Josh Allen", 9000), ("Random KTC Player", 500)])
        rows, report = build_canonical_pool(
            sleeper_roster_data=sleeper,
            full_data_ktc=ktc,
        )
        names = {r.canonical_name for r in rows}
        assert "Random KTC Player" in names
        rp = next(r for r in rows if r.canonical_name == "Random KTC Player")
        assert rp.in_ktc_top525 is True
        assert rp.in_sleeper is False

    def test_adamidp_only_idp_is_included(self):
        """An Adamidp-only IDP absent from KTC and Sleeper enters the universe."""
        sleeper = _sleeper_data({"Josh Allen": "QB"})
        ktc = _ktc_data([("Josh Allen", 9000)])
        adamidp_rows = [
            AdamidpRow(
                overall_rank=1,
                player_name="Will Anderson",
                position="DL",
                position_rank=1,
                trade_value_text="Tier 1",
                source_pdf="idp_vet.pdf",
            )
        ]
        rows, report = build_canonical_pool(
            sleeper_roster_data=sleeper,
            full_data_ktc=ktc,
            adamidp_rows=adamidp_rows,
        )
        names = {r.canonical_name for r in rows}
        assert "Will Anderson" in names
        wa = next(r for r in rows if r.canonical_name == "Will Anderson")
        assert wa.in_adamidp_pdf is True
        assert wa.in_sleeper is False
        assert wa.in_ktc_top525 is False

    def test_final_union_is_deduped(self):
        """Same player in Sleeper + KTC appears once with both flags."""
        sleeper = _sleeper_data({"Josh Allen": "QB"})
        ktc = _ktc_data([("Josh Allen", 9000)])
        rows, report = build_canonical_pool(
            sleeper_roster_data=sleeper,
            full_data_ktc=ktc,
        )
        allens = [r for r in rows if "josh allen" in r.canonical_name.lower()]
        assert len(allens) == 1
        assert allens[0].in_sleeper is True
        assert allens[0].in_ktc_top525 is True

    def test_no_arbitrary_cap_beyond_ktc_525(self):
        """KTC entries beyond 525 should not be in the universe (only top 525)."""
        ktc = _ktc_data([(f"Player {i}", 10000 - i) for i in range(600)])
        rows, report = build_canonical_pool(
            sleeper_roster_data=_sleeper_data({}),
            full_data_ktc=ktc,
        )
        ktc_members = [r for r in rows if r.in_ktc_top525]
        assert len(ktc_members) == KTC_UNIVERSE_LIMIT
        assert report.ktc_top525_count == KTC_UNIVERSE_LIMIT

    def test_idp_trade_calc_enriches_but_does_not_decide_membership(self):
        """IDPTradeCalc only enriches — a player ONLY in IDPTradeCalc is NOT in the union."""
        sleeper = _sleeper_data({"Josh Allen": "QB"})
        ktc = _ktc_data([("Josh Allen", 9000)])
        idp_tc = {"Unique IDP Player": 3000, "Josh Allen": 8500}
        rows, report = build_canonical_pool(
            sleeper_roster_data=sleeper,
            full_data_ktc=ktc,
            idp_trade_calc_data=idp_tc,
        )
        names = {r.canonical_name for r in rows}
        # "Unique IDP Player" is only in IDPTradeCalc — should NOT be in pool
        assert "Unique IDP Player" not in names
        # Josh Allen should be enriched with IDPTradeCalc value
        allen = next(r for r in rows if r.canonical_name == "Josh Allen")
        assert allen.idp_trade_calc_matched is True
        assert allen.idp_trade_calc_value == 8500


# ── KTC structured ingestion ──

class TestKtcStructured:
    def test_ktc_rows_have_rank_and_value(self):
        ktc = _ktc_data([("A", 9000), ("B", 8000), ("C", 7000)])
        rows = extract_ktc_structured(ktc, limit=3)
        assert len(rows) == 3
        assert rows[0]["source_rank"] == 1
        assert rows[0]["source_value"] == 9000
        assert rows[2]["source_rank"] == 3

    def test_ktc_excludes_picks(self):
        ktc = {"Josh Allen": 9000, "2026 Early 1st": 7000}
        rows = extract_ktc_structured(ktc)
        names = [r["name"] for r in rows]
        assert "Josh Allen" in names
        assert not any("2026" in n for n in names)


# ── Adamidp PDF extraction ──

class TestAdamidpExtraction:
    def test_split_line_names_dedupe(self):
        """Overlapping PDF segments dedupe correctly."""
        rows = [
            AdamidpRow(overall_rank=1, player_name="Will Anderson", position="DL",
                       position_rank=1, source_pdf="a.pdf"),
            AdamidpRow(overall_rank=1, player_name="Will Anderson", position="DL",
                       position_rank=1, source_pdf="b.pdf"),
            AdamidpRow(overall_rank=2, player_name="Micah Parsons", position="LB",
                       position_rank=1, source_pdf="a.pdf"),
        ]
        unique, ambig = dedupe_adamidp_rows(rows)
        assert len(unique) == 2
        assert len(ambig) == 0
        names = {r.player_name for r in unique}
        assert "Will Anderson" in names
        assert "Micah Parsons" in names

    def test_malformed_rows_become_ambiguous(self):
        """Rows marked ambiguous are separated."""
        rows = [
            AdamidpRow(overall_rank=1, player_name="Will Anderson", position="DL"),
            AdamidpRow(player_name="???", ambiguous=True, ambiguous_reason="bad parse"),
        ]
        unique, ambig = dedupe_adamidp_rows(rows)
        assert len(unique) == 1
        assert len(ambig) == 1
        assert ambig[0].ambiguous_reason == "bad parse"

    def test_artifact_read(self):
        """Read from a JSON artifact file."""
        data = {
            "rows": [
                {"overallRank": 1, "playerName": "Will Anderson", "position": "DL",
                 "positionRank": 1, "tradeValueText": "Tier 1"},
                {"overallRank": 2, "playerName": "Micah Parsons", "position": "LB",
                 "positionRank": 1, "tradeValueText": "Tier 1"},
            ]
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            rows = extract_adamidp_from_artifact(f.name)
        assert len(rows) == 2
        assert rows[0].player_name == "Will Anderson"
        assert rows[0].overall_rank == 1


# ── Name matching/identity tests ──

class TestNameMatching:
    def test_jr_sr_normalization(self):
        assert pool_normalize_lookup("Patrick Mahomes Jr.") == pool_normalize_lookup("Patrick Mahomes")
        assert pool_normalize_lookup("Odell Beckham Jr") == pool_normalize_lookup("Odell Beckham")

    def test_ii_iii_normalization(self):
        assert pool_normalize_lookup("Travis Kelce III") == pool_normalize_lookup("Travis Kelce")

    def test_apostrophe_handling(self):
        assert pool_normalize_lookup("Ja'Marr Chase") == pool_normalize_lookup("JaMarr Chase")
        assert pool_normalize_lookup("Ja\u2019Marr Chase") == pool_normalize_lookup("JaMarr Chase")

    def test_hyphen_handling(self):
        assert pool_normalize_lookup("Amon-Ra St. Brown") == pool_normalize_lookup("Amon Ra St Brown")

    def test_initial_handling(self):
        assert pool_normalize_lookup("T.J. Watt") == pool_normalize_lookup("TJ Watt")
        assert pool_normalize_lookup("A.J. Brown") == pool_normalize_lookup("AJ Brown")

    def test_punctuation_spacing(self):
        assert pool_normalize_lookup("D.J. Moore") == pool_normalize_lookup("DJ Moore")


# ── Position safety ──

class TestPositionSafety:
    def test_offense_cannot_become_idp(self):
        """An offensive player cannot be reclassified as IDP from fallback joins."""
        sleeper = _sleeper_data({"DJ Moore": "WR"})
        ktc = _ktc_data([("DJ Moore", 5000)])
        rows, _ = build_canonical_pool(
            sleeper_roster_data=sleeper,
            full_data_ktc=ktc,
        )
        moore = next(r for r in rows if "moore" in r.canonical_name.lower())
        assert moore.position == "WR"

    def test_position_normalization(self):
        assert normalize_position("DE") == "DL"
        assert normalize_position("DT") == "DL"
        assert normalize_position("CB") == "DB"
        assert normalize_position("SS") == "DB"
        assert normalize_position("OLB") == "LB"
        assert normalize_position("QB") == "QB"


# ── IDPTradeCalc crosswalk ──

class TestIDPTradeCalcCrosswalk:
    def test_every_union_player_is_queried(self):
        sleeper = _sleeper_data({"A": "QB", "B": "RB"})
        ktc = _ktc_data([("A", 9000), ("C", 8000)])
        idp_tc = {"A": 8500, "C": 7500}
        rows, report = build_canonical_pool(
            sleeper_roster_data=sleeper,
            full_data_ktc=ktc,
            idp_trade_calc_data=idp_tc,
        )
        # Union is {A, B, C} = 3 players. All should be queried.
        assert report.idp_trade_calc_queried_count == 3
        assert report.idp_trade_calc_matched_count == 2  # A and C
        assert report.idp_trade_calc_unmatched_count == 1  # B
        assert report.idp_trade_calc_matched_count + report.idp_trade_calc_unmatched_count == report.idp_trade_calc_queried_count

    def test_unmatched_names_reported(self):
        sleeper = _sleeper_data({"A": "QB", "B": "RB"})
        ktc = _ktc_data([("A", 9000)])
        idp_tc = {"A": 8500}
        rows, report = build_canonical_pool(
            sleeper_roster_data=sleeper,
            full_data_ktc=ktc,
            idp_trade_calc_data=idp_tc,
        )
        assert "B" in report.idp_trade_calc_unmatched_names


# ── Audit report ──

class TestAuditReport:
    def test_report_has_all_counts(self):
        sleeper = _sleeper_data({"A": "QB"})
        ktc = _ktc_data([("B", 9000)])
        rows, report = build_canonical_pool(
            sleeper_roster_data=sleeper,
            full_data_ktc=ktc,
        )
        assert report.sleeper_count == 1
        assert report.ktc_top525_count == 1
        assert report.final_union_count == 2

    def test_report_serializable(self):
        """Report can be serialized to JSON."""
        sleeper = _sleeper_data({"A": "QB"})
        ktc = _ktc_data([("B", 9000)])
        _, report = build_canonical_pool(
            sleeper_roster_data=sleeper,
            full_data_ktc=ktc,
        )
        d = report.to_dict()
        json_str = json.dumps(d)
        assert "sleeper_count" in json_str


# ── Integration: Adamidp IDP players survive downstream ──

class TestAdamidpIntegration:
    """Integration tests: IDP players from Adamidp survive through pool builder."""

    def test_adamidp_idp_players_survive_in_pool(self):
        """Real IDP names from the Adamidp list appear in the canonical pool."""
        sleeper = _sleeper_data({"Josh Allen": "QB"})
        ktc = _ktc_data([("Josh Allen", 9000)])
        adamidp_rows = [
            AdamidpRow(overall_rank=1, player_name="Travis Hunter", position="DB"),
            AdamidpRow(overall_rank=2, player_name="Will Anderson", position="DL"),
            AdamidpRow(overall_rank=3, player_name="Aidan Hutchinson", position="DL"),
            AdamidpRow(overall_rank=4, player_name="Carson Schwesinger", position="LB"),
            AdamidpRow(overall_rank=41, player_name="Rueben Bain Jr.", position="DL"),
        ]
        rows, report = build_canonical_pool(
            sleeper_roster_data=sleeper,
            full_data_ktc=ktc,
            adamidp_rows=adamidp_rows,
        )
        names = {r.canonical_name for r in rows}
        # All Adamidp IDP players should be in the pool
        for expected in ["Travis Hunter", "Will Anderson", "Aidan Hutchinson",
                         "Carson Schwesinger"]:
            assert expected in names, f"{expected} missing from pool"
        # Rueben Bain Jr. should match after suffix stripping
        assert any("Rueben Bain" in n for n in names), "Rueben Bain Jr. missing from pool"

    def test_adamidp_idp_positions_preserved(self):
        """IDP positions from Adamidp are preserved in the pool."""
        sleeper = _sleeper_data({})
        ktc = _ktc_data([])
        adamidp_rows = [
            AdamidpRow(overall_rank=1, player_name="Travis Hunter", position="DB"),
            AdamidpRow(overall_rank=2, player_name="Will Anderson", position="DL"),
            AdamidpRow(overall_rank=4, player_name="Fred Warner", position="LB"),
        ]
        rows, _ = build_canonical_pool(
            sleeper_roster_data=sleeper,
            full_data_ktc=ktc,
            adamidp_rows=adamidp_rows,
        )
        hunter = next(r for r in rows if r.canonical_name == "Travis Hunter")
        anderson = next(r for r in rows if r.canonical_name == "Will Anderson")
        warner = next(r for r in rows if r.canonical_name == "Fred Warner")
        assert hunter.position == "DB"
        assert anderson.position == "DL"
        assert warner.position == "LB"

    def test_offense_players_not_emitted_as_idp(self):
        """DJ Moore and Elijah Mitchell cannot be reclassified as IDP."""
        sleeper = _sleeper_data({
            "DJ Moore": "WR",
            "Elijah Mitchell": "RB",
        })
        ktc = _ktc_data([("DJ Moore", 5000), ("Elijah Mitchell", 3000)])
        # Even if somehow an Adamidp row matches these offense players,
        # position safety prevents reclassification.
        adamidp_rows = [
            AdamidpRow(overall_rank=99, player_name="DJ Moore", position="DB"),  # wrong pos
        ]
        rows, _ = build_canonical_pool(
            sleeper_roster_data=sleeper,
            full_data_ktc=ktc,
            adamidp_rows=adamidp_rows,
        )
        moore = next(r for r in rows if "moore" in r.canonical_name.lower())
        mitchell = next(r for r in rows if "mitchell" in r.canonical_name.lower())
        assert moore.position == "WR", f"DJ Moore wrongly classified as {moore.position}"
        assert mitchell.position == "RB", f"Elijah Mitchell wrongly classified as {mitchell.position}"

    def test_adamidp_artifact_reads_correctly(self):
        """The artifact file format is correctly parsed."""
        artifact_path = Path(__file__).resolve().parents[2] / "data" / "adamidp_normalized.json"
        if not artifact_path.exists():
            pytest.skip("adamidp artifact not present")
        rows = extract_adamidp_from_artifact(artifact_path)
        assert len(rows) > 300, f"Expected 300+ rows, got {len(rows)}"
        # First row should be Travis Hunter
        assert rows[0].player_name == "Travis Hunter"
        assert rows[0].position == "DB"
        assert rows[0].overall_rank == 1
        # All positions should be normalized IDP
        for r in rows:
            assert r.position in {"DL", "LB", "DB"}, f"{r.player_name} has position {r.position}"

    def test_pool_audit_counts_with_adamidp(self):
        """Pool audit includes Adamidp counts."""
        sleeper = _sleeper_data({"Josh Allen": "QB"})
        ktc = _ktc_data([("Josh Allen", 9000)])
        adamidp_rows = [
            AdamidpRow(overall_rank=i, player_name=f"IDP Player {i}", position="LB")
            for i in range(1, 11)
        ]
        _, report = build_canonical_pool(
            sleeper_roster_data=sleeper,
            full_data_ktc=ktc,
            adamidp_rows=adamidp_rows,
        )
        assert report.adamidp_extracted_raw_count == 10
        assert report.adamidp_unique_count == 10
        assert report.final_union_count == 11  # 1 KTC/Sleeper + 10 Adamidp
