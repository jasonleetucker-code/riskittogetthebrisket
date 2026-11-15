"""AL-P4 — the point-in-time pick-forecast / team-strength snapshot.

Pins: round-trip through the append-only store; missing inputs recorded as
``None`` WITH a reason (never zero, never silently absent); tiered, append-only
idempotency per capture window (a transient core failure is refused, a better
tier supersedes without overwriting, an unsettled capture cannot hold the
window); a failed ``/traded_picks`` fetch recording NO ownership (not the
overlay's default-ownership fallback); a stale contract never pricing roster
quality; and that a capture run changes nothing served.
"""

from __future__ import annotations

import ast
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.ros import pick_forecast_snapshot as snap

LEAGUE = "dynasty_main"
SLEEPER_ID = "1312006700437352448"
NFL_STATE = {"season": "2026", "season_type": "regular", "week": 5, "display_week": 5}


def _strength_row(rid: int, owner: str, strength: float, *, injured: bool = False) -> dict:
    return {
        "ownerId": owner,
        "rosterId": rid,
        "teamName": f"Team {rid}",
        "teamRosStrength": strength,
        "startingLineupScore": strength,
        "benchDepthScore": 10.0 + rid,
        "positionalCoverageScore": 1.0,
        "healthAvailabilityScore": 0.9,
        "startingLineup": [],
        "benchDepth": [],
        "fullRoster": [
            {
                "playerId": f"p{rid}",
                "canonicalName": f"Player {rid}",
                "position": "WR",
                "rosValue": 50.0,
                "fantasyPositions": ["WR"],
                "injured": injured,
                "bye": False,
            }
        ],
        "unfilledSlots": [],
        "unmappedPlayerCount": 0,
    }


def _pick_detail(season: int, rnd: int, origin: int, owner: int) -> dict:
    return {
        "season": str(season),
        "round": rnd,
        "slot": None,
        "original_roster_id": origin,
        "owner_roster_id": owner,
        "label": f"{season} {rnd}",
        "assetId": f"pick:{LEAGUE}:{season}:r{rnd}:o{origin}",
    }


def _full_inputs(**overrides) -> snap.SnapshotInputs:
    overlay = [
        {
            "roster_id": 1,
            "ownerId": "u1",
            "name": "A",
            "pickDetails": [_pick_detail(2027, 1, 1, 1)],
        },
        {
            "roster_id": 2,
            "ownerId": "u2",
            "name": "B",
            "pickDetails": [_pick_detail(2027, 1, 2, 2), _pick_detail(2027, 2, 1, 2)],
        },
    ]
    strength = [_strength_row(1, "u1", 40.0, injured=True), _strength_row(2, "u2", 60.0)]
    from src.ros.pick_projection import build_pick_projections

    base = dict(
        league_key=LEAGUE,
        nfl_state=NFL_STATE,
        rosters=[{"roster_id": 1, "owner_id": "u1"}, {"roster_id": 2, "owner_id": "u2"}],
        team_names={"u1": "Alpha", "u2": "Beta"},
        league={"settings": {"playoff_teams": 6, "draft_rounds": 6, "num_teams": 2}},
        drafts=[{"draft_id": "d1", "season": "2027", "type": "auction", "settings": {}}],
        scoring_fingerprint="abc123",
        playoff_structure={
            "playoffTeams": 6,
            "byeTeams": 2,
            "playoffWeekStart": 15,
            "source": "league_settings",
            "reason": "",
        },
        strength_rows=strength,
        strength_source="persisted_snapshot",
        standings=[
            {
                "ownerId": "u1",
                "rosterId": 1,
                "wins": 3,
                "losses": 1,
                "ties": 0,
                "games": 4,
                "winPct": 0.75,
                "pointsFor": 480.0,
                "pointsAgainst": 400.0,
                "standing": 1,
                "sleeperRank": None,
            },
            {
                "ownerId": "u2",
                "rosterId": 2,
                "wins": 1,
                "losses": 3,
                "ties": 0,
                "games": 4,
                "winPct": 0.25,
                "pointsFor": 420.0,
                "pointsAgainst": 470.0,
                "standing": 2,
                "sleeperRank": None,
            },
        ],
        luck_rows=[
            {"ownerId": "u1", "gamesPlayed": 4, "allPlayWinPct": 0.7, "expectedWins": 2.8},
            {"ownerId": "u2", "gamesPlayed": 4, "allPlayWinPct": 0.3, "expectedWins": 1.2},
        ],
        remaining_schedule=[(6, "u1", "u2"), (7, "u2", "u1")],
        roster_intel={
            "teams": {
                "u1": {"strength": {"total": 30000}, "agePortfolio": {"meanAge": 25.1}},
                "u2": {"strength": {"total": 28000}, "agePortfolio": {"meanAge": 27.4}},
            }
        },
        overlay_teams=overlay,
        capture_settled=True,
        capture_settled_reason=None,
        last_final_week=4,
        provenance={"payloadSha256": "f" * 64},
    )
    # The season simulation under the canonical draft-order rule: roster 1
    # (owner u1) finishes worst in most simulated seasons.
    season_sim = {
        "season": 2026,
        "draftOrderRule": "reverse_record_lower_pf",
        "regularSeasonProgress": {"weeksFinal": 4, "weeksTotal": 14},
        "playoffOdds": [
            {"ownerId": "u1", "draftSlotDistribution": [0.8, 0.2]},
            {"ownerId": "u2", "draftSlotDistribution": [0.2, 0.8]},
        ],
    }
    base["forecast"] = build_pick_projections(overlay, season_sim, current_season=2026)
    base.update(overrides)
    return snap.SnapshotInputs(**base)


# ── round trip ───────────────────────────────────────────────────────


def test_snapshot_round_trips_through_the_store(tmp_path: Path) -> None:
    record = snap.assemble_snapshot(_full_inputs(), recorded_at="2026-10-06T12:20:00+00:00")
    assert snap.record_snapshot(record, tmp_path) is True

    stored = list(snap.iter_snapshots(tmp_path))
    assert stored == [json.loads(json.dumps(record, default=str))]
    assert (tmp_path / "ledger-2026-10.jsonl").exists()
    assert record["key"] in snap.recorded_keys(tmp_path)


