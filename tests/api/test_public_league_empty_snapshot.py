"""An empty public-league snapshot must be a failure, not a result.

**Observed live, not theorised.** On 2026-07-30 at 16:18 UTC — on the
production deploy that shipped an unrelated dependency bump —
``https://chaseupside.com/api/public/league`` served **7,403 bytes** with
``leagueName: ""``, ``managers: 0``, ``seasonsCovered: []`` and all 17
sections empty. HTTP **200**. Meanwhile
``/api/public/league/metrics`` reported::

    rebuild_count:        3
    rebuild_failures:     0        <- nothing counted it
    last_season_count:    0        <- the only honest signal
    last_manager_count:   0
    last_contract_bytes:  2005444  <- FROZEN at the last healthy build

The public ``/league`` page is the only surface an anonymous visitor can
reach, and it had nothing on it, while every aggregate signal said
healthy. A monitor keyed on payload size —
``deploy/grafana/public-league-dashboard.json`` — would have read 2 MB
and green straight through the outage.

**The mechanism.** ``walk_league_chain`` returns ``[]`` on any Sleeper
miss (``src/public_league/sleeper_client.py``: ``if not league: break``,
8s timeout) and ``build_public_snapshot`` returns a season-less snapshot
rather than raising. ``_rebuild_public_snapshot`` then ran its entire
success path on it: cleared the failure cooldown, cached it with a fresh
``fetched_at`` (so it was served for the full 300s TTL *plus*
stale-while-revalidate), and skipped the persist block — which is guarded
on ``and snapshot.seasons`` and is the only writer of
``last_contract_bytes``. Hence the frozen counter: the metric could not
fall, because the code that sets it never ran.

Recovery took a forced rebuild once the TTL lapsed; the first
``?refresh=1`` inside the window was deduped and returned the empty
payload in 0.93s with ``rebuild_count`` unmoved.

The two tests below fail against the pre-fix server: the first because
the empty snapshot was cached and returned, the second because
``rebuild_failures`` stayed at 0.
"""

from __future__ import annotations

import time
import types

import pytest

import server


def _snapshot(seasons, managers_by_owner=None):
    """Minimal stand-in with the two attributes the guard reads."""
    return types.SimpleNamespace(
        seasons=list(seasons),
        managers=types.SimpleNamespace(by_owner_id=dict(managers_by_owner or {})),
    )


@pytest.fixture
def cold_cache(monkeypatch):
    """Cold cache pinned to a synthetic league; restored afterwards.

    ``_public_league_cache`` and ``_public_league_metrics`` are
    module-level globals shared with every other test in the run — the
    same reason ``test_public_league_refresh_storm`` saves and restores
    them.
    """
    saved = dict(server._public_league_cache)
    saved_metrics = dict(server._public_league_metrics)
    monkeypatch.setattr(
        server._league_registry,
        "get_sleeper_league_id",
        lambda *a, **k: "EMPTYTEST",
    )
    server._public_league_cache.update(
        {
            "snapshot": None,
            "snapshot_league_id": None,
            "fetched_at": 0.0,
            "refreshing": False,
            "last_failure_at": 0.0,
            "last_failure_error": None,
        }
    )
    yield
    server._public_league_cache.clear()
    server._public_league_cache.update(saved)
    server._public_league_metrics.clear()
    server._public_league_metrics.update(saved_metrics)


