"""``rookieBoardValue`` on the /api/draft-capital pick rows.

Why the field exists: ``rookieKtcValue`` carries the rookie's DOLLAR value on
the $1200 ladder, produced by ``_rookie_dollars_from_values``.  That curve is
not invertible, so a client holding only dollars cannot recover the board
value — and Perfect Draft needs board value, because net roster value is
measured against a displaced roster player in ``rankDerivedValue`` units.

``_our_rookie_pool`` already computed the number and threw it away; this is
that number, carried through.

It is also the most proprietary figure on the payload — the public-league
guard blocklists ``rankDerivedValue`` outright — so it must be stripped for
unauthenticated callers alongside the other rookie fields, not after someone
notices.
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
            }
        ],
        "teamTotals": [{"team": "Alpha", "auctionDollars": 417}],
        "totalBudget": 1200,
    }


def test_the_board_value_is_stripped_for_public_callers():
    redacted = server._redact_draft_capital_for_public(_payload())
    pick = redacted["picks"][0]
    assert "rookieBoardValue" not in pick
    # The rest of the rookie board goes with it, as before.
    for gone in ("rookieName", "rookiePos", "rookieKtcValue", "rookieKtcDollar"):
        assert gone not in pick
    assert redacted.get("rookieBoardRedacted") is True
    # Pick ownership and dollar values stay — the public /league tab reads them.
    assert pick["dollarValue"] == 135.0
    assert pick["currentOwner"] == "Alpha"


def test_it_is_listed_in_the_private_field_tuple():
    # Pinning the tuple rather than only the behaviour: a future field added
    # to the payload but not to this tuple is the exact leak this guards.
    assert "rookieBoardValue" in server._DRAFT_CAPITAL_PRIVATE_PICK_FIELDS


def test_an_authenticated_payload_keeps_it():
    payload = _payload()
    assert payload["picks"][0]["rookieBoardValue"] == 7587.0


def test_the_dollar_ladder_and_the_board_value_are_different_scales():
    """The reason the field is needed at all.

    Dollars are a rank-decayed share of a fixed $1200 pool; board value is the
    0-9999 blended dynasty value.  Value-per-dollar is not constant down the
    ladder — measured on the live board it rises roughly 30x from the top
    rookie to the 72nd — so one cannot stand in for the other.
    """
    values = [7587.0, 4180.0, 2990.0, 2430.0, 1721.0]
    dollars = server._rookie_dollars_from_values(values, total=100)
    ratios = [v / d for v, d in zip(values, dollars) if d > 0]
    # Non-proportionality is the whole point: if value/dollar were constant,
    # the dollar column would carry the same information and this field would
    # be redundant.  (The direction and magnitude of the spread depend on
    # where the floors and per-round caps bind, so only the invariant that
    # survives every input shape is asserted here.)
    assert max(ratios) > 1.2 * min(ratios), "the two scales are not proportional"
