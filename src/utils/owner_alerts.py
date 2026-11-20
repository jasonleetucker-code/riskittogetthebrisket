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
ATTEMPTED at least one channel is recorded in process memory -- last delivered,
last failed, consecutive failures -- and :func:`delivery_health` publishes it
(booleans, ISO timestamps and a count; ``/api/status`` ``alertDelivery``), so a
box that cannot reach its owner is visible from outside
(``scripts/check_production_slo.py``).  A call with no channel configured
attempted nothing and is not a failure.  The record resets on restart.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone

from src.utils import owner_notify

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


def deliver(
    to_email: str | None,
    subject: str,
    body: str,
    *,
    email: EmailDelivery | None = None,
    push: PushDelivery | None = None,
) -> bool:
    """Push first, e-mail as fallback.  ``True`` when either channel delivered.

    ``push`` defaults to the configured ntfy webhook (absent -> skipped).
    ``email`` is used only for a real address (never :data:`OWNER_CHANNEL`).
    """
    push_fn = push if push is not None else owner_notify.channel()
    attempted = False
    if push_fn is not None:
        attempted = True
        try:
            if push_fn(subject, body):
                _record(True)
                return True
        except Exception:  # noqa: BLE001 - a channel fault must never break the caller
            pass
    delivered = False
    if email is not None and to_email and to_email != OWNER_CHANNEL:
        attempted = True
        try:
            delivered = bool(email(to_email, subject, body))
        except Exception:  # noqa: BLE001
            delivered = False
    if attempted:
        _record(delivered)
    return delivered


def deliver_each(
    to_email: str | None,
    subject: str,
    body: str,
    *,
    email: EmailDelivery | None = None,
    push: PushDelivery | None = None,
) -> dict[str, bool | None]:
    """Try EVERY channel once (an operator test): ``None`` = not configured."""
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
    if attempted:
        _record(any(attempted))
    return out


# ── in-process delivery health ───────────────────────────────────────────

_HEALTH_LOCK = threading.Lock()
_HEALTH: dict[str, float | int | None] = {
    "lastDeliveredAt": None,
    "lastFailedAt": None,
    "consecutiveFailures": 0,
}


def _record(delivered: bool, *, now: float | None = None) -> None:
    """One ATTEMPTED delivery.  A success resets the failure streak."""
    stamp = time.time() if now is None else now
    with _HEALTH_LOCK:
        if delivered:
            _HEALTH["lastDeliveredAt"] = stamp
            _HEALTH["consecutiveFailures"] = 0
        else:
            _HEALTH["lastFailedAt"] = stamp
            _HEALTH["consecutiveFailures"] = int(_HEALTH["consecutiveFailures"] or 0) + 1


def _iso(epoch: float | int | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()


def delivery_health(env: Mapping[str, str] | None = None) -> dict[str, bool | int | str | None]:
    """``/api/status`` ``alertDelivery``: which channels exist and how delivery
    has gone in THIS process.  Booleans, ISO timestamps (``None`` = never) and a
    count only -- no address, no URL, no subject."""
    channels = channels_configured(env)
    with _HEALTH_LOCK:
        snap = dict(_HEALTH)
    return {
        "ntfyConfigured": channels["ntfy"],
        "emailConfigured": channels["email"],
        "lastDeliveredAt": _iso(snap["lastDeliveredAt"]),
        "lastFailedAt": _iso(snap["lastFailedAt"]),
        "consecutiveFailures": int(snap["consecutiveFailures"] or 0),
    }


def reset_delivery_health_for_tests() -> None:
    with _HEALTH_LOCK:
        _HEALTH.update(lastDeliveredAt=None, lastFailedAt=None, consecutiveFailures=0)
