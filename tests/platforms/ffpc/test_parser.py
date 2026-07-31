from pathlib import Path

import pytest

from src.platforms.assets import AssetResolver
from src.platforms.ffpc.parser import FFPCParser

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def parser():
    import json

    players = json.loads((FIXTURES / "players.json").read_text(encoding="utf-8"))
    return FFPCParser(AssetResolver.from_sleeper_directory(players))


def parse(parser, name, season="2026"):
    return parser.parse(
        (FIXTURES / name).read_text(encoding="utf-8"),
        source_url="https://myffpc.com/public/league?id=L1",
        source_league_id="L1",
        season=season,
        format_type="dynasty",
        fetched_ms=1_800_000_000_000,
    )


def test_standings_preserve_identity_scope_and_completed_evidence(parser):
    result = parse(parser, "standings.html")
    assert result.page_types == {"standings"}
    assert len(result.batch.manager_seasons) == 2
    global_manager = next(m for m in result.batch.managers if m.display_name == "Alice Sharp")
    scoped_manager = next(m for m in result.batch.managers if m.display_name == "Bob Highstakes")
    assert global_manager.source_identity_type == "global_unverified"
    assert scoped_manager.source_identity_type == "league_scoped_team"
    assert "league_scoped_identity" in result.batch.manager_seasons[1].exclusion_reasons
    assert all(row.sharp_eligible is False for row in result.batch.manager_seasons)


def test_duplicate_team_side_trade_rows_do_not_duplicate_movements(parser):
    result = parse(parser, "transactions.html")
    assert len(result.batch.transactions) == 2  # one trade, one waiver
    trade_key = "ffpc:league:L1:tx:TX-1"
    trade = [m for m in result.batch.movements if m.transaction_key == trade_key]
    assert len(trade) == 2
    assert {m.action for m in trade} == {"add", "drop"}
    waiver_key = "ffpc:league:L1:tx:W-1"
    waiver = [m for m in result.batch.movements if m.transaction_key == waiver_key]
    assert len(waiver) == 1 and waiver[0].faab_bid == 77


def test_multi_asset_trade_and_pick_mapping(parser):
    result = parse(parser, "multi_asset_trade.html")
    assert len(result.batch.transactions) == 1
    assert len(result.batch.movements) == 4
    pick_ids = {m.canonical_asset_id for m in result.batch.movements if m.asset_type == "pick"}
    assert pick_ids == {"pick:2027:1:team-12"}


def test_changed_column_order_and_missing_optional_columns(parser):
    result = parse(parser, "reordered_missing_optional.html")
    assert len(result.batch.transactions) == 1
    assert result.batch.movements[0].canonical_asset_id == "9999"


def test_roster_page(parser):
    result = parse(parser, "rosters.html")
    assert result.page_types == {"rosters"}
    assert len(result.batch.memberships) == 1
    assets = result.batch.memberships[0].metadata["rosterAssets"]
    assert len(assets) == 2
    assert assets[0]["canonicalAssetId"] == "4046"


def test_historical_page_stores_unknowns_honestly(parser):
    result = parse(parser, "historical_season.html", season="2025")
    assert len(result.batch.manager_seasons) == 2
    assert all(row.is_complete for row in result.batch.manager_seasons)
    assert all(not row.sharp_eligible for row in result.batch.manager_seasons)


def test_invalid_page_returns_parse_failure_not_fabricated_data(parser):
    result = parse(parser, "invalid.html")
    assert result.errors == ["no_supported_ffpc_tables"]
    assert not result.batch.transactions
    assert not result.batch.manager_seasons


def test_no_authoritative_transaction_id_uses_order_independent_trade_fingerprint(parser):
    result = parse(parser, "no_transaction_id_duplicate.html")
    assert len(result.batch.transactions) == 1
    assert len(result.batch.movements) == 2
    assert result.batch.counters["transactionsDeduplicated"] == 2
    assert result.batch.counters["movementsSkippedAsDuplicates"] == 1
    assert result.batch.transactions[0].source_transaction_id.startswith("league:L1:fingerprint:")


def test_standings_unknown_fields_remain_unknown_not_zero(parser):
    result = parse(parser, "historical_season.html", season="2025")
    assert all(row.ties is None for row in result.batch.manager_seasons)
    assert all("missing_ties" in row.exclusion_reasons for row in result.batch.manager_seasons)


def test_verified_complete_ffpc_evidence_can_enter_automated_layer(parser):
    result = parser.parse(
        (FIXTURES / "standings.html").read_text(encoding="utf-8"),
        source_url="https://myffpc.com/public/league?id=L1",
        source_league_id="L1",
        season="2025",
        format_type="dynasty",
        fetched_ms=1_800_000_000_000,
        sharp_eligible=True,
        verified_global_ids={"501"},
        season_complete=True,
    )
    alice = next(
        row for row in result.batch.manager_seasons if row.manager_key == "ffpc:site-user-501"
    )
    bob = next(row for row in result.batch.manager_seasons if row.manager_key != alice.manager_key)
    assert alice.sharp_eligible is True
    assert alice.evidence_status == "automated_evidence"
    assert bob.sharp_eligible is False
    assert "league_scoped_identity" in bob.exclusion_reasons


def test_draft_board_is_parsed_for_mapping_audit_not_trade_signal(parser):
    result = parse(parser, "draft_board.html")
    assert "draft" in result.page_types
    assert len(result.batch.draft_results) == 2
    assert result.batch.draft_results[0]["canonicalAssetId"] == "4046"
    assert result.batch.draft_results[1]["canonicalAssetId"] is None
    assert result.batch.transactions == []
    assert result.batch.movements == []


def test_authoritative_transaction_ids_are_scoped_to_ffpc_league(parser):
    html = (FIXTURES / "transactions.html").read_text(encoding="utf-8")
    first = parser.parse(
        html,
        source_url="https://myffpc.com/public/league?id=L1",
        source_league_id="L1",
        season="2026",
        format_type="dynasty",
        fetched_ms=1_800_000_000_000,
    )
    second = parser.parse(
        html,
        source_url="https://myffpc.com/public/league?id=L2",
        source_league_id="L2",
        season="2026",
        format_type="dynasty",
        fetched_ms=1_800_000_000_000,
    )
    first_keys = {row.transaction_key for row in first.batch.transactions}
    second_keys = {row.transaction_key for row in second.batch.transactions}
    assert first_keys.isdisjoint(second_keys)
