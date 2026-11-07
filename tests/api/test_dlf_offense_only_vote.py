"""DLF IDP vote hold: approved restore, HELD AT RELEASE (re-applied 2026-10-19).

History: the owner's policy hold of 2026-10-16 ("DLF vote is offense-only") was
RESCINDED by the universal source-voting directive of 2026-10-19, which approves
restoring DLF IDP and DLF Rookie IDP voting.  The restore is implemented (flag
OFF), but the hold was re-applied the same day as a TEMPORARY release hold:
under the incumbent outlier filter the restore drops valid Draft Sharks IDP /
FantasyPros IDP / IDP Trade Calculator votes (30 rows, moves up to 54%, none
from DLF's own vote), which the directive forbids.  On 2026-10-20 the owner
chose Option 3: those moves are not accepted, and the hold lifts only with the
owner's explicit approval after a preregistered outlier-filter Version 2
passes every mandatory gate -- locked by ``tests/api/test_dlf_idp_hold_locked.py``.
The board tests here force the flag both ways IN-PROCESS, so they pin the hold
AND the (evidence-only) restore path either way.

The owner settled the interpretation docs/sources/SOURCE_VALUATION_AUDIT_2026-10-13.md
left open: the DLF IDP boards (``dlfIdp``, ``dlfRookieIdp``) stay ingested and
displayed but never vote; ``dlfSf`` / ``dlfRookieSf`` vote unchanged; DLF Values
stays held.  Implemented through the EXISTING vote-hold gate
(``data_contract.POLICY_SOURCE_VOTE_HOLDS`` feeds the same active-source gate
seasonal inactivity and the private holds use) with the flag
``dlf_offense_only_vote`` (``RISKIT_FEATURE_DLF_OFFENSE_ONLY_VOTE=0`` + restart
lifts the hold: the approved restore).

Two halves: declaration / surface properties that need no board, and
invariants on the newest complete archived scrape built twice (flag ON and
OFF) — every board assertion is all-of / none-of, never a count, so a refresh
of the archive or the CSVs cannot flip it.
"""

from __future__ import annotations

import copy

import pytest

import src.api.data_contract as dc
from src.api import feature_flags
from tests.archive_fixtures import newest_complete_raw_payload

_HELD = ("dlfIdp", "dlfRookieIdp")
_DLF_OFFENSE = ("dlfSf", "dlfRookieSf")
_FLAG = "dlf_offense_only_vote"
_ENV = "RISKIT_FEATURE_DLF_OFFENSE_ONLY_VOTE"
_REASON = "owner_policy_dlf_idp_restore_held_pending_outlier_fix"
_LEVEL = {"none": -1, "low": 0, "medium": 1, "high": 2}
#: Axes that measure the QUALITY of a family's own evidence.  A family that
#: leaves the panel can legitimately lift a row only through one of these —
#: never through independence or coverage, which would mean its SILENCE
#: (not its evidence) had been holding the row down.
_EVIDENCE_QUALITY_AXES = {"agreement", "freshness", "applicability"}


@pytest.fixture
def flag(monkeypatch):
    def _set(on: bool) -> None:
        monkeypatch.setenv(_ENV, "1" if on else "0")
        feature_flags.reload()

    yield _set
    feature_flags.reload()


# ── declaration / surface ─────────────────────────────────────────────────


def test_the_hold_names_exactly_the_dlf_idp_boards():
    offense_only = {k for k, h in dc.POLICY_SOURCE_VOTE_HOLDS.items() if h["flag"] == _FLAG}
    assert offense_only == set(_HELD)
    registered = set(dc.get_ranking_source_keys())
    assert set(_HELD) <= registered, "a held source stays REGISTERED (ingested + displayed)"
    for key in _DLF_OFFENSE:
        assert key in registered and key not in dc.POLICY_SOURCE_VOTE_HOLDS
    # DLF Values (owner closeout 2026-10-18 Decision 4) is registered as an
    # offense-only DLF member under its OWN release hold, never this one.
    assert "dlfValuesSfTep" in registered
    assert dc.POLICY_SOURCE_VOTE_HOLDS["dlfValuesSfTep"]["flag"] == "dlf_values_rank_hill_vote"


