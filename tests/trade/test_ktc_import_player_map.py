"""KTC trade-URL import: the player-map ladder, error classes and endpoint.

Regression for the 2026-10-13 outage: KTC moved the trade-calculator player
map into ``<script type="application/json" id="ktc-players">`` and every import
returned "Failed to fetch KTC player map.".  The fixtures under
``tests/fixtures/ktc/`` are trimmed captures of the real pages taken that day,
in their real embed forms — no network in this file.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from src.trade import ktc_import as ki
from src.utils import circuit_breaker

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ktc"
_CALC_HTML = (_FIXTURES / "trade_calculator_2026-10-13.html").read_text(encoding="utf-8")
_DB_HTML = (_FIXTURES / "trade_database_2026-10-13.html").read_text(encoding="utf-8")

_URL = (
    "https://keeptradecut.com/trade-calculator"
    "?var=5&pickVal=0&teamOne=1934|1273|1712&teamTwo=1415|2"
    "&format=2&isStartup=0&tep=1"
)


class _Outage(OSError):
    pass


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """Fresh memory cache, fresh breaker, last-good file in tmp."""
    monkeypatch.setattr(ki, "_cache", {"players": None, "fetched_at": 0.0, "index": None})
    monkeypatch.setattr(ki, "_LAST_GOOD_PATH", tmp_path / "ktc" / "last_good.json")
    circuit_breaker.reset_all_for_tests()
    yield
    circuit_breaker.reset_all_for_tests()


def _pages(monkeypatch, *, db=_DB_HTML, calc=_CALC_HTML):
    """Serve fixture HTML per URL; ``None`` means that page is unreachable."""
    calls: list[str] = []

    def fake_fetch(url, timeout):
        calls.append(url)
        html = db if url == ki._KTC_TRADE_DATABASE_URL else calc
        if html is None:
            raise _Outage(f"connection refused: {url}")
        return html

    monkeypatch.setattr(ki, "_fetch_html", fake_fetch)
    return calls


def _names(entries):
    return [e["name"] for e in entries]


def test_full_search_index_resolves_ids_deeper_than_the_value_board(monkeypatch):
    _pages(monkeypatch)
    out = ki.resolve_trade_url(_URL)
    assert _names(out["sideOne"]) == ["Jeremiyah Love", "Jameson Williams", "2027 Mid 4th"]
    # id 2 is on KTC's search index but not its 500-row value board.
    assert _names(out["sideTwo"]) == ["Jahmyr Gibbs", "Taywan Taylor"]
    assert out["unresolved"] == {"sideOne": [], "sideTwo": []}
    pick = out["sideOne"][2]
    assert pick["isPick"] is True and pick["position"] == "RDP"
    assert out["playerMap"]["source"] == "live"
    assert out["playerMap"]["index"] == "trade_database_search_index"


def test_calculator_json_script_embed_is_read_when_the_index_page_is_down(monkeypatch):
    """The exact embed form that broke the import on 2026-10-13."""
    _pages(monkeypatch, db=None)
    out = ki.resolve_trade_url(_URL)
    assert _names(out["sideOne"]) == ["Jeremiyah Love", "Jameson Williams", "2027 Mid 4th"]
    assert _names(out["sideTwo"]) == ["Jahmyr Gibbs"]
    # The value board does not carry id 2 — reported, not dropped.
    assert out["unresolved"] == {"sideOne": [], "sideTwo": [2]}
    assert out["playerMap"]["index"] == "trade_calculator_value_board"


def test_apostrophes_and_initials_survive_resolution(monkeypatch):
    _pages(monkeypatch)
    out = ki.resolve_trade_url(
        "https://keeptradecut.com/trade-calculator?teamOne=1274&teamTwo=1555"
    )
    assert _names(out["sideOne"]) == ["Wan'Dale Robinson"]
    assert _names(out["sideTwo"]) == ["J.J. McCarthy"]


def test_layout_change_is_a_named_error_not_a_generic_fetch_failure(monkeypatch):
    blank = "<html><body><script>var somethingElse = 1;</script></body></html>"
    _pages(monkeypatch, db=blank, calc=blank)
    with pytest.raises(ki.KtcLayoutChanged) as err:
        ki.resolve_trade_url(_URL)
    assert "layout" in err.value.user_message


def test_outage_with_no_saved_copy_is_unreachable(monkeypatch):
    _pages(monkeypatch, db=None, calc=None)
    with pytest.raises(ki.KtcUnreachable):
        ki.resolve_trade_url(_URL)


def test_successful_read_saves_a_copy_that_serves_a_cold_start_outage(monkeypatch):
    _pages(monkeypatch)
    ki.resolve_trade_url(_URL)
    saved = json.loads(ki._LAST_GOOD_PATH.read_text(encoding="utf-8"))
    assert saved["schema"] == "ktc-id-index/v1"
    assert saved["index"] == "trade_database_search_index"

    # Restart (memory cleared) during a KTC outage.
    monkeypatch.setattr(ki, "_cache", {"players": None, "fetched_at": 0.0, "index": None})
    _pages(monkeypatch, db=None, calc=None)
    out = ki.resolve_trade_url(_URL)
    assert _names(out["sideTwo"]) == ["Jahmyr Gibbs", "Taywan Taylor"]
    assert out["playerMap"]["source"] == "last_good"
    assert out["playerMap"]["index"] == "trade_database_search_index"


def test_saved_copy_older_than_the_bound_is_refused(monkeypatch):
    _pages(monkeypatch)
    ki.resolve_trade_url(_URL)
    saved = json.loads(ki._LAST_GOOD_PATH.read_text(encoding="utf-8"))
    too_old = datetime.now(timezone.utc) - timedelta(hours=ki._LAST_GOOD_MAX_AGE_HOURS + 1)
    saved["fetchedAt"] = too_old.isoformat()
    ki._LAST_GOOD_PATH.write_text(json.dumps(saved), encoding="utf-8")

    monkeypatch.setattr(ki, "_cache", {"players": None, "fetched_at": 0.0, "index": None})
    _pages(monkeypatch, db=None, calc=None)
    with pytest.raises(ki.KtcUnreachable):
        ki.resolve_trade_url(_URL)


def test_saved_copy_is_reported_with_its_real_age(monkeypatch):
    _pages(monkeypatch)
    ki.resolve_trade_url(_URL)
    saved = json.loads(ki._LAST_GOOD_PATH.read_text(encoding="utf-8"))
    saved["fetchedAt"] = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    ki._LAST_GOOD_PATH.write_text(json.dumps(saved), encoding="utf-8")

    monkeypatch.setattr(ki, "_cache", {"players": None, "fetched_at": 0.0, "index": None})
    _pages(monkeypatch, db=None, calc=None)
    meta = ki.resolve_trade_url(_URL)["playerMap"]
    assert meta["source"] == "last_good"
    assert 29.9 <= meta["ageHours"] <= 30.1


def test_one_id_claimed_by_two_names_fails_closed(monkeypatch):
    conflicting = (
        "<script>var allPlayerSearchValues = ["
        '{"playerName":"Jahmyr Gibbs","playerID":1415,"position":"RB"},'
        '{"playerName":"Someone Else","playerID":1415,"position":"WR"}];</script>'
    )
    _pages(monkeypatch, db=conflicting)
    with pytest.raises(ki.KtcIdConflict):
        ki.resolve_trade_url(_URL)


def test_memory_cache_avoids_refetching_within_the_ttl(monkeypatch):
    calls = _pages(monkeypatch)
    ki.resolve_trade_url(_URL)
    n = len(calls)
    out = ki.resolve_trade_url(_URL)
    assert len(calls) == n
    assert out["playerMap"]["source"] == "memory"


def test_stale_memory_copy_is_served_with_its_age_when_refresh_fails(monkeypatch):
    _pages(monkeypatch)
    ki.resolve_trade_url(_URL)
    ki._cache["fetched_at"] = time.time() - ki._CACHE_TTL_SECONDS - 7200
    _pages(monkeypatch, db=None, calc=None)
    meta = ki.resolve_trade_url(_URL)["playerMap"]
    assert meta["source"] == "memory"
    assert meta["ageHours"] >= 3.0


def test_repeated_failures_open_the_breaker(monkeypatch):
    _pages(monkeypatch, db=None, calc=None)
    for _ in range(3):
        with pytest.raises(ki.KtcUnreachable):
            ki.resolve_trade_url(_URL)
    with pytest.raises(ki.KtcCircuitOpen):
        ki.resolve_trade_url(_URL)


def test_export_uses_the_same_map(monkeypatch):
    _pages(monkeypatch)
    out = ki.build_ktc_url(["Jahmyr Gibbs", "2027 Mid 4th"], ["Taywan Taylor", "Nobody Real"])
    assert "teamOne=1415|1712" in out["url"]
    assert "teamTwo=2" in out["url"]
    assert out["unresolved"] == {"sideOne": [], "sideTwo": ["Nobody Real"]}


# ── endpoint ──────────────────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda r: {"username": "testuser"})
    with TestClient(server.app) as c:
        yield c


def test_endpoint_success_carries_player_map_provenance(monkeypatch, client):
    _pages(monkeypatch)
    res = client.post("/api/trade/import-ktc", json={"url": _URL})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["playerMap"]["source"] == "live"
    assert len(body["sideOne"]) == 3 and len(body["sideTwo"]) == 2


def test_endpoint_layout_change_says_so(monkeypatch, client):
    blank = "<html></html>"
    _pages(monkeypatch, db=blank, calc=blank)
    res = client.post("/api/trade/import-ktc", json={"url": _URL})
    assert res.status_code == 502
    body = res.json()
    assert body["ok"] is False
    assert body["reason"] == "KtcLayoutChanged"
    assert body["error"] == ki.KtcLayoutChanged.user_message


def test_endpoint_outage_is_503_with_a_retry_message(monkeypatch, client):
    _pages(monkeypatch, db=None, calc=None)
    res = client.post("/api/trade/import-ktc", json={"url": _URL})
    assert res.status_code == 503
    assert res.json()["reason"] == "KtcUnreachable"


def test_endpoint_malformed_url_is_400(monkeypatch, client):
    calls = _pages(monkeypatch)
    res = client.post(
        "/api/trade/import-ktc",
        json={"url": "https://keeptradecut.com/trade-calculator?teamOne=abc"},
    )
    assert res.status_code == 400
    assert "non-integer" in res.json()["error"]
    assert calls == []  # nothing fetched for a URL we cannot parse


def test_endpoint_rejects_non_ktc_url(client):
    res = client.post("/api/trade/import-ktc", json={"url": "https://example.com/?teamOne=1"})
    assert res.status_code == 400


def test_export_endpoint_reports_the_named_error(monkeypatch, client):
    _pages(monkeypatch, db=None, calc=None)
    res = client.post("/api/trade/export-ktc", json={"sideOne": ["Jahmyr Gibbs"]})
    assert res.status_code == 503
    assert res.json()["reason"] == "KtcUnreachable"