def test_full_record_carries_every_owner_field_with_no_missing_reasons() -> None:
    record = snap.assemble_snapshot(_full_inputs())
    assert record["schema"] == snap.SCHEMA
    assert (record["season"], record["seasonType"], record["week"]) == ("2026", "regular", 5)
    for team in record["teams"]:
        for name in snap.TEAM_FIELDS:
            assert team[name] is not None, name
        assert team["missing"] == {}
    team1 = record["teams"][0]
    assert team1["rosStrength"]["teamRosStrength"] == 40.0
    assert "fullRoster" not in team1["rosStrength"]
    assert team1["depth"]["benchDepthScore"] == 11.0
    assert [p["playerId"] for p in team1["injuries"]["injuredPlayers"]] == ["p1"]
    assert team1["record"]["wins"] == 3
    assert team1["points"]["pointsPerGame"] == 120.0
    assert team1["allPlay"]["allPlayWinPct"] == 0.7
    assert team1["remainingSchedule"] == [
        {"week": 6, "opponent": "u2"},
        {"week": 7, "opponent": "u2"},
    ]
    assert team1["rosterQuality"] == {"total": 30000}
    assert team1["age"] == {"meanAge": 25.1}
    # Owner 2 holds roster 1's 2027 2nd: ownership is STATE, identity is origin.
    assert record["teams"][1]["ownedPicks"] == [
        f"pick:{LEAGUE}:2027:r1:o2",
        f"pick:{LEAGUE}:2027:r2:o1",
    ]
    # dynasty_main has a recorded draft-order rule (canonical owner since
    # 2026-10-04), so nothing at league level is missing.
    assert record["rules"]["draftOrderRule"] == "reverse_record_lower_pf"
    assert set(record["missing"]) == set()


def test_forecast_carries_model_identity_and_canonical_pick_ids() -> None:
    record = snap.assemble_snapshot(_full_inputs())
    forecast = record["forecast"]
    model = forecast["model"]
    assert model["module"] == "src.ros.pick_projection"
    assert model["modelVersion"] == "pick_projector_v2_draft_order_rule"
    assert len(model["codeSha256"]) == 64
    assert model["orderRuleOwner"] == "src.public_league.draft_order"
    assert model["slotInput"] == "season_simulation"
    ids = {p["assetId"] for p in forecast["picks"]}
    assert ids == {
        f"pick:{LEAGUE}:2027:r1:o1",
        f"pick:{LEAGUE}:2027:r1:o2",
        f"pick:{LEAGUE}:2027:r2:o1",
    }
    # Roster 1 finishes worst under the rule in most simulations -> slot 1,
    # and the capture keeps the slot distribution it was forecast from.
    slot = {p["assetId"]: p["projectedSlot"] for p in forecast["picks"]}
    assert slot[f"pick:{LEAGUE}:2027:r1:o1"] == 1
    dist = {p["assetId"]: p["slotDistribution"] for p in forecast["picks"]}
    assert dist[f"pick:{LEAGUE}:2027:r1:o1"] == [0.8, 0.2]
    assert forecast["meta"]["regularSeasonProgress"] == {"weeksFinal": 4, "weeksTotal": 14}


# ── missing is never zero ────────────────────────────────────────────


def test_missing_inputs_are_null_with_a_reason_never_zero() -> None:
    inputs = _full_inputs(
        strength_rows=None,
        strength_reason="team_strength_unavailable_every_tier_declined",
        standings=None,
        standings_reason="standings_failed:boom",
        luck_rows=[],
        remaining_schedule=[],
        roster_intel=None,
        roster_intel_reason="canonical_contract_is_for_league:dynasty_new",
        overlay_teams=None,
        overlay_reason="traded_picks_fetch_failed_ownership_unproven",
        forecast=None,
        forecast_reason="pick_ownership_unproven:traded_picks_fetch_failed_ownership_unproven",
        league=None,
        league_reason="league_has_no_current_season",
        drafts=None,
        drafts_reason="league_has_no_current_season",
        scoring_fingerprint=None,
        scoring_fingerprint_reason="league_has_no_current_season",
        playoff_structure=None,
        playoff_structure_reason="league_has_no_current_season",
    )
    record = snap.assemble_snapshot(inputs)

    assert record["pickOwnership"] is None
    assert record["missing"]["pickOwnership"] == "traded_picks_fetch_failed_ownership_unproven"
    assert record["forecast"] is None and record["missing"]["forecast"].startswith(
        "pick_ownership_unproven"
    )
    for name in ("leagueSettings", "drafts", "scoringConfigFingerprint", "playoffStructure"):
        assert record["rules"][name] is None
        assert record["missing"][name]

    for team in record["teams"]:
        for name in snap.TEAM_FIELDS:
            assert team[name] is None, (name, team[name])
            assert team["missing"][name], name
        assert team["missing"]["rosStrength"] == "team_strength_unavailable_every_tier_declined"
        assert team["missing"]["allPlay"] == "no_scored_regular_season_weeks_this_season"
        assert team["missing"]["remainingSchedule"] == "no_posted_future_regular_season_matchups"
        assert team["missing"]["rosterQuality"] == "canonical_contract_is_for_league:dynasty_new"


def test_a_preseason_team_has_no_points_per_game_rather_than_zero() -> None:
    standings = [
        dict(r, wins=0, losses=0, games=0, winPct=0.0, pointsFor=0.0, pointsAgainst=0.0)
        for r in _full_inputs().standings
    ]
    record = snap.assemble_snapshot(_full_inputs(standings=standings))
    points = record["teams"][0]["points"]
    assert points["pointsPerGame"] is None
    assert points["pointsPerGameMissingReason"] == "no_games_played"


