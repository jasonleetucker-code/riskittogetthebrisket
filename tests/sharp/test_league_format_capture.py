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

    def test_module_never_updates_a_capture_row_and_deletes_only_in_retention(self):
        src = (REPO / "src/sharp/league_format_capture.py").read_text(encoding="utf-8")
        assert not re.search(r"UPDATE\s+sharp_league_format_captures", src, re.I)
        assert not re.search(r"REPLACE\s+INTO\s+sharp_league_format_captures", src, re.I)
        # The ONE delete is the retention pass; nothing else may remove a row.
        tree = ast.parse(src)
        deleting = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and re.search(
                r"DELETE\s+FROM\s+sharp_league_format_captures",
                ast.get_source_segment(src, node) or "",
                re.I,
            )
        }
        assert deleting == {"prune_captures"}, deleting


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


# ── the bracket: exact needs a later same-hash observation ───────────────


def _c(ms, sha, cid=1, season="2026"):
    return {"capturedMs": ms, "captureId": cid, "season": season, "payloadSha256": sha}


def _o(ms, sha, season="2026"):
    return {"observedMs": ms, "payloadSha256": sha, "season": season}


class TestBracket:
    def test_capture_before_and_same_hash_check_after_is_confirmed(self):
        caps = [_c(T0, "A")]
        cap, timing, conf = lfc.bracketed_capture(caps, [_o(T0 + 2 * DAY, "A")], T0 + DAY)
        assert timing == lfc.TIMING_AT_OR_BEFORE and conf["state"] == lfc.CONFIRMED
        ev = lfc.evidence_dict(cap, timing, conf)
        assert ev["exactAtTradeTime"] is True and ev["confirmedAt"] == lfc._iso(T0 + 2 * DAY)

    def test_a_changed_hash_after_the_trade_is_not_exact(self):
        caps = [_c(T0, "A", 1), _c(T0 + 2 * DAY, "B", 2)]
        # Even a later re-observation of A (a revert) does not rescue it: the
        # first thing seen after the trade was B.
        cap, timing, conf = lfc.bracketed_capture(caps, [_o(T0 + 3 * DAY, "A")], T0 + DAY)
        assert cap["captureId"] == 1, "the in-force capture still supplies the axes"
        assert conf["state"] == lfc.CONFIRMATION_CHANGED
        assert lfc.evidence_dict(cap, timing, conf)["exactAtTradeTime"] is False

    def test_no_later_check_is_unconfirmed(self):
        cap, timing, conf = lfc.bracketed_capture([_c(T0, "A")], [_o(T0 - HOUR, "A")], T0 + DAY)
        assert conf["state"] == lfc.CONFIRMATION_MISSING
        ev = lfc.evidence_dict(cap, timing, conf)
        assert ev["exactAtTradeTime"] is False
        assert ev["confirmationAfterTrade"] == lfc.CONFIRMATION_MISSING

    def test_evidence_without_a_confirmation_is_never_exact(self):
        cap, timing = lfc.capture_in_force([_c(T0, "A")], T0 + DAY)
        assert lfc.evidence_dict(cap, timing)["exactAtTradeTime"] is False

    def test_a_tie_at_one_instant_fails_closed(self):
        caps = [_c(T0, "A", 1), _c(T0 + 2 * DAY, "B", 2)]
        conf = lfc.confirm_after_trade(
            caps[0], T0 + DAY, captures=caps, observations=[_o(T0 + 2 * DAY, "A")]
        )
        assert conf["state"] == lfc.CONFIRMATION_CHANGED

    def test_another_seasons_observation_never_confirms(self):
        conf = lfc.confirm_after_trade(
            _c(T0, "A"),
            T0 + DAY,
            observations=[_o(T0 + 2 * DAY, "A", season="2025")],
            season="2026",
        )
        assert conf["state"] == lfc.CONFIRMATION_MISSING

    def test_a_window_needs_a_confirmation_at_or_after_its_end(self):
        conf = lfc.confirm_after_trade(
            _c(T0, "A"), T0 + DAY, T0 + 3 * DAY, observations=[_o(T0 + 2 * DAY, "A")]
        )
        assert conf["state"] == lfc.CONFIRMATION_MISSING
        conf = lfc.confirm_after_trade(
            _c(T0, "A"),
            T0 + DAY,
            T0 + 3 * DAY,
            observations=[_o(T0 + 2 * DAY, "A"), _o(T0 + 3 * DAY, "A")],
        )
        assert conf["state"] == lfc.CONFIRMED


