"""Pin: payload priming must not block on Sleeper network calls.

``_prime_latest_payload`` runs in two loop-critical places:

* the FastAPI ``lifespan`` startup path, BEFORE uvicorn binds the
  port — deploy verification probes the port on a fixed retry budget,
  so anything slow here fails the deploy and triggers auto-rollback
  (this happened three times on 2026-07-25: a slow Sleeper API held
  the pre-bind overlay warm past the budget); and
* ``run_scraper`` at scrape end, directly on the event loop.

The overlay warm is a cache-priming optimization, so it belongs on a
background daemon thread (``_warm_overlays_in_background``).  This test
pins the contract: priming returns promptly even when the overlay
fetch hangs, and the warm still happens (on a thread) once the fetch
unblocks.
"""

from __future__ import annotations

import threading
import time

import server


def _minimal_contract() -> dict:
    return {
        "meta": {"leagueKey": "main"},
        "players": {},
        "playersArray": [],
        "sleeper": {"idToPlayer": {}},
        "date": "2026-01-01",
    }


def test_prime_latest_payload_returns_while_overlay_fetch_hangs(monkeypatch):
    """A wedged Sleeper API must not delay priming (and therefore must
    not delay the port bind at boot or the loop at scrape end)."""
    release = threading.Event()
    started = threading.Event()
    calls: list[str] = []

    def hanging_fetch(*, sleeper_league_id, id_to_player, force_refresh=False):
        started.set()
        calls.append(sleeper_league_id)
        # Simulate Sleeper stalling until the test releases it.
        release.wait(timeout=10)
        return {"teams": [{"ownerId": "o1"}], "overlayFetchedAt": "t"}

    monkeypatch.setattr(server._sleeper_overlay, "fetch_sleeper_overlay", hanging_fetch)

    t0 = time.monotonic()
    server._prime_latest_payload(_minimal_contract())
    elapsed = time.monotonic() - t0

    try:
        # Priming must return promptly — well under the hang window.
        # Generous bound: serialization of the minimal contract is
        # milliseconds; 5s only trips if the fetch ran inline.
        assert elapsed < 5.0, (
            f"_prime_latest_payload took {elapsed:.1f}s — the overlay warm "
            "is blocking again (it must run on a background thread)"
        )
        # The warm thread did start the fetch (cache priming preserved)
        # for at least one active league, unless no leagues are
        # configured in this environment — in which case there is
        # nothing to warm and nothing to block on either.
        if server._league_registry.active_leagues():
            assert started.wait(timeout=5), "overlay warm thread never started a fetch"
    finally:
        release.set()


def test_warm_overlays_in_background_is_nonfatal_on_fetch_error(monkeypatch):
    """A raising fetch must be swallowed by the worker (warm is
    best-effort), never propagate to the caller."""

    def broken_fetch(**_kw):
        raise RuntimeError("sleeper down")

    monkeypatch.setattr(server._sleeper_overlay, "fetch_sleeper_overlay", broken_fetch)

    # Must not raise, and must return immediately.
    t0 = time.monotonic()
    server._warm_overlays_in_background(_minimal_contract())
    assert time.monotonic() - t0 < 1.0
    # Give the daemon thread a beat to run + swallow the error.
    for th in threading.enumerate():
        if th.name == "sleeper-overlay-warm":
            th.join(timeout=5)
