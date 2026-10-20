"""Chase Upside Trade Market (``chaseTradeMarket``) — the shadow source's declaration.

The owner directive of 2026-10-19 (second, later version, which wins on conflict)
asks for a proprietary, trade-derived dynasty valuation source built on the
existing market-trade ledger, labelled **"Experimental — Not Voting"**, that "must
remain non-voting until it passes the required independent validation and I
approve production voting". This module is the ONE place that declares what the
source IS and that it is HELD; nothing else may restate it.

What it declares
────────────────
* identity — the source keys (offense and IDP, disjoint scopes; picks are held
  structurally and have no key), display name, status label, model family,
  B10 correlation group, lineage provider and basis, and the box-local board
  directory;
* the **vote hold**, in the same vocabulary the contract's vote-state stamp uses
  (``reason`` / ``decision`` / ``holdKind`` / ``votes: False``), so the P10
  registration can hand it to the existing active-source gate without a new
  mechanism;
* the would-be ``_RANKING_SOURCES`` entries (:func:`shadow_ranking_source_entries`),
  used today only by tests that prove the hold neutralises the source, and by the
  P10 registration as its starting point;
* the model family's feature manifest (:data:`FEATURE_MANIFEST`), validated
  against ``config/model_registry/feature_dictionary.json``.

HELD BY CONSTRUCTION
────────────────────
:func:`vote_holds` takes no argument, reads no feature flag, no environment
variable and no file. It always returns the hold. There is deliberately **no
switch** that lifts it (``VOTE_RELEASE_FLAG is None``): voting requires a reviewed
change that adds one, after validation passes and the owner approves (design §6
"Promotion", owner question Q9). A registry promotion of a ``chase_trade_market``
model version moves only the shadow champion pointer; it does not touch this
hold (``promotion_gates.CHASE_TRADE_MARKET_POLICY.voting_effect``).

DECOUPLED FROM THE SIGNALS SHADOW HOLD
──────────────────────────────────────
``data_contract.PRIVATE_SOURCE_VOTE_HOLDS`` / ``PRIVATE_SOURCE_SHADOW_KEYS`` are
the Signals IDP crosswalk hold, lifted by ``signals_idp_shared_market`` and
coupled to ``signals_active_source`` through ``_private_source_vote_state``'s
``key.startswith("signals")`` rule. Reusing them would make this source's vote
state a function of a Signals methodology decision. So this hold names neither
table nor flag, and ``tests/sources/test_chase_trade_market_shadow.py`` pins that
toggling every Signals flag leaves it in force.

REGISTRATION STAGE
──────────────────
Stage **S0 — shadow and unregistered** (design §6, the recommended default until
promotion prep): the key is in no source registry (``_RANKING_SOURCES``,
``_SOURCE_CSV_PATHS``, the frontend mirror, lineage, rehabilitation, freshness,
dataset recording). The private board, when P7 writes one, lives under
:data:`BOARD_DIR` (gitignored ``data/``) and is read only by the owner view.
Registration (S1) is P10 and needs #1817 / #1831 / #1847 / #1844 merged first; it
must consume this module rather than restate it.

Privacy: nothing here holds a league, manager, user or transaction id, and the
board this source will publish carries player identity and model output only.
"""

from __future__ import annotations

from typing import Any, Mapping

SOURCE_KEY = "chaseTradeMarket"
IDP_SOURCE_KEY = "chaseTradeMarketIdp"
#: Every key this source will ever register. Picks have no key: the Sleeper lanes
#: observe only the generic pick grade, which matches only rank-less derived rows
#: (design §4.10), so picks stay held structurally.
SOURCE_KEYS: tuple[str, ...] = (SOURCE_KEY, IDP_SOURCE_KEY)

DISPLAY_NAME = "Chase Upside Trade Market"
#: The owner's verbatim label (V2 directive §9).
STATUS_LABEL = "Experimental — Not Voting"
#: Disclosure the design requires wherever the values are shown (spec §19.8):
#: this measures the sharp-graph verified-dynasty market, not "all dynasty".
POPULATION_LABEL = "sharp-graph verified-dynasty trade market"

MODEL_FAMILY = "chase_trade_market"
#: The learning-receipt producer name and its own artifact store
#: (``learning_receipt.NATIVE_STORES`` / ``ARTIFACT_STORE_WRITERS``).
RECEIPT_PRODUCER = "chase_trade_market"
MODEL_STORE = "chase_trade_market_model"
CORRELATION_GROUP = "chaseTradeMarket"
LINEAGE_PROVIDER = "chaseUpside"
LINEAGE_BASIS = "trade_derived"
#: Box-local, gitignored (``data/`` is ignored). Never committed.
BOARD_DIR = "data/sources/chase_trade_market/board"

REGISTRATION_STAGE_S0 = "S0_unregistered_shadow"
REGISTRATION_STAGE_S1 = "S1_registered_held"
REGISTRATION_STAGE = REGISTRATION_STAGE_S0

HOLD_KIND = "experimental_shadow"
HOLD_REASON = "experimental_not_voting_pending_validation_and_owner_approval"
HOLD_DECISION = (
    "owner directive 2026-10-19 (second version, section 9): Experimental — Not "
    "Voting until the model passes independent validation and the owner approves "
    "production voting"
)
#: No switch lifts the hold. Adding one is the reviewed change that makes this
#: source eligible to vote, and it is not this module's to make.
VOTE_RELEASE_FLAG: str | None = None