class TestObservationLog:
    def _log(self, db):
        conn = ledger.connect(db)
        try:
            return [
                tuple(r)
                for r in conn.execute(
                    "SELECT observed_ms, payload_sha256 FROM sharp_league_format_observations "
                    "ORDER BY observed_ms"
                ).fetchall()
            ]
        finally:
            conn.close()

    def test_an_unchanged_reobservation_logs_its_hash_append_only_and_throttled(self, db):
        conn = _conn(db)
        try:
            lfc.record_capture(conn, _league(), captured_ms=T0, source="t")
            # Inside the throttle window of the capture itself: not logged.
            lfc.record_capture(conn, _league(), captured_ms=T0 + 60_000, source="t")
            lfc.record_capture(conn, _league(), captured_ms=T0 + DAY, source="t")
            lfc.record_capture(conn, _league(), captured_ms=T0 + DAY + 60_000, source="t")
            lfc.record_capture(conn, _league(), captured_ms=T0 + 2 * DAY, source="t")
            conn.commit()
        finally:
            conn.close()
        sha = _rows(db)[0]["payload_sha256"]
        assert self._log(db) == [(T0 + DAY, sha), (T0 + 2 * DAY, sha)]

    def test_module_never_updates_an_observation_row(self):
        src = (REPO / "src/sharp/league_format_capture.py").read_text(encoding="utf-8")
        assert not re.search(r"UPDATE\s+sharp_league_format_observations", src, re.I)
        assert not re.search(r"REPLACE\s+INTO\s+sharp_league_format_observations", src, re.I)

    def test_compaction_keeps_each_runs_latest_observation_and_every_verdict(self, db):
        ledger.ingest_events(_trade_events("T1", "L1", T0 + DAY), path=db)
        conn = _conn(db)
        try:
            a, b = _league(), _league(roster_positions=OFFENSE_ONLY)
            lfc.record_capture(conn, a, captured_ms=T0, source="t")
            for k in (2, 3, 4):
                lfc.record_capture(conn, a, captured_ms=T0 + k * DAY, source="t")
            lfc.record_capture(conn, b, captured_ms=T0 + 5 * DAY, source="t")
            for k in (6, 7):
                lfc.record_capture(conn, b, captured_ms=T0 + k * DAY, source="t")
            conn.commit()
            caps = lfc.load_capture_index(conn)["L1"]
            before = lfc.load_observation_index(conn)["L1"]
            verdicts = {
                t: lfc.bracketed_capture(caps, before, t)[2]["state"]
                for t in (T0 + DAY, T0 + int(3.5 * DAY), T0 + int(4.5 * DAY), T0 + int(5.5 * DAY))
            }
            removed = lfc.prune_observations(conn, cutoff_ms=T0)
            conn.commit()
            after = lfc.load_observation_index(conn)["L1"]
        finally:
            conn.close()
        assert removed == 3
        assert [o["observedMs"] for o in after] == [T0 + 4 * DAY, T0 + 7 * DAY]
        assert {
            t: lfc.bracketed_capture(caps, after, t)[2]["state"] for t in verdicts
        } == verdicts, "compaction is lossless for the bracket"
        assert verdicts[T0 + int(4.5 * DAY)] == lfc.CONFIRMATION_CHANGED


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
        assert obs["_format"].idp_enabled is True, "the later offense-only change is not used"
        # ...but the format CHANGED after the trade, so the prior capture is
        # not proven at trade time (the bracket): axes kept, exactness not.
        assert obs["formatEvidence"]["exactAtTradeTime"] is False
        assert obs["formatEvidence"]["confirmationAfterTrade"] == lfc.CONFIRMATION_CHANGED
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
    """``fail`` -> transport error, ``missing`` -> league does not exist
    (Sleeper's 200 + null), ``rate_limit`` -> HTTP 429."""

    def __init__(self, leagues=None, fail=(), missing=(), rate_limit=()):
        self.leagues = leagues or {}
        self.fail = set(fail)
        self.missing = set(missing)
        self.rate_limit = set(rate_limit)
        self.calls: list[str] = []

    def __call__(self, url):
        self.calls.append(url)
        lid = url.rsplit("/", 1)[-1]
        if lid in self.rate_limit:
            raise lfc.RateLimited(url)
        if lid in self.fail:
            return lfc.FETCH_ERROR
        if lid in self.missing:
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


