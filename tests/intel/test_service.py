"""Service orchestration: league-partitioned refresh writes and
partition-scoped reads."""

from __future__ import annotations

import time

from src.intel import service, store
from tests.intel.conftest import (
    DAY_MS,
    FakeSleeper,
    fill_traded_picks,
    leagues_url,
    make_league,
    make_roster,
    make_trade_tx,
    rosters_url,
    state_url,
    tx_url,
)

SEASON = "2026"


def _responses_for(member: str, lid: str, asset: str) -> dict:
    now_ms = int(time.time() * 1000)
    return fill_traded_picks(
        {
            state_url(): {"week": 1, "season_type": "off", "league_season": SEASON},
            leagues_url(member, SEASON): [make_league(lid)],
            rosters_url(lid): [make_roster(1, member, players=[asset])],
            # A TRADE, not a waiver: only trades reach the buy/sell
            # board, so a waiver fixture here would assert an empty
            # board and stop testing partition scoping at all.
            tx_url(lid, 1): [make_trade_tx(f"t-{lid}", now_ms - DAY_MS, adds={asset: 1})],
        }
    )


def test_refresh_writes_only_the_target_leagues_partition(intel_data_dir):
    fake_main = FakeSleeper(_responses_for("A", "LA", "p-main"))
    service.refresh_intel(
        member_ids=["A"],
        season=SEASON,
        league_key="dynasty_main",
        http_get=fake_main,
        sleep_s=0,
    )
    assert store.snapshot_path("dynasty_main").exists()
    assert not store.snapshot_path("dynasty_new").exists()

    fake_new = FakeSleeper(_responses_for("Z", "LZ", "p-new"))
    service.refresh_intel(
        member_ids=["Z"],
        season=SEASON,
        league_key="dynasty_new",
        http_get=fake_new,
        sleep_s=0,
    )

    main_state = store.load_state("dynasty_main")
    new_state = store.load_state("dynasty_new")
    assert set(main_state["members"]) == {"A"}
    assert set(new_state["members"]) == {"Z"}
    assert {e["assetId"] for e in main_state["events"]} == {"p-main"}
    assert {e["assetId"] for e in new_state["events"]} == {"p-new"}

    # Partition-scoped reads see only their own league's data.
    summary_main = service.build_summary_payload("dynasty_main")
    summary_new = service.build_summary_payload("dynasty_new")
    assert {a["assetId"] for a in summary_main["assets"]} == {"p-main"}
    assert {a["assetId"] for a in summary_new["assets"]} == {"p-new"}
    assert summary_main["leagueKey"] == "dynasty_main"

    assert service.snapshot_ready("dynasty_main") is True
    assert service.snapshot_ready("never_refreshed") is False


def _seed_league_responses(member: str, seed_league_id: str, lid: str, asset: str) -> dict:
    """Responses for a seedless (sleeper_league_id-driven) refresh:
    seed-league rosters/users + the member's own league crawl."""
    now_ms = int(time.time() * 1000)
    return fill_traded_picks(
        {
            state_url(): {"week": 1, "season_type": "off", "league_season": SEASON},
            f"https://api.sleeper.app/v1/league/{seed_league_id}/rosters": [make_roster(1, member)],
            f"https://api.sleeper.app/v1/league/{seed_league_id}/users": [
                {"user_id": member, "display_name": f"user-{member}"}
            ],
            leagues_url(member, SEASON): [make_league(lid)],
            rosters_url(lid): [make_roster(1, member, players=[asset])],
            # A TRADE, not a waiver: only trades reach the buy/sell
            # board, so a waiver fixture here would assert an empty
            # board and stop testing partition scoping at all.
            tx_url(lid, 1): [make_trade_tx(f"t-{lid}", now_ms - DAY_MS, adds={asset: 1})],
        }
    )


