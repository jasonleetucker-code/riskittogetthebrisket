"""TC-08 — the browsable dynasty trade database.

``src.trade.market_trade_database`` filters the canonical underlying-trade
ledger.  Pinned on synthetic ledgers persisted through the ledger owner's
writer (fixtures shared with the TC-07 tests):

* every row passes TC-07 visibility and projection (no second rule set);
* a format filter EXCLUDES unknown values and counts them — unknown is never
  a match;
* the window, paging, shape, source and asset-mix filters;
* an all-unresolved asset filter answers ``no_assets``, never "all trades";
* bad filters raise ``FilterError`` (the route's 400);
* no value is read or computed.
"""

from __future__ import annotations

import ast
import json
from datetime import date
from pathlib import Path

import pytest

from src.trade import market_trade_database as db
from src.trade import market_trade_format as mtf
from src.trade import market_trade_reference as ref
from tests.trade.test_market_trade_reference import (
    KTC_FMT,
    LEAGUE,
    PARTIAL_FMT,
    SECRET_IDS,
    SLEEPER_FMT,
    TODAY,
    _fixture_groups,
    _group,
    _persist,
    _pick,
    _player,
    _privacy,
)

REPO = Path(__file__).resolve().parents[2]

IDP_FMT = mtf.TradeMarketFormat(
    source=mtf.SOURCE_SLEEPER,
    dynasty_state=mtf.DYNASTY,
    teams=10,
    demand={"QB": (1, 1), "RB": (2, 3), "WR": (2, 3), "TE": (1, 2)},
    total_starters=9,
    idp_enabled=True,
    scoring={"rec": 1.0},
)


def _ktc(gid, date_, sides, fmt=KTC_FMT):
    return _group(
        gid,
        date_=date_,
        families=[ref.SOURCE_KTC],
        sides=sides,
        fmt=fmt,
        host="mfl",
        host_league_id="777777777777777777",
    )


def _run(root, filters=None, **kw):
    kw.setdefault("today", TODAY)
    kw.setdefault("privacy", _privacy())
    return db.browse_trades(kw.pop("league", LEAGUE), filters or db.TradeFilters(), root=root, **kw)


@pytest.fixture
def root(tmp_path):
    _persist(
        tmp_path,
        [
            _ktc("utrade:ktc_trade_database:d1", "2026-10-05", [[_player("1")], [_player("2")]]),
            _ktc(
                "utrade:ktc_trade_database:d2",
                "2026-10-04",
                [[_player("3"), _pick(2027, 1, tier="early")], [_player("4")]],
            ),
            _ktc(
                "utrade:ktc_trade_database:d3", "2026-10-03", [[_pick(2027, 2)], [_pick(2028, 1)]]
            ),
            _ktc(
                "utrade:ktc_trade_database:d4",
                "2026-10-02",
                [[_player("5")], [_player("6")]],
                fmt=PARTIAL_FMT,
            ),
            _ktc(
                "utrade:ktc_trade_database:d5",
                "2026-10-01",
                [[_player("7")], [_player("8")]],
                fmt=IDP_FMT,
            ),
            _ktc("utrade:ktc_trade_database:d6", "2026-07-01", [[_player("9")], [_player("10")]]),
            _ktc("utrade:ktc_trade_database:old", "2024-01-01", [[_player("11")], [_player("12")]]),
            _ktc("utrade:ktc_trade_database:undated", None, [[_player("13")], [_player("14")]]),
        ],
    )
    return tmp_path


def _dates(body):
    return [t["occurredDate"] for t in body["trades"]]


def test_no_ledger_is_unavailable(tmp_path):
    body = _run(tmp_path)
    assert body["state"] == "unavailable" and body["trades"] == []


