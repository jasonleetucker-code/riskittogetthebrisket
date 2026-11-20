#!/usr/bin/env python3
"""Send one labelled TEST push per production alert class from the box (STAB-2).

Run on the production host by ``signals-health-probe.yml`` mode ``notify-test``.
It reads the owner webhook from the app ``.env`` -- the same file the backend
and the alert-sweep timer load -- and POSTs a test message per alert class, so
the owner can confirm on the phone that every class arrives.  Delivery to the
ntfy server is reported here; actual RECEIPT can only be confirmed by the owner.

Output is public (a workflow log): booleans, class names and the webhook's
validation state (``ok`` / ``unset`` / ``rejected_<reason>``, from
``owner_notify.validate``).  The webhook URL is never printed.  Exit codes: 0
every push accepted; 1 at least one push failed; 3 no owner push channel
configured, or the configured value was rejected (nothing sent).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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


def run(app_dir: Path, *, transport: owner_notify.Transport | None = None) -> tuple[dict, int]:
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
        return out, 3
    sent = {}
    for key, title in TEST_CLASSES:
        result = owner_alerts.deliver_each(
            None,
            title,
            BODY,
            push=lambda s, b: owner_notify.send(s, b, url=url, transport=transport),
        )
        sent[key] = result["ntfy"]
    out["sent"] = sent
    return out, 0 if all(sent.values()) else 1


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
