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

# Captured at import time — BEFORE the fixture stubs the module
# attribute — so the fast-path tripwire test can restore the real
# implementation.
from src.api.sleeper_overlay import fetch_sleeper_teams_overlay as _REAL_TEAMS_OVERLAY
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
    # Both overlay entry points are stubbed — the endpoint uses the
    # teams-only fast path; background warm threads use the full one.
    monkeypatch.setattr(
        server._sleeper_overlay, "fetch_sleeper_teams_overlay", lambda **kwargs: None
    )
    monkeypatch.setattr(server._sleeper_overlay, "fetch_sleeper_overlay", lambda **kwargs: None)
    monkeypatch.setattr(server.public_snapshot_store, "load_snapshot", lambda: None)
    monkeypatch.setattr(
        faab_contention, "load_intel_snapshot", lambda path=None, league_key=None: None
    )

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


def _post(client, monkeypatch, body, mutate=None):
    contract = _stub_contract()
    if mutate is not None:
        mutate(contract)
    monkeypatch.setattr(server, "latest_contract_data", contract)
    return client.post("/api/waiver/faab-recommend", json=body)


# League analytics stand-in for the snapshot-scoping tests.  WR has
# ≥3 historical bids so the per-position calibration fires (which in
# turn keeps env scaling off), and o1 has a real aggression history
# while "departed" belongs to an owner no longer in the league.
_FAKE_SUMMARY = {
    "leagueBudget": 100,
    "leagueAvgWinningBid": 12.0,
    "leagueMedianWinningBid": 10.0,
    "totalBidsAnalyzed": 20,
    "positionBids": {"WR": {"avg": 30.0, "count": 10, "min": 5, "max": 60}},
    "tierBids": {},
    "teamAggression": {
        "o1": {
            "avgBid": 20.0,
            "winningCount": 5,
            "totalCount": 5,
            "totalSpent": 100,
            "maxBid": 40,
        },
        "departed": {
            "avgBid": 99.0,
            "winningCount": 9,
            "totalCount": 9,
            "totalSpent": 891,
            "maxBid": 99,
        },
    },
    "recentWins": [],
    "playerHistory": {},
}


# A snapshot timestamp that is always FRESH relative to the run.
#
# This was hardcoded to "2026-07-25T11:00:00+00:00".  ``leagueAnalytics``
# goes stale after 7 days (``faab_contention.py``'s
# ``_STALE_AFTER_SECONDS``), so the fixture aged out of freshness on
# 2026-08-01 and ``test_matching_league_snapshot_consumed_normally`` —
# which asserts ``"leagueAnalytics" not in staleInputs`` — became
# permanently red on the calendar, with no code change involved.
#
# A test whose verdict depends on the wall clock passes by construction
# when written and fails by construction later; either way its result is
# not about the code.  Anchoring to "now" keeps it measuring the thing it
# is named for: that a snapshot for the RESOLVED league flows through.
# Staleness itself is covered separately — see the stale-input tests
# that pass an explicitly old timestamp on purpose.
def _fresh_generated_at() -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()


def _install_snapshot(monkeypatch, league_id, summary=None, generated_at=None):
    """Fake public snapshot for ``league_id``; ``summary=None`` arms
    a tripwire that fails the test if the endpoint tries to build
    analytics from a wrong-league snapshot."""
    import types

    from src.api import faab_analytics

    snap = types.SimpleNamespace(
        root_league_id=league_id,
        generated_at=generated_at or _fresh_generated_at(),
    )
    monkeypatch.setattr(server.public_snapshot_store, "load_snapshot", lambda: snap)
    if summary is not None:
        monkeypatch.setattr(faab_analytics, "summarize_league_faab", lambda s: summary)
    else:

        def _boom(s):
            raise AssertionError("summarize_league_faab must not run for a wrong-league snapshot")

        monkeypatch.setattr(faab_analytics, "summarize_league_faab", _boom)


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


def test_broke_user_still_gets_populated_rival_field(faab_env, monkeypatch):
    """Codex P2 #1: the rival base is TEAM-INDEPENDENT.  A user with
    $0 remaining gets their own bid capped to $0, but rival demand is
    modeled from the add's public value — flush opponents still
    produce positive estimates and a positive clearing price."""

    def broke_me(contract):
        for t in contract["sleeper"]["teams"]:
            if t["ownerId"] == "me":
                t["faabRemaining"] = 0

    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = _post(
            c,
            monkeypatch,
            {"addPlayerName": "Hot Pickup", "teamOwnerId": "me"},
            mutate=broke_me,
        )
    payload = res.json()
    assert payload["standard"] == 0  # the USER's bid is capped at $0
    contention = payload["contention"]
    assert contention["skipped"] is False
    assert contention["perOpponent"], "rival field must not be empty"
    assert any(r["expBid"] > 0 for r in contention["perOpponent"])
    assert contention["topRival"] > 0
    assert contention["clearing"] == contention["topRival"] + 1


