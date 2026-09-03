"""C5-GD-02's first real caller.

Pinned against a real production shape discovered while validating this
script by hand (2026-09-03): ``sleeper.positions`` is keyed by player
NAME, not playerId -- ``sleeper.idToPlayer`` (playerId -> name) is the
missing link. The first version of this script assumed a direct
playerId -> position map and silently captured every player as position
UNKNOWN against real production data; ``test_position_map_chains_through_idtoplayer``
exists specifically so that regression can't come back quietly.
"""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.capture_game_day_snapshots import (  # noqa: E402
    _capture_league,
    _position_map_from_contract,
)
from src.api.league_registry import LeagueConfig  # noqa: E402
from src.ros import game_day_archive  # noqa: E402


def _league_cfg(**overrides) -> LeagueConfig:
    base = dict(
        key="dynasty_test",
        display_name="Test League",
        sleeper_league_id="123",
        scoring_profile="superflex_tep15_ppr1",
        roster_settings={"starters": {"QB": 1, "RB": 2, "WR": 2, "FLEX": 1}, "teamCount": 2},
        idp_enabled=False,
    )
    base.update(overrides)
    return LeagueConfig(**base)


def test_position_map_chains_through_idtoplayer():
    """The real bug this test exists to pin: sleeper.positions is
    name-keyed, so a direct playerId lookup against it silently misses
    every player. idToPlayer is the required intermediate step."""
    contract = {
        "sleeper": {
            "idToPlayer": {"111": "Jane Runner", "222": "Joe Thrower"},
            "positions": {"Jane Runner": "RB", "Joe Thrower": "QB"},
        }
    }
    assert _position_map_from_contract(contract) == {"111": "RB", "222": "QB"}


def test_position_map_drops_names_with_no_position_entry():
    contract = {
        "sleeper": {
            "idToPlayer": {"111": "Jane Runner", "999": "Nobody Known"},
            "positions": {"Jane Runner": "RB"},
        }
    }
    assert _position_map_from_contract(contract) == {"111": "RB"}


def test_position_map_empty_sleeper_block_returns_empty():
    assert _position_map_from_contract({}) == {}
    assert _position_map_from_contract({"sleeper": {}}) == {}


def test_capture_league_writes_one_snapshot_per_roster(tmp_path, monkeypatch):
    """End-to-end against fakes: real record_snapshot writes, real
    starter-slot resolution, real position-eligibility derivation --
    only the Sleeper HTTP calls and the scoring fingerprint are faked."""
    monkeypatch.setattr(game_day_archive, "ARCHIVE_ROOT", tmp_path)

    responses = {
        "https://api.sleeper.app/v1/league/123": {
            "roster_positions": ["QB", "RB", "WR", "FLEX", "BN", "BN"],
        },
        "https://api.sleeper.app/v1/league/123/rosters": [
            {"owner_id": "u1", "roster_id": 1, "players": ["111", "222", "333"]},
            {"owner_id": "u2", "roster_id": 2, "players": []},
        ],
    }

    def fake_fetch_json(url):
        return responses[url]

    import scripts.capture_game_day_snapshots as mod

    monkeypatch.setattr(mod, "_fetch_json", fake_fetch_json)
    monkeypatch.setattr(
        "src.api.league_registry.scoring_fingerprint_for_league",
        lambda cfg: "sf1:fake",
    )

    cfg = _league_cfg()
    position_map = {"111": "RB", "222": "QB", "333": "K"}

    written, skipped = _capture_league(
        cfg,
        position_map=position_map,
        season=2026,
        week=1,
        capture_kind="pregame",
        dry_run=False,
    )

    # roster u2 is empty -> skipped, not written or errored
    assert written == 1
    assert skipped == 1

    snap = game_day_archive.load_snapshot("dynasty_test", 2026, 1, "u1", "pregame")
    assert snap is not None
    assert snap.scoring_config_id == "sf1:fake"
    by_id = {p.player_id: p for p in snap.roster}
    assert by_id["111"].position == "RB"
    assert by_id["111"].is_lineup_eligible is True  # RB legal in RB or FLEX
    assert by_id["333"].position == "K"
    assert by_id["333"].is_lineup_eligible is False  # K not in this league's resolved slots
    # Every captured estimate is honestly unknown -- no per-week
    # projection source exists anywhere in this codebase (see the
    # script's own module docstring).
    assert all(p.point_estimate is None and p.estimate_source is None for p in snap.roster)


