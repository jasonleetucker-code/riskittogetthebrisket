"""The smoke record must stop the churn without freezing the record.

CI reliability lane, 2026-08-20.  See ``scripts/sharp_smoke_record.py``
for the measurement (42 of 66 bot commits to ``main`` in 24 hours) and
the design.

The two failure modes this file pins are opposites, and a naive fix hits
one while dodging the other:

* writing every run  -> 42 commits/day of "still the same", every one of
  them class-C drift under every open PR;
* writing only on change -> the record freezes, and a workflow that has
  silently stopped firing becomes indistinguishable from one reporting a
  stable state.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import sharp_smoke_record as record  # noqa: E402

UNVERIFIABLE = {
    "status": "unverifiable_unauthenticated",
    "cohort": {},
    "ffpcMarket": {},
    "errors": [
        {
            "attempt": 1,
            "type": "Unauthenticated",
            "message": "401 from https://chaseupside.com/api/sharp/cohort",
        }
    ],
    # ``checkedAt`` MUST be present in these fixtures.  Without it,
    # ``result.get("checkedAt")`` returns None on both sides of every
    # comparison, and a mutant that folds the timestamp into the
    # fingerprint passes the whole file.  Measured: it did, before this
    # key was added.  A guard that cannot fail is decoration.
    "checkedAt": "2026-08-20T05:20:00.111111+00:00",
    "eventName": "workflow_run",
    "deployRunId": "1",
    "deployHeadSha": "aaaa",
    "attempts": 1,
}

HEALTHY = {
    "status": "healthy",
    "cohort": {"qualifiedManagers": 12, "seasonRows": 22553},
    "ffpcMarket": {"assetRows": 100},
    "errors": [],
    "checkedAt": "2026-08-20T05:20:00.222222+00:00",
    "eventName": "workflow_run",
    "deployRunId": "2",
    "deployHeadSha": "bbbb",
    "attempts": 3,
}


def _record(previous, result, *, now="2026-08-20T05:20:00+00:00", today="2026-08-20"):
    return record.build_record(previous, result, now_iso=now, today=today)


# --------------------------------------------------------------------------
# the churn
# --------------------------------------------------------------------------


def test_an_unchanged_state_on_the_same_day_is_not_rewritten():
    """The 42-commits-a-day case."""
    first = _record(None, UNVERIFIABLE)
    second = _record(first, UNVERIFIABLE, now="2026-08-20T05:44:00+00:00")
    assert record.decide_write(first, second) is False


def test_a_changed_state_is_written_immediately():
    first = _record(None, UNVERIFIABLE)
    second = _record(first, HEALTHY, now="2026-08-20T06:00:00+00:00")
    assert record.decide_write(first, second) is True


def test_the_day_rollover_writes_a_heartbeat_even_when_nothing_changed():
    """Without this the record freezes and a dead workflow looks alive."""
    first = _record(None, UNVERIFIABLE)
    next_day = _record(first, UNVERIFIABLE, now="2026-08-21T05:20:00+00:00", today="2026-08-21")
    assert record.decide_write(first, next_day) is True
    assert next_day["lastObservedOn"] == "2026-08-21"


def test_the_first_ever_run_writes():
    assert record.decide_write(None, _record(None, UNVERIFIABLE)) is True


def test_an_unparseable_or_older_record_is_not_treated_as_evidence():
    assert record.load_previous(None) is None
    assert record.load_previous("{not json") is None
    assert record.load_previous(json.dumps({"schema": 1, "status": "healthy"})) is None
    good = json.dumps(_record(None, HEALTHY))
    assert record.load_previous(good) is not None


# --------------------------------------------------------------------------
# the fingerprint must not carry time
# --------------------------------------------------------------------------


def test_the_fingerprint_ignores_every_time_varying_field():
    """Folding a clock value in would restore the every-run write.

    This is the mutation this module is most likely to suffer, because
    ``checkedAt`` reads like part of the result.
    """
    later = dict(
        UNVERIFIABLE,
        checkedAt="2026-08-21T09:44:31.987654+00:00",
        attempts=57,
        deployRunId="999",
        deployHeadSha="zzzz",
        eventName="push",
    )
    assert record.state_fingerprint(UNVERIFIABLE) == record.state_fingerprint(later)


def test_the_fingerprint_ignores_checked_at_specifically():
    """Named on its own because it is THE mutant this module invites.

    ``checkedAt`` reads like part of the result, and including it is a
    one-word change that restores the every-run write while the diff
    looks like a tidy-up.  Measured: a mutant adding it passed every
    other test in this file.
    """
    only_time_moved = dict(UNVERIFIABLE, checkedAt="2099-01-01T00:00:00+00:00")
    assert record.state_fingerprint(UNVERIFIABLE) == record.state_fingerprint(only_time_moved)


def test_the_fingerprint_ignores_the_error_message_but_not_its_type():
    other_message = dict(
        UNVERIFIABLE,
        errors=[{"type": "Unauthenticated", "message": "401 from somewhere/else"}],
    )
    assert record.state_fingerprint(UNVERIFIABLE) == record.state_fingerprint(other_message)

    other_type = dict(UNVERIFIABLE, errors=[{"type": "TimeoutError", "message": "read timed out"}])
    assert record.state_fingerprint(UNVERIFIABLE) != record.state_fingerprint(other_type)


def test_a_changed_cohort_changes_the_fingerprint():
    moved = dict(HEALTHY, cohort={"qualifiedManagers": 13, "seasonRows": 22553})
    assert record.state_fingerprint(HEALTHY) != record.state_fingerprint(moved)


# --------------------------------------------------------------------------
# state age vs observation age
# --------------------------------------------------------------------------


def test_state_since_holds_while_the_state_holds():
    first = _record(None, UNVERIFIABLE, now="2026-08-05T09:14:02+00:00", today="2026-08-05")
    later = _record(first, UNVERIFIABLE, now="2026-08-20T05:20:00+00:00", today="2026-08-20")
    assert later["stateSince"] == "2026-08-05T09:14:02+00:00"
    assert later["lastObservedOn"] == "2026-08-20"


def test_state_since_advances_when_the_state_changes():
    first = _record(None, UNVERIFIABLE, now="2026-08-05T09:14:02+00:00", today="2026-08-05")
    changed = _record(first, HEALTHY, now="2026-08-20T05:20:00+00:00", today="2026-08-20")
    assert changed["stateSince"] == "2026-08-20T05:20:00+00:00"


# --------------------------------------------------------------------------
# missing is not zero
# --------------------------------------------------------------------------


def test_an_unmeasured_run_reports_empty_blocks_and_says_so():
    """`cohort: {}` and `cohort: {qualifiedManagers: 0}` are opposite claims."""
    built = _record(None, UNVERIFIABLE)
    assert built["measured"] is False
    assert built["cohort"] == {}
    assert built["ffpcMarket"] == {}
    assert "qualifiedManagers" not in built["cohort"]
    assert built["lastMeasuredOn"] is None


def test_a_measured_run_says_so_and_stamps_the_date():
    built = _record(None, HEALTHY)
    assert built["measured"] is True
    assert built["lastMeasuredOn"] == "2026-08-20"


def test_deploy_failed_and_timeout_are_not_measurements():
    for status in ("deploy_failed", "degraded_timeout", "endpoint_retry", "waiting"):
        assert record.is_measured(status) is False, status


# --------------------------------------------------------------------------
# the one tooth
# --------------------------------------------------------------------------


def test_a_standing_unverifiable_is_not_a_regression():
    """The live situation: never measured, no credential, not a failure."""
    first = _record(None, UNVERIFIABLE)
    assert first["credentialRegression"] is False
    second = _record(first, UNVERIFIABLE, now="2026-08-21T05:20:00+00:00", today="2026-08-21")
    assert second["credentialRegression"] is False


def test_losing_a_capability_the_record_shows_we_had_is_a_regression():
    measured = _record(None, HEALTHY, now="2026-08-20T05:00:00+00:00", today="2026-08-20")
    lost = _record(measured, UNVERIFIABLE, now="2026-08-21T05:00:00+00:00", today="2026-08-21")
    assert lost["credentialRegression"] is True


def test_the_regression_survives_days_of_unverifiable_after_a_measurement():
    """`lastMeasuredOn` is carried forward, so the tooth does not fall out."""
    measured = _record(None, HEALTHY, now="2026-08-20T05:00:00+00:00", today="2026-08-20")
    day_one = _record(measured, UNVERIFIABLE, now="2026-08-21T05:00:00+00:00", today="2026-08-21")
    day_two = _record(day_one, UNVERIFIABLE, now="2026-08-22T05:00:00+00:00", today="2026-08-22")
    assert day_two["lastMeasuredOn"] == "2026-08-20"
    assert day_two["credentialRegression"] is True


def test_other_unhealthy_statuses_are_not_credential_regressions():
    """A failed deploy is not a lost credential; it has its own branch."""
    measured = _record(None, HEALTHY)
    failed = _record(measured, {"status": "deploy_failed", "cohort": {}, "ffpcMarket": {}})
    assert failed["credentialRegression"] is False


# --------------------------------------------------------------------------
# 2026-10-26: the two triggers are not two states (audit RPA-F-019)
# --------------------------------------------------------------------------
#
# Measured on main: 16 record commits in 24 hours, every one a flip between
# ``unverifiable_unauthenticated`` (push-triggered run, which probes) and
# ``deploy_superseded`` / ``deploy_unmeasured`` (deploy-triggered run whose
# deploy was cancelled or skipped, which probes nothing).  Each flip changed
# the fingerprint, hence a commit, hence a fresh ``stateSince`` -- and
# ``stateSince`` is the key the #951 tracker dedups on, so each flip was also
# a new comment (41 marker-carrying comments, 41 distinct ``since`` values).

PUSH_RUN = dict(UNVERIFIABLE, eventName="push", tokenProvisioned=False)
SUPERSEDED = {
    "status": "deploy_superseded",
    "cohort": {},
    "ffpcMarket": {},
    "errors": [],
    "checkedAt": "2026-10-26T16:15:28+00:00",
    "eventName": "workflow_run",
    "deployConclusion": "cancelled",
    "deployRunId": "40357247756",
    "deployHeadSha": "22a2ac8f",
    "attempts": 0,
    "tokenProvisioned": False,
}
UNMEASURED = dict(SUPERSEDED, status="deploy_unmeasured", deployConclusion="skipped")
FAILED = dict(SUPERSEDED, status="deploy_failed", deployConclusion="failure")


class _Tracked:
    """The tracked file as a sequence of runs sees it: only a write changes it."""

    def __init__(self):
        self.file = None
        self.writes = 0
        self.markers = []  # the tracker's (status|stateSince), as the gate would read it

    def run(self, result, *, now, today):
        previous = record.load_previous(json.dumps(self.file) if self.file else None)
        this_run = record.build_record(previous, result, now_iso=now, today=today)
        persisted = record.record_to_persist(previous, this_run)
        if record.decide_write(previous, persisted):
            self.file = persisted
            self.writes += 1
        self.markers.append(f"{this_run['status']}|{this_run['stateSince']}")
        return this_run


def test_the_record_does_not_flap_between_the_push_and_deploy_triggered_runs():
    """THE 16-A-DAY CASE: push, superseded, push, unmeasured, push, superseded."""
    tracked = _Tracked()
    sequence = [PUSH_RUN, SUPERSEDED, PUSH_RUN, UNMEASURED, PUSH_RUN, SUPERSEDED, PUSH_RUN]
    for minute, result in enumerate(sequence):
        tracked.run(result, now=f"2026-10-26T16:{10 + minute:02d}:00+00:00", today="2026-10-26")
    assert tracked.writes == 1, "only the first observation is news; everything after is a repeat"
    assert tracked.file["status"] == "unverifiable_unauthenticated"
    assert tracked.file["stateSince"] == "2026-10-26T16:10:00+00:00"


def test_the_tracker_key_does_not_move_across_a_superseded_run():
    """The #951 marker is ``status|stateSince`` from the run-scoped record.  If
    that moves, the tracker comments again -- which is how 41 comments happened."""
    tracked = _Tracked()
    for minute, result in enumerate([PUSH_RUN, SUPERSEDED, PUSH_RUN, UNMEASURED, PUSH_RUN]):
        tracked.run(result, now=f"2026-10-26T16:{10 + minute:02d}:00+00:00", today="2026-10-26")
    push_markers = {m for m in tracked.markers if m.startswith("unverifiable_unauthenticated|")}
    assert len(push_markers) == 1, push_markers


def test_a_superseded_run_still_reports_itself_as_superseded_to_the_gate():
    """Shielding the file must not shield the gate's input."""
    tracked = _Tracked()
    tracked.run(PUSH_RUN, now="2026-10-26T16:10:00+00:00", today="2026-10-26")
    this_run = tracked.run(SUPERSEDED, now="2026-10-26T16:11:00+00:00", today="2026-10-26")
    assert this_run["status"] == "deploy_superseded"
    assert this_run["measured"] is False
    assert tracked.file["status"] == "unverifiable_unauthenticated"


