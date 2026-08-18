"""An undelivered alert is not a delivered one.

AUDIT FINDING F-20 (2026-08-18)
───────────────────────────────
``check_and_alert`` recorded the 4-hour cooldown BEFORE it attempted
delivery::

    for a in alerts:
        if _should_fire(a, state, now=now):
            firing.append(a)
            state[a.category] = {"firedAt": now, ...}   # cooldown banked
    _save_ops_state(state, path=kv_path)                # and persisted

    to_deliver = firing + recovery_alerts
    if not to_deliver or delivery is None or not to_email:
        return summary                                  # early return
    try:
        summary["delivered"] = bool(delivery(to_email, subject, body))
    except Exception:
        summary["delivered"] = False                    # no rollback

So an unconfigured mailer — or one that raises — spent the window without
sending anything, and the next sweep inside four hours found ``firedAt`` and
stayed silent.  The operator was never told.

WORSE THAN SILENCE
──────────────────
``_detect_recovery`` reads the same state, so when the condition cleared the
operator received ``[RECOVERY] <category> resolved`` — a resolution notice
for an incident they were never informed of.  Reproduced over three sweeps
against a persistent kv: the only email delivered was the recovery.

WHY 41 PASSING TESTS MISSED IT
──────────────────────────────
None of them ran the function with ``delivery=None``, with an empty
``to_email``, or with a delivery callable that raises — the three paths on
which the cooldown is spent without an email being sent.  They all assert
what happens when delivery works.

THREE FACTS, NOT ONE
────────────────────
"we decided to alert", "we attempted delivery" and "the operator was told"
are different, and the state must keep them apart.  ``_should_fire`` now
keys on the last DELIVERED alert.
"""

from __future__ import annotations

import pytest

from src.api import ops_alerts


UNHEALTHY = {"ok": False, "status": "invalid", "errors": ["contract not initialized"]}


def _sweep(kv, *, delivery=None, to_email="ops@example.com"):
    return ops_alerts.check_and_alert(
        contract_health=dict(UNHEALTHY),
        delivery=delivery,
        to_email=to_email,
        kv_path=kv,
    )


@pytest.fixture
def kv(tmp_path):
    return tmp_path / "ops_state.json"


def test_a_working_mailer_still_gets_its_cooldown(kv) -> None:
    """The guard must not simply disable cooldowns — that would turn a real
    incident into a mail flood, which is what the cooldown exists to stop."""
    sent = []
    delivery = lambda to, subj, body: (sent.append(subj), True)[1]  # noqa: E731

    first = _sweep(kv, delivery=delivery)
    assert first["fired"] >= 1 and first["delivered"] is True

    second = _sweep(kv, delivery=delivery)
    assert second["fired"] == 0, "a delivered alert must not re-fire inside the window"
    assert len(sent) == 1


def test_an_unconfigured_mailer_does_not_consume_the_window(kv) -> None:
    """The measured defect, inverted.

    Two sweeps with no delivery configured, then one with a working mailer:
    the operator must still be told.
    """
    _sweep(kv, delivery=None)
    _sweep(kv, delivery=None)

    sent = []
    later = _sweep(kv, delivery=lambda to, s, b: (sent.append(s), True)[1])
    assert later["fired"] >= 1, "the cooldown was spent while nothing was sent"
    assert len(sent) == 1


def test_an_empty_recipient_does_not_consume_the_window(kv) -> None:
    _sweep(kv, delivery=lambda to, s, b: True, to_email="")
    sent = []
    later = _sweep(kv, delivery=lambda to, s, b: (sent.append(s), True)[1])
    assert later["fired"] >= 1
    assert len(sent) == 1


def test_a_raising_mailer_does_not_consume_the_window(kv) -> None:
    def boom(to, subject, body):
        raise RuntimeError("smtp down")

    first = _sweep(kv, delivery=boom)
    assert first["delivered"] is False

    sent = []
    later = _sweep(kv, delivery=lambda to, s, b: (sent.append(s), True)[1])
    assert later["fired"] >= 1, "a delivery exception spent the window"
    assert len(sent) == 1


def test_a_mailer_returning_false_does_not_consume_the_window(kv) -> None:
    """``delivery`` returns a bool; ``False`` means it did not send."""
    _sweep(kv, delivery=lambda to, s, b: False)
    sent = []
    later = _sweep(kv, delivery=lambda to, s, b: (sent.append(s), True)[1])
    assert later["fired"] >= 1
    assert len(sent) == 1


def test_no_recovery_for_an_incident_never_reported(kv) -> None:
    """A resolution notice for something the operator was never told about is
    worse than silence."""
    _sweep(kv, delivery=None)  # condition fires, nothing sent

    recovered = ops_alerts.check_and_alert(
        contract_health={"ok": True, "status": "healthy", "errors": []},
        delivery=lambda to, s, b: True,
        to_email="ops@example.com",
        kv_path=kv,
    )
    assert (
        recovered["recovered"] == 0
    ), "emitted a RECOVERY for a failure notice that was never delivered"


def test_the_summary_names_an_unconfigured_mailer(kv) -> None:
    """ "Nothing to send" and "could not send" must not read the same."""
    summary = _sweep(kv, delivery=None)
    assert summary.get("deliveryConfigured") is False
    assert summary["delivered"] is False


def test_undelivered_state_is_not_written_as_delivered(kv) -> None:
    """Structural: whatever the state records after an undelivered sweep, it
    must not carry a ``deliveredAt`` — that is the value ``_should_fire``
    keys on, so writing one would re-create the defect one layer down.

    Read through the module's own accessor rather than parsing the file:
    ``user_kv`` owns that storage format, and a test that hard-codes JSON
    would be asserting against an implementation detail it does not own.
    """
    _sweep(kv, delivery=None)
    state = ops_alerts._load_ops_state(path=kv)
    for _category, entry in (state or {}).items():
        if isinstance(entry, dict):
            assert not entry.get("deliveredAt"), entry
