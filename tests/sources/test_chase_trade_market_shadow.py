"""chaseTradeMarket is HELD by construction and cannot vote or move B11 confidence.

Three halves, all synthetic (no live board, no network, no private data):

1. **Declaration** — the hold is unconditional (no flag, env or file read), every
   source key is held, and the label is the owner's verbatim "Experimental — Not
   Voting".
2. **Decoupled from the Signals shadow hold** — the key is in neither Signals
   table, and toggling every Signals flag leaves the hold in force.
3. **Stage S0** — no source registry names the key yet (the "no registry names
   the key" proof of design §6), so nothing can load it.
4. **Zero effect through the real gate** — with the source registered into a
   COPY of the registry and given values on every row, handing its held keys to
   the existing active-source gate (``policy_held_sources``) produces a board
   identical to one built without the source: values, ranks, voters,
   ``confidenceBucket`` and every B11 axis. A positive control proves the
   synthetic source is not inert when it is NOT held, so the test cannot pass
   vacuously.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import src.api.data_contract as dc
from src.api import feature_flags
from src.sources import chase_trade_market as ctm

REPO = Path(__file__).resolve().parents[2]

# ── 1. declaration ─────────────────────────────────────────────────────────


def test_every_key_is_held_with_the_owner_label():
    holds = ctm.vote_holds()
    assert set(holds) == set(ctm.SOURCE_KEYS) == {"chaseTradeMarket", "chaseTradeMarketIdp"}
    for hold in holds.values():
        assert hold["votes"] is False
        assert hold["flag"] is None
        assert hold["statusLabel"] == "Experimental — Not Voting"
        assert hold["reason"] == ctm.HOLD_REASON
    assert ctm.held_source_keys() == frozenset(ctm.SOURCE_KEYS)
    assert not any(ctm.may_vote(k) for k in ctm.SOURCE_KEYS)
    assert ctm.may_vote("ktcCrowdSfTep")
    assert ctm.VOTE_RELEASE_FLAG is None
    assert ctm.DISPLAY_NAME == "Chase Upside Trade Market"


def test_the_hold_reads_nothing_and_cannot_be_weakened_by_a_caller(monkeypatch):
    first = ctm.vote_holds()
    first[ctm.SOURCE_KEY]["votes"] = True
    first.pop(ctm.IDP_SOURCE_KEY)
    assert ctm.vote_holds()[ctm.SOURCE_KEY]["votes"] is False
    assert ctm.IDP_SOURCE_KEY in ctm.vote_holds()
    # A flag or env that sounds like a release does nothing: no switch exists.
    monkeypatch.setenv("RISKIT_FEATURE_CHASE_TRADE_MARKET_VOTE", "1")
    feature_flags.reload()
    try:
        assert ctm.held_source_keys() == frozenset(ctm.SOURCE_KEYS)
    finally:
        feature_flags.reload()


def test_assert_not_voting_fails_closed():
    ctm.assert_not_voting({"ktcCrowdSfTep", "fantasyCalc"})
    with pytest.raises(ctm.HeldSourceVotedError, match="chaseTradeMarket"):
        ctm.assert_not_voting({"ktcCrowdSfTep", ctm.SOURCE_KEY})


def test_vote_state_entry_reads_as_absent_by_design_to_existing_readers():
    for present in (True, False):
        entry = ctm.vote_state_entry(csv_present=present)
        assert entry["votes"] is False and entry["heldFromVote"] == ctm.HOLD_REASON
        stamp = {ctm.SOURCE_KEY: entry}
        assert ctm.SOURCE_KEY in dc.private_sources_absent_by_design(stamp)


def test_picks_have_no_key_and_entries_are_disjoint_scopes():
    entries = ctm.shadow_ranking_source_entries()
    assert [e["key"] for e in entries] == list(ctm.SOURCE_KEYS)
    assert {e["scope"] for e in entries} == {
        dc.SOURCE_SCOPE_OVERALL_OFFENSE,
        dc.SOURCE_SCOPE_OVERALL_IDP,
    }
    for e in entries:
        assert e["correlation_group"] == ctm.CORRELATION_GROUP
        assert e["game_type"] == dc.GAME_TYPE_DYNASTY and e["game_type_evidence"]
        assert e["shadow_only"] is True and e["depth"] is None


# ── 2. decoupled from the Signals shadow hold ──────────────────────────────


def test_not_in_the_signals_tables():
    for key in ctm.SOURCE_KEYS:
        assert key not in dc.PRIVATE_SOURCE_VOTE_HOLDS
        assert key not in dc.PRIVATE_SOURCE_SHADOW_KEYS
        assert key not in dc.POLICY_SOURCE_VOTE_HOLDS
        assert not key.startswith("signals")  # _private_source_vote_state's coupling rule


@pytest.mark.parametrize("active", ["0", "1"])
@pytest.mark.parametrize("idp_promoted", ["0", "1"])
def test_signals_flags_never_release_it(monkeypatch, active, idp_promoted):
    monkeypatch.setenv("RISKIT_FEATURE_SIGNALS_ACTIVE_SOURCE", active)
    monkeypatch.setenv("RISKIT_FEATURE_SIGNALS_IDP_SHARED_MARKET", idp_promoted)
    feature_flags.reload()
    try:
        assert ctm.held_source_keys() == frozenset(ctm.SOURCE_KEYS)
        assert not set(ctm.SOURCE_KEYS) & set(dc._private_source_vote_state())
    finally:
        feature_flags.reload()


def test_module_imports_neither_the_contract_nor_feature_flags():
    import ast

    tree = ast.parse(Path(ctm.__file__).read_text(encoding="utf-8"))
    imported = {
        (n.module if isinstance(n, ast.ImportFrom) else a.name)
        for n in ast.walk(tree)
        if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in (n.names if isinstance(n, ast.Import) else [n])
    }
    assert not {m for m in imported if m and ("data_contract" in m or "feature_flags" in m)}
    assert "os" not in imported  # no environment read


# ── 3. stage S0: no registry names the key ────────────────────────────────

_REGISTRY_FILES = (
    "frontend/lib/dynasty-data.js",
    "config/sources/source_lineage.json",
    "config/sources/rehabilitation.json",
    "config/sources/freshness_v1.json",
    "scripts/record_source_datasets.py",
)


@pytest.mark.skipif(
    ctm.REGISTRATION_STAGE != ctm.REGISTRATION_STAGE_S0,
    reason="registered at S1: the P10 registration owns its own proofs",
)
def test_stage_s0_no_registry_names_the_key():
    registered = set(dc.get_ranking_source_keys())
    for key in ctm.SOURCE_KEYS:
        assert key not in registered
        assert key not in dc._SOURCE_CSV_PATHS
    for rel in _REGISTRY_FILES:
        text = (REPO / rel).read_text(encoding="utf-8")
        assert ctm.SOURCE_KEY not in text, rel  # also covers the IDP key (a superstring)


# ── 4. zero effect through the real active-source gate ────────────────────

_PLAYERS = (
    # name, pos, ktcCrowd, ktcTrades, fantasyCalc, dynastyDaddy, ctm (deliberately
    # inverted so an unheld vote visibly moves values and agreement)
    ("Off A", "QB", 9999, 9800, 9900, 9700, 4200),
    ("Off B", "WR", 9000, 9100, 8800, 8900, 9990),
    ("Off C", "RB", 8000, 7900, 8100, 7800, 9500),
    ("Off D", "TE", 7000, 7100, 6900, 7050, 9000),
    ("Off E", "WR", 6000, 5900, 6100, 6050, 8800),
    ("Off F", "RB", 5000, 5100, 4900, 5050, 8500),
    ("Off G", "QB", 4000, 3900, 4100, 4050, 8200),
    ("Off H", "WR", 3000, 3100, 2900, 3050, 8000),
)
_VOTERS = ("ktcCrowdSfTep", "ktcTradesSfTep", "fantasyCalc", "dynastyDaddySf")


def _rows(with_ctm: bool) -> list[dict]:
    out = []
    for name, pos, *vals in _PLAYERS:
        sites = dict(zip(_VOTERS, vals[:4]))
        if with_ctm:
            sites[ctm.SOURCE_KEY] = vals[4]
        out.append(
            {
                "canonicalName": name,
                "displayName": name,
                "legacyRef": name,
                "position": pos,
                "assetClass": "offense",
                "values": {
                    "overall": 0,
                    "rawComposite": 0,
                    "finalAdjusted": 0,
                    "displayValue": None,
                },
                "canonicalSiteValues": sites,
                "sourceCount": len(sites),
            }
        )
    return out


_DECISION_FIELDS = (
    "rankDerivedValue",
    "canonicalConsensusRank",
    "confidenceBucket",
    "confidenceLabel",
    "confidenceAxes",
    "confidenceReasons",
    "quarantined",
    "anomalyFlags",
    "sourceCount",
)


def _board(monkeypatch, *, with_ctm: bool, held: frozenset[str] | set[str]) -> dict[str, dict]:
    registry = list(dc._RANKING_SOURCES)
    if with_ctm:
        registry += [copy.deepcopy(e) for e in ctm.shadow_ranking_source_entries()]
    monkeypatch.setattr(dc, "_RANKING_SOURCES", registry)
    rows = _rows(with_ctm)
    dc._compute_unified_rankings(rows, {}, policy_held_sources=held)
    return {r["canonicalName"]: r for r in rows}


def _decisions(board: dict[str, dict]) -> dict[str, dict]:
    return {
        name: {f: json.dumps(row.get(f), sort_keys=True, default=str) for f in _DECISION_FIELDS}
        for name, row in board.items()
    }


def test_a_held_chase_trade_market_changes_no_value_rank_or_confidence(monkeypatch):
    baseline = _board(monkeypatch, with_ctm=False, held=set())
    held = _board(monkeypatch, with_ctm=True, held=ctm.held_source_keys())
    assert _decisions(held) == _decisions(baseline)
    for row in held.values():
        voters = set(row.get("sourceRankMeta") or {})
        ctm.assert_not_voting(voters)
        assert not set(row.get("sourceRanks") or {}) & set(ctm.SOURCE_KEYS)
        # B11: the held family is not an ELIGIBLE family whose silence counts.
        assert ctm.CORRELATION_GROUP not in json.dumps(row.get("confidenceAxes"), default=str)
        assert ctm.CORRELATION_GROUP not in json.dumps(row.get("confidenceReasons"), default=str)


def test_positive_control_an_unheld_vote_would_move_the_board(monkeypatch):
    """Without the hold the same synthetic source DOES vote — so the test above
    measures the hold, not an inert fixture."""
    baseline = _board(monkeypatch, with_ctm=False, held=set())
    unheld = _board(monkeypatch, with_ctm=True, held=set())
    assert any(ctm.SOURCE_KEY in (r.get("sourceRankMeta") or {}) for r in unheld.values())
    assert _decisions(unheld) != _decisions(baseline)
    moved_value = [
        n for n in baseline if unheld[n]["rankDerivedValue"] != baseline[n]["rankDerivedValue"]
    ]
    moved_b11 = [
        n
        for n in baseline
        if json.dumps(unheld[n].get("confidenceAxes"), sort_keys=True, default=str)
        != json.dumps(baseline[n].get("confidenceAxes"), sort_keys=True, default=str)
    ]
    assert moved_value and moved_b11  # both halves of "cannot vote or affect B11" are live