class TestEmptySnapshotIsRefusedNotCached:
    def test_a_zero_season_snapshot_is_not_served(self, cold_cache, monkeypatch):
        """With nothing cached, refuse rather than answer 200 with nothing."""
        monkeypatch.setattr(server, "build_public_snapshot", lambda *a, **k: _snapshot([]))
        with pytest.raises(server.PublicSnapshotUnavailable):
            server._get_public_snapshot(force_refresh=True)

    def test_a_zero_season_snapshot_is_not_cached(self, cold_cache, monkeypatch):
        """The empty snapshot must not land in the cache.

        This is what made the outage last: cached with a fresh
        ``fetched_at``, it was served for the whole TTL, and the first
        forced refresh inside that window was deduped.
        """
        monkeypatch.setattr(server, "build_public_snapshot", lambda *a, **k: _snapshot([]))
        with pytest.raises(server.PublicSnapshotUnavailable):
            server._get_public_snapshot(force_refresh=True)
        assert server._public_league_cache["snapshot"] is None

    def test_a_good_snapshot_still_caches_and_serves(self, cold_cache, monkeypatch):
        """The guard must not reject healthy rebuilds."""
        good = _snapshot(["2026", "2025"], {"o1": {}, "o2": {}})
        monkeypatch.setattr(server, "build_public_snapshot", lambda *a, **k: good)
        got = server._get_public_snapshot(force_refresh=True)
        assert got is good
        assert server._public_league_cache["snapshot"] is good
        assert server._public_league_metrics["last_season_count"] == 2
        assert server._public_league_metrics["last_manager_count"] == 2

    def test_the_last_good_snapshot_is_served_when_a_rebuild_comes_back_empty(
        self, cold_cache, monkeypatch
    ):
        """Serving stale beats serving empty.

        A healthy snapshot is already cached; the next rebuild returns
        zero seasons. The caller must get the good one, not the empty
        one and not a 503.
        """
        good = _snapshot(["2026", "2025"], {"o1": {}})
        monkeypatch.setattr(server, "build_public_snapshot", lambda *a, **k: good)
        server._get_public_snapshot(force_refresh=True)

        monkeypatch.setattr(server, "build_public_snapshot", lambda *a, **k: _snapshot([]))
        # Age the cache past its TTL so the force-refresh actually rebuilds
        # rather than being deduped by the post-lock re-check.
        server._public_league_cache["fetched_at"] = (
            time.time() - server._PUBLIC_LEAGUE_CACHE_TTL_SECONDS - 1
        )
        assert server._get_public_snapshot(force_refresh=True) is good


class TestTheOutageIsCountedAsAFailure:
    def test_an_empty_rebuild_increments_rebuild_failures(self, cold_cache, monkeypatch):
        """The signal that was missing.

        `rebuild_failures` read 0 through the live outage, which is what
        made it invisible to everything watching.
        """
        before = server._public_league_metrics.get("rebuild_failures", 0)
        monkeypatch.setattr(server, "build_public_snapshot", lambda *a, **k: _snapshot([]))
        with pytest.raises(server.PublicSnapshotUnavailable):
            server._get_public_snapshot(force_refresh=True)
        assert server._public_league_metrics["rebuild_failures"] == before + 1

    def test_an_empty_rebuild_arms_the_failure_cooldown(self, cold_cache, monkeypatch):
        """A success clears the cooldown; an empty result must not."""
        monkeypatch.setattr(server, "build_public_snapshot", lambda *a, **k: _snapshot([]))
        with pytest.raises(server.PublicSnapshotUnavailable):
            server._get_public_snapshot(force_refresh=True)
        assert server._public_league_cache["last_failure_at"] > 0
        assert "zero seasons" in str(server._public_league_cache["last_failure_error"])

    def test_the_season_and_manager_counts_report_zero(self, cold_cache, monkeypatch):
        """These two told the truth during the outage. Keep them truthful.

        Deliberately asserted alongside the failure counter: the fix is
        not "make the counters agree", it is "count the failure AND keep
        the honest counters honest", so a monitor can key on either.
        """
        monkeypatch.setattr(server, "build_public_snapshot", lambda *a, **k: _snapshot([]))
        with pytest.raises(server.PublicSnapshotUnavailable):
            server._get_public_snapshot(force_refresh=True)
        assert server._public_league_metrics["last_season_count"] == 0
        assert server._public_league_metrics["last_manager_count"] == 0
