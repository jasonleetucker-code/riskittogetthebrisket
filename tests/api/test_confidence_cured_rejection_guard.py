"""Losing evidence never raises confidence — the CURED-rejection half.

Owner directive 2026-10-07 (IDP Trade Calculator's quarantine cutoff): a
withheld vote must never RAISE a row's confidence.  ``_lost_evidence_replay``
re-asks the outlier test of the OBSERVED panel (voting + withheld values) and
classifies every source by what the loss did to it:

* (a) withheld, kept by the observed panel — lost evidence, a SEAT;
* (b) rejected now, kept by the observed panel — a rejection the loss
  CAUSED, a SEAT;
* (c) kept now, rejected by the observed panel — a rejection the loss CURED.
  Not evidence while the withheld source still voted, so the confidence gate
  does not credit it (``confidence_cured_rejection_guard``, default ON): no
  head, and a SEAT for a family left with no credited member — dropped
  outright it would leave the share denominators, and removing a disagreeing
  vote could PROMOTE the row (measured: Jordan Love, agreement 10 of 14 ->
  10 of 13, medium -> high).  Its value vote is untouched;
* rejected on both panels — nothing changed for it, in neither list.

Measured before the guard (newest archive, simulated IDPTC cutoff): IDPTC was
itself rejected on Patrick Mahomes, but its presence in the panel is what
rejected Yahoo/Boone and Draft Sharks; withholding it un-rejected both and
coverage rose 9 -> 11 of 14 families (medium -> high).
"""

from __future__ import annotations

import copy
import random
from typing import Any

import pytest

import src.api.data_contract as dc
from src.api import feature_flags
from src.api.confidence import CONFIDENCE_LEVELS, FamilyEvidence
from tests.archive_fixtures import newest_complete_raw_payload

_LEVEL = {name: i for i, name in enumerate(CONFIDENCE_LEVELS)}
_FLAG = "confidence_cured_rejection_guard"
_ENV = "RISKIT_FEATURE_CONFIDENCE_CURED_REJECTION_GUARD"
_STAMP = "confidenceUncredited"

# A tight cluster plus ``x``: kept on its own, rejected once ``w`` joins.
_CLUSTER = [("a", 5000.0), ("b", 5100.0), ("c", 5200.0), ("d", 5300.0)]
_X = ("x", 6200.0)


def _replay(voting, withheld, **kw) -> dc._LostEvidence:
    dropped_now = kw.pop("dropped_now", None)
    if dropped_now is None:
        _kept, dropped_now = dc._hampel_filter_per_player(list(voting), k=dc._HAMPEL_K)
    return dc._lost_evidence_replay(
        voting_pairs=list(voting),
        withheld_pairs=list(withheld),
        dropped_now=dropped_now,
        outlier_test_applies=kw.pop("outlier_test_applies", True),
        **kw,
    )


# ── the replay: cases (a), (b), (c) and "rejected on both" ─────────────────


def test_fixture_premise_x_is_kept_now_and_rejected_on_the_observed_panel() -> None:
    _k, now = dc._hampel_filter_per_player(_CLUSTER + [_X], k=dc._HAMPEL_K)
    _k, observed = dc._hampel_filter_per_player(_CLUSTER + [_X, ("w", 3000.0)], k=dc._HAMPEL_K)
    assert "x" not in now and "x" in observed and "w" in observed


def test_c_a_rejection_the_loss_cured_is_named_and_never_seated() -> None:
    # The withheld vote is itself an outlier (IDPTC on Mahomes): not a seat.
    lost = _replay(_CLUSTER + [_X], [("w", 3000.0)])
    assert lost.cured == ["x"]
    assert lost.seats == []


def test_a_and_c_together_a_kept_withheld_vote_is_seated_its_cure_named() -> None:
    _k, observed = dc._hampel_filter_per_player(_CLUSTER + [_X, ("w", 4500.0)], k=dc._HAMPEL_K)
    assert observed == ["x"]  # premise: w is kept, x rejected
    lost = _replay(_CLUSTER + [_X], [("w", 4500.0)])
    assert lost.seats == ["w"]
    assert lost.cured == ["x"]