def test_partially_identifiable_pick_ownership_is_not_recorded_as_ownership() -> None:
    bad = _pick_detail(2027, 1, 1, 1)
    bad["assetId"] = f"pick:{LEAGUE}:2027:r1:o9"  # disagrees with its own birth facts
    overlay = [{"roster_id": 1, "pickDetails": [bad, _pick_detail(2027, 2, 1, 1)]}]
    record = snap.assemble_snapshot(_full_inputs(overlay_teams=overlay))
    assert record["pickOwnership"] is None
    assert record["missing"]["pickOwnership"] == "unidentifiable_pick_details:1"
    assert record["forecast"] is None
    assert record["missing"]["forecast"].startswith("pick_ownership_unproven:")


def test_a_null_without_a_reason_is_refused_before_any_write(tmp_path: Path) -> None:
    record = snap.assemble_snapshot(_full_inputs())
    record["teams"][0]["allPlay"] = None
    with pytest.raises(ValueError, match="allPlay"):
        snap.record_snapshot(record, tmp_path)
    assert not list(tmp_path.iterdir())


# ── identity and idempotency ─────────────────────────────────────────


def test_an_equal_tier_rerun_is_a_no_op_per_league_and_window(tmp_path: Path) -> None:
    first = snap.assemble_snapshot(_full_inputs(), recorded_at="2026-10-06T12:20:00+00:00")
    assert first["tier"] == snap.TOP_TIER
    assert snap.record_snapshot(first, tmp_path) is True
    # Same window, same tier, different content (a catch-up later that week): a no-op.
    later = snap.assemble_snapshot(
        _full_inputs(strength_source="live_compute"), recorded_at="2026-10-08T09:00:00+00:00"
    )
    assert later["key"] == first["key"]
    assert snap.record_snapshot(later, tmp_path) is False
    # The next NFL week is a new record.
    nxt = snap.assemble_snapshot(
        _full_inputs(nfl_state={**NFL_STATE, "week": 6}),
        recorded_at="2026-10-13T12:20:00+00:00",
    )
    assert snap.record_snapshot(nxt, tmp_path) is True
    # Another league in the same week is a new record too.
    other = snap.assemble_snapshot(_full_inputs(league_key="dynasty_new"))
    assert snap.record_snapshot(other, tmp_path) is True

    stored = list(snap.iter_snapshots(tmp_path))
    assert [(r["leagueKey"], r["week"], r["captureWindow"]) for r in stored] == [
        (LEAGUE, 5, "nfl-week:5"),
        (LEAGUE, 6, "nfl-week:6"),
        ("dynasty_new", 5, "nfl-week:5"),
    ]
    assert stored[0]["teamStrengthSource"] == "persisted_snapshot"
    assert all(r["supersedes"] is None for r in stored)


def test_season_type_is_part_of_the_week_identity() -> None:
    reg = snap.snapshot_key(LEAGUE, "2026", "regular", 1, snap.TOP_TIER)
    pre = snap.snapshot_key(LEAGUE, "2026", "pre", 1, snap.TOP_TIER)
    assert reg != pre


def test_the_tier_is_part_of_the_key_and_unknown_tiers_are_refused() -> None:
    keys = {snap.snapshot_key(LEAGUE, "2026", "regular", 5, t) for t in snap.TIERS}
    assert len(keys) == len(snap.TIERS)
    with pytest.raises(ValueError):
        snap.snapshot_key(LEAGUE, "2026", "regular", 5, "settled/perfect")


# ── one degraded run must not lose the week ──────────────────────────


def _transient_inputs(**extra) -> snap.SnapshotInputs:
    """What a Sleeper timeout looks like by the time it reaches assembly."""
    reason = "public_snapshot_failed:ReadTimeout:timed out"
    return _full_inputs(
        rosters=None,
        rosters_reason=reason,
        standings=None,
        standings_reason=reason,
        overlay_teams=None,
        overlay_reason="traded_picks_fetch_failed_ownership_unproven",
        forecast=None,
        forecast_reason="pick_ownership_unproven:traded_picks_fetch_failed_ownership_unproven",
        capture_settled=None,
        capture_settled_reason=reason,
        **extra,
    )


def test_a_transient_core_failure_is_refused_and_writes_nothing(tmp_path: Path) -> None:
    record = snap.assemble_snapshot(_transient_inputs())
    assert set(snap.transient_core_misses(record)) == {"teams", "pickOwnership", "forecast"}
    with pytest.raises(snap.TransientCaptureRefused) as err:
        snap.record_snapshot(record, tmp_path)
    assert "pickOwnership" in err.value.misses
    assert not tmp_path.exists() or not list(tmp_path.iterdir())


def test_the_recorder_exits_non_zero_on_a_transient_failure_and_writes_nothing(
    tmp_path: Path, monkeypatch
) -> None:
    import scripts.snapshot_pick_forecast as cli

    monkeypatch.setattr("src.public_league.sleeper_client.fetch_nfl_state", lambda: dict(NFL_STATE))
    monkeypatch.setattr("src.api.league_registry.get_league_by_key", lambda key: CFG)
    monkeypatch.setattr(snap, "gather_inputs", lambda *a, **k: _transient_inputs())
    store = tmp_path / "store"
    rc = cli.main(["record", "--league", LEAGUE, "--dir", str(store), "--no-contract"])
    assert rc == cli.EXIT_TRANSIENT != 0
    assert not store.exists() or not list(store.iterdir())


def test_an_unreadable_nfl_state_exits_transient(tmp_path: Path, monkeypatch) -> None:
    import scripts.snapshot_pick_forecast as cli

    monkeypatch.setattr("src.public_league.sleeper_client.fetch_nfl_state", lambda: None)
    assert cli.main(["record", "--dir", str(tmp_path), "--no-contract"]) == cli.EXIT_TRANSIENT


def test_a_structural_core_null_is_written_as_degraded_not_refused(tmp_path: Path) -> None:
    # The overlay fold's known defect (separately owned): unidentifiable pick
    # details. Fail-closed detection stays; a retry would answer the same.
    bad = _pick_detail(2027, 1, 1, 1)
    bad["assetId"] = f"pick:{LEAGUE}:2027:r1:o9"
    record = snap.assemble_snapshot(
        _full_inputs(overlay_teams=[{"roster_id": 1, "pickDetails": [bad]}])
    )
    assert snap.transient_core_misses(record) == {}
    assert record["completeness"] == "degraded" and record["tier"] == "settled/degraded"
    assert snap.record_snapshot(record, tmp_path) is True


