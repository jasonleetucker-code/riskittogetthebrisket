"""Web Push (PWA) delivery + per-user subscription persistence.

Sits next to the existing SMTP delivery path.  A user can subscribe
either, neither, or both — the dispatch helpers in ``server.py``
fan out a notification through every channel a user has enabled.

Storage
───────
Subscriptions live in ``user_kv`` under the ``pushSubscriptions`` key:

    [
      {
        "endpoint": "https://...",
        "keys": {"p256dh": "...", "auth": "..."},
        "ua": "iPhone Safari",        # optional, for the UI list
        "createdAt": "2026-04-26T..."
      },
      ...
    ]

A given device generates a unique ``endpoint``; we de-dup by endpoint
on insert so re-subscribing on the same device replaces rather than
duplicates.

Sending
───────
``send_push(sub, title, body, url=None)`` returns True on success,
False on transient delivery failure, and removes the subscription
on a 404/410 (the browser explicitly told us this endpoint is dead).
Callers walk the subscription list and prune as we go.

VAPID
─────
Public/private keys come from the env vars ``VAPID_PUBLIC_KEY`` and
``VAPID_PRIVATE_KEY`` (base64url-encoded raw EC P-256 keys, no PEM
wrapping).  ``VAPID_CONTACT`` is the ``mailto:`` address browsers
include in delivery failures.  When any of the three is missing,
``is_configured()`` returns False and the dispatch path falls back
to email-only.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any

_LOGGER = logging.getLogger(__name__)

_VAPID_PUBLIC = os.getenv("VAPID_PUBLIC_KEY", "").strip()
_VAPID_PRIVATE = os.getenv("VAPID_PRIVATE_KEY", "").strip()
_VAPID_CONTACT = os.getenv("VAPID_CONTACT", "").strip()


def is_configured() -> bool:
    return bool(_VAPID_PUBLIC and _VAPID_PRIVATE and _VAPID_CONTACT)


def public_key() -> str:
    return _VAPID_PUBLIC


def _private_key_for_pywebpush() -> str:
    """``pywebpush`` accepts the raw base64url private key string
    directly.  We pass it through unchanged so the same value lives
    in env, in test fixtures, and on the wire.
    """
    return _VAPID_PRIVATE


_KV_KEY = "pushSubscriptions"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def list_subscriptions(user_state: dict[str, Any]) -> list[dict[str, Any]]:
    raw = user_state.get(_KV_KEY)
    if isinstance(raw, list):
        return [s for s in raw if isinstance(s, dict) and isinstance(s.get("endpoint"), str)]
    return []


def upsert_subscription(
    user_state: dict[str, Any], sub: dict[str, Any]
) -> list[dict[str, Any]]:
    """Add ``sub`` to the user's list, replacing any record with the
    same endpoint.  Returns the new full list (caller persists)."""
    endpoint = str(sub.get("endpoint") or "").strip()
    keys = sub.get("keys") or {}
    if not endpoint or not isinstance(keys, dict):
        raise ValueError("subscription missing endpoint/keys")
    if not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError("subscription keys missing p256dh/auth")

    record = {
        "endpoint": endpoint,
        "keys": {"p256dh": str(keys["p256dh"]), "auth": str(keys["auth"])},
        "ua": str(sub.get("ua") or "")[:120],
        "createdAt": _utc_iso(),
    }
    current = list_subscriptions(user_state)
    deduped = [s for s in current if s.get("endpoint") != endpoint]
    deduped.append(record)
    return deduped


def remove_subscription(
    user_state: dict[str, Any], endpoint: str
) -> list[dict[str, Any]]:
    current = list_subscriptions(user_state)
    return [s for s in current if s.get("endpoint") != endpoint]


_send_lock = threading.Lock()


def send_push(
    sub: dict[str, Any],
    *,
    title: str,
    body: str,
    url: str | None = None,
    tag: str | None = None,
) -> tuple[bool, bool]:
    """Send a push notification.

    Returns ``(ok, gone)``: ``ok`` is True if delivery succeeded,
    ``gone`` is True if the browser told us the subscription is
    permanently dead (404/410) and the caller should remove it.
    """
    if not is_configured():
        return (False, False)
    try:
        # Lazy import: pywebpush is only loaded when push is in use.
        from pywebpush import WebPushException, webpush
    except Exception as exc:  # pragma: no cover
        _LOGGER.warning("pywebpush unavailable: %s", exc)
        return (False, False)

    payload = {"title": title[:120], "body": body[:300]}
    if url:
        payload["url"] = url
    if tag:
        payload["tag"] = tag[:60]

    with _send_lock:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": sub["keys"],
                },
                data=json.dumps(payload),
                vapid_private_key=_private_key_for_pywebpush(),
                vapid_claims={"sub": _VAPID_CONTACT},
                ttl=60 * 60 * 24,  # 24h: align with custom-alert cooldown
            )
            return (True, False)
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", 0) if exc.response else 0
            if status in (404, 410):
                _LOGGER.info("push subscription gone (%d) — pruning", status)
                return (False, True)
            _LOGGER.warning("push send failed (%s): %s", status, exc)
            return (False, False)
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("push send unexpected error: %s", exc)
            return (False, False)


def fanout(
    user_state: dict[str, Any],
    *,
    title: str,
    body: str,
    url: str | None = None,
    tag: str | None = None,
) -> tuple[int, list[str]]:
    """Send to every subscription on this user.  Returns
    ``(num_delivered, endpoints_to_prune)``."""
    delivered = 0
    to_prune: list[str] = []
    for sub in list_subscriptions(user_state):
        ok, gone = send_push(sub, title=title, body=body, url=url, tag=tag)
        if ok:
            delivered += 1
        if gone:
            to_prune.append(sub["endpoint"])
    return (delivered, to_prune)