def test_the_restore_is_held_at_release_by_default_and_the_flag_is_live(flag):
    """The owner approved the restore (2026-10-19); it is held at release
    pending the outlier fix (CQ-65), so the hold is IN FORCE by default and
    ``=0`` lifts it (the restore path stays one flag away)."""
    assert feature_flags._DEFAULTS[_FLAG] is True
    assert feature_flags.gate_status(_FLAG) == feature_flags.LIVE
    assert set(_HELD) <= set(dc._policy_source_vote_holds())
    flag(False)
    assert not set(_HELD) & set(dc._policy_source_vote_holds())


def test_the_hold_says_it_is_temporary_and_names_its_lift_condition():
    """A release hold, never an indefinite exclusion: the published reason and
    decision name the approved restore and the outlier-fix lift condition."""
    for key in _HELD:
        hold = dc.POLICY_SOURCE_VOTE_HOLDS[key]
        assert hold["reason"] == _REASON
        assert "2026-10-19" in hold["decision"]
        assert "approves the DLF IDP restore" in hold["decision"]
        assert "temporary" in hold["decision"] and "CQ-65" in hold["decision"]


def test_registry_surface_names_the_hold_with_a_reason(flag):
    flag(True)
    reg = {s["key"]: s for s in dc.get_ranking_source_registry()}
    for key in _HELD:
        hold = reg[key]["voteHold"]
        assert hold and hold["reason"] == _REASON
        assert "2026-10-19" in hold["decision"]
    for key in _DLF_OFFENSE:
        assert reg[key]["voteHold"] is None
    flag(False)
    reg = {s["key"]: s for s in dc.get_ranking_source_registry()}
    assert all(reg[k]["voteHold"] is None for k in _HELD)


def test_vote_state_stamp_marks_held_public_sources(flag):
    flag(True)
    state = dc._source_vote_state()
    for key in _HELD:
        entry = state[key]
        assert entry["private"] is False
        assert entry["holdKind"] == dc.VOTE_HOLD_KIND_OWNER_POLICY
        assert entry["votes"] is False
        assert entry["heldFromVote"] == _REASON
    # The coverage gates (CI watchdog, deploy verifier, validator) excuse a
    # source by the board's own stamp through this one reader.
    assert set(_HELD) <= dc.private_sources_absent_by_design(state)
    flag(False)
    state = dc._source_vote_state()
    assert not set(_HELD) & set(state)


# ── the real board, ON vs OFF ─────────────────────────────────────────────


@pytest.fixture(scope="module")
def boards():
    raw, name = newest_complete_raw_payload()
    if raw is None:
        pytest.skip("no complete archived scrape available")
    mp = pytest.MonkeyPatch()
    try:
        out = {}
        for on in (True, False):
            mp.setenv(_ENV, "1" if on else "0")
            feature_flags.reload()
            out[on] = dc.build_api_data_contract(copy.deepcopy(raw))
    finally:
        mp.undo()
        feature_flags.reload()
    return out


def _rows(contract):
    return {
        str(r.get("displayName") or r.get("canonicalName")): r
        for r in contract["playersArray"]
        if isinstance(r, dict)
    }


def _voters(row):
    return set(row.get("sourceRankMeta") or {})


def test_dlf_idp_never_votes_with_the_flag_on(boards):
    for row in boards[True]["playersArray"]:
        assert not _voters(row) & set(_HELD), row.get("displayName")
        assert not set((row.get("sourceRanks") or {})) & set(_HELD)


def test_dlf_idp_votes_with_the_flag_off(boards):
    observed = {
        k
        for r in boards[False]["playersArray"]
        for k in _HELD
        if (r.get("canonicalSiteValues") or {}).get(k)
    }
    voted = {k for r in boards[False]["playersArray"] for k in _voters(r) & set(_HELD)}
    assert observed, "archive carries no DLF IDP observations"
    assert voted == observed


