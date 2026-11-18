"""Fail-closed startup / auth-comparison guards (audit Task 13).

Owner of three small, pure decisions ``server.py`` consumes:

* ``is_placeholder_password`` -- the example/placeholder credentials that
  must never authenticate a real deployment (``.env.example`` ships
  ``changeme``).  Only the explicit local-dev escape hatch
  ``ALLOW_DEFAULT_LOGIN_DEV`` may use one.
* ``production_env_violations`` -- test/dev switches that must be off when
  the process is marked production (``RISKIT_ENV=production``, set by the
  systemd unit AFTER ``EnvironmentFile=`` so ``.env`` cannot unset it).
* ``constant_time_equals`` -- ``hmac.compare_digest`` over BYTES, so a
  non-ASCII header value cannot raise ``TypeError`` (-> HTTP 500).

Nothing here logs or returns a secret value; violations name variables only.
"""

from __future__ import annotations

import hmac
from collections.abc import Mapping

PLACEHOLDER_PASSWORDS = frozenset(
    {
        "",
        "changeme",
        "change-me",
        "changeit",
        "password",
        "passw0rd",
        "admin",
        "secret",
        "example",
        "your-password",
        "your_password",
        "yourpassword",
        "replace-me",
        "replaceme",
        "replace-with-a-real-password-before-first-run",
        "test",
        "12345678",
    }
)

_TRUTHY = {"1", "true", "yes", "on"}
PRODUCTION_FORBIDDEN_FLAGS = ("E2E_TEST_MODE", "ALLOW_DEFAULT_LOGIN_DEV")


def is_placeholder_password(value: str | None) -> bool:
    return (value or "").strip().lower() in PLACEHOLDER_PASSWORDS


def is_production(environ: Mapping[str, str]) -> bool:
    return (environ.get("RISKIT_ENV") or "").strip().lower() in {"production", "prod"}


def production_env_violations(environ: Mapping[str, str]) -> list[str]:
    """Names (never values) of forbidden switches enabled in a production env."""
    if not is_production(environ):
        return []
    return [
        name
        for name in PRODUCTION_FORBIDDEN_FLAGS
        if (environ.get(name) or "").strip().lower() in _TRUTHY
    ]


def constant_time_equals(presented: str, configured: str) -> bool:
    """Constant-time equality that is safe for any ``str`` input."""
    return hmac.compare_digest(
        (presented or "").encode("utf-8", "surrogateescape"),
        (configured or "").encode("utf-8", "surrogateescape"),
    )