def test_default_browse_is_newest_first_in_the_last_year(root):
    body = _run(root)
    assert body["state"] == "ok"
    assert _dates(body) == [
        "2026-10-05",
        "2026-10-04",
        "2026-10-03",
        "2026-10-02",
        "2026-10-01",
        "2026-07-01",
    ]
    assert body["filters"]["since"] == "2025-10-08"
    assert body["notSupported"]["valueBand"]


def test_window_and_until(root):
    body = _run(root, db.TradeFilters(since="2026-10-02", until="2026-10-04"))
    assert _dates(body) == ["2026-10-04", "2026-10-03", "2026-10-02"]


def test_since_is_clamped_and_noted(root):
    body = _run(root, db.TradeFilters(since="2020-01-01"))
    assert body["filters"]["since"] == "2023-10-09"
    assert body["notes"] == ["since_clamped_to_2023-10-09"]
    assert "2024-01-01" in _dates(body)


def _page(root, cursor, **kw):
    c = cursor or {}
    return _run(root, before_date=c.get("beforeDate"), skip=c.get("skip", 0), **kw)


def test_cursor_paging_walks_every_row_once(root):
    first = _run(root, limit=2)
    assert _dates(first) == ["2026-10-05", "2026-10-04"] and first["hasMore"] is True
    assert first["nextCursor"] == {"beforeDate": "2026-10-03", "skip": 0}
    second = _page(root, first["nextCursor"], limit=2)
    assert _dates(second) == ["2026-10-03", "2026-10-02"]
    third = _page(root, second["nextCursor"], limit=2)
    assert _dates(third) == ["2026-10-01", "2026-07-01"]
    assert third["hasMore"] is False and third["nextCursor"] is None


def test_cursor_skips_within_a_shared_date(tmp_path):
    same_day = [
        _ktc(f"utrade:ktc_trade_database:s{i}", "2026-10-05", [[_player(str(i))], [_player("x")]])
        for i in range(5)
    ]
    _persist(tmp_path, same_day)
    seen = []
    cursor = None
    for _ in range(5):
        body = _page(tmp_path, cursor, limit=2)
        seen += [t["sides"][0][0]["canonicalId"] for t in body["trades"]]
        cursor = body["nextCursor"]
        if cursor is None:
            break
    assert len(seen) == 5 and len(set(seen)) == 5


def test_paging_continues_past_the_scan_bound(root, monkeypatch):
    monkeypatch.setattr(db, "MAX_SCAN", 2)
    seen = []
    cursor = None
    for _ in range(10):
        body = _page(root, cursor, limit=5)
        seen += _dates(body)
        cursor = body["nextCursor"]
        if body["scanCapped"]:
            assert body["hasMore"] is True and cursor is not None
        if cursor is None:
            break
    assert seen == [
        "2026-10-05",
        "2026-10-04",
        "2026-10-03",
        "2026-10-02",
        "2026-10-01",
        "2026-07-01",
    ]


def test_until_only_is_anchored_on_until(root):
    body = _run(root, db.TradeFilters(until="2026-07-15"))
    assert body["state"] == "ok"
    assert body["filters"]["since"] == "2025-07-15"
    assert _dates(body) == ["2026-07-01"]


def test_format_filter_excludes_unknown_and_counts_it(root):
    body = _run(root, db.TradeFilters(teams=12))
    # d4 (PARTIAL_FMT, 10 teams) and d5 (10 teams) are mismatches; KTC rows are 12.
    assert "2026-10-02" not in _dates(body) and "2026-10-01" not in _dates(body)
    body = _run(root, db.TradeFilters(idp=True))
    assert _dates(body) == ["2026-10-01"]
    # KTC rows and the partial row do not state IDP: excluded AND counted.
    assert body["excludedUnknown"]["idp"] >= 1


def test_superflex_unknown_is_not_a_match(root):
    body = _run(root, db.TradeFilters(superflex=False))
    assert "2026-10-02" not in _dates(body)  # partial: superflex unknown
    assert body["excludedUnknown"].get("superflex", 0) >= 1