#: Scopes, mirroring ``data_contract.SOURCE_SCOPE_*`` by value (this module must
#: not import the contract builder: it is read by tests and by P10 wiring).
_SCOPE_OVERALL_OFFENSE = "overall_offense"
_SCOPE_OVERALL_IDP = "overall_idp"
_GAME_TYPE_DYNASTY = "DYNASTY"
_GAME_TYPE_EVIDENCE = (
    "trades only from leagues whose Sleeper settings.type == 2 is captured by the "
    "market-trade format owner (src/trade/market_trade_format.py dynasty axis); a "
    "trade whose dynasty state is unverified is excluded "
    "(market_trade_eval.fit_suitability: dynasty_state_unverified)"
)


def _hold() -> dict[str, Any]:
    return {
        "reason": HOLD_REASON,
        "decision": HOLD_DECISION,
        "holdKind": HOLD_KIND,
        "flag": VOTE_RELEASE_FLAG,
        "statusLabel": STATUS_LABEL,
        "votes": False,
    }


def vote_holds() -> dict[str, dict[str, Any]]:
    """``{source_key: hold}`` for every key of this source — ALWAYS.

    Reads nothing. A fresh copy each call, so a caller mutating its result cannot
    weaken the next caller's hold."""
    return {key: _hold() for key in SOURCE_KEYS}


def held_source_keys() -> frozenset[str]:
    """The keys the active-source gate must drop. Always every key of this source."""
    return frozenset(vote_holds())


def may_vote(key: str) -> bool:
    """False for every key of this source; ``True`` only for keys it does not own."""
    return str(key) not in held_source_keys()


class HeldSourceVotedError(AssertionError):
    """A held chaseTradeMarket key reached a vote (fail closed, never repaired)."""


def assert_not_voting(voting_keys: Any) -> None:
    """Raise if any held key is among ``voting_keys`` (e.g. a row's ``sourceRankMeta``
    keys or the active-source list). The P10 registration and the on-box
    ``contractHealth`` rule call this; a violation is a pipeline fault, so it is
    raised rather than quietly filtered."""
    leaked = sorted(held_source_keys() & {str(k) for k in (voting_keys or ())})
    if leaked:
        raise HeldSourceVotedError(
            f"held source key(s) {leaked} reached a vote; {STATUS_LABEL!r} sources never vote"
        )


def vote_state_entry(*, csv_present: bool) -> dict[str, Any]:
    """This source's entry in the contract vote-state stamp vocabulary.

    Matches the keys ``data_contract._source_vote_state`` publishes for a held
    source (``heldFromVote`` / ``votes`` / ``voteState`` / ``holdKind``), so every
    existing reader — ``private_sources_absent_by_design``, the coverage gates,
    the Rankings/Settings labels — treats it as "collected, not voting by
    declaration". ``private: True``: the board is box-local."""
    return {
        "state": "present" if csv_present else "not_provisioned",
        "provisioned": bool(csv_present),
        "csvPresent": bool(csv_present),
        "private": True,
        "holdKind": HOLD_KIND,
        "holdDecision": HOLD_DECISION,
        "rollbackFlag": VOTE_RELEASE_FLAG,
        "rolledBack": False,
        "heldFromVote": HOLD_REASON,
        "votes": False,
        "voteState": "held" if csv_present else "unavailable",
        "statusLabel": STATUS_LABEL,
    }


def shadow_ranking_source_entries() -> tuple[dict[str, Any], ...]:
    """The would-be ``_RANKING_SOURCES`` entries — NOT registered at stage S0.

    Signal ``rank`` (ordinal trade information on borrowed spacing, design §4.9):
    the board's ``voteRank`` travels rank -> percentile -> Hill. ``depth`` is left
    ``None`` on purpose: coverage is unknown until the first real fit, and a guessed
    depth would set a percentile denominator nobody measured."""
    common: dict[str, Any] = {
        "game_type": _GAME_TYPE_DYNASTY,
        "game_type_evidence": _GAME_TYPE_EVIDENCE,
        "column_label": "CU Trades",
        "position_group": None,
        "depth": None,
        "weight": 1.0,
        "is_backbone": False,
        "is_retail": False,
        "is_tep_premium": False,
        "needs_shared_market_translation": False,
        "excludes_rookies": False,
        "correlation_group": CORRELATION_GROUP,
        "private": True,
        "status_label": STATUS_LABEL,
        "shadow_only": True,
    }
    return (
        {
            "key": SOURCE_KEY,
            "display_name": DISPLAY_NAME,
            "scope": _SCOPE_OVERALL_OFFENSE,
            **common,
        },
        {
            "key": IDP_SOURCE_KEY,
            "display_name": f"{DISPLAY_NAME} IDP",
            "scope": _SCOPE_OVERALL_IDP,
            **common,
        },
    )


#: The trade-observation features the model family consumes, by dictionary
#: ``(name, version)``. Definitions live ONLY in
#: ``config/model_registry/feature_dictionary.json``; this lists references.
#: League maturity (completed dynasty seasons, both readings) is deliberately
#: absent: its owner is ``src/intel/league_filter.py``, whose current
#: ``league_age_seasons`` is a floor (2 for any chained league) that cannot
#: decide ">= 3 verified completed seasons". It joins this manifest when P3 lands
#: the exact as-of resolver (gaps G3/G5) — never as a guessed definition here.
FEATURE_MANIFEST: tuple[Mapping[str, Any], ...] = (
    {"name": "trade_observation_lane", "version": 1},
    {"name": "trade_dedupe_state", "version": 1},
    {"name": "trade_format_disposition", "version": 1},
    {"name": "trade_topology", "version": 1},
    {"name": "trade_fit_suitability", "version": 1},
)
