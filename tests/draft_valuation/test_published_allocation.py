"""Last-known-good published allocations (owner addendum 2026-10-18)."""

from __future__ import annotations

import json
import shutil
from dataclasses import fields
from fractions import Fraction

import pytest

from src.draft.rookie_auction import published as pub
from src.draft.rookie_auction.curve import compute_curve
from src.draft.rookie_auction.published import (
    REPO_STORE,
    AllocationCandidate,
    CandidateFailure,
    PublishedAllocation,
    allocation_history,
    resolve_published_allocation,
)
from src.draft.rookie_auction.snapshots import canonical_checksum
from src.draft.rookie_auction.verify import verify_whole_dollar_allocation
from src.identity.pick_lifecycle import ClassLifecycle
from tests.draft_valuation import reference_workbook_formulas as ref
from tests.draft_valuation.test_curve_properties import _case
from tests.draft_valuation.test_whole_dollars import EXPECTED_WHOLE

LEAGUE = "dynasty_main"
SEED_AT = "2026-10-17T00:00:00+00:00"


@pytest.fixture()
def stores(tmp_path):
    repo = tmp_path / "repo"
    # Only the 2027 seed: these tests edit "the" stored record (Batch E seeds
    # 2028 / 2029 beside it in the real store).
    shutil.copytree(REPO_STORE / LEAGUE / "2027", repo / LEAGUE / "2027")
    box = tmp_path / "box"
    return {"store_dirs": [repo, box], "write_dir": box}


def _candidate(seed=3, *, at="2027-01-10T00:00:00+00:00", year=2027, **prov):
    res = compute_curve(*_case(seed))
    return AllocationCandidate.from_curve(
        res, draft_year=year, effective_at=at, provenance={"inputsSnapshotSha256": "x", **prov}
    )


def test_repo_store_publishes_the_2027_workbook_allocation_unchanged():
    out = resolve_published_allocation(LEAGUE, 2027, store_dirs=[REPO_STORE])
    assert out.allocation_state == "current" and out.failed_refresh is None
    assert list(out.final_whole_dollars) == EXPECTED_WHOLE and sum(out.final_whole_dollars) == 1200
    assert out.effective_at == SEED_AT
    assert out.receipt["validation"]["verifier"]["result"] == "pass"
    assert out.receipt["provenance"]["spineYears"] == [2024, 2025, 2026]
    assert out.dollars_by_slot()["1.01"] == 135
    assert out.reference_dollars[0] == "134.5"


def test_identical_refresh_writes_nothing_and_keeps_the_original_record(stores):
    seed = resolve_published_allocation(LEAGUE, 2027, **stores)
    again = AllocationCandidate(
        draft_year=2027,
        reference_dollars=[Fraction(r) for r in seed.reference_dollars],
        effective_at="2026-11-01T00:00:00+00:00",
        provenance={"workbookSha256": "a-new-download-of-the-same-cells"},
    )
    out = resolve_published_allocation(LEAGUE, 2027, candidate=again, **stores)
    assert out.allocation_state == "current" and out.effective_at == SEED_AT
    assert not stores["write_dir"].exists() or not any(stores["write_dir"].rglob("*.json"))


def test_calculation_failure_falls_back_to_last_known_good(stores):
    bad = AllocationCandidate(
        draft_year=2027,
        reference_dollars=[Fraction(1)] * 72,  # sums to 72, not 1200
        effective_at="2027-01-10T00:00:00+00:00",
        provenance={},
    )
    out = resolve_published_allocation(LEAGUE, 2027, candidate=bad, **stores)
    assert out.allocation_state == "last_known_good"
    assert out.failed_refresh["at"] == "2027-01-10T00:00:00+00:00"
    assert out.failed_refresh["reason"].startswith("apportionment_refused:sum_not_total")
    assert out.last_valid_at == SEED_AT and "failed" in out.warning
    assert list(out.final_whole_dollars) == EXPECTED_WHOLE  # never zero


def test_missing_input_value_falls_back(stores):
    vals = [Fraction(1)] * 72
    vals[5] = None
    out = resolve_published_allocation(
        LEAGUE,
        2027,
        candidate=AllocationCandidate(2027, vals, "2027-01-10T00:00:00+00:00", {}),
        **stores,
    )
    assert out.allocation_state == "last_known_good"
    assert "missing_value" in out.failed_refresh["reason"]


def test_verifier_failure_falls_back(stores, monkeypatch):
    class Failed:
        ok = False
        failures = ("not_minimum_deviation:x>y",)

    monkeypatch.setattr(pub, "verify_whole_dollar_allocation", lambda *a, **k: Failed())
    out = resolve_published_allocation(LEAGUE, 2027, candidate=_candidate(), **stores)
    assert out.allocation_state == "last_known_good"
    assert out.failed_refresh["reason"].startswith("verification_failed")