def test_missing_contention_lowers_reported_confidence(faab_env, monkeypatch):
    """Codex P2 #2: the contention-missing factor must count against
    confidence.  With baseline + trending + league calibration all
    present, the pre-append bucket would be 'high'; the appended
    0.15-weight missing factor pulls the honest bucket to 'medium'."""
    _install_snapshot(monkeypatch, "L-MAIN", summary=_FAKE_SUMMARY)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = _post(c, monkeypatch, {"addPlayerName": "Hot Pickup"})
    payload = res.json()
    missing = [f for f in payload["factors"] if f["missing"]]
    assert any(f["label"] == "Rival contention" for f in missing)
    assert payload["confidence"] == "medium"  # not "high"


def test_wrong_league_snapshot_treated_as_unavailable(faab_env, monkeypatch):
    """Codex P2 #3: a snapshot for ANOTHER league must not feed
    aggression/median/env into this league's estimates — analytics
    degrade to unavailable instead."""
    _install_snapshot(monkeypatch, "L-OTHER", summary=None)  # tripwire
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = _post(
            c,
            monkeypatch,
            {"addPlayerName": "Hot Pickup", "teamOwnerId": "me"},
        )
    payload = res.json()
    # League analytics reported as a missing input, not consumed.
    assert payload["inputsAsOf"]["leagueAnalytics"] is None
    assert "leagueAnalytics" in payload["staleInputs"]
    assert any("league" in f["label"].lower() and f["missing"] for f in payload["factors"])
    # Every rival defaults to neutral aggression with the lowSample flag.
    contention = payload["contention"]
    assert contention["perOpponent"]
    assert all(r["lowSample"] for r in contention["perOpponent"])
    assert all(r["aggression"] == 1.0 for r in contention["perOpponent"])
    assert any("sample floor" in n for n in contention["notes"])


def test_no_player_id_preserves_missing_trending(faab_env, monkeypatch):
    """Codex round-2 #1: a row without a playerId cannot be looked up
    on the trending board — the impossible lookup must NOT read as
    '0 trending / input present'.  With no name-based fallback either,
    trending stays an honestly-missing input."""

    def strip_pids(contract):
        for row in contract["playersArray"]:
            row["playerId"] = None

    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = _post(c, monkeypatch, {"addPlayerName": "Hot Pickup"}, mutate=strip_pids)
    payload = res.json()
    trending_factors = [f for f in payload["factors"] if f["label"].lower().startswith("trending")]
    assert trending_factors and all(f["missing"] for f in trending_factors)
    assert payload["inputsAsOf"]["trending"] is None
    assert "trending" in payload["staleInputs"]


def test_overlay_faab_budget_beats_hardcoded_fallback(faab_env, monkeypatch):
    """Codex round-2 #2: with league analytics unavailable, the
    budget must come from the roster block's faabBudget (the resolved
    league's real setting), not the hard-coded $100 — otherwise every
    bid in a $200 league is halved."""

    def budget_200(contract):
        for t in contract["sleeper"]["teams"]:
            t["faabBudget"] = 200

    with TestClient(server.app, raise_server_exceptions=True) as c:
        res_200 = _post(c, monkeypatch, {"addPlayerName": "Hot Pickup"}, mutate=budget_200)
        res_100 = _post(c, monkeypatch, {"addPlayerName": "Hot Pickup"})
    p200, p100 = res_200.json(), res_100.json()
    assert p200["max"] == 200  # cap follows the league's real budget
    assert p100["max"] == 100
    assert p200["standard"] == 2 * p100["standard"]  # bids scale with budget


