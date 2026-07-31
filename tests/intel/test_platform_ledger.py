from pathlib import Path

from src.intel import ledger, platform_ledger
from src.platforms.base import (
    NormalizedBatch,
    NormalizedLeague,
    NormalizedManager,
    NormalizedMovement,
    NormalizedTransaction,
)


def legacy_event():
    return {
        "eventId": "same:sleeper-user:add:P1",
        "txId": "same",
        "leagueId": "same",
        "ownerId": "sleeper-user",
        "assetId": "P1",
        "assetType": "player",
        "action": "add",
        "txType": "trade",
        "ts": 1_800_000_000_000,
        "week": 1,
        "faabBid": None,
    }


def ffpc_batch():
    return NormalizedBatch(
        platform="ffpc",
        managers=[NormalizedManager.build("ffpc", "same")],
        leagues=[NormalizedLeague.build("ffpc", "same", season="2026")],
        transactions=[
            NormalizedTransaction.build(
                "ffpc", "same", league_key="ffpc:same", season="2026", week=1,
                transaction_type="trade", status="complete", created_ms=1_800_000_100_000
            )
        ],
        movements=[
            NormalizedMovement.build(
                "ffpc", "same:ffpc-user:add:P1", transaction_key="ffpc:same",
                league_key="ffpc:same", canonical_asset_id="P1", source_asset_id="ffpc-p1",
                source_name="Player One", asset_type="player", action="add",
                manager_key="ffpc:same", roster_id="team-1", counterparty_manager_key=None,
                timestamp_ms=1_800_000_100_000
            )
        ],
    )


def test_migration_preserves_sleeper_rows_and_is_idempotent(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    conn = ledger.connect(path)
    ledger.ingest_events([legacy_event()], conn=conn)
    before = ledger.counts(conn=conn)
    conn.close()

    first = platform_ledger.backup_and_migrate(path, backup=True)
    second = platform_ledger.migration_report(path)
    assert first["rowCountsPreserved"] is True
    assert first["backupPath"] and Path(first["backupPath"]).exists()
    assert second["ok"] is True

    conn = ledger.connect(path)
    assert ledger.counts(conn=conn) == before
    row = conn.execute("SELECT platform, transaction_key FROM transactions").fetchone()
    assert tuple(row) == ("sleeper", "sleeper:same")
    conn.close()


def test_same_bare_ids_do_not_collide_and_reingestion_is_noop(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    conn = ledger.connect(path)
    ledger.ingest_events([legacy_event()], conn=conn)
    conn.close()
    platform_ledger.ensure_platform_schema(path).close()
    first = platform_ledger.ingest_batch(ffpc_batch(), path=path)
    second = platform_ledger.ingest_batch(ffpc_batch(), path=path)
    assert first.transactions_inserted == 1 and first.movements_inserted == 1
    assert second.transactions_inserted == 0 and second.movements_inserted == 0

    conn = ledger.connect(path)
    keys = {r[0] for r in conn.execute("SELECT transaction_key FROM transactions")}
    assert keys == {"sleeper:same", "ffpc:same"}
    assert conn.execute("SELECT COUNT(*) FROM asset_movements").fetchone()[0] == 2
    conn.close()


def test_no_orphaned_movements_after_platform_ingest(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    platform_ledger.ingest_batch(ffpc_batch(), path=path)
    report = platform_ledger.migration_report(path)
    assert report["orphans"]["movementTransactions"] == 0


def test_future_legacy_sleeper_writes_receive_platform_keys(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    platform_ledger.ensure_platform_schema(path).close()
    conn = ledger.connect(path)
    ledger.ingest_events([legacy_event()], conn=conn)
    tx = conn.execute(
        "SELECT platform, transaction_key, league_key FROM transactions"
    ).fetchone()
    movement = conn.execute(
        "SELECT platform, movement_key, manager_key, canonical_asset_id "
        "FROM asset_movements"
    ).fetchone()
    assert tuple(tx) == ("sleeper", "sleeper:same", "sleeper:same")
    assert tuple(movement) == (
        "sleeper",
        "sleeper:same:sleeper-user:add:P1",
        "sleeper:sleeper-user",
        "P1",
    )
    conn.close()


def test_migration_keeps_foreign_key_check_clean(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    conn = ledger.connect(path)
    ledger.ingest_events([legacy_event()], conn=conn)
    conn.close()
    platform_ledger.backup_and_migrate(path)
    conn = ledger.connect(path)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_resolving_alias_repairs_previously_unmapped_movements(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    source = ffpc_batch()
    unresolved = NormalizedMovement.build(
        "ffpc",
        "unmapped-movement",
        transaction_key="ffpc:same",
        league_key="ffpc:same",
        canonical_asset_id=None,
        source_asset_id="unknown-ffpc-player",
        source_name="Resolved Later",
        asset_type="player",
        action="add",
        manager_key="ffpc:same",
        roster_id="team-1",
        counterparty_manager_key=None,
        timestamp_ms=1_800_000_100_000,
        metadata={"normalizedName": "resolved later", "mappingReason": "no_exact_match"},
    )
    source.movements = [unresolved]
    platform_ledger.ingest_batch(source, path=path)
    assert len(platform_ledger.unmapped_assets(path)) == 1

    conn = platform_ledger.ensure_platform_schema(path)
    platform_ledger.register_asset_alias(
        platform="ffpc",
        source_asset_id="unknown-ffpc-player",
        canonical_asset_id="P99",
        source_name="Resolved Later",
        normalized_name="resolved later",
        asset_type="player",
        match_method="manual_mapping",
        match_confidence=1.0,
        manually_verified=True,
        conn=conn,
    )
    conn.commit()
    row = conn.execute(
        "SELECT canonical_asset_id, asset_id FROM asset_movements "
        "WHERE movement_key='ffpc:unmapped-movement'"
    ).fetchone()
    conn.close()
    assert tuple(row) == ("P99", "P99")
    assert platform_ledger.unmapped_assets(path) == []


def test_cross_platform_manager_link_requires_explicit_verification(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    platform_ledger.ingest_batch(ffpc_batch(), path=path)
    conn = platform_ledger.ensure_platform_schema(path)
    import pytest

    with pytest.raises(ValueError):
        platform_ledger.link_manager_identity(
            manager_key="ffpc:same",
            canonical_manager_id="person:1",
            link_method="name_match",
            confidence=0.7,
            verified=False,
            conn=conn,
        )
    platform_ledger.link_manager_identity(
        manager_key="ffpc:same",
        canonical_manager_id="person:1",
        link_method="manual_verified",
        confidence=1.0,
        verified=True,
        conn=conn,
    )
    conn.commit()
    link = conn.execute(
        "SELECT link_method, verified FROM manager_identity_links "
        "WHERE manager_key='ffpc:same'"
    ).fetchone()
    conn.close()
    assert tuple(link) == ("manual_verified", 1)


def test_future_sleeper_league_upserts_sync_platform_league(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    platform_ledger.ensure_platform_schema(path).close()
    conn = ledger.connect(path)
    ledger.upsert_leagues(
        [
            {
                "league_id": "legacy-L",
                "season": "2026",
                "name": "Legacy League",
                "settings_json": '{"signalEligible":true,"sharpEligible":true}',
            }
        ],
        conn=conn,
    )
    row = conn.execute(
        "SELECT league_key, platform, sharp_eligible FROM platform_leagues "
        "WHERE league_key='sleeper:legacy-L'"
    ).fetchone()
    conn.close()
    assert tuple(row) == ("sleeper:legacy-L", "sleeper", 1)
