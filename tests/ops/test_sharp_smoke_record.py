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
