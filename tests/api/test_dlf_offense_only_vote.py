"""DLF vote offense-only (owner directive 2026-10-16).

The owner settled the interpretation docs/sources/SOURCE_VALUATION_AUDIT_2026-10-13.md
left open: the DLF IDP boards (``dlfIdp``, ``dlfRookieIdp``) stay ingested and
displayed but never vote; ``dlfSf`` / ``dlfRookieSf`` vote unchanged; DLF Values
stays held.  Implemented through the EXISTING vote-hold gate
(``data_contract.POLICY_SOURCE_VOTE_HOLDS`` feeds the same active-source gate
seasonal inactivity and the private holds use) with the rollback flag
``dlf_offense_only_vote`` (``RISKIT_FEATURE_DLF_OFFENSE_ONLY_VOTE=0`` + restart).

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
    assert set(dc.POLICY_SOURCE_VOTE_HOLDS) == set(_HELD)
    registered = set(dc.get_ranking_source_keys())
    assert set(_HELD) <= registered, "a held source stays REGISTERED (ingested + displayed)"
    for key in _DLF_OFFENSE:
        assert key in registered and key not in dc.POLICY_SOURCE_VOTE_HOLDS
    # DLF Values is not a voter today and this change does not make it one.
    assert "dlfValuesSfTep" not in registered
    assert all(h["flag"] == _FLAG for h in dc.POLICY_SOURCE_VOTE_HOLDS.values())


def test_flag_defaults_on_and_is_live():
    assert feature_flags._DEFAULTS[_FLAG] is True
    assert feature_flags.gate_status(_FLAG) == feature_flags.LIVE


def test_registry_surface_names_the_hold_with_a_reason(flag):
    flag(True)
    reg = {s["key"]: s for s in dc.get_ranking_source_registry()}
    for key in _HELD:
        hold = reg[key]["voteHold"]
        assert hold and hold["reason"] == "owner_policy_dlf_vote_offense_only"
        assert "2026-10-16" in hold["decision"]
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
        assert entry["heldFromVote"] == "owner_policy_dlf_vote_offense_only"
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


def test_no_confidence_rise_from_the_held_familys_silence(boards):
    """A policy hold makes DLF IDP ineligible (not lost evidence) — the
    posture every declared methodology state already has (seasonal
    inactivity, the Signals IDP hold).  A row may therefore rise only where
    DLF IDP VOTED and was itself the weak evidence (disagreeing / stale /
    inapplicable); never via coverage or independence."""
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
        assert bottleneck and bottleneck <= _EVIDENCE_QUALITY_AXES, (name, axes)


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
