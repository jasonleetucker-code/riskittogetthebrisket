#!/usr/bin/env python3
"""
Trigger a Jenkins build from local sync flow.

Environment variables:
  JENKINS_TRIGGER_URL   Required. Example:
                        https://jenkins.example.com/job/dynasty-app/buildWithParameters
  JENKINS_USER          Optional Jenkins username
  JENKINS_API_TOKEN     Optional Jenkins API token (required if JENKINS_USER is set)
  JENKINS_CRUMB_URL     Optional crumb endpoint override.
                        Defaults to <scheme>://<host>/crumbIssuer/api/json
"""

from __future__ import annotations

import base64
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def _auth_header(user: str | None, token: str | None) -> dict[str, str]:
    if not user or not token:
        return {}
    raw = f"{user}:{token}".encode("utf-8")
    encoded = base64.b64encode(raw).decode("ascii")
    return {"Authorization": f"Basic {encoded}"}


def _default_crumb_url(trigger_url: str) -> str:
    parsed = urlparse(trigger_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid JENKINS_TRIGGER_URL: {trigger_url}")
    return f"{parsed.scheme}://{parsed.netloc}/crumbIssuer/api/json"


def _fetch_crumb(crumb_url: str, headers: dict[str, str]) -> dict[str, str]:
    req = Request(crumb_url, headers=headers, method="GET")
    with urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    field = payload.get("crumbRequestField")
    value = payload.get("crumb")
    if not field or not value:
        return {}
    return {field: value}


def main() -> int:
    trigger_url = (os.getenv("JENKINS_TRIGGER_URL") or "").strip()
    if not trigger_url:
        print("[jenkins] JENKINS_TRIGGER_URL is not set; skipping trigger.")
        return 0

    user = (os.getenv("JENKINS_USER") or "").strip() or None
    token = (os.getenv("JENKINS_API_TOKEN") or "").strip() or None
    headers = _auth_header(user, token)

    # Best effort crumb fetch; if Jenkins does not require crumbs this will still work.
    crumb_url = (os.getenv("JENKINS_CRUMB_URL") or "").strip() or _default_crumb_url(trigger_url)
    try:
        headers.update(_fetch_crumb(crumb_url, headers))
    except Exception as exc:  # noqa: BLE001 - crumb is optional
        print(f"[jenkins] Crumb fetch skipped/failed: {exc}")

    req = Request(trigger_url, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=30) as resp:
            code = getattr(resp, "status", 200)
            print(f"[jenkins] Triggered successfully (HTTP {code}).")
        return 0
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"[jenkins] Trigger failed: HTTP {exc.code}")
        if body:
            print(body[:1000])
        return 1
    except URLError as exc:
        print(f"[jenkins] Trigger failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
