"""Owner push notification through the existing ``NOTIFY_WEBHOOK_URL`` path.

The repository already has ONE owner push channel: ``deploy/monitoring/
uptime_check.sh`` POSTs a plain-text body to ``NOTIFY_WEBHOOK_URL`` (a private
ntfy topic, or any webhook that accepts a text POST), set as a systemd drop-in.
This module is that same contract for Python callers -- same variable, same
plain-text POST, same "unset means nothing external is contacted" rule -- so no
feature grows its own notifier.

Rules:

* **Never raises.**  A notification is best-effort: an unreachable ntfy server
  returns ``False`` and must never delay or fail the caller's real work.
* **Short timeout** (:data:`DEFAULT_TIMEOUT_SECONDS`), applied per socket
  operation by urllib -- not a hard wall-clock cap (DNS is not covered), so
  callers keep their own outer bound (e.g. a systemd ``TimeoutStartSec``).
* **The URL is treated as a secret.**  A private ntfy topic name is a bearer
  credential for that topic, so it is never logged, printed or returned.
* **https only** (plus http to loopback, for a self-hosted relay on the box).
* Callers own deduplication; this module only delivers one message.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

WEBHOOK_ENV = "NOTIFY_WEBHOOK_URL"
DEFAULT_TIMEOUT_SECONDS = 5.0
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}

#: ``(url, title, body, timeout) -> HTTP status``; injectable for tests.
Transport = Callable[[str, str, str, float], int]


def webhook_url() -> str | None:
    """The configured owner webhook, or ``None`` when unset or not allowed."""
    raw = (os.environ.get(WEBHOOK_ENV) or "").strip()
    return raw if raw and _allowed(raw) else None


def _allowed(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" and parts.netloc:
        return True
    return parts.scheme == "http" and (parts.hostname or "") in _LOOPBACK


def _urllib_transport(url: str, title: str, body: str, timeout: float) -> int:
    headers = {"Content-Type": "text/plain; charset=utf-8"}
    if title:
        # ntfy reads the Title header; other text webhooks ignore it.  Header
        # values must be latin-1, so anything else stays in the body only.
        try:
            title.encode("latin-1")
            headers["Title"] = title
        except UnicodeEncodeError:
            pass
    req = urllib.request.Request(url, data=body.encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - scheme checked
        return int(resp.status)


def send(
    title: str,
    body: str,
    *,
    url: str | None = None,
    transport: Transport | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> bool:
    """POST one plain-text message.  ``True`` only on a 2xx.  Never raises."""
    target = url if url is not None else webhook_url()
    if not target or not _allowed(target):
        return False
    text = f"{title}\n\n{body}" if title else body
    try:
        status = (transport or _urllib_transport)(target, title, text, timeout)
    except Exception:  # noqa: BLE001 - best effort; never fail or delay the caller
        return False
    return 200 <= int(status) < 300


def channel(
    *, transport: Transport | None = None, timeout: float = DEFAULT_TIMEOUT_SECONDS
) -> Callable[[str, str], bool] | None:
    """A ``(subject, body) -> delivered`` callable, or ``None`` when no owner
    webhook is configured (so callers can tell "not configured" from "failed")."""
    url = webhook_url()
    if url is None:
        return None
    return lambda subject, body: send(subject, body, url=url, transport=transport, timeout=timeout)
