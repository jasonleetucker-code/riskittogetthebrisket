"""One owner-alert delivery for every server-side alert (owner directive 2026-11-19, STAB-2).

Before this module the box had two disconnected channels:

* ``NOTIFY_WEBHOOK_URL`` (ntfy, :mod:`src.utils.owner_notify`) -- used only by the
  uptime probe and the Signals reconnect notice;
* e-mail (``ALERT_TO`` + Gmail SMTP) -- used by every other alert: the backup and
  uptime watchdogs (``server.send_alert``), the ops-alert sweep and the per-source
  staleness sweep.  Outbound 465 is firewalled on the production VPS.

The 2026-11-18 Signals health probe recorded ZERO reconnect-notice sends on any
channel across ~400 h, so the owner was told nothing.  Configuring ntfy would not
have helped the e-mail-only alerts.  This module routes all of them the same way:
**the owner's ntfy webhook first, e-mail as fallback** -- the order
``signals_auth.deliver_reconnect_notice`` already uses.

Rules (the ``owner_notify`` contract, unchanged):

* Never raises; a channel fault returns ``False``.
* The webhook URL is a secret: never logged, printed or returned.
  :func:`channels_configured` reports booleans only.
* "Not configured" is distinguishable from "configured and failed": callers get
  ``None`` from :func:`recipient` when no channel exists at all.

Delivery health (2026-11-20): every :func:`deliver` / :func:`deliver_each` that
ATTEMPTED at least one channel is recorded -- last delivered, last failed,
consecutive failures -- and :func:`delivery_health` publishes it (booleans, ISO
timestamps and a count; ``/api/status`` ``alertDelivery``), so a box that cannot
reach its owner is visible from outside (``scripts/check_production_slo.py``).
A call with no channel configured attempted nothing and is not a failure.

The record PERSISTS across restarts (2026-11-20 review): a sweep attempts at
most a couple of deliveries, so the three failures the SLO rule breaches on take
several sweeps, and an in-memory record reset by a deploy in between read 0
("OK") while delivery was failing.  It lives in user_kv under the ops-alert
system user (beside ``ops_alerts.record_sweep``'s stamp), best-effort: a store
fault is logged (exception class only) and never breaks a delivery, and this
process's own record still answers.  No record anywhere is UNKNOWN
(``consecutiveFailures: None``), never 0.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils import owner_notify

_LOGGER = logging.getLogger(__name__)

#: Stand-in recipient for callers whose contract requires an address
#: (``ops_alerts.check_and_alert`` / ``source_health_alerts.check_and_alert`` only
#: test it for truthiness and pass it back to the delivery callable).  It is never
#: used as an e-mail address: :func:`deliver` skips e-mail for it.
OWNER_CHANNEL = "owner-channel"

#: ``(to_email, subject, body) -> delivered`` -- the e-mail half, injected by the caller.
EmailDelivery = Callable[[str, str, str], bool]
#: ``(subject, body) -> delivered`` -- the push half; defaults to ``owner_notify``.
PushDelivery = Callable[[str, str], bool]


def _email_configured(env: Mapping[str, str]) -> bool:
    enabled = (env.get("ALERT_ENABLED") or "").strip().lower() in {"1", "true", "yes", "on"}
    return bool(
        enabled
        and (env.get("ALERT_TO") or "").strip()
        and (env.get("ALERT_FROM") or "").strip()
        # server.py reads GMAIL_APP_PASSWORD as the alias of ALERT_PASSWORD.
        and (env.get("ALERT_PASSWORD") or env.get("GMAIL_APP_PASSWORD") or "").strip()
    )


def ntfy_state(env: Mapping[str, str] | None = None) -> str:
    """The webhook's :func:`owner_notify.validate` answer -- a state and a reason
    code (``ok`` / ``unset`` / ``rejected:<reason>``), never the value."""
    env = os.environ if env is None else env
    return owner_notify.validate(env.get(owner_notify.WEBHOOK_ENV))


def channels_configured(env: Mapping[str, str] | None = None) -> dict[str, bool]:
    """``{"ntfy": bool, "email": bool}`` -- presence only, never a value."""
    env = os.environ if env is None else env
    return {
        "ntfy": ntfy_state(env) == owner_notify.STATE_OK,
        "email": _email_configured(env),
    }


def recipient(alert_to: str | None, env: Mapping[str, str] | None = None) -> str | None:
    """What to pass as ``to_email``: the address, the owner-channel stand-in, or
    ``None`` when nothing is configured (so the sweep reports "not configured")."""
    if (alert_to or "").strip():
        return alert_to.strip()
    return OWNER_CHANNEL if channels_configured(env)["ntfy"] else None


#: Every producer TEST notice's title starts with this (``POST
#: /api/test-alert?producers=1``, ``scripts/send_owner_test_alert.py``).
TEST_TITLE_PREFIX = "[TEST]"
#: The first line of a producer TEST notice's body: what follows is that
#: producer's real formatting, and nothing fired.
TEST_BODY_BANNER = (
    "TEST MESSAGE from an operator check of the alert producers "
    "(POST /api/test-alert?producers=1). Nothing fired, nothing changed and no "
    "action is needed: the text below only shows this producer's real formatting."
)


def mark_test(subject: str, body: str) -> tuple[str, str]:
    """``(subject, body)`` of a producer's real notice, labelled as a TEST."""
    return f"{TEST_TITLE_PREFIX} {subject}", f"{TEST_BODY_BANNER}\n\n{body}"


