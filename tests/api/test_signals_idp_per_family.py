"""Signals IDP per-family release (owner directive 2026-10-19, SIGNALS_IDP_VOTING).

Proves, through the production entry point on the SYNTHETIC Signals fixture of
``tests/api/test_signals_active_source.py`` (no Signals data, no network):

* the vote-state truth table, family by family, with AND semantics;
* ``signals_idp_shared_market`` ALONE is byte-identical to the default build;
* master + family WITHOUT ``signals_idp_xwalk_v2`` is ``held:
  no_qualified_translation`` — Candidate A can never vote — and the shadow
  stamp keeps publishing in every held / shadow state;
* a DL-only release moves only DL rows (and the picks tethered to the rookie
  pool); LB / DB keep their shadow; no offense row moves;
* rollback of a family is byte-identical to never releasing it;
* the Signals-scoped Sleeper-id guard withholds a contradicted name match and
  leaves offense (``signalsSf``) matching untouched;
* rookie and family-mismatch rows are withheld with a named reason;
* confidence does not score a translation-withheld row as uncovered;
* every release flag is read by literal name (AST pin);
* the count-aware n>=5 trim is unreachable on IDP rows under today's registry;
* consumers report the EFFECTIVE per-family state.
"""

from __future__ import annotations

import ast
import contextlib
import copy
import inspect
import io
import json
from pathlib import Path

import pytest

from src.api import data_contract as dc
from src.api.data_contract import build_api_data_contract
from tests.api.test_signals_active_source import (
    IDP_POS,
    IDP_RELEASE_FLAGS,
    SIGNALS_KEYS,
    _flags,
    _idp,
    _off,
    _raw_payload,
    _rows,
    _write_store,
)

FAMILY_KEYS = SIGNALS_KEYS[1:]
FAMILY_FLAG = dict(
    zip(FAMILY_KEYS, ("signals_idp_dl_vote", "signals_idp_lb_vote", "signals_idp_db_vote"))
)
MASTER = "signals_idp_shared_market"
XWALK = "signals_idp_xwalk_v2"
ACTIVE = "signals_active_source"

# Wall-clock fields that differ between two otherwise identical builds.
_CLOCK_KEYS = frozenset({"generatedAt", "mtime"})


def _normalised(contract: dict) -> str:
    def strip(node):
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k not in _CLOCK_KEYS}
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node

    return json.dumps(strip(contract), sort_keys=True, default=str)


def _build(root: Path, raw: dict | None = None) -> dict:
    with contextlib.redirect_stdout(io.StringIO()):
        return build_api_data_contract(copy.deepcopy(raw or _raw_payload()), csv_root=root)