def test_refresh_many_crawls_every_league_into_its_partition(intel_data_dir):
    # Two active leagues with disjoint pools — one call, both
    # partitions written (this is the cron's leagueKey=all path).
    responses = {}
    responses.update(_seed_league_responses("A", "SEED_MAIN", "LA", "p-main"))
    responses.update(_seed_league_responses("Z", "SEED_NEW", "LZ", "p-new"))
    fake = FakeSleeper(responses)

    summary = service.refresh_intel_many(
        [
            {"leagueKey": "dynasty_main", "sleeperLeagueId": "SEED_MAIN"},
            {"leagueKey": "dynasty_new", "sleeperLeagueId": "SEED_NEW"},
        ],
        season=SEASON,
        http_get=fake,
        sleep_s=0,
    )
    assert summary["mode"] == "all"
    assert summary["leagueKeys"] == ["dynasty_main", "dynasty_new"]
    assert summary["errors"] == []
    assert [lg["leagueKey"] for lg in summary["leagues"]] == ["dynasty_main", "dynasty_new"]

    assert store.snapshot_path("dynasty_main").exists()
    assert store.snapshot_path("dynasty_new").exists()
    assert {e["assetId"] for e in store.load_state("dynasty_main")["events"]} == {"p-main"}
    assert {e["assetId"] for e in store.load_state("dynasty_new")["events"]} == {"p-new"}

    status = service.refresh_status()
    assert status["isRunning"] is False
    assert status["lastError"] is None
    assert status["lastResult"]["mode"] == "all"


def test_refresh_many_isolates_per_league_failures(intel_data_dir):
    # League B's seed rosters are unreachable → its refresh fails,
    # but league A still completes and B's error is surfaced via
    # lastError so the cron's failure handler fires.
    responses = _seed_league_responses("A", "SEED_MAIN", "LA", "p-main")
    fake = FakeSleeper(responses)

    summary = service.refresh_intel_many(
        [
            {"leagueKey": "dynasty_main", "sleeperLeagueId": "SEED_MAIN"},
            {"leagueKey": "dynasty_new", "sleeperLeagueId": "SEED_MISSING"},
        ],
        season=SEASON,
        http_get=fake,
        sleep_s=0,
    )
    assert [lg["leagueKey"] for lg in summary["leagues"]] == ["dynasty_main"]
    assert summary["errors"][0]["leagueKey"] == "dynasty_new"
    assert store.snapshot_path("dynasty_main").exists()
    assert not store.snapshot_path("dynasty_new").exists()
    status = service.refresh_status()
    assert "dynasty_new" in (status["lastError"] or "")


def test_refresh_many_rejected_while_single_refresh_running(intel_data_dir, monkeypatch):
    import threading

    import pytest

    gate = threading.Event()
    entered = threading.Event()

    def slow_refresh(**kwargs):
        entered.set()
        gate.wait(timeout=10)
        return {}

    monkeypatch.setattr(service, "_refresh_locked", slow_refresh)
    t = threading.Thread(target=lambda: service.refresh_intel(member_ids=["A"]), daemon=True)
    t.start()
    assert entered.wait(timeout=5)
    with pytest.raises(service.RefreshAlreadyRunning):
        service.refresh_intel_many([{"leagueKey": "x", "sleeperLeagueId": "1"}])
    gate.set()
    t.join(timeout=5)


def test_refresh_stamps_league_key_in_status_and_result(intel_data_dir):
    fake = FakeSleeper(_responses_for("A", "LA", "p1"))
    result = service.refresh_intel(
        member_ids=["A"],
        season=SEASON,
        league_key="dynasty_main",
        http_get=fake,
        sleep_s=0,
    )
    assert result["leagueKey"] == "dynasty_main"
    status = service.refresh_status("dynasty_main")
    assert status["leagueKey"] == "dynasty_main"
    assert status["snapshotLeagueKey"] == "dynasty_main"
    assert status["snapshotStaleHours"] is not None