def test_a_complete_record_supersedes_a_degraded_one_and_history_is_kept(
    tmp_path: Path,
) -> None:
    bad = _pick_detail(2027, 1, 1, 1)
    bad["assetId"] = f"pick:{LEAGUE}:2027:r1:o9"
    degraded = snap.assemble_snapshot(
        _full_inputs(overlay_teams=[{"roster_id": 1, "pickDetails": [bad]}]),
        recorded_at="2026-10-06T12:20:00+00:00",
    )
    assert snap.record_snapshot(degraded, tmp_path) is True
    complete = snap.assemble_snapshot(_full_inputs(), recorded_at="2026-10-07T12:20:00+00:00")
    assert complete["key"] != degraded["key"]
    assert snap.record_snapshot(complete, tmp_path) is True
    # A later degraded capture of the same window cannot displace it.
    again = snap.assemble_snapshot(
        _full_inputs(overlay_teams=[{"roster_id": 1, "pickDetails": [bad]}]),
        recorded_at="2026-10-08T12:20:00+00:00",
    )
    assert snap.record_snapshot(again, tmp_path) is False

    history = list(snap.iter_snapshots(tmp_path))
    assert [r["tier"] for r in history] == ["settled/degraded", "settled/complete"]
    assert history[1]["supersedes"] == degraded["key"]
    assert history[1]["supersedesTier"] == "settled/degraded"
    current = snap.current_snapshots(tmp_path)
    assert [(r["key"], r["tier"]) for r in current] == [(complete["key"], snap.TOP_TIER)]


def test_a_partial_record_is_superseded_by_a_complete_one(tmp_path: Path) -> None:
    partial = snap.assemble_snapshot(
        _full_inputs(luck_rows=None, luck_reason="all_play_failed:ConnectionError:reset")
    )
    assert partial["completeness"] == "partial"
    assert partial["transientMissing"]["teams[1].allPlay"].startswith("all_play_failed")
    assert snap.record_snapshot(partial, tmp_path) is True
    assert snap.record_snapshot(snap.assemble_snapshot(_full_inputs()), tmp_path) is True
    assert snap.current_snapshots(tmp_path)[0]["tier"] == snap.TOP_TIER


def test_an_unsettled_capture_is_superseded_by_a_settled_one(tmp_path: Path) -> None:
    # Monday before Monday Night Football: an operator run.
    monday = snap.assemble_snapshot(
        _full_inputs(
            capture_settled=False,
            capture_settled_reason="weeks_in_progress:[5]",
            in_progress_weeks=[5],
        ),
        recorded_at="2026-10-05T20:00:00+00:00",
    )
    assert monday["captureSettled"] is False and monday["tier"] == "unsettled/complete"
    assert monday["captureSettledReason"] == "weeks_in_progress:[5]"
    assert snap.record_snapshot(monday, tmp_path) is True
    tuesday = snap.assemble_snapshot(_full_inputs(), recorded_at="2026-10-06T12:20:00+00:00")
    assert snap.record_snapshot(tuesday, tmp_path) is True
    # And the other order: a settled window cannot be taken by an unsettled run.
    assert snap.record_snapshot(monday, tmp_path) is False

    history = list(snap.iter_snapshots(tmp_path))
    assert [r["captureSettled"] for r in history] == [False, True]
    assert history[1]["supersedes"] == monday["key"]
    assert snap.current_snapshots(tmp_path)[0]["key"] == tuesday["key"]


def test_the_recorder_skips_a_window_already_held_at_the_top_tier(
    tmp_path: Path, monkeypatch
) -> None:
    import scripts.snapshot_pick_forecast as cli

    monkeypatch.setattr("src.public_league.sleeper_client.fetch_nfl_state", lambda: dict(NFL_STATE))
    monkeypatch.setattr("src.api.league_registry.get_league_by_key", lambda key: CFG)
    calls: list = []

    def _gather(*_a, **_k):
        calls.append(1)
        return _full_inputs()

    monkeypatch.setattr(snap, "gather_inputs", _gather)
    args = ["record", "--league", LEAGUE, "--dir", str(tmp_path), "--no-contract"]
    assert cli.main(args) == cli.EXIT_OK
    assert cli.main(args) == cli.EXIT_OK
    assert len(calls) == 1, "a window held at settled/complete is not re-gathered"
    assert len(list(snap.iter_snapshots(tmp_path))) == 1


def test_offseason_captures_are_keyed_by_iso_week_not_a_frozen_nfl_week() -> None:
    off = {"season": "2026", "season_type": "off", "week": 0}
    a = snap.assemble_snapshot(_full_inputs(nfl_state=off), recorded_at="2026-03-03T12:20:00+00:00")
    b = snap.assemble_snapshot(_full_inputs(nfl_state=off), recorded_at="2026-03-05T12:20:00+00:00")
    c = snap.assemble_snapshot(_full_inputs(nfl_state=off), recorded_at="2026-03-10T12:20:00+00:00")
    assert a["captureWindow"] == b["captureWindow"] == "iso-week:2026-W10"
    assert a["key"] == b["key"]
    assert c["captureWindow"] == "iso-week:2026-W11" and c["key"] != a["key"]
    assert a["nflState"] == off  # the host's own state is still recorded verbatim


@pytest.mark.parametrize(
    "state",
    [
        None,
        {},
        {"season": "2026", "week": 5},
        {"season": "2026", "season_type": "regular"},
        {"season": "2026", "season_type": "regular", "week": "x"},
        {"season": "2026", "season_type": "regular", "week": -1},
    ],
)
def test_an_unreadable_nfl_state_is_refused_never_guessed(state) -> None:
    assert snap.week_identity(state) is None
    with pytest.raises(ValueError):
        snap.assemble_snapshot(_full_inputs(nfl_state=state or {}))


