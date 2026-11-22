"""The rookie-class guard on the current-year pick tether (flag
``pick_class_tether_guard``, default OFF, owner-held).

The defect: ``_anchor_current_year_picks_to_rookies`` tethered the active slot
class to EVERY ``rookie`` row.  In season the active slot class is next year's
(vendors publish 2027 slots in November) while the ``rookie`` rows are the class
that was just drafted, so "2027 Pick 1.01" inherited Jeremiyah Love's value — a
2026 rookie already in the NFL.  The guard asks the class owner
(``src/draft/rookie_auction/class_snapshot.py::class_identity``) which class each
rookie belongs to and tethers a slot of year Y only to class-Y rookies.

Pinned here:

* synthetic: same-class tether unchanged; mismatched class not tethered; mixed
  pools keep only the proven class; unknown observed season tethers nothing;
  an explicit ``eligibleDraftYear`` wins;
* completion: a refused slot no market prices is derived from the previous slot,
  monotone, never left unpriced;
* the pinned board (frozen inputs, in season): OFF carries no guard stamp and
  calls the incumbent pass with its incumbent arguments; ON moves only
  current-year slot picks, prices every one of them with provenance, and
  validates clean; the census catches an unpriced slot when the guard is on.

Byte identity of the flag-OFF board against the pre-change code is MEASURED (the
committed evidence, ``docs/picks/PICK_CLASS_GUARD_EVIDENCE_2026-11-21.md`` §3):
the sha256 of the full contract is equal on three boards.
"""

from __future__ import annotations

import copy
import math
import re
from typing import Any

import pytest

from src.api import data_contract as dc
from src.api import feature_flags
from tests.archive_fixtures import build_pinned_contract

_FLAG = "pick_class_tether_guard"
_ENV = "RISKIT_FEATURE_PICK_CLASS_TETHER_GUARD"
_SLOT = re.compile(r"^(\d{4}) Pick (\d)\.(\d\d)$")


def _rookie(name: str, value: int, *, years_exp: int | None = 0, **extra: Any) -> dict[str, Any]:
    row = {
        "canonicalName": name,
        "assetClass": "offense",
        "rookie": True,
        "yearsExp": years_exp,
        "canonicalConsensusRank": 10000 - value,
        "rankDerivedValue": value,
    }
    row.update(extra)
    return row


def _pick(name: str, value: int | None) -> dict[str, Any]:
    return {
        "canonicalName": name,
        "assetClass": "pick",
        "rookie": False,
        "canonicalConsensusRank": None,
        "rankDerivedValue": value,
        "canonicalSiteValues": {"idpTradeCalc": value} if value else {},
    }


def _slot_picks(year: int, rounds: int = 2, value_of=lambda r, s: 5000 - 100 * r - s):
    return [
        _pick(f"{year} Pick {r}.{s:02d}", value_of(r, s))
        for r in range(1, rounds + 1)
        for s in range(1, 13)
    ]


@pytest.fixture(autouse=True)
def _twelve_teams(monkeypatch):
    monkeypatch.setattr(dc, "_resolve_league_roster_count", lambda *a, **k: 12)


# ── the anchor pass, synthetic ────────────────────────────────────────────


def test_same_class_pool_tethers_exactly_as_the_incumbent_pass() -> None:
    """Pre-draft: every rookie is the slot year's class, so the guard changes
    nothing the tether writes (values, anchors, evidence, confidence)."""
    rookies = [_rookie(f"R{i:02d}", 9000 - 37 * i) for i in range(1, 31)]
    base = rookies + _slot_picks(2026)
    plain, guarded = copy.deepcopy(base), copy.deepcopy(base)
    n_plain = dc._anchor_current_year_picks_to_rookies(plain, 2026)
    report: dict[str, Any] = {}
    n_guarded = dc._anchor_current_year_picks_to_rookies(
        guarded, 2026, class_guard=True, observed_nfl_season=2026, guard_report=report
    )
    assert n_plain == n_guarded == 24
    assert plain == guarded
    assert report["rookiePool"] == {
        "considered": 30,
        "sameClass": 30,
        "otherClassByYear": {},
        "unprovableByReason": {},
    }
    assert report["tethered"] == 24 and report["withheldSlots"] == {}
    assert report["classIdentityOwner"] == dc.PICK_CLASS_IDENTITY_OWNER