def test_b_a_rejection_the_loss_caused_is_seated_never_cured() -> None:
    # The fixture the seat half was written against: with "w" the panel is
    # wide enough to keep "x"; without it "x" is rejected.
    voting = [(k, 3000.0 + 100 * i) for i, k in enumerate("abcde")] + [("x", 4300.0)]
    lost = _replay(voting, [("w", 4000.0)])
    assert "x" in lost.seats and "w" in lost.seats
    assert lost.cured == []


def test_rejected_on_both_panels_is_in_neither_list() -> None:
    cluster = [(f"s{i}", 1000.0 + 10 * i) for i in range(6)]
    lost = _replay(cluster + [("old", 9000.0)], [("w", 1020.0)])
    assert lost.seats == ["w"]
    assert lost.cured == []


def test_picks_bypass_the_outlier_test_so_nothing_is_cured() -> None:
    lost = _replay(_CLUSTER + [_X], [("w", 3000.0)], dropped_now=[], outlier_test_applies=False)
    assert lost == dc._LostEvidence(["w"], [])


def test_the_non_exact_joint_path_cannot_identify_cured_rejections() -> None:
    lost = _replay(_CLUSTER + [_X], [("w", 3000.0)], exact_replay=False)
    assert lost.cured == []
    assert lost.seats == ["w"]  # the conservative superset, unchanged


def test_a_replay_of_a_different_filter_names_no_cure() -> None:
    lost = _replay(_CLUSTER + [_X], [("w", 3000.0)], cured_identifiable=False)
    assert lost.cured == []
    assert lost.seats == _replay(_CLUSTER + [_X], [("w", 3000.0)]).seats


def test_the_outlier_policy_replay_is_asked_for_cures_too() -> None:
    # A stub policy that rejects "x" on any panel containing "w".
    def policy(observed):
        return ["x"] if any(k == "w" for k, _v in observed) else []

    lost = _replay(_CLUSTER + [_X], [("w", 5150.0)], dropped_now=[], replay=policy)
    assert lost.cured == ["x"]
    assert lost.seats == ["w"]


def _old_seats(*, voting_pairs, withheld_pairs, dropped_now, outlier_test_applies, exact_replay):
    """The seat rule exactly as it stood before the cured-rejection half."""
    withheld = [k for k, _v in withheld_pairs]
    if not outlier_test_applies:
        return withheld
    if not exact_replay:
        return withheld + [k for k in dropped_now if k not in withheld]
    observed = list(voting_pairs) + list(withheld_pairs)
    if len(observed) >= dc._HAMPEL_MIN_N:
        _kept, observed_dropped = dc._hampel_filter_per_player(observed, k=dc._HAMPEL_K)
    else:
        observed_dropped = []
    already = set(observed_dropped)
    return [k for k in withheld if k not in already] + [
        k for k in dropped_now if k not in already and k not in withheld
    ]


def test_seats_are_byte_identical_to_the_prior_rule_on_random_panels() -> None:
    rng = random.Random(20261106)
    for _ in range(2000):
        n = rng.randint(1, 9)
        m = rng.randint(1, 3)
        values = [rng.choice([rng.gauss(5000, 300), rng.uniform(500, 9999)]) for _ in range(n + m)]
        voting = [(f"v{i}", values[i]) for i in range(n)]
        withheld = [(f"w{i}", values[n + i]) for i in range(m)]
        _k, dropped = dc._hampel_filter_per_player(voting, k=dc._HAMPEL_K)
        for applies in (True, False):
            for exact in (True, False):
                kw = dict(
                    voting_pairs=voting,
                    withheld_pairs=withheld,
                    dropped_now=dropped,
                    outlier_test_applies=applies,
                    exact_replay=exact,
                )
                old = _old_seats(**kw)
                assert dc._lost_evidence_seats(**kw) == old
                lost = dc._lost_evidence_replay(**kw)
                assert lost.seats == old
                # (c) is exactly: kept now, rejected by the observed panel.
                if applies and exact:
                    obs = voting + withheld
                    _kk, obs_dropped = (
                        dc._hampel_filter_per_player(obs, k=dc._HAMPEL_K)
                        if len(obs) >= dc._HAMPEL_MIN_N
                        else ([], [])
                    )
                    want = [k for k, _v in voting if k in obs_dropped and k not in dropped]
                    assert lost.cured == want
                else:
                    assert lost.cured == []
                assert not set(lost.cured) & set(lost.seats)