def test_the_store_refuses_the_force_added_ros_tree() -> None:
    with pytest.raises(snap.StorePathRefused):
        snap.check_store_path(snap.REPO_ROOT / "data" / "ros" / "pick_forecast")
    with pytest.raises(snap.StorePathRefused):
        snap.check_store_path(snap.REPO_ROOT / "data" / "ros")
    assert snap.check_store_path(snap.DEFAULT_DIR) == snap.DEFAULT_DIR.resolve()


def test_default_store_is_gitignored_and_not_force_added() -> None:
    import subprocess

    probe = snap.DEFAULT_DIR / "ledger-2026-10.jsonl"
    out = subprocess.run(["git", "check-ignore", "-q", str(probe)], cwd=snap.REPO_ROOT, check=False)
    assert out.returncode == 0, "data/pick_forecast_snapshots/ must be gitignored"
    workflow = (snap.REPO_ROOT / ".github" / "workflows" / "scheduled-refresh.yml").read_text(
        encoding="utf-8"
    )
    assert "pick_forecast_snapshots" not in workflow


# ── gathering: real overlay fold, observed /traded_picks ─────────────


def _patch_owners(monkeypatch, strength_calls: list) -> None:
    def _no_snapshot(*_a, **_k):
        raise RuntimeError("offline")

    def _strength(league_key, *, snapshot=None, persist=True):
        strength_calls.append({"league_key": league_key, "persist": persist})
        return [_strength_row(1, "u1", 40.0), _strength_row(2, "u2", 60.0)]

    monkeypatch.setattr("src.public_league.snapshot.build_public_snapshot", _no_snapshot)
    monkeypatch.setattr("src.ros.team_strength.load_or_compute_team_strength", _strength)
    monkeypatch.setattr("src.ros.team_strength.persisted_fast_path_rows", lambda _key: None)
    monkeypatch.setattr(
        "src.api.draft_class_evidence.active_seasons_for_league",
        lambda _lid, seasons: list(seasons),
    )
    # The season simulation under the league's rule, pinned (never the
    # checkout's cache file, whose freshness is its mtime).
    monkeypatch.setattr(
        "src.ros.playoff_sim._load_cached_payload",
        lambda key=None: {
            "season": datetime.now(timezone.utc).year,
            "draftOrderRule": "reverse_record_lower_pf",
            "regularSeasonProgress": {"weeksFinal": 4, "weeksTotal": 14},
            "playoffOdds": [
                {"ownerId": "u1", "draftSlotDistribution": [0.9, 0.1]},
                {"ownerId": "u2", "draftSlotDistribution": [0.1, 0.9]},
            ],
        },
    )


def _fake_sleeper(traded_picks):
    def get(url: str):
        if url.endswith("/rosters"):
            return [
                {"roster_id": 1, "owner_id": "u1", "players": [], "settings": {}},
                {"roster_id": 2, "owner_id": "u2", "players": [], "settings": {}},
            ]
        if url.endswith("/users"):
            return [{"user_id": "u1", "display_name": "a"}, {"user_id": "u2", "display_name": "b"}]
        if url.endswith("/traded_picks"):
            return traded_picks
        if url.rstrip("/").endswith(SLEEPER_ID):
            return {"settings": {"waiver_budget": 100}}
        return None

    return get


CFG = SimpleNamespace(key=LEAGUE, sleeper_league_id=SLEEPER_ID)


def test_a_failed_traded_picks_fetch_records_no_ownership(monkeypatch) -> None:
    calls: list = []
    _patch_owners(monkeypatch, calls)
    inputs = snap.gather_inputs(
        CFG,
        NFL_STATE,
        contract=None,
        contract_reason="contract_build_skipped",
        http_get=_fake_sleeper(None),
    )
    assert inputs.overlay_teams is None
    assert inputs.overlay_reason == "traded_picks_fetch_failed_ownership_unproven"
    assert inputs.forecast is None
    record = snap.assemble_snapshot(inputs)
    assert record["pickOwnership"] is None
    assert record["forecast"] is None
    assert record["missing"]["pickOwnership"] == "traded_picks_fetch_failed_ownership_unproven"
    # The public snapshot failed: its fields are null with that reason.
    assert record["missing"]["teams"].startswith("public_snapshot_failed:")


def test_a_successful_fold_records_canonical_ownership_and_the_served_forecast(
    monkeypatch,
) -> None:
    calls: list = []
    _patch_owners(monkeypatch, calls)
    season = datetime.now(timezone.utc).year + 1
    traded = [{"season": str(season), "round": 1, "roster_id": 1, "owner_id": 2}]
    inputs = snap.gather_inputs(
        CFG,
        NFL_STATE,
        contract=None,
        contract_reason="contract_build_skipped",
        http_get=_fake_sleeper(traded),
    )
    assert inputs.overlay_teams is not None
    record = snap.assemble_snapshot(inputs)
    owners = {p["assetId"]: p["ownerRosterId"] for p in record["pickOwnership"]}
    assert owners[f"pick:{LEAGUE}:{season}:r1:o1"] == 2
    assert record["forecast"]["model"]["function"] == "build_pick_projections"
    assert record["forecast"]["picks"], "future picks should project"
    # Roster quality / age need the contract; skipped here, and SAID so.
    assert inputs.roster_intel is None
    assert inputs.roster_intel_reason == "contract_build_skipped"


# ── nothing served changes ───────────────────────────────────────────


def test_team_strength_is_read_without_persisting(monkeypatch) -> None:
    calls: list = []
    _patch_owners(monkeypatch, calls)
    snap.gather_inputs(
        CFG, NFL_STATE, contract=None, contract_reason="x", http_get=_fake_sleeper([])
    )
    assert calls == [{"league_key": LEAGUE, "persist": False}]


def test_a_foreign_league_contract_is_never_used_for_roster_quality(
    monkeypatch, registry_ids
) -> None:
    calls: list = []
    _patch_owners(monkeypatch, calls)
    contract = {"sleeper": {"leagueId": "1320092771247222784"}}
    inputs = snap.gather_inputs(
        CFG, NFL_STATE, contract=contract, contract_reason=None, http_get=_fake_sleeper([])
    )
    assert inputs.roster_intel is None
    assert inputs.roster_intel_reason == "canonical_contract_is_for_league:dynasty_new"


