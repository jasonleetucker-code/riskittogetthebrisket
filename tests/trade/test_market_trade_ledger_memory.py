"""The daily ledger build shares format objects without changing a byte it writes.

``dynasty-market-trade-ledger.service`` (MemoryMax=2G) holds the whole
append-only history in memory, and every observation used to carry its own
copy of its league's format: a fresh ``TradeMarketFormat`` (with the scoring
card), a fresh ``marketFormat`` dict and, per group, a fresh ``comparability``
block -- about half the build's working set, measured with tracemalloc on
synthetic stores.  ``market_trade_format.FormatInterner`` now shares one of
each per distinct format.

Two properties are pinned here:

* EQUIVALENCE -- the persisted ledger (every table, every row) and the report
  JSON are identical to a build whose interner shares nothing (the old
  behaviour, one fresh object per call);
* THE MEMORY PROPERTY, deterministically -- the number of distinct format
  objects, ``marketFormat`` dicts and ``comparability`` blocks is a function
  of the distinct FORMATS, so quadrupling the trades per league leaves it
  unchanged (no flaky byte measurement).

Fixtures are synthetic (``market_trade_fixtures``); no real league or trade.
"""

from __future__ import annotations

import itertools
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from src.intel import ledger
from src.trade import market_trade_archive as A
from src.trade import market_trade_format as F
from src.trade import market_trade_normalize as N
from src.trade import market_trade_report as R
from tests.trade.market_trade_fixtures import KTC_INDEX, ctx, ktc_row, ktc_settings, sleeper_league
from tests.trade.test_market_trade_normalize import _ev, _league_row, confirm_formats

TARGET = F.format_from_sleeper_league(sleeper_league("TGT"))
TRADE_MS = 1_790_866_800_000  # 2026-10-01T15:00Z
POST_TRADE_CAPTURE_MS = 1_791_500_000_000  # after every fixture trade
OFFENSE_POSITIONS = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"] + ["BN"] * 15
SLEEPER_ASSETS = ["1001", "1002", "1003", "1004", "2001", "2002"]
KTC_IDS = [11, 12, 13, 14, 21]
IDP_LINEUP = [
    {"limit": "1-2", "name": "QB"},
    {"limit": "2-4", "name": "RB"},
    {"limit": "3-5", "name": "WR"},
    {"limit": "1-3", "name": "TE"},
    {"limit": "2", "name": "DL"},
]


class _NonSharingInterner(F.FormatInterner):
    """The pre-interning behaviour: a fresh object on every call."""

    def sleeper(self, league, *, captured_at=None, by_content=False):
        return F.format_from_sleeper_league(league, captured_at=captured_at)

    def ktc(self, settings):
        return F.format_from_ktc_settings(settings)

    def as_dict(self, fmt):
        return fmt.to_dict()

    def compare(self, src, tgt):
        return F.compare_formats(src, tgt)


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


def _sleeper_trades(league: str, n: int) -> list[dict[str, Any]]:
    events = []
    for i in range(n):
        tx = f"{league}-T{i}"
        a = SLEEPER_ASSETS[i % len(SLEEPER_ASSETS)]
        b = SLEEPER_ASSETS[(i + 1) % len(SLEEPER_ASSETS)]
        ts = TRADE_MS + i * 60_000
        events += [
            _ev(tx, 1, "add", a, league=league, ts=ts),
            _ev(tx, 2, "drop", a, league=league, ts=ts),
            _ev(tx, 2, "add", b, league=league, ts=ts),
            _ev(tx, 1, "drop", b, league=league, ts=ts),
        ]
        if i % 3 == 0:
            events += [
                _ev(tx, 2, "add", "pick:2027:1", league=league, disc="o3", ts=ts),
                _ev(tx, 1, "drop", "pick:2027:1", league=league, disc="o3", ts=ts),
            ]
    return events