# ── review fix 1: a post-trade capture can never be NATIVE_COMPARABLE ────


def _target():
    return mtf.format_from_sleeper_league(sleeper_league("TGT"))


def _group_disposition(obs):
    from src.trade import market_trade_groups as grp

    groups = grp.group_observations([obs]).groups
    assert len(groups) == 1
    g = groups[0]
    return g, mtf.disposition(g["_format"], _target(), observation=g)


class TestFormatTimingCap:
    def _seed(self, db, *, trade_ms, capture_ms, recheck_ms=None, recheck_league=None):
        ledger.ingest_events(_trade_events("T1", "L1", trade_ms), path=db)
        ledger.upsert_leagues([_league_row("L1")], path=db)
        conn = _conn(db)
        try:
            lfc.record_capture(conn, _league(), captured_ms=capture_ms, source="t")
            if recheck_ms is not None:
                lfc.record_capture(
                    conn, recheck_league or _league(), captured_ms=recheck_ms, source="t"
                )
            conn.commit()
        finally:
            conn.close()

    def test_a_bracketed_pre_trade_capture_can_reach_native_comparable(self, db):
        # Capture before, a re-check after that saw the SAME payload.
        self._seed(db, trade_ms=T0 + DAY, capture_ms=T0, recheck_ms=T0 + 2 * DAY)
        g, d = _group_disposition(_obs(db, "T1")[0])
        assert g["formatEvidence"]["exactAtTradeTime"] is True, "evidence travels with the group"
        assert g["formatEvidence"]["confirmationAfterTrade"] == lfc.CONFIRMED
        assert d["disposition"] == mtf.NATIVE_COMPARABLE
        assert d["formatTimingCap"] is None

    def test_a_pre_trade_capture_with_no_later_check_is_unconfirmed(self, db):
        # However recent the capture, nothing has looked at the league since
        # the trade: the settings could have changed in between.
        self._seed(db, trade_ms=T0 + DAY, capture_ms=T0)
        g, d = _group_disposition(_obs(db, "T1")[0])
        assert g["formatEvidence"]["confirmationAfterTrade"] == lfc.CONFIRMATION_MISSING
        assert d["disposition"] == mtf.TARGET_UNSUPPORTED
        assert d["formatTimingCap"] == mtf.TIMING_CAP_UNCONFIRMED_AFTER_TRADE
        assert d["formatTimingCap"] == "format_unconfirmed_after_trade"

    def test_a_changed_hash_after_the_trade_is_capped_but_keeps_the_in_force_axes(self, db):
        self._seed(
            db,
            trade_ms=T0 + DAY,
            capture_ms=T0,
            recheck_ms=T0 + 2 * DAY,
            recheck_league=_league(roster_positions=OFFENSE_ONLY),
        )
        obs = _obs(db, "T1")[0]
        assert obs["_format"].idp_enabled is True, "axes from the capture in force"
        g, d = _group_disposition(obs)
        assert d["formatTimingCap"] == mtf.TIMING_CAP_CHANGED_AFTER_TRADE
        assert d["disposition"] == mtf.TARGET_UNSUPPORTED

    def test_a_post_trade_capture_is_capped_with_the_reason_recorded(self, db):
        # Identical format, every axis MATCHES — only the timing differs.
        self._seed(db, trade_ms=T0, capture_ms=T0 + DAY)
        g, d = _group_disposition(_obs(db, "T1")[0])
        assert not d["formatAuthority"]["differentAxes"]
        assert not d["formatAuthority"]["unknownAxes"]
        assert d["disposition"] == mtf.TARGET_UNSUPPORTED
        assert d["formatTimingCap"] == mtf.TIMING_CAP_POST_TRADE == "format_capture_post_trade"
        assert d["formatAuthority"]["formatTimingCap"] == "format_capture_post_trade"
        assert d["strongestUnsupportedAxis"] == mtf.FORMAT_TIMING_AXIS

    @pytest.mark.parametrize(
        "evidence, source, reason",
        [
            (
                {"timing": "post_trade_capture", "exactAtTradeTime": False},
                None,
                "format_capture_post_trade",
            ),
            (
                {"timing": "trade_time_unknown", "exactAtTradeTime": False},
                None,
                "format_time_unknown",
            ),
            # A label claiming exactness without the flag is not proof.
            ({"timing": "at_or_before_trade"}, None, "format_unconfirmed_after_trade"),
            # Nor is the flag without the bracket's confirmation.
            (
                {"timing": "at_or_before_trade", "exactAtTradeTime": True},
                None,
                "format_unconfirmed_after_trade",
            ),
            (
                {
                    "timing": "at_or_before_trade",
                    "exactAtTradeTime": False,
                    "confirmationAfterTrade": "changed_after_trade",
                },
                None,
                "format_changed_after_trade",
            ),
            # A capture-sourced format with NO dated evidence fails closed.
            (None, "sleeper_league_capture_full", "format_capture_timing_unproven"),
            (None, "host_capture_via_discovery", "format_capture_timing_unproven"),
        ],
    )
    def test_no_unproven_timing_ever_reaches_native(self, evidence, source, reason):
        fmt = mtf.format_from_sleeper_league(sleeper_league("SRC"))
        obs = {"formatEvidence": evidence, "formatSource": source}
        d = mtf.disposition(fmt, _target(), observation=obs)
        assert d["disposition"] == mtf.TARGET_UNSUPPORTED
        assert d["formatTimingCap"] == reason

    def test_own_league_registry_format_without_evidence_fails_closed(self):
        # The own-league registry format used to carry no formatEvidence and
        # was applied to EVERY past season uncapped.  It is now dated like any
        # capture (tests/trade/test_own_league_season_format.py), so a row
        # missing that evidence can no longer certify a native match.
        fmt = mtf.format_from_sleeper_league(sleeper_league("SRC"))
        obs = {"formatSource": "registry_and_scoring_card"}
        d = mtf.disposition(fmt, _target(), observation=obs)
        assert d["disposition"] == mtf.TARGET_UNSUPPORTED
        assert d["formatTimingCap"] == "format_capture_timing_unproven"

    def test_own_league_trade_also_seen_by_sharp_post_trade_stays_native(self, db):
        # The same host trade in both lanes: an own-league member whose format
        # is BRACKETED at the trade (its season capture, confirmed by a later
        # re-fetch) represents the group, so a Sharp member's post-trade
        # capture cannot cap it.
        from src.trade import market_trade_groups as grp

        self._seed(db, trade_ms=T0, capture_ms=T0 + DAY)
        sharp = _obs(db, "T1")[0]
        own = {
            **sharp,
            "observationId": f"{N.SOURCE_OWN_LEAGUE}:dynasty_main:T1",
            "sourceFamily": N.SOURCE_OWN_LEAGUE,
            "formatSource": N.FORMAT_SOURCE_SEASON_LEAGUE,
            "formatEvidence": {
                "basis": N.EVIDENCE_BASIS_SEASON_LEAGUE,
                "timing": lfc.TIMING_AT_OR_BEFORE,
                "exactAtTradeTime": True,
                "confirmationAfterTrade": lfc.CONFIRMED,
                "captureSource": "own_league_season_chain_league_endpoint",
            },
            "_format": _target(),
            "leagueKey": "dynasty_main",
        }
        groups = grp.group_observations([sharp, own]).groups
        assert len(groups) == 1
        g = groups[0]
        assert g["formatSource"] == N.FORMAT_SOURCE_SEASON_LEAGUE
        assert g["formatEvidence"]["exactAtTradeTime"] is True
        d = mtf.disposition(g["_format"], _target(), observation=g)
        assert d["disposition"] == mtf.NATIVE_COMPARABLE

    def test_timing_vocabulary_matches_the_capture_owner(self):
        assert mtf._TIMING_AT_OR_BEFORE == lfc.TIMING_AT_OR_BEFORE
        assert mtf._TIMING_POST_TRADE == lfc.TIMING_POST_TRADE
        assert mtf._TIMING_TRADE_TIME_UNKNOWN == lfc.TIMING_TRADE_TIME_UNKNOWN
        assert mtf._CONFIRMED == lfc.CONFIRMED
        assert mtf._CONFIRMATION_CHANGED == lfc.CONFIRMATION_CHANGED
        assert {
            N.FORMAT_SOURCE_CAPTURE_FULL,
            N.FORMAT_SOURCE_CAPTURE_POST_TRADE,
            N.FORMAT_SOURCE_KTC_HOST_UPGRADE,
            N.FORMAT_SOURCE_SEASON_LEAGUE,
            N.FORMAT_SOURCE_SEASON_LEAGUE_POST_TRADE,
            N.FORMAT_SOURCE_REGISTRY,
            N.FORMAT_SOURCE_REGISTRY_UNPROVEN,
            N.FORMAT_SOURCE_SEASON_MISSING,
        } == set(mtf.CAPTURE_FORMAT_SOURCES)
        assert lfc.SOURCE_LEGACY_SNAPSHOT_TIME_UNKNOWN.endswith(mtf._UNDATED_CAPTURE_SUFFIX)


