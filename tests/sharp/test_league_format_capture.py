"""Point-in-time league-format captures for Sharp-discovered leagues.

Every Sleeper call is faked.  These pin: append-only dated capture,
nearest-prior selection (a later capture is never exact-at-time), unknown
stays unknown, IDP slot/scoring structure reaching the ledger's format axes,
the catch-up pass's budget and fair order, the zero-extra-request hooks, and
that none of it can reach a served value.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from src.intel import ledger
from src.sharp import league_format_capture as lfc
from src.trade import market_trade_format as mtf
from src.trade import market_trade_normalize as N
from tests.trade.market_trade_fixtures import TARGET_POSITIONS, ctx, sleeper_league

REPO = Path(__file__).resolve().parents[2]
T0 = 1_790_000_000_000  # 2026-09-21
HOUR = 3_600_000
DAY = 24 * HOUR

OFFENSE_ONLY = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "BN", "BN"]


@pytest.fixture()
def db(tmp_path, monkeypatch):
    from src.intel import store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "intel")
    ledger.reset_setup_cache()
    path = tmp_path / "intel" / ledger.LEDGER_FILENAME
    ledger.connect(path).close()
    yield path
    ledger.reset_setup_cache()


def _conn(db):
    conn = ledger.connect(db)
    lfc.ensure_schema(conn)
    return conn


def _rows(db):
    conn = ledger.connect(db)
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM sharp_league_format_captures ORDER BY captured_ms, capture_id"
            ).fetchall()
        ]
    finally:
        conn.close()


def _league(lid="L1", *, status="in_season", **kw):
    lg = sleeper_league(lid, **kw)
    lg["status"] = status
    return lg


# ── append-only, dated ────────────────────────────────────────────────────


class TestAppendOnlyCapture:
    def test_unchanged_reobservation_inserts_nothing_and_a_change_is_a_new_dated_row(self, db):
        conn = _conn(db)
        try:
            a = _league(scoring={"rec": 1.0, "pass_td": 4.0})
            b = _league(scoring={"rec": 0.5, "pass_td": 4.0})  # mid-season change
            assert lfc.record_capture(conn, a, captured_ms=T0, source="t") == "new"
            assert lfc.record_capture(conn, a, captured_ms=T0 + DAY, source="t") == "unchanged"
            assert lfc.record_capture(conn, b, captured_ms=T0 + 2 * DAY, source="t") == "new"
            # Reverting is a change relative to what was in force: a third row,
            # never a rewrite of the first.
            assert lfc.record_capture(conn, a, captured_ms=T0 + 3 * DAY, source="t") == "new"
            conn.commit()
        finally:
            conn.close()
        rows = _rows(db)
        assert [r["captured_ms"] for r in rows] == [T0, T0 + 2 * DAY, T0 + 3 * DAY]
        assert rows[0]["payload_sha256"] == rows[2]["payload_sha256"] != rows[1]["payload_sha256"]
        assert json.loads(rows[1]["payload_json"])["scoring_settings"]["rec"] == 0.5

    def test_status_progression_is_not_a_format_change(self, db):
        conn = _conn(db)
        try:
            lfc.record_capture(conn, _league(status="pre_draft"), captured_ms=T0, source="t")
            out = lfc.record_capture(
                conn, _league(status="in_season"), captured_ms=T0 + DAY, source="t"
            )
            conn.commit()
        finally:
            conn.close()
        assert out == "unchanged"
        rows = _rows(db)
        assert len(rows) == 1 and rows[0]["league_status"] == "pre_draft"

    def test_incomplete_payload_is_never_recorded(self, db):
        conn = _conn(db)
        try:
            lg = _league()
            lg.pop("scoring_settings")
            assert lfc.record_capture(conn, lg, captured_ms=T0, source="t") == "incomplete"
            conn.commit()
        finally:
            conn.close()
        assert _rows(db) == []

    def test_module_never_updates_or_deletes_a_capture_row(self):
        src = (REPO / "src/sharp/league_format_capture.py").read_text(encoding="utf-8")
        assert not re.search(r"UPDATE\s+sharp_league_format_captures", src, re.I)
        assert not re.search(r"DELETE\s+FROM\s+sharp_league_format_captures", src, re.I)
        assert not re.search(r"REPLACE\s+INTO\s+sharp_league_format_captures", src, re.I)


# ── selection: nearest prior; a future capture is never exact ────────────


def _cap(ms, cid, season="2026"):
    return {"capturedMs": ms, "captureId": cid, "season": season, "payload": {}}


class TestCaptureInForce:
    def test_nearest_prior_capture_wins(self):
        caps = [_cap(T0, 1), _cap(T0 + 2 * DAY, 2), _cap(T0 + 5 * DAY, 3)]
        cap, timing = lfc.capture_in_force(caps, T0 + 3 * DAY)
        assert cap["captureId"] == 2 and timing == lfc.TIMING_AT_OR_BEFORE

    def test_a_capture_at_the_exact_trade_instant_is_in_force(self):
        cap, timing = lfc.capture_in_force([_cap(T0, 1)], T0)
        assert cap["captureId"] == 1 and timing == lfc.TIMING_AT_OR_BEFORE

    def test_only_later_captures_give_the_earliest_marked_post_trade(self):
        caps = [_cap(T0 + 5 * DAY, 3), _cap(T0 + 2 * DAY, 2)]
        cap, timing = lfc.capture_in_force(caps, T0)
        assert cap["captureId"] == 2 and timing == lfc.TIMING_POST_TRADE
        assert lfc.evidence_dict(cap, timing)["exactAtTradeTime"] is False

    def test_undated_trade_is_never_exact(self):
        cap, timing = lfc.capture_in_force([_cap(T0, 1)], None)
        assert timing == lfc.TIMING_TRADE_TIME_UNKNOWN

    def test_other_season_capture_is_never_used_and_none_is_unknown(self):
        assert lfc.capture_in_force([_cap(T0, 1, season="2025")], T0 + DAY, season="2026") == (
            None,
            None,
        )
        assert lfc.capture_in_force([], T0) == (None, None)
        assert lfc.evidence_dict(None, None)["timing"] is None


# ── the ledger normalizer consumes them ──────────────────────────────────


def _trade_events(tx, league, ts):
    def ev(rid, action, asset):
        return {
            "eventId": f"{tx}:r{rid}:{action}:{asset}",
            "txId": tx,
            "leagueId": league,
            "ownerId": f"user{rid}",
            "rosterId": str(rid),
            "assetId": asset,
            "assetType": "player",
            "action": action,
            "txType": "trade",
            "ts": ts,
            "week": 4,
        }

    return [
        ev(1, "add", "2001"),
        ev(2, "drop", "2001"),
        ev(2, "add", "1001"),
        ev(1, "drop", "1001"),
    ]


def _league_row(lid):
    return {
        "league_id": lid,
        "season": "2026",
        "total_rosters": 12,
        "settings_json": json.dumps({"type": 2, "bestBall": 1, "sharpEligible": True}),
    }


def _obs(db, tx):
    rows, status = N.sleeper_discovery_observations(ledger_path=db, ctx=ctx())
    return next(o for o in rows if o["hostTxId"] == tx), status


class TestLedgerUsesCaptureInForceAtTrade:
    def test_trade_takes_the_prior_capture_not_the_later_change(self, db):
        ledger.ingest_events(_trade_events("T1", "L1", T0 + 3 * DAY), path=db)
        ledger.upsert_leagues([_league_row("L1")], path=db)
        conn = _conn(db)
        try:
            lfc.record_capture(conn, _league(), captured_ms=T0, source="t")
            lfc.record_capture(
                conn, _league(roster_positions=OFFENSE_ONLY), captured_ms=T0 + 5 * DAY, source="t"
            )
            conn.commit()
        finally:
            conn.close()
        obs, status = _obs(db, "T1")
        assert obs["formatSource"] == "sleeper_league_capture_full"
        assert obs["formatEvidence"]["exactAtTradeTime"] is True
        assert obs["_format"].idp_enabled is True, "the later offense-only change is not used"
        assert status["formatCaptures"]["tradesByFormatSource"] == {
            "sleeper_league_capture_full": 1
        }

    def test_trade_before_every_capture_is_post_trade_never_exact(self, db):
        ledger.ingest_events(_trade_events("T1", "L1", T0), path=db)
        ledger.upsert_leagues([_league_row("L1")], path=db)
        conn = _conn(db)
        try:
            lfc.record_capture(conn, _league(), captured_ms=T0 + DAY, source="t")
            conn.commit()
        finally:
            conn.close()
        obs, _ = _obs(db, "T1")
        assert obs["formatSource"] == "sleeper_league_capture_post_trade"
        assert obs["formatEvidence"]["timing"] == "post_trade_capture"
        assert obs["formatEvidence"]["exactAtTradeTime"] is False
        assert obs["_format"].demand is not None, "used — host facts beat UNKNOWN"

    def test_no_capture_stays_unknown(self, db):
        ledger.ingest_events(_trade_events("T1", "L1", T0), path=db)
        ledger.upsert_leagues([_league_row("L1")], path=db)
        obs, status = _obs(db, "T1")
        fmt = obs["_format"]
        assert obs["formatSource"] == "discovery_row_partial"
        assert fmt.demand is None and fmt.scoring is None and fmt.idp_enabled is None
        assert fmt.superflex is None and fmt.te_scoring_edge() is None
        assert status["formatCaptures"]["state"] == "no_captures"

    def test_reader_never_creates_the_capture_table(self, db):
        ledger.ingest_events(_trade_events("T1", "L1", T0), path=db)
        before = db.stat().st_mtime_ns
        N.sleeper_discovery_observations(ledger_path=db, ctx=ctx())
        assert db.stat().st_mtime_ns == before


class TestIdpFirstClass:
    def test_dl_lb_db_slots_and_idp_scoring_reach_the_format_axes(self, db):
        positions = (
            ["QB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"]
            + ["DL", "DL", "LB", "LB", "LB", "DB", "DB", "IDP_FLEX"]
            + ["BN"] * 20
        )
        scoring = {"rec": 1.0, "pass_td": 4.0, "idp_tkl_solo": 1.5, "idp_sack": 4.0}
        ledger.ingest_events(_trade_events("T1", "LIDP", T0 + DAY), path=db)
        ledger.upsert_leagues([_league_row("LIDP")], path=db)
        conn = _conn(db)
        try:
            lfc.record_capture(
                conn,
                _league("LIDP", roster_positions=positions, scoring=scoring),
                captured_ms=T0,
                source="t",
            )
            conn.commit()
        finally:
            conn.close()
        fmt = _obs(db, "T1")[0]["_format"]
        assert fmt.idp_enabled is True
        assert fmt.idp_starters == 8
        assert fmt.idp_slot_tokens == {"DL": 2, "LB": 3, "DB": 2, "IDP_FLEX": 1}
        assert fmt.demand_for("LB")[0] == 3, "LB-only slots"
        assert fmt.demand_for("DL")[1] == 3, "DL eligible for its own slots + IDP_FLEX"
        assert fmt.superflex is True
        assert fmt.scoring_subset(lambda k: k.startswith("idp_")) == {
            "idp_tkl_solo": 1.5,
            "idp_sack": 4.0,
        }
        target = mtf.format_from_sleeper_league(sleeper_league("TGT"))
        axes = mtf.compare_formats(fmt, target)
        # Every IDP axis is now DECIDED (match or different), none UNKNOWN.
        for axis in ("idpEnabled", "idpStarterDepth", "idpPositionalStructure", "idpScoring"):
            assert axes[axis]["state"] != mtf.UNKNOWN, axis
        assert axes["idpEnabled"]["state"] == mtf.MATCH
        assert axes["idpStarterDepth"]["state"] == mtf.DIFFERENT  # 8 vs the target's 9

    def test_offense_only_capture_is_idp_false_not_unknown(self, db):
        ledger.ingest_events(_trade_events("T1", "LOFF", T0 + DAY), path=db)
        ledger.upsert_leagues([_league_row("LOFF")], path=db)
        conn = _conn(db)
        try:
            lfc.record_capture(
                conn, _league("LOFF", roster_positions=OFFENSE_ONLY), captured_ms=T0, source="t"
            )
            conn.commit()
        finally:
            conn.close()
        fmt = _obs(db, "T1")[0]["_format"]
        assert fmt.idp_enabled is False and fmt.idp_starters == 0


# ── the catch-up pass: budget, order, refresh rules ──────────────────────


class FakeLeagues:
    def __init__(self, leagues=None, fail=()):
        self.leagues = leagues or {}
        self.fail = set(fail)
        self.calls: list[str] = []

    def __call__(self, url):
        self.calls.append(url)
        lid = url.rsplit("/", 1)[-1]
        if lid in self.fail:
            return None
        return self.leagues.get(lid) or _league(lid)


def _seed_trade_leagues(db, ids):
    for i, lid in enumerate(ids):
        ledger.ingest_events(_trade_events(f"T{i}", lid, T0), path=db)


def _pass(db, http, **kw):
    kw.setdefault("budget", 100)
    kw.setdefault("now_ms", T0 + 10 * DAY)
    return lfc.capture_league_formats(
        http_get=http, ledger_path=db, sleep_s=0, sleep_fn=lambda _s: None, **kw
    )


class TestCatchUpPass:
    def test_budget_is_a_hard_cap_and_the_rest_is_pending(self, db):
        _seed_trade_leagues(db, ["L1", "L2", "L3", "L4", "L5"])
        http = FakeLeagues()
        res = _pass(db, http, budget=3)
        assert len(http.calls) == 3 == res.calls_used
        assert res.captures_new == 3 and res.leagues_pending == 2 and res.budget_exhausted
        # The next run reaches the leagues the first one could not — never
        # the same prefix again.
        http2 = FakeLeagues()
        _pass(db, http2, budget=3)
        assert {c.rsplit("/", 1)[-1] for c in http2.calls} == {"L4", "L5"}

    def test_recently_checked_and_complete_leagues_are_not_due(self, db):
        _seed_trade_leagues(db, ["L1", "L2"])
        http = FakeLeagues({"L2": _league("L2", status="complete")})
        _pass(db, http)
        http2 = FakeLeagues()
        # One day later: inside the weekly refresh window, nothing is due.
        assert _pass(db, http2, now_ms=T0 + 11 * DAY).leagues_due == 0
        # Past the window the in-season league is due; the complete one never.
        http3 = FakeLeagues()
        _pass(db, http3, now_ms=T0 + 30 * DAY)
        assert [c.rsplit("/", 1)[-1] for c in http3.calls] == ["L1"]

    def test_a_league_also_captured_by_discovery_is_not_refetched(self, db):
        _seed_trade_leagues(db, ["L1", "L2"])
        conn = _conn(db)
        try:
            lfc.record_capture(conn, _league("L1"), captured_ms=T0 + 9 * DAY, source="d")
            conn.commit()
        finally:
            conn.close()
        http = FakeLeagues()
        _pass(db, http)
        assert [c.rsplit("/", 1)[-1] for c in http.calls] == ["L2"]

    def test_failures_rotate_and_a_run_of_them_stops_the_pass(self, db):
        ids = [f"L{i:02d}" for i in range(15)]
        _seed_trade_leagues(db, ids)
        http = FakeLeagues(fail=ids)
        res = _pass(db, http)
        assert res.stopped_reason == "consecutive_fetch_failures"
        assert res.calls_used == lfc.MAX_CONSECUTIVE_FAILURES
        assert res.captures_new == 0 and _rows(db) == []


# ── zero-extra-request hooks ─────────────────────────────────────────────


def test_roster_crawl_records_the_league_payload_it_already_fetched(tmp_path):
    from tests.sharp.test_roster_collect import fake_http, league_payload, seed_sleeper_membership

    from src.sharp import roster_collect as rc

    path = tmp_path / "ledger.sqlite3"
    seed_sleeper_membership(path)
    calls: list[str] = []
    rc.collect_sleeper_rosters(
        manager_keys=["sleeper:u1"],
        http_get=fake_http(league=league_payload(), calls=calls),
        ledger_path=path,
        sleep_fn=lambda _s: None,
        now_ms=T0,
    )
    league_calls = [c for c in calls if c.endswith("/league/L1")]
    assert len(league_calls) == 1, "no extra /league fetch for the capture"
    conn = ledger.connect(path)
    try:
        row = conn.execute(
            "SELECT capture_source, payload_json FROM sharp_league_format_captures"
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == lfc.SOURCE_ROSTER_CRAWL
    assert json.loads(row[1])["roster_positions"][0] == "QB"


# ── no served-value change ───────────────────────────────────────────────


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
    return out


def test_captures_cannot_reach_a_served_value():
    """The capture is evidence for the trade ledger only.  It imports no value
    owner, the value pipeline imports neither it nor the ledger normalizer, and
    it writes only its own two tables."""
    mod = REPO / "src/sharp/league_format_capture.py"
    src = mod.read_text(encoding="utf-8")
    for forbidden in ("src.api.data_contract", "src.canonical", "src.bdvm"):
        assert not any(i.startswith(forbidden) for i in _imports(mod)), forbidden
    assert "rankDerivedValue" not in src
    for value_path in (
        "src/api/data_contract.py",
        "server.py",
        "src/canonical/player_valuation.py",
    ):
        imports = _imports(REPO / value_path)
        assert not any("league_format_capture" in i for i in imports), value_path
        assert not any("market_trade_normalize" in i for i in imports), value_path
    targets = set(re.findall(r"INSERT(?:\s+OR\s+IGNORE)?\s+INTO\s+(\w+)", src, re.I))
    assert targets and targets <= set(lfc.WRITE_TABLES), targets


def test_target_positions_fixture_is_the_idp_target():
    # Guard for the IDP test above: the comparison target really is IDP.
    assert {"DL", "LB", "DB"} <= set(TARGET_POSITIONS)
