"""A failed acquisition must not be representable as a healthy empty source.

That sentence is the whole point of the vocabulary under test.  Before it,
the repo signalled acquisition outcomes only through fetcher exit codes, and
``.github/workflows/scheduled-refresh.yml::run_fetcher`` collapsed exit 1 and
exit 2 into the same branch — so "the vendor changed their HTML" and "the
network blipped" were the same event by the time anything observed them, and
neither was distinguishable downstream from "the vendor published nothing".
"""

from __future__ import annotations

import pytest

from src.sources.acquisition_state import (
    ACQUISITION_STATES,
    AUTH_REQUIRED,
    HEALTHY,
    NO_CROSS_POSITION_COVERAGE,
    PARSE_FAILED,
    PARTIAL,
    SCHEMA_CHANGED,
    STALE,
    UNAVAILABLE,
    USABLE_ACQUISITION_STATES,
    AcquisitionOutcome,
    AcquisitionStateError,
    state_from_exit_code,
)


class TestAFailureIsNotAnEmptyBoard:
    """The invariant the module exists for, asserted structurally."""

    @pytest.mark.parametrize("state", [UNAVAILABLE, AUTH_REQUIRED, PARSE_FAILED, SCHEMA_CHANGED])
    def test_a_failure_state_cannot_carry_a_row_count(self, state: str) -> None:
        with pytest.raises(AcquisitionStateError) as exc:
            AcquisitionOutcome("src", state, reason="r", row_count=0)
        assert "must not be representable as an empty board" in str(exc.value)

    def test_a_healthy_board_may_legitimately_be_empty(self) -> None:
        """0 rows is a real observation when a board really did arrive."""
        outcome = AcquisitionOutcome("src", HEALTHY, row_count=0)
        assert outcome.row_count == 0
        assert outcome.acquired is True

    def test_absent_and_zero_are_different_values(self) -> None:
        acquired_empty = AcquisitionOutcome("src", HEALTHY, row_count=0)
        never_arrived = AcquisitionOutcome("src", UNAVAILABLE, reason="timeout")
        assert acquired_empty.row_count == 0
        assert never_arrived.row_count is None
        assert acquired_empty.to_dict()["rowCount"] == 0
        assert never_arrived.to_dict()["rowCount"] is None

    def test_a_failure_must_say_why(self) -> None:
        with pytest.raises(AcquisitionStateError) as exc:
            AcquisitionOutcome("src", UNAVAILABLE)
        assert "requires a reason" in str(exc.value)


class TestTheStatesAreDistinct:
    def test_auth_required_is_not_unavailable(self) -> None:
        """One is fixed by waiting; the other needs an owner action."""
        assert AUTH_REQUIRED != UNAVAILABLE
        assert AUTH_REQUIRED in ACQUISITION_STATES

    def test_schema_changed_is_not_parse_failed(self) -> None:
        """One is a bug in us; the other is the vendor moving."""
        assert SCHEMA_CHANGED != PARSE_FAILED

    def test_no_cross_position_coverage_is_an_acquired_state(self) -> None:
        """The board arrived; it simply does not connect the two pools."""
        outcome = AcquisitionOutcome("src", NO_CROSS_POSITION_COVERAGE, row_count=1000)
        assert outcome.acquired is True
        assert outcome.usable is False

    def test_an_unknown_state_is_refused(self) -> None:
        with pytest.raises(AcquisitionStateError):
            AcquisitionOutcome("src", "PROBABLY_FINE")


class TestStaleIsNotCurrent:
    def test_stale_rows_arrived_but_may_not_be_consumed_as_current(self) -> None:
        outcome = AcquisitionOutcome("src", STALE, reason="42h > 24h budget", row_count=275)
        assert outcome.acquired is True
        assert outcome.usable is False
        assert STALE not in USABLE_ACQUISITION_STATES

    def test_only_healthy_and_partial_are_usable(self) -> None:
        assert USABLE_ACQUISITION_STATES == {HEALTHY, PARTIAL}


class TestExitCodeMapping:
    def test_zero_is_healthy(self) -> None:
        assert state_from_exit_code(0) == HEALTHY

    def test_two_is_a_schema_regression(self) -> None:
        """The signal CI currently discards by collapsing exit 1 and 2."""
        assert state_from_exit_code(2) == SCHEMA_CHANGED

    def test_one_is_the_weaker_claim(self) -> None:
        """Exit 1 covers both fetch and parse errors, so it must not assert
        the stronger of the two."""
        assert state_from_exit_code(1) == UNAVAILABLE

    def test_exit_one_and_two_do_not_collapse(self) -> None:
        assert state_from_exit_code(1) != state_from_exit_code(2)