def test_unmatched_team_owner_skips_contention(faab_env, monkeypatch):
    """Codex round-2 #4: a stale/foreign teamOwnerId matches no
    current roster — the opponent filter would exclude nobody and
    model the user's own team as a rival.  Contention must skip with
    the explicit note + missing factor (honest confidence included)."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = _post(
            c,
            monkeypatch,
            {"addPlayerName": "Hot Pickup", "teamOwnerId": "ghost-owner"},
        )
    payload = res.json()
    contention = payload["contention"]
    assert contention["skipped"] is True
    assert contention["perOpponent"] == []
    assert contention["clearing"] is None
    assert any("does not match any current roster" in n for n in contention["notes"])
    missing_factor = next(
        (f for f in payload["factors"] if f["label"] == "Rival contention"),
        None,
    )
    assert missing_factor is not None and missing_factor["missing"] is True
    # Honest confidence: the reported bucket accounts for the
    # appended missing factor (round-1 pattern).
    from src.trade.faab_recommender import compute_confidence

    assert payload["confidence"] == compute_confidence(payload["factors"])


def test_cold_cache_uses_teams_only_fast_path(faab_env, monkeypatch):
    """Codex round-3 P1: with a cold overlay cache the endpoint must
    take the teams-only fast path — the heavy trades/waivers history
    builders (dozens of serial Sleeper requests) are tripwired to
    fail the test if invoked."""
    from src.api import sleeper_overlay

    sleeper_overlay.invalidate_overlay_cache()

    def _boom(*args, **kwargs):
        raise AssertionError("heavy overlay builder invoked on the FAAB recommend path")

    monkeypatch.setattr(sleeper_overlay, "_build_trades_block", _boom)
    monkeypatch.setattr(sleeper_overlay, "_build_waivers_block", _boom)
    fresh_teams = [
        {
            "ownerId": "me",
            "name": "My Team",
            "players": [],
            "faabRemaining": 77,
            "faabBudget": 100,
        },
        {
            "ownerId": "o1",
            "name": "Rival One",
            "players": [],
            "faabRemaining": 55,
            "faabBudget": 100,
        },
    ]
    monkeypatch.setattr(
        sleeper_overlay, "_build_teams_block", lambda lid, id_map: list(fresh_teams)
    )
    # Restore the REAL teams-only fetch (the fixture stubs it to None).
    monkeypatch.setattr(sleeper_overlay, "fetch_sleeper_teams_overlay", _REAL_TEAMS_OVERLAY)
    try:
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = _post(
                c,
                monkeypatch,
                {"addPlayerName": "Hot Pickup", "teamOwnerId": "me"},
            )
        payload = res.json()
        assert res.status_code == 200
        # Honest freshness stamp from the live teams-only fetch.
        assert payload["inputsAsOf"]["rosters"]
        assert "rosters" not in payload["staleInputs"]
        # The fast-path teams (not the baked stub block) were used.
        contention = payload["contention"]
        assert contention["skipped"] is False
        assert {r["ownerId"] for r in contention["perOpponent"]} == {"o1"}
    finally:
        # The fast path cached its teams under this league id — drop
        # them so no other test inherits the tripwire fixture's data.
        sleeper_overlay.invalidate_overlay_cache()


def test_all_missing_balances_skip_contention(faab_env, monkeypatch):
    """Codex round-3 P2: rosters loaded but every faabRemaining is
    absent (degraded league-settings fetch) — contention must skip
    with the missing-input factor + honest confidence, never model
    unverifiable rivals at full bid."""

    def wipe_balances(contract):
        for t in contract["sleeper"]["teams"]:
            t["faabRemaining"] = None

    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = _post(
            c,
            monkeypatch,
            {"addPlayerName": "Hot Pickup", "teamOwnerId": "me"},
            mutate=wipe_balances,
        )
    payload = res.json()
    contention = payload["contention"]
    assert contention["skipped"] is True
    assert contention["perOpponent"] == []
    assert any("FAAB balances unavailable" in n for n in contention["notes"])
    missing_factor = next(
        (f for f in payload["factors"] if f["label"] == "Rival contention"),
        None,
    )
    assert missing_factor is not None and missing_factor["missing"] is True
    from src.trade.faab_recommender import compute_confidence

    assert payload["confidence"] == compute_confidence(payload["factors"])


def test_mixed_balances_run_with_unknown_rival_excluded(faab_env, monkeypatch):
    """Half the rivals carry a balance (o1) — contention runs, but the
    unknown-balance rival (o2) is flagged and excluded from the
    clearing math (documented conservative behavior)."""

    def unknown_o2(contract):
        for t in contract["sleeper"]["teams"]:
            if t["ownerId"] == "o2":
                t["faabRemaining"] = None

    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = _post(
            c,
            monkeypatch,
            {"addPlayerName": "Hot Pickup", "teamOwnerId": "me"},
            mutate=unknown_o2,
        )
    payload = res.json()
    contention = payload["contention"]
    assert contention["skipped"] is False
    per = {r["ownerId"]: r for r in contention["perOpponent"]}
    assert per["o2"]["balanceUnknown"] is True
    assert per["o1"]["balanceUnknown"] is False
    # The clearing price is driven by the verifiable rival only.
    assert contention["topRival"] == per["o1"]["expBid"]
    assert any("no visible FAAB balance" in n for n in contention["notes"])


def test_matching_league_snapshot_consumed_normally(faab_env, monkeypatch):
    """Counterpart to the wrong-league test: a snapshot for the
    RESOLVED league flows through — o1's real aggression history is
    used and the departed owner's entry never reaches the model."""
    generated_at = _fresh_generated_at()
    _install_snapshot(monkeypatch, "L-MAIN", summary=_FAKE_SUMMARY, generated_at=generated_at)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = _post(
            c,
            monkeypatch,
            {"addPlayerName": "Hot Pickup", "teamOwnerId": "me"},
        )
    payload = res.json()
    assert payload["inputsAsOf"]["leagueAnalytics"] == generated_at
    assert "leagueAnalytics" not in payload["staleInputs"]
    contention = payload["contention"]
    per = {r["ownerId"]: r for r in contention["perOpponent"]}
    assert set(per) == {"o1", "o2"}  # "departed" filtered out
    # o1: avgBid 20 vs median 10 → aggression 2.0, real sample.
    assert per["o1"]["aggression"] == 2.0
    assert per["o1"]["lowSample"] is False
