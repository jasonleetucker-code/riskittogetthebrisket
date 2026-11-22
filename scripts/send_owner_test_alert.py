#!/usr/bin/env python3
"""Send one labelled TEST push per production alert class from the box (STAB-2).

Run on the production host by ``signals-health-probe.yml`` mode ``notify-test``.
Three checks, each reported separately:

1. **The ``.env`` URL** (``sent``).  It reads the owner webhook from the app
   ``.env`` -- the same file the backend and the alert-sweep timer load -- and
   POSTs a test message per alert class, so the owner can confirm on the phone
   that every class arrives.  This proves the FILE: it passes even when the
   backend was never restarted onto that URL.
2. **The running backend's producers** (``backend``).  With the
   ``SIGNAL_ALERT_CRON_TOKEN`` bearer from the same ``.env`` it calls the LOCAL
   backend's ``POST /api/test-alert?producers=1``, which sends one ``[TEST]``
   notice through each real producer (the ops sweep, the staleness sweep,
   ``send_alert``, the Signals reconnect notice) with the RUNNING process's
   channels.  Without a token it says ``token_absent`` and fails nothing.
3. **The push-capable drop-in units** (``dropinUnits``): each unit in
   ``signals_health.PUSH_DROPIN_UNITS``, by name (spelled as an identifier),
   and whether its own ``NOTIFY_WEBHOOK_URL`` is configured (``None`` = the
   unit is not loaded or could not be read: unknown, never "configured").

Delivery to the ntfy server is reported here; actual RECEIPT can only be
confirmed by the owner.

Output is public (a workflow log): booleans, class and unit names, reason codes
and the webhook's validation state (``ok`` / ``unset`` / ``rejected_<reason>``,
from ``owner_notify.validate``).  The webhook URL and the token are never
printed.  Exit codes: 0 every check that ran passed; 1 a push failed, or the
backend check ran and did not deliver on every producer; 3 the ``.env`` holds no
usable owner push channel (no ``.env`` push was sent; the backend and drop-in
checks still run and are reported).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.sources import signals_health as H  # noqa: E402
from src.utils import owner_alerts, owner_notify  # noqa: E402

#: (class key, title) -- one per alert class the owner directive names.
TEST_CLASSES: tuple[tuple[str, str], ...] = (
    ("signals_auth", "[TEST] Signals session needs reconnect"),
    ("source_freshness", "[TEST] Source freshness failure"),
    ("deploy_lag", "[TEST] Production deploy lag"),
    ("backup", "[TEST] Backups stale or failed"),
    ("health", "[TEST] Production health degraded"),
)
BODY = (
    "Test message from the production box (signals-health-probe notify-test). "
    "No action needed. If this arrived, alerts of this class reach you."
)

#: The RUNNING backend's producer test (loopback only; see ``server.test_alert``).
LOCAL_PRODUCER_TEST_URL = "http://127.0.0.1:8000/api/test-alert?producers=1"
#: The bearer that route accepts besides an admin session (read from ``.env``).
CRON_TOKEN_ENV = "SIGNAL_ALERT_CRON_TOKEN"
#: Every producer is sent synchronously, each bounded by its channels' own
#: timeouts (ntfy 5 s, SMTP 15 s per port), so the worst case is ~2 minutes.
BACKEND_TIMEOUT_SECONDS = 180.0
#: ``server.OWNER_ALERT_PRODUCER_REASONS`` (pinned equal by test); anything else
#: the backend answers is reported as ``unrecognized``, never echoed.
PRODUCER_REASONS = frozenset(
    {"delivered", "all_channels_failed", "not_configured", "producer_error"}
)
#: The backend's HTTP status -> this check's state.
_BACKEND_STATES = {
    200: "ok",
    400: "not_configured",
    401: "refused",
    403: "refused",
    # The shared owner test-alert budget is spent (server._TEST_ALERT_CAPACITY):
    # the backend is healthy, nothing was sent, run again after retryAfterSeconds.
    429: "rate_limited",
    502: "failed",
}
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")

#: ``(url, token, timeout) -> (HTTP status, parsed JSON body or None)``.
BackendPost = Callable[[str, str, float], tuple[int, Any]]

# Loopback is always direct: a proxy configured on the box must not see the token.
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _urllib_post(url: str, token: str, timeout: float) -> tuple[int, Any]:
    req = urllib.request.Request(
        url, data=b"", method="POST", headers={"Authorization": f"Bearer {token}"}
    )
    try:
        with _DIRECT.open(req, timeout=timeout) as resp:  # noqa: S310 - fixed loopback URL
            status, raw = int(resp.status), resp.read()
    except urllib.error.HTTPError as exc:
        status, raw = int(exc.code), exc.read()
    try:
        return status, json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return status, None


def _identifier(value: Any) -> str | None:
    text = str(value) if value is not None else ""
    return text if _IDENTIFIER.match(text) else None


def _unit_identifier(unit: str) -> str:
    """A systemd unit name as a public-safe identifier
    (``riskit-uptime.service`` -> ``riskit_uptime_service``)."""
    return re.sub(r"[^A-Za-z0-9_]", "_", unit)


def _project_producers(body: Any) -> dict[str, dict[str, Any]] | None:
    """The backend's per-producer answers, allowlisted: identifier-shaped names,
    ``delivered`` as a bool or ``None``, a known reason, an identifier error
    class.  ``None`` when the body carries no producer map."""
    producers = body.get("producers") if isinstance(body, Mapping) else None
    if not isinstance(producers, Mapping) or not producers:
        return None
    out: dict[str, dict[str, Any]] = {}
    for name, row in producers.items():
        key = _identifier(name)
        if key is None or not isinstance(row, Mapping):
            continue
        delivered = row.get("delivered")
        reason = row.get("reason")
        entry: dict[str, Any] = {
            "delivered": delivered if delivered is None or isinstance(delivered, bool) else None,
            "reason": reason if reason in PRODUCER_REASONS else "unrecognized",
        }
        if row.get("errorClass") is not None:
            entry["errorClass"] = _identifier(row.get("errorClass")) or "withheld"
        out[key] = entry
    return out or None


def backend_producer_check(
    env: Mapping[str, str] | None, *, post: BackendPost | None = None
) -> tuple[dict[str, Any], bool | None]:
    """``(report, passed)``: ``passed`` is ``None`` when the check could not run
    (no token in ``.env``) -- said, never counted as a failure."""
    token = ((env or {}).get(CRON_TOKEN_ENV) or "").strip()
    report: dict[str, Any] = {
        "tokenConfigured": bool(token),
        "state": "token_absent",
        "httpStatus": None,
        "ntfyState": None,
        "producers": None,
    }
    if not token:
        return report, None
    try:
        status, body = (post or _urllib_post)(
            LOCAL_PRODUCER_TEST_URL, token, BACKEND_TIMEOUT_SECONDS
        )
    except Exception as exc:  # noqa: BLE001 - a class, never a message (public log)
        report.update(state="unreachable", errorClass=type(exc).__name__)
        return report, False
    producers = _project_producers(body)
    state = _BACKEND_STATES.get(status, "unexpected_status")
    if state in ("ok", "failed", "not_configured") and producers is None:
        state = "unexpected_response"
    ntfy = body.get("ntfyState") if isinstance(body, Mapping) else None
    report.update(
        state=state,
        httpStatus=status,
        ntfyState=_identifier(owner_notify.public_state(ntfy)) if isinstance(ntfy, str) else None,
        producers=producers,
    )
    if state == "rate_limited":
        retry = body.get("retryAfterSeconds") if isinstance(body, Mapping) else None
        # An integer or nothing: never echo a backend value of another shape.
        report["retryAfterSeconds"] = (
            retry if isinstance(retry, int) and not isinstance(retry, bool) else None
        )
    passed = state == "ok" and all(p["delivered"] is True for p in (producers or {}).values())
    return report, passed


def dropin_units(app_dir: Path, show: H.ShowFn) -> dict[str, bool | None]:
    """Each push-capable drop-in unit (``signals_health.PUSH_DROPIN_UNITS``) by
    name, and whether its own webhook is configured -- judged by the probe's
    own reader (``alert_routing_section``), not a second one."""
    routing = H.alert_routing_section(Path(app_dir), {}, show)
    return {
        _unit_identifier(unit): routing.get(field) for field, unit in H.PUSH_DROPIN_UNITS.items()
    }


def run(
    app_dir: Path,
    *,
    transport: owner_notify.Transport | None = None,
    post: BackendPost | None = None,
    show: H.ShowFn | None = None,
) -> tuple[dict, int]:
    env = H._env_file(Path(app_dir) / ".env")  # noqa: SLF001 - shared parser
    out: dict = {"mode": "notify_test", "envFileReadable": env is not None}
    url = (env or {}).get(owner_notify.WEBHOOK_ENV, "").strip()
    # The ONE validator; its answer is a state + reason code, never the value.
    state = owner_notify.validate(url)
    configured = state == owner_notify.STATE_OK
    out["configured"] = {"ntfy": configured}
    out["ntfyState"] = owner_notify.public_state(state)
    if not configured:
        out["sent"] = {key: None for key, _ in TEST_CLASSES}
        code = 3
    else:
        sent = {}
        for key, title in TEST_CLASSES:
            result = owner_alerts.deliver_each(
                None,
                title,
                BODY,
                push=lambda s, b: owner_notify.send(s, b, url=url, transport=transport),
                # Not the server: never write its user_kv store (/api/status
                # alertDelivery) from this out-of-process operator run.
                persist=False,
            )
            sent[key] = result["ntfy"]
        out["sent"] = sent
        code = 0 if all(sent.values()) else 1
    out["backend"], backend_passed = backend_producer_check(env, post=post)
    if backend_passed is False and code == 0:
        code = 1
    out["dropinUnits"] = dropin_units(Path(app_dir), show or H.systemd_show)
    return out, code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--app-dir", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        out, code = run(args.app_dir)
    except Exception as exc:  # noqa: BLE001 - print a class, never a traceback (public log)
        print(json.dumps({"mode": "notify_test", "error": type(exc).__name__}))
        return 1
    H.assert_public_safe(out)
    print(json.dumps(out, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
