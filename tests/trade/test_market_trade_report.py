"""End-to-end over synthetic lanes: raw -> canonical ledger -> dispositions -> report."""

from __future__ import annotations

import json
import sqlite3

import pytest

from src.intel import ledger
from src.trade import market_trade_archive as A
from src.trade import market_trade_format as F
from src.trade import market_trade_normalize as N
from src.trade import market_trade_report as R
from tests.trade.market_trade_fixtures import KTC_INDEX, ctx, ktc_row, ktc_settings, sleeper_league
from tests.trade.test_market_trade_normalize import (
    _league_row,
    _trade_events,
    confirm_formats,
)

TARGET = F.format_from_sleeper_league(sleeper_league("TGT"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    from src.intel import store

    A._reset_setup_cache_for_tests()
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "intel")
    ledger.reset_setup_cache()
    intel = tmp_path / "intel" / ledger.LEDGER_FILENAME
    ledger.connect(intel).close()
    yield {"tmp": tmp_path, "intel": intel, "archive": tmp_path / "mt" / "archive.sqlite"}
    ledger.reset_setup_cache()
    A._reset_setup_cache_for_tests()


def _seed(env):
    # Sleeper: one IDP trade in a dynasty_main-shaped league (captured format),
    # one trade in an offense-only league.
    ledger.ingest_events(_trade_events("T1", "L-IDP"), path=env["intel"])
    offense_events = [
        e | {"eventId": e["eventId"] + "x", "txId": "T2", "leagueId": "L-OFF"}
        for e in _trade_events("T2", "L-OFF")
        if e["assetId"] != "2001"
    ]
    ledger.ingest_events(offense_events, path=env["intel"])
    idp_row = _league_row("L-IDP")
    off_lg = sleeper_league(
        "L-OFF",
        roster_positions=["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"]
        + ["BN"] * 15,
        scoring={"rec": 1.0, "pass_td": 4.0},
        teams=10,
        best_ball=0,
    )
    off_settings = {
        "type": 2,
        "marketFormat": F.capture_sleeper_league_format(
            off_lg, captured_at="2026-10-01T00:00:00+00:00"
        ),
    }
    ledger.upsert_leagues(
        [
            idp_row,
            {
                "league_id": "L-OFF",
                "season": "2026",
                "total_rosters": 10,
                "settings_json": json.dumps(off_settings),
            },
        ],
        path=env["intel"],
    )
    # A re-check after the trades saw the same payloads: bracketed (exact).
    confirm_formats(env["intel"], [sleeper_league("L-IDP"), off_lg])
    # KTC: the same L-IDP trade (probable duplicate) + an unrelated MFL 1QB trade.
    rows = [
        ktc_row(501, [11], [902, 14]),
        ktc_row(502, [13], [12], settings=ktc_settings("99", platform="mfl", qbs=1)),
    ]
    rows[0]["settings"] = ktc_settings("L-IDP")
    rows[0]["teamOne"]["playerIds"] = ["11", "902"]  # Alpha Receiver + 2027 Mid 1st
    rows[0]["teamTwo"]["playerIds"] = ["edge"]
    f = A.FetchRecord(
        fetch_id="f1",
        source_family=N.SOURCE_KTC,
        fetched_at="2026-10-01T12:00:00+00:00",
        outcome="archived",
    )
    index = KTC_INDEX + [{"playerName": "Echo Edge", "playerID": 21, "position": "DL"}]
    rows[0]["teamTwo"]["playerIds"] = ["21"]
    A.record_fetch(
        f,
        [A.RawObservation(str(r["id"]), r, "2026-10-01") for r in rows],
        identity_entries=index,
        path=env["archive"],
    )


def _build(env, **kw):
    return R.build_ledger(
        archive_path=env["archive"],
        intel_ledger_path=env["intel"],
        league_keys=[],
        ctx=ctx(),
        target_format=TARGET,
        lanes=(N.SOURCE_KTC, N.SOURCE_SLEEPER_DISCOVERY),
        **kw,
    )


def test_end_to_end_counts_dispositions_and_idp_metadata(env):
    _seed(env)
    result = _build(env)
    groups = {g["underlyingTradeId"]: g for g in result["grouping"].groups}

    idp = groups["utrade:sleeper:L-IDP:T1"]
    assert idp["dedupeState"] == "PROBABLE_DUPLICATE", "KTC + Sleeper observation of one trade"
    assert idp["provenance"] == ["KTC_MARKET", "SHARP_DISCOVERY"]
    assert idp["disposition"] == F.NATIVE_COMPARABLE
    # IDP trades preserve scoring + roster-format metadata
    mf = idp["marketFormat"]
    assert mf["idp"]["enabled"] is True and mf["idp"]["slotTokens"] == {"DL": 3, "LB": 3, "DB": 3}
    assert mf["idp"]["scoring"]["idp_sack"] == 2.92

    off = groups["utrade:sleeper:L-OFF:T2"]
    assert off["marketFormat"]["idp"]["enabled"] is False
    assert off["marketFormat"]["idp"]["starters"] == 0
    # The fixture strips the IDP asset, leaving a one-sided trade: a hard
    # topology failure, so TARGET_UNSUPPORTED rather than BROAD_CONTEXT.
    assert off["disposition"] == F.TARGET_UNSUPPORTED
    assert off["dispositionReasons"] == ["invalid_topology:two_team_one_sided"]
    assert off["targetPriceAuthority"] == 0

    # A verified-dynasty (KTC source-level) 1QB trade: BROAD_CONTEXT, mismatch.
    mfl = next(g for g in groups.values() if g["sourceFamilies"] == ["ktc_trade_database"])
    assert mfl["disposition"] == F.BROAD_CONTEXT
    assert mfl["broadContextKind"] == F.BROAD_FORMAT_MISMATCH
    assert mfl["targetPriceAuthority"] == 0
    assert mfl["strongestUnsupportedAxis"] == "qbDemand"
    assert idp["targetPriceAuthority"] == 1 and idp["dispositionReasons"] == []

    cov = R.coverage_report(result)
    assert cov["rawSourceObservations"]["total"] == 4
    assert cov["underlyingTrades"]["underlyingTradesPointEstimate"] == 3
    assert cov["probableCrossSourceGroups"] == 1
    assert cov["sleeperSharpDiscoveryLeagueCount"] == 2
    assert cov["idpLeagueCount"] == 1
    assert cov["idpLeagueTradeCount"] == 1
    assert cov["nativeComparableIdpTrades"] == 1
    assert any("NOT a random sample" in b for b in cov["knownSamplingBiases"])


def test_canonical_ledger_is_separate_from_raw_and_rebuilt_wholesale(env):
    _seed(env)
    result = _build(env)
    root = env["tmp"] / "mt"
    path = R.persist_canonical_ledger(result["grouping"].groups, root=root)
    assert path != env["archive"]
    conn = sqlite3.connect(path)
    try:
        n = conn.execute("SELECT COUNT(*) FROM underlying_trades").fetchone()[0]
        members = conn.execute("SELECT COUNT(*) FROM trade_members").fetchone()[0]
    finally:
        conn.close()
    assert (n, members) == (3, 4)
    # Rebuilding replaces, never appends.
    R.persist_canonical_ledger(result["grouping"].groups, root=root)
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM underlying_trades").fetchone()[0] == 3
    finally:
        conn.close()
    # The raw archive is untouched by a ledger build.
    assert A.coverage(N.SOURCE_KTC, path=env["archive"])["observations"] == 2


def test_killed_runs_temp_files_are_removed_and_a_failed_build_leaves_none(env, monkeypatch):
    import os
    import time

    _seed(env)
    groups = _build(env)["grouping"].groups
    root = env["tmp"] / "mt"
    root.mkdir(parents=True, exist_ok=True)
    stale = root / f".{R.LEDGER_FILENAME}.99999.tmp"
    fresh = root / f".{R.LEDGER_FILENAME}.88888.tmp"
    stale.write_bytes(b"x" * 1024)
    fresh.write_bytes(b"y")
    old = time.time() - R.STALE_TEMP_AGE_SECONDS - 60
    os.utime(stale, (old, old))
    R.persist_canonical_ledger(groups, root=root)
    assert not stale.exists(), "a killed run's leftover is removed on the next build"
    assert fresh.exists(), "a young temp file may be a concurrent manual build"

    # A build that fails mid-write removes its own temp file and leaves the
    # previous ledger in place.
    before = (root / R.LEDGER_FILENAME).read_bytes()

    def boom(*a, **k):
        raise RuntimeError("simulated failure mid-build")

    real = R._write_ledger_db

    def partial_then_boom(tmp, *a, **k):
        tmp.write_bytes(b"partial")
        boom()

    monkeypatch.setattr(R, "_write_ledger_db", partial_then_boom)
    with pytest.raises(RuntimeError):
        R.persist_canonical_ledger(groups, root=root)
    monkeypatch.setattr(R, "_write_ledger_db", real)
    assert not list(root.glob(f".{R.LEDGER_FILENAME}.{os.getpid()}.tmp"))
    assert (root / R.LEDGER_FILENAME).read_bytes() == before


def test_repeat_build_is_deterministic(env):
    _seed(env)
    a = [g["underlyingTradeId"] for g in _build(env)["grouping"].groups]
    b = [g["underlyingTradeId"] for g in _build(env)["grouping"].groups]
    assert a == b
