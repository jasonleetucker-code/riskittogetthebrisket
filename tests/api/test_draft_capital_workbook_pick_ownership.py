"""Default-league workbook path: pick ownership is OBSERVED or the board is refused.

``server._fetch_draft_capital`` (the ``dynasty_main`` workbook path) used to turn
a failed Sleeper ``/traded_picks`` fetch into ``traded = []`` and serve the
workbook's hand-entered ownership columns as if no pick had been traded — the
fourth producer named as a follow-up under CLAUDE.md "League pick OWNERSHIP is
observed or unknown, never assumed".  It now reads the response through
``src.identity.picks.traded_picks_observation`` (a list, even an empty one, is
an observation; anything else is ``None``) and refuses the board on ``None``
exactly as the Sleeper-derived fallback does.

``tests/api/test_draft_capital_all_years.py`` already pins the two basic
refusals (an exception and a non-list body).  This module pins the rest of the
contract:

* the refusal IS the fallback's refusal — equal dicts, one vocabulary from
  ``src.identity.picks`` — and carries no board fields;
* Sleeper failing BEFORE ``/traded_picks`` (rosters) refuses too, rather than
  serving a workbook-only board as current;
* ``[]`` is an observation of no trades and serves the normal board; a list of
  trades moves ownership and the per-team dollars;
* a successful observation is byte-identical to the pre-fail-closed reader (a
  bare ``json.loads``) and gains no refusal keys;
* workbook-only mode (``apply_sleeper_trades=False``) never consults Sleeper's
  ownership and is unaffected;
* the route caches the refusal for its normal 300 s TTL — the same as the
  fallback's refusal, since both take the same non-generation-error branch —
  never answers it with the stale last-valid board, and ``?refresh=1`` retries.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from src.identity import picks as pick_identity
from tests.api import test_draft_capital_fallback as _fallback
from tests.api.test_draft_capital_all_years import (
    LEAGUE_ID,
    LEAGUE_KEY,
    TRADED,
    YEAR,
    _contract,
    _fake_workbook,
    _sleeper,
    _urlopen,
)

EXPECTED_REFUSAL = {
    "error": "pick_ownership_unavailable",
    "message": "Could not fetch traded picks from Sleeper; pick ownership is unknown.",
    "pickOwnershipState": "unavailable",
    "pickOwnershipReason": "traded_picks_fetch_failed",
}

REFUSAL_KEYS = {
    pick_identity.PICK_OWNERSHIP_STATE_FIELD,
    pick_identity.PICK_OWNERSHIP_REASON_FIELD,
    "error",
    "message",
}

# Bob holds Ann's second-round pick in the WORKBOOK class (the upcoming draft).
WORKBOOK_CLASS_TRADE = [{"season": str(YEAR + 1), "round": 2, "roster_id": 1, "owner_id": 2}]


@pytest.fixture
def server_mod(monkeypatch):
    server = pytest.importorskip("server")
    import src.api.draft_class_evidence as dce

    monkeypatch.setattr(server, "_parse_draft_data", _fake_workbook)
    monkeypatch.setattr(server, "_sleeper_league_id_for_draft", lambda _k=None: LEAGUE_ID)
    monkeypatch.setattr(server, "_our_rookie_pool", lambda *_a, **_k: [])
    monkeypatch.setattr(server, "latest_contract_data", _contract())
    monkeypatch.setattr(
        server._league_registry,
        "league_key_for_sleeper_id",
        lambda lid: LEAGUE_KEY if lid == LEAGUE_ID else None,
    )
    monkeypatch.setattr(dce, "read_snapshot", lambda _lid: None)
    monkeypatch.setattr(server, "_DRAFT_CAPITAL_CACHE", {})
    monkeypatch.setattr(server, "_DRAFT_CAPITAL_LAST_VALID", {})
    monkeypatch.setattr(server, "_DRAFT_CAPITAL_LOCKS", {})
    return server


def _sleeper_up(server, monkeypatch, traded=TRADED, **overrides):
    responses = _sleeper(traded)
    responses.update(overrides)
    seen: list[str] = []
    fake = _urlopen(responses)

    def recording(url, *args, **kwargs):
        seen.append(url.full_url if hasattr(url, "full_url") else str(url))
        return fake(url, *args, **kwargs)

    monkeypatch.setattr(server.urllib.request, "urlopen", recording)
    return seen


def _build(server, monkeypatch, traded=TRADED, **kwargs):
    _sleeper_up(server, monkeypatch, traded)
    return server._fetch_draft_capital(**kwargs)


def _canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _owner_of(result, pick_label):
    return next(p for p in result["picks"] if p["pick"] == pick_label)


def _dollars(result):
    return {t["team"]: t["auctionDollars"] for t in result["teamTotals"]}


# --- refusal ---------------------------------------------------------------------------


def test_refusal_is_exactly_the_fallbacks_refusal(server_mod, monkeypatch):
    workbook = _build(server_mod, monkeypatch, traded=OSError("sleeper down"))
    fallback = _fallback._build(monkeypatch, None)
    assert workbook == EXPECTED_REFUSAL
    assert workbook == fallback
    # One vocabulary: every value comes from the pick-identity owner.
    assert workbook["error"] == pick_identity.PICK_OWNERSHIP_UNAVAILABLE_ERROR
    assert workbook[pick_identity.PICK_OWNERSHIP_STATE_FIELD] == (
        pick_identity.PICK_OWNERSHIP_UNAVAILABLE
    )
    assert workbook[pick_identity.PICK_OWNERSHIP_REASON_FIELD] == (
        pick_identity.PICK_OWNERSHIP_REASON_TRADED_PICKS_FETCH_FAILED
    )


@pytest.mark.parametrize("body", [None, {"error": "rate limited"}, "oops", 0])
def test_every_non_list_body_refuses_with_no_board_fields(server_mod, monkeypatch, body):
    result = _build(server_mod, monkeypatch, traded=body)
    assert result == EXPECTED_REFUSAL, body
    assert set(result) == REFUSAL_KEYS


def test_sleeper_failing_before_traded_picks_refuses(server_mod, monkeypatch):
    seen = _sleeper_up(
        server_mod,
        monkeypatch,
        **{f"/league/{LEAGUE_ID}/rosters": OSError("rosters down")},
    )
    result = server_mod._fetch_draft_capital()
    assert result == EXPECTED_REFUSAL
    # Ownership was never observed: /traded_picks was not even reached, and
    # the workbook-only board is not served in its place.
    assert not any(u.endswith("/traded_picks") for u in seen)


# --- success ---------------------------------------------------------------------------


def test_empty_list_is_an_observation_of_no_trades(server_mod, monkeypatch):
    result = _build(server_mod, monkeypatch, traded=[])
    assert "error" not in result
    assert not (set(result) & {pick_identity.PICK_OWNERSHIP_STATE_FIELD, "message"})
    assert result["additionalClassesState"] == "observed"
    # No trades reported: every workbook pick stays with the workbook's owner.
    for p in result["picks"]:
        assert p["isTraded"] is False, p["pick"]
        assert p["currentOwner"] == p["originalOwner"], p["pick"]
    assert sum(_dollars(result).values()) == 1200


def test_observed_trades_move_ownership_and_dollars(server_mod, monkeypatch):
    untraded = _build(server_mod, monkeypatch, traded=[])
    traded = _build(server_mod, monkeypatch, traded=WORKBOOK_CLASS_TRADE)
    assert "error" not in traded
    before, after = _owner_of(untraded, "2.01"), _owner_of(traded, "2.01")
    assert before["currentOwner"] == "Team-Ann" and before["isTraded"] is False
    assert after["currentOwner"] == "Team-Bob" and after["isTraded"] is True
    assert after["originalOwner"] == "Team-Ann"
    moved = after["dollarValue"]
    assert moved > 0
    d0, d1 = _dollars(untraded), _dollars(traded)
    assert d1["Team-Ann"] == d0["Team-Ann"] - moved
    assert d1["Team-Bob"] == d0["Team-Bob"] + moved
    assert sum(d1.values()) == sum(d0.values()) == 1200


@pytest.mark.parametrize("traded", [[], WORKBOOK_CLASS_TRADE, TRADED])
def test_success_is_byte_identical_to_the_pre_fail_closed_reader(server_mod, monkeypatch, traded):
    """Before the fail-closed change the body was read with a bare
    ``json.loads`` and filtered by ``isinstance(traded, list)``.  For every
    observed list the published board is byte-identical."""
    current = _build(server_mod, monkeypatch, traded=traded)
    monkeypatch.setattr(pick_identity, "traded_picks_observation", lambda body: body)
    legacy = _build(server_mod, monkeypatch, traded=traded)
    assert "error" not in current
    assert _canonical(current) == _canonical(legacy)
    # The gate adds nothing to a served board.
    assert not (set(current) & REFUSAL_KEYS)


def test_workbook_only_mode_is_unaffected_by_a_failed_fetch(server_mod, monkeypatch):
    seen = _sleeper_up(server_mod, monkeypatch, traded=OSError("sleeper down"))
    result = server_mod._fetch_draft_capital(apply_sleeper_trades=False)
    assert "error" not in result
    assert not any(u.endswith("/traded_picks") for u in seen)
    assert result["additionalClassesState"] == "not_requested"


# --- route cache -----------------------------------------------------------------------


class _League:
    key = LEAGUE_KEY
    sleeper_league_id = LEAGUE_ID
    roster_settings: dict = {}


def _route(server, monkeypatch, refresh):
    league = _League()
    monkeypatch.setattr(server, "_resolve_league_for_request", lambda _r: league)
    monkeypatch.setattr(server._league_registry, "get_default_league", lambda: league)
    monkeypatch.setattr(server, "_is_authenticated", lambda _r: True)
    resp = asyncio.run(server.get_draft_capital(object(), refresh=refresh))
    return json.loads(resp.body)


def test_route_caches_the_refusal_for_the_full_ttl_and_never_serves_stale(server_mod, monkeypatch):
    real = server_mod._fetch_draft_capital
    builds: list[tuple] = []

    def counting(*args, **kwargs):
        builds.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(server_mod, "_fetch_draft_capital", counting)

    # 1. A valid board is served and remembered as the last valid one.
    _sleeper_up(server_mod, monkeypatch)
    good = _route(server_mod, monkeypatch, refresh="1")
    assert "error" not in good and good["leagueKey"] == LEAGUE_KEY

    # 2. /traded_picks fails: the refusal is served — NOT the last valid board,
    #    because an ownership refusal is not a dollars-generation failure.
    _sleeper_up(server_mod, monkeypatch, traded=OSError("sleeper down"))
    refused = _route(server_mod, monkeypatch, refresh="1")
    assert refused == {**EXPECTED_REFUSAL, "leagueKey": LEAGUE_KEY}
    assert "staleWhileRevalidate" not in refused
    assert pick_identity.PICK_OWNERSHIP_UNAVAILABLE_ERROR not in (
        server_mod._DRAFT_CAPITAL_GENERATION_ERRORS
    )
    # Cached for the normal TTL (the fallback's refusal takes this same branch),
    # not the short stale-revalidation window.
    stamp, cached = server_mod._DRAFT_CAPITAL_CACHE[LEAGUE_KEY]
    assert cached == refused
    assert time.time() - stamp < 5
    assert server_mod._DRAFT_CAPITAL_TTL_SEC == 300
    # The last valid board itself is untouched.
    assert "error" not in server_mod._DRAFT_CAPITAL_LAST_VALID[LEAGUE_KEY][1]
    assert len(builds) == 2

    # 3. Within the TTL the cached refusal answers, even with Sleeper back.
    _sleeper_up(server_mod, monkeypatch)
    again = _route(server_mod, monkeypatch, refresh="")
    assert again == refused
    assert len(builds) == 2

    # 4. ?refresh=1 rebuilds and serves the board again.
    recovered = _route(server_mod, monkeypatch, refresh="1")
    assert "error" not in recovered
    assert len(builds) == 3