def test_a_real_deploy_failure_is_a_state_change_and_is_recorded():
    """``deploy_failed`` carries a verdict (the gate goes red), unlike the other two."""
    assert "deploy_failed" not in record.NO_VERDICT_STATUSES
    tracked = _Tracked()
    tracked.run(PUSH_RUN, now="2026-10-26T16:10:00+00:00", today="2026-10-26")
    tracked.run(FAILED, now="2026-10-26T16:11:00+00:00", today="2026-10-26")
    assert tracked.file["status"] == "deploy_failed"
    tracked.run(PUSH_RUN, now="2026-10-26T16:12:00+00:00", today="2026-10-26")
    assert tracked.file["status"] == "unverifiable_unauthenticated"
    assert tracked.writes == 3


def test_no_verdict_statuses_are_exactly_the_runs_that_probed_nothing():
    assert record.NO_VERDICT_STATUSES == {"deploy_superseded", "deploy_unmeasured"}
    assert not (record.NO_VERDICT_STATUSES & record.MEASURED_STATUSES)


def test_a_superseded_run_does_not_advance_the_heartbeat():
    """``lastObservedOn`` answers "are we still CHECKING?".  A run that probed
    nothing did not check, so it cannot vouch for the day."""
    first = _record(None, PUSH_RUN, now="2026-10-26T10:00:00+00:00", today="2026-10-26")
    skipped = _record(first, SUPERSEDED, now="2026-10-27T01:00:00+00:00", today="2026-10-27")
    persisted = record.record_to_persist(first, skipped)
    assert persisted is first
    assert record.decide_write(first, persisted) is False
    # A real probe the next day does advance it.
    probed = _record(first, PUSH_RUN, now="2026-10-27T02:00:00+00:00", today="2026-10-27")
    assert record.decide_write(first, record.record_to_persist(first, probed)) is True


