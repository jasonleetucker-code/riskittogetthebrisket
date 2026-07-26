"""Service orchestration: league-partitioned refresh writes and
partition-scoped reads."""

from __future__ import annotations

import time

from src.intel import service, store
from tests.intel.conftest import (
    DAY_MS,
    FakeSleeper,
    leagues_url,
    make_league,
    make_roster,
    make_waiver_tx,
    rosters_url,
    state_url,
    tx_url,
)

SEASON = "2026"


def _responses_for(member: str, lid: str, asset: str) -> dict:
    now_ms = int(time.time() * 1000)
    return {
        state_url(): {"week": 1, "season_type": "off", "league_season": SEASON},
        leagues_url(member, SEASON): [make_league(lid)],
        rosters_url(lid): [make_roster(1, member, players=[asset])],
        tx_url(lid, 1): [make_waiver_tx(f"t-{lid}", now_ms - DAY_MS, 1, add_player=asset)],
    }


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