class TestKtcHostUpgradeTiming:
    def _ktc(self, occurred="2026-09-25"):
        return {
            "observationId": "ktc:1",
            "sourceFamily": N.SOURCE_KTC,
            "host": "sleeper",
            "hostLeagueId": "L1",
            "occurredDate": occurred,
            "_format": mtf.TradeMarketFormat(source=mtf.SOURCE_KTC),
            "formatSource": "ktc_vendor_settings",
        }

    def _cap(self, ms, season="2026"):
        payload = lfc.capture_payload(_league())
        payload["season"] = season
        return {
            "captureId": 1,
            "leagueId": "L1",
            "season": season,
            "payloadSha256": lfc.payload_sha256(payload),
            "capturedMs": ms,
            "capturedAt": lfc._iso(ms),
            "captureSource": "t",
            "payload": payload,
        }

    def _seen(self, cap, ms):
        return {"season": cap["season"], "payloadSha256": cap["payloadSha256"], "observedMs": ms}

    def test_a_later_capture_upgrades_but_is_capped(self):
        obs = self._ktc("2026-09-01")
        N.attach_host_formats([obs], captures={"L1": [self._cap(T0)]})
        assert obs["formatSource"] == N.FORMAT_SOURCE_CAPTURE_POST_TRADE
        d = mtf.disposition(obs["_format"], _target(), observation=obs)
        assert d["disposition"] == mtf.TARGET_UNSUPPORTED
        assert d["formatTimingCap"] == "format_capture_post_trade"

    def test_an_undated_ktc_row_is_time_unknown(self):
        obs = self._ktc(None)
        N.attach_host_formats([obs], captures={"L1": [self._cap(T0)]})
        d = mtf.disposition(obs["_format"], _target(), observation=obs)
        assert d["formatTimingCap"] == "format_time_unknown"

    def test_a_prior_capture_is_exact_only_when_confirmed_past_the_day_window(self):
        cap = self._cap(T0)
        end = N._ktc_conservative_trade_end_ms("2026-12-01")
        # Confirmed INSIDE the day window: the trade could still be later.
        early = self._ktc("2026-12-01")
        N.attach_host_formats(
            [early],
            captures={"L1": [cap]},
            league_seasons={"L1": "2026"},
            format_observations={"L1": [self._seen(cap, end - HOUR)]},
        )
        assert early["formatSource"] == N.FORMAT_SOURCE_KTC_HOST_UPGRADE
        assert early["formatEvidence"]["exactAtTradeTime"] is False
        obs = self._ktc("2026-12-01")
        N.attach_host_formats(
            [obs],
            captures={"L1": [cap]},
            league_seasons={"L1": "2026"},
            format_observations={"L1": [self._seen(cap, end)]},
        )
        assert obs["formatSource"] == N.FORMAT_SOURCE_KTC_HOST_UPGRADE
        assert obs["formatEvidence"]["exactAtTradeTime"] is True
        other = self._ktc("2026-12-01")
        N.attach_host_formats(
            [other], captures={"L1": [self._cap(T0, season="2025")]}, league_seasons={"L1": "2026"}
        )
        assert other["formatSource"] == "ktc_vendor_settings", "another season's capture is unused"


