"""The board says it does not score IDP under the league's settings.

Audit finding W27-F012 (root cause R7).

The ordering of the IDP families on this board is inherited wholesale
from generic IDP calculators.  Measured on the live board: DL peaks at
6,362, LB at 5,908 and DB at 3,159 — defensive backs compressed to
roughly half the value at every quantile — while ``dynasty_main`` pays
5.32 per pass defensed and 5.32 per interception against 1.33 per solo
tackle, so a 15-pass-defensed cornerback earns 79.8 points from one
category alone.  Nothing in the live value path re-scores a defender
under the league's own settings.

Correcting that needs a forward-looking projection feed (the
scoring-exact concept lives in ``src/bdvm/``).  Disclosing it does not,
and a reader who knows the values are format-generic reads them
correctly today — the same posture ``ValueBasisNote`` already takes on
/draft.  This pins the disclosure so a later refactor cannot quietly
drop it.
"""

from __future__ import annotations

from tests.api.test_trust_confidence import _make_player, _payload_with_players

from src.api.data_contract import build_api_data_contract


def _methodology() -> dict:
    payload = _payload_with_players(_make_player("Test LB", "LB", ktc=4000))
    return build_api_data_contract(payload)["methodology"]


def test_the_contract_states_that_idp_is_not_league_scored():
    block = _methodology()["idpTranslation"]["formatSensitivity"]
    assert block["scoredUnderLeagueSettings"] is False


def test_the_statement_is_readable_prose_not_just_a_flag():
    block = _methodology()["idpTranslation"]["formatSensitivity"]
    text = block["description"]
    assert "format-generic" in text.lower()
    # It must point somewhere, or it is a dead end for the reader.
    assert "/bdvm" in text


def test_the_flag_is_a_claim_about_scoring_not_about_coverage():
    """A board with no IDP source at all would still be unscored.

    The disclosure is about the VALUE CONCEPT, so it is unconditional on
    which sources happened to cover this payload — a reader must not
    have to infer it from source coverage.
    """
    payload = _payload_with_players(_make_player("Test QB", "QB", ktc=8000))
    block = build_api_data_contract(payload)["methodology"]["idpTranslation"][
        "formatSensitivity"
    ]
    assert block["scoredUnderLeagueSettings"] is False