def test_ktc_tep_level_is_the_vendors_own_setting(root):
    body = _run(root, db.TradeFilters(ktc_tep_level=2))
    assert body["trades"]
    for t in body["trades"]:
        assert t["formatTags"]["ktcTepLevel"] == 2
    # Non-KTC-format rows never carry a vendor level: NOT APPLICABLE, which is
    # counted apart from unknown.
    assert body["excludedNotApplicable"].get("ktcTepLevel") == 2
    assert "ktcTepLevel" not in body["excludedUnknown"]


def test_shape_and_asset_mix(root):
    assert _dates(_run(root, db.TradeFilters(shape=db.parse_shape("1x2")))) == ["2026-10-04"]
    assert _dates(_run(root, db.TradeFilters(asset_mix="picks"))) == ["2026-10-03"]
    assert _dates(_run(root, db.TradeFilters(asset_mix="mixed"))) == ["2026-10-04"]


def test_asset_filter_uses_tc07_identity(root):
    body = _run(root, db.TradeFilters(pick_names=["2027 Early 1st"]))
    assert _dates(body) == ["2026-10-04"]
    body = _run(root, db.TradeFilters(player_ids=["1"], until="2026-10-04"))
    assert body["trades"] == []


def test_all_unresolved_asset_filter_is_no_assets_not_everything(root):
    body = _run(root, db.TradeFilters(pick_names=["not a pick"]))
    assert body["state"] == "no_assets" and body["reason"] == "asset_filter_unresolved"
    assert body["trades"] == []


def test_source_filter_and_privacy(tmp_path):
    _persist(tmp_path, _fixture_groups())
    body = _run(tmp_path, db.TradeFilters(source=ref.SOURCE_OWN))
    assert body["trades"] and all(ref.SOURCE_OWN in t["sourceFamilies"] for t in body["trades"])
    everything = _run(tmp_path)
    assert everything["withheld"].get(ref.WITHHELD_UNKNOWN_FAMILY) == 1
    text = json.dumps(everything)
    for secret in SECRET_IDS:
        assert secret not in text
    assert "utrade:" not in text


@pytest.mark.parametrize(
    "filters",
    [
        db.TradeFilters(since="yesterday"),
        db.TradeFilters(since="2026-10-05", until="2026-10-01"),
        db.TradeFilters(source="espn"),
        db.TradeFilters(asset_mix="faab"),
        db.TradeFilters(ktc_tep_level=7),
        db.TradeFilters(teams=0),
        db.TradeFilters(until="2026-13-01"),
        db.TradeFilters(until="2020-01-01"),
    ],
)
def test_bad_filters_raise(root, filters):
    with pytest.raises(db.FilterError):
        _run(root, filters)


@pytest.mark.parametrize("raw", ["2", "axb", "0x1", "1x99"])
def test_bad_shape(raw):
    with pytest.raises(db.FilterError):
        db.parse_shape(raw)


def test_parse_shape_orders_largest_first():
    assert db.parse_shape("1x2") == (2, 1)
    assert db.parse_shape("") is None


def test_window_reader_is_newest_first_and_excludes_undated(root):
    from src.trade import market_trade_report as report

    conn = report.open_canonical_ledger(root)
    try:
        rows = list(report.read_ledger_window(conn, since_date="2000-01-01"))
    finally:
        conn.close()
    dates = [r["occurredDate"] for r, _ in rows]
    assert None not in dates
    assert dates == sorted(dates, reverse=True)


def test_module_reads_no_value():
    tree = ast.parse((REPO / "src/trade/market_trade_database.py").read_text(encoding="utf-8"))
    strings = {
        n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    assert "rankDerivedValue" not in strings and "targetPriceAuthority" not in strings


def test_sleeper_fmt_fixture_is_dynasty():
    # Guard the shared fixture this suite leans on.
    assert SLEEPER_FMT.dynasty_state == mtf.DYNASTY
    assert date.fromisoformat("2026-10-08") == TODAY
