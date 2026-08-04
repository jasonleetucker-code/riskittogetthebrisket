from src.intel import platform_ledger
from src.platforms.base import (
    NormalizedBatch,
    NormalizedLeague,
    NormalizedManager,
    NormalizedMovement,
    NormalizedTransaction,
)
from src.sharp import market

NOW = 1_800_000_000_000


def batch(platform, manager, league, tx, movement, action="add", tx_type="trade"):
    manager_key = f"{platform}:{manager}"
    league_key = f"{platform}:{league}"
    return NormalizedBatch(
        platform=platform,
        managers=[NormalizedManager.build(platform, manager)],
        leagues=[NormalizedLeague.build(platform, league)],
        transactions=[
            NormalizedTransaction.build(
                platform,
                tx,
                league_key=league_key,
                season="2026",
                week=1,
                transaction_type=tx_type,
                status="complete",
                created_ms=NOW - 10_000,
            )
        ],
        movements=[
            NormalizedMovement.build(
                platform,
                movement,
                transaction_key=f"{platform}:{tx}",
                league_key=league_key,
                canonical_asset_id="P1",
                source_asset_id=f"{platform}-p1",
                source_name="Unified Player",
                asset_type="player",
                action=action,
                manager_key=manager_key,
                roster_id="1",
                counterparty_manager_key=None,
                timestamp_ms=NOW - 10_000,
            )
        ],
    )


def members():
    return [
        market.CohortMember("sleeper:u1", "sleeper", "automated_qualified", 0.9),
        market.CohortMember("ffpc:f1", "ffpc", "curated_high_stakes", 0.7),
    ], {"automatedQualifiedManagers": 1, "curatedManagers": 1}


def test_same_canonical_player_is_one_combined_row_with_reconciled_sources(tmp_path, monkeypatch):
    path = tmp_path / "ledger.sqlite3"
    platform_ledger.ingest_batch(batch("sleeper", "u1", "L1", "T1", "M1"), path=path)
    platform_ledger.ingest_batch(batch("ffpc", "f1", "L2", "T2", "M2"), path=path)
    monkeypatch.setattr(market, "cohort_members", lambda **kwargs: members())
    payload = market.market_payload(
        window="30d",
        now_ms=NOW,
        ledger_path=path,
        ffpc_config={"enabled": True, "allowCuratedInCombinedSignals": True},
    )
    assert len(payload["assets"]) == 1
    row = payload["assets"][0]
    assert row["assetId"] == "P1"
    assert row["windows"]["30d"]["buys"] == 2
    assert row["windows"]["30d"]["volume"] == 2
    assert row["sourceLabels"] == ["FFPC", "Sleeper"]
    assert row["sources"]["sleeper"]["buys"] + row["sources"]["ffpc"]["buys"] == 2


def test_platform_filter_uses_source_specific_raw_counts(tmp_path, monkeypatch):
    path = tmp_path / "ledger.sqlite3"
    platform_ledger.ingest_batch(batch("sleeper", "u1", "L1", "T1", "M1"), path=path)
    platform_ledger.ingest_batch(batch("ffpc", "f1", "L2", "T2", "M2"), path=path)
    monkeypatch.setattr(market, "cohort_members", lambda **kwargs: members())
    payload = market.market_payload(
        window="30d",
        platform="ffpc",
        now_ms=NOW,
        ledger_path=path,
        ffpc_config={"enabled": True, "allowCuratedInCombinedSignals": True},
    )
    row = payload["assets"][0]
    assert row["windows"]["30d"]["buys"] == 1
    assert row["sourceLabels"] == ["FFPC"]


