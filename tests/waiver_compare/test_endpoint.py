"""GET /api/public/waiver-compare — public, read-only, isolated."""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import server
from src.api import league_registry
from src.waiver_compare.service import WaiverCompareService
from tests.waiver_compare.test_service import CONTRACT, NFL, ROSTERS, USERS


@pytest.fixture
def client(monkeypatch):
    svc = WaiverCompareService(
        fetch_rosters=lambda _lid: ("ok", ROSTERS),
        fetch_users=lambda _lid: ("ok", USERS),
        fetch_players=lambda: NFL,
    )
    monkeypatch.setattr(server, "_waiver_compare_service", svc)
    monkeypatch.setattr(server, "latest_contract_data", CONTRACT)
    # tests/conftest.py points the registry at a missing file; stand in the
    # one league this page serves.
    cfg = SimpleNamespace(
        key="dynasty_main",
        display_name="Risk It To Get The Brisket",
        sleeper_league_id="L1",
        active=True,
    )
    monkeypatch.setattr(
        league_registry, "get_league_by_key", lambda key: cfg if key == "dynasty_main" else None
    )
    # No ``with``: skip the lifespan (it starts scrape threads).
    return TestClient(server.app)


def test_reachable_without_a_session(client):
    res = client.get("/api/public/waiver-compare")
    assert res.status_code == 200, res.text[:300]
    body = res.json()
    assert body["ok"] is True
    assert body["league"]["key"] == "dynasty_main"
    assert res.headers["x-robots-tag"].startswith("noindex")


def test_payload_carries_no_canonical_value(client):
    text = client.get("/api/public/waiver-compare").text
    assert "rankDerivedValue" not in text
    assert "9999" not in text  # the canonical value planted in the fixture


def test_source_settings_are_the_requested_ones(client):
    sources = client.get("/api/public/waiver-compare").json()["values"]["sources"]
    assert sources["ktc"]["sourceKey"] == "ktcCrowdTradesSfTep"
    assert "Crowd+Trades" in sources["ktc"]["settings"]
    assert "TE++" in sources["ktc"]["settings"]
    assert sources["idptc"]["sourceKey"] == "idpTradeCalc"


# What a UTF-8 middle dot (U+00B7) becomes when its two bytes (C2 B7) are read
# as Latin-1 / cp1252 -- A-circumflex then the dot -- plus the other usual
# double-encoding signatures: U+00C2, U+00C3, U+00E2 U+20AC, U+FFFD.  Written as
# escapes so this file stays ASCII and cannot itself be mangled.
_MOJIBAKE = ("\u00c2", "\u00c3", "\u00e2\u20ac", "\ufffd")


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(key)
            yield from _strings(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            yield from _strings(value)


def test_served_source_labels_carry_a_middle_dot_not_mojibake(client):
    """A client that decodes the UTF-8 body as Latin-1 shows the separator as
    two characters (U+00C2 then the dot).  The served label must hold the
    single U+00B7 itself."""
    sources = client.get("/api/public/waiver-compare").json()["values"]["sources"]
    assert sources["ktc"]["settings"] == "Dynasty \u00b7 Crowd+Trades \u00b7 Superflex \u00b7 TE++"
    assert sources["idptc"]["settings"] == "Superflex \u00b7 TE Premium \u00b7 offense + IDP"
    assert "\u00c2" not in sources["ktc"]["settings"]
    for text in _strings(sources):
        assert not any(marker in text for marker in _MOJIBAKE), text


def test_no_string_in_the_payload_is_double_encoded(client):
    body = client.get("/api/public/waiver-compare").json()
    bad = [t for t in _strings(body) if any(m in t for m in _MOJIBAKE)]
    assert bad == []


def test_body_is_utf8_and_says_so(client):
    """Single-encoded on the wire (C2 B7), and the Content-Type names the
    charset: a bare ``application/json`` is read as ISO-8859-1 by clients such
    as Windows PowerShell 5.1, which is how the mojibake appeared."""
    res = client.get("/api/public/waiver-compare")
    assert b"\xc2\xb7" in res.content  # U+00B7 encoded once
    assert b"\xc3\x82" not in res.content  # not U+00B7 encoded twice
    content_type = res.headers["content-type"].lower().replace(" ", "")
    assert content_type == "application/json;charset=utf-8"
    # A client that honours the declared charset recovers the label intact.
    assert "Dynasty \u00b7 Crowd+Trades" in res.content.decode("utf-8")


def test_only_get_is_served(client):
    assert client.post("/api/public/waiver-compare", json={}).status_code in (401, 405)


def test_contract_is_not_mutated(client):
    before = copy.deepcopy(CONTRACT)
    client.get("/api/public/waiver-compare")
    assert CONTRACT == before
