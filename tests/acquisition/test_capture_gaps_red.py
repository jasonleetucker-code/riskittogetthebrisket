"""C1-U8 RED — the two places acquisition evidence is fetched and dropped.

WHY THESE ARE THE FIRST TESTS
─────────────────────────────
C1-ACQ-01 asks for acquisition history with cost basis.  Before any
schema question is interesting, there is a supply question: **is the
evidence even being kept?**  The survey says no, in two places, and both
are already paying the network cost.

RED-1  ``_build_waivers_block`` records NOTHING.  Every waiver and
       free-agent transaction passes through ``_build_trades_block``'s
       loop and is ``continue``d one line before ``ledger_batch.append``;
       the waivers builder then re-reads the same memoised bodies and
       discards everything older than ``window_days``.  The FAAB bid it
       computes is the literal cost basis of every non-draft, non-trade
       roster addition, and it survives only inside a rolling window.

RED-1b The capture must sit AHEAD of both filters — the window cutoff
       and the ``seen`` dedupe — for the same reason the trades path
       states at its own append: ``window_days`` is OUR cutoff, not
       Sleeper's, so a transaction outside it is exactly the one about
       to become unreadable.

RED-2  ``record_transactions`` is called with ``league_key`` and
       ``season`` unset, so both are NULL on every row ever written.
       Both are available at the call site.  Without ``league_key`` a
       per-league projection has to re-derive the registry key row by
       row, and ``season`` is the only thing distinguishing two chain
       members of the same registry league.

These assert on the RECORDED ROWS, never on the source's statement
order — a test that greps the file for an ``append`` before an ``if``
passes when the code is rearranged into something equivalent and wrong.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.api import sleeper_overlay
from src.retention import league_events

_NOW_MS = 1_770_000_000_000
_WINDOW_DAYS = 365
_INSIDE_MS = _NOW_MS - 10 * 24 * 3600 * 1000
_OUTSIDE_MS = _NOW_MS - 900 * 24 * 3600 * 1000


@pytest.fixture
def db(tmp_path, monkeypatch):
    league_events._reset_setup_cache_for_tests()
    path = tmp_path / "retention" / "league_events.sqlite"
    monkeypatch.setattr(league_events, "DB_PATH", path)
    yield path
    league_events._reset_setup_cache_for_tests()


def _waiver(tx_id: str, ts_ms: int, *, bid: int = 7, tx_type: str = "waiver") -> dict[str, Any]:
    return {
        "transaction_id": tx_id,
        "type": tx_type,
        "status": "complete",
        "leg": 3,
        "status_updated": ts_ms,
        "roster_ids": [4],
        "adds": {"4034": 4},
        "drops": {"1234": 4},
        "settings": {"waiver_bid": bid},
    }


def _fake_getter(transactions_by_league: dict[str, list[dict[str, Any]]]):
    """Serve the chain walk, roster lookup and one week of transactions."""

    def getter(url: str):
        if url.endswith("/rosters"):
            return [{"roster_id": 4, "owner_id": "u4"}]
        if url.endswith("/users"):
            return [{"user_id": "u4", "display_name": "Four"}]
        for lid, txs in transactions_by_league.items():
            if url.endswith(f"/league/{lid}/transactions/3"):
                return txs
            if url.endswith(f"/league/{lid}"):
                return {"league_id": lid, "season": "2026", "previous_league_id": None}
        if "/transactions/" in url:
            return []
        return None

    return getter


def _recorded(path) -> list[dict[str, Any]]:
    conn = league_events.connect(path)
    try:
        cur = conn.execute(
            "SELECT transaction_id, type, league_key, season, sleeper_league_id "
            "FROM league_transactions ORDER BY transaction_id"
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


class TestRed1WaiverEvidenceIsRetained:
    def test_a_completed_waiver_reaches_the_ledger(self, db, monkeypatch):
        monkeypatch.setattr(sleeper_overlay, "_utc_now_ms", lambda: _NOW_MS)
        getter = _fake_getter({"L1": [_waiver("w1", _INSIDE_MS)]})

        block = sleeper_overlay._build_waivers_block(
            "L1", window_days=_WINDOW_DAYS, id_to_player={}, getter=getter
        )
        assert (
            block
        ), "the display block itself regressed — this test is about retention, not display"

        rows = _recorded(db)
        assert [r["transaction_id"] for r in rows] == ["w1"], (
            "a completed waiver claim was fetched, rendered, and then dropped. Its FAAB bid "
            "is the cost basis of that acquisition and Sleeper is the only place it exists."
        )
        assert rows[0]["type"] == "waiver"

    def test_a_free_agent_add_reaches_the_ledger(self, db, monkeypatch):
        monkeypatch.setattr(sleeper_overlay, "_utc_now_ms", lambda: _NOW_MS)
        getter = _fake_getter({"L1": [_waiver("f1", _INSIDE_MS, bid=0, tx_type="free_agent")]})

        sleeper_overlay._build_waivers_block(
            "L1", window_days=_WINDOW_DAYS, id_to_player={}, getter=getter
        )
        assert [r["transaction_id"] for r in _recorded(db)] == ["f1"], (
            "a free-agent add is an acquisition with a $0 basis, which is a different "
            "statement from an unknown basis"
        )


class TestRed1bCaptureOutrunsBothFilters:
    def test_a_transaction_outside_the_display_window_is_still_recorded(self, db, monkeypatch):
        """The window is OUR cutoff, not Sleeper's."""
        monkeypatch.setattr(sleeper_overlay, "_utc_now_ms", lambda: _NOW_MS)
        getter = _fake_getter({"L1": [_waiver("old", _OUTSIDE_MS)]})

        block = sleeper_overlay._build_waivers_block(
            "L1", window_days=_WINDOW_DAYS, id_to_player={}, getter=getter
        )
        assert block == [], "fixture wrong: this transaction should be outside the display window"

        assert [r["transaction_id"] for r in _recorded(db)] == ["old"], (
            "capture sits behind the window cutoff, so the ledger only ever learns about "
            "claims that were ALREADY visible — the ones about to roll out of Sleeper's "
            "feed are exactly the ones it misses"
        )

    def test_a_duplicate_across_the_chain_still_reaches_the_ledger(self, db, monkeypatch):
        """The in-request ``seen`` set exists to stop the UI showing one
        claim twice.  The ledger has its own primary key for that, and
        deduping ahead of it would hide a chain member's own copy."""
        monkeypatch.setattr(sleeper_overlay, "_utc_now_ms", lambda: _NOW_MS)

        def getter(url: str):
            if url.endswith("/rosters"):
                return [{"roster_id": 4, "owner_id": "u4"}]
            if url.endswith("/users"):
                return [{"user_id": "u4", "display_name": "Four"}]
            if url.endswith("/league/L1"):
                return {"league_id": "L1", "season": "2026", "previous_league_id": "L0"}
            if url.endswith("/league/L0"):
                return {"league_id": "L0", "season": "2025", "previous_league_id": None}
            if "/transactions/3" in url:
                return [_waiver("dupe", _INSIDE_MS)]
            if "/transactions/" in url:
                return []
            return None

        sleeper_overlay._build_waivers_block(
            "L1", window_days=_WINDOW_DAYS, id_to_player={}, getter=getter
        )
        rows = _recorded(db)
        leagues = sorted(r["sleeper_league_id"] for r in rows)
        assert leagues == ["L0", "L1"], (
            "the same transaction id observed in two chain members must be recorded per "
            f"chain member, not deduped away in-request; got {leagues}"
        )