# ── review fix 2: no write lock held across the roster crawl's fetches ──


def test_roster_crawl_holds_no_write_lock_across_network_calls(tmp_path):
    import sqlite3

    from tests.sharp.test_roster_collect import fake_http, league_payload, seed_sleeper_membership

    from src.sharp import roster_collect as rc

    path = tmp_path / "ledger.sqlite3"
    seed_sleeper_membership(path)
    inner = fake_http(league=league_payload())
    locked_at: list[str] = []
    probed: list[str] = []

    def probing_http(url):
        # Another writer must be able to take the lock at every fetch.
        other = sqlite3.connect(str(path), timeout=0)
        try:
            other.execute("BEGIN IMMEDIATE")
            other.rollback()
        except sqlite3.OperationalError:
            locked_at.append(url)
        finally:
            other.close()
        probed.append(url)
        return inner(url)

    rc.collect_sleeper_rosters(
        manager_keys=["sleeper:u1"],
        http_get=probing_http,
        ledger_path=path,
        sleep_fn=lambda _s: None,
        now_ms=T0,
    )
    assert any(u.endswith("/rosters") for u in probed), "the fetch after the capture was probed"
    assert locked_at == [], f"writer lock held during: {locked_at}"
    conn = ledger.connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM sharp_league_format_captures").fetchone()[0] == 1
    finally:
        conn.close()