def test_mismatched_class_is_not_tethered() -> None:
    """In season: slots are 2027, the rookies are the 2026 class."""
    rookies = [_rookie(f"R{i:02d}", 9000 - 37 * i) for i in range(1, 31)]
    picks = _slot_picks(2027)
    before = copy.deepcopy(picks)
    report: dict[str, Any] = {}
    n = dc._anchor_current_year_picks_to_rookies(
        rookies + picks, 2027, class_guard=True, observed_nfl_season=2026, guard_report=report
    )
    assert n == 0
    assert picks == before, "a refused slot keeps its market blend untouched"
    assert report["rookiePool"]["sameClass"] == 0
    assert report["rookiePool"]["otherClassByYear"] == {"2026": 30}
    assert len(report["withheldSlots"]) == 24
    assert set(report["withheldSlots"].values()) == {dc.TETHER_WITHHELD_NO_SAME_CLASS}
    # The incumbent pass tethers the same board — the defect.
    assert dc._anchor_current_year_picks_to_rookies(rookies + copy.deepcopy(before), 2027) == 24


def test_mixed_pool_keeps_only_the_proven_class_in_value_order() -> None:
    same = [_rookie(f"New{i:02d}", 8000 - 50 * i) for i in range(1, 6)]
    older = [_rookie(f"Old{i:02d}", 8975 - 50 * i, years_exp=1) for i in range(1, 6)]
    unprovable = [_rookie("NoExp", 9500, years_exp=None)]
    picks = _slot_picks(2026, rounds=1)
    report: dict[str, Any] = {}
    n = dc._anchor_current_year_picks_to_rookies(
        same + older + unprovable + picks,
        2026,
        class_guard=True,
        observed_nfl_season=2026,
        guard_report=report,
    )
    assert n == 5
    assert [p["pickRookieAnchor"] for p in picks[:5]] == [r["canonicalName"] for r in same]
    assert [p["rankDerivedValue"] for p in picks[:5]] == [r["rankDerivedValue"] for r in same]
    assert report["rookiePool"]["otherClassByYear"] == {"2025": 5}
    assert report["rookiePool"]["unprovableByReason"] == {"unprovable:no_years_exp": 1}
    assert set(report["withheldSlots"]) == {f"2026 Pick 1.{s:02d}" for s in range(6, 13)}
    assert set(report["withheldSlots"].values()) == {dc.TETHER_WITHHELD_POOL_EXHAUSTED}


def test_unknown_observed_season_tethers_nothing() -> None:
    rookies = [_rookie(f"R{i:02d}", 9000 - 37 * i) for i in range(1, 31)]
    report: dict[str, Any] = {}
    n = dc._anchor_current_year_picks_to_rookies(
        rookies + _slot_picks(2026),
        2026,
        class_guard=True,
        observed_nfl_season=None,
        guard_report=report,
    )
    assert n == 0
    assert set(report["withheldSlots"].values()) == {dc.TETHER_WITHHELD_SEASON_UNKNOWN}
    assert report["rookiePool"]["unprovableByReason"] == {
        "unprovable:observation_season_unknown": 30
    }


def test_an_explicit_eligible_draft_year_wins() -> None:
    rookies = [
        _rookie(f"R{i:02d}", 9000 - 37 * i, years_exp=None, eligibleDraftYear=2027)
        for i in range(1, 13)
    ]
    picks = _slot_picks(2027, rounds=1)
    n = dc._anchor_current_year_picks_to_rookies(
        rookies + picks, 2027, class_guard=True, observed_nfl_season=2026, guard_report={}
    )
    assert n == 12 and picks[0]["pickRookieAnchor"] == "R01"


def test_observed_season_comes_from_the_board_date() -> None:
    assert dc._observed_nfl_season_for_board("2026-11-21") == 2026
    assert dc._observed_nfl_season_for_board("2027-01-10") == 2026  # week 18 spills over
    assert dc._observed_nfl_season_for_board("2026-07-14") == 2026
    assert dc._observed_nfl_season_for_board(None) is None
    assert dc._observed_nfl_season_for_board("not a date") is None
    # A board dated in another year must not read today's season off the
    # clock: these only pass if the board's own date drives the resolver.
    assert dc._observed_nfl_season_for_board("2028-03-01") == 2028
    assert dc._observed_nfl_season_for_board("2028-01-31") == 2027
    assert dc._observed_nfl_season_for_board("2031-09-15") == 2031