class TestRed2TheCallSiteSuppliesWhatItAlreadyKnows:
    def test_recorded_rows_carry_the_season(self, db, monkeypatch):
        monkeypatch.setattr(sleeper_overlay, "_utc_now_ms", lambda: _NOW_MS)
        getter = _fake_getter({"L1": [_waiver("w1", _INSIDE_MS)]})

        sleeper_overlay._build_waivers_block(
            "L1", window_days=_WINDOW_DAYS, id_to_player={}, getter=getter
        )
        rows = _recorded(db)
        assert rows, "nothing recorded — RED-1 has to pass first"
        assert rows[0]["season"] == "2026", (
            "season is NULL on every row: it is the only thing distinguishing two chain "
            "members of one registry league, and it is right there in the league object "
            "the chain walk already fetched"
        )

    def test_each_chain_member_records_its_own_season(self, db, monkeypatch):
        """Not the root's season stamped on everything — the whole point
        of the column is that one registry league spans several."""
        monkeypatch.setattr(sleeper_overlay, "_utc_now_ms", lambda: _NOW_MS)

        def getter(url: str):
            if url.endswith("/rosters"):
                return [{"roster_id": 4, "owner_id": "u4"}]
            if url.endswith("/users"):
                return [{"user_id": "u4", "display_name": "Four"}]
            if url.endswith("/league/L1"):
                return {"league_id": "L1", "season": "2026", "previous_league_id": "L0"}
            if url.endswith("/league/L0"):
                return {"league_id": "L0", "season": "2025", "previous_league_id": None}
            if "/transactions/3" in url:
                return [_waiver("dupe", _INSIDE_MS)]
            if "/transactions/" in url:
                return []
            return None

        sleeper_overlay._build_waivers_block(
            "L1", window_days=_WINDOW_DAYS, id_to_player={}, getter=getter
        )
        by_league = {r["sleeper_league_id"]: r["season"] for r in _recorded(db)}
        assert by_league == {"L1": "2026", "L0": "2025"}, by_league

    def test_an_unknown_season_stays_null_rather_than_guessing(self, db, monkeypatch):
        """``_league_season`` falls back to the calendar year, which is
        right for display and wrong here: a guessed season is
        indistinguishable from an observed one once it is stored."""
        monkeypatch.setattr(sleeper_overlay, "_utc_now_ms", lambda: _NOW_MS)

        def getter(url: str):
            if url.endswith("/rosters"):
                return [{"roster_id": 4, "owner_id": "u4"}]
            if url.endswith("/users"):
                return [{"user_id": "u4", "display_name": "Four"}]
            if url.endswith("/league/L1"):
                return {"league_id": "L1", "previous_league_id": None}  # no season
            if "/transactions/3" in url:
                return [_waiver("w1", _INSIDE_MS)]
            if "/transactions/" in url:
                return []
            return None

        sleeper_overlay._build_waivers_block(
            "L1", window_days=_WINDOW_DAYS, id_to_player={}, getter=getter
        )
        rows = _recorded(db)
        assert rows and rows[0]["season"] is None, rows

    def test_the_registry_key_is_resolved_from_the_root_not_per_member(self, monkeypatch):
        """A previous season's Sleeper id is not in the registry, so
        resolving per chain member would leave every historical row
        unattributed."""
        seen: list[str] = []

        def fake_lookup(sid):
            seen.append(str(sid))
            return "dynasty_main" if str(sid) == "L1" else None

        import src.api.league_registry as registry

        monkeypatch.setattr(registry, "league_key_for_sleeper_id", fake_lookup)
        assert sleeper_overlay._registry_key_for_chain("L1") == "dynasty_main"
        assert seen == ["L1"]
