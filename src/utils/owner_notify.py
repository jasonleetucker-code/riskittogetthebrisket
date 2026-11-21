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
  credential for that topic, so it is never logged, printed or returned --
  :func:`validate` answers with a state and a reason CODE, never the value.
* **ONE validator** (:func:`validate`).  ``owner_alerts.channels_configured``,
  the Signals probe's drop-in check, the box test push and the startup warning
  all ask it, so "configured" means the same thing everywhere.  Shell callers
  ask it through ``python -m src.utils.owner_notify --check``.
* **https only** (plus http to loopback, for a self-hosted relay on the box);
  lower-case scheme, a host, no embedded credentials, no whitespace.
* **Redirects are not followed**: a 3xx is a failed delivery, so the scheme
  check cannot be bypassed by a redirect to an http host.
* Callers own deduplication; this module only delivers one message.
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

WEBHOOK_ENV = "NOTIFY_WEBHOOK_URL"
DEFAULT_TIMEOUT_SECONDS = 5.0
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}

#: :func:`validate` answers.  ``rejected:<reason>`` for every refusal.
STATE_OK = "ok"
STATE_UNSET = "unset"
REJECTED_PREFIX = "rejected:"
#: Every reason code :func:`validate` can give (names only, never a value).
REJECT_REASONS = ("scheme", "no_host", "whitespace", "userinfo", "malformed")

#: ``python -m src.utils.owner_notify --check`` exit codes.
EXIT_OK = 0
EXIT_REJECTED = 1
EXIT_UNSET = 3

#: ``(url, title, body, timeout) -> HTTP status``; injectable for tests.
Transport = Callable[[str, str, str, float], int]


def validate(raw: str | None) -> str:
    """``"ok"`` | ``"unset"`` | ``"rejected:<reason>"`` for a webhook value.

    The answer carries a reason CODE (:data:`REJECT_REASONS`), never any part of
    the value.  Surrounding whitespace is ignored (an env file or a systemd
    ``Environment=`` line may carry it); anything else is checked as written:

    * ``whitespace`` -- a space, tab or newline inside the value;
    * ``malformed``  -- a control or non-ASCII character, or a value urllib
      cannot split (a broken ``[ipv6`` host, a non-numeric port);
    * ``scheme``     -- anything but lower-case ``https://``, or ``http://`` to
      loopback (a quoted value lands here: its scheme is ``"https``);
    * ``no_host``    -- ``https://`` with no host;
    * ``userinfo``   -- ``user:pass@host``: credentials embedded in the URL.
    """
    value = (raw or "").strip()
    if not value:
        return STATE_UNSET
    for ch in value:
        if ch.isspace():
            return REJECTED_PREFIX + "whitespace"
        if not (0x21 <= ord(ch) <= 0x7E):
            return REJECTED_PREFIX + "malformed"
    try:
        parts = urllib.parse.urlsplit(value)
        host = parts.hostname or ""
        parts.port  # noqa: B018 - raises ValueError on a non-numeric/out-of-range port
    except ValueError:
        return REJECTED_PREFIX + "malformed"
    # ``urlsplit`` lower-cases the scheme it returns; the raw prefix must
    # already be lower-case, as the workflows' ``== https://*`` test requires.
    scheme = value.split(":", 1)[0]
    if scheme == "https":
        pass
    elif scheme == "http" and host in _LOOPBACK:
        pass
    else:
        return REJECTED_PREFIX + "scheme"
    if "@" in parts.netloc:
        return REJECTED_PREFIX + "userinfo"
    if not host:
        return REJECTED_PREFIX + "no_host"
    return STATE_OK


def public_state(state: str) -> str:
    """:func:`validate`'s answer as an identifier (``rejected:scheme`` ->
    ``rejected_scheme``), for outputs that admit identifier-shaped strings only
    (the Signals probe's public projection)."""
    return state.replace(":", "_")


def webhook_url() -> str | None:
    """The configured owner webhook, or ``None`` when unset or not allowed."""
    raw = (os.environ.get(WEBHOOK_ENV) or "").strip()
    return raw if validate(raw) == STATE_OK else None


def _allowed(url: str) -> bool:
    """Back-compat alias: ``True`` exactly when :func:`validate` says ``ok``."""
    return validate(url) == STATE_OK


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect: urllib then raises ``HTTPError`` for the 3xx."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


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
    with _OPENER.open(req, timeout=timeout) as resp:  # noqa: S310 - scheme checked
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
    if not target or validate(target) != STATE_OK:
        return False
    text = f"{title}\n\n{body}" if title else body
    try:
        status = int((transport or _urllib_transport)(target, title, text, timeout))
    except Exception:  # noqa: BLE001 - best effort; never fail or delay the caller
        return False
    return 200 <= status < 300


def channel(
    *, transport: Transport | None = None, timeout: float = DEFAULT_TIMEOUT_SECONDS
) -> Callable[[str, str], bool] | None:
    """A ``(subject, body) -> delivered`` callable, or ``None`` when no owner
    webhook is configured (so callers can tell "not configured" from "failed")."""
    url = webhook_url()
    if url is None:
        return None
    return lambda subject, body: send(subject, body, url=url, transport=transport, timeout=timeout)


def check_exit_code(state: str) -> int:
    """The ``--check`` exit code for a :func:`validate` answer."""
    if state == STATE_OK:
        return EXIT_OK
    if state == STATE_UNSET:
        return EXIT_UNSET
    return EXIT_REJECTED


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            f"Validate {WEBHOOK_ENV} from the environment (never prints it). "
            f"Exit {EXIT_OK} ok, {EXIT_REJECTED} rejected, {EXIT_UNSET} unset."
        )
    )
    parser.add_argument("--check", action="store_true", required=True)
    parser.parse_args(argv)
    state = validate(os.environ.get(WEBHOOK_ENV))
    print(f"{WEBHOOK_ENV}: {state}", file=sys.stderr)
    return check_exit_code(state)


if __name__ == "__main__":
    raise SystemExit(main())