def test_with_no_previous_record_a_superseded_run_is_written_rather_than_dropped():
    """Nothing to preserve, and an honest 'no verdict yet' beats an empty file."""
    built = _record(None, SUPERSEDED)
    assert record.record_to_persist(None, built) is built
    assert record.decide_write(None, built) is True


# --------------------------------------------------------------------------
# run-only fields vs state fields (stated in the module docstring)
# --------------------------------------------------------------------------


def test_run_only_fields_never_change_the_fingerprint():
    base = dict(PUSH_RUN)
    for field, value in (
        ("checkedAt", "2030-01-01T00:00:00+00:00"),
        ("attempts", 80),
        ("eventName", "workflow_run"),
        ("deployRunId", "123456"),
        ("deployHeadSha", "ffff"),
        ("deployConclusion", "success"),
    ):
        changed = dict(base, **{field: value})
        assert record.state_fingerprint(changed) == record.state_fingerprint(base), field


def test_the_token_state_is_part_of_the_state():
    """Absent vs presented-and-refused are different problems with different
    owners, and a 401 looks identical for both."""
    absent = dict(PUSH_RUN, tokenProvisioned=False)
    rejected = dict(PUSH_RUN, tokenProvisioned=True)
    assert record.state_fingerprint(absent) != record.state_fingerprint(rejected)
    assert record.decide_write(_record(None, absent), _record(None, rejected)) is True


def test_an_unrecorded_token_state_is_not_the_same_as_absent():
    """Missing is not False."""
    unknown = {k: v for k, v in PUSH_RUN.items() if k != "tokenProvisioned"}
    assert _record(None, unknown)["tokenProvisioned"] is None
    assert record.state_fingerprint(unknown) != record.state_fingerprint(PUSH_RUN)


def test_the_record_stores_a_boolean_never_the_credential():
    built = _record(None, dict(PUSH_RUN, tokenProvisioned=True))
    assert built["tokenProvisioned"] is True
    assert set(built) >= {"tokenProvisioned", "measured", "stateFingerprint"}
