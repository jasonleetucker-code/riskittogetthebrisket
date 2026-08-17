"""C1-U8 — cost basis, and the four ways it must refuse to guess.

THE INVARIANT WORTH STATING PLAINLY
───────────────────────────────────
**A future snapshot can never become historical basis.**  Everything
below is one consequence of that or another.

``value_known_before`` is instant-strict, so a board built later on the
same calendar day does not qualify.  ``value_as_of`` is day-granular and
WOULD qualify, which is why it is the wrong function here: pricing
Monday's trade with Monday-evening's board reads the market's reaction
to that trade back into its own cost.

The rest are the sibling refusals — undated acquisition, an acquisition
before the permanent history floor, an asset the ledger has never seen.
Each returns ``None`` with a NAMED reason, never 0 and never the
nearest available number in either direction.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.acquisition.basis import (
    REASON_UNDATED,
    attach_basis,
    basis_for_holding,
)
from src.history import store as history_store

LEAGUE = "dynasty_main"

#: Comfortably after HISTORY_FLOOR (2026-07-14).
_D0 = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def ledger(tmp_path):
    history_store._reset_setup_cache_for_tests()
    path = tmp_path / "temporal_ledger.sqlite"
    yield path
    history_store._reset_setup_cache_for_tests()


def _observe(path, asset_key: str, when: datetime, value: float) -> None:
    history_store.write_observations(
        [
            {
                "asset_key": asset_key,
                "lane": history_store.LANE_CANONICAL,
                "source_key": "",
                "observed_date": when.date().isoformat(),
                "observed_at": when.isoformat(),
                "origin": "live",
                "asset_class": "offense",
                "value": value,
                "display_name": "Test Player",
            }
        ],
        path=path,
    )


def _holding(ms: int | None, asset_id: str = "player:4034") -> dict:
    return {
        "league_key": LEAGUE,
        "asset_id": asset_id,
        "owner_rid": 1,
        "sequence_num": 1,
        "acquired_at_ms": ms,
        "acquired_ref": "tx:t1",
        "acquired_method": "TRADE",
    }


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


class TestTheBasisIsWhatWasKnownBefore:
    def test_a_prior_observation_prices_the_acquisition(self, ledger):
        _observe(ledger, "player:4034", _D0 - timedelta(hours=6), 5000.0)
        result = basis_for_holding(_holding(_ms(_D0)), path=ledger)
        assert result["value"] == 5000.0
        assert result["missingReason"] is None

    def test_a_later_same_day_observation_is_not_used(self, ledger):
        """The look-ahead that ``value_as_of`` would allow and
        ``value_known_before`` refuses."""
        _observe(ledger, "player:4034", _D0 + timedelta(hours=6), 9000.0)
        result = basis_for_holding(_holding(_ms(_D0)), path=ledger)
        assert result["value"] is None, (
            "a board built AFTER the trade, on the same calendar day, was used as its cost "
            "basis — that board already contains the market's reaction to the trade"
        )

    def test_the_nearest_prior_wins_over_an_older_one(self, ledger):
        _observe(ledger, "player:4034", _D0 - timedelta(days=5), 1000.0)
        _observe(ledger, "player:4034", _D0 - timedelta(hours=2), 4000.0)
        assert basis_for_holding(_holding(_ms(_D0)), path=ledger)["value"] == 4000.0

    def test_a_future_only_ledger_never_back_fills(self, ledger):
        """The same look-ahead in the other direction: the earliest
        FUTURE observation is not a substitute for a missing prior."""
        _observe(ledger, "player:4034", _D0 + timedelta(days=30), 7777.0)
        assert basis_for_holding(_holding(_ms(_D0)), path=ledger)["value"] is None


class TestItRefusesRatherThanGuesses:
    def test_an_undated_acquisition_has_no_basis(self, ledger):
        result = basis_for_holding(_holding(None), path=ledger)
        assert result["value"] is None
        assert result["missingReason"] == REASON_UNDATED

    def test_an_acquisition_before_the_history_floor_is_named_not_priced(self, ledger):
        before_floor = datetime(2026, 1, 5, tzinfo=timezone.utc)
        _observe(ledger, "player:4034", _D0, 5000.0)
        result = basis_for_holding(_holding(_ms(before_floor)), path=ledger)
        assert result["value"] is None
        assert result["missingReason"] == "before_history_boundary", result

    def test_an_unobserved_asset_is_missing_not_zero(self, ledger):
        _observe(ledger, "player:other", _D0 - timedelta(days=1), 5000.0)
        result = basis_for_holding(_holding(_ms(_D0)), path=ledger)
        assert result["value"] is None
        assert result["value"] != 0, "missing is never zero"
        assert result["missingReason"]

    def test_an_unresolvable_asset_id_is_named(self, ledger):
        result = basis_for_holding(_holding(_ms(_D0), asset_id="garbage"), path=ledger)
        assert result["value"] is None
        assert result["missingReason"] == "unresolvable_asset_key"

    def test_a_genuine_zero_survives_as_a_value(self, ledger):
        """The other half of "missing is never zero", and the half that
        is easy to lose.

        A player really can be observed at 0. The code is correct today
        because it branches on ``is None``; a refactor to ``if not
        value:`` would silently reclassify every genuine zero as
        ``no_prior_observation`` and no other test would notice. This is
        the test that would.
        """
        _observe(ledger, "player:4034", _D0 - timedelta(hours=2), 0.0)
        result = basis_for_holding(_holding(_ms(_D0)), path=ledger)

        assert result["value"] == 0.0
        assert result["value"] is not None
        assert result["missingReason"] is None, (
            "an observed 0.0 was reported as missing — 'worth nothing' and 'we never "
            "looked' are different facts"
        )

    def test_attach_basis_does_not_overwrite_a_zero_with_a_missing_reason(self, ledger):
        _observe(ledger, "player:4034", _D0 - timedelta(hours=2), 0.0)
        holdings = [_holding(_ms(_D0))]
        attach_basis(holdings, path=ledger)
        assert holdings[0]["basis_value"] == 0.0
        assert holdings[0]["basis_missing_reason"] is None


class TestPickBasisUsesTheClockAsOfTheEvent:
    """The C3-REPLAY-01 defense, exercised rather than asserted.

    An earlier cut of this class was VACUOUS: `basis.py` always passed
    `slot=None`, and `market_resolution` only consults
    `current_draft_year` inside its `slot is not None` branch — so the
    clock was never read, and the test hardcoded a draft year that
    happened to collapse to the same generic ref either way. It proved
    nothing.

    The two cases below are the real ones. With a KNOWN slot the clock
    decides between the exact-slot grade and the tier grade; with an
    unknown slot the generic grade is correct and the clock genuinely
    does not matter — which is a fact worth pinning, not a gap.
    """

    def test_an_unknown_slot_resolves_generic_and_ignores_the_clock(self, ledger):
        from src.history.keys import pick_asset_key
        from src.identity.picks import market_resolution

        pick_id = f"pick:{LEAGUE}:2028:r1:o9"
        resolution = market_resolution(year=2028, round_num=1, slot=None, current_draft_year=2026)
        assert resolution.basis == "unknown_slot"
        key = pick_asset_key(resolution.ref.board_row_name())
        _observe(ledger, key, _D0 - timedelta(hours=3), 3200.0)

        result = basis_for_holding(_holding(_ms(_D0), asset_id=pick_id), path=ledger)
        assert result["value"] == 3200.0, result

    def test_a_known_slot_is_graded_by_the_clock_at_the_EVENT(self, ledger):
        """The same pick, the same known slot, two different event
        instants — and two different grades.

        Before the 2027 draft arrives, a 2027 pick sitting at slot 4 is
        still a *future* pick: `tier_from_slot`. After it arrives, it is
        `exact_slot`. Pricing the earlier trade with today's clock would
        hand it the slot the pick eventually landed on — hindsight the
        market did not have.
        """
        from src.history.keys import pick_asset_key
        from src.identity.picks import market_resolution

        pick_id = f"pick:{LEAGUE}:2027:r1:o9"
        early = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)  # 2027 draft still future
        late = datetime(2027, 8, 1, 12, 0, tzinfo=timezone.utc)  # 2027 draft has arrived

        early_ref = market_resolution(year=2027, round_num=1, slot=4, current_draft_year=2027)
        late_ref = market_resolution(year=2027, round_num=1, slot=4, current_draft_year=2028)
        assert early_ref.basis == "exact_slot"
        assert late_ref.basis == "exact_slot"

        # The clock as of each event, from the canonical as-of owner.
        from src.api.data_contract import rookie_draft_year_on

        assert rookie_draft_year_on(early.date()) == 2027
        assert rookie_draft_year_on(late.date()) == 2028

        # Grade the pick under a clock for which 2027 is STILL FUTURE.
        future_ref = market_resolution(year=2027, round_num=1, slot=4, current_draft_year=2026)
        assert future_ref.basis == "tier_from_slot", (
            "a slot known before the draft year arrives must grade as a TIER, not an "
            "exact slot — otherwise a pre-draft trade is priced at hindsight"
        )
        assert future_ref.ref.board_row_name() != early_ref.ref.board_row_name(), (
            "the two grades must resolve to DIFFERENT board rows, or the clock cannot "
            "be said to decide anything"
        )

        # Now prove basis_for_holding actually routes through that.
        exact_key = pick_asset_key(early_ref.ref.board_row_name())
        _observe(ledger, exact_key, early - timedelta(hours=3), 4400.0)

        holding = _holding(_ms(early), asset_id=pick_id)
        holding["realized_slot"] = 4
        result = basis_for_holding(holding, path=ledger)
        assert result["value"] == 4400.0, (
            f"the realized slot did not reach market_resolution — the as-of-event clock "
            f"is unreachable again: {result}"
        )

    def test_the_slot_actually_changes_which_row_is_priced(self, ledger):
        """Slot-aware and slot-blind resolution must not silently agree,
        or the previous test would pass for the wrong reason."""
        from src.acquisition.basis import _history_asset_key

        pick_id = f"pick:{LEAGUE}:2027:r1:o9"
        instant = datetime(2027, 8, 1, tzinfo=timezone.utc)
        blind = _history_asset_key(pick_id, instant, realized_slot=None)
        aware = _history_asset_key(pick_id, instant, realized_slot=4)
        assert blind and aware and blind != aware, (blind, aware)

    def test_zero_is_not_a_slot(self, ledger):
        """``realized_slot: 0`` is absence, not slot zero."""
        from src.acquisition.basis import _history_asset_key

        pick_id = f"pick:{LEAGUE}:2027:r1:o9"
        instant = datetime(2027, 8, 1, tzinfo=timezone.utc)
        assert _history_asset_key(pick_id, instant, realized_slot=0) == _history_asset_key(
            pick_id, instant, realized_slot=None
        )

    def test_an_unresolvable_pick_id_is_refused(self, ledger):
        result = basis_for_holding(_holding(_ms(_D0), asset_id="pick:not-a-real-id"), path=ledger)
        assert result["value"] is None


class TestTheAsOfClockIsTheOwnersAsOfForm:
    """`current_rookie_draft_year` answers a PRESENT-TENSE question — its
    config override and observed-year self-roll both beat the `today`
    argument. Calling it with a historical date would silently return
    today's answer, which is the exact re-grading this module prevents.
    `rookie_draft_year_on` is the as-of form."""

    def test_the_rollover_boundary_is_applied_to_the_given_date(self):
        from datetime import date

        from src.api.data_contract import rookie_draft_year_on

        assert rookie_draft_year_on(date(2026, 5, 14)) == 2026
        assert rookie_draft_year_on(date(2026, 5, 15)) == 2027

    def test_it_ignores_the_present_tense_observed_year(self):
        import src.api.data_contract as dc
        from datetime import date

        previous = dc._OBSERVED_CURRENT_DRAFT_YEAR
        try:
            dc.set_observed_current_draft_year(2031)
            assert dc.current_rookie_draft_year(today=date(2026, 1, 5)) == 2031
            assert (
                dc.rookie_draft_year_on(date(2026, 1, 5)) == 2026
            ), "the as-of form must not inherit the present-tense observed year"
        finally:
            dc.set_observed_current_draft_year(previous)


class TestAttachBasisDegradesInsteadOfFailing:
    def test_every_holding_is_stamped(self, ledger):
        _observe(ledger, "player:4034", _D0 - timedelta(hours=1), 500.0)
        holdings = [_holding(_ms(_D0)), _holding(None, asset_id="player:zzz")]
        attach_basis(holdings, path=ledger)
        assert holdings[0]["basis_value"] == 500.0
        assert holdings[1]["basis_value"] is None
        assert holdings[1]["basis_missing_reason"] == REASON_UNDATED

    def test_an_unreachable_ledger_degrades_every_row(self, tmp_path):
        """A projection that refuses to build because a value lookup
        failed is strictly worse than one that says which values it
        could not find."""
        holdings = [_holding(_ms(_D0))]
        attach_basis(holdings, path=tmp_path / "does-not-exist.sqlite")
        assert holdings[0]["basis_value"] is None
        assert holdings[0]["basis_missing_reason"]
