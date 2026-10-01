"""AL-P4 — the point-in-time pick-forecast / team-strength snapshot.

Pins: round-trip through the append-only store; missing inputs recorded as
``None`` WITH a reason (never zero, never silently absent); first-write-wins
idempotency per Sleeper NFL week; a failed ``/traded_picks`` fetch recording NO
ownership (not the overlay's default-ownership fallback); and that a capture run
changes nothing served.
"""

from __future__ import annotations

import ast
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
        {"roster_id": 1, "name": "A", "pickDetails": [_pick_detail(2027, 1, 1, 1)]},
        {
            "roster_id": 2,
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
        provenance={"payloadSha256": "f" * 64},
    )
    base["forecast"] = build_pick_projections(overlay, strength, current_season=2026)
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
    # The only league-level "missing" is the unowned draft-order rule.
    assert set(record["missing"]) == {"draftOrderRule"}


def test_forecast_carries_model_identity_and_canonical_pick_ids() -> None:
    record = snap.assemble_snapshot(_full_inputs())
    forecast = record["forecast"]
    model = forecast["model"]
    assert model["module"] == "src.ros.pick_projection"
    assert model["modelVersion"] is None and model["modelVersionMissingReason"]
    assert len(model["codeSha256"]) == 64
    assert model["orderRuleAssumed"] == "reverse_final_standings"
    ids = {p["assetId"] for p in forecast["picks"]}
    assert ids == {
        f"pick:{LEAGUE}:2027:r1:o1",
        f"pick:{LEAGUE}:2027:r1:o2",
        f"pick:{LEAGUE}:2027:r2:o1",
    }
    # Weakest team (roster 1, strength 40) projects to slot 1.
    slot = {p["assetId"]: p["projectedSlot"] for p in forecast["picks"]}
    assert slot[f"pick:{LEAGUE}:2027:r1:o1"] == 1


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


def test_first_write_wins_per_league_and_nfl_week(tmp_path: Path) -> None:
    first = snap.assemble_snapshot(_full_inputs(), recorded_at="2026-10-06T12:20:00+00:00")
    assert snap.record_snapshot(first, tmp_path) is True
    # Same week, different content (a re-run later that week): a no-op.
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
    assert [(r["leagueKey"], r["week"]) for r in stored] == [
        (LEAGUE, 5),
        (LEAGUE, 6),
        ("dynasty_new", 5),
    ]
    assert stored[0]["teamStrengthSource"] == "persisted_snapshot"


def test_season_type_is_part_of_the_week_identity() -> None:
    reg = snap.snapshot_key(LEAGUE, "2026", "regular", 1)
    pre = snap.snapshot_key(LEAGUE, "2026", "pre", 1)
    assert reg != pre


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
    monkeypatch.setattr(
        "src.api.draft_class_evidence.active_seasons_for_league",
        lambda _lid, seasons: list(seasons),
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
