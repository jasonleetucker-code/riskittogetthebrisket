"""``/api/draft-capital`` must not serve the proprietary rookie board.

The endpoint is deliberately on the public API allowlist: the public
/league page's draft-capital tab reads it for team names, pick ownership
and pick dollar values — all of it already visible on Sleeper.

What was NOT public-safe is what got stapled onto every pick.
``_our_rookie_pool()`` reads ``latest_contract_data['playersArray']``
ordered by ``rankDerivedValue`` — the same field the public-league
payload guard blocklists outright — and the endpoint copied its fields
onto each pick.  An anonymous ``curl`` therefore returned the full
ordered top-72 rookie board with per-rookie derived dollars.

Only the private /draft page consumes those fields
(frontend/app/draft/page.jsx), so redacting them for anonymous callers
costs no functionality.

``ROOKIE_FIELDS`` below is the ORIGINAL five, kept deliberately as a
regression floor rather than being grown to match
``_DRAFT_CAPITAL_PRIVATE_PICK_FIELDS`` — that tuple has since gained
``rookieBoardValue`` (PR #655) and ``rookieDispersionCV`` /
``rookieSingleSource``, each pinned by membership in its own test beside
the change that added it.  Coupling this file to the live tuple would
make it assert only that the code agrees with itself.

These tests pin both halves of the fix:
  * anonymous responses carry none of the five fields;
  * authenticated responses still carry them — including immediately
    after an anonymous request, which is the cache-poisoning regression
    the redact-on-a-copy design exists to prevent.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import server

ROOKIE_FIELDS = (
    "rookieName",
    "rookiePos",
    "rookieKtcValue",
    "rookieKtcDollar",
    "rookieIdpDollar",
)


def _fake_payload():
    """A draft-capital payload shaped like the real one, rookie fields filled."""
    return {
        "picks": [
            {
                "pick": "1.01",
                "round": 1,
                "overallPick": 1,
                "dollarValue": 62.0,
                "currentOwner": "Team A",
                "rookieName": "Some Rookie",
                "rookiePos": "WR",
                "rookieKtcValue": 62.0,
                "rookieKtcDollar": 58.5,
                "rookieIdpDollar": 60.0,
            },
            {
                "pick": "1.02",
                "round": 1,
                "overallPick": 2,
                "dollarValue": 55.0,
                "currentOwner": "Team B",
                "rookieName": "Another Rookie",
                "rookiePos": "RB",
                "rookieKtcValue": 55.0,
                "rookieKtcDollar": 51.0,
                "rookieIdpDollar": 53.5,
            },
        ],
        "teams": [{"name": "Team A", "total": 120}],
        "totalBudget": 1200,
    }


# ── The redactor itself ──────────────────────────────────────────────


def test_redactor_strips_every_rookie_field():
    out = server._redact_draft_capital_for_public(_fake_payload())
    for pick in out["picks"]:
        for field in ROOKIE_FIELDS:
            assert field not in pick, f"{field} survived redaction"


def test_redactor_keeps_the_public_pick_data():
    out = server._redact_draft_capital_for_public(_fake_payload())
    assert [p["pick"] for p in out["picks"]] == ["1.01", "1.02"]
    assert [p["dollarValue"] for p in out["picks"]] == [62.0, 55.0]
    assert [p["currentOwner"] for p in out["picks"]] == ["Team A", "Team B"]
    assert out["teams"] == [{"name": "Team A", "total": 120}]
    assert out["totalBudget"] == 1200
    assert out["rookieBoardRedacted"] is True


def test_redactor_does_not_mutate_its_input():
    """The cached object is shared across sessions — redaction must copy.

    Mutating in place would strip the rookie board from the cache and
    break the authenticated /draft page for the rest of the TTL.
    """
    original = _fake_payload()
    server._redact_draft_capital_for_public(original)
    for pick in original["picks"]:
        for field in ROOKIE_FIELDS:
            assert field in pick, f"{field} was stripped from the caller's object"


@pytest.mark.parametrize("payload", [None, {}, {"picks": None}, {"picks": "nope"}, []])
def test_redactor_tolerates_unexpected_shapes(payload):
    """A 503/error body must pass through rather than raising."""
    server._redact_draft_capital_for_public(payload)


# ── The endpoint ─────────────────────────────────────────────────────


class _FakeLeague:
    """Minimal stand-in for a registry league config.

    The test environment loads no league registry, so the real resolver
    returns ``no_leagues_configured``.  Only ``key`` is read on the path
    under test.
    """

    key = "test_league"


@pytest.fixture
def client(monkeypatch):
    """A started client whose draft-capital cache holds a known payload.

    The cache must be seeded INSIDE the lifespan context — startup
    warmup repopulates/clears it, so seeding beforehand gets discarded
    and the endpoint falls through to the real workbook parse (which is
    environment-dependent: with no contract loaded the rookie fields
    come back present-but-null, which would make these assertions lie).

    Resolving to the *default* league also keeps the handler off the
    ``data_not_ready`` guard, which only fires on the non-default path.
    """
    league = _FakeLeague()
    monkeypatch.setattr(server, "_resolve_league_for_request", lambda r: league)
    monkeypatch.setattr(server._league_registry, "get_default_league", lambda: league)

    saved = dict(server._DRAFT_CAPITAL_CACHE)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        server._DRAFT_CAPITAL_CACHE[league.key] = (time.time(), _fake_payload())
        yield c
    server._DRAFT_CAPITAL_CACHE.clear()
    server._DRAFT_CAPITAL_CACHE.update(saved)


def test_anonymous_response_has_no_rookie_board(client):
    res = client.get("/api/draft-capital")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("rookieBoardRedacted") is True
    for pick in body["picks"]:
        for field in ROOKIE_FIELDS:
            assert field not in pick, f"{field} leaked to an anonymous caller"
    # The public half of the payload is untouched.
    assert [p["pick"] for p in body["picks"]] == ["1.01", "1.02"]
    assert [p["dollarValue"] for p in body["picks"]] == [62.0, 55.0]


def test_authenticated_response_keeps_the_rookie_board(client, monkeypatch):
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    res = client.get("/api/draft-capital")
    assert res.status_code == 200, res.text
    body = res.json()
    assert "rookieBoardRedacted" not in body
    assert body["picks"][0]["rookieName"] == "Some Rookie"
    assert body["picks"][0]["rookieKtcDollar"] == 58.5


def test_anonymous_request_does_not_poison_the_cache(client, monkeypatch):
    """An anonymous hit must not strip the rookie board for the next authed one.

    This is the regression that an in-place redaction would introduce:
    the cache is keyed by league, not by viewer.
    """
    anon = client.get("/api/draft-capital")
    assert anon.status_code == 200
    assert "rookieName" not in anon.json()["picks"][0]

    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    authed = client.get("/api/draft-capital")
    assert authed.status_code == 200
    assert authed.json()["picks"][0]["rookieName"] == "Some Rookie"
