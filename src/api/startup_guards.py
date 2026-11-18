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

import argparse
import hmac
import sys
from collections.abc import Mapping
from pathlib import Path

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


def env_truthy(environ: Mapping[str, str], name: str) -> bool:
    """Same truthiness ``server._env_bool`` applies (``_TRUTHY``)."""
    return (environ.get(name) or "").strip().lower() in _TRUTHY


def startup_refusals(environ: Mapping[str, str]) -> list[str]:
    """The ONE startup rule set (audit Task 13); ``server.py`` and the deploy
    pre-flight both call this so they cannot drift.

    Returns human-readable refusal reasons naming variables only, never values.
    """
    reasons: list[str] = []
    bad = production_env_violations(environ)
    if bad:
        reasons.append("RISKIT_ENV=production but test/dev switches are enabled: " + ", ".join(bad))
    password = (environ.get("JASON_LOGIN_PASSWORD") or "").strip()
    dev_hatch = env_truthy(environ, "ALLOW_DEFAULT_LOGIN_DEV")
    if not password:
        if not dev_hatch:
            reasons.append("JASON_LOGIN_PASSWORD is unset/empty and ALLOW_DEFAULT_LOGIN_DEV is off")
    elif is_placeholder_password(password) and not dev_hatch:
        reasons.append("JASON_LOGIN_PASSWORD is a known placeholder/example value")
    return reasons


def parse_env_file(text: str) -> dict[str, str]:
    """Parse like systemd ``EnvironmentFile=``: blank lines and ``#``/``;``
    comments ignored, one optional pair of matching quotes stripped, last
    assignment wins.  A leading ``export`` is treated as absent (safe superset).
    """
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        if line.startswith("export") and line[6:7] in (" ", "\t"):
            line = line[6:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def check_env_file(path: Path, *, production: bool) -> list[str]:
    """Refusals the server would raise if started with this env file."""
    environ = parse_env_file(path.read_text(encoding="utf-8", errors="replace"))
    if production:
        environ["RISKIT_ENV"] = "production"  # the unit sets it after EnvironmentFile=
    return startup_refusals(environ)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check-env-file", required=True, type=Path)
    parser.add_argument("--production", action="store_true")
    args = parser.parse_args(argv)
    try:
        reasons = check_env_file(args.check_env_file, production=args.production)
    except OSError as exc:
        print(f"cannot read env file: {type(exc).__name__}", file=sys.stderr)
        return 2
    for reason in reasons:
        print(f"startup guard would refuse: {reason}", file=sys.stderr)
    return 1 if reasons else 0


def constant_time_equals(presented: str, configured: str) -> bool:
    """Constant-time equality that is safe for any ``str`` input.

    An empty/unset ``configured`` secret never matches (even an empty
    ``presented``): unset must not authorize.
    """
    if not (configured or ""):
        return False
    return hmac.compare_digest(
        (presented or "").encode("utf-8", "surrogateescape"),
        (configured or "").encode("utf-8", "surrogateescape"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