def test_a_pool_with_no_provable_class_is_named_unprovable_not_empty() -> None:
    """Pre-draft (Feb-Apr) the scraper marks prospects ``_isRookie`` with no
    ``yearsExp``: none is PROVEN to be the slot's class.  The refusal says so,
    rather than "no same-class rookies"."""
    prospects = [_rookie(f"P{i:02d}", 9000 - 37 * i, years_exp=None) for i in range(1, 31)]
    picks = _slot_picks(2027)
    report: dict[str, Any] = {}
    n = dc._anchor_current_year_picks_to_rookies(
        prospects + picks, 2027, class_guard=True, observed_nfl_season=2027, guard_report=report
    )
    assert n == 0
    assert report["rookiePool"]["unprovableByReason"] == {"unprovable:no_years_exp": 30}
    assert set(report["withheldSlots"].values()) == {dc.TETHER_WITHHELD_UNPROVABLE}
    assert report["leagueSize"] > 0 and report["anchorRounds"] == dc._ROOKIE_ANCHOR_ROUNDS


# ── completion of refused slots, synthetic ────────────────────────────────


def test_refused_slots_with_no_market_are_derived_monotone() -> None:
    r4 = [_pick(f"2027 Pick 4.{s:02d}", 1800 - 30 * s) for s in range(1, 13)]
    r5 = [_pick(f"2027 Pick 5.{s:02d}", None) for s in range(1, 13)]
    r6 = [_pick(f"2027 Pick 6.{s:02d}", None) for s in range(1, 13)]
    rows = r4 + r5 + r6
    guard = {"withheldSlots": {r["canonicalName"]: dc.TETHER_WITHHELD_NO_SAME_CLASS for r in rows}}
    dc._complete_future_pick_values(rows, {}, 2027, horizon_end_year=2027, tether_guard=guard)
    values = [r["rankDerivedValue"] for r in rows]
    assert all(isinstance(v, int) and v > 0 for v in values), "never left unpriced"
    assert all(a > b for a, b in zip(values, values[1:])), "earlier picks are worth more"
    step5 = dc._load_pick_year_discount()["roundStepByRound"]["5"]
    assert r5[-1]["rankDerivedValue"] == pytest.approx(r4[-1]["rankDerivedValue"] * step5, abs=6)
    prov = r5[0]["pickValueProvenance"]
    assert prov["class"] == "derived_round_step" and prov["basis"] == "2027 Pick 4.12"
    assert prov["appliedAs"] == "slot_continuation" and prov["slotsPerRound"] == 12
    assert prov["tetherWithheld"] == {
        "reason": dc.TETHER_WITHHELD_NO_SAME_CLASS,
        "anchorYear": 2027,
    }
    assert r4[0]["pickValueProvenance"]["class"] == "direct_market_blend"
    assert r5[0]["confidenceBasis"] == "derived_round_step"
    assert guard["derivedSlots"] == 24 and guard["withheldUnpriced"] == []


def test_a_refused_slot_with_no_slot_market_takes_its_tier_market_blend() -> None:
    """The IDP Trade Calculator cutoff (owner 2026-10-07) with the guard on:
    the only slot market is withheld, so rounds 1-4 have no slot value and no
    round step.  They are priced at their TIER's market blend (captured before
    alias suppression), never left unpriced; rounds 5-6 then continue from it."""
    r1 = [_pick(f"2027 Pick 1.{s:02d}", None) for s in range(1, 13)]
    r5 = [_pick(f"2027 Pick 5.{s:02d}", None) for s in range(1, 13)]
    tiers = {"2027 Early 1st": 6584.0, "2027 Mid 1st": 5482.0, "2027 Late 1st": 4909.0}
    tier_rows = [_pick(name, None) for name in tiers]
    for row in tier_rows:
        row["pickGenericSuppressed"] = True
        row["pickEvidence"] = {"state": "single_provider", "valueBasis": "market_blend"}
    rows = r1 + r5 + tier_rows
    guard = {
        "withheldSlots": {r["canonicalName"]: dc.TETHER_WITHHELD_NO_SAME_CLASS for r in r1 + r5}
    }
    dc._complete_future_pick_values(
        rows, {}, 2027, horizon_end_year=2027, tether_guard=guard, guard_tier_values=tiers
    )
    assert [r["rankDerivedValue"] for r in r1] == [6584] * 4 + [5482] * 4 + [4909] * 4
    prov = r1[0]["pickValueProvenance"]
    assert prov["class"] == "direct_market_blend" and prov["grade"] == "tier"
    assert prov["basis"] == "2027 Early 1st"
    assert prov["tetherWithheld"]["reason"] == dc.TETHER_WITHHELD_NO_SAME_CLASS
    assert r1[0]["pickEvidence"] == {"state": "single_provider", "valueBasis": "market_blend"}
    assert r1[0]["confidenceBasis"] == "derived_tier_values"
    # Round 5 has no tier market here; it continues from 1.12 by the round step.
    assert r5[0]["pickValueProvenance"]["basis"] == "2027 Pick 1.12"
    assert all(isinstance(r["rankDerivedValue"], int) for r in r5)
    assert guard["withheldUnpriced"] == []