# ── the assembly: an uncredited source is no evidence; its family survives
#    only through another credited member ───────────────────────────────────


def _assemble(uncredited=()):
    return dc._family_evidence_for_row(
        row={"position": "WR"},
        effective_source_ranks={"a1": 1, "a2": 2, "b": 3, "c": 4},
        effective_source_meta={
            "a1": {"appliedWeight": 0.2, "valueContribution": 5000},
            "a2": {"appliedWeight": 0.8, "valueContribution": 5200},
            "b": {"appliedWeight": 1.0, "valueContribution": 5100},
            "c": {"appliedWeight": 1.0, "valueContribution": 7000},
        },
        src_by_key={},
        family_by_key={"a1": "fam", "a2": "fam", "b": "b", "c": "c"},
        fresh_by_source={"a1": True, "a2": True, "b": True, "c": True},
        uncredited=uncredited,
    )


def test_an_uncredited_single_member_family_is_no_evidence() -> None:
    families = {ev.family: ev.source_key for ev in _assemble({"c"})}
    assert families == {"fam": "a2", "b": "b"}


def test_a_family_with_another_credited_member_stays_represented() -> None:
    # "a2" carried the most weight; uncredited, "a1" represents the family.
    by_family = {ev.family: ev for ev in _assemble({"a2"})}
    assert by_family["fam"].source_key == "a1"
    assert by_family["fam"].value_contribution == 5000
    assert all(isinstance(ev, FamilyEvidence) for ev in by_family.values())


def test_no_uncredited_is_the_prior_assembly_exactly() -> None:
    assert _assemble() == _assemble(())
    assert [ev.source_key for ev in _assemble()] == ["a2", "b", "c"]


# ── the board ──────────────────────────────────────────────────────────────


_BOARDS: dict[bool, dict[str, Any]] = {}