# ── review fix 3: 429 is not a deleted league ────────────────────────────


class TestRateLimitAndNotFound:
    def test_a_429_stops_the_pass_at_once_and_leaves_the_league_due(self, db):
        _seed_trade_leagues(db, ["L1", "L2", "L3"])
        http = FakeLeagues(rate_limit={"L2"})
        res = _pass(db, http)
        assert res.stopped_reason == "rate_limited"
        assert [c.rsplit("/", 1)[-1] for c in http.calls] == ["L1", "L2"]
        assert res.leagues_pending == 2 and res.fetch_failures == 0
        # L2 was never marked checked: the next pass starts there.
        http2 = FakeLeagues()
        _pass(db, http2, now_ms=T0 + 10 * DAY + HOUR)
        assert [c.rsplit("/", 1)[-1] for c in http2.calls] == ["L2", "L3"]

    def test_deleted_leagues_are_answers_not_failures(self, db):
        ids = [f"L{i:02d}" for i in range(15)]
        _seed_trade_leagues(db, ids)
        res = _pass(db, FakeLeagues(missing=ids))
        assert res.stopped_reason is None, "15 deleted leagues must not trip the failure stop"
        assert res.not_found == 15 and res.fetch_failures == 0
        # Settled until the refresh window — not re-fetched every pass.
        assert _pass(db, FakeLeagues(), now_ms=T0 + 11 * DAY).leagues_due == 0

    def test_classified_client_distinguishes_429_404_null_and_error(self, monkeypatch):
        from src.public_league import sleeper_client as sc

        class Resp:
            def __init__(self, status, body=None, bad=False):
                self.status_code, self._body, self._bad = status, body, bad

            def json(self):
                if self._bad:
                    raise ValueError("bad json")
                return self._body

        answers = {
            "u429": Resp(429),
            "u404": Resp(404),
            "unull": Resp(200, None),
            "u500": Resp(500),
            "ubad": Resp(200, bad=True),
            "uok": Resp(200, {"league_id": "X"}),
        }

        class Session:
            def get(self, url, timeout):
                return answers[url.rsplit("/", 1)[-1]]

        monkeypatch.setattr(sc, "_get_session", lambda: Session())
        sc.reset_request_cache()
        kinds = {k: sc.request_json_classified(f"https://x.test/{k}")[0] for k in answers}
        assert kinds == {
            "u429": sc.FETCH_RATE_LIMITED,
            "u404": sc.FETCH_NOT_FOUND,
            "unull": sc.FETCH_NOT_FOUND,
            "u500": sc.FETCH_ERROR,
            "ubad": sc.FETCH_ERROR,
            "uok": sc.FETCH_OK,
        }
        # The legacy helper other callers rely on is unchanged: None for all non-200.
        sc.reset_request_cache()
        assert sc._request_json("https://x.test/u429") is None
        sc.reset_request_cache()

    def test_default_fetcher_raises_on_429_and_marks_errors(self, monkeypatch):
        from src.public_league import sleeper_client as sc

        monkeypatch.setattr(
            sc, "request_json_classified", lambda url: (sc.FETCH_RATE_LIMITED, None)
        )
        with pytest.raises(lfc.RateLimited):
            lfc._default_http_get("u")
        monkeypatch.setattr(sc, "request_json_classified", lambda url: (sc.FETCH_ERROR, None))
        assert lfc._default_http_get("u") is lfc.FETCH_ERROR
        monkeypatch.setattr(sc, "request_json_classified", lambda url: (sc.FETCH_NOT_FOUND, None))
        assert lfc._default_http_get("u") is None


