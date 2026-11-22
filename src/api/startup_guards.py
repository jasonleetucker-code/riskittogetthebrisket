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

A fourth, advisory decision: ``alert_channel_warnings`` -- owner-alert settings
that are present but unusable (a ``NOTIFY_WEBHOOK_URL`` the one validator
rejects, half-configured e-mail) or, in production, absent altogether.  These
are WARNINGS, never refusals: alerts are optional, and refusing to start would
take the site down to protect a notification channel.
"""

from __future__ import annotations

import argparse
import hmac
import importlib.util
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

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


WEBHOOK_ENV = "NOTIFY_WEBHOOK_URL"
ALERT_EMAIL_SETTINGS = ("ALERT_TO", "ALERT_FROM", "ALERT_PASSWORD")


def _owner_notify() -> ModuleType | None:
    """``src/utils/owner_notify.py`` -- the ONE webhook validator.

    Imported lazily: ``deploy/deploy.sh`` runs THIS file on its own, copied out
    of the target revision, so a top-level import would make that pre-flight
    crash (and refuse the deploy).  Run that way, the validator is loaded from a
    copy beside this file, or -- only when this file sits at ``src/api/`` in a
    checkout -- from ``src/utils/``; otherwise ``None`` and the webhook is simply
    not judged here (never guessed).  No other location is searched: deploy.sh's
    copy lives in a private ``mktemp -d`` directory, and a path derived from it
    (``/tmp/utils/...``) would be world-writable."""
    try:
        from src.utils import owner_notify  # noqa: PLC0415

        return owner_notify
    except ImportError:
        pass
    here = Path(__file__).resolve()
    candidates = [here.with_name("owner_notify.py")]
    if here.parent.name == "api" and here.parents[1].name == "src":
        candidates.append(here.parents[1] / "utils" / "owner_notify.py")
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            spec = importlib.util.spec_from_file_location("_startup_owner_notify", candidate)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        except Exception:  # noqa: BLE001 - advisory check; never break the pre-flight
            continue
    return None


def alert_channel_warnings(environ: Mapping[str, str]) -> list[str]:
    """Owner-alert settings that will not deliver, as warnings.

    Names and reason codes only -- never a value (the webhook URL is a secret).
    Advisory: the server logs these once at startup and the deploy pre-flight
    prints them, but neither refuses on them."""
    warnings: list[str] = []
    notify = _owner_notify()
    webhook_ok = False
    if notify is not None:
        state = notify.validate(environ.get(WEBHOOK_ENV))
        webhook_ok = state == notify.STATE_OK
        if state.startswith(notify.REJECTED_PREFIX):
            reason = state[len(notify.REJECTED_PREFIX) :]
            warnings.append(
                f"{WEBHOOK_ENV} is set but rejected ({reason}); owner push alerts are off "
                "until it is a plain https:// URL"
            )
    email_on = env_truthy(environ, "ALERT_ENABLED")
    values = {name: (environ.get(name) or "").strip() for name in ALERT_EMAIL_SETTINGS}
    if not values["ALERT_PASSWORD"]:
        values["ALERT_PASSWORD"] = (environ.get("GMAIL_APP_PASSWORD") or "").strip()
    missing = [name for name, value in values.items() if not value]
    if email_on and missing:
        warnings.append(
            "ALERT_ENABLED is on but " + ", ".join(missing) + " unset; e-mail alerts are off"
        )
    email_ok = email_on and not missing
    if is_production(environ) and notify is not None and not webhook_ok and not email_ok:
        warnings.append(
            f"no owner alert channel is configured ({WEBHOOK_ENV} or ALERT_*); "
            "production alerts reach no one (docs/ops/OWNER_ALERT_CHANNEL_SETUP_2026-11-19.md)"
        )
    return warnings


def _env_from_file(path: Path, *, production: bool) -> dict[str, str]:
    environ = parse_env_file(path.read_text(encoding="utf-8", errors="replace"))
    if production:
        environ["RISKIT_ENV"] = "production"  # the unit sets it after EnvironmentFile=
    return environ


def check_env_file(path: Path, *, production: bool) -> list[str]:
    """Refusals the server would raise if started with this env file."""
    return startup_refusals(_env_from_file(path, production=production))


def check_env_file_warnings(path: Path, *, production: bool) -> list[str]:
    """Alert-channel warnings the server would log if started with this env file."""
    return alert_channel_warnings(_env_from_file(path, production=production))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check-env-file", required=True, type=Path)
    parser.add_argument("--production", action="store_true")
    args = parser.parse_args(argv)
    try:
        reasons = check_env_file(args.check_env_file, production=args.production)
        warnings = check_env_file_warnings(args.check_env_file, production=args.production)
    except OSError as exc:
        print(f"cannot read env file: {type(exc).__name__}", file=sys.stderr)
        return 2
    for warning in warnings:
        # Advisory: printed, never part of the exit code.
        print(f"startup guard warning: {warning}", file=sys.stderr)
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