def deliver(
    to_email: str | None,
    subject: str,
    body: str,
    *,
    email: EmailDelivery | None = None,
    push: PushDelivery | None = None,
    persist: bool = True,
    record: bool = True,
) -> bool:
    """Push first, e-mail as fallback.  ``True`` when either channel delivered.

    ``push`` defaults to the configured ntfy webhook (absent -> skipped).
    ``email`` is used only for a real address (never :data:`OWNER_CHANNEL`).
    ``persist=False`` keeps the attempt out of the store (a process that is not
    the server, e.g. ``scripts/send_owner_test_alert.py``).  ``record=False``
    keeps it out of the delivery-health record altogether, in memory too (an
    operator's producer test, which must not move ``alertDelivery``).
    """
    push_fn = push if push is not None else owner_notify.channel()
    attempted = False
    delivered = False
    if push_fn is not None:
        attempted = True
        try:
            delivered = bool(push_fn(subject, body))
        except Exception:  # noqa: BLE001 - a channel fault must never break the caller
            delivered = False
    if not delivered and email is not None and to_email and to_email != OWNER_CHANNEL:
        attempted = True
        try:
            delivered = bool(email(to_email, subject, body))
        except Exception:  # noqa: BLE001
            delivered = False
    if attempted and record:
        _record(delivered, persist=persist)
    return delivered


def deliver_each(
    to_email: str | None,
    subject: str,
    body: str,
    *,
    email: EmailDelivery | None = None,
    push: PushDelivery | None = None,
    persist: bool = True,
    record: bool = True,
) -> dict[str, bool | None]:
    """Try EVERY channel once (an operator test): ``None`` = not configured.
    ``persist`` and ``record`` as in :func:`deliver`."""
    out: dict[str, bool | None] = {"ntfy": None, "email": None}
    push_fn = push if push is not None else owner_notify.channel()
    if push_fn is not None:
        try:
            out["ntfy"] = bool(push_fn(subject, body))
        except Exception:  # noqa: BLE001
            out["ntfy"] = False
    if email is not None and to_email and to_email != OWNER_CHANNEL:
        try:
            out["email"] = bool(email(to_email, subject, body))
        except Exception:  # noqa: BLE001
            out["email"] = False
    attempted = [v for v in out.values() if v is not None]
    if attempted and record:
        _record(any(attempted), persist=persist)
    return out


# ── delivery health (persisted, best-effort) ─────────────────────────────