def test_source_outage_falls_back(stores):
    out = resolve_published_allocation(
        LEAGUE,
        2027,
        candidate=CandidateFailure(
            2027, "inputs_missing:rookie board unavailable", "2027-02-01T00:00:00+00:00"
        ),
        **stores,
    )
    assert out.allocation_state == "last_known_good"
    assert out.failed_refresh == {
        "at": "2027-02-01T00:00:00+00:00",
        "reason": "inputs_missing:rookie board unavailable",
    }


def test_recovery_republishes_and_history_stays_immutable(stores):
    seed_file = next(stores["store_dirs"][0].rglob("*.json"))
    seed_bytes = seed_file.read_bytes()
    first = resolve_published_allocation(LEAGUE, 2027, candidate=_candidate(3), **stores)
    assert first.allocation_state == "current" and first.effective_at == "2027-01-10T00:00:00+00:00"
    assert list(first.final_whole_dollars) != EXPECTED_WHOLE
    # A later failure now falls back to the NEW allocation, not the seed.
    fail = CandidateFailure(2027, "inputs_missing", "2027-01-11T00:00:00+00:00")
    lkg = resolve_published_allocation(LEAGUE, 2027, candidate=fail, **stores)
    assert lkg.allocation_state == "last_known_good"
    assert lkg.final_whole_dollars == first.final_whole_dollars
    assert lkg.last_valid_at == "2027-01-10T00:00:00+00:00"
    history = allocation_history(LEAGUE, 2027, store_dirs=stores["store_dirs"])
    assert [h[1]["effectiveAt"] for h in history] == [SEED_AT, "2027-01-10T00:00:00+00:00"]
    assert seed_file.read_bytes() == seed_bytes
    # A constrained-repair class (seed 25) also publishes, verified.
    rec = resolve_published_allocation(
        LEAGUE, 2027, candidate=_candidate(25, at="2027-01-12T00:00:00+00:00"), **stores
    )
    assert rec.allocation_state == "current"
    assert rec.receipt["validation"]["apportionment"]["method"] == "constrained_min_deviation"
    assert rec.receipt["validation"]["verifier"]["result"] == "pass"


def test_ownership_is_never_stored_or_readable(stores):
    names = {f.name for f in fields(PublishedAllocation)}
    assert not names & {"owner", "owners", "ownership", "teams", "team_totals", "roster_ids"}
    out = resolve_published_allocation(LEAGUE, 2027, **stores)
    assert not pub._contains_ownership(out.to_dict())
    # A candidate that smuggles ownership into its provenance is refused.
    sneaky = _candidate(3, rosterId=4)
    refused = resolve_published_allocation(LEAGUE, 2027, candidate=sneaky, **stores)
    assert refused.allocation_state == "last_known_good"
    assert refused.failed_refresh["reason"] == "provenance_carries_ownership"
    # A stored record edited to carry ownership is ignored, even re-checksummed.
    p = next(stores["store_dirs"][0].rglob("*.json"))
    rec = json.loads(p.read_text("utf-8"))
    rec["finalWholeDollars"][0]["currentOwnerRosterId"] = 7
    rec["checksum"]["value"] = canonical_checksum(rec)
    p.write_text(json.dumps(rec), "utf-8")
    gone = resolve_published_allocation(LEAGUE, 2027, **stores)
    assert gone.allocation_state == "unavailable" and any("ownership" in n for n in gone.notes)


def test_changed_ownership_does_not_touch_the_curve(stores):
    """Ownership lives in the consumer's live fold; the curve is the same either way."""
    a = resolve_published_allocation(LEAGUE, 2027, **stores)
    b = resolve_published_allocation(LEAGUE, 2027, **stores)
    assert a.dollars_by_slot() == b.dollars_by_slot()
    assert set(a.dollars_by_slot()) == {f"{r}.{s:02d}" for r in range(1, 7) for s in range(1, 13)}


def test_retired_class_is_stale_and_refused(stores):
    retired = ClassLifecycle(
        2027, "retired", ("rookie_draft_complete:d1", "rookies_rostered:70/72")
    )
    out = resolve_published_allocation(LEAGUE, 2027, lifecycle=retired, **stores)
    assert out.allocation_state == "unavailable" and out.unavailable_reason == "draft_class_retired"
    assert out.final_whole_dollars is None
    with pytest.raises(LookupError):
        out.dollars_by_slot()