# ── review fix 4: dynasty-only captures + retention ──────────────────────


class TestDynastyOnlyCaptures:
    @pytest.mark.parametrize(
        "ltype, best_ball, expected",
        [(2, 1, "new"), (2, 0, "new"), (0, 0, "not_dynasty"), (1, 0, "not_dynasty")],
    )
    def test_only_dynasty_payloads_are_stored(self, db, ltype, best_ball, expected):
        conn = _conn(db)
        try:
            lg = _league(ltype=ltype, best_ball=best_ball)
            assert lfc.record_capture(conn, lg, captured_ms=T0, source="t") == expected
            conn.commit()
        finally:
            conn.close()
        assert len(_rows(db)) == (1 if expected == "new" else 0)

    def test_unstated_type_is_kept_for_classification(self, db):
        conn = _conn(db)
        try:
            lg = _league()
            lg["settings"].pop("type")
            assert lfc.record_capture(conn, lg, captured_ms=T0, source="t") == "new"
            conn.commit()
        finally:
            conn.close()

    def test_non_target_dynasty_formats_are_kept(self, db):
        conn = _conn(db)
        try:
            one_qb = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "BN", "BN"]
            assert (
                lfc.record_capture(
                    conn, _league(roster_positions=one_qb), captured_ms=T0, source="t"
                )
                == "new"
            )
            conn.commit()
        finally:
            conn.close()

    def test_a_redraft_league_is_checked_once_then_settled(self, db):
        _seed_trade_leagues(db, ["R1"])
        res = _pass(db, FakeLeagues({"R1": _league("R1", ltype=0)}))
        assert res.not_dynasty == 1 and _rows(db) == []
        assert _pass(db, FakeLeagues(), now_ms=T0 + 11 * DAY).leagues_due == 0


def _check(conn, lid, ms):
    lfc._touch_check(conn, lid, checked_ms=ms, result="unchanged", status="in_season")


class TestCaptureRetention:
    NOW = T0 + 600 * DAY
    OLD = T0  # 600 days before NOW: beyond the 400-day horizon

    def _setup(self, db):
        # LA: a retained trade at NOW-10d; captures at OLD (superseded) and
        # OLD+100d (the one in force for the trade).
        ledger.ingest_events(_trade_events("TA", "LA", self.NOW - 10 * DAY), path=db)
        ledger.upsert_leagues([_league_row("LA")], path=db)
        conn = _conn(db)
        try:
            for lid, ms, rec in (
                ("LA", self.OLD, {"rec": 1.0}),
                ("LA", self.OLD + 100 * DAY, {"rec": 0.5}),
                ("LB", self.OLD, {"rec": 1.0}),  # live league, no trades
                ("LC", self.OLD, {"rec": 1.0}),  # dead league, no trades
                ("LD", self.NOW - DAY, {"rec": 1.0}),  # recent: always kept
            ):
                lfc.record_capture(conn, _league(lid, scoring=rec), captured_ms=ms, source="t")
            _check(conn, "LA", self.NOW - DAY)
            _check(conn, "LB", self.NOW - DAY)
            _check(conn, "LC", self.OLD + DAY)
            conn.commit()
        finally:
            conn.close()

    def test_prune_keeps_what_is_in_force_and_drops_the_rest(self, db):
        self._setup(db)
        conn = ledger.connect(db)
        try:
            removed = lfc.prune_captures(conn, now_ms=self.NOW)
        finally:
            conn.close()
        kept = {(r["league_id"], r["captured_ms"]) for r in _rows(db)}
        assert removed == 2
        assert kept == {
            ("LA", self.OLD + 100 * DAY),  # in force for the retained trade
            ("LB", self.OLD),  # the format in force now for a live league
            ("LD", self.NOW - DAY),
        }
        # The retained trade still reads the same capture after pruning.
        obs, _ = _obs(db, "TA")
        assert obs["formatSource"] == "sleeper_league_capture_full"

    def test_ledger_prune_runs_capture_retention(self, db):
        self._setup(db)
        ledger.prune(now_ms=self.NOW, path=db)
        assert len(_rows(db)) == 3

    def test_prune_on_a_ledger_without_the_table_is_a_noop(self, db):
        conn = ledger.connect(db)
        try:
            assert lfc.prune_captures(conn, now_ms=self.NOW) == 0
            assert not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'sharp_league_format_captures'"
            ).fetchone()
        finally:
            conn.close()