def test_dlf_idp_stays_ingested_and_stamped_held(boards):
    on = boards[True]
    assert any((r.get("canonicalSiteValues") or {}).get("dlfIdp") for r in on["playersArray"])
    stamp = on["privateSourceAvailability"]
    for key in _HELD:
        assert stamp[key]["holdKind"] == "owner_policy" and stamp[key]["votes"] is False
    assert not set(_HELD) & set(boards[False]["privateSourceAvailability"])


def test_dlf_offense_boards_still_vote(boards):
    for key in _DLF_OFFENSE:
        observed = any(
            (r.get("canonicalSiteValues") or {}).get(key) for r in boards[True]["playersArray"]
        )
        if not observed:
            continue
        assert any(key in _voters(r) for r in boards[True]["playersArray"]), key


def test_no_row_is_zeroed_or_newly_unpriced(boards):
    on, off = _rows(boards[True]), _rows(boards[False])
    assert set(on) == set(off)
    for name, row in on.items():
        assert row.get("rankDerivedValue") != 0, name
        if (off[name].get("rankDerivedValue") or 0) > 0:
            assert (row.get("rankDerivedValue") or 0) > 0, f"{name} lost its price"


def test_offense_values_do_not_move_and_moved_picks_are_tethered(boards):
    """Offense never priced off DLF IDP; current-year slot picks inherit the
    merged (offense + IDP) rookie pool, so they may re-tether — nothing else.
    The two-way boost reads IDP sources, so a two-way player may move."""
    on, off = _rows(boards[True]), _rows(boards[False])
    for name, row in on.items():
        before, after = off[name].get("rankDerivedValue"), row.get("rankDerivedValue")
        if before == after:
            continue
        if row.get("assetClass") == "pick":
            prov = row.get("pickValueProvenance") or {}
            assert prov.get("class") == "rookie_pool_tether", (name, prov)
        elif row.get("assetClass") != "idp":
            assert name in dc._TWO_WAY_PLAYERS, f"offense row {name} moved {before}->{after}"


#: The confidence gate's stamp for a vote that reached the value but that the
#: gate's REPLAY of the outlier test rejects (``data_contract._lost_evidence_replay``
#: case (c), flag ``confidence_cured_rejection_guard``).
_CURED_REJECTION = "rejected_with_withheld_votes"


def _cured_rejections(row):
    """Voting sources the row's confidence gate declined to credit because the
    outlier test, replayed on the OBSERVED panel, rejects them."""
    return {
        key
        for key, meta in (row.get("sourceRankMeta") or {}).items()
        if isinstance(meta, dict) and meta.get("confidenceUncredited") == _CURED_REJECTION
    }


def _recovered_evidence(on_row, off_row):
    """Non-held sources the restore board's outlier test REJECTED that the
    held board CREDITS -- evidence the hold gives back, not silence.

    The restore board records an outlier rejection in one of two places, and
    both are the SAME incumbent test:

    * ``droppedSources`` -- the blend's own filter rejected the vote;
    * ``sourceRankMeta[src].confidenceUncredited == "rejected_with_withheld_votes"``
      -- the vote reached the value only because a freshness-withheld source
      left the panel; the confidence gate replays the same filter on the
      OBSERVED panel (voting + withheld values, ``_lost_evidence_replay``
      case (c)), that replay rejects the vote, so the gate credits it nothing.
      Measured on ``dynasty_export_20261107_133702``: Edgerrin Cooper, with
      The IDP Show withheld as stale (3541).  Restore panel: IDPTC 3339,
      DLF IDP 3326, FantasyPros IDP 4698, Draft Sharks IDP 4754 -- the blend
      drops nothing, but the replay with The IDP Show rejects FantasyPros and
      Draft Sharks (median 3541, MAD 215 -> threshold floored at 1000; they sit
      1157 / 1213 away -- DLF's vote beside IDPTC and The IDP Show collapses
      the spread).  Held panel: the replay rejects nothing (median 4119.5,
      threshold 1668), both are credited, coverage 2 of 5 -> 3 of 4 eligible
      families, bucket low -> medium.  DLF's vote is the but-for cause --
      the CQ-65 defect the hold exists to prevent, reached through the
      guard's replay instead of the blend.  Nick Bolton is the same case
      (3605 / 3383 / 3503 / 4783 / 4901).

    CREDITED on the held board means voting, not dropped AND not uncredited:
    a vote the held board's gate still declines to credit is not evidence the
    hold gave back, so it cannot explain a coverage / independence rise.

    Residual, named: the guard's own carve-out (every source it would credit
    is cured -> the prior answer, unstamped) publishes those sources as
    credited, so this reads them as credited -- the build's published answer.
    """
    rejected_off = set(off_row.get("droppedSources") or []) | _cured_rejections(off_row)
    credited_on = _voters(on_row) - set(on_row.get("droppedSources") or [])
    credited_on -= _cured_rejections(on_row)
    return (rejected_off - set(_HELD)) & credited_on


