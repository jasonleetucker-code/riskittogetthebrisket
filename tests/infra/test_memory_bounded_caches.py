"""Memory bounds from the 2026-10-19 production memory-pressure incident.

The backend was restarted by the liveness watchdog after its cgroup peaked
at 2.6 GB against ``MemoryHigh=2560M`` on a swapless host.  Three
process-lifetime retentions were measured with a module-global deep-size
scan after one authenticated round of the V1 route set:

* ``src.news.providers.sleeper._PLAYER_MAP`` held Sleeper's whole
  ``/players/nfl`` dump (38.4 MB) as a second copy beside
  ``sleeper_client``'s, while the provider reads five fields of it;
* ``src.public_league.sleeper_client._request_cache`` expired lazily, so
  every URL fetched once stayed resident although its 60 s TTL meant it
  could never be served again;
* ``server._persisted`` pinned the boot public-league snapshot (46.9 MB)
  after the first rebuild replaced the served one.

Each test pins BOTH halves of the fix: the answer callers see is
unchanged, and the retention is bounded.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from src.news.providers import sleeper as news_sleeper
from src.public_league import sleeper_client as sc

REPO = Path(__file__).resolve().parents[2]


# ── news provider player map ──────────────────────────────────────────


def _dump() -> dict:
    return {
        "6797": {
            "full_name": "Jayden Reed",
            "first_name": "Jayden",
            "last_name": "Reed",
            "position": "WR",
            "team": "GB",
            # Fields the provider never reads — the bulk of the real dump.
            "birth_date": "2000-03-27",
            "college": "Michigan State",
            "fantasy_positions": ["WR"],
            "metadata": {"rookie_year": "2023", "channel_id": "x" * 200},
            "injury_status": None,
        },
        "9999": {"first_name": "Rookie", "last_name": "Breakout", "position": "RB"},
        "1234": {"full_name": "No Team", "position": "WR", "team": None},
        "4321": {"years_exp": 3},  # nameless — the provider skips it
        "5555": "not-a-dict",  # kept verbatim, exactly as before
    }


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _Session:
    def __init__(self, dump):
        self._dump = dump

    def get(self, url, timeout=None, headers=None):
        if "/trending/add" in url:
            # The non-dict entry crashes the provider on the full dump and the
            # slim one alike, so it is not trended here (the slim-map test
            # pins that it is kept verbatim).
            ids = [pid for pid, e in self._dump.items() if isinstance(e, dict)]
            return _Resp([{"player_id": pid, "count": 100 - i} for i, pid in enumerate(ids)])
        if "/trending/drop" in url:
            return _Resp([{"player_id": "1234", "count": 7}])
        if url.endswith("/players/nfl"):
            return _Resp(self._dump)
        raise AssertionError(url)


def _items(provider_map_full: bool) -> list:
    news_sleeper._reset_player_map_for_tests()
    provider = news_sleeper.SleeperTrendingProvider(session=_Session(_dump()))
    if provider_map_full:
        # The pre-fix behaviour: the cache stored the dump verbatim.
        original = news_sleeper._slim_player_map
        news_sleeper._slim_player_map = lambda raw: raw
        try:
            return [i for i in provider.fetch(limit=50)]
        finally:
            news_sleeper._slim_player_map = original
    return [i for i in provider.fetch(limit=50)]


def test_slim_player_map_renders_identical_items():
    """Every NewsItem field is identical whether the map is full or slim."""
    full = _items(provider_map_full=True)
    slim = _items(provider_map_full=False)
    assert full, "fixture must produce items"

    def _shape(items):
        # ``ts`` is the fetch clock (two fetches, two instants); every other
        # field is a function of the player map and must be identical.
        return [dataclasses.replace(i, ts="") for i in items]

    assert _shape(full) == _shape(slim)


def test_slim_player_map_keeps_only_read_fields():
    slim = news_sleeper._slim_player_map(_dump())
    assert set(slim) == set(_dump()), "every key survives"
    assert slim["5555"] == "not-a-dict", "non-dict entries are kept verbatim"
    for pid, entry in slim.items():
        if isinstance(entry, dict):
            assert set(entry) <= set(news_sleeper._PLAYER_MAP_FIELDS)
            # A field absent upstream stays absent (never None-filled).
            assert set(entry) == {f for f in news_sleeper._PLAYER_MAP_FIELDS if f in _dump()[pid]}
    news_sleeper._reset_player_map_for_tests()
    news_sleeper.SleeperTrendingProvider(session=_Session(_dump()))._fetch_player_map()
    cached = news_sleeper._PLAYER_MAP._map
    assert "metadata" not in cached["6797"] and "college" not in cached["6797"]
    news_sleeper._reset_player_map_for_tests()


# ── sleeper_client request cache ──────────────────────────────────────


@pytest.fixture
def clean_request_cache(monkeypatch):
    sc.reset_request_cache()
    monkeypatch.setattr(sc, "_CACHE_TTL_SECONDS", 60.0)
    yield
    sc.reset_request_cache()


def _at(monkeypatch, t: float) -> None:
    import time as _time

    monkeypatch.setattr(_time, "time", lambda: t)


def test_request_cache_ttl_answers_unchanged(clean_request_cache, monkeypatch):
    _at(monkeypatch, 1000.0)
    sc._cache_put("u1", {"a": 1})
    _at(monkeypatch, 1059.0)
    assert sc._cache_get("u1") == {"a": 1}, "live entry still served"
    _at(monkeypatch, 1061.0)
    assert sc._cache_get("u1") is None, "expired entry still never served"
    sc._cache_put("u2", None)
    assert "u2" not in sc._request_cache, "failures are still not cached"


def test_request_cache_sweeps_expired_entries_on_put(clean_request_cache, monkeypatch):
    _at(monkeypatch, 1000.0)
    for i in range(50):
        sc._cache_put(f"https://x/week/{i}", {"payload": i})
    _at(monkeypatch, 1100.0)  # every one is past its TTL, none was re-read
    sc._cache_put("https://x/fresh", {"payload": "fresh"})
    assert list(sc._request_cache) == ["https://x/fresh"]


def test_request_cache_is_capped_oldest_first(clean_request_cache, monkeypatch):
    _at(monkeypatch, 1000.0)
    cap = sc._REQUEST_CACHE_MAX_ENTRIES
    for i in range(cap + 25):
        sc._cache_put(f"u{i}", i)
    assert len(sc._request_cache) == cap
    assert sc._cache_get("u0") is None and sc._cache_get(f"u{cap + 24}") == cap + 24
    # A re-put refreshes recency: it is no longer the next to go.
    sc._cache_put("u25", "again")
    sc._cache_put("new", 1)
    assert sc._cache_get("u25") == "again"
    assert sc._cache_get("u26") is None


# ── boot public-league snapshot ───────────────────────────────────────


def test_boot_public_snapshot_is_not_pinned_by_a_module_global():
    """No module-level name in server.py binds the boot snapshot.

    The served snapshot's only owner is ``_public_league_cache``; a module
    global would keep the boot generation alive after every rebuild.
    """
    tree = ast.parse((REPO / "server.py").read_text(encoding="utf-8"))
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.Try):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Assign):
                    targets.extend(inner.targets)
        for target in targets:
            value = getattr(node, "value", None)
            names = {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}
            assert "_persisted" not in names
            if value is not None and isinstance(value, ast.Call):
                func = value.func
                called = getattr(func, "attr", getattr(func, "id", ""))
                assert called != "load_snapshot", (
                    "the persisted public snapshot must be loaded inside a function, "
                    "never bound to a module global"
                )


def test_boot_public_snapshot_loader_seeds_the_cache(monkeypatch):
    import server

    class _Snap:
        seasons = [object()]
        root_league_id = "L1"

    monkeypatch.setattr(server.public_snapshot_store, "load_snapshot", lambda: _Snap())
    monkeypatch.setattr(server, "_public_snapshot_integrity_error", lambda snap: None)
    saved = dict(server._public_league_cache)
    try:
        server._load_persisted_public_snapshot_at_boot()
        assert isinstance(server._public_league_cache["snapshot"], _Snap)
        assert server._public_league_cache["snapshot_league_id"] == "L1"
        assert server._public_league_cache["fetched_at"] == 0.0
        assert not hasattr(server, "_persisted")
    finally:
        server._public_league_cache.clear()
        server._public_league_cache.update(saved)
