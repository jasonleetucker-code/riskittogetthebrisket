"""``rookieDispersionCV`` / ``rookieSingleSource`` on /api/draft-capital picks.

Why they exist: Perfect Draft's confidence bootstrap draws a per-player value
shock, and until this landed it drew EVERY player from one flat constant.  The
board already knows how much its sources disagreed about each rookie —
``marketDispersionCV``, stamped by the canonical pipeline — but nothing in the
draft data path carried it, so the per-player term the code was written around
was always ``undefined``.

The subtle half is the zero.  The scraper's ``_coeff_var`` returns ``0.0``
whenever it has fewer than two comparable site values, so ``0.0`` means
*dispersion unobserved*, not *the sources agreed*.  On the 2026-08-04 board that
is 27 of the top 72 rookies, and they are exactly the thinnest-covered rows.
Shipping a literal ``0.0`` to the client would have presented the least
trustworthy values on the board as the most certain ones — strictly worse than
the flat constant it replaced.  ``_our_rookie_pool`` therefore normalises
non-positive to ``None``, and the client widens rather than tightens those rows.

These are board internals, so they redact with the rest of the rookie board.
"""

from __future__ import annotations

import server


def _payload():
    return {
        "picks": [
            {
                "pick": "1.01",
                "overallPick": 1,
                "dollarValue": 135.0,
                "currentOwner": "Alpha",
                "rookieName": "Jeremiyah Love",
                "rookiePos": "RB",
                "rookieKtcValue": 135.0,
                "rookieKtcDollar": 130.0,
                "rookieIdpDollar": None,
                "rookieBoardValue": 7587.0,
                "rookieDispersionCV": 0.032514,
                "rookieSingleSource": False,
            }
        ],
        "teamTotals": [{"team": "Alpha", "auctionDollars": 417}],
        "totalBudget": 1200,
    }


def test_they_are_stripped_for_public_callers():
    redacted = server._redact_draft_capital_for_public(_payload())
    pick = redacted["picks"][0]
    assert "rookieDispersionCV" not in pick
    assert "rookieSingleSource" not in pick
    assert redacted.get("rookieBoardRedacted") is True
    # Public Sleeper facts still survive.
    assert pick["dollarValue"] == 135.0
    assert pick["currentOwner"] == "Alpha"


def test_they_are_listed_in_the_private_field_tuple():
    # Pinned by membership, not only behaviour: a field added to the payload
    # but not to this tuple is the exact leak the tuple guards against.
    assert "rookieDispersionCV" in server._DRAFT_CAPITAL_PRIVATE_PICK_FIELDS
    assert "rookieSingleSource" in server._DRAFT_CAPITAL_PRIVATE_PICK_FIELDS


def test_an_authenticated_payload_keeps_them():
    pick = _payload()["picks"][0]
    assert pick["rookieDispersionCV"] == 0.032514
    assert pick["rookieSingleSource"] is False


def _pool_with(monkeypatch, rows):
    monkeypatch.setattr(server, "latest_contract_data", {"playersArray": rows}, raising=False)
    return server._our_rookie_pool(top_n=10)


def _row(name, value, cv, *, single=False):
    return {
        "canonicalName": name,
        "displayName": name,
        "position": "RB",
        "playerId": name.lower().replace(" ", "-"),
        "rookie": True,
        "rankDerivedValue": value,
        "marketDispersionCV": cv,
        "isSingleSource": single,
        "assetClass": "offense",
    }


def test_the_pool_carries_a_measured_dispersion(monkeypatch):
    pool = _pool_with(monkeypatch, [_row("Observed Rookie", 7000.0, 0.0325)])
    assert pool[0]["dispersionCV"] == 0.0325
    assert pool[0]["singleSource"] is False


def test_an_unobservable_dispersion_becomes_none_not_zero(monkeypatch):
    """The load-bearing case.

    A zero CV on the wire is indistinguishable from perfect source agreement,
    and the client's sigma would collapse to zero for precisely the rookies the
    board knows least about.  ``None`` forces the client to decide what an
    unobserved row is worth, which is the only honest place for that decision.
    """
    pool = _pool_with(monkeypatch, [_row("Thin Rookie", 5000.0, 0.0)])
    assert pool[0]["dispersionCV"] is None

    pool = _pool_with(monkeypatch, [_row("Missing Rookie", 5000.0, None)])
    assert pool[0]["dispersionCV"] is None


def test_the_single_source_flag_survives(monkeypatch):
    pool = _pool_with(monkeypatch, [_row("Lonely Rookie", 4000.0, None, single=True)])
    assert pool[0]["singleSource"] is True