def test_recovered_evidence_requires_a_rejected_vote_the_hold_keeps():
    """Synthetic (no live board): the admissible coverage / independence rise
    needs a non-held vote rejected under the restore and kept under the hold.
    Silence alone -- or a vote rejected on both boards, or a held source's own
    rejection -- recovers nothing."""
    off = {
        "sourceRankMeta": {"dlfIdp": {}, "fantasyProsIdp": {}, "idpTradeCalc": {}},
        "droppedSources": ["fantasyProsIdp"],
    }
    kept = {"sourceRankMeta": {"fantasyProsIdp": {}, "idpTradeCalc": {}}, "droppedSources": []}
    assert _recovered_evidence(kept, off) == {"fantasyProsIdp"}
    still_rejected = dict(kept, droppedSources=["fantasyProsIdp"])
    assert _recovered_evidence(still_rejected, off) == set()
    silence = {"sourceRankMeta": {"idpTradeCalc": {}}, "droppedSources": []}
    assert _recovered_evidence(silence, dict(off, droppedSources=[])) == set()
    held_only = dict(off, droppedSources=["dlfIdp"])
    assert _recovered_evidence(kept, held_only) == set()
    # Kept in the held board's blend but NOT credited by its gate: no recovery.
    kept_uncredited = {
        "sourceRankMeta": {
            "fantasyProsIdp": {"confidenceUncredited": _CURED_REJECTION},
            "idpTradeCalc": {},
        },
        "droppedSources": [],
    }
    assert _recovered_evidence(kept_uncredited, off) == set()


def test_recovered_evidence_reads_the_gates_replay_rejection_too():
    """Synthetic (no live board): a restore-board vote the confidence gate
    left uncredited as a cured rejection, credited on the held board, is
    recovered evidence -- the same outlier test as ``droppedSources``, read
    where the guard records it.  Any other stamp, a held source's own stamp,
    or a vote the held board's gate still declines recovers nothing."""
    cured = {"confidenceUncredited": _CURED_REJECTION}
    off = {
        "sourceRankMeta": {
            "dlfIdp": {},
            "idpTradeCalc": {},
            "fantasyProsIdp": dict(cured),
            "draftSharksIdp": dict(cured),
        },
        "droppedSources": [],
    }
    on = {
        "sourceRankMeta": {"idpTradeCalc": {}, "fantasyProsIdp": {}, "draftSharksIdp": {}},
        "droppedSources": [],
    }
    assert _recovered_evidence(on, off) == {"fantasyProsIdp", "draftSharksIdp"}
    still_cured = copy.deepcopy(on)
    still_cured["sourceRankMeta"]["draftSharksIdp"] = dict(cured)
    assert _recovered_evidence(still_cured, off) == {"fantasyProsIdp"}
    other_stamp = copy.deepcopy(off)
    other_stamp["sourceRankMeta"]["fantasyProsIdp"] = {"confidenceUncredited": "something_else"}
    other_stamp["sourceRankMeta"]["draftSharksIdp"] = {}
    assert _recovered_evidence(on, other_stamp) == set()
    held_stamp = copy.deepcopy(off)
    held_stamp["sourceRankMeta"] = {"dlfIdp": dict(cured), "idpTradeCalc": {}}
    assert _recovered_evidence(on, held_stamp) == set()