def _board(guard: bool, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    if guard not in _BOARDS:
        raw, _archive = newest_complete_raw_payload()
        if raw is None:
            pytest.skip("no complete archived scrape to build a contract from")
        monkeypatch.setenv(_ENV, "1" if guard else "0")
        feature_flags.reload()
        try:
            assert feature_flags.is_enabled(_FLAG) is guard
            _BOARDS[guard] = dc.build_api_data_contract(copy.deepcopy(raw))
        finally:
            monkeypatch.delenv(_ENV, raising=False)
            feature_flags.reload()
    return _BOARDS[guard]


def _rows(contract: dict[str, Any]) -> dict[tuple[Any, ...], dict[str, Any]]:
    return {
        (r.get("canonicalName") or r.get("displayName"), r.get("assetClass")): r
        for r in contract.get("playersArray") or []
    }


def _uncredited(row: dict[str, Any]) -> list[str]:
    return sorted(
        k
        for k, m in (row.get("sourceRankMeta") or {}).items()
        if isinstance(m, dict) and m.get(_STAMP)
    )


def test_the_flag_is_registered_default_on() -> None:
    feature_flags.reload()
    assert feature_flags._DEFAULTS[_FLAG] is True
    assert feature_flags.is_enabled(_FLAG) is True


def test_guard_changes_no_value_rank_tier_or_vote(monkeypatch) -> None:
    on, off = _rows(_board(True, monkeypatch)), _rows(_board(False, monkeypatch))
    assert on.keys() == off.keys()
    fields = (
        "rankDerivedValue",
        "canonicalConsensusRank",
        "canonicalTierId",
        "canonicalPercentile",
        "droppedSources",
        "freshnessExcludedSources",
        "effectiveSourceRanks",
        "effectiveSourceCount",
        "independentSourceCount",
    )
    moved = [(k, f) for k in on for f in fields if on[k].get(f) != off[k].get(f)]
    assert moved == []


def test_guard_never_raises_coverage_or_independence(monkeypatch) -> None:
    """Removing a family from the credited panel can only hold or lower the
    two count axes — structurally, on every row."""
    on, off = _rows(_board(True, monkeypatch)), _rows(_board(False, monkeypatch))
    for key, a in on.items():
        ax_on, ax_off = a.get("confidenceAxes") or {}, off[key].get("confidenceAxes") or {}
        for axis in ("coverage", "independence"):
            if axis in ax_on and axis in ax_off:
                assert _LEVEL[ax_on[axis]] <= _LEVEL[ax_off[axis]], (key, axis)


def test_guard_never_raises_any_axis_against_crediting_the_cure(monkeypatch) -> None:
    """Seated, a cured family stays in every share denominator and earns
    nothing, so against crediting it (guard OFF) no axis can rise — on every
    row where the cured source's family has no other credited member.  Where
    it does, the family is represented by that member instead (the observed
    panel's verdict), whose own evidence is what the gate then reads."""
    on, off = _rows(_board(True, monkeypatch)), _rows(_board(False, monkeypatch))
    compared = 0
    for key, row in on.items():
        stamped = _uncredited(row)
        if not stamped:
            continue
        meta = row.get("sourceRankMeta") or {}
        withheld = set(row.get("freshnessExcludedSources") or ())
        credited = {
            dc.correlation_group_for(k)
            for k in row.get("effectiveSourceRanks") or {}
            if k not in stamped
            and k not in withheld
            and (meta.get(k) or {}).get("contributedToBlend") is not False
        }
        if {dc.correlation_group_for(k) for k in stamped} & credited:
            continue
        compared += 1
        ax_on, ax_off = row.get("confidenceAxes") or {}, off[key].get("confidenceAxes") or {}
        for axis, level in ax_on.items():
            assert _LEVEL[level] <= _LEVEL[ax_off[axis]], (key, axis, ax_off, ax_on)
        assert _LEVEL[row["confidenceBucket"]] <= _LEVEL[off[key]["confidenceBucket"]], key
        seat_line = [r for r in row.get("confidenceReasons") or [] if "did not reach" in r]
        assert seat_line, key
        seated = {name.strip() for name in seat_line[0].split(":", 1)[1].split(",")}
        assert {dc.correlation_group_for(k) for k in stamped} <= seated, (key, seated)
    if not compared:
        pytest.skip("no row on this board carries a cure whose family lost every voter")


def test_every_stamp_names_a_voting_source_on_a_row_that_lost_a_vote(monkeypatch) -> None:
    on, off = _rows(_board(True, monkeypatch)), _rows(_board(False, monkeypatch))
    for key, row in on.items():
        stamped = _uncredited(row)
        if not stamped:
            continue
        assert row.get("assetClass") != "pick", key
        assert row.get("freshnessExcludedSources"), key
        dropped = set(row.get("droppedSources") or ())
        voting = set(row.get("effectiveSourceRanks") or {})
        for source in stamped:
            assert source not in dropped and source in voting, (key, source)
    assert not [k for k, r in off.items() if _uncredited(r)], "flag OFF stamps nothing"


def test_withholding_never_raises_coverage_through_a_cured_rejection(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """The simulated IDPTC cutoff, guard ON: the two count axes can only fall
    when a vote is withheld — with no residual exemption, because neither
    reads the published value.  (The share axes are
    ``test_idptc_cutoff_readiness::test_5``'s, which exempts only agreement on
    a row whose value moved.)  Before the guard this failed on Patrick
    Mahomes: coverage medium -> high through two cured rejections."""
    from tests.api.test_idptc_cutoff_readiness import _simulation

    sim = _simulation(tmp_path_factory.mktemp("idptc_cutoff"))
    before, after = _rows(sim["before"]), _rows(sim["after"])
    for key, b in before.items():
        ab, aa = b.get("confidenceAxes") or {}, after[key].get("confidenceAxes") or {}
        for axis in ("coverage", "independence"):
            if axis in ab and axis in aa:
                assert _LEVEL[aa[axis]] <= _LEVEL[ab[axis]], (key, axis, ab, aa)