@pytest.fixture
def registry_ids(monkeypatch):
    """The suite's registry is deliberately empty (tests/conftest.py); map the two ids."""
    ids = {SLEEPER_ID: LEAGUE, "1320092771247222784": "dynasty_new"}
    monkeypatch.setattr(
        "src.api.league_registry.league_key_for_sleeper_id", lambda sid: ids.get(str(sid))
    )


def test_the_contract_league_is_decided_by_its_rosters_not_a_label(registry_ids) -> None:
    # build_api_data_contract stamps no meta.leagueKey; a label alone proves nothing.
    assert snap.contract_league_key({"meta": {"leagueKey": LEAGUE}}) is None
    assert snap.contract_league_key({"sleeper": {"leagueId": SLEEPER_ID}}) == LEAGUE
    # A label that disagrees with the rosters is a chimera.
    chimera = {"meta": {"leagueKey": "dynasty_new"}, "sleeper": {"leagueId": SLEEPER_ID}}
    assert snap.contract_league_key(chimera) is None
    assert snap.contract_league_key({"sleeper": {"leagueId": "999"}}) is None
    assert snap.contract_league_key(None) is None


_SERVED_WRITERS = {
    "write_team_strength_snapshot",
    "record_snapshot_power",
    "write_scoring_snapshot",
    "_persist_best_effort",
}


def test_the_module_calls_no_served_writer() -> None:
    """Structural: capture code never reaches a writer another reader serves."""
    for rel in ("src/ros/pick_forecast_snapshot.py", "scripts/snapshot_pick_forecast.py"):
        tree = ast.parse((snap.REPO_ROOT / rel).read_text(encoding="utf-8"))
        names = {
            n.attr if isinstance(n, ast.Attribute) else n.id
            for n in ast.walk(tree)
            if isinstance(n, (ast.Attribute, ast.Name))
        }
        assert not names & _SERVED_WRITERS, (rel, names & _SERVED_WRITERS)
        text = (snap.REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "power_snapshots.record_snapshot" not in text
        assert "exports/latest" not in text.replace("``exports/latest``", "")


# ── orphan rosters: owner-keyed fields are UNKNOWN, never [] ─────────


def test_an_orphan_roster_has_no_remaining_schedule_rather_than_an_empty_one() -> None:
    rosters = [{"roster_id": 1, "owner_id": "u1"}, {"roster_id": 2, "owner_id": None}]
    record = snap.assemble_snapshot(_full_inputs(rosters=rosters))
    orphan = record["teams"][1]
    assert orphan["ownerId"] is None
    for name in ("remainingSchedule", "allPlay", "rosterQuality", "age"):
        assert orphan[name] is None, name
        assert orphan["missing"][name] == snap.ORPHAN_ROSTER_REASON, name
    # Structural, not a failed read: it does not demote the record.
    assert record["completeness"] == "complete"


def test_an_owner_the_posted_schedule_does_not_place_is_unknown_not_empty() -> None:
    record = snap.assemble_snapshot(_full_inputs(remaining_schedule=[(6, "u1", "u9")]))
    team2 = record["teams"][1]
    assert team2["remainingSchedule"] is None
    assert team2["missing"]["remainingSchedule"] == "owner_absent_from_posted_schedule"


# ── a stale contract never prices roster quality ─────────────────────


@pytest.mark.parametrize(
    ("age", "reason"), [(9.0, "contract_stale"), (None, "contract_age_unknown")]
)
def test_a_stale_or_ageless_board_is_not_built_into_roster_quality(
    tmp_path: Path, monkeypatch, age, reason
) -> None:
    import scripts.snapshot_pick_forecast as cli
    from src.api import data_contract, sparse_evidence_shadow

    payload = tmp_path / "dynasty_data.json"
    payload.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        sparse_evidence_shadow, "newest_live_payload", lambda _root: (payload, {}, age)
    )

    def _boom(_raw):
        raise AssertionError("a stale board was built")

    monkeypatch.setattr(data_contract, "build_api_data_contract", _boom)
    contract, got, provenance = cli._load_contract()
    assert contract is None and got == reason
    # The budget is the existing scrape-cadence rule, not a new number.
    from src.api.league_registry import SCORING_SNAPSHOT_MAX_AGE_HOURS

    assert provenance["staleBudgetHours"] == float(SCORING_SNAPSHOT_MAX_AGE_HOURS)

    # Downstream: both fields are null WITH that reason, and the record is
    # merely partial -- a fresh board later in the window supersedes it.
    record = snap.assemble_snapshot(_full_inputs(roster_intel=None, roster_intel_reason=got))
    for team in record["teams"]:
        assert team["rosterQuality"] is None and team["missing"]["rosterQuality"] == reason
        assert team["age"] is None and team["missing"]["age"] == reason
    assert record["completeness"] == "partial"


def test_a_fresh_board_is_built(tmp_path: Path, monkeypatch) -> None:
    import scripts.snapshot_pick_forecast as cli
    from src.api import data_contract, sparse_evidence_shadow

    payload = tmp_path / "dynasty_data.json"
    payload.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        sparse_evidence_shadow, "newest_live_payload", lambda _root: (payload, {}, 2.0)
    )
    monkeypatch.setattr(data_contract, "build_api_data_contract", lambda raw: {"version": "v"})
    contract, reason, provenance = cli._load_contract()
    assert contract == {"version": "v"} and reason is None
    assert provenance["payloadAgeHours"] == 2.0


# ── gathering against a realistic league ─────────────────────────────

_OWNERS = ["u1", "u2", "u3", "u4"]