def test_a_held_vote_can_make_the_gates_replay_reject_valid_votes():
    """The mechanism, on the production replay with the measured Edgerrin
    Cooper values (``dynasty_export_20261107_133702``; The IDP Show withheld
    as stale): with DLF IDP voting the observed-panel replay rejects
    FantasyPros IDP and Draft Sharks IDP although the blend kept them; with
    DLF IDP held it rejects nothing.  So the held board's credit for them is
    evidence the hold gives back, not the held family's silence."""
    show = [("idpShowCombined", 3541.0)]
    held_panel = [("idpTradeCalc", 3339.0), ("fantasyProsIdp", 4698.0), ("draftSharksIdp", 4754.0)]
    restore_panel = held_panel + [("dlfIdp", 3326.0)]
    for panel in (restore_panel, held_panel):
        assert dc._hampel_filter_per_player(panel, k=dc._HAMPEL_K, min_n=dc._HAMPEL_MIN_N)[1] == []
    restore = dc._lost_evidence_replay(
        voting_pairs=restore_panel, withheld_pairs=show, dropped_now=[], outlier_test_applies=True
    )
    held = dc._lost_evidence_replay(
        voting_pairs=held_panel, withheld_pairs=show, dropped_now=[], outlier_test_applies=True
    )
    assert sorted(restore.cured) == ["draftSharksIdp", "fantasyProsIdp"]
    assert held.cured == []
    assert restore.seats == held.seats == ["idpShowCombined"]


def test_no_confidence_rise_from_the_held_familys_silence(boards):
    """A policy hold makes DLF IDP ineligible (not lost evidence) — the
    posture every declared methodology state already has (seasonal
    inactivity, the Signals IDP hold).  A row may therefore rise only where
    DLF IDP VOTED and either

    * was itself the weak evidence (disagreeing / stale / inapplicable): the
      bottleneck is an evidence-quality axis; or
    * its vote made the incumbent outlier filter reject ANOTHER family's
      valid vote (the CQ-65 defect the hold exists to prevent) -- in the
      blend, or in the confidence gate's replay of that filter over the
      observed panel (``_recovered_evidence``): the held board credits that
      vote, so independence / coverage rise on RECOVERED evidence.

    Never via coverage or independence with nothing recovered -- that would
    mean the held family's SILENCE, not evidence, had lifted the row."""
    on, off = _rows(boards[True]), _rows(boards[False])
    for name, row in on.items():
        old = off[name]
        if _LEVEL.get(row.get("confidenceBucket"), -2) <= _LEVEL.get(
            old.get("confidenceBucket"), -2
        ):
            continue
        assert _voters(old) & set(_HELD), f"{name} rose without a DLF IDP vote to lose"
        axes = old.get("confidenceAxes") or {}
        bottleneck = {ax for ax, lvl in axes.items() if lvl == old.get("confidenceBucket")}
        assert bottleneck, (name, axes)
        if bottleneck <= _EVIDENCE_QUALITY_AXES:
            continue
        recovered = _recovered_evidence(row, old)
        assert recovered, (
            f"{name} rose through {sorted(bottleneck - _EVIDENCE_QUALITY_AXES)} "
            "with no outlier-rejected vote recovered",
            axes,
        )


def test_contract_validates_in_both_lanes_shape(boards):
    report = dc.validate_api_data_contract(boards[True])
    assert not report.get("structuralErrors"), report.get("structuralErrors")
    assert not any(e.startswith("source_missing:dlf") for e in report.get("errors") or [])


def test_ci_coverage_watchdog_excuses_the_held_boards(boards, monkeypatch):
    """The CI contract-coverage watchdog (and, through the same decision
    core, the deploy verifier) reads ``sourceRankMeta`` membership.  A held
    board contributes to no row, so it must be excused by the board's own
    stamp — otherwise every deploy would fail its coverage gate."""
    from scripts import watchdog_contract_coverage as wcc

    monkeypatch.setattr(wcc, "_csv_nonempty", lambda key: True)
    fresh = {k: {"ageHours": 0.0} for k in dc.get_ranking_source_keys()}
    violations, _ok, skipped = wcc.evaluate_coverage(boards[True], fresh, {})
    assert not {k for k, _ in violations} & set(_HELD), violations
    assert set(_HELD) <= set(skipped)
