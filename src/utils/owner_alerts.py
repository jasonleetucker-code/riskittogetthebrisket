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
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping

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
        and (env.get("ALERT_PASSWORD") or "").strip()
    )


def channels_configured(env: Mapping[str, str] | None = None) -> dict[str, bool]:
    """``{"ntfy": bool, "email": bool}`` -- presence only, never a value."""
    env = os.environ if env is None else env
    raw = (env.get(owner_notify.WEBHOOK_ENV) or "").strip()
    return {
        "ntfy": bool(raw) and owner_notify._allowed(raw),  # noqa: SLF001 - same module family
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
    if push_fn is not None:
        try:
            if push_fn(subject, body):
                return True
        except Exception:  # noqa: BLE001 - a channel fault must never break the caller
            pass
    if email is not None and to_email and to_email != OWNER_CHANNEL:
        try:
            return bool(email(to_email, subject, body))
        except Exception:  # noqa: BLE001
            return False
    return False


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
    return out
