"""End-to-end KTC import regression test.

Exercises the full ingestion path:
    KTC URL  →  POST /api/trade/import-ktc  →  sideOne/sideTwo
              →  each name can be resolved in the frontend's
                 canonical name space (simulated via contract + buildRows
                 semantics — pins that picks don't silently drop).

This is the test we SHOULD have written the first time the KTC
pick bug was reported.  It would have caught it at test time
rather than after a user report.  Pinning it here prevents
regression.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server
from src.trade import ktc_import
from src.canonical import normalization_validator as nv


# The specific URL from the user's original bug report — one pick,
# three players, across two sides.
_BUG_URL = (
    "https://keeptradecut.com/trade-calculator"
    "?var=5&pickVal=0&teamOne=1934|1273|1712&teamTwo=1415"
    "&format=2&isStartup=0&tep=1"
)


def test_ktc_backend_returns_pick_with_valid_canonical_name():
    """Invariant 1: backend's resolve_trade_url returns
    '2027 Mid 4th' (or similar canonical pick name) for KTC ID 1712."""
    try:
        result = ktc_import.resolve_trade_url(_BUG_URL)
    except Exception as exc:
        pytest.skip(f"KTC upstream unreachable: {exc}")
    pick_entries = [
        e for e in (result["sideOne"] + result["sideTwo"])
        if e.get("isPick")
    ]
    assert pick_entries, "Backend dropped the pick from the KTC URL"
    for pe in pick_entries:
        name = pe["name"]
        assert nv.is_valid_pick_name(name), (
            f"KTC pick name {name!r} doesn't match any canonical "
            f"pick shape — will never resolve in rowByName.get()"
        )


def test_ktc_backend_returns_all_four_assets():
    """The URL has 4 assets (3 players + 1 pick).  None should be
    silently dropped."""
    try:
        result = ktc_import.resolve_trade_url(_BUG_URL)
    except Exception as exc:
        pytest.skip(f"KTC upstream unreachable: {exc}")
    total = len(result["sideOne"]) + len(result["sideTwo"])
    unresolved = (
        len(result["unresolved"]["sideOne"])
        + len(result["unresolved"]["sideTwo"])
    )
    assert total + unresolved == 4, (
        f"KTC parsed 4 IDs but returned {total} resolved + "
        f"{unresolved} unresolved — something went missing"
    )


def test_ktc_endpoint_returns_structured_response(monkeypatch):
    """The /api/trade/import-ktc endpoint itself returns the
    structured shape the frontend expects, even on error."""
    # Stub the KTC resolver so the test doesn't depend on KTC being up.
    from src.trade import ktc_import as ki
    monkeypatch.setattr(ki, "resolve_trade_url", lambda _url: {
        "sourceUrl": _url,
        "sideOne": [
            {"ktcId": 1934, "name": "Jeremiyah Love", "position": "RB",
             "team": "", "slug": "", "isPick": False},
            {"ktcId": 1273, "name": "Jameson Williams", "position": "WR",
             "team": "", "slug": "", "isPick": False},
            {"ktcId": 1712, "name": "2027 Mid 4th", "position": "RDP",
             "team": "", "slug": "", "isPick": True},
        ],
        "sideTwo": [
            {"ktcId": 1415, "name": "Jahmyr Gibbs", "position": "RB",
             "team": "", "slug": "", "isPick": False},
        ],
        "unresolved": {"sideOne": [], "sideTwo": []},
    })
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(
        server, "_get_auth_session",
        lambda r: {"username": "testuser"},
    )
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post(
            "/api/trade/import-ktc",
            json={"url": _BUG_URL},
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("ok") is not False
    # Pick shape validated.
    pick = next(e for e in body["sideOne"] if e.get("isPick"))
    assert pick["name"] == "2027 Mid 4th"
    assert nv.is_valid_pick_name(pick["name"])


def test_pick_name_validator_accepts_all_canonical_shapes():
    """Pin the set of pick-name shapes we treat as canonical."""
    valid = [
        "2027 Mid 4th", "2026 Early 1st", "2026 Late 3rd",
        "2026 Pick 1.01", "2027 Pick 2.12",
        "2026 1st Round", "2027 4th Round",
    ]
    invalid = [
        "2027 4th",  # missing tier
        "Mid 2027 4th",  # wrong order
        "2027 Mid Quatro",  # bad round
        "Josh Allen",
        "",
        "2027",
    ]
    for v in valid:
        assert nv.is_valid_pick_name(v), f"should accept: {v!r}"
    for iv in invalid:
        assert not nv.is_valid_pick_name(iv), f"should reject: {iv!r}"