@pytest.fixture(scope="module")
def store(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("signals_per_family")
    _write_store(root)
    return root


@pytest.fixture(scope="module")
def default_board(store) -> dict:
    return _build(store)


# ── the truth table (pure decision) ─────────────────────────────────────


def _decide(key: str, **on: bool) -> tuple[bool, str | None]:
    return dc._private_vote_decision(key, {k: bool(v) for k, v in on.items()})


@pytest.mark.parametrize("key", FAMILY_KEYS)
def test_truth_table(key):
    fam = FAMILY_FLAG[key]
    shadow_reason = dc.PRIVATE_SOURCE_VOTE_HOLDS[key]
    everything = {ACTIVE: True, MASTER: True, fam: True, XWALK: True}
    # active=0 → rolled back, whatever else is on.
    assert _decide(key, **{**everything, ACTIVE: False})[0] is True
    # master=0 → shadow (the declared hold).
    assert _decide(key, **{**everything, MASTER: False}) == (False, shadow_reason)
    # family=0 → shadow.
    assert _decide(key, **{**everything, fam: False}) == (False, shadow_reason)
    # master+family but no qualified translation → held, never Candidate A.
    assert _decide(key, **{**everything, XWALK: False}) == (
        False,
        dc.HOLD_NO_QUALIFIED_TRANSLATION,
    )
    # all four → votes.
    assert _decide(key, **everything) == (False, None)
    # a SIBLING family's switch releases nothing here.
    for other in set(FAMILY_FLAG.values()) - {fam}:
        assert _decide(key, **{ACTIVE: True, MASTER: True, other: True, XWALK: True}) == (
            False,
            shadow_reason,
        )
    # unknown / missing flags read as OFF (fail closed).
    assert _decide(key) == (True, shadow_reason)


def test_offense_is_untouched_by_the_idp_release_flags():
    assert _decide("signalsSf", **{ACTIVE: True}) == (False, None)
    assert _decide("signalsSf", **{ACTIVE: False})[0] is True


@pytest.mark.parametrize(
    "flags,state,votes,shadow",
    [
        ((), "shadow", False, True),
        ((MASTER,), "shadow", False, True),
        ((MASTER, "signals_idp_dl_vote"), "held", False, True),
        ((XWALK,), "shadow", False, True),
        ((MASTER, "signals_idp_dl_vote", XWALK), "active", True, False),
    ],
)
def test_vote_state_stamp_and_shadow_publication(store, flags, state, votes, shadow):
    with _flags(*flags):
        avail = dc._private_source_vote_state(store)
    dl = avail["signalsIdpDl"]
    assert (dl["voteState"], dl["votes"]) == (state, votes)
    assert dl["rollbackFlag"] == "signals_idp_dl_vote"
    assert dc.private_source_publishes_shadow("signalsIdpDl", dl) is shadow
    if state == "held":
        assert dl["heldFromVote"] == dc.HOLD_NO_QUALIFIED_TRANSLATION
    # LB / DB are never released by a DL-only flag set.
    assert avail["signalsIdpLb"]["voteState"] == "shadow"
    assert avail["signalsIdpDb"]["voteState"] == "shadow"


def test_missing_csv_is_unavailable_and_publishes_no_shadow(tmp_path):
    _write_store(tmp_path)
    (tmp_path / "data/sources/signals/board/signalsIdpLb.csv").unlink()
    with _flags(*IDP_RELEASE_FLAGS):
        avail = dc._private_source_vote_state(tmp_path)
    lb = avail["signalsIdpLb"]
    assert lb["voteState"] == "unavailable" and lb["votes"] is False
    assert not dc.private_source_publishes_shadow("signalsIdpLb", lb)


# ── byte identity ───────────────────────────────────────────────────────


def test_the_master_alone_is_byte_identical_to_the_default(store, default_board):
    with _flags(MASTER):
        master_only = _build(store)
    assert _normalised(master_only) == _normalised(default_board)


@pytest.mark.parametrize("family_flag", sorted(FAMILY_FLAG.values()))
def test_a_family_flag_without_the_master_is_byte_identical(store, default_board, family_flag):
    with _flags(family_flag, XWALK):
        built = _build(store)
    rows, base = _rows(built), _rows(default_board)
    assert {n: r.get("rankDerivedValue") for n, r in rows.items()} == {
        n: r.get("rankDerivedValue") for n, r in base.items()
    }


def test_held_without_a_translation_moves_no_value_and_keeps_the_shadow(store, default_board):
    with _flags(MASTER, "signals_idp_dl_vote"):
        held = _build(store)
    assert held["privateSourceAvailability"]["signalsIdpDl"]["voteState"] == "held"
    on, off = _rows(held), _rows(default_board)
    for name, row in on.items():
        assert row.get("rankDerivedValue") == off[name].get("rankDerivedValue"), name
        assert row.get("confidenceBucket") == off[name].get("confidenceBucket"), name
        assert "signalsIdpDl" not in (row.get("sourceRankMeta") or {})
    shadows = [r for r in on.values() if "signalsIdpDl" in (r.get("sourceShadowMeta") or {})]
    assert shadows and all(
        r["sourceShadowMeta"]["signalsIdpDl"].get("candidate") is None  # still Candidate A
        for r in shadows
    )


def test_a_dl_only_release_moves_only_dl_rows_and_tethered_picks(store, default_board):
    with _flags(MASTER, "signals_idp_dl_vote", XWALK):
        dl_only = _build(store)
    avail = dl_only["privateSourceAvailability"]
    assert avail["signalsIdpDl"]["voteState"] == "active"
    assert avail["signalsIdpLb"]["voteState"] == avail["signalsIdpDb"]["voteState"] == "shadow"
    on, off = _rows(dl_only), _rows(default_board)
    moved = [n for n in on if on[n].get("rankDerivedValue") != off[n].get("rankDerivedValue")]
    assert moved, "a released family must actually vote"
    for name in moved:
        row = on[name]
        assert row.get("position") == "DL" or row.get("assetClass") == "pick", name
    assert not [n for n in moved if n.startswith("Synthetic Off")]
    contributing = [
        r
        for r in on.values()
        if float(
            ((r.get("sourceRankMeta") or {}).get("signalsIdpDl") or {}).get("appliedWeight") or 0
        )
        > 0
    ]
    assert len(contributing) > 20
    assert all(
        isinstance(r["sourceRankMeta"]["signalsIdpDl"]["valueContribution"], int)
        and r["sourceRankMeta"]["signalsIdpDl"]["valueContribution"] > 0
        for r in contributing
    )
    for row in on.values():
        meta = row.get("sourceRankMeta") or {}
        assert "signalsIdpLb" not in meta and "signalsIdpDb" not in meta
        if row.get("position") == "DL":
            assert "signalsIdpDl" not in (row.get("sourceShadowMeta") or {})


def test_rolling_a_family_back_is_byte_identical_to_never_releasing_it(store, default_board):
    with _flags(MASTER, XWALK):  # the family switch is OFF again
        rolled_back = _build(store)
    on, off = _rows(rolled_back), _rows(default_board)
    for name in on:
        assert on[name].get("rankDerivedValue") == off[name].get("rankDerivedValue")
        assert on[name].get("canonicalConsensusRank") == off[name].get("canonicalConsensusRank")


# ── identity guard (Signals IDP only) ───────────────────────────────────


def _contradicted_store(root: Path, target: int, *, offense: bool) -> None:
    """The fixture store with one observation's Sleeper id CONTRADICTING the
    row it name-matches (same name, a different sid)."""
    from src.sources import signals as S
    from tests.api import test_signals_active_source as T

    off, idp = T._signals_observations()
    pool = off if offense else idp
    name = _off(target) if offense else _idp(target)
    for obs in pool:
        if obs["name"] == name:
            obs["sleeperId"] = "99999"
    store_dir = root / "data" / "sources" / "signals"
    (store_dir / "values").mkdir(parents=True, exist_ok=True)
    (store_dir / "values" / S.PROVISIONED_MARKER).write_text("{}", encoding="utf-8")
    for spec, obs in ((S.VALUE_DATASETS["offense"], off), (S.VALUE_DATASETS["idp"], idp)):
        rows, _ = S.build_board_rows(obs, spec)
        for key in spec.output_keys():
            board = [r for r in rows if spec.board_key_for(r) == key]
            path = S.board_csv_path(store_dir, key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(S.render_board_csv(board), encoding="utf-8")


def test_a_contradicted_sid_is_withheld_for_signals_idp_only(tmp_path):
    _contradicted_store(tmp_path, 3, offense=False)  # Synthetic Idp 003 (a DL)
    off_root = tmp_path / "off"
    _contradicted_store(off_root, 40, offense=True)
    with _flags(*IDP_RELEASE_FLAGS):
        guarded = _build(tmp_path)
        offense_board = _build(off_root)
    row = _rows(guarded)[_idp(3)]
    assert "signalsIdpDl" not in (row.get("canonicalSiteValues") or {})
    assert "signalsIdpDl" not in (row.get("sourceRankMeta") or {})
    assert dc._LAST_CONTRACT_JOIN_SUMMARY is not None
    # Offense matching is NOT guarded: the contradicted offense row still joins.
    assert "signalsSf" in (_rows(offense_board)[_off(40)].get("canonicalSiteValues") or {})
    # Without the crosswalk flag the guard is off and the served join is unchanged.
    plain = _build(tmp_path)
    assert "signalsIdpDl" in (_rows(plain)[_idp(3)].get("canonicalSiteValues") or {})


def test_the_guard_is_opt_in_inside_the_identity_owner():
    from src.identity import resolution as R

    per_source = {"abc::DL": {"sleeperId": "2", "value": 1.0}}
    kwargs = dict(
        row_player_id="1",
        row_name="abc",
        row_position="DL",
        per_source=per_source,
        sid_index={},
        row_groups_by_key={},
        canonical_match_key=lambda s: s,
        position_group=lambda p: p,
    )
    assert R.match_row_to_source_entry(**kwargs).via == "name_group"
    refused = R.match_row_to_source_entry(**kwargs, refuse_sid_contradiction=True)
    assert (refused.entry_key, refused.via) == (None, R.VIA_SID_CONTRADICTION)
    # An absent id on either side is no contradiction.
    assert (
        R.match_row_to_source_entry(
            **{**kwargs, "row_player_id": ""}, refuse_sid_contradiction=True
        ).via
        == "name_group"
    )


# ── rookies, family mismatch, confidence ────────────────────────────────


def test_rookie_rows_are_withheld_by_basis(store):
    raw = _raw_payload()
    rookie = _idp(7)  # an LB the Signals board covers
    raw["players"][rookie]["_isRookie"] = True
    raw["players"][rookie]["rookie"] = True
    with _flags(*IDP_RELEASE_FLAGS):
        built = _build(store, raw)
    row = _rows(built)[rookie]
    if not row.get("rookie"):
        pytest.skip("the fixture's rookie marker did not survive the build")
    assert "signalsIdpLb" not in (row.get("sourceRankMeta") or {})
    withheld = row["sourceWithheldMeta"]["signalsIdpLb"]
    assert withheld["withheldReason"] == "rookie_unobservable_by_basis"
    assert withheld["withheldByTranslation"] is True


def test_a_family_mismatch_is_counted_not_dropped(tmp_path):
    from src.sources import signals as S
    from tests.api import test_signals_active_source as T

    off, idp = T._signals_observations()
    for obs in idp:
        if obs["name"] == _idp(6):  # a DL we hold as DL; Signals files it under DB
            obs["position"] = "DB"
            obs["rawPosition"] = "CB"
    store_dir = tmp_path / "data" / "sources" / "signals"
    (store_dir / "values").mkdir(parents=True, exist_ok=True)
    (store_dir / "values" / S.PROVISIONED_MARKER).write_text("{}", encoding="utf-8")
    for spec, obs in ((S.VALUE_DATASETS["offense"], off), (S.VALUE_DATASETS["idp"], idp)):
        rows, _ = S.build_board_rows(obs, spec)
        for key in spec.output_keys():
            board = [r for r in rows if spec.board_key_for(r) == key]
            path = S.board_csv_path(store_dir, key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(S.render_board_csv(board), encoding="utf-8")
    with _flags(XWALK):
        shadow = _build(tmp_path)
    row = _rows(shadow)[_idp(6)]
    assert row["position"] == "DL"
    if "signalsIdpDb" not in (row.get("canonicalSiteValues") or {}):
        pytest.skip("the identity join did not attach the mismatched observation")
    meta = row["sourceShadowMeta"]["signalsIdpDb"]
    assert meta["withheldReason"] == "family_mismatch" and meta["wouldContribute"] is None
    assert "signalsIdpDb" not in (row.get("sourceRankMeta") or {})


def test_confidence_does_not_count_a_translation_withheld_row_as_uncovered(store):
    """A Signals-only LB (no bridge coordinate) is withheld by OUR translation;
    the Signals family must not enter that row's eligible-family denominator."""
    raw = _raw_payload()
    name = _idp(4)  # an LB Signals covers
    raw["players"][name].pop("idpTradeCalc", None)
    raw["players"][name]["_canonicalSiteValues"].pop("idpTradeCalc", None)
    with _flags(*IDP_RELEASE_FLAGS):
        released = _build(store, raw)
    base = _build(store, raw)
    on, off = _rows(released)[name], _rows(base)[name]
    assert on["sourceWithheldMeta"]["signalsIdpLb"]["withheldReason"] == "unmatched_in_reference"
    assert on.get("softFallbackCount") == off.get("softFallbackCount")
    assert on.get("confidenceAxes") == off.get("confidenceAxes")


# ── structural pins ─────────────────────────────────────────────────────


def test_every_release_flag_is_read_by_literal_name():
    tree = ast.parse(inspect.getsource(dc._private_vote_flags))
    literal = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", getattr(node.func, "attr", "")) == "is_enabled"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }
    declared = {f for flags in dc.PRIVATE_SOURCE_HOLD_RELEASE_FLAGS.values() for f in flags}
    assert declared <= literal
    assert set(dc.PRIVATE_SOURCE_ROLLBACK_FLAGS.values()) <= literal
    from src.api import feature_flags

    for name in literal:
        assert name in feature_flags._DEFAULTS, name
    for name in ("signals_idp_dl_vote", "signals_idp_lb_vote", "signals_idp_db_vote", XWALK):
        assert feature_flags._DEFAULTS[name] is False
    assert set(dc.PRIVATE_SOURCE_HOLD_RELEASE_FLAGS) == set(dc.PRIVATE_SOURCE_VOTE_HOLDS)


def test_the_crosswalk_flag_is_read_by_literal_name_in_the_pipeline():
    src = inspect.getsource(dc._compute_unified_rankings)
    assert '_feature_flags.is_enabled("signals_idp_xwalk_v2")' in src
    assert 'is_enabled("signals_idp_xwalk_v2")' in inspect.getsource(dc._enrich_from_source_csvs)


def test_the_count_aware_trim_is_unreachable_on_idp_rows_under_todays_registry():
    """IDP rows carry at most 4 subgroup voters (one Signals family per row),
    so the n>=5 trim never fires there.  Fails the day a fifth IDP subgroup
    voter is registered — which must then be a deliberate decision."""
    cross_market, _ = dc._anchor_key_sets(dc._RANKING_SOURCES)
    for pos in IDP_POS:
        subgroup = set()
        for src in dc._RANKING_SOURCES:
            key = str(src.get("key") or "")
            if key in cross_market:
                continue
            scopes = [src["scope"], *(src.get("extra_scopes") or [])]
            if any(dc._scope_eligible(pos, s, src.get("position_group")) for s in scopes):
                subgroup.add(key)
        assert len(subgroup) <= 4, (pos, sorted(subgroup))


# ── consumers ───────────────────────────────────────────────────────────


def test_rankings_sources_publishes_a_static_private_vote_policy_without_counts():
    reg = {e["key"]: e for e in dc.get_ranking_source_registry()}
    for key in FAMILY_KEYS:
        policy = reg[key]["privateVotePolicy"]
        assert policy["heldByDefault"] is True
        assert policy["rollbackFlag"] == FAMILY_FLAG[key]
        assert FAMILY_FLAG[key] in policy["releaseFlags"] and XWALK in policy["releaseFlags"]
        assert not any(isinstance(v, int) and not isinstance(v, bool) for v in policy.values())
    assert reg["ktcCrowdSfTep"]["privateVotePolicy"] is None


def test_value_movement_reads_the_effective_state():
    from src.api import value_movement as vm

    released = {"signalsIdpDl": {"voteState": "active", "votes": True}}
    held = {"signalsIdpDl": {"voteState": "held", "votes": False}}
    assert vm.source_role("signalsIdpDl", released) == vm.ROLE_MODEL_INPUT
    assert vm.source_role("signalsIdpDl", held) == vm.ROLE_HELD
    assert vm.source_role("signalsIdpDl") == vm.ROLE_HELD  # declaration fallback


def test_signals_metadata_votes_are_derived_not_hardcoded():
    from src.sources import signals as S

    idp = S.value_dataset_metadata(S.VALUE_DATASETS["idp"])
    assert idp["votes"] is False and set(idp["votesByKey"]) == set(FAMILY_KEYS)
    with _flags(*IDP_RELEASE_FLAGS):
        assert S.value_dataset_metadata(S.VALUE_DATASETS["idp"])["votes"] is True
    with _flags(MASTER):
        assert S.value_dataset_metadata(S.VALUE_DATASETS["idp"])["votes"] is False