#: The user_kv synthetic user the record persists under -- the one
#: ``ops_alerts.record_sweep`` stamps the sweep under (pinned equal by test).
HEALTH_STATE_USER = "_system_ops_alerts"
#: The record's key in that user's state blob.
HEALTH_STATE_KEY = "alertDelivery"
#: The user_kv store file; ``None`` = ``user_kv.USER_KV_PATH`` (read at call
#: time).  ``tests/runtime_data_isolation.py`` points it at a per-test file.
HEALTH_STORE_PATH: Path | None = None

#: ``{"lastDeliveredEpoch", "lastFailedEpoch", "consecutiveFailures"}``.
HealthRecord = dict[str, Any]

_HEALTH_LOCK = threading.Lock()
#: This process's view of the record (``None`` until it records one).
_HEALTH: dict[str, HealthRecord | None] = {"record": None}


def _store_path() -> Path:
    if HEALTH_STORE_PATH is not None:
        return Path(HEALTH_STORE_PATH)
    from src.api import user_kv  # noqa: PLC0415 - lazily, from a utils module

    return Path(user_kv.USER_KV_PATH)


def _epoch(value: Any) -> tuple[bool, float | None]:
    """``(readable, value)``: ``None`` (never happened) or a number of seconds."""
    if value is None:
        return True, None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False, None
    return True, float(value)


def _coerce_record(raw: Any) -> HealthRecord | None:
    """A stored record, or ``None`` when absent or unreadable -- never a 0."""
    if not isinstance(raw, dict):
        return None
    failures = raw.get("consecutiveFailures")
    if isinstance(failures, bool) or not isinstance(failures, int) or failures < 0:
        return None
    delivered_ok, delivered = _epoch(raw.get("lastDeliveredEpoch"))
    failed_ok, failed = _epoch(raw.get("lastFailedEpoch"))
    if not (delivered_ok and failed_ok):
        return None
    return {
        "lastDeliveredEpoch": delivered,
        "lastFailedEpoch": failed,
        "consecutiveFailures": failures,
    }


def _latest_event(record: HealthRecord) -> float:
    stamps = [s for s in (record["lastDeliveredEpoch"], record["lastFailedEpoch"]) if s is not None]
    return max(stamps) if stamps else float("-inf")


def _later(a: float | None, b: float | None) -> float | None:
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def _merge(a: HealthRecord | None, b: HealthRecord | None) -> HealthRecord | None:
    """Two views of the record: the most recent EVENT decides the streak, and
    each timestamp is the later of the two."""
    if a is None:
        return b
    if b is None:
        return a
    newer = a if _latest_event(a) >= _latest_event(b) else b
    return {
        "lastDeliveredEpoch": _later(a["lastDeliveredEpoch"], b["lastDeliveredEpoch"]),
        "lastFailedEpoch": _later(a["lastFailedEpoch"], b["lastFailedEpoch"]),
        "consecutiveFailures": newer["consecutiveFailures"],
    }


def _advance(prior: HealthRecord | None, delivered: bool, stamp: float) -> HealthRecord:
    """The record after one ATTEMPTED delivery; a success resets the streak.
    With no prior record the streak starts at this attempt -- a lower bound,
    since attempts made before any record existed are not known."""
    if prior is None:
        record: HealthRecord = {
            "lastDeliveredEpoch": None,
            "lastFailedEpoch": None,
            "consecutiveFailures": 0,
        }
    else:
        record = dict(prior)
    if delivered:
        record["lastDeliveredEpoch"] = stamp
        record["consecutiveFailures"] = 0
    else:
        record["lastFailedEpoch"] = stamp
        record["consecutiveFailures"] += 1
    return record


def _persist(delivered: bool, stamp: float, memory: HealthRecord | None) -> HealthRecord | None:
    """Advance the STORED record under the user_kv write lock.  Returns the new
    record, or ``None`` when the store could not be written (logged with the
    exception class only, never raised)."""
    written: dict[str, HealthRecord] = {}

    def _apply(entry: dict[str, Any]) -> None:
        base = _merge(_coerce_record(entry.get(HEALTH_STATE_KEY)), memory)
        written["record"] = _advance(base, delivered, stamp)
        entry[HEALTH_STATE_KEY] = written["record"]

    try:
        from src.api import user_kv  # noqa: PLC0415

        user_kv.mutate_user_state(HEALTH_STATE_USER, _apply, path=_store_path())
    except Exception as exc:  # noqa: BLE001 - delivery never fails over its bookkeeping
        _LOGGER.warning(
            "owner-alert delivery health not persisted (%s); this process keeps its own record",
            type(exc).__name__,
        )
        return None
    return written.get("record")