def _realistic_snapshot(*, partial_week: bool = False):
    """A four-team league in week 5: weeks 1-4 scored and closed by the host
    clock, weeks 5-14 posted with Sleeper's 0.0 stubs, playoffs from week 15."""
    from src.public_league.identity import build_manager_registry
    from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot

    wins = {1: 3, 2: 2, 3: 2, 4: 1}
    rosters = [
        {
            "roster_id": rid,
            "owner_id": owner,
            "players": [f"p{rid}"],
            "settings": {
                "wins": wins[rid],
                "losses": 4 - wins[rid],
                "ties": 0,
                "fpts": 400 + 10 * rid,
                "fpts_decimal": 50,
                "fpts_against": 420,
                "fpts_against_decimal": 0,
            },
        }
        for rid, owner in enumerate(_OWNERS, start=1)
    ]
    users = [{"user_id": o, "display_name": o.upper()} for o in _OWNERS]
    pairs = {1: 1, 2: 1, 3: 2, 4: 2}

    def _week(wk: int, scored: bool, live_only: tuple[int, ...] = ()) -> list[dict]:
        return [
            {
                "roster_id": rid,
                "matchup_id": pairs[rid],
                "points": (100.0 + rid + wk) if (scored or rid in live_only) else 0.0,
            }
            for rid in pairs
        ]

    matchups = {wk: _week(wk, scored=True) for wk in range(1, 5)}
    for wk in range(5, 15):
        live = (1, 2) if partial_week and wk == 5 else ()
        matchups[wk] = _week(wk, scored=False, live_only=live)
    current = SeasonSnapshot(
        season="2026",
        league_id="L2026",
        league={
            "league_id": "L2026",
            "season": "2026",
            "status": "in_season",
            "total_rosters": 4,
            "settings": {
                "playoff_week_start": 15,
                "playoff_teams": 2,
                "last_scored_leg": 4,
                "num_teams": 4,
            },
            "scoring_settings": {"rec": 1.0, "pass_td": 4.0},
            "roster_positions": ["QB", "RB", "WR", "TE", "FLEX", "BN"],
        },
        users=users,
        rosters=rosters,
        matchups_by_week=matchups,
        transactions_by_week={},
        drafts=[
            {
                "draft_id": "d2027",
                "season": "2027",
                "type": "auction",
                "status": "pre_draft",
                "settings": {"rounds": 6},
                "draft_order": None,
                "slot_to_roster_id": None,
            }
        ],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )
    snapshot = PublicLeagueSnapshot(
        root_league_id="L2026", generated_at="2026-10-06T12:20:00Z", seasons=[current]
    )
    snapshot.managers = build_manager_registry(
        [{"league": current.league, "users": users, "rosters": rosters}]
    )
    return snapshot


def _strength_rows_4() -> list[dict]:
    return [_strength_row(rid, o, 30.0 + 5 * rid) for rid, o in enumerate(_OWNERS, start=1)]


def _fake_sleeper_4(traded_picks):
    def get(url: str):
        if url.endswith("/rosters"):
            return [
                {"roster_id": rid, "owner_id": o, "players": [], "settings": {}}
                for rid, o in enumerate(_OWNERS, start=1)
            ]
        if url.endswith("/users"):
            return [{"user_id": o, "display_name": o} for o in _OWNERS]
        if url.endswith("/traded_picks"):
            return traded_picks
        if url.rstrip("/").endswith(SLEEPER_ID):
            return {"settings": {"waiver_budget": 100}}
        return None

    return get


@pytest.fixture
def realistic(monkeypatch, tmp_path):
    """The real snapshot-side owners over a realistic league; team strength is
    the REAL read path (persist=False), its file tree redirected to tmp."""
    from src.ros import team_strength

    state: dict = {"snapshot": _realistic_snapshot(), "build_kwargs": []}

    def _build(league_id, **kwargs):
        state["build_kwargs"].append(kwargs)
        return state["snapshot"]

    monkeypatch.setattr("src.public_league.snapshot.build_public_snapshot", _build)
    monkeypatch.setattr(team_strength, "ROS_DATA_DIR", tmp_path / "ros")
    monkeypatch.setattr(
        team_strength,
        "compute_team_strength_from_snapshot",
        lambda snapshot, league_key=None: _strength_rows_4(),
    )
    monkeypatch.setattr(team_strength, "_live_compute_cache", {})
    monkeypatch.setattr(
        "src.api.draft_class_evidence.active_seasons_for_league",
        lambda _lid, seasons: list(seasons),
    )
    state["strength_dir"] = tmp_path / "ros" / "team_strength"
    # The league's season simulation is pinned, never read from whatever
    # cache file the checkout happens to carry (its freshness is file mtime).
    state["sim"] = {
        "season": datetime.now(timezone.utc).year,
        "draftOrderRule": "reverse_record_lower_pf",
        "regularSeasonProgress": {"weeksFinal": 4, "weeksTotal": 14},
        "playoffOdds": [
            {"ownerId": o, "draftSlotDistribution": [1.0 if i == j else 0.0 for j in range(4)]}
            for i, o in enumerate(_OWNERS)
        ],
    }
    monkeypatch.setattr("src.ros.playoff_sim._load_cached_payload", lambda key=None: state["sim"])
    return state


def _gather_realistic(traded=None):
    season = datetime.now(timezone.utc).year + 1
    if traded is None:
        traded = [{"season": str(season), "round": 1, "roster_id": 1, "owner_id": 2}]
    return snap.gather_inputs(
        CFG,
        NFL_STATE,
        contract=None,
        contract_reason="contract_build_skipped",
        http_get=_fake_sleeper_4(traded),
    )