def test_completion_without_the_guard_leaves_current_slots_alone() -> None:
    rows = [_pick(f"2027 Pick 5.{s:02d}", None) for s in range(1, 13)]
    dc._complete_future_pick_values(rows, {}, 2027, horizon_end_year=2027)
    assert all(r["rankDerivedValue"] is None for r in rows)
    assert all(r["pickValueProvenance"]["class"] == "unavailable" for r in rows)
    assert all("tetherWithheld" not in r["pickValueProvenance"] for r in rows)


# ── the pinned board (in season: 2026-11-15, slots are 2027) ──────────────

_BOARDS: dict[bool, dict[str, Any]] = {}


def _board(guard: bool, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    if guard not in _BOARDS:
        monkeypatch.setenv(_ENV, "1" if guard else "0")
        feature_flags.reload()
        try:
            assert feature_flags.is_enabled(_FLAG) is guard
            _BOARDS[guard] = build_pinned_contract()
        finally:
            monkeypatch.delenv(_ENV, raising=False)
            feature_flags.reload()
    return _BOARDS[guard]


def _rows(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(r.get("canonicalName")): r for r in contract["playersArray"]}


def _slot_key(name: str) -> tuple[int, int, int]:
    m = _SLOT.match(name)
    assert m, name
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def test_the_flag_is_registered_default_off() -> None:
    feature_flags.reload()
    assert feature_flags._DEFAULTS[_FLAG] is False
    assert feature_flags.is_enabled(_FLAG) is False


def test_flag_off_runs_the_incumbent_pass_and_stamps_nothing(monkeypatch) -> None:
    calls: dict[str, list[Any]] = {"anchor": [], "complete": []}
    real_anchor = dc._anchor_current_year_picks_to_rookies
    real_complete = dc._complete_future_pick_values

    def spy_anchor(*args, **kwargs):
        calls["anchor"].append(kwargs)
        return real_anchor(*args, **kwargs)

    def spy_complete(*args, **kwargs):
        calls["complete"].append(kwargs.get("tether_guard", "absent"))
        return real_complete(*args, **kwargs)

    monkeypatch.setattr(dc, "_anchor_current_year_picks_to_rookies", spy_anchor)
    monkeypatch.setattr(dc, "_complete_future_pick_values", spy_complete)
    monkeypatch.setenv(_ENV, "0")
    feature_flags.reload()
    try:
        off = build_pinned_contract()
    finally:
        monkeypatch.delenv(_ENV, raising=False)
        feature_flags.reload()
    assert calls["anchor"] and all(kw == {} for kw in calls["anchor"])
    assert calls["complete"] and all(g is None for g in calls["complete"])
    assert "pickClassTetherGuard" not in off
    year = off["currentDraftYear"]
    slots = [r for n, r in _rows(off).items() if _SLOT.match(n) and _slot_key(n)[0] == year]
    assert len(slots) == 72
    for r in slots:
        prov = r["pickValueProvenance"]
        assert prov["class"] == "rookie_pool_tether"  # the incumbent (defective) tether
        assert "tetherWithheld" not in prov and "rookieClassYear" not in prov


def test_flag_on_moves_only_current_year_slot_picks(monkeypatch) -> None:
    off, on = _rows(_board(False, monkeypatch)), _rows(_board(True, monkeypatch))
    assert off.keys() == on.keys()
    year = _board(True, monkeypatch)["currentDraftYear"]
    moved = [n for n in off if off[n].get("rankDerivedValue") != on[n].get("rankDerivedValue")]
    assert moved, "the in-season board must change with the guard on"
    assert all(_SLOT.match(n) and _slot_key(n)[0] == year for n in moved), moved
    for name, row in off.items():
        if row.get("assetClass") == "pick":
            continue
        for field in ("rankDerivedValue", "canonicalConsensusRank", "canonicalTierId"):
            assert row.get(field) == on[name].get(field), (name, field)


def test_flag_on_prices_every_current_slot_with_provenance(monkeypatch) -> None:
    board = _board(True, monkeypatch)
    guard = board["pickClassTetherGuard"]
    year = board["currentDraftYear"]
    assert guard["anchorYear"] == year and guard["observedNflSeason"] == year - 1
    assert guard["rookiePool"]["sameClass"] == 0 and guard["tethered"] == 0
    assert guard["withheld"] == 72
    assert guard["withheldReasons"] == {dc.TETHER_WITHHELD_NO_SAME_CLASS: 72}
    assert guard["withheldUnpriced"] == []
    slots = sorted(
        (r for n, r in _rows(board).items() if _SLOT.match(n) and _slot_key(n)[0] == year),
        key=lambda r: _slot_key(r["canonicalName"]),
    )
    assert len(slots) == 72
    values = []
    for r in slots:
        v = r["rankDerivedValue"]
        assert isinstance(v, (int, float)) and math.isfinite(v) and v > 0, r["canonicalName"]
        prov = r["pickValueProvenance"]
        assert prov["class"] in ("direct_market_blend", "derived_round_step"), prov
        assert prov["tetherWithheld"]["reason"] == dc.TETHER_WITHHELD_NO_SAME_CLASS
        assert not r.get("pickRookieAnchor")
        assert isinstance(r.get("pickEvidence"), dict)
        assert r["pickEvidence"]["valueBasis"] != "rookie_pool_tether"
        values.append(v)
    assert all(a >= b for a, b in zip(values, values[1:])), "later picks never worth more"
    derived = [r for r in slots if r["pickValueProvenance"]["class"] == "derived_round_step"]
    assert {_slot_key(r["canonicalName"])[1] for r in derived} == {5, 6}
    health = dc.validate_api_data_contract(board)
    assert health["ok"], health["errors"]


def test_the_census_catches_an_unpriced_current_slot_when_the_guard_is_on(monkeypatch) -> None:
    board = copy.deepcopy(_board(True, monkeypatch))
    year = board["currentDraftYear"]
    victim = next(
        r
        for r in board["playersArray"]
        if _SLOT.match(str(r.get("canonicalName"))) and _slot_key(r["canonicalName"])[0] == year
    )
    victim["rankDerivedValue"] = None
    errors = dc.validate_api_data_contract(board)["errors"]
    assert f"pick_completeness_census:{victim['canonicalName']}:missing_or_unpriced" in errors
    # Without the guard stamp the current slotted year stays out of scope (the
    # flag-OFF census is unchanged).
    del board["pickClassTetherGuard"]
    errors = dc.validate_api_data_contract(board)["errors"]
    assert f"pick_completeness_census:{victim['canonicalName']}:missing_or_unpriced" not in errors


def test_the_census_checks_only_the_slot_range_the_tether_covers(monkeypatch) -> None:
    """A vendor slot beyond the tether's league size (or round range) was never
    tethered, flag OFF or ON, so an unpriced one must not fail the ON build."""
    board = copy.deepcopy(_board(True, monkeypatch))
    year = board["currentDraftYear"]
    guard = board["pickClassTetherGuard"]
    extra = f"{year} Pick 1.{guard['leagueSize'] + 1:02d}"
    template = next(
        r for r in board["playersArray"] if r.get("canonicalName") == f"{year} Pick 1.01"
    )
    stray = copy.deepcopy(template)
    stray.update(canonicalName=extra, displayName=extra, rankDerivedValue=None)
    board["playersArray"].append(stray)
    errors = dc.validate_api_data_contract(board)["errors"]
    assert f"pick_completeness_census:{extra}:missing_or_unpriced" not in errors
    # ...while an in-range slot is still owed a value.
    victim = next(r for r in board["playersArray"] if r.get("canonicalName") == f"{year} Pick 2.03")
    victim["rankDerivedValue"] = None
    errors = dc.validate_api_data_contract(board)["errors"]
    assert f"pick_completeness_census:{year} Pick 2.03:missing_or_unpriced" in errors
