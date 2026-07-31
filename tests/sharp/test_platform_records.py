from src.intel import platform_ledger
from src.platforms.base import (
    IDENTITY_GLOBAL_VERIFIED,
    IDENTITY_LEAGUE_SCOPED_TEAM,
    NormalizedBatch,
    NormalizedLeague,
    NormalizedManager,
    NormalizedManagerSeason,
    NormalizedMovement,
    NormalizedTransaction,
)
from src.sharp import platform_records


def season(manager_key, league_key, season, identity):
    return NormalizedManagerSeason(
        platform="ffpc",
        league_key=league_key,
        season=season,
        manager_key=manager_key,
        roster_id="1",
        wins=10,
        losses=4,
        ties=0,
        points_for=1800,
        points_against=1600,
        made_playoffs=True,
        is_champion=False,
        is_runner_up=True,
        finish_rank=2,
        team_count=12,
        is_complete=True,
        sharp_eligible=True,
        source_identity_type=identity,
        evidence_status="automated_evidence",
    )


def test_league_scoped_ffpc_identity_cannot_satisfy_multi_league_qualification(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    key = "ffpc:league:L1:team:1"
    batch = NormalizedBatch(
        platform="ffpc",
        managers=[
            NormalizedManager.build(
                "ffpc",
                "league:L1:team:1",
                source_identity_type=IDENTITY_LEAGUE_SCOPED_TEAM,
                identity_scope="league:L1",
            )
        ],
        leagues=[
            NormalizedLeague.build("ffpc", "L1", sharp_eligible=True),
            NormalizedLeague.build("ffpc", "L2", sharp_eligible=True),
        ],
        manager_seasons=[
            season(key, "ffpc:L1", "2025", IDENTITY_LEAGUE_SCOPED_TEAM),
            season(key, "ffpc:L2", "2024", IDENTITY_LEAGUE_SCOPED_TEAM),
        ],
    )
    platform_ledger.ingest_batch(batch, path=path)
    records, evidence = platform_records.build_manager_records(ledger_path=path)
    assert records == []
    assert "league_scoped_identity" in evidence[key].reasons


def test_verified_ffpc_evidence_uses_same_manager_record_type(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    key = "ffpc:site-user-42"
    batch = NormalizedBatch(
        platform="ffpc",
        managers=[
            NormalizedManager.build(
                "ffpc",
                "site-user-42",
                source_identity_type=IDENTITY_GLOBAL_VERIFIED,
                identity_scope="platform",
                identity_confidence=1.0,
            )
        ],
        leagues=[
            NormalizedLeague.build("ffpc", "L1", sharp_eligible=True),
            NormalizedLeague.build("ffpc", "L2", sharp_eligible=True),
        ],
        transactions=[
            NormalizedTransaction.build(
                "ffpc",
                "recent-trade",
                league_key="ffpc:L1",
                season="2026",
                week=1,
                transaction_type="trade",
                status="complete",
                created_ms=1_800_000_000_000,
            )
        ],
        movements=[
            NormalizedMovement.build(
                "ffpc",
                "recent-movement",
                transaction_key="ffpc:recent-trade",
                league_key="ffpc:L1",
                canonical_asset_id="P1",
                source_asset_id="ffpc-P1",
                source_name="Player One",
                asset_type="player",
                action="add",
                manager_key=key,
                roster_id="1",
                counterparty_manager_key=None,
                timestamp_ms=1_800_000_000_000,
            )
        ],
        manager_seasons=[
            season(key, "ffpc:L1", "2025", IDENTITY_GLOBAL_VERIFIED),
            season(key, "ffpc:L2", "2024", IDENTITY_GLOBAL_VERIFIED),
        ],
    )
    platform_ledger.ingest_batch(batch, path=path)
    records, evidence = platform_records.build_manager_records(ledger_path=path)
    assert len(records) == 1
    assert records[0].user_id == key
    assert records[0].dynasty_leagues == 2
    assert evidence[key].automated_eligible_rows == 2


def test_verified_ffpc_seasons_without_activity_remain_insufficient(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    key = "ffpc:site-user-no-activity"
    batch = NormalizedBatch(
        platform="ffpc",
        managers=[
            NormalizedManager.build(
                "ffpc",
                "site-user-no-activity",
                source_identity_type=IDENTITY_GLOBAL_VERIFIED,
                identity_scope="platform",
                identity_confidence=1.0,
            )
        ],
        leagues=[
            NormalizedLeague.build("ffpc", "L1", sharp_eligible=True),
            NormalizedLeague.build("ffpc", "L2", sharp_eligible=True),
        ],
        manager_seasons=[
            season(key, "ffpc:L1", "2025", IDENTITY_GLOBAL_VERIFIED),
            season(key, "ffpc:L2", "2024", IDENTITY_GLOBAL_VERIFIED),
        ],
    )
    platform_ledger.ingest_batch(batch, path=path)
    records, evidence = platform_records.build_manager_records(ledger_path=path)
    assert records == []
    assert "missing_recent_activity" in evidence[key].reasons
