"""Batch F — sitewide draft-capital integration, receipts, monitoring, cache.

Pins (``docs/draft/DRAFT_VALUATION_WORKSTREAM.md`` → Batch F):

* the upcoming class's dollars come from THE generation reader, not the
  workbook's L2:L73 (which is a parity diagnostic only);
* every class carries the Batch F receipt read from its SERVED record;
* ``rookieKtcValue`` (the /draft pre-draft ladder) is the canonical curve —
  byte-identical to the legacy float function on a full 72-rookie board, and
  MISSING (never stretched, never $0) on anything else;
* the KTC fallback no longer publishes raw KTC values or synthetic
  "Rookie #N" rows under the dollar field;
* ``_parse_csv_rookies`` parses the export's ``"1.0"`` numbers and reads the
  ``Composite`` block below its own header (map §3), refusing a mismatch;
* stale-while-revalidate: a failed dollars generation is answered with the
  last valid board of the SAME year, labelled; another year never answers;
* operator alerts per (league, class) through the existing ops plumbing;
* the auction room snapshots the receipt with its budgets.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from src.api import ops_alerts as oa
from src.api import user_kv
from src.draft.rookie_auction.generation import RECEIPT_FIELDS
from tests.api import test_draft_capital_multi_year as _my
from tests.api.test_draft_capital_multi_year import LEAGUE_ID, LEAGUE_KEY, YEAR, _run


@pytest.fixture
def server_mod(monkeypatch):
    """The Batch E route harness (stubbed 72-pick workbook + Sleeper league)."""
    server = pytest.importorskip("server")
    import src.api.draft_class_evidence as dce

    monkeypatch.setattr(server, "_parse_draft_data", _my._fake_workbook)
    monkeypatch.setattr(server, "_sleeper_league_id_for_draft", lambda _k=None: LEAGUE_ID)
    monkeypatch.setattr(server, "_our_rookie_pool", lambda *_a, **_k: [])
    monkeypatch.setattr(
        server._league_registry,
        "league_key_for_sleeper_id",
        lambda lid: LEAGUE_KEY if lid == LEAGUE_ID else None,
    )
    monkeypatch.setattr(dce, "read_snapshot", lambda _lid: None)
    return server


# --- receipts --------------------------------------------------------------------------


def test_every_class_carries_the_receipt_from_its_served_record(server_mod, monkeypatch):
    result = _run(server_mod, monkeypatch)
    receipt = result["draftValuationGeneration"]
    assert tuple(receipt) == RECEIPT_FIELDS
    assert receipt["targetDraftYear"] == YEAR + 1 == result["season"]
    assert receipt["generationHash"] == result["draftValuation"]["recordChecksum"]
    assert receipt["curveVersion"] == "draft_data_workbook_v1"
    assert receipt["spineYears"] == [2024, 2025, 2026]
    assert receipt["inputMode"] == "frozen_fallback"
    assert receipt["actualInputClassYear"] == 2026
    assert receipt["allocationState"] == "current"
    # The draftValuation block carries the same receipt.
    assert {k: result["draftValuation"][k] for k in RECEIPT_FIELDS} == receipt
    classes = result["budgetPolicy"]["classes"]
    for season in (YEAR + 1, YEAR + 2, YEAR + 3):
        block = classes[str(season)]
        for field in RECEIPT_FIELDS:
            assert field in block, (season, field)
        assert block["targetDraftYear"] == season
        assert block["generationHash"] == block["recordChecksum"]
        assert block["curveVersion"] == "draft_data_workbook_v1"
    assert classes[str(YEAR + 1)]["generationHash"] == receipt["generationHash"]


def test_workbook_column_is_a_diagnostic_and_matches_today(server_mod, monkeypatch):
    result = _run(server_mod, monkeypatch)
    parity = result["workbookParity"]
    assert parity["state"] == "matches" and parity["mismatchCount"] == 0
    assert parity["comparedPicks"] == 72 and parity["authority"] == "diagnostic_only"


# --- the rookie ladder ------------------------------------------------------------------


def _pool(n):
    # Strictly decreasing board values, KTC on every other rookie.
    return [
        {
            "name": f"Rookie {i:02d}",
            "pos": "WR",
            "value": float(7300 - 83 * i),
            "ktcRaw": float(7000 - 90 * i) if i % 2 == 0 else None,
            "idpRaw": None,
            "assetClass": "offense",
            "dispersionCV": None,
            "singleSource": False,
        }
        for i in range(n)
    ]


def test_full_board_ladder_is_identical_to_the_legacy_function(server_mod, monkeypatch):
    pool = _pool(72)
    monkeypatch.setattr(server_mod, "_our_rookie_pool", lambda *_a, **_k: pool)
    legacy = server_mod._rookie_dollars_from_values([r["value"] for r in pool], 1200)
    if len(legacy) != 72:
        pytest.skip("Draft Data workbook unavailable (the legacy function needs its spine)")
    result = _run(server_mod, monkeypatch)
    picks = sorted(result["picks"], key=lambda p: p["overallPick"])
    assert [p["rookieKtcValue"] for p in picks] == legacy
    assert sum(p["rookieKtcValue"] for p in picks) == 1200
    ladder = result["rookieDollarLadder"]
    assert ladder["state"] == "computed" and ladder["targetDraftYear"] == YEAR + 1
    assert ladder["spineYears"] == [2024, 2025, 2026]
    assert ladder["inputSource"] == "canonical_board_rank_derived_value"


def test_short_board_leaves_the_ladder_missing_never_stretched(server_mod, monkeypatch):
    pool = _pool(60)
    monkeypatch.setattr(server_mod, "_our_rookie_pool", lambda *_a, **_k: pool)
    result = _run(server_mod, monkeypatch)
    picks = sorted(result["picks"], key=lambda p: p["overallPick"])
    named = [p for p in picks if p["rookieName"]]
    assert len(named) == 60
    assert all(p["rookieKtcValue"] is None for p in named)
    assert all(p["rookieBoardValue"] is not None for p in named)
    assert result["rookieDollarLadder"]["state"] == "refused"
    assert result["rookieDollarLadder"]["reason"] == "inputs_incomplete:need_72_rookies_have_60"


def _with_ktc_rookies(server, monkeypatch, rookies):
    real = server._parse_draft_data

    def fake():
        out = list(real())
        out[4] = rookies
        return tuple(out)

    monkeypatch.setattr(server, "_parse_draft_data", fake)


def test_ktc_fallback_publishes_dollars_not_raw_ktc_values(server_mod, monkeypatch):
    rookies = [{"name": f"K{i}", "pos": "RB", "value": 6800 - 70 * i} for i in range(80)]
    _with_ktc_rookies(server_mod, monkeypatch, rookies)
    result = _run(server_mod, monkeypatch)
    assert result["rookieSource"] == "ktc_fallback"
    picks = sorted(result["picks"], key=lambda p: p["overallPick"])
    dollars = [p["rookieKtcValue"] for p in picks]
    assert sum(dollars) == 1200 and max(dollars) < 200
    assert result["rookieDollarLadder"]["inputSource"] == "ktc_rookie_values"


def test_ktc_fallback_drops_synthetic_rows_and_refuses_a_short_list(server_mod, monkeypatch):
    real = [{"name": f"K{i}", "pos": "RB", "value": 6800 - 70 * i} for i in range(50)]
    synthetic = [{"name": f"Rookie #{i + 1}", "pos": "—", "value": 100} for i in range(50, 72)]
    _with_ktc_rookies(server_mod, monkeypatch, real + synthetic)
    result = _run(server_mod, monkeypatch)
    picks = sorted(result["picks"], key=lambda p: p["overallPick"])
    assert not any(str(p["rookieName"] or "").startswith("Rookie #") for p in picks)
    assert all(p["rookieKtcValue"] is None for p in picks)
    assert result["rookieDollarLadder"]["state"] == "refused"


# --- _parse_csv_rookies -----------------------------------------------------------------


def _write_csv(path, rows):
    import csv

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for r in rows:
            w.writerow(r)


def _row(rank="", player="", pos="", value=""):
    return [""] * 22 + [rank, player, pos, value] + [""] * 4


def test_parse_csv_rookies_reads_the_real_export():
    server = pytest.importorskip("server")
    if not server.DRAFT_DATA_CSV.exists():
        pytest.skip("draft_data.csv not in this checkout")
    rookies = server._parse_csv_rookies()
    assert len(rookies) == 78
    assert rookies[0] == {"name": "Jeremiyah Love", "pos": "RB", "value": 6817}
    assert rookies[1] == {"name": "Carnell Tate", "pos": "WR", "value": 5203}
    values = [r["value"] for r in rookies]
    assert all(values[i] <= values[i - 1] for i in range(1, len(values)))


def test_parse_csv_rookies_float_cells_and_offset_header(tmp_path, monkeypatch):
    """The two defects: ``int("1.0")`` and the two-row Composite offset."""
    server = pytest.importorskip("server")
    path = tmp_path / "draft.csv"
    _write_csv(
        path,
        [
            _row(value="Composite"),
            _row(value="900.0"),
            _row("Rank", "Player", "Pos", "800.0"),
            _row("1.0", "A", "RB", "700.0"),
            _row("3.0", "B", "WR", ""),
            _row("4.0", "C", "QB", ""),
        ],
    )
    monkeypatch.setattr(server, "DRAFT_DATA_CSV", path)
    assert server._parse_csv_rookies() == [
        {"name": "A", "pos": "RB", "value": 900},
        {"name": "B", "pos": "WR", "value": 800},
        {"name": "C", "pos": "QB", "value": 700},
    ]


def test_parse_csv_rookies_aligned_layout_still_works(tmp_path, monkeypatch):
    server = pytest.importorskip("server")
    path = tmp_path / "draft.csv"
    _write_csv(
        path,
        [
            _row("Rank", "Player", "Pos", "Composite"),
            _row("1", "A", "RB", "50.5"),
            _row("2", "B", "WR", "40"),
        ],
    )
    monkeypatch.setattr(server, "DRAFT_DATA_CSV", path)
    assert server._parse_csv_rookies() == [
        {"name": "A", "pos": "RB", "value": 50.5},
        {"name": "B", "pos": "WR", "value": 40},
    ]


@pytest.mark.parametrize(
    "rows",
    [
        # one more value than names — which name lost its value is unknowable
        [
            _row(value="Composite"),
            _row(value="9"),
            _row("Rank", "Player", "Pos", "8"),
            _row("1", "A", "RB", "7"),
            _row("2", "B", "WR", "6"),
        ],
        # values rise
        [
            _row("Rank", "Player", "Pos", "Composite"),
            _row("1", "A", "RB", "5"),
            _row("2", "B", "WR", "6"),
        ],
        # a non-positive value is not a value
        [
            _row("Rank", "Player", "Pos", "Composite"),
            _row("1", "A", "RB", "5"),
            _row("2", "B", "WR", "0"),
        ],
        # no value header at all
        [_row("Rank", "Player", "Pos", "5"), _row("1", "A", "RB", "4")],
    ],
)
def test_parse_csv_rookies_refuses_rather_than_misattributing(tmp_path, monkeypatch, rows):
    server = pytest.importorskip("server")
    path = tmp_path / "draft.csv"
    _write_csv(path, rows)
    monkeypatch.setattr(server, "DRAFT_DATA_CSV", path)
    assert server._parse_csv_rookies() == []


# --- stale-while-revalidate -------------------------------------------------------------


class _League:
    key = "swr_league"


def _call(server, monkeypatch, result, refresh="1"):
    league = _League()
    monkeypatch.setattr(server, "_resolve_league_for_request", lambda r: league)
    monkeypatch.setattr(server._league_registry, "get_default_league", lambda: league)
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(server, "_fetch_draft_capital", lambda *_a, **_k: dict(result))
    resp = asyncio.run(server.get_draft_capital(object(), refresh=refresh))
    return json.loads(resp.body)


@pytest.fixture
def swr(monkeypatch):
    server = pytest.importorskip("server")
    monkeypatch.setattr(server, "_DRAFT_CAPITAL_CACHE", {})
    monkeypatch.setattr(server, "_DRAFT_CAPITAL_LAST_VALID", {})
    monkeypatch.setattr(server, "_DRAFT_CAPITAL_LOCKS", {})
    return server


GOOD = {"season": 2027, "picks": [{"pick": "1.01", "dollarValue": 135}], "teamTotals": []}


def _failed(year):
    return {
        "error": "draft_dollars_unavailable",
        "unavailableReason": "no_verified_allocation",
        "draftYear": year,
        "draftValuationGeneration": {"targetDraftYear": year, "generationHash": None},
    }


def test_failed_generation_serves_the_same_years_last_valid_board(swr, monkeypatch):
    first = _call(swr, monkeypatch, GOOD)
    assert "staleWhileRevalidate" not in first
    out = _call(swr, monkeypatch, _failed(2027))
    assert "error" not in out
    assert out["picks"] == GOOD["picks"]
    stale = out["staleWhileRevalidate"]
    assert stale["state"] == "serving_last_valid_board" and stale["draftYear"] == 2027
    assert stale["failedError"] == "draft_dollars_unavailable"
    assert stale["failedReason"] == "no_verified_allocation"
    # The stale answer is cached only for the short revalidation window.
    stamp, _cached = swr._DRAFT_CAPITAL_CACHE[_League.key]
    remaining = swr._DRAFT_CAPITAL_TTL_SEC - (time.time() - stamp)
    assert remaining <= swr._DRAFT_CAPITAL_STALE_RETRY_SEC + 1
    # The stored last-valid board itself was never mutated.
    assert "staleWhileRevalidate" not in swr._DRAFT_CAPITAL_LAST_VALID[_League.key][1]


def test_another_years_board_never_answers(swr, monkeypatch):
    _call(swr, monkeypatch, GOOD)
    out = _call(swr, monkeypatch, _failed(2028))
    assert out["error"] == "draft_dollars_unavailable"


def test_too_old_or_non_generation_failures_keep_refusing(swr, monkeypatch):
    _call(swr, monkeypatch, GOOD)
    stamp, good = swr._DRAFT_CAPITAL_LAST_VALID[_League.key]
    swr._DRAFT_CAPITAL_LAST_VALID[_League.key] = (stamp - 7 * 3600, good)
    assert _call(swr, monkeypatch, _failed(2027))["error"] == "draft_dollars_unavailable"
    swr._DRAFT_CAPITAL_LAST_VALID[_League.key] = (time.time(), good)
    ownership = {"error": "pick_ownership_unavailable", "message": "x", "draftYear": 2027}
    assert _call(swr, monkeypatch, ownership)["error"] == "pick_ownership_unavailable"


# --- operator alerts --------------------------------------------------------------------


@pytest.fixture()
def kv(tmp_path):
    path = tmp_path / "kv.sqlite"
    user_kv._SETUP_DONE.clear()
    yield path
    user_kv._SETUP_DONE.clear()


def _row_state(year, state, degraded=True, reason="frozen baseline edited"):
    return {
        "leagueKey": LEAGUE_KEY,
        "draftYear": year,
        "allocationState": state,
        "degraded": degraded,
        "reason": reason,
        "lastValidAt": "2026-10-18T00:00:00+00:00",
    }


def test_draft_valuation_alerts_per_class():
    alerts = oa._check_draft_valuation(
        [
            _row_state(2027, "current", degraded=False),
            _row_state(2028, "last_known_good"),
            _row_state(2029, "unavailable", reason="no_verified_allocation"),
        ]
    )
    by = {a.category: a for a in alerts}
    assert set(by) == {f"draft_valuation:{LEAGUE_KEY}:2028", f"draft_valuation:{LEAGUE_KEY}:2029"}
    assert by[f"draft_valuation:{LEAGUE_KEY}:2028"].severity == "warning"
    assert by[f"draft_valuation:{LEAGUE_KEY}:2029"].severity == "critical"


def test_draft_valuation_alert_cools_down_and_unknown_is_not_recovery(kv):
    sent = []

    def _send(to, subj, body):
        sent.append((subj, body))
        return True

    rows = [_row_state(2028, "last_known_good")]
    s1 = oa.check_and_alert(draft_valuation=rows, delivery=_send, to_email="a@b.c", kv_path=kv)
    s2 = oa.check_and_alert(draft_valuation=rows, delivery=_send, to_email="a@b.c", kv_path=kv)
    assert s1["fired"] == 1 and s2["fired"] == 0 and len(sent) == 1
    # Not checked this sweep: no false "[RECOVERY]".
    s3 = oa.check_and_alert(draft_valuation=None, delivery=_send, to_email="a@b.c", kv_path=kv)
    assert s3["recovered"] == 0
    # Checked and healthy: the recovery notice fires once.
    s4 = oa.check_and_alert(
        draft_valuation=[_row_state(2028, "current", degraded=False)],
        delivery=_send,
        to_email="a@b.c",
        kv_path=kv,
    )
    assert s4["recovered"] == 1


# --- the auction room -------------------------------------------------------------------


def test_auction_budgets_snapshot_the_generation_receipt():
    from src.auction import sources

    receipt = {k: None for k in RECEIPT_FIELDS} | {"generationHash": "ab" * 32}
    seats = [{"name": "A", "team": "Team A"}]
    dc = {
        "teamTotals": [{"team": "Team A", "auctionDollars": 100}],
        "draftValuationGeneration": receipt,
    }
    _seats, prov = sources.join_budgets(seats, dc)
    assert prov["draftValuationGeneration"] == receipt
    assert prov["staleWhileRevalidate"] is None
