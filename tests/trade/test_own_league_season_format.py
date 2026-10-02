"""Own-league trades are classified in their OWN season's league format.

Synthetic leagues only (no real league id, manager or trade).  What is pinned:

* a past-season own-league trade reads THAT season-league's settings (10
  teams, its own slots and card), never today's registry league;
* the ``previous_league_id`` chain is walked, stored and resolved, and a
  completed season is fetched once and then frozen;
* point in time = a BRACKET: a capture at or before the trade is exact only
  once a later re-fetch confirmed the same payload hash (no later check ->
  ``format_unconfirmed_after_trade``; a different hash -> changed, capped);
  one taken after the trade (a completed season's final settings fetched now)
  is capped; the registry format never certifies anything;
* an undated legacy snapshot never counts as exact for a later trade;
* evidence only — nothing here reaches a served value.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from src.acquisition import store as store_mod
from src.acquisition.events import events_from_transaction
from src.sharp import league_format_capture as lfc
from src.trade import market_trade_format as mtf
from src.trade import market_trade_normalize as N
from src.trade import own_league_format_capture as olfc
from tests.trade.market_trade_fixtures import TARGET_POSITIONS, ctx, sleeper_league

REPO = Path(__file__).resolve().parents[2]
HOUR = 3600 * 1000
DAY = 24 * HOUR
T_2025 = 1_757_000_000_000  # 2025-09
T_NOW = 1_790_000_000_000  # 2026-09-21

CUR, PREV, OLDEST = "SYN-CUR-2026", "SYN-PREV-2025", "SYN-OLD-2024"
KEY = "syn_own_league"

#: 2025's league: 10 teams, one fewer TE slot, a TE bonus that 2026 dropped.
PREV_POSITIONS = [p for p in TARGET_POSITIONS if p != "TE"] + ["TE"]
PREV_SCORING_EXTRA = {"bonus_rec_te": 0.35}


def _season_league(lid, season, *, teams, prev, status, positions=None, scoring_extra=None):
    lg = sleeper_league(lid, teams=teams, roster_positions=positions)
    lg["season"] = season
    lg["status"] = status
    lg["previous_league_id"] = prev
    lg["scoring_settings"].update(scoring_extra or {})
    return lg


LEAGUES = {
    CUR: _season_league(CUR, "2026", teams=12, prev=PREV, status="in_season"),
    PREV: _season_league(
        PREV,
        "2025",
        teams=10,
        prev=OLDEST,
        status="complete",
        positions=PREV_POSITIONS,
        scoring_extra=PREV_SCORING_EXTRA,
    ),
    OLDEST: _season_league(OLDEST, "2024", teams=10, prev="0", status="complete"),
}


class FakeSleeper:
    def __init__(self, leagues=None):
        self.leagues = dict(leagues or LEAGUES)
        self.calls: list[str] = []

    def __call__(self, url):
        self.calls.append(url)
        return self.leagues.get(url.rsplit("/", 1)[-1])


def _target():
    """Today's league (= the current season-league's own format)."""
    return mtf.format_from_sleeper_league(LEAGUES[CUR])


@pytest.fixture
def store(tmp_path):
    return tmp_path / "own_formats.sqlite"


def _refresh(store, *, at_ms, http=None, **kw):
    return olfc.refresh_own_league_formats(
        KEY,
        root_league_id=CUR,
        path=store,
        http_get=http or FakeSleeper(),
        clock_ms=lambda: at_ms,
        **kw,
    )


def _classify(trade, index):
    return N._own_league_format(
        trade,
        league_key=KEY,
        index=index,
        current_league_id=CUR,
        registry_format=_target,
    )


def _dispose(fmt, src, ev):
    return mtf.disposition(fmt, _target(), observation={"formatSource": src, "formatEvidence": ev})


# ── the chain ──────────────────────────────────────────────────────────────


class TestChain:
    def test_previous_league_id_chain_is_walked_and_indexed_by_its_own_season(self, store):
        res = _refresh(store, at_ms=T_NOW)
        assert res.stopped_reason is None
        assert res.leagues_fetched == 3 and res.captures_new == 3
        idx = olfc.load_index(store)
        assert idx.league_for_season(KEY, "2026") == CUR
        assert idx.league_for_season(KEY, 2025) == PREV
        assert idx.league_for_season(KEY, "2024") == OLDEST
        assert idx.league_for_season(KEY, "2023") is None, "no substitute season"

    def test_a_completed_season_is_fetched_once_then_frozen(self, store):
        _refresh(store, at_ms=T_NOW)
        http = FakeSleeper()
        res = _refresh(store, at_ms=T_NOW + DAY, http=http)
        # Only the in-season league is re-fetched; the completed ones follow
        # their stored link.
        assert [u.rsplit("/", 1)[-1] for u in http.calls] == [CUR]
        assert res.skipped_frozen == 2 and res.captures_unchanged == 1
        assert olfc.load_index(store).league_for_season(KEY, "2024") == OLDEST

    def test_a_mid_season_change_is_a_new_dated_row_never_an_overwrite(self, store):
        _refresh(store, at_ms=T_NOW)
        changed = dict(LEAGUES)
        changed[CUR] = {**LEAGUES[CUR], "total_rosters": 14}
        _refresh(store, at_ms=T_NOW + DAY, http=FakeSleeper(changed))
        caps = olfc.load_index(store).captures[CUR]
        assert [c["capturedMs"] for c in caps] == [T_NOW, T_NOW + DAY]

    def test_max_fetches_caps_the_walk(self, store):
        res = _refresh(store, at_ms=T_NOW, max_fetches=2)
        assert res.leagues_fetched == 2 and res.stopped_reason == "budget_exhausted"

    def test_a_malformed_chain_resolves_to_the_earliest_recorded_link(self, store):
        # A bogus link claiming 2025, written FIRST (lowest rowid, so plain
        # table order would hand it the season) but recorded LATER in time.
        conn = olfc.connect(store)
        try:
            conn.execute(
                "INSERT INTO own_league_season_chain "
                "(league_key, league_id, season, previous_league_id, first_seen_ms) "
                "VALUES (?, ?, ?, ?, ?)",
                (KEY, "ZZZ-BOGUS", "2025", None, T_NOW + DAY),
            )
            conn.commit()
        finally:
            conn.close()
        _refresh(store, at_ms=T_NOW)
        for _ in range(3):
            assert olfc.load_index(store).league_for_season(KEY, "2025") == PREV

    def test_a_429_stops_the_walk_and_is_not_a_missing_league(self, store):
        def limited(url):
            raise lfc.RateLimited(url)

        res = _refresh(store, at_ms=T_NOW, http=limited)
        assert res.stopped_reason == "rate_limited" and res.captures_new == 0

    def test_a_missing_store_is_a_state_not_an_error(self, tmp_path):
        idx = olfc.load_index(tmp_path / "absent.sqlite")
        assert idx.state == "own_league_format_store_missing" and not idx.captures
        assert not (tmp_path / "absent.sqlite").exists(), "a read never creates the store"


# ── point-in-time classification ───────────────────────────────────────────


class TestPastSeason:
    def test_a_past_season_trade_uses_that_seasons_league_not_todays(self, store):
        _refresh(store, at_ms=T_NOW)
        idx = olfc.load_index(store)
        trade = {"sleeperLeagueId": PREV, "season": "2025", "occurredAtMs": T_2025}
        fmt, src, ev = _classify(trade, idx)
        assert fmt.teams == 10, "2025's 10 teams, not today's 12"
        assert fmt.scoring.get("bonus_rec_te") == 0.35
        assert src == N.FORMAT_SOURCE_SEASON_LEAGUE_POST_TRADE
        assert ev["basis"] == "season_league_settings"
        assert ev["seasonLeagueId"] == PREV and ev["seasonCompleteAtCapture"] is True
        assert ev["exactAtTradeTime"] is False
        d = _dispose(fmt, src, ev)
        assert d["disposition"] == mtf.TARGET_UNSUPPORTED
        assert d["comparability"]["teamCount"]["state"] == mtf.DIFFERENT
        assert d["formatTimingCap"] == mtf.TIMING_CAP_POST_TRADE

    def test_a_trade_without_a_league_id_resolves_through_the_chain(self, store):
        _refresh(store, at_ms=T_NOW)
        trade = {"sleeperLeagueId": None, "season": "2025", "occurredAtMs": T_2025}
        fmt, _src, ev = _classify(trade, olfc.load_index(store))
        assert ev["seasonLeagueResolution"] == "previous_league_id_chain"
        assert ev["seasonLeagueId"] == PREV and fmt.teams == 10

    def test_an_identical_past_format_is_still_capped_by_timing(self, store):
        # Even when every axis MATCHES, a completed season's final settings
        # fetched later do not prove the settings at trade time.
        same = dict(LEAGUES)
        same[PREV] = {**LEAGUES[CUR], "league_id": PREV, "season": "2025", "status": "complete"}
        _refresh(store, at_ms=T_NOW, http=FakeSleeper(same))
        trade = {"sleeperLeagueId": PREV, "season": "2025", "occurredAtMs": T_2025}
        d = _dispose(*_classify(trade, olfc.load_index(store)))
        assert not d["formatAuthority"]["differentAxes"]
        assert d["disposition"] == mtf.TARGET_UNSUPPORTED
        assert d["strongestUnsupportedAxis"] == mtf.FORMAT_TIMING_AXIS

    def test_an_unresolvable_season_is_unknown_never_todays_format(self):
        trade = {"sleeperLeagueId": None, "season": "2019", "occurredAtMs": T_2025}
        fmt, src, ev = _classify(trade, olfc.EMPTY_INDEX)
        assert src == N.FORMAT_SOURCE_SEASON_MISSING
        assert ev["reason"] == "season_league_unresolved"
        assert fmt.teams is None and fmt.demand is None and fmt.scoring is None
        assert _dispose(fmt, src, ev)["disposition"] == mtf.TARGET_UNSUPPORTED


class TestCurrentSeason:
    def test_the_registry_format_never_certifies_anything(self):
        # No season capture yet: the registry's starters / team count /
        # roster size are undated config, so even a trade long after the
        # scoring card was fetched is capped.
        trade = {"sleeperLeagueId": CUR, "season": "2026", "occurredAtMs": T_NOW + HOUR}
        fmt, src, ev = _classify(trade, olfc.EMPTY_INDEX)
        assert src == N.FORMAT_SOURCE_REGISTRY_UNPROVEN
        assert ev["timing"] == N.TIMING_REGISTRY_UNDATED and ev["exactAtTradeTime"] is False
        d = _dispose(fmt, src, ev)
        assert not d["formatAuthority"]["differentAxes"]
        assert d["disposition"] == mtf.TARGET_UNSUPPORTED
        assert d["formatTimingCap"] == mtf.TIMING_CAP_UNPROVEN

    def test_the_retired_registry_label_fails_closed(self):
        fmt = _target()
        d = _dispose(fmt, N.FORMAT_SOURCE_REGISTRY, None)
        assert d["disposition"] == mtf.TARGET_UNSUPPORTED

    def test_a_season_capture_before_the_trade_is_unconfirmed_until_rechecked(self, store):
        _refresh(store, at_ms=T_NOW)
        trade = {"sleeperLeagueId": CUR, "season": "2026", "occurredAtMs": T_NOW + HOUR}
        fmt, src, ev = _classify(trade, olfc.load_index(store))
        assert src == N.FORMAT_SOURCE_SEASON_LEAGUE and ev["exactAtTradeTime"] is False
        d = _dispose(fmt, src, ev)
        assert d["formatTimingCap"] == mtf.TIMING_CAP_UNCONFIRMED_AFTER_TRADE
        # The next timer run re-fetches the in-season league and sees the
        # SAME payload: the trade is now bracketed.
        _refresh(store, at_ms=T_NOW + 6 * HOUR)
        fmt, src, ev = _classify(trade, olfc.load_index(store))
        assert ev["exactAtTradeTime"] is True
        assert ev["confirmationAfterTrade"] == lfc.CONFIRMED
        assert _dispose(fmt, src, ev)["disposition"] == mtf.NATIVE_COMPARABLE

    def test_a_changed_hash_after_the_trade_is_capped(self, store):
        _refresh(store, at_ms=T_NOW)
        changed = dict(LEAGUES)
        changed[CUR] = {**LEAGUES[CUR], "total_rosters": 14}
        _refresh(store, at_ms=T_NOW + DAY, http=FakeSleeper(changed))
        trade = {"sleeperLeagueId": CUR, "season": "2026", "occurredAtMs": T_NOW + HOUR}
        fmt, src, ev = _classify(trade, olfc.load_index(store))
        assert fmt.teams == 12, "the capture in force at the trade supplies the axes"
        assert ev["confirmationAfterTrade"] == lfc.CONFIRMATION_CHANGED
        assert _dispose(fmt, src, ev)["formatTimingCap"] == mtf.TIMING_CAP_CHANGED_AFTER_TRADE

    def test_a_trade_before_the_season_capture_is_capped(self, store):
        _refresh(store, at_ms=T_NOW)
        trade = {"sleeperLeagueId": CUR, "season": "2026", "occurredAtMs": T_NOW - DAY}
        fmt, src, ev = _classify(trade, olfc.load_index(store))
        assert src == N.FORMAT_SOURCE_SEASON_LEAGUE_POST_TRADE
        assert _dispose(fmt, src, ev)["formatTimingCap"] == mtf.TIMING_CAP_POST_TRADE

    def test_an_undated_trade_is_time_unknown(self):
        trade = {"sleeperLeagueId": CUR, "season": "2026", "occurredAtMs": None}
        fmt, src, ev = _classify(trade, olfc.EMPTY_INDEX)
        assert _dispose(fmt, src, ev)["formatTimingCap"] == mtf.TIMING_CAP_TIME_UNKNOWN


# ── undated legacy snapshots ───────────────────────────────────────────────


class TestUndatedLegacySnapshot:
    def test_an_undated_snapshot_before_the_trade_is_still_capped(self):
        payload = lfc.capture_payload(LEAGUES[CUR])
        cap = {
            "captureId": 7,
            "leagueId": CUR,
            "season": "2026",
            "capturedMs": T_NOW,
            "capturedAt": lfc._iso(T_NOW),
            "captureSource": lfc.SOURCE_LEGACY_SNAPSHOT_TIME_UNKNOWN,
            "payload": payload,
        }
        cap["payloadSha256"] = lfc.payload_sha256(payload)
        seen = [
            {"season": "2026", "payloadSha256": cap["payloadSha256"], "observedMs": T_NOW + 2 * DAY}
        ]
        chosen, timing, conf = lfc.bracketed_capture([cap], seen, T_NOW + DAY, season="2026")
        assert timing == lfc.TIMING_AT_OR_BEFORE, "nearest-prior selection is unchanged"
        ev = lfc.evidence_dict(chosen, timing, conf)
        assert ev["exactAtTradeTime"] is True, "even bracketed..."
        fmt = mtf.format_from_sleeper_league(payload)
        obs = {"formatSource": N.FORMAT_SOURCE_CAPTURE_FULL, "formatEvidence": ev}
        d = mtf.disposition(fmt, _target(), observation=obs)
        assert not d["formatAuthority"]["differentAxes"]
        assert d["disposition"] == mtf.TARGET_UNSUPPORTED
        assert d["formatTimingCap"] == mtf.TIMING_CAP_UNDATED_SNAPSHOT

    def test_a_dated_legacy_snapshot_is_not_affected(self):
        ev = {
            "timing": lfc.TIMING_AT_OR_BEFORE,
            "exactAtTradeTime": True,
            "confirmationAfterTrade": lfc.CONFIRMED,
            "captureSource": lfc.SOURCE_LEGACY_SNAPSHOT,
        }
        assert mtf.format_timing_cap({"formatEvidence": ev}) is None


# ── end to end through the acquisition store ───────────────────────────────


@pytest.fixture
def acq(tmp_path):
    store_mod._reset_setup_cache_for_tests()
    yield tmp_path / "retention" / "acquisition.sqlite"
    store_mod._reset_setup_cache_for_tests()


def _ingest(acq, tx_id, *, lid, season, ts):
    tx = {
        "transaction_id": tx_id,
        "type": "trade",
        "status": "complete",
        "leg": 3,
        "status_updated": ts,
        "adds": {"1001": 1, "1002": 2},
        "drops": {"1001": 2, "1002": 1},
        "draft_picks": [],
    }
    store_mod.write_events(
        events_from_transaction(tx, league_key=KEY, sleeper_league_id=lid, season=season),
        path=acq,
    )


def test_own_league_lane_uses_each_trades_own_season(acq, store, monkeypatch):
    _refresh(store, at_ms=T_NOW)
    _refresh(store, at_ms=T_NOW + 2 * DAY)  # the re-fetch that brackets t-2026
    _ingest(acq, "t-2025", lid=PREV, season="2025", ts=T_2025)
    _ingest(acq, "t-2026", lid=CUR, season="2026", ts=T_NOW + DAY)

    class _Cfg:
        key = KEY
        sleeper_league_id = CUR

    from src.api import league_registry as reg
    from src.trade import market_trade_ledger

    monkeypatch.setattr(reg, "get_league_by_key", lambda k: _Cfg() if k == KEY else None)
    # The ledger row's legacy format summary reads the registry too; it is not
    # what this test is about.
    monkeypatch.setattr(market_trade_ledger, "_format_metadata", lambda key: {})
    rows, status = N.own_league_observations(
        league_keys=[KEY], acquisition_path=acq, ctx=ctx(), own_league_format_path=store
    )
    assert status["available"] is True, status
    by_tx = {r["hostTxId"]: r for r in rows}
    assert set(by_tx) == {"t-2025", "t-2026"}
    assert by_tx["t-2025"]["_format"].teams == 10
    assert by_tx["t-2025"]["formatSource"] == N.FORMAT_SOURCE_SEASON_LEAGUE_POST_TRADE
    assert by_tx["t-2026"]["_format"].teams == 12
    assert by_tx["t-2026"]["formatSource"] == N.FORMAT_SOURCE_SEASON_LEAGUE
    assert status["seasonFormats"]["tradesByFormatSource"] == {
        N.FORMAT_SOURCE_SEASON_LEAGUE: 1,
        N.FORMAT_SOURCE_SEASON_LEAGUE_POST_TRADE: 1,
    }
    native = [
        tx
        for tx, r in by_tx.items()
        if mtf.disposition(r["_format"], _target(), observation=r)["disposition"]
        == mtf.NATIVE_COMPARABLE
    ]
    assert native == ["t-2026"]


# ── evidence only ──────────────────────────────────────────────────────────


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
    return out


def test_own_league_format_capture_cannot_reach_a_served_value():
    mod = REPO / "src/trade/own_league_format_capture.py"
    src = mod.read_text(encoding="utf-8")
    for forbidden in ("src.api.data_contract", "src.canonical", "src.bdvm"):
        assert not any(i.startswith(forbidden) for i in _imports(mod)), forbidden
    assert "rankDerivedValue" not in src
    for value_path in ("src/api/data_contract.py", "server.py"):
        assert not any("own_league_format_capture" in i for i in _imports(REPO / value_path))
    targets = set(re.findall(r"INSERT(?:\s+OR\s+IGNORE)?\s+INTO\s+(\w+)", src, re.I))
    assert targets and targets <= set(olfc.WRITE_TABLES), targets


# ── the timer pass: shared 429 stop, its own budget ────────────────────────


def _crawl_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "crawl_sharp_transactions_for_test", REPO / "scripts/crawl_sharp_transactions.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Cfg2:
    def __init__(self, key):
        self.key = key
        self.sleeper_league_id = f"SYN-{key}"


class _Spy:
    def __init__(self, results):
        self.results = list(results)
        self.calls: list[tuple[str, int]] = []

    def __call__(self, key, *, root_league_id, sleep_s, max_fetches):
        self.calls.append((key, max_fetches))
        res = olfc.OwnLeagueFormatRefresh(league_key=key, root_league_id=root_league_id)
        res.leagues_fetched, res.stopped_reason = self.results.pop(0)
        return res


class TestTimerPass:
    def test_skipped_when_the_sharp_format_pass_hit_a_429(self):
        spy = _Spy([])
        out = _crawl_script()._capture_own_league_formats(
            budget=24, sharp_stopped_reason="rate_limited", configs=[_Cfg2("a")], refresh=spy
        )
        assert out["skipped"] == "sharp_format_pass_rate_limited"
        assert spy.calls == [], "no own-league request after a shared-IP 429"

    def test_a_429_inside_stops_the_remaining_leagues(self):
        spy = _Spy([(1, "rate_limited")])
        out = _crawl_script()._capture_own_league_formats(
            budget=24, configs=[_Cfg2("a"), _Cfg2("b")], refresh=spy
        )
        assert [c[0] for c in spy.calls] == ["a"]
        assert out["stoppedReason"] == "rate_limited"
        assert out["leagues"][1] == {"leagueKey": "b", "skipped": "rate_limited"}

    def test_its_own_budget_is_shared_across_leagues(self):
        spy = _Spy([(3, "budget_exhausted")])
        out = _crawl_script()._capture_own_league_formats(
            budget=3, configs=[_Cfg2("a"), _Cfg2("b")], refresh=spy
        )
        assert spy.calls == [("a", 3)]
        assert out["callsUsed"] == 3
        assert out["leagues"][1]["skipped"] == "own_league_format_budget_exhausted"

    def test_other_sharp_stops_do_not_skip_it(self):
        spy = _Spy([(1, None)])
        out = _crawl_script()._capture_own_league_formats(
            budget=24,
            sharp_stopped_reason="consecutive_fetch_failures",
            configs=[_Cfg2("a")],
            refresh=spy,
        )
        assert spy.calls == [("a", 24)] and out["callsUsed"] == 1
