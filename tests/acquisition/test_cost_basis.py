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


class TestPickBasisUsesTheClockAsOfTheEvent:
    def test_a_league_pick_resolves_through_the_identity_owner(self, ledger):
        """A league pick is not a history key.  It resolves to a MARKET
        ref via ``market_resolution``, whose ``current_draft_year`` is
        taken AS OF THE EVENT — passing today's would re-grade an old
        trade under today's basis (the C3-REPLAY-01 class)."""
        from src.history.keys import pick_asset_key
        from src.identity.picks import market_resolution

        pick_id = f"pick:{LEAGUE}:2028:r1:o9"
        resolution = market_resolution(year=2028, round_num=1, slot=None, current_draft_year=2026)
        key = pick_asset_key(resolution.ref.board_row_name())
        _observe(ledger, key, _D0 - timedelta(hours=3), 3200.0)

        result = basis_for_holding(_holding(_ms(_D0), asset_id=pick_id), path=ledger)
        assert result["value"] == 3200.0, result

    def test_an_unresolvable_pick_id_is_refused(self, ledger):
        result = basis_for_holding(_holding(_ms(_D0), asset_id="pick:not-a-real-id"), path=ledger)
        assert result["value"] is None


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
