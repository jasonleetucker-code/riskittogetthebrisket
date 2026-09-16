#!/usr/bin/env python3
"""Is a scrape currently making the live server unreachable?

    python scripts/scrape_activity.py https://chaseupside.com
    # exit 0 = an active, non-stalled scrape explains the unreachability
    # exit 1 = no such scrape; unreachability is a real fault
    # exit 2 = could not tell (status unreachable/unparseable)

WHY THIS EXISTS
───────────────
``server.py``'s startup path launches a scrape three seconds after boot
(``initial_scrape`` -> ``asyncio.sleep(3)`` -> ``run_scraper(trigger="startup")``),
and the scrape's browser-launch phase blocks the process. Every deploy
restarts the service, so every deploy creates a window in which the box is
alive but answers nothing — ``/api/health`` itself included.

That window is a KNOWN, BOUNDED recovery state, not a fault, and the repo
already says so: ``verify_live_source_coverage.py`` retries only while the
server reports an active non-stalled scrape, after a one-shot check turned
this same window into a rollback (2026-09-09 incident).

This module is the ONE definition of that predicate. It is imported by
``verify_live_source_coverage.py`` rather than copied, and exposed as a CLI so
the deploy's post-deploy smoke test in ``.github/workflows/deploy.yml`` can ask
the same question from bash instead of growing a second, drifting answer.

WHAT IT IS NOT
──────────────
It is not a reason to pass a failing probe. It distinguishes "could not reach
the app" from "the app answered with the wrong thing", and only the first is
ever attributable to a scrape. A wrong status code — an auth gate returning
200 where 401 is required, say — is a correctness statement and must fail on
the spot, whatever the scrape is doing.
"""

from __future__ import annotations

import argparse
import json
import urllib.request

_TIMEOUT_SECONDS = 20

#: HTTP codes that mean "the request never reached a working app": curl's
#: 000 (timeout/connection failure) and the gateway codes nginx returns when
#: the upstream is blocked or down. Anything else is an ANSWER, and an answer
#: is never excused by a scrape.
UNREACHABLE_CODES: frozenset[str] = frozenset({"000", "000000", "502", "503", "504"})


def is_unreachable_code(code: str | int) -> bool:
    """True when ``code`` means the app never answered.

    ``503`` is included deliberately: nginx emits it when the upstream is
    unavailable. A route that answers 503 *by design* (``/api/health`` when
    degraded) is matched by its own expected-code pattern before this is ever
    consulted, so including it here cannot mask a legitimate degraded answer.
    """
    return str(code).strip() in UNREACHABLE_CODES


def recovering_scrape(status: dict) -> bool:
    """True only for an active scrape that still has a chance to finish.

    Stalled and hung scrapes are NOT recovering — those are the states that
    should fail a deploy rather than be waited out.
    """
    return bool(status.get("running")) and not bool(status.get("stalled") or status.get("hung"))


def fetch_status(base_url: str, *, timeout: int = _TIMEOUT_SECONDS) -> dict | None:
    """One shot at ``<base>/api/status``. ``None`` when it cannot be read.

    Deliberately single-shot: callers that need a retry budget own it, so this
    cannot silently multiply someone else's bounded window.
    """
    url = base_url.rstrip("/") + "/api/status"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "scrape-activity"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return payload if isinstance(payload, dict) else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "base_url",
        nargs="?",
        help="public base URL, e.g. https://chaseupside.com",
    )
    ap.add_argument(
        "--check-code",
        metavar="CODE",
        help=(
            "classify an observed HTTP code instead of querying a server. "
            "Exit 0 when the code means the app never answered (and a scrape "
            "could therefore explain it), 1 when the app answered."
        ),
    )
    ap.add_argument("--timeout", type=int, default=_TIMEOUT_SECONDS)
    args = ap.parse_args()

    if args.check_code is not None:
        if is_unreachable_code(args.check_code):
            print(f"scrape-activity: {args.check_code} means the app never answered")
            return 0
        print(
            f"scrape-activity: {args.check_code} is an ANSWER — "
            "a scrape never excuses a wrong status code"
        )
        return 1

    if not args.base_url:
        ap.error("base_url is required unless --check-code is given")

    status = fetch_status(args.base_url, timeout=args.timeout)
    if status is None:
        # The blocking window can swallow /api/status too, so "cannot tell" is
        # its own answer rather than a "no". The caller decides what to do with
        # an unknown; it must never silently read as "a scrape explains this".
        print("scrape-activity: /api/status unreachable or unparseable — cannot tell")
        return 2
    if recovering_scrape(status):
        print(
            "scrape-activity: active scrape "
            f"(step={status.get('current_step')!r}, source={status.get('current_source')!r})"
        )
        return 0
    print(
        "scrape-activity: no active recovering scrape "
        f"(running={status.get('running')!r}, stalled={status.get('stalled')!r}, "
        f"hung={status.get('hung')!r})"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