def test_capture_league_refuses_when_scoring_fingerprint_unavailable(tmp_path, monkeypatch):
    """Fails closed: an unproven scoring identity must never be
    fabricated into permanent evidence."""
    monkeypatch.setattr(game_day_archive, "ARCHIVE_ROOT", tmp_path)
    monkeypatch.setattr(
        "src.api.league_registry.scoring_fingerprint_for_league",
        lambda cfg: None,
    )

    written, skipped = _capture_league(
        _league_cfg(),
        position_map={},
        season=2026,
        week=1,
        capture_kind="pregame",
        dry_run=False,
    )
    assert (written, skipped) == (0, 0)
    assert game_day_archive.load_snapshots_for_week("dynasty_test", 2026, 1) == []


def test_capture_league_second_call_is_a_safe_noop(tmp_path, monkeypatch):
    """Re-running against a week already captured must not error --
    record_snapshot's append-only refusal is caught and counted as
    skipped, not raised."""
    monkeypatch.setattr(game_day_archive, "ARCHIVE_ROOT", tmp_path)

    responses = {
        "https://api.sleeper.app/v1/league/123": {"roster_positions": ["QB", "BN"]},
        "https://api.sleeper.app/v1/league/123/rosters": [
            {"owner_id": "u1", "roster_id": 1, "players": ["222"]},
        ],
    }

    import scripts.capture_game_day_snapshots as mod

    monkeypatch.setattr(mod, "_fetch_json", lambda url: responses[url])
    monkeypatch.setattr(
        "src.api.league_registry.scoring_fingerprint_for_league",
        lambda cfg: "sf1:fake",
    )

    cfg = _league_cfg()
    kwargs = dict(
        position_map={"222": "QB"},
        season=2026,
        week=1,
        capture_kind="pregame",
        dry_run=False,
    )
    first = _capture_league(cfg, **kwargs)
    second = _capture_league(cfg, **kwargs)
    assert first == (1, 0)
    assert second == (0, 1)


def test_capture_league_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(game_day_archive, "ARCHIVE_ROOT", tmp_path)

    responses = {
        "https://api.sleeper.app/v1/league/123": {"roster_positions": ["QB", "BN"]},
        "https://api.sleeper.app/v1/league/123/rosters": [
            {"owner_id": "u1", "roster_id": 1, "players": ["222"]},
        ],
    }

    import scripts.capture_game_day_snapshots as mod

    monkeypatch.setattr(mod, "_fetch_json", lambda url: responses[url])
    monkeypatch.setattr(
        "src.api.league_registry.scoring_fingerprint_for_league",
        lambda cfg: "sf1:fake",
    )

    written, skipped = _capture_league(
        _league_cfg(),
        position_map={"222": "QB"},
        season=2026,
        week=1,
        capture_kind="pregame",
        dry_run=True,
    )
    assert written == 1
    assert game_day_archive.load_snapshots_for_week("dynasty_test", 2026, 1) == []


def test_capture_league_skips_on_sleeper_fetch_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(game_day_archive, "ARCHIVE_ROOT", tmp_path)
    monkeypatch.setattr(
        "src.api.league_registry.scoring_fingerprint_for_league",
        lambda cfg: "sf1:fake",
    )

    import scripts.capture_game_day_snapshots as mod

    def raise_url_error(url):
        raise OSError("network unreachable")

    monkeypatch.setattr(mod, "_fetch_json", raise_url_error)

    written, skipped = _capture_league(
        _league_cfg(),
        position_map={},
        season=2026,
        week=1,
        capture_kind="pregame",
        dry_run=False,
    )
    assert (written, skipped) == (0, 0)
