"""The declared seasonal-window owner (``src/sources/seasonal_policy.py``).

Owner methodology decision 2026-10-03 (issue #1552): an empty Flock
``PROSPECTS_SF`` board for the graduating class, from October 1 of that
class year, is an expected ``seasonally_inactive`` state — not a stale-source
failure, not a success, and not a vote.  These tests pin the owner's rules;
the fetcher / watchdog / contract consumers are pinned in their own files.

Hermetic: every test uses a temporary state directory and fixed clocks.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.api.source_health_alerts import load_soft_sources
from src.sources import seasonal_policy as sp
from src.sources.acquisition_state import (
    SEASONALLY_INACTIVE,
    SEASONALLY_INACTIVE_EXIT_CODE,
    USABLE_ACQUISITION_STATES,
    AcquisitionOutcome,
    state_from_exit_code,
)

KEY = "flockFantasySfRookies"
OCT_2 = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)
SEP_30 = datetime(2026, 9, 30, 23, 59, tzinfo=timezone.utc)


def _empty(year=2026, fmt="PROSPECTS_SF"):
    out = {"data": [], "year": year}
    if fmt is not None:
        out["format"] = fmt
    return out


@pytest.fixture()
def policy() -> sp.SeasonalPolicy:
    return sp.load_policies()[KEY]


# ── The real declaration ────────────────────────────────────────────────
class TestDeclaredPolicy:
    def test_flock_rookies_declared_with_the_owner_cutoff(self, policy):
        assert (policy.inactive_month, policy.inactive_day) == (10, 1)
        assert policy.class_year_field == "year"
        assert policy.expected_format == "PROSPECTS_SF"
        assert policy.reactivation == "first_valid_nonempty_response"

    def test_not_soft(self):
        """Owner rule 6: soft is a delayed OUTAGE alarm — wrong semantics."""
        soft = load_soft_sources()
        assert KEY not in soft
        assert "flockFantasy" not in soft

    def test_only_declared_sources_have_policies(self):
        assert set(sp.load_policies()) == {KEY}

    def test_malformed_policy_file_raises_rather_than_reading_empty(self, tmp_path):
        bad = tmp_path / "p.json"
        bad.write_text(json.dumps({"sources": {KEY: {"expectedEmpty": {}}}}), encoding="utf-8")
        with pytest.raises(sp.SeasonalPolicyError):
            sp.load_policies(bad)

    def test_missing_policy_file_means_no_policies(self, tmp_path):
        assert sp.load_policies(tmp_path / "absent.json") == {}


# ── Verdict: is this empty response the declared state? ────────────────
class TestClassifyEmptyResponse:
    def test_empty_after_cutoff_is_expected(self, policy):
        v = sp.classify_empty_response(policy, _empty(), OCT_2)
        assert v.expected and v.class_year == 2026

    def test_cutoff_is_inclusive_at_midnight_utc(self, policy):
        at = datetime(2026, 10, 1, tzinfo=timezone.utc)
        assert sp.classify_empty_response(policy, _empty(), at).expected

    def test_empty_before_cutoff_fails_closed(self, policy):
        """Owner rule 8: empty while the source is EXPECTED active fails closed."""
        v = sp.classify_empty_response(policy, _empty(), SEP_30)
        assert not v.expected
        assert v.reason.startswith("before_declared_window")

    def test_empty_for_the_next_class_fails_closed(self, policy):
        """Once the vendor rolls the year, an empty board is not the graduation."""
        v = sp.classify_empty_response(policy, _empty(year=2027), OCT_2)
        assert not v.expected

    def test_empty_a_full_cycle_later_fails_closed(self, policy):
        at = datetime(2027, 10, 1, tzinfo=timezone.utc)
        v = sp.classify_empty_response(policy, _empty(year=2026), at)
        assert not v.expected
        assert v.reason.startswith("after_declared_window")

    @pytest.mark.parametrize(
        "response",
        [
            {"data": []},  # no class year
            {"data": [], "year": "2026", "format": "PROSPECTS_SF"},  # not an int
            {"data": [], "year": True, "format": "PROSPECTS_SF"},  # bool is not a year
            {"data": [], "year": 2026},  # format missing
            {"data": [], "year": 2026, "format": "SUPERFLEX"},  # wrong board
            {"data": None, "year": 2026, "format": "PROSPECTS_SF"},  # not a list
            ["not", "a", "dict"],
        ],
    )
    def test_off_signature_empty_fails_closed(self, policy, response):
        assert not sp.classify_empty_response(policy, response, OCT_2).expected

    def test_non_empty_board_is_never_inactive(self, policy):
        """Rows that were all FILTERED OUT are a parse problem, not a season."""
        resp = {"data": [{"isRookie": False}], "year": 2026, "format": "PROSPECTS_SF"}
        v = sp.classify_empty_response(policy, resp, OCT_2)
        assert not v.expected and v.reason == "response_not_empty"

    def test_undeclared_source_fails_closed(self):
        v = sp.classify_empty_response(None, _empty(), OCT_2)
        assert not v.expected and v.reason == "no_declared_seasonal_policy"


# ── State: explicit, never a success stamp ─────────────────────────────
class TestState:
    def test_inactive_observation_writes_only_the_seasonal_state(self, policy, tmp_path):
        v = sp.classify_empty_response(policy, _empty(), OCT_2)
        state = sp.record_inactive_observation(tmp_path, policy, v, OCT_2)
        assert state["state"] == sp.SEASONALLY_INACTIVE
        assert state["lastObservation"]["rawRowCount"] == 0
        # The whole record is the one state file: no fake freshness stamp.
        assert sorted(p.name for p in tmp_path.iterdir()) == [f"{KEY}_seasonal.json"]
        assert not (tmp_path / f"{KEY}_last_success").exists()
        assert "lastSuccess" not in json.dumps(state)

    def test_refuses_a_non_expected_verdict(self, policy, tmp_path):
        v = sp.classify_empty_response(policy, _empty(), SEP_30)
        with pytest.raises(ValueError):
            sp.record_inactive_observation(tmp_path, policy, v, SEP_30)
        assert not any(tmp_path.iterdir())

    def test_repeated_observations_keep_since_and_advance_verification(self, policy, tmp_path):
        later = datetime(2026, 10, 3, 2, tzinfo=timezone.utc)
        v1 = sp.classify_empty_response(policy, _empty(), OCT_2)
        sp.record_inactive_observation(tmp_path, policy, v1, OCT_2)
        v2 = sp.classify_empty_response(policy, _empty(), later)
        state = sp.record_inactive_observation(tmp_path, policy, v2, later)
        assert state["since"] == "2026-10-02T12:00:00Z"
        assert state["lastInactiveVerifiedAt"] == "2026-10-03T02:00:00Z"
        assert [t["state"] for t in state["transitions"]] == [sp.SEASONALLY_INACTIVE]

    def test_reactivation_is_a_noop_without_an_inactive_state(self, tmp_path):
        assert sp.record_reactivation(tmp_path, KEY, OCT_2, row_count=40) is None
        assert not any(tmp_path.iterdir())

    def test_reactivation_closes_the_window(self, policy, tmp_path):
        v = sp.classify_empty_response(policy, _empty(), OCT_2)
        sp.record_inactive_observation(tmp_path, policy, v, OCT_2)
        jan = datetime(2027, 1, 15, tzinfo=timezone.utc)
        state = sp.record_reactivation(tmp_path, KEY, jan, row_count=60, class_year=2027)
        assert state is not None and state["state"] == sp.ACTIVE
        assert state["lastInactiveVerifiedAt"] is None
        assert [t["state"] for t in state["transitions"]] == [sp.SEASONALLY_INACTIVE, sp.ACTIVE]

    def test_reactivation_requires_rows(self, tmp_path):
        with pytest.raises(ValueError):
            sp.record_reactivation(tmp_path, KEY, OCT_2, row_count=0)

    def test_state_as_of_reads_the_transition_in_force(self, policy, tmp_path):
        v = sp.classify_empty_response(policy, _empty(), OCT_2)
        sp.record_inactive_observation(tmp_path, policy, v, OCT_2)
        jan = datetime(2027, 1, 15, tzinfo=timezone.utc)
        sp.record_reactivation(tmp_path, KEY, jan, row_count=60)
        state = sp.load_state(sp.state_path(tmp_path, KEY))
        assert sp.state_as_of(state, SEP_30) is None
        assert sp.state_as_of(state, datetime(2026, 11, 1, tzinfo=timezone.utc)) == (
            sp.SEASONALLY_INACTIVE
        )
        assert sp.state_as_of(state, datetime(2027, 2, 1, tzinfo=timezone.utc)) == sp.ACTIVE
        assert sp.state_as_of(state, None) == sp.ACTIVE


# ── Readers ─────────────────────────────────────────────────────────────
class TestReaders:
    def _inactive(self, policy, tmp_path, at=OCT_2):
        v = sp.classify_empty_response(policy, _empty(), at)
        sp.record_inactive_observation(tmp_path, policy, v, at)

    def test_contract_reader_sees_inactive_at_board_time(self, policy, tmp_path):
        self._inactive(policy, tmp_path)
        assert set(sp.inactive_sources_as_of(tmp_path, OCT_2)) == {KEY}
        # A board built BEFORE the transition keeps the source (determinism).
        assert sp.inactive_sources_as_of(tmp_path, SEP_30) == {}

    def test_undeclared_state_file_is_ignored(self, tmp_path):
        """A stray state file cannot switch off a source nobody declared."""
        stray = {
            "state": sp.SEASONALLY_INACTIVE,
            "transitions": [{"state": sp.SEASONALLY_INACTIVE, "at": "2026-10-01T00:00:00Z"}],
        }
        (tmp_path / "dlfSf_seasonal.json").write_text(json.dumps(stray), encoding="utf-8")
        assert sp.inactive_sources_as_of(tmp_path, OCT_2) == {}
        verified, lapsed = sp.watchdog_seasonal_split(tmp_path, OCT_2, lambda _k: 24)
        assert verified == {} and lapsed == {}

    def test_watchdog_accepts_only_a_recent_reverification(self, policy, tmp_path):
        self._inactive(policy, tmp_path)
        verified, lapsed = sp.watchdog_seasonal_split(
            tmp_path, datetime(2026, 10, 3, 6, tzinfo=timezone.utc), lambda _k: 24
        )
        assert set(verified) == {KEY} and lapsed == {}
        verified, lapsed = sp.watchdog_seasonal_split(
            tmp_path, datetime(2026, 10, 4, 0, tzinfo=timezone.utc), lambda _k: 24
        )
        assert verified == {} and set(lapsed) == {KEY}


# ── Acquisition vocabulary (reused, not a second one) ──────────────────
class TestAcquisitionVocabulary:
    def test_exit_code_maps_to_seasonally_inactive(self):
        assert state_from_exit_code(SEASONALLY_INACTIVE_EXIT_CODE) == SEASONALLY_INACTIVE

    def test_does_not_collide_with_yahoo_partial_scrape_exit_3(self):
        assert SEASONALLY_INACTIVE_EXIT_CODE != 3

    def test_inactive_is_acquired_but_not_usable(self):
        outcome = AcquisitionOutcome(KEY, SEASONALLY_INACTIVE, row_count=0)
        assert outcome.acquired and not outcome.usable
        assert SEASONALLY_INACTIVE not in USABLE_ACQUISITION_STATES


def test_config_file_is_the_one_the_owner_reads():
    assert sp.CONFIG_PATH == Path(sp.REPO_ROOT) / "config" / "sources" / "seasonal_policy_v1.json"
    assert sp.CONFIG_PATH.exists()