def test_explicit_canonical_manager_link_prevents_cross_platform_unique_count_inflation(
    tmp_path, monkeypatch
):
    path = tmp_path / "ledger.sqlite3"
    platform_ledger.ingest_batch(batch("sleeper", "u1", "L1", "T1", "M1"), path=path)
    platform_ledger.ingest_batch(batch("ffpc", "f1", "L2", "T2", "M2"), path=path)
    conn = platform_ledger.ensure_platform_schema(path)
    for manager_key in ("sleeper:u1", "ffpc:f1"):
        platform_ledger.link_manager_identity(
            manager_key=manager_key,
            canonical_manager_id="person:verified-1",
            link_method="manual_verified",
            confidence=1.0,
            verified=True,
            conn=conn,
        )
    conn.commit()
    conn.close()
    monkeypatch.setattr(market, "cohort_members", lambda **kwargs: members())
    row = market.market_payload(
        window="30d", now_ms=NOW, ledger_path=path, ffpc_config={"enabled": True}
    )["assets"][0]
    assert row["windows"]["30d"]["uniqueManagers"] == 1


def test_waiver_never_enters_trade_buy_signal(tmp_path, monkeypatch):
    path = tmp_path / "ledger.sqlite3"
    platform_ledger.ingest_batch(batch("sleeper", "u1", "L1", "T1", "M1"), path=path)
    platform_ledger.ingest_batch(
        batch("ffpc", "f1", "L2", "W1", "WM1", tx_type="waiver"), path=path
    )
    monkeypatch.setattr(market, "cohort_members", lambda **kwargs: members())
    row = market.market_payload(
        window="30d", now_ms=NOW, ledger_path=path, ffpc_config={"enabled": True}
    )["assets"][0]
    assert row["windows"]["30d"]["buys"] == 1
    assert "ffpc" not in row["sources"]


def test_nested_windows_are_independent_views_not_added(tmp_path, monkeypatch):
    path = tmp_path / "ledger.sqlite3"
    platform_ledger.ingest_batch(batch("sleeper", "u1", "L1", "T1", "M1"), path=path)
    monkeypatch.setattr(market, "cohort_members", lambda **kwargs: members())
    thirty = market.market_payload(window="30d", now_ms=NOW, ledger_path=path, ffpc_config={})[
        "assets"
    ][0]
    ninety = market.market_payload(window="90d", now_ms=NOW, ledger_path=path, ffpc_config={})[
        "assets"
    ][0]
    assert thirty["windows"]["30d"]["volume"] == 1
    assert ninety["windows"]["90d"]["volume"] == 1


def test_source_failure_is_degraded_without_hiding_sleeper_rows(tmp_path, monkeypatch):
    path = tmp_path / "ledger.sqlite3"
    platform_ledger.ingest_batch(batch("sleeper", "u1", "L1", "T1", "M1"), path=path)
    platform_ledger.record_ingestion_run(
        run_id="ffpc-failed",
        platform="ffpc",
        source_ref="L2",
        started_ms=NOW - 1_000,
        finished_ms=NOW,
        status="failed",
        error={"type": "ParserError", "message": "layout changed"},
        path=path,
    )
    monkeypatch.setattr(market, "cohort_members", lambda **kwargs: members())
    payload = market.market_payload(
        window="30d",
        now_ms=NOW,
        ledger_path=path,
        ffpc_config={"enabled": True},
    )
    assert len(payload["assets"]) == 1
    assert payload["assets"][0]["sources"].keys() == {"sleeper"}
    assert payload["coverage"]["platforms"]["ffpc"]["status"] == "degraded"


def test_per_observation_manager_quality_uses_actual_asset_contributors(tmp_path, monkeypatch):
    path = tmp_path / "ledger.sqlite3"
    platform_ledger.ingest_batch(batch("sleeper", "u1", "L1", "T1", "M1"), path=path)
    platform_ledger.ingest_batch(batch("ffpc", "f1", "L2", "T2", "M2"), path=path)
    monkeypatch.setattr(market, "cohort_members", lambda **kwargs: members())
    row = market.market_payload(
        window="30d", now_ms=NOW, ledger_path=path, ffpc_config={"enabled": True}
    )["assets"][0]
    assert row["managerQuality"] == 0.8


