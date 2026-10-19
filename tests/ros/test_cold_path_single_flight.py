"""Cold-path single flights: concurrent cold reads share ONE compute or download.

``load_or_compute_team_strength``'s 120 s TTL only helps callers that arrive
after a live compute finishes.  A cold page load fans out (Analyze Trade's
posture bundle, Gameplan, the playoff sim ...) and every caller arriving
during the compute used to start its own Sleeper overlay fetch and full lineup
solve.  Trade War Room speed, owner directive 2026-10-19.
"""

from __future__ import annotations

import threading

from src.ros import team_strength

ROWS = [{"ownerId": "o1", "startingLineupScore": 10.0, "fullRoster": []}]


def _patch(monkeypatch, compute):
    monkeypatch.setattr(team_strength, "_live_compute_cache", {})
    monkeypatch.setattr(team_strength, "persisted_fast_path_rows", lambda _k=None: None)
    monkeypatch.setattr(team_strength, "compute_team_strength_live", compute)
    persisted: list = []
    monkeypatch.setattr(
        team_strength,
        "_persist_best_effort",
        lambda rows, *, league_key, persist: persisted.append((league_key, persist)),
    )
    return persisted


def test_concurrent_cold_callers_compute_once_and_share_rows(monkeypatch):
    gate = threading.Event()
    calls: list[str] = []

    def compute(league_key):
        calls.append(league_key)
        gate.wait(5)
        return [dict(r) for r in ROWS]

    persisted = _patch(monkeypatch, compute)
    results: list = []
    threads = [
        threading.Thread(
            target=lambda: results.append(team_strength.load_or_compute_team_strength("lg"))
        )
        for _ in range(4)
    ]
    for t in threads:
        t.start()
    while not calls:
        threading.Event().wait(0.01)
    threading.Event().wait(0.2)
    gate.set()
    for t in threads:
        t.join(10)
    assert calls == ["lg"]
    assert len(results) == 4 and all(r == ROWS for r in results)
    assert persisted == [("lg", True)]  # persisted once, by the one compute


def test_leagues_and_persist_modes_do_not_share_a_flight(monkeypatch):
    calls: list[str] = []
    _patch(monkeypatch, lambda key: calls.append(key) or [dict(r) for r in ROWS])
    team_strength.load_or_compute_team_strength("a")
    team_strength.load_or_compute_team_strength("b")
    assert calls == ["a", "b"]
    # Within the TTL a finished compute is reused, as before.
    team_strength.load_or_compute_team_strength("a")
    assert calls == ["a", "b"]


def test_an_evidence_less_compute_is_still_unavailable(monkeypatch):
    persisted = _patch(monkeypatch, lambda key: [{"ownerId": "o1", "startingLineupScore": 0.0}])
    assert team_strength.load_or_compute_team_strength("z") == []
    assert persisted == []


def test_concurrent_cold_nfl_player_dump_reads_download_once(monkeypatch):
    from src.public_league import sleeper_client

    gate = threading.Event()
    downloads: list[str] = []

    def fake_request(url, timeout=None):
        downloads.append(url)
        gate.wait(5)
        return {"1": {"full_name": "A"}}

    monkeypatch.setattr(sleeper_client, "_nfl_players_cache", None)
    monkeypatch.setattr(sleeper_client, "_request_json", fake_request)
    out: list = []
    threads = [
        threading.Thread(target=lambda: out.append(sleeper_client.fetch_nfl_players()))
        for _ in range(3)
    ]
    for t in threads:
        t.start()
    while not downloads:
        threading.Event().wait(0.01)
    threading.Event().wait(0.2)
    gate.set()
    for t in threads:
        t.join(10)
    assert len(downloads) == 1
    assert out == [{"1": {"full_name": "A"}}] * 3
    # A failure is still not cached (the next caller retries).
    monkeypatch.setattr(sleeper_client, "_nfl_players_cache", None)
    monkeypatch.setattr(sleeper_client, "_request_json", lambda url, timeout=None: None)
    assert sleeper_client.fetch_nfl_players() == {}
    assert sleeper_client._nfl_players_cache is None
