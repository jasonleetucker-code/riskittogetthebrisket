"""/api/draft-capital's workbook class through the last-known-good resolver.

Owner addendum 2026-10-18: a failed refresh of the 72-pick class must not
erase the last verified whole-dollar allocation, the stored dollar curve never
carries ownership (ownership always comes from the live Sleeper fold), budgets
are never $0 because a refresh failed, and no other year's allocation is ever
used.  The canonical store / resolver is ``src/draft/rookie_auction/published``
(its own tests: ``tests/draft_valuation/test_published_allocation.py``); these
tests pin how the ROUTE consumes it.  The real workbook is used read-only; the
box-local store is redirected per test by ``tests/runtime_data_isolation``.
"""

from __future__ import annotations

from collections import defaultdict
from unittest.mock import patch

import pytest

from tests.api.test_draft_capital_correctness import YEAR, _retired_evidence, _workbook_run

SEED_YEAR = 2027  # the repo-tracked dynasty_main allocation (effective 2026-10-17)


@pytest.fixture(autouse=True)
def _seed_year_only():
    if YEAR + 1 != SEED_YEAR:
        pytest.skip("the repo seed allocation is for the 2027 class")


def _run_with_reference(transform, *, rostered=("P1",)):
    """Run the workbook route with the sheet's L2:L73 column transformed."""
    import server

    real = server._parse_draft_data()
    pick_dollars, workbook_picks, slot_to_original, wb_totals, rookies, pick_values_l = real
    if len(workbook_picks) != 72:
        pytest.skip("Draft Data workbook unavailable")
    fake = (
        pick_dollars,
        workbook_picks,
        slot_to_original,
        wb_totals,
        rookies,
        transform(list(pick_values_l)),
    )
    with patch.object(server, "_parse_draft_data", return_value=fake):
        return _workbook_run(_retired_evidence(YEAR, list(rostered)))


def _owned_sums(result):
    owned = defaultdict(int)
    for p in result["picks"]:
        owned[p["currentOwner"]] += p["dollarValue"]
    return owned


def _assert_reconciled(result):
    assert sum(p["dollarValue"] for p in result["picks"]) == 1200
    assert all(isinstance(p["dollarValue"], int) for p in result["picks"])
    owned = _owned_sums(result)
    for t in result["teamTotals"]:
        assert isinstance(t["auctionDollars"], int)
        assert t["auctionDollars"] == owned.get(t["team"], 0)
    assert sum(t["auctionDollars"] for t in result["teamTotals"]) == 1200


def test_verified_refresh_publishes_current():
    out = _run_with_reference(lambda values: values)
    assert "error" not in out, out
    assert out["draftValuation"]["allocationState"] == "current"
    assert out["draftValuation"]["failedRefresh"] is None
    _assert_reconciled(out)


def test_failed_refresh_keeps_the_same_years_last_verified_allocation():
    """A refresh whose curve no longer totals $1,200 fails validation; the
    2027 class keeps its last verified whole dollars, labelled, never $0."""
    good = _run_with_reference(lambda values: values)
    broken = _run_with_reference(lambda values: [values[0] + 1, *values[1:]])
    assert "error" not in broken, broken
    state = broken["draftValuation"]
    assert state["allocationState"] == "last_known_good"
    assert state["failedRefresh"]["reason"]
    assert state["lastValidAt"]
    assert state["warning"]
    assert [p["dollarValue"] for p in broken["picks"]] == [p["dollarValue"] for p in good["picks"]]
    _assert_reconciled(broken)


def test_missing_reference_column_falls_back_too():
    out = _run_with_reference(lambda values: [])
    assert "error" not in out, out
    assert out["draftValuation"]["allocationState"] == "last_known_good"
    assert "missing" in out["draftValuation"]["failedRefresh"]["reason"]
    _assert_reconciled(out)


def test_ownership_comes_from_live_sleeper_even_on_fallback():
    """The stored curve carries no ownership: a pick traded on Sleeper moves
    to its new owner under ``last_known_good`` exactly as under ``current``."""
    import server
    from tests.api import test_draft_capital_correctness as base

    real = server._parse_draft_data()
    if len(real[1]) != 72:
        pytest.skip("Draft Data workbook unavailable")
    broken = (*real[:5], [real[5][0] + 1, *real[5][1:]])
    original_stub = base._workbook_stub

    def stub_with_trade(url_map):
        url_map = dict(url_map)
        url_map["/traded_picks"] = [
            {"season": str(SEED_YEAR), "round": 1, "roster_id": 1, "owner_id": 2}
        ]
        return original_stub(url_map)

    with (
        patch.object(server, "_parse_draft_data", return_value=broken),
        patch.object(base, "_workbook_stub", stub_with_trade),
    ):
        out = base._workbook_run(_retired_evidence(YEAR, ["P1"]))
    assert "error" not in out, out
    assert out["draftValuation"]["allocationState"] == "last_known_good"
    traded = [p for p in out["picks"] if p["round"] == 1 and p["originRosterId"] == 1]
    assert traded and all(p["currentOwnerRosterId"] == 2 for p in traded)
    _assert_reconciled(out)


def test_no_applicable_allocation_fails_closed_never_zero():
    """A class with no stored allocation and a failed refresh refuses the
    board with a named reason — it never borrows another year's curve and
    never publishes $0 budgets."""
    out = _run_with_reference(lambda values: [values[0] + 1, *values[1:]], rostered=())
    # ``rostered=()`` keeps the board on the anchor year (YEAR), for which no
    # allocation is stored: the 2027 seed must not answer for it.
    assert out.get("error") == "draft_dollars_unavailable", out
    assert out["unavailableReason"]
    assert "teamTotals" not in out