def _seed(env: dict[str, Path], per_league: int) -> None:
    """Four Sharp leagues, one per format path, plus KTC rows that repeat a
    handful of lineups, name those leagues (host upgrades) and duplicate a
    Sleeper trade."""
    from src.sharp import league_format_capture as lfc

    intel = env["intel"]
    off_lg = sleeper_league(
        "L-POST", roster_positions=OFFENSE_POSITIONS, scoring={"rec": 1.0}, teams=10
    )
    # L-BRK: legacy snapshot migrated to the capture table + later re-check
    # (bracketed).  L-NONE: no capture at all (partial format).
    ledger.upsert_leagues(
        [_league_row("L-BRK"), _league_row("L-NONE", captured=False)]
        + [{"league_id": "L-POST", "season": "2026", "total_rosters": 10, "settings_json": "{}"}],
        path=intel,
    )
    confirm_formats(intel, [sleeper_league("L-BRK")])
    conn = ledger.connect(intel)
    try:
        lfc.ensure_schema(conn)
        # L-POST: only a capture taken after every trade (post-trade label).
        lfc.record_capture(conn, off_lg, captured_ms=POST_TRADE_CAPTURE_MS, source="test")
        conn.commit()
    finally:
        conn.close()
    # L-LEG: a legacy settings snapshot the one-shot migration never reached
    # (added after it ran), so it is a read-side candidate only.
    ledger.upsert_leagues([_league_row("L-LEG")], path=intel)
    for league in ("L-BRK", "L-NONE", "L-POST", "L-LEG"):
        ledger.ingest_events(_sleeper_trades(league, per_league), path=intel)

    # Every combination of the KTC format inputs, repeated in proportion to
    # ``per_league``: an interner keyed on too few inputs would merge two of
    # them and change the output, and every fixture size reaches every format.
    combos = list(itertools.product((1, 2), (10, 12), (0, 1), (None, IDP_LINEUP), (False, True)))
    rows = []
    for i in range(len(combos) * max(1, per_league // 6)):
        qbs, teams, tep, lineup, is_2te = combos[i % len(combos)]
        league = ("L-BRK", "L-POST", "M-1", "M-2")[i % 4]
        settings = ktc_settings(league, qbs=qbs, teams=teams, tep=tep, lineup=lineup)
        settings["is2TE"] = is_2te
        one = [KTC_IDS[i % len(KTC_IDS)]]
        two = [KTC_IDS[(i + 2) % len(KTC_IDS)], 902]
        date = ("2026-10-01T00:00:00", "2026-10-03T00:00:00")[i // 4 % 2]
        rows.append(ktc_row(1000 + i, one, two, date=date, settings=settings))
    # The same trade as L-BRK's first Sleeper trade (a cross-source duplicate).
    dup = ktc_row(999, [11], [12, 901], date="2026-10-01T00:00:00", settings=ktc_settings("L-BRK"))
    rows.append(dup)
    index = KTC_INDEX + [{"playerName": "Echo Edge", "playerID": 21, "position": "DL"}]
    fetch = A.FetchRecord(
        fetch_id="f1",
        source_family=N.SOURCE_KTC,
        fetched_at="2026-10-04T12:00:00+00:00",
        outcome="archived",
    )
    A.record_fetch(
        fetch,
        [A.RawObservation(str(r["id"]), r, r["date"][:10]) for r in rows],
        identity_entries=index,
        path=env["archive"],
    )
    # A second revision of every fifth row.
    revised = [dict(r, isUsedInVft=False) for r in rows[::5]]
    fetch2 = A.FetchRecord(
        fetch_id="f2",
        source_family=N.SOURCE_KTC,
        fetched_at="2026-10-05T12:00:00+00:00",
        outcome="archived",
    )
    A.record_fetch(
        fetch2,
        [A.RawObservation(str(r["id"]), r, r["date"][:10]) for r in revised],
        identity_entries=index,
        path=env["archive"],
    )


def _build(env: dict[str, Path]) -> dict[str, Any]:
    return R.build_ledger(
        archive_path=env["archive"],
        intel_ledger_path=env["intel"],
        league_keys=[],
        ctx=ctx(),
        target_format=TARGET,
        lanes=(N.SOURCE_KTC, N.SOURCE_SLEEPER_DISCOVERY),
    )


def _outputs(result: dict[str, Any], root: Path) -> tuple[dict[str, list], str]:
    """What the daily build writes, minus its run-time stamps: every table of
    the persisted ledger and the report body (``scripts/market_trade_ledger``)."""
    path = R.persist_canonical_ledger(
        result["grouping"].groups,
        root=root,
        built_at="2026-11-21T00:00:00+00:00",
        extra_meta={"volume": result["grouping"].volume, "targetLeague": "dynasty_main"},
    )
    conn = sqlite3.connect(path)
    try:
        tables = {
            name: conn.execute(f"SELECT * FROM {name} ORDER BY 1, 2").fetchall()
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        }
        tables["__schema__"] = conn.execute(
            "SELECT sql FROM sqlite_master ORDER BY name"
        ).fetchall()
    finally:
        conn.close()
    report = {
        "coverage": R.coverage_report(result),
        "evaluation": R.evaluation_report(result, contract=None, board_date=None),
    }
    return tables, json.dumps(report, indent=1, default=str)


def test_interned_build_writes_exactly_what_a_non_sharing_build_writes(env, monkeypatch):
    _seed(env, per_league=12)
    shared = _build(env)
    shared_tables, shared_report = _outputs(shared, env["tmp"] / "shared")

    monkeypatch.setattr(F, "FormatInterner", _NonSharingInterner)
    fresh = _build(env)
    fresh_tables, fresh_report = _outputs(fresh, env["tmp"] / "fresh")

    # The fixture reaches every format path the interner touches.
    sources = {o["formatSource"] for o in shared["observations"]}
    assert {
        N.FORMAT_SOURCE_CAPTURE_FULL,
        N.FORMAT_SOURCE_CAPTURE_POST_TRADE,
        N.FORMAT_SOURCE_PARTIAL,
        "ktc_vendor_settings",
    } <= sources
    assert any(o.get("vendorFormat") for o in shared["observations"])  # host upgrades
    assert shared["grouping"].volume["groupsByState"].get("PROBABLE_DUPLICATE")
    assert shared_tables["underlying_trades"] and shared_tables["formats"]

    assert shared_tables == fresh_tables
    assert shared_report == fresh_report
    # The in-memory observations serialize identically too (the census reads them).
    assert json.dumps(
        [{k: v for k, v in o.items() if k != "_format"} for o in shared["observations"]],
        sort_keys=True,
        default=str,
    ) == json.dumps(
        [{k: v for k, v in o.items() if k != "_format"} for o in fresh["observations"]],
        sort_keys=True,
        default=str,
    )
    assert [o["_format"] for o in shared["observations"]] == [
        o["_format"] for o in fresh["observations"]
    ]


def _distinct_shared_objects(result: dict[str, Any]) -> dict[str, int]:
    obs = result["observations"]
    groups = result["grouping"].groups
    return {
        "formats": len({id(o["_format"]) for o in obs}),
        "marketFormat": len({id(o["marketFormat"]) for o in obs}),
        "comparability": len({id(g["comparability"]) for g in groups}),
    }


def test_format_objects_scale_with_formats_not_observations(env, tmp_path, monkeypatch):
    """Quadrupling the trades per league leaves the number of format objects,
    ``marketFormat`` dicts and ``comparability`` blocks unchanged: the build's
    format memory is bounded by the distinct formats in the history."""
    per_league = 6
    _seed(env, per_league=per_league)
    small = _build(env)
    small_counts = _distinct_shared_objects(small)

    big_env = {
        "tmp": tmp_path / "big",
        "intel": tmp_path / "big" / "intel" / ledger.LEDGER_FILENAME,
        "archive": tmp_path / "big" / "mt" / "archive.sqlite",
    }
    from src.intel import store

    monkeypatch.setattr(store, "DATA_DIR", big_env["intel"].parent)
    ledger.reset_setup_cache()
    A._reset_setup_cache_for_tests()
    ledger.connect(big_env["intel"]).close()
    _seed(big_env, per_league=per_league * 4)
    big = _build(big_env)
    big_counts = _distinct_shared_objects(big)

    assert len(big["observations"]) >= 3 * len(small["observations"])
    assert big_counts == small_counts
    # And far fewer than one per observation / group.
    assert small_counts["formats"] < len(small["observations"]) / 2
    assert big_counts["comparability"] < len(big["grouping"].groups) / 4


# ── the interner itself ──────────────────────────────────────────────────


def test_interner_returns_what_the_constructors_build():
    interner = F.FormatInterner()
    lg = sleeper_league("L-X")
    assert interner.sleeper(lg, captured_at="2026-10-01T00:00:00+00:00") == (
        F.format_from_sleeper_league(lg, captured_at="2026-10-01T00:00:00+00:00")
    )
    s = ktc_settings("L-X")
    k = interner.ktc(s)
    assert k == F.format_from_ktc_settings(s)
    assert interner.as_dict(k) == k.to_dict()
    assert interner.compare(k, TARGET) == F.compare_formats(k, TARGET)
    assert interner.ktc(None) == F.format_from_ktc_settings(None)


def test_interner_shares_by_identity_and_by_exact_content_only():
    interner = F.FormatInterner()
    lg = sleeper_league("L-X")
    a = interner.sleeper(lg, captured_at="t1")
    assert interner.sleeper(lg, captured_at="t1") is a
    # Another object, or another capture time, is another format object.
    assert interner.sleeper(dict(lg), captured_at="t1") is not a
    assert interner.sleeper(lg, captured_at="t2") is not a
    # Content-keyed paths: equal content shares; JSON-distinct values do not.
    assert interner.sleeper({"season": "2026"}, by_content=True) is interner.sleeper(
        {"season": "2026"}, by_content=True
    )
    base = ktc_settings("L-1")
    other_league = ktc_settings("L-2")  # league id / url are not format inputs
    assert interner.ktc(base) is interner.ktc(other_league)
    for value in (1, 1.0, True, "1"):
        assert interner.ktc({**base, "tep": value}).vendor["tepLevel"] == value
        assert type(interner.ktc({**base, "tep": value}).vendor["tepLevel"]) is type(value)
    assert interner.ktc({**base, "tep": 1}) is not interner.ktc({**base, "tep": True})
    assert interner.as_dict(a) is interner.as_dict(a)
    assert interner.compare(a, TARGET) is interner.compare(a, TARGET)


def test_disposition_with_an_interner_equals_without():
    interner = F.FormatInterner()
    for fmt in (
        F.format_from_sleeper_league(sleeper_league("L-X")),
        F.format_from_ktc_settings(ktc_settings("L-X", qbs=1)),
        F.TradeMarketFormat(source=F.SOURCE_UNKNOWN),
    ):
        assert F.disposition(fmt, TARGET, interner=interner) == F.disposition(fmt, TARGET)