def test_curated_contribution_is_disabled_by_default():
    config = {
        "curatedManagers": [
            {
                "managerKey": "ffpc:site-user-7",
                "verified": True,
                "allowedToContribute": True,
                "weight": 0.8,
            }
        ],
        "allowCuratedInCombinedSignals": False,
    }
    selected, coverage = market.cohort_members(qualification="curated", ffpc_config=config)
    assert selected == []
    assert coverage["curatedContributionEnabled"] is False


def test_complete_automated_ffpc_score_can_enter_same_cohort(monkeypatch):
    from src.sharp import score as sharp_score

    record = sharp_score.ManagerRecord(
        user_id="ffpc:site-user-42",
        completed_seasons=2,
        observed_leagues=2,
        dynasty_leagues=2,
        completed_games=28,
        wins=18,
        losses=10,
    )
    monkeypatch.setattr(
        market.platform_records,
        "build_manager_records",
        lambda **kwargs: ([record], {}),
    )
    monkeypatch.setattr(
        market.sharp_score,
        "score_managers",
        lambda records: [
            sharp_score.ManagerScore(
                user_id="ffpc:site-user-42",
                evaluable=True,
                score=88.0,
                qualified=True,
                methodology_version="sharp-v2",
            )
        ],
    )
    selected, _coverage = market.cohort_members(
        qualification="automated", ffpc_config={"enabled": True}
    )
    assert selected[0].platform == "ffpc"
    assert selected[0].qualification_method == "automated_qualified"
    assert selected[0].quality == 0.88


def test_disabling_ffpc_excludes_automated_and_curated_ffpc_members(monkeypatch):
    from src.sharp import score as sharp_score

    record = sharp_score.ManagerRecord(user_id="ffpc:site-user-42")
    monkeypatch.setattr(
        market.platform_records,
        "build_manager_records",
        lambda **kwargs: ([record], {}),
    )
    monkeypatch.setattr(
        market.sharp_score,
        "score_managers",
        lambda records: [
            sharp_score.ManagerScore(
                user_id="ffpc:site-user-42",
                evaluable=True,
                score=88.0,
                qualified=True,
                methodology_version="sharp-v2",
            )
        ],
    )
    config = {
        "enabled": False,
        "allowCuratedInCombinedSignals": True,
        "curatedManagers": [
            {
                "managerKey": "ffpc:site-user-42",
                "verified": True,
                "allowedToContribute": True,
                "weight": 0.8,
            }
        ],
    }
    # Isolate from the real curated store. Without this the test reads the
    # production ledger, so an operational action — verifying one industry
    # sharp's identity through the review queue — flips a unit test. It did:
    # a Sleeper-platform curated member appeared and the blanket `== []`
    # assertion failed even though the FFPC behaviour under test was correct.
    monkeypatch.setattr(market.curated_model, "curated_cohort_members", lambda **_kwargs: [])

    selected, coverage = market.cohort_members(qualification="all", ffpc_config=config)
    # The claim in the test's name is about FFPC, so assert exactly that. A
    # blanket "nobody at all" also passes when the FFPC filter is broken and
    # some unrelated population happens to be empty.
    assert [member for member in selected if member.platform == "ffpc"] == []
    assert selected == []
    assert coverage["curatedContributionEnabled"] is False


def test_audit_payload_preserves_source_trace(tmp_path, monkeypatch):
    path = tmp_path / "ledger.sqlite3"
    platform_ledger.ingest_batch(batch("sleeper", "u1", "L1", "T1", "M1"), path=path)
    monkeypatch.setattr(market, "cohort_members", lambda **kwargs: members())
    payload = market.audit_payload("P1", window="30d", now_ms=NOW, ledger_path=path)
    movement = payload["movements"][0]
    assert movement["platform"] == "sleeper"
    assert movement["league"] == "sleeper:L1"
    assert movement["transaction"] == "sleeper:T1"
    assert movement["manager"] == "sleeper:u1"
    assert movement["direction"] == "add"
    assert movement["qualificationMethod"] == "automated_qualified"