def test_gathering_a_realistic_league_fills_every_owner_path(realistic) -> None:
    inputs = _gather_realistic()
    record = snap.assemble_snapshot(inputs, recorded_at="2026-10-06T12:20:00+00:00")

    assert record["tier"] == snap.TOP_TIER, record["transientMissing"]
    assert record["captureSettled"] is True and record["lastFinalWeek"] == 4
    assert record["inProgressWeeks"] == []
    assert [t["rosterId"] for t in record["teams"]] == [1, 2, 3, 4]
    t1 = record["teams"][0]
    # standings (metrics.season_standings over Sleeper roster settings)
    assert t1["record"]["wins"] == 3 and t1["record"]["games"] == 4
    assert t1["points"]["pointsFor"] == 410.5
    # all-play (luck.build_section over the four closed weeks)
    assert t1["allPlay"] is not None and t1["allPlay"]["gamesPlayed"] == 4
    # remaining schedule (playoff_sim.remaining_schedule): weeks 5-14 posted
    assert [g["week"] for g in t1["remainingSchedule"]] == list(range(5, 15))
    assert {g["opponent"] for g in t1["remainingSchedule"]} == {"u2"}
    # team strength: the real read path, the live tier
    assert t1["rosStrength"]["teamRosStrength"] == 35.0
    assert record["teamStrengthSource"] == "live_compute"
    # rules: drafts, playoff structure, scoring fingerprint, verbatim settings
    assert record["rules"]["drafts"][0]["draft_id"] == "d2027"
    assert record["rules"]["playoffStructure"] is not None
    assert len(record["rules"]["scoringConfigFingerprint"]) == 64
    assert record["rules"]["leagueSettings"]["last_scored_leg"] == 4
    # pick ownership and the forecast
    assert record["pickOwnership"] and record["forecast"]["picks"]
    # provenance: the team-strength file is stamped, and absent here
    tsf = record["provenance"]["teamStrengthFile"]
    assert tsf["fastPathFresh"] is False and tsf["mtime"] is None
    assert tsf["missingReason"] == "no_persisted_team_strength_file"
    # No fresh persisted file -> the live tier needs names -> the dump is fetched.
    assert realistic["build_kwargs"] == [{"include_nfl_players": True}]
    assert record["provenance"]["nflPlayerDumpRequested"] is True


def test_a_capture_during_a_part_played_week_is_unsettled(realistic) -> None:
    realistic["snapshot"] = _realistic_snapshot(partial_week=True)
    record = snap.assemble_snapshot(_gather_realistic())
    assert record["captureSettled"] is False
    assert record["inProgressWeeks"] == [5]
    assert record["captureSettledReason"] == "weeks_in_progress:[5]"
    assert record["tier"] == "unsettled/complete"


def test_a_fresh_persisted_team_strength_file_skips_the_player_dump(realistic) -> None:
    from src.ros import team_strength

    team_strength.write_team_strength_snapshot(_strength_rows_4(), league_key=LEAGUE)
    record = snap.assemble_snapshot(_gather_realistic())
    assert realistic["build_kwargs"] == [{"include_nfl_players": False}]
    assert record["teamStrengthSource"] == "persisted_snapshot"
    tsf = record["provenance"]["teamStrengthFile"]
    assert tsf["fastPathFresh"] is True and tsf["mtime"]
    assert tsf["ageHours"] is not None and tsf["ageHours"] < 1


def test_a_half_fetched_current_season_is_a_transient_refusal(realistic, tmp_path) -> None:
    broken = _realistic_snapshot()
    broken.current_season.rosters = []  # sleeper_client answers a failed GET with []
    realistic["snapshot"] = broken
    record = snap.assemble_snapshot(_gather_realistic())
    assert record["missing"]["teams"].startswith("current_season_integrity_failed:")
    with pytest.raises(snap.TransientCaptureRefused):
        snap.record_snapshot(record, tmp_path / "store")
    assert not (tmp_path / "store").exists()


def test_persist_false_writes_no_served_team_strength_file(realistic) -> None:
    """Behavioural, not argument-checking: a capture leaves the served file
    tree untouched, while the same read path with persist=True would write."""
    from src.ros import team_strength

    strength_dir = realistic["strength_dir"]
    _gather_realistic()
    assert not strength_dir.exists() or not list(strength_dir.iterdir())

    # Control: the harness can see a write when one happens.
    team_strength.load_or_compute_team_strength(
        LEAGUE, snapshot=realistic["snapshot"], persist=True
    )
    assert list(strength_dir.iterdir())


def test_a_missing_or_stale_simulation_refuses_the_write_not_a_slotless_forecast(
    realistic,
) -> None:
    """dynasty_main has a recorded rule, so a missing/stale season simulation
    is TRANSIENT: writing a slot-less forecast now would occupy the week's
    top tier and the real capture (the calibration input) would be lost."""
    realistic["sim"] = None
    inputs = _gather_realistic()
    assert inputs.forecast is None
    assert inputs.forecast_reason == "season_simulation_unavailable"
    record = snap.assemble_snapshot(inputs, recorded_at="2026-10-06T12:20:00+00:00")
    assert "forecast" in record["transientMissing"]
    assert record["tier"] != snap.TOP_TIER


def test_the_capture_records_the_rule_slots_it_was_forecast_from(realistic) -> None:
    record = snap.assemble_snapshot(_gather_realistic(), recorded_at="2026-10-06T12:20:00+00:00")
    forecast = record["forecast"]
    assert forecast["meta"]["draftOrderRule"] == "reverse_record_lower_pf"
    slotted = [p for p in forecast["picks"] if p["projectedSlot"] is not None]
    assert slotted and all(p["slotDistribution"] for p in slotted)


def test_a_simulation_that_cannot_be_joined_is_transient_not_a_slotless_capture(
    realistic,
) -> None:
    """A rule league whose fresh simulation cannot be joined to the rosters
    (an ownerId the overlay does not carry) is a simulation gap the next run
    closes — the write is refused, not locked in as a slot-less top tier."""
    sim = copy.deepcopy(realistic["sim"])
    sim["playoffOdds"][0]["ownerId"] = "owner-not-in-the-league"
    realistic["sim"] = sim
    inputs = _gather_realistic()
    assert inputs.forecast is None
    assert inputs.forecast_reason == (
        "season_simulation_unavailable:simulation_owner_join_incomplete"
    )
    record = snap.assemble_snapshot(inputs, recorded_at="2026-10-06T12:20:00+00:00")
    assert "forecast" in record["transientMissing"]
    assert record["tier"] != snap.TOP_TIER


def test_transient_slot_reasons_are_the_projector_constants() -> None:
    from src.ros import pick_projection as pp

    assert snap._TRANSIENT_SLOT_REASONS == {
        pp.SIMULATION_JOIN_INCOMPLETE,
        pp.NO_SLOT_DISTRIBUTION,
    }
