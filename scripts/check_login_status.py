#!/usr/bin/env python3
"""Test one login credential against a site and print ONLY the HTTP status.

For the ``JASON_LOGIN_PASSWORD`` rotation (docs/ops/CREDENTIAL_INVENTORY_2026-11-19.md
section 4): prove the NEW value logs in and the OLD value is refused without ever
displaying either.  Stdlib only.

The password is never accepted as an argument (it would land in shell history and
the process list).  It comes from the environment variable named by
``--password-env`` (default ``CHECK_LOGIN_PASSWORD``) or, when that is unset, from a
hidden ``getpass`` prompt.  The username comes from ``--username`` or
``JASON_LOGIN_USERNAME``.  Output is exactly one line::

    login HTTP <status> (<label>)

and the exit code says whether that matched ``--expect``:

    0  matched (ok -> 200, refused -> 401)
    1  did not match, or the site answered something else (429 throttled, 5xx, ...)
    2  usage / could not reach the site

A refused attempt counts toward the login throttle (src/api/rate_limit.py); one
check per credential is fine, do not loop it.  A successful login mints a normal
session; nothing is changed on the server.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

EXPECT_STATUS = {"ok": 200, "refused": 401}
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def url_is_safe(url: str) -> bool:
    """https anywhere, or http only to an exact loopback host; never userinfo."""
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
        parts.port  # noqa: B018 (raises ValueError on a malformed port)
    except ValueError:
        return False
    if not host or parts.username is not None or parts.password is not None or "@" in parts.netloc:
        return False
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and host in _LOOPBACK_HOSTS


def attempt_login(url: str, username: str, password: str, timeout: float = 15.0) -> int:
    """POST the credential; return the HTTP status (never the body)."""
    body = json.dumps({"username": username, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        url.rstrip("/") + "/api/auth/login",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (operator-given URL)
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def main(
    argv: list[str] | None = None,
    env: dict[str, str] | None = None,
    prompt: Callable[[str], str] = getpass.getpass,
    login: Callable[[str, str, str], int] = attempt_login,
) -> int:
    env = dict(os.environ) if env is None else env
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", required=True, help="site origin, e.g. https://example.com")
    ap.add_argument("--username", default=env.get("JASON_LOGIN_USERNAME", ""))
    ap.add_argument("--password-env", default="CHECK_LOGIN_PASSWORD")
    ap.add_argument("--expect", choices=sorted(EXPECT_STATUS), required=True)
    ap.add_argument("--label", default="credential")
    args = ap.parse_args(argv)
    if not url_is_safe(args.url):
        print("refusing: --url must be https (or loopback http)", file=sys.stderr)
        return 2
    if not args.username:
        print("no username: pass --username or set JASON_LOGIN_USERNAME", file=sys.stderr)
        return 2
    password = env.get(args.password_env) or prompt("password (hidden): ")
    if not password:
        print("empty password", file=sys.stderr)
        return 2
    try:
        status = login(args.url, args.username, password)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"could not reach the site ({type(exc).__name__})", file=sys.stderr)
        return 2
    print(f"login HTTP {status} ({args.label})")
    return 0 if status == EXPECT_STATUS[args.expect] else 1


if __name__ == "__main__":
    sys.exit(main())