def _read_stored_with_state() -> tuple[HealthRecord | None, str]:
    """``(stored record, state)``: state is ``"recorded"``, ``"none"`` (the box
    has never attempted a delivery: nothing to read) or ``"unreadable"``.
    Read-only: a missing store is answered without creating it."""
    try:
        path = _store_path()
        if not path.is_file():
            return None, "none"
        from src.api import user_kv  # noqa: PLC0415

        state = user_kv.get_user_state(HEALTH_STATE_USER, path=path)
    except Exception as exc:  # noqa: BLE001 - a diagnostic never raises
        _LOGGER.warning("owner-alert delivery health unreadable (%s)", type(exc).__name__)
        return None, "unreadable"
    raw = state.get(HEALTH_STATE_KEY)
    if raw is None:
        return None, "none"
    record = _coerce_record(raw)
    return record, ("recorded" if record is not None else "unreadable")


def _read_stored() -> HealthRecord | None:
    """The stored record; ``None`` when there is none or it cannot be read."""
    return _read_stored_with_state()[0]


def _record(delivered: bool, *, now: float | None = None, persist: bool = True) -> None:
    """One ATTEMPTED delivery: advance the stored record (best-effort) and
    this process's own."""
    stamp = time.time() if now is None else now
    with _HEALTH_LOCK:
        memory = _HEALTH["record"]
    written = _persist(delivered, stamp, memory) if persist else None
    with _HEALTH_LOCK:
        if written is not None:
            _HEALTH["record"] = _merge(_HEALTH["record"], written)
        else:
            _HEALTH["record"] = _advance(_HEALTH["record"], delivered, stamp)


def _iso(epoch: float | int | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()


def delivery_health(env: Mapping[str, str] | None = None) -> dict[str, bool | int | str | None]:
    """``/api/status`` ``alertDelivery``: which channels exist and how delivery
    has gone -- the stored record merged with this process's own.  Booleans,
    ISO timestamps (``None`` = never) and a count (``None`` = no attempt is
    recorded, or the record is unreadable: never published as 0) -- no
    address, no URL, no subject.  ``deliveryRecord`` says which:
    ``"recorded"``, ``"none"`` (no delivery has ever been attempted, so none
    has failed -- every attempt is persisted) or ``"unreadable"``."""
    channels = channels_configured(env)
    stored, stored_state = _read_stored_with_state()
    with _HEALTH_LOCK:
        record = _merge(stored, _HEALTH["record"])
    if record is None:
        return {
            "ntfyConfigured": channels["ntfy"],
            "emailConfigured": channels["email"],
            "lastDeliveredAt": None,
            "lastFailedAt": None,
            "consecutiveFailures": None,
            "deliveryRecord": "unreadable" if stored_state == "unreadable" else "none",
        }
    return {
        "ntfyConfigured": channels["ntfy"],
        "emailConfigured": channels["email"],
        "lastDeliveredAt": _iso(record["lastDeliveredEpoch"]),
        "lastFailedAt": _iso(record["lastFailedEpoch"]),
        "consecutiveFailures": record["consecutiveFailures"],
        "deliveryRecord": "recorded",
    }


def reset_delivery_health_for_tests(*, store: bool = True) -> None:
    """Forget this process's record and, unless ``store=False`` (a simulated
    restart), the stored one."""
    with _HEALTH_LOCK:
        _HEALTH["record"] = None
    if not store:
        return
    path = _store_path()
    if path.is_file():
        from src.api import user_kv  # noqa: PLC0415

        user_kv.mutate_user_state(
            HEALTH_STATE_USER, lambda entry: entry.pop(HEALTH_STATE_KEY, None), path=path
        )
