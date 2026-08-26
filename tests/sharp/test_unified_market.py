from src.intel import platform_ledger
from src.platforms.base import (
    NormalizedBatch,
    NormalizedLeague,
    NormalizedManager,
    NormalizedMovement,
    NormalizedTransaction,
)
from src.sharp import cohort, market

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
        cohort.platform_records,
        "build_manager_records",
        lambda **kwargs: ([record], {}),
    )
    monkeypatch.setattr(
        cohort.sharp_score,
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
        cohort.platform_records,
        "build_manager_records",
        lambda **kwargs: ([record], {}),
    )
    monkeypatch.setattr(
        cohort.sharp_score,
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


def test_one_manager_cannot_dominate_an_asset(tmp_path, monkeypatch):
    """The defect: `src/sharp` capped concentration nowhere.

    Consensus Edge has bounded per-manager and per-league share since
    ADR-011. This path did not, so a manager with eight observations
    against two other managers' one each drove the signal almost
    entirely, and `breadth_factor = m/(m+3)` saturated far too fast to
    push back — the board read "three sharps are buying" on what was
    effectively one person's opinion.

    Raw counts stay raw: `volume` describes the record. The capped
    weights are what `strength` is computed from.

    NOTE what a share cap can and cannot do. It bounds one contributor's
    share OF A TOTAL, so with a single contributor there is nothing to
    scale against — a lone manager's share is 100% by construction and
    capping it is meaningless. That case is bounded by `breadth_factor`
    (one manager gives 1/(1+3) = 0.25) and not by this. The cap is for
    concentration among several, which is what this asserts.
    """
    path = tmp_path / "ledger.sqlite3"
    cohort_list = []
    for i in range(8):
        platform_ledger.ingest_batch(batch("sleeper", "u1", f"L{i}", f"T{i}", f"M{i}"), path=path)
    for idx, other in enumerate(("u2", "u3")):
        platform_ledger.ingest_batch(
            batch("sleeper", other, f"LO{idx}", f"TO{idx}", f"MO{idx}"), path=path
        )
    for key in ("u1", "u2", "u3"):
        cohort_list.append(
            market.CohortMember(f"sleeper:{key}", "sleeper", "automated_qualified", 0.9)
        )
    monkeypatch.setattr(
        market,
        "cohort_members",
        lambda **kwargs: (cohort_list, {"automatedQualifiedManagers": 3}),
    )
    payload = market.market_payload(
        window="30d", now_ms=NOW, ledger_path=path, ffpc_config={"enabled": False}
    )
    win = payload["assets"][0]["windows"]["30d"]

    # The record is unchanged: ten movements happened.
    assert win["buys"] == 10
    assert win["volume"] == 10
    assert win["uniqueManagers"] == 3

    # The evidence is bounded: u1 held 80% and is cut toward the 34% cap.
    assert win["concentrationCapped"] is True
    assert win["weightedVolume"] < 10, "one manager still contributes eight observations"
    assert win["weightedVolume"] > 2, "the two independent managers were erased"


def test_a_broad_asset_is_not_capped(tmp_path, monkeypatch):
    # The cap must bind on concentration, not on volume — ten different
    # managers are exactly the evidence the board is for.
    path = tmp_path / "ledger.sqlite3"
    cohort_members_list = []
    for i in range(10):
        platform_ledger.ingest_batch(
            batch("sleeper", f"u{i}", f"L{i}", f"T{i}", f"M{i}"), path=path
        )
        cohort_members_list.append(
            market.CohortMember(f"sleeper:u{i}", "sleeper", "automated_qualified", 0.9)
        )
    monkeypatch.setattr(
        market,
        "cohort_members",
        lambda **kwargs: (cohort_members_list, {"automatedQualifiedManagers": 10}),
    )
    payload = market.market_payload(
        window="30d", now_ms=NOW, ledger_path=path, ffpc_config={"enabled": False}
    )
    win = payload["assets"][0]["windows"]["30d"]
    assert win["uniqueManagers"] == 10
    assert win["concentrationCapped"] is False
    assert win["weightedVolume"] == 10.0


def test_capping_shrinks_a_lean_but_never_flips_it(tmp_path, monkeypatch):
    # Buys and sells scale by the same per-contributor factor, so a cap
    # can reduce confidence in a direction but cannot reverse it.
    path = tmp_path / "ledger.sqlite3"
    for i in range(6):
        platform_ledger.ingest_batch(
            batch("sleeper", "u1", f"L{i}", f"T{i}", f"M{i}", action="add"), path=path
        )
    platform_ledger.ingest_batch(batch("sleeper", "u1", "LX", "TX", "MX", action="drop"), path=path)
    monkeypatch.setattr(market, "cohort_members", lambda **kwargs: members())
    payload = market.market_payload(
        window="30d", now_ms=NOW, ledger_path=path, ffpc_config={"enabled": False}
    )
    win = payload["assets"][0]["windows"]["30d"]
    assert win["net"] > 0
    assert win["weightedNet"] > 0, "the cap reversed the direction of the lean"
    assert win["weightedNet"] <= win["net"]

def test_overlapping_tracker_windows_share_one_ledger_read(tmp_path, monkeypatch):
    """48h/7d/30d remain independent views but share one SQL scan."""
    path = tmp_path / "ledger.sqlite3"
    platform_ledger.ingest_batch(batch("sleeper", "u1", "L1", "T1", "M1"), path=path)
    monkeypatch.setattr(market, "cohort_members", lambda **kwargs: members())

    real_query = platform_ledger.query_movements
    calls = []

    def counted_query(**kwargs):
        calls.append(dict(kwargs))
        return real_query(**kwargs)

    monkeypatch.setattr(market.platform_ledger, "query_movements", counted_query)
    payload = market.market_payload(
        window="7d",
        now_ms=NOW,
        ledger_path=path,
        ffpc_config={"enabled": True, "allowCuratedInCombinedSignals": True},
    )

    assert len(calls) == 1
    assert calls[0]["since_ms"] == NOW - 30 * 24 * 60 * 60 * 1000
    row = payload["assets"][0]
    assert row["windows"]["7d"]["volume"] == 1
    assert row["velocity"] is None
