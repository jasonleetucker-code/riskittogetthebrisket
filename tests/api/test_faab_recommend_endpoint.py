"""Endpoint tests for ``POST /api/waiver/faab-recommend`` (FAAB v2).

Pins the response contract:

* BACKWARD COMPAT — every v1 key survives unchanged; FAAB v2 only
  ADDS keys (``contention``, ``inputsAsOf``, ``staleInputs``).
* No ``teamOwnerId`` in the body ⇒ contention is SKIPPED with an
  explicit missing-factor note — the server never guesses which
  team is the user's.
* With ``teamOwnerId`` ⇒ contention runs against the OTHER teams
  only, ``clearing = topRival + 1``.

All Sleeper/analytics/intel inputs are stubbed — no live network.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import server
from src.api import league_registry
from src.trade import faab_contention

# The v1 response keys — the frozen backward-compat surface.
V1_KEYS = {
    "conservative",
    "standard",
    "aggressive",
    "max",
    "confidence",
    "factors",
    "warnings",
    "explanation",
    "leagueKey",
    "resolvedAddValue",
    "resolvedDropValue",
    "resolvedAddPosition",
}


@pytest.fixture
def faab_env(tmp_path, monkeypatch):
    """Single-league registry + stubbed external inputs."""
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "defaultLeagueKey": "main",
                "leagues": [
                    {
                        "key": "main",
                        "displayName": "Main",
                        "sleeperLeagueId": "L-MAIN",
                        "active": True,
                        "rosterSettings": {"teamCount": 12},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()

    from src.api import user_kv

    monkeypatch.setattr(user_kv, "USER_KV_PATH", tmp_path / "user_kv.sqlite")
    user_kv._SETUP_DONE.clear()

    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)

    # Kill every external input: overlay (rosters come from the baked
    # stub block), public snapshot (league analytics), intel snapshot.
    monkeypatch.setattr(server._sleeper_overlay, "fetch_sleeper_overlay", lambda **kwargs: None)
    monkeypatch.setattr(server.public_snapshot_store, "load_snapshot", lambda: None)
    monkeypatch.setattr(faab_contention, "load_intel_snapshot", lambda path=None: None)

    # Trending adapter serves a canned snapshot (primary path).
    from src.adapters import sleeper_trending

    monkeypatch.setattr(
        sleeper_trending,
        "get_trending_adds",
        lambda **kwargs: {
            "fetchedAt": "2026-07-25T12:00:00+00:00",
            "lookbackHours": 24,
            "counts": {"1234": 12000},
        },
    )

    yield

    league_registry.reload_registry()


def _row(name, pos, value, pid=None):
    return {
        "canonicalName": name,
        "displayName": name,
        "position": pos,
        "rankDerivedValue": value,
        "playerId": pid,
        "rookie": False,
    }


def _stub_contract():
    return {
        "meta": {"leagueKey": "main"},
        "players": {"stub": {"name": "Stub"}},
        "playersArray": [
            _row("Hot Pickup", "WR", 4000, pid="1234"),
            _row("Backup Wr", "WR", 1000),
            _row("Rostered Wr", "WR", 5000),
            _row("Rostered Qb", "QB", 6000),
        ],
        "sleeper": {
            "leagueId": "L-MAIN",
            "teams": [
                {
                    "ownerId": "me",
                    "name": "My Team",
                    "players": ["Rostered Qb"],
                    "faabRemaining": 80,
                },
                {
                    "ownerId": "o1",
                    "name": "Rival One",
                    "players": ["Rostered Wr"],
                    "faabRemaining": 60,
                },
                {
                    "ownerId": "o2",
                    "name": "Rival Two",
                    "players": [],
                    "faabRemaining": 0,
                },
            ],
        },
    }


def _post(client, monkeypatch, body):
    monkeypatch.setattr(server, "latest_contract_data", _stub_contract())
    return client.post("/api/waiver/faab-recommend", json=body)


def test_backward_compat_keys_and_additive_v2_keys(faab_env, monkeypatch):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = _post(c, monkeypatch, {"addPlayerName": "Hot Pickup"})
    assert res.status_code == 200
    payload = res.json()
    # Every v1 key present (backward compat pin).
    assert V1_KEYS <= set(payload.keys())
    # FAAB v2 additive keys.
    assert set(payload["contention"].keys()) >= {
        "clearing",
        "topRival",
        "perOpponent",
        "skipped",
        "notes",
    }
    assert set(payload["inputsAsOf"].keys()) == {
        "rosters",
        "leagueAnalytics",
        "trending",
        "intel",
    }
    assert isinstance(payload["staleInputs"], list)
    assert payload["leagueKey"] == "main"
    assert payload["resolvedAddPosition"] == "WR"
    assert payload["resolvedAddValue"] == 4000


def test_no_team_owner_skips_contention_with_missing_factor(faab_env, monkeypatch):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = _post(c, monkeypatch, {"addPlayerName": "Hot Pickup"})
    payload = res.json()
    contention = payload["contention"]
    assert contention["skipped"] is True
    assert contention["clearing"] is None
    assert contention["topRival"] is None
    assert contention["perOpponent"] == []
    assert any("never guess" in n for n in contention["notes"])
    missing_factor = next(
        (f for f in payload["factors"] if f["label"] == "Rival contention"),
        None,
    )
    assert missing_factor is not None
    assert missing_factor["missing"] is True


def test_team_owner_enables_contention_against_other_teams(faab_env, monkeypatch):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = _post(
            c,
            monkeypatch,
            {"addPlayerName": "Hot Pickup", "teamOwnerId": "me"},
        )
    payload = res.json()
    contention = payload["contention"]
    assert contention["skipped"] is False
    assert contention["clearing"] == contention["topRival"] + 1
    owner_ids = {r["ownerId"] for r in contention["perOpponent"]}
    assert "me" not in owner_ids  # the user's team is never a rival
    assert owner_ids == {"o1", "o2"}
    # Broke rival is capped at their $0 remaining.
    o2 = next(r for r in contention["perOpponent"] if r["ownerId"] == "o2")
    assert o2["expBid"] == 0
    # Winning-bid selection bias is surfaced, not hidden.
    assert contention["estimateOnly"] is True
    assert any("selection bias" in n for n in contention["notes"])


def test_inputs_as_of_and_stale_inputs_reflect_stubbed_sources(faab_env, monkeypatch):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = _post(c, monkeypatch, {"addPlayerName": "Hot Pickup"})
    payload = res.json()
    inputs = payload["inputsAsOf"]
    # Trending came from the canned adapter snapshot.
    assert inputs["trending"] == "2026-07-25T12:00:00+00:00"
    # Overlay/analytics/intel were stubbed away → no timestamps →
    # flagged stale.
    assert inputs["rosters"] is None
    assert inputs["leagueAnalytics"] is None
    assert inputs["intel"] is None
    stale = set(payload["staleInputs"])
    assert {"rosters", "leagueAnalytics", "intel"} <= stale


def test_trending_adapter_is_primary_signal(faab_env, monkeypatch):
    """The add player is hot on the adapter's board (12k adds) —
    the trending factor must register as PRESENT, not missing."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = _post(c, monkeypatch, {"addPlayerName": "Hot Pickup"})
    payload = res.json()
    trending_factors = [f for f in payload["factors"] if f["label"].lower().startswith("trending")]
    assert trending_factors, "expected a trending factor row"
    assert all(f["missing"] is False for f in trending_factors)


def test_unknown_player_still_404s(faab_env, monkeypatch):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = _post(c, monkeypatch, {"addPlayerName": "Ghost Player"})
    assert res.status_code == 404
