"""Owner step schedule for source freshness (owner directive 2026-10-19 §2).

Days since the last GENUINE publisher update:

    0-7 -> 1.00 | 8-14 -> 0.75 | 15-21 -> 0.50 | 22-30 -> 0.25 | >30 -> 0

``days = floor((asOf - clock) / 24 h)`` between UTC instants.  The clock is a
vendor-stated publication time where one is recorded, else the last observed
content change; an unchanged re-download never moves it; an update time we
cannot establish is never fresh.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.sources import freshness as fr
from src.sources.dataset_integrity import parse_board
from src.sources.dataset_state import observe

NOW = datetime(2026, 10, 19, 6, 0, tzinfo=timezone.utc)
CFG = fr.load_config()
STEP = fr.load_step_schedule()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _state(
    clock: datetime,
    *,
    first_observed: datetime | None = None,
    upstream: str | None = None,
    rows: dict[str, str] | None = None,
    subset: str = "players",
    health: str = "HEALTHY",
) -> dict:
    first = first_observed or (clock - timedelta(days=200))
    return {
        "subsets": {
            subset: {
                "changeHistory": [
                    {"at": _iso(clock), "broad": True, "rowsChanged": 50, "rowsTotal": 100}
                ],
                "firstObservedAt": _iso(first),
                "firstObservationIsBaseline": True,
                "lastAnyMeaningfulChangeAt": _iso(clock),
                "lastBroadDatasetChangeAt": _iso(clock),
                "rowCount": 100,
                "rowCountHistory": [100],
                "rowChangedAt": rows or {},
            }
        },
        "health": {"state": health, "errors": []},
        "upstream": {"publishedAt": upstream, "version": None},
    }


def _v2(key: str, state: dict | None, *, as_of: datetime = NOW) -> fr.SourceWeighting:
    return fr.assess_source(key, state, as_of=as_of, cfg=CFG, schedule=fr.SCHEDULE_V2, step=STEP)


class TestTheOwnersNumbers:
    def test_config_is_exactly_the_directive(self):
        assert STEP.steps == ((7, 1.0), (14, 0.75), (21, 0.5), (30, 0.25))
        assert STEP.beyond == 0.0
        assert STEP.unknown == 0.0

    @pytest.mark.parametrize(
        "days, expected",
        [(0, 1.0), (7, 1.0), (8, 0.75), (14, 0.75), (15, 0.5), (21, 0.5)]
        + [(22, 0.25), (30, 0.25), (31, 0.0), (365, 0.0)],
    )
    def test_step_table(self, days, expected):
        assert STEP.freshness_for_days(days) == expected

    def test_it_multiplies_the_base_weight(self):
        # Base 1.0 -> 1.00 / 0.75 / 0.50 / 0.25 / 0.00 week by week.
        for days, want in ((3, 1.0), (10, 0.75), (17, 0.5), (25, 0.25), (40, 0.0)):
            sw = _v2("dlfSf", _state(NOW - timedelta(days=days)))
            factor, _ = sw.factor_for_row(is_pick=False, row_key=None)
            assert 1.0 * factor * sw.health_factor * sw.coverage_factor == want


class TestDayBoundaries:
    """Pinned at every step edge, exactly and one second before."""

    @pytest.mark.parametrize(
        "edge, before, after",
        [(8, 1.0, 0.75), (15, 0.75, 0.5), (22, 0.5, 0.25), (31, 0.25, 0.0)],
    )
    def test_edges(self, edge, before, after):
        exactly = NOW - timedelta(days=edge)
        just_before = exactly + timedelta(seconds=1)
        assert _v2("dlfSf", _state(just_before)).subsets["players"].freshness == before
        assert _v2("dlfSf", _state(exactly)).subsets["players"].freshness == after

    def test_whole_days_are_utc_instants_not_calendar_dates(self):
        clock = datetime(2026, 10, 11, 23, 59, tzinfo=timezone.utc)
        # 7 d 6 h 1 m later, across eight calendar dates: still day 7.
        assert fr.whole_days_elapsed(clock, NOW) == 7
        other_tz = clock.astimezone(timezone(timedelta(hours=-7)))
        assert fr.whole_days_elapsed(other_tz, NOW) == 7

    def test_a_future_clock_is_day_zero(self):
        assert fr.whole_days_elapsed(NOW + timedelta(hours=3), NOW) == 0


class TestTheClockIsAGenuineUpdate:
    def test_unchanged_redownload_never_resets_the_clock(self):
        text = "name,rank\n" + "\n".join(f"Player {i},{i}" for i in range(1, 101))
        board = parse_board(text, signal="rank")
        published = NOW - timedelta(days=40)
        state = observe(None, source_key="dlfSf", board=board, observed_at=published)
        changed = text.replace("Player 1,1\nPlayer 2,2", "Player 2,1\nPlayer 1,2")
        changed = changed.replace("Player 3,3\nPlayer 4,4", "Player 4,3\nPlayer 3,4")
        changed = changed.replace("Player 5,5\nPlayer 6,6", "Player 6,5\nPlayer 5,6")
        update_at = NOW - timedelta(days=20)
        state = observe(
            state,
            source_key="dlfSf",
            board=parse_board(changed, signal="rank"),
            observed_at=update_at,
        )
        # Re-downloaded successfully every day since, content unchanged.
        for d in range(19, -1, -1):
            state = observe(
                state,
                source_key="dlfSf",
                board=parse_board(changed, signal="rank"),
                observed_at=NOW - timedelta(days=d),
            )
        sub = _v2("dlfSf", state).subsets["players"]
        assert sub.clock_basis == fr.CLOCK_BASIS_CONTENT
        assert sub.genuine_update_at() == update_at.replace(microsecond=0)
        assert sub.freshness == 0.5  # day 20, not day 0

    def test_a_recorded_publisher_time_is_the_clock_for_any_source(self):
        # fantasyProsIdp is not declared EXPLICIT in the v1 config on main;
        # a recorded vendor time is still its clock under v2.
        broad = NOW - timedelta(days=25)
        vendor = NOW - timedelta(days=45)
        sub = _v2("fantasyProsIdp", _state(broad, upstream=_iso(vendor))).subsets["players"]
        assert sub.clock_basis == fr.CLOCK_BASIS_PUBLISHER
        assert sub.genuine_update_at() == vendor
        assert sub.freshness == 0.0
        assert sub.style == fr.STYLE_EXPLICIT

    def test_publisher_time_never_fresher_than_observed_content(self):
        # A cosmetic vendor edit moved the stamp; the data did not change.
        broad = NOW - timedelta(days=12)
        vendor = NOW - timedelta(days=1)
        sub = _v2("idpShowCombined", _state(broad, upstream=_iso(vendor))).subsets["players"]
        assert sub.clock_basis == fr.CLOCK_BASIS_CONTENT
        assert sub.genuine_update_at() == broad
        assert sub.freshness == 0.75

    def test_a_future_publisher_time_is_ignored(self):
        broad = NOW - timedelta(days=3)
        vendor = NOW + timedelta(days=2)
        sub = _v2("fantasyProsIdp", _state(broad, upstream=_iso(vendor))).subsets["players"]
        assert sub.clock_basis == fr.CLOCK_BASIS_CONTENT
        assert sub.freshness == 1.0

    def test_a_genuine_new_publication_restores_full_weight_immediately(self):
        assert _v2("dlfSf", _state(NOW - timedelta(days=45))).subsets["players"].freshness == 0.0
        assert _v2("dlfSf", _state(NOW - timedelta(hours=2))).subsets["players"].freshness == 1.0


class TestUnknownIsNeverFresh:
    def test_first_observation_baseline_votes_at_zero(self):
        first = NOW - timedelta(days=3)
        state = _state(first, first_observed=first)
        state["subsets"]["players"]["changeHistory"] = []
        sub = _v2("dlfSf", state).subsets["players"]
        assert sub.clock_basis == fr.CLOCK_BASIS_UNKNOWN
        assert sub.freshness == 0.0
        assert sub.state == fr.STATE_UNMEASURED
        assert sub.genuine_update_at() is None

    def test_a_baseline_older_than_the_schedule_is_proven_stale(self):
        first = NOW - timedelta(days=40)
        state = _state(first, first_observed=first)
        state["subsets"]["players"]["changeHistory"] = []
        sub = _v2("dlfSf", state).subsets["players"]
        assert sub.freshness == 0.0
        assert sub.state == fr.STATE_QUARANTINED

    def test_no_recorded_state_is_unmeasured_not_zero(self):
        # No dataset state at all is a MEASUREMENT GAP, not evidence about the
        # source: the long-standing unmeasured posture (base weight), under
        # both rules.
        sw = _v2("dlfSf", None)
        assert sw.measured is False
        assert sw.factor_for_row(is_pick=False, row_key=None) == (1.0, None)

    def test_a_board_older_than_our_tracking_is_unmeasured_not_zero(self):
        # Replaying a board from before this source was first observed: the
        # freshness record does not reach the board's time, so there is
        # nothing to apply (the replay posture), never a fabricated clock.
        later = NOW + timedelta(days=5)
        sub = _v2("dlfSf", _state(later, first_observed=later)).subsets["players"]
        assert sub.clock_at is None
        assert sub.clock_basis == fr.CLOCK_BASIS_NOT_TRACKED
        assert sub.freshness == 1.0
        assert sub.state == fr.STATE_UNMEASURED
        assert sub.genuine_update_at() is None
        assert sub.to_dict()["freshnessPct"] is None

    def test_tracked_but_unknown_is_zero_while_untracked_is_unmeasured(self):
        # The two cases side by side: we watched the board since T0 and never
        # saw it publish (unknown -> 0) versus the board predates T0
        # (not tracked -> unmeasured).
        first = NOW - timedelta(days=3)
        state = _state(first, first_observed=first)
        state["subsets"]["players"]["changeHistory"] = []
        tracked = _v2("dlfSf", state).subsets["players"]
        untracked = _v2("dlfSf", state, as_of=first - timedelta(days=1)).subsets["players"]
        assert (tracked.clock_basis, tracked.freshness) == (fr.CLOCK_BASIS_UNKNOWN, 0.0)
        assert (untracked.clock_basis, untracked.freshness) == (fr.CLOCK_BASIS_NOT_TRACKED, 1.0)


class TestRowLevelClocks:
    def test_a_revised_row_votes_at_its_own_step(self):
        board_clock = NOW - timedelta(days=10)
        rows = {"josh allen": _iso(NOW - timedelta(days=1)), "joe burrow": _iso(board_clock)}
        sw = _v2("idpTradeCalc", _state(board_clock, rows=rows))
        sub = sw.subsets["players"]
        assert sub.style != fr.STYLE_EXPLICIT
        assert sw.factor_for_row(is_pick=False, row_key="josh allen")[0] == 1.0
        assert sw.factor_for_row(is_pick=False, row_key="joe burrow")[0] == 0.75
        assert sub.freshness == 0.75

    def test_a_row_still_on_the_baseline_is_unknown(self):
        first = NOW - timedelta(days=60)
        board_clock = first  # no broad change since the first observation
        rows = {"a": _iso(NOW - timedelta(days=2)), "b": _iso(first)}
        state = _state(board_clock, first_observed=first, rows=rows)
        state["subsets"]["players"]["changeHistory"] = []
        sw = _v2("idpTradeCalc", state)
        assert sw.factor_for_row(is_pick=False, row_key="a")[0] == 1.0
        assert sw.factor_for_row(is_pick=False, row_key="b")[0] == 0.0

    def test_picks_have_their_own_clock(self):
        state = _state(NOW - timedelta(days=2))
        picks = _state(NOW - timedelta(days=35), subset="picks")
        state["subsets"]["picks"] = picks["subsets"]["picks"]
        sw = _v2("idpTradeCalc", state)
        assert sw.factor_for_row(is_pick=False, row_key=None)[0] == 1.0
        assert sw.factor_for_row(is_pick=True, row_key=None)[0] == 0.0


class TestScope:
    def test_the_ktc_market_benchmark_stays_on_v1(self):
        sw = _v2("ktcCrowdTradesSfTep", _state(NOW - timedelta(days=10)))
        assert sw.schedule == fr.SCHEDULE_V1
        assert sw.subsets["players"].schedule == fr.SCHEDULE_V1

    def test_v1_is_untouched_by_the_v2_fields(self):
        state = _state(NOW - timedelta(days=2))
        v1 = fr.assess_source("dlfSf", state, as_of=NOW, cfg=CFG)
        d = v1.to_dict()
        assert "freshnessSchedule" not in d
        assert "clockBasis" not in d["subsets"]["players"]
        v2 = _v2("dlfSf", state).to_dict()
        assert v2["freshnessSchedule"] == fr.SCHEDULE_V2
        sub = v2["subsets"]["players"]
        assert sub["clockBasis"] == fr.CLOCK_BASIS_CONTENT
        assert sub["daysSinceGenuineUpdate"] == 2
        assert sub["freshnessPct"] == 100.0

    def test_descriptor_strings(self):
        v1 = fr.weighting_descriptor(fr.SCHEDULE_V1, CFG)
        assert v1 == {
            "configVersion": CFG.version,
            "curve": CFG.curve,
            "formula": "effective = base x freshness(age / expectedCadence) x health x coverage",
        }
        v2 = fr.weighting_descriptor(fr.SCHEDULE_V2)
        assert v2["curve"] == "STEP_V2"
        assert "0-7d 1, 8-14d 0.75, 15-21d 0.5, 22-30d 0.25, >30d 0" in v2["formula"]


class TestScheduleFileValidation:
    def _write(self, tmp_path, payload):
        p = tmp_path / "sched.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p

    def test_rejects_increasing_freshness(self, tmp_path):
        p = self._write(
            tmp_path,
            {"schedule": [{"maxDays": 7, "freshness": 0.5}, {"maxDays": 14, "freshness": 0.75}]},
        )
        with pytest.raises(fr.StepScheduleError):
            fr.load_step_schedule(p)

    def test_rejects_non_ascending_days(self, tmp_path):
        p = self._write(
            tmp_path,
            {"schedule": [{"maxDays": 7, "freshness": 1.0}, {"maxDays": 7, "freshness": 0.5}]},
        )
        with pytest.raises(fr.StepScheduleError):
            fr.load_step_schedule(p)

    def test_rejects_an_empty_schedule(self, tmp_path):
        with pytest.raises(fr.StepScheduleError):
            fr.load_step_schedule(self._write(tmp_path, {"schedule": []}))


class TestTheFlag:
    def test_flag_selects_the_rule(self, monkeypatch):
        from src.api import feature_flags

        monkeypatch.setenv("RISKIT_FEATURE_SOURCE_FRESHNESS_SCHEDULE_V2", "0")
        feature_flags.reload()
        try:
            assert fr.active_schedule() == fr.SCHEDULE_V1
            monkeypatch.setenv("RISKIT_FEATURE_SOURCE_FRESHNESS_SCHEDULE_V2", "1")
            feature_flags.reload()
            assert fr.active_schedule() == fr.SCHEDULE_V2
        finally:
            monkeypatch.delenv("RISKIT_FEATURE_SOURCE_FRESHNESS_SCHEDULE_V2", raising=False)
            feature_flags.reload()

    def test_default_is_off_activation_held_for_the_owner(self):
        """Owner decision 2026-10-20 on PR #1831 (Option B): implementation
        and percentages approved, activation held.  The lock with its full
        rationale is tests/api/test_freshness_v2_hold_locked.py; every v2
        test in this module forces the rule explicitly."""
        from src.api.feature_flags import _DEFAULTS

        assert _DEFAULTS["source_freshness_schedule_v2"] is False


class TestOnePublisherClockOwner:
    """#1817 D5 (``fantasyProsIdp`` EXPLICIT via ``styleFlag``) and the v2
    generalisation (every source with a recorded vendor time) are ONE rule:
    ``freshness.publisher_clock_style``."""

    NOW = datetime(2026, 10, 19, 6, 0, tzinfo=timezone.utc)

    def _state(self, published_days_ago: float, content_days_ago: float) -> dict:
        content = self.NOW - timedelta(days=content_days_ago)
        published = self.NOW - timedelta(days=published_days_ago)
        iso = content.isoformat()
        return {
            "subsets": {
                "players": {
                    "changeHistory": [
                        {"at": iso, "broad": True, "rowsChanged": 90, "rowsTotal": 100}
                    ],
                    "firstObservedAt": (content - timedelta(days=200)).isoformat(),
                    "lastAnyMeaningfulChangeAt": iso,
                    "lastBroadDatasetChangeAt": iso,
                    "rowCount": 100,
                    "rowCountHistory": [100],
                }
            },
            "health": {"state": "HEALTHY", "errors": []},
            "upstream": {"publishedAt": published.isoformat()},
        }

    def _clock(self, key, schedule, *, d5_on=True):
        from src.api import feature_flags

        mp = pytest.MonkeyPatch()
        mp.setenv("RISKIT_FEATURE_FANTASYPROS_IDP_UPSTREAM_CLOCK", "1" if d5_on else "0")
        feature_flags.reload()
        try:
            cfg = fr.load_config()
            sw = fr.assess_source(
                key, self._state(20, 3), as_of=self.NOW, cfg=cfg, schedule=schedule
            )
        finally:
            mp.undo()
            feature_flags.reload()
        return sw.subset_for(False)

    def test_v1_publisher_clock_only_for_declared_sources(self):
        assert self._clock("fantasyProsIdp", fr.SCHEDULE_V1).clock == "upstreamPublishedAt"
        assert self._clock("fantasyCalc", fr.SCHEDULE_V1).clock == "lastBroadDatasetChangeAt"

    def test_v2_generalises_to_every_recorded_vendor_time(self):
        assert self._clock("fantasyProsIdp", fr.SCHEDULE_V2).clock == "upstreamPublishedAt"
        sub = self._clock("fantasyCalc", fr.SCHEDULE_V2)
        assert sub.clock == "upstreamPublishedAt"
        assert sub.style_evidence.get("explicitFromRecordedUpstream") is True

    def test_d5_rollback_is_honoured_under_both_rules(self):
        for schedule in (fr.SCHEDULE_V1, fr.SCHEDULE_V2):
            sub = self._clock("fantasyProsIdp", schedule, d5_on=False)
            assert sub.clock == "lastBroadDatasetChangeAt", schedule
        sub = self._clock("fantasyProsIdp", fr.SCHEDULE_V2, d5_on=False)
        assert sub.style_evidence.get("publisherClockWithheldBy") == (
            "fantasypros_idp_upstream_clock"
        )

    def test_one_clock_block_in_assess_subset(self):
        import inspect

        src = inspect.getsource(fr.assess_subset)
        assert src.count('"upstreamPublishedAt"') == 1
        assert "publisher_clock_style(" in src
        assert "publishedAt" not in src.replace('get("publishedAt")', "", 1)