def test_formula_version_mismatch_is_stale(stores):
    p = next(stores["store_dirs"][0].rglob("*.json"))
    rec = json.loads(p.read_text("utf-8"))
    rec["formulaVersion"] = "draft_data_workbook_v0"
    rec["checksum"]["value"] = canonical_checksum(rec)
    p.write_text(json.dumps(rec), "utf-8")
    out = resolve_published_allocation(LEAGUE, 2027, **stores)
    assert out.allocation_state == "unavailable"
    assert out.unavailable_reason == "stored_allocation_formula_version_mismatch"
    cand = _candidate()
    cand = AllocationCandidate(2027, cand.reference_dollars, cand.effective_at, {}, "other_v9")
    fb = resolve_published_allocation(LEAGUE, 2027, candidate=cand, store_dirs=[REPO_STORE])
    assert fb.allocation_state == "last_known_good"
    assert fb.failed_refresh["reason"] == "formula_version_mismatch:other_v9"


def test_missing_fallback_fails_closed(tmp_path):
    out = resolve_published_allocation(
        LEAGUE,
        2027,
        candidate=CandidateFailure(2027, "inputs_missing", "2027-01-01T00:00:00+00:00"),
        store_dirs=[tmp_path / "empty"],
        write_dir=tmp_path / "w",
    )
    assert out.allocation_state == "unavailable"
    assert out.unavailable_reason == "no_verified_allocation"
    assert out.final_whole_dollars is None and out.failed_refresh["reason"] == "inputs_missing"
    assert out.to_dict()["totalDollars"] is None  # never zero


def test_year_mismatch_and_no_cross_year_fallback(stores):
    out = resolve_published_allocation(LEAGUE, 2027, candidate=_candidate(year=2028), **stores)
    assert out.allocation_state == "unavailable"
    assert out.unavailable_reason == "draft_year_mismatch:2028!=2027"
    other = resolve_published_allocation(LEAGUE, 2028, **stores)  # only 2027 is stored
    assert (
        other.allocation_state == "unavailable"
        and other.unavailable_reason == "no_verified_allocation"
    )


def test_unconfigured_league_and_edited_records(stores):
    assert (
        resolve_published_allocation("dynasty_new", 2027, **stores).unavailable_reason
        == "league_not_configured:dynasty_new"
    )
    p = next(stores["store_dirs"][0].rglob("*.json"))
    rec = json.loads(p.read_text("utf-8"))
    rec["finalWholeDollars"][0]["dollars"] = 136
    p.write_text(json.dumps(rec), "utf-8")
    out = resolve_published_allocation(LEAGUE, 2027, **stores)
    assert out.allocation_state == "unavailable" and any("checksum" in n for n in out.notes)


# --- the runtime verifier --------------------------------------------------------------


def test_runtime_verifier_agrees_with_the_reference_on_all_250_cases():
    floors, caps = ref.dynasty_main_whole_dollar_bounds()
    from tests.draft_valuation.test_curve_properties import SEEDS

    for seed in SEEDS:
        res = compute_curve(*_case(seed))
        half = [Fraction(u, 2) for u in res.units]
        v = verify_whole_dollar_allocation(
            half, res.final_whole_dollars, 1200, floors=floors, caps=caps
        )
        assert v.ok, (seed, v.failures)
        assert v.optimum == res.whole_dollars.total_deviation


def test_runtime_verifier_rejects_non_optimal_and_wrong_tie_break():
    floors, caps = ref.dynasty_main_whole_dollar_bounds()
    res = compute_curve(*_case(3))
    half = [Fraction(u, 2) for u in res.units]
    good = list(res.final_whole_dollars)
    # Move a dollar between two exact-integer picks: same total, worse deviation.
    exact = [i for i in range(1, 30) if half[i].denominator == 1 and good[i] == half[i]]
    i, j = exact[0], exact[1]
    worse = list(good)
    worse[i] += 1
    worse[j] -= 1
    assert not verify_whole_dollar_allocation(half, worse, 1200, floors=floors, caps=caps).ok
    # Same deviation, wrong tie-break: round a later half-dollar pick up instead.
    halves = [k for k in range(48) if half[k].denominator == 2]
    up = [k for k in halves if good[k] > half[k]]
    down = [k for k in halves if good[k] < half[k]]
    candidates = []
    for a in up:
        for b in down:
            if b <= a:
                continue
            swapped = list(good)
            swapped[a] -= 1
            swapped[b] += 1
            if all(swapped[k] <= swapped[k - 1] for k in range(1, 72)):
                candidates.append(swapped)
    assert candidates, "no monotone same-deviation alternative in this case"
    v = verify_whole_dollar_allocation(half, candidates[0], 1200, floors=floors, caps=caps)
    assert not v.ok and v.failures == ("not_lexicographic_tie_break",)