# ── review fix 5: legacy settings snapshots survive re-discovery ────────


def _legacy_settings(captured_at, **mf_overrides):
    payload = lfc.capture_payload(_league())
    mf = {**payload, **mf_overrides}
    if captured_at is not None:
        mf["capturedAt"] = captured_at
    return json.dumps({"type": 2, "bestBall": 1, "marketFormat": mf})


class TestLegacySnapshotMigration:
    def _seed_legacy(self, db, settings_json):
        ledger.upsert_leagues(
            [
                {
                    "league_id": "L1",
                    "season": "2026",
                    "total_rosters": 12,
                    "settings_json": settings_json,
                }
            ],
            path=db,
        )

    def test_snapshot_is_copied_at_its_original_time_and_survives_overwrite(self, db):
        self._seed_legacy(db, _legacy_settings(lfc._iso(T0)))
        ledger.ingest_events(_trade_events("T1", "L1", T0 + DAY), path=db)
        conn = ledger.connect(db)
        try:
            lfc.ensure_schema(conn)
            assert lfc.migrate_legacy_settings_snapshots(conn) is None, "one-shot"
        finally:
            conn.close()
        rows = _rows(db)
        assert [(r["captured_ms"], r["capture_source"]) for r in rows] == [
            (T0, lfc.SOURCE_LEGACY_SNAPSHOT)
        ]
        # Re-discovery overwrites settings_json without marketFormat ...
        self._seed_legacy(db, json.dumps({"type": 2, "bestBall": 1}))
        # ... and the trade still reads the earlier-dated capture.
        obs, _ = _obs(db, "T1")
        assert obs["formatSource"] == "sleeper_league_capture_full"
        assert obs["formatEvidence"]["capturedAt"] == lfc._iso(T0)

    def test_migration_is_idempotent(self, db):
        self._seed_legacy(db, _legacy_settings(lfc._iso(T0)))
        for _ in range(3):
            conn = ledger.connect(db)
            try:
                lfc.ensure_schema(conn)
                conn.execute("DELETE FROM sharp_league_format_migrations")
                conn.commit()
                lfc.migrate_legacy_settings_snapshots(conn)
            finally:
                conn.close()
        assert len(_rows(db)) == 1

    def test_undated_snapshot_is_stored_at_the_migration_bound(self, db):
        self._seed_legacy(db, _legacy_settings(None))
        conn = ledger.connect(db)
        try:
            conn.executescript(lfc._SCHEMA)  # tables only — run the migration by hand
            counts = lfc.migrate_legacy_settings_snapshots(conn, now_ms=T0 + 5 * DAY)
        finally:
            conn.close()
        assert counts["copiedTimeUnknown"] == 1
        rows = _rows(db)
        assert rows[0]["captured_ms"] == T0 + 5 * DAY
        assert rows[0]["capture_source"] == lfc.SOURCE_LEGACY_SNAPSHOT_TIME_UNKNOWN

    def test_discovery_migrates_before_it_overwrites_settings(self, db):
        from tests.sharp.test_discovery import FakeSleeper, seeds, user

        from src.sharp import discovery

        self._seed_legacy(db, _legacy_settings(lfc._iso(T0)))
        lg = _league()
        lg["name"] = "League L1"
        http = FakeSleeper(
            {
                f"{discovery.SLEEPER_BASE}/league/L0/users": [user("u1")],
                f"{discovery.SLEEPER_BASE}/user/u1/leagues/nfl/2026": [lg],
                f"{discovery.SLEEPER_BASE}/league/L1/users": [],
            }
        )
        discovery.discover(http_get=http, seeds=seeds(seed_leagues=["L0"]), ledger_path=db)
        sources = sorted(r["capture_source"] for r in _rows(db))
        assert lfc.SOURCE_LEGACY_SNAPSHOT in sources, sources
