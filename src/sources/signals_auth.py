"""Signals account session: store, renewal, failure classes.  ONE owner.

Signals (signalsfantasy.com) signs users in with an emailed one-time code —
there is no password to store.  The owner signs in ONCE, in a dedicated
browser window (``scripts/signals_connect.py connect``); this module keeps the
resulting Cognito session alive for unattended collection and says, truthfully,
when it can no longer do so.  Full record:
``docs/sources/SIGNALS_ACCOUNT_CONNECTION.md``.

What was OBSERVED in the shipped web app (2026-10-01, bundle
``index-D9PR2evB.js`` on ``webapp.signalsfantasy.com``) and what is NOT known
until a real session is observed is recorded in that document.  This module
only depends on the observed mechanism:

* AWS Cognito via Amplify JS v6; sign-in is ``USER_AUTH`` + ``EMAIL_OTP``.
* Tokens live in ``window.localStorage`` under
  ``CognitoIdentityServiceProvider.<clientId>.<username>.*``.
* The site renews with ``GetTokensFromRefreshToken`` (``ClientId``,
  ``RefreshToken``, optional ``DeviceKey``) and adopts a NEW refresh token
  whenever the response carries one.  That is exactly what :func:`renew` does,
  so a pool with refresh-token rotation enabled is handled — and a pool without
  it is too.

Invariants (each pinned by ``tests/sources/test_signals_auth.py``):

* **Secrets never leave the store.**  :func:`status` and every exception
  message carry expiry times, states and a non-reversible 8-hex fingerprint —
  never a token value.  The refresh token is only ever sent to
  ``https://cognito-idp.<region>.amazonaws.com/``, with the region read from
  the token's own ``iss`` claim and validated (no configurable endpoint in
  production; tests inject one as a parameter).
* **The store is outside every checkout and web root**, 0700 directory,
  0600 files, written temp + fsync + ``os.replace``.
* **One renewal owner.**  Renewal runs under an exclusive file lock and
  re-reads the session under that lock, so two workers can never both spend
  the same refresh token and a rotated token can never be overwritten by a
  stale one.  If another process already renewed, its result is used.
* **Renew before expiry** (``skew_seconds``).  An expired ACCESS token is a
  reason to renew, never a reason to stop.
* **Failure classes are distinct.**  A revoked/expired refresh credential is
  ``reconnect_required`` — collection stops, no retry loop, no login email is
  ever triggered from code, and ONE notice per failure episode is queued.
  Network/5xx/throttling is ``transient`` — bounded retries, never a lock-out.
  A data-request 403 is not assumed to be expiry: see
  :func:`classify_data_response`.
* **Missing is not healthy.**  No store → ``not_connected``.  Refresh-token
  lifetime is not observable client-side (Cognito refresh tokens are opaque),
  so it is reported as unknown, never guessed.

Vocabulary reuse: :func:`acquisition_state_for` maps the failure classes onto
``src.sources.acquisition_state`` (``AUTH_REQUIRED`` / ``UNAVAILABLE``) so a
collector reports through the one existing acquisition vocabulary.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.sources.acquisition_state import AUTH_REQUIRED, HEALTHY, UNAVAILABLE

__all__ = [
    "ACCESS_DENIED",
    "AUTH_DIR_ENV",
    "DATA_OK",
    "DATA_RENEW_AND_RETRY",
    "RECONNECT_REQUIRED",
    "REFRESH_REFUSED",
    "SignalsAuthError",
    "SignalsStore",
    "StorePathError",
    "TRANSIENT",
    "acquisition_state_for",
    "classify_data_response",
    "deliver_reconnect_notice",
    "get_access_token",
    "import_session",
    "renew",
    "resolve_store_dir",
    "status",
]

# ── Observed web-app facts (2026-10-01; see the connection doc §2) ──────────

#: Where the owner signs in.  The login form is served at the app root.
WEBAPP_ORIGIN = "https://webapp.signalsfantasy.com"
#: Shipped Amplify outputs.  Used to VALIDATE a capture, never to mint tokens.
EXPECTED_REGION = "us-east-2"
EXPECTED_USER_POOL_ID = "us-east-2_Zqml90OCW"
EXPECTED_CLIENT_ID = "7ud6sc23s8g3td1h5bfho9mua4"
#: Amplify's localStorage key prefix.
AMPLIFY_KEY_PREFIX = "CognitoIdentityServiceProvider"

SCHEMA_VERSION = 1
AUTH_DIR_ENV = "RISKIT_SIGNALS_AUTH_DIR"
SESSION_FILE = "signals_session.json"  # matches the repo's *_session.json ignore
STATUS_FILE = "signals_auth_status.json"
LOCK_FILE = ".signals_auth.lock"

DEFAULT_SKEW_SECONDS = 300
DEFAULT_LOCK_TIMEOUT_SECONDS = 60.0
HTTP_TIMEOUT_SECONDS = 15.0
#: Bounded transient retries per renewal (never a loop).
TRANSIENT_ATTEMPTS = 3
TRANSIENT_BACKOFF_SECONDS = (1.0, 3.0)
MAX_RETRY_AFTER_SECONDS = 30.0
#: Indirection so tests can skip real backoff without patching time.sleep.
_backoff_sleep = time.sleep

# ── Failure classes ─────────────────────────────────────────────────────────

#: The refresh credential is revoked/expired/invalid, or a new email-code
#: sign-in would be required.  Owner action: ``signals_connect.py reconnect``.
RECONNECT_REQUIRED = "reconnect_required"
#: Network error, 5xx, throttling.  Retried within a bound; never a lock-out.
TRANSIENT = "transient"
#: A data request was refused with a token Cognito just (re)issued — not
#: expiry.  Entitlement/subscription or provider-side access control.
ACCESS_DENIED = "access_denied"
#: Cognito refused the renewal for a reason that is neither credential death
#: nor transient (bad parameter, unknown client, WAF).  Retrying will not help;
#: reconnecting may not either.  Stops and notifies with the provider's type.
REFRESH_REFUSED = "refresh_refused"

#: Classes that stop authenticated collection and open a notice episode.
STOPPING_CLASSES = frozenset({RECONNECT_REQUIRED, ACCESS_DENIED, REFRESH_REFUSED})

#: Data-response verdicts (:func:`classify_data_response`).
DATA_OK = "ok"
DATA_RENEW_AND_RETRY = "renew_and_retry"

#: Auth-health states published by :func:`status`.
STATE_NOT_CONNECTED = "not_connected"
STATE_HEALTHY = "healthy"
STATE_RENEWAL_DUE = "renewal_due"
STATE_TRANSIENT_FAILURE = "transient_failure"

#: Cognito error ``__type`` → (class, reason).  Anything absent is
#: REFRESH_REFUSED for a 4xx and TRANSIENT for a 5xx.
_COGNITO_ERRORS: dict[str, tuple[str, str]] = {
    "NotAuthorizedException": (RECONNECT_REQUIRED, "refresh_token_not_authorized"),
    "RefreshTokenReuseException": (RECONNECT_REQUIRED, "refresh_token_reused"),
    "UserNotFoundException": (RECONNECT_REQUIRED, "user_not_found"),
    "UserNotConfirmedException": (RECONNECT_REQUIRED, "user_not_confirmed"),
    "PasswordResetRequiredException": (RECONNECT_REQUIRED, "reset_required"),
    "TooManyRequestsException": (TRANSIENT, "throttled"),
    "LimitExceededException": (TRANSIENT, "throttled"),
    "InternalErrorException": (TRANSIENT, "provider_internal_error"),
    "ServiceUnavailableException": (TRANSIENT, "provider_unavailable"),
    "InvalidParameterException": (REFRESH_REFUSED, "invalid_parameter"),
    "ResourceNotFoundException": (REFRESH_REFUSED, "client_or_pool_not_found"),
    "ForbiddenException": (REFRESH_REFUSED, "forbidden_by_provider"),
    "InvalidLambdaResponseException": (REFRESH_REFUSED, "provider_trigger_error"),
    "UnexpectedLambdaException": (REFRESH_REFUSED, "provider_trigger_error"),
    "UserLambdaValidationException": (REFRESH_REFUSED, "provider_trigger_error"),
}

_REGION_RE = re.compile(r"^[a-z]{2}(?:-gov)?-[a-z]+-\d$")
_ISS_RE = re.compile(
    r"^https://cognito-idp\.([a-z0-9-]+)\.amazonaws\.com/([A-Za-z0-9-]+_[A-Za-z0-9]+)$"
)


class SignalsAuthError(RuntimeError):
    """A classified authentication failure.  Messages never contain secrets."""

    def __init__(self, failure_class: str, reason: str, detail: str = "") -> None:
        self.failure_class = failure_class
        self.reason = reason
        self.detail = detail
        super().__init__(f"{failure_class}: {reason}" + (f" ({detail})" if detail else ""))


class StorePathError(ValueError):
    """The configured store location is unsafe (inside a checkout or web root)."""


def acquisition_state_for(failure_class: str | None) -> str:
    """Map an auth failure class onto the ONE acquisition vocabulary."""
    if failure_class is None:
        return HEALTHY
    if failure_class == TRANSIENT:
        return UNAVAILABLE
    return AUTH_REQUIRED


def classify_data_response(status_code: int, *, renewal_attempted: bool) -> str:
    """Verdict for an authenticated DATA request (AppSync / page fetch).

    A 401/403 is NOT automatically expiry.  The caller renews at most once
    (``renew_and_retry``); a refusal that survives a fresh renewal is
    ``access_denied`` — entitlement or provider access control, which a new
    token cannot fix and which must not trigger a re-login loop.
    """
    if 200 <= status_code < 300:
        return DATA_OK
    if status_code in (401, 403):
        return ACCESS_DENIED if renewal_attempted else DATA_RENEW_AND_RETRY
    if status_code == 429 or status_code >= 500:
        return TRANSIENT
    return ACCESS_DENIED if status_code in (402, 451) else TRANSIENT


# ── Small primitives ────────────────────────────────────────────────────────


def _utc_iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def fingerprint(secret: str | None) -> str | None:
    """Non-reversible 8-hex tag, for telling tokens apart in status/logs."""
    if not secret:
        return None
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:8]


def jwt_claims(token: str | None) -> dict[str, Any]:
    """Decode a JWT payload WITHOUT verifying it.  Read for expiry/routing only.

    Signature verification is Cognito's job on every use; this module only
    needs ``exp`` (when to renew) and ``iss`` (where the refresh goes).
    """
    if not token or token.count(".") != 2:
        return {}
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except (ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def cognito_endpoint_for(access_token: str) -> tuple[str, str, str]:
    """``(endpoint, region, userPoolId)`` from the token's own ``iss``.

    Validated so a malformed or hostile token cannot route the refresh token
    anywhere but AWS Cognito.
    """
    iss = str(jwt_claims(access_token).get("iss") or "")
    m = _ISS_RE.match(iss)
    if not m or not _REGION_RE.match(m.group(1)) or not m.group(2).startswith(m.group(1) + "_"):
        raise SignalsAuthError(RECONNECT_REQUIRED, "unrecognized_token_issuer")
    region = m.group(1)
    return f"https://cognito-idp.{region}.amazonaws.com/", region, m.group(2)


# ── Store location ──────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WEB_ROOTS = (Path("/var/www"), Path("/usr/share/nginx"), Path("/srv/www"), Path("/srv/http"))


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _inside_git_checkout(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def validate_store_dir(path: Path, *, repo_root: Path = _REPO_ROOT) -> Path:
    """Refuse any location inside a checkout or a public web root."""
    resolved = Path(os.path.abspath(os.path.expanduser(str(path))))
    with contextlib.suppress(OSError):
        resolved = resolved.resolve()
    repo = repo_root.resolve()
    if _is_within(resolved, repo):
        raise StorePathError(f"refusing a Signals session store inside the repository ({repo})")
    for web in _WEB_ROOTS:
        if _is_within(resolved, web):
            raise StorePathError(f"refusing a Signals session store inside a web root ({web})")
    checkout = _inside_git_checkout(resolved)
    if checkout is not None:
        raise StorePathError(f"refusing a Signals session store inside a git checkout ({checkout})")
    return resolved


def default_store_dir() -> Path:
    """Per-OS default, always outside the checkout.

    * Linux (the prod box): ``/var/lib/signals-auth`` when it exists
      (provisioning creates it 0700, owned by the app user), else
      ``$XDG_STATE_HOME/riskit/signals-auth`` (``~/.local/state/...``).
    * Windows: ``%LOCALAPPDATA%\\riskit\\signals-auth`` (per-user ACL).
    * macOS: ``~/Library/Application Support/riskit/signals-auth``.
    """
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "riskit" / "signals-auth"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "riskit" / "signals-auth"
    system = Path("/var/lib/signals-auth")
    if system.is_dir():
        return system
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state) / "riskit" / "signals-auth"


def resolve_store_dir(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Explicit argument → ``$RISKIT_SIGNALS_AUTH_DIR`` → per-OS default."""
    raw = explicit or os.environ.get(AUTH_DIR_ENV) or default_store_dir()
    return validate_store_dir(Path(raw))


# ── Store ───────────────────────────────────────────────────────────────────


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "posix":
        return  # Windows: %LOCALAPPDATA% is already per-user by ACL.
    st = path.stat()
    if st.st_uid != os.getuid():
        raise StorePathError(f"session store {path} is owned by uid {st.st_uid}, not this user")
    if st.st_mode & 0o077:
        os.chmod(path, 0o700)


def _replace_with_retry(src: Path, dst: Path) -> None:
    """``os.replace``; on Windows a concurrent reader can hold ``dst`` open for
    a moment (no FILE_SHARE_DELETE), so retry briefly.  POSIX never retries."""
    for attempt in range(40):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if os.name == "posix" or attempt == 39:
                raise
            time.sleep(0.025)


def _atomic_write_json(path: Path, obj: dict[str, Any]) -> None:
    """temp file (0600, O_EXCL) → fsync → os.replace → fsync directory."""
    data = (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode("utf-8")
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if os.name == "posix":
            os.chmod(tmp, 0o600)
        _replace_with_retry(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    if os.name == "posix":
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


def _read_json(path: Path) -> dict[str, Any] | None:
    for attempt in range(40):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            break
        except FileNotFoundError:
            return None
        except PermissionError as exc:  # Windows: mid-replace by another process
            if os.name == "posix" or attempt == 39:
                raise SignalsAuthError(
                    RECONNECT_REQUIRED, "session_store_unreadable", type(exc).__name__
                ) from None
            time.sleep(0.025)
        except (OSError, ValueError) as exc:
            raise SignalsAuthError(
                RECONNECT_REQUIRED, "session_store_unreadable", type(exc).__name__
            ) from None
    return data if isinstance(data, dict) else None


@contextlib.contextmanager
def _exclusive_lock(path: Path, timeout: float) -> Iterator[None]:
    """Cross-process exclusive lock on ``path`` (flock / msvcrt), polled."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                if os.name == "posix":
                    import fcntl  # noqa: PLC0415

                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    import msvcrt  # noqa: PLC0415

                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise SignalsAuthError(TRANSIENT, "renewal_lock_timeout") from None
                time.sleep(0.05)
        try:
            yield
        finally:
            if os.name == "posix":
                import fcntl  # noqa: PLC0415

                fcntl.flock(fd, fcntl.LOCK_UN)
            else:
                import msvcrt  # noqa: PLC0415

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    finally:
        os.close(fd)


@dataclass(frozen=True)
class SignalsStore:
    root: Path

    @classmethod
    def open(cls, explicit: str | os.PathLike[str] | None = None) -> SignalsStore:
        return cls(resolve_store_dir(explicit))

    @property
    def session_path(self) -> Path:
        return self.root / SESSION_FILE

    @property
    def status_path(self) -> Path:
        return self.root / STATUS_FILE

    def lock(
        self, timeout: float = DEFAULT_LOCK_TIMEOUT_SECONDS
    ) -> contextlib.AbstractContextManager:
        _ensure_private_dir(self.root)
        return _exclusive_lock(self.root / LOCK_FILE, timeout)

    def read_session(self) -> dict[str, Any] | None:
        return _read_json(self.session_path)

    def write_session(self, session: dict[str, Any]) -> None:
        _ensure_private_dir(self.root)
        _atomic_write_json(self.session_path, session)

    def delete_session(self) -> bool:
        try:
            self.session_path.unlink()
            return True
        except FileNotFoundError:
            return False

    def read_status(self) -> dict[str, Any]:
        try:
            return _read_json(self.status_path) or {}
        except SignalsAuthError:
            return {}

    def write_status(self, data: dict[str, Any]) -> None:
        _ensure_private_dir(self.root)
        _atomic_write_json(self.status_path, data)


# ── Session shape ───────────────────────────────────────────────────────────

_DEVICE_KEYS = ("deviceKey", "deviceGroupKey", "randomPasswordKey")


def build_session(captured: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    """Validate a raw Amplify capture and build the stored session.

    ``captured`` is ``{"clientId", "username", "accessToken", "idToken",
    "refreshToken", "deviceKey"?, "deviceGroupKey"?, "randomPasswordKey"?,
    "clockDrift"?}`` — exactly what ``signals_connect.py`` extracts from the
    Signals origin's localStorage, nothing else.
    """
    now = time.time() if now is None else now
    refresh = captured.get("refreshToken")
    access = captured.get("accessToken")
    client_id = captured.get("clientId")
    if not refresh or not isinstance(refresh, str):
        raise SignalsAuthError(RECONNECT_REQUIRED, "capture_missing_refresh_token")
    if not access or not isinstance(access, str):
        raise SignalsAuthError(RECONNECT_REQUIRED, "capture_missing_access_token")
    claims = jwt_claims(access)
    if claims.get("token_use") != "access":
        raise SignalsAuthError(RECONNECT_REQUIRED, "capture_access_token_malformed")
    if client_id and claims.get("client_id") and claims["client_id"] != client_id:
        raise SignalsAuthError(RECONNECT_REQUIRED, "capture_client_mismatch")
    _endpoint, region, pool = cognito_endpoint_for(access)
    device = {k: captured[k] for k in _DEVICE_KEYS if captured.get(k)}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "provider": "aws-cognito",
        "origin": WEBAPP_ORIGIN,
        "region": region,
        "userPoolId": pool,
        "clientId": client_id or claims.get("client_id"),
        "username": captured.get("username"),
        "tokens": {
            "accessToken": access,
            "idToken": captured.get("idToken"),
            "refreshToken": refresh,
        },
        "device": device or None,
        "capturedAt": _utc_iso(now),
        "lastRenewedAt": None,
        "renewCount": 0,
        "refreshTokenRotations": 0,
    }


def _token_exp(session: dict[str, Any], name: str) -> float | None:
    exp = jwt_claims((session.get("tokens") or {}).get(name)).get("exp")
    return float(exp) if isinstance(exp, (int, float)) else None


def _access_token_fresh(session: dict[str, Any], *, now: float, skew: float) -> bool:
    exp = _token_exp(session, "accessToken")
    return exp is not None and exp - skew > now


# ── Status / episodes ───────────────────────────────────────────────────────


def _episode_id(failure_class: str, started_at: float) -> str:
    return hashlib.sha256(f"{failure_class}:{started_at:.3f}".encode()).hexdigest()[:12]


def record_failure(
    store: SignalsStore, failure_class: str, reason: str, *, now: float | None = None
) -> dict[str, Any]:
    """Record a classified failure; open ONE notice episode for stopping classes.

    A second failure of the same class while an episode is open does not open
    another — that is the deduplication.  Transient failures never open one.
    Takes no lock itself (``renew`` calls it while holding the store lock); a
    collector recording e.g. ``access_denied`` should wrap it in
    ``store.lock()`` so status writes do not race.
    """
    now = time.time() if now is None else now
    st = store.read_status()
    st["lastAttemptAt"] = _utc_iso(now)
    st["lastFailure"] = {"class": failure_class, "reason": reason, "at": _utc_iso(now)}
    if failure_class == TRANSIENT:
        st["consecutiveTransientFailures"] = int(st.get("consecutiveTransientFailures") or 0) + 1
        if st.get("state") not in STOPPING_CLASSES:
            st["state"] = STATE_TRANSIENT_FAILURE
    else:
        st["state"] = failure_class
        episode = st.get("episode")
        if not episode or episode.get("failureClass") != failure_class:
            st["episode"] = {
                "id": _episode_id(failure_class, now),
                "failureClass": failure_class,
                "reason": reason,
                "startedAt": _utc_iso(now),
                "noticeDeliveredAt": None,
                "noticeAttempts": 0,
            }
    store.write_status(st)
    return st


def _record_success(store: SignalsStore, *, now: float, event: str) -> None:
    st = store.read_status()
    episode = st.pop("episode", None)
    if episode:
        episode["resolvedAt"] = _utc_iso(now)
        st["lastResolvedEpisode"] = episode
    st.update(
        {
            "state": STATE_HEALTHY,
            "lastAttemptAt": _utc_iso(now),
            "lastSuccessAt": _utc_iso(now),
            "lastSuccessEvent": event,
            "consecutiveTransientFailures": 0,
        }
    )
    st.pop("lastFailure", None)
    store.write_status(st)


def status(store: SignalsStore, *, now: float | None = None) -> dict[str, Any]:
    """Redacted AUTHENTICATION health.  Never contains a token value.

    Source-data freshness is a different question owned by the collector's
    store; ``scripts/signals_connect.py status`` reads it separately.
    """
    now = time.time() if now is None else now
    st = store.read_status()
    try:
        session = store.read_session()
    except SignalsAuthError as exc:
        return {"state": RECONNECT_REQUIRED, "reason": exc.reason, "storeDir": str(store.root)}
    if session is None:
        return {
            "state": STATE_NOT_CONNECTED,
            "storeDir": str(store.root),
            "lastResolvedEpisode": st.get("lastResolvedEpisode"),
        }
    tokens = session.get("tokens") or {}
    access_exp = _token_exp(session, "accessToken")
    id_exp = _token_exp(session, "idToken")
    state = st.get("state") or STATE_HEALTHY
    if state == STATE_HEALTHY and (access_exp is None or access_exp <= now):
        state = STATE_RENEWAL_DUE  # normal between renewals, not a failure
    if state == STATE_TRANSIENT_FAILURE:
        acquisition = UNAVAILABLE
    else:
        acquisition = acquisition_state_for(state if state in STOPPING_CLASSES else None)
    return {
        "state": state,
        "acquisitionState": acquisition,
        "storeDir": str(store.root),
        "provider": session.get("provider"),
        "region": session.get("region"),
        "userPoolId": session.get("userPoolId"),
        "clientIdMatchesShippedConfig": session.get("clientId") == EXPECTED_CLIENT_ID,
        "capturedAt": session.get("capturedAt"),
        "lastRenewedAt": session.get("lastRenewedAt"),
        "renewCount": session.get("renewCount", 0),
        "refreshTokenRotationsObserved": session.get("refreshTokenRotations", 0),
        "refreshTokenRotationEvidence": (
            "unobserved (no renewal yet)"
            if not session.get("renewCount")
            else ("rotating" if session.get("refreshTokenRotations") else "not rotating")
        ),
        "accessTokenExpiresAt": _utc_iso(access_exp),
        "idTokenExpiresAt": _utc_iso(id_exp),
        "refreshTokenExpiresAt": None,
        "refreshTokenExpiry": "not observable client-side (opaque Cognito refresh token)",
        "refreshTokenFingerprint": fingerprint(tokens.get("refreshToken")),
        "deviceKeyPresent": bool((session.get("device") or {}).get("deviceKey")),
        "lastAttemptAt": st.get("lastAttemptAt"),
        "lastSuccessAt": st.get("lastSuccessAt"),
        "lastFailure": st.get("lastFailure"),
        "consecutiveTransientFailures": st.get("consecutiveTransientFailures", 0),
        "episode": st.get("episode"),
    }


# ── Cognito transport ───────────────────────────────────────────────────────

Transport = Callable[[str, str, dict[str, Any], float], tuple[int, dict[str, Any], dict[str, str]]]


def _urllib_transport(
    endpoint: str, target: str, body: dict[str, Any], timeout: float
) -> tuple[int, dict[str, Any], dict[str, str]]:
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/x-amz-json-1.1",
            "X-Amz-Target": f"AWSCognitoIdentityProviderService.{target}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - validated endpoint
            raw = resp.read()
            code, headers = resp.status, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        raw, code, headers = exc.read(), exc.code, dict(exc.headers or {})
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except (ValueError, UnicodeDecodeError):
        payload = {}
    return code, payload if isinstance(payload, dict) else {}, headers


def _classify_cognito(code: int, payload: dict[str, Any]) -> tuple[str, str]:
    err_type = str(payload.get("__type") or payload.get("code") or "").rsplit("#", 1)[-1]
    if err_type == "NotAuthorizedException":
        # Provider message text, e.g. "Refresh Token has been revoked".  It
        # never echoes the token, so refining the reason from it is safe.
        msg = str(payload.get("message") or "").lower()
        for needle, reason in (
            ("revoked", "refresh_token_revoked"),
            ("expired", "refresh_token_expired"),
            ("invalid refresh token", "refresh_token_invalid"),
        ):
            if needle in msg:
                return RECONNECT_REQUIRED, reason
    if err_type in _COGNITO_ERRORS:
        return _COGNITO_ERRORS[err_type]
    if code == 429 or code >= 500:
        return TRANSIENT, f"http_{code}"
    return REFRESH_REFUSED, err_type or f"http_{code}"


def _call_refresh(
    session: dict[str, Any], *, transport: Transport, endpoint: str | None
) -> dict[str, Any]:
    """One bounded renewal: up to TRANSIENT_ATTEMPTS tries for transient errors only."""
    tokens = session.get("tokens") or {}
    real_endpoint, _region, _pool = cognito_endpoint_for(tokens.get("accessToken") or "")
    url = endpoint or real_endpoint
    body: dict[str, Any] = {
        "ClientId": session.get("clientId"),
        "RefreshToken": tokens.get("refreshToken"),
    }
    device_key = (session.get("device") or {}).get("deviceKey")
    if device_key:
        body["DeviceKey"] = device_key
    last: tuple[str, str] = (TRANSIENT, "unknown")
    for attempt in range(TRANSIENT_ATTEMPTS):
        try:
            code, payload, headers = transport(
                url, "GetTokensFromRefreshToken", body, HTTP_TIMEOUT_SECONDS
            )
        except (OSError, urllib.error.URLError) as exc:
            last = (TRANSIENT, f"network_{type(exc).__name__}")
            code, payload, headers = 0, {}, {}
        else:
            if code == 200:
                result = payload.get("AuthenticationResult") or {}
                if not result.get("AccessToken"):
                    raise SignalsAuthError(RECONNECT_REQUIRED, "no_authentication_result")
                return result
            last = _classify_cognito(code, payload)
            if last[0] != TRANSIENT:
                raise SignalsAuthError(*last)
        if attempt + 1 < TRANSIENT_ATTEMPTS:
            delay = TRANSIENT_BACKOFF_SECONDS[min(attempt, len(TRANSIENT_BACKOFF_SECONDS) - 1)]
            retry_after = headers.get("Retry-After") if headers else None
            if retry_after and retry_after.isdigit():
                delay = min(float(retry_after), MAX_RETRY_AFTER_SECONDS)
            _backoff_sleep(delay)
    raise SignalsAuthError(*last)


def _apply_refresh(
    session: dict[str, Any], result: dict[str, Any], *, now: float
) -> dict[str, Any]:
    new = json.loads(json.dumps(session))
    tokens = new.setdefault("tokens", {})
    tokens["accessToken"] = result["AccessToken"]
    if result.get("IdToken"):
        tokens["idToken"] = result["IdToken"]
    rotated = result.get("RefreshToken")
    if rotated and rotated != tokens.get("refreshToken"):
        tokens["refreshToken"] = rotated
        new["refreshTokenRotations"] = int(new.get("refreshTokenRotations") or 0) + 1
    new["lastRenewedAt"] = _utc_iso(now)
    new["renewCount"] = int(new.get("renewCount") or 0) + 1
    return new


# ── Public operations ───────────────────────────────────────────────────────


def renew(
    store: SignalsStore,
    *,
    force: bool = False,
    skew_seconds: float = DEFAULT_SKEW_SECONDS,
    transport: Transport | None = None,
    endpoint: str | None = None,
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
    now_fn: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Renew under the lock if due (or ``force``).  Returns the session.

    Short-circuits WITHOUT a network call while a stopping episode is open —
    a dead refresh token is not retried in a loop, and nothing here can send a
    login email.  ``force`` makes exactly one deliberate attempt.
    """
    transport = transport or _urllib_transport
    with store.lock(lock_timeout):
        session = store.read_session()
        if session is None:
            raise SignalsAuthError(RECONNECT_REQUIRED, "not_connected")
        st = store.read_status()
        if not force and st.get("state") in STOPPING_CLASSES:
            episode = st.get("episode") or {}
            raise SignalsAuthError(
                st["state"], str(episode.get("reason") or "episode_open"), "stopped; owner action"
            )
        now = now_fn()
        if not force and _access_token_fresh(session, now=now, skew=skew_seconds):
            return session  # another worker already renewed, or not yet due
        try:
            result = _call_refresh(session, transport=transport, endpoint=endpoint)
        except SignalsAuthError as exc:
            record_failure(store, exc.failure_class, exc.reason, now=now_fn())
            if exc.failure_class == TRANSIENT and _access_token_fresh(
                session, now=now_fn(), skew=0
            ):
                return session  # early renewal failed; the current token still works
            raise
        renewed = _apply_refresh(session, result, now=now_fn())
        store.write_session(renewed)
        _record_success(store, now=now_fn(), event="renewed")
        return renewed


def get_access_token(
    store: SignalsStore,
    *,
    token: str = "accessToken",
    skew_seconds: float = DEFAULT_SKEW_SECONDS,
    transport: Transport | None = None,
    endpoint: str | None = None,
    now_fn: Callable[[], float] = time.time,
) -> str:
    """A currently valid token for an authenticated request.

    Fast path reads without the lock; renewal always takes it.  ``token`` may
    be ``"idToken"`` for APIs that authorize on the ID token.
    """
    session = store.read_session()
    if session is None:
        raise SignalsAuthError(RECONNECT_REQUIRED, "not_connected")
    st = store.read_status()
    if st.get("state") not in STOPPING_CLASSES and _access_token_fresh(
        session, now=now_fn(), skew=skew_seconds
    ):
        value = (session.get("tokens") or {}).get(token)
        if value:
            return value
    session = renew(
        store, skew_seconds=skew_seconds, transport=transport, endpoint=endpoint, now_fn=now_fn
    )
    value = (session.get("tokens") or {}).get(token)
    if not value:
        raise SignalsAuthError(RECONNECT_REQUIRED, f"session_missing_{token}")
    return value


def import_session(
    store: SignalsStore, captured_or_session: dict[str, Any], *, now: float | None = None
) -> dict[str, Any]:
    """Install a new session (connect / reconnect / provision).  Closes any
    open episode.  Accepts either a raw capture or an already-built session."""
    now = time.time() if now is None else now
    if (
        captured_or_session.get("schemaVersion") == SCHEMA_VERSION
        and "tokens" in captured_or_session
    ):
        tokens = captured_or_session["tokens"]
        session = build_session(
            {
                "clientId": captured_or_session.get("clientId"),
                "username": captured_or_session.get("username"),
                **tokens,
                **(captured_or_session.get("device") or {}),
            },
            now=now,
        )
        for keep in ("capturedAt", "lastRenewedAt", "renewCount", "refreshTokenRotations"):
            if captured_or_session.get(keep) is not None:
                session[keep] = captured_or_session[keep]
    else:
        session = build_session(captured_or_session, now=now)
    with store.lock():
        store.write_session(session)
        _record_success(store, now=now, event="connected")
    return session


def disconnect(store: SignalsStore) -> bool:
    """Remove the local session (under the lock).  Remote revocation is a
    separate, explicit step (:func:`revoke_remote`)."""
    with store.lock():
        removed = store.delete_session()
        st = store.read_status()
        st.pop("episode", None)
        st["state"] = STATE_NOT_CONNECTED
        store.write_status(st)
    return removed


def revoke_remote(
    store: SignalsStore, *, transport: Transport | None = None, endpoint: str | None = None
) -> bool:
    """Revoke this session's refresh token at Cognito (``RevokeToken``).

    Kills every copy of THIS session, including a provisioned box copy that
    shares the token — which is why it is opt-in.
    """
    transport = transport or _urllib_transport
    with store.lock():
        session = store.read_session()
        if session is None:
            return False
        tokens = session.get("tokens") or {}
        real_endpoint, _r, _p = cognito_endpoint_for(tokens.get("accessToken") or "")
        code, payload, _h = transport(
            endpoint or real_endpoint,
            "RevokeToken",
            {"ClientId": session.get("clientId"), "Token": tokens.get("refreshToken")},
            HTTP_TIMEOUT_SECONDS,
        )
    if code == 200:
        return True
    cls, reason = _classify_cognito(code, payload)
    raise SignalsAuthError(cls, f"revoke_{reason}")


# ── Owner notice (reuses the server's existing SMTP alert channel) ──────────


def format_reconnect_notice(episode: dict[str, Any]) -> tuple[str, str]:
    cls = episode.get("failureClass")
    action = (
        "Run on your Windows machine:\n"
        "  python scripts/signals_connect.py reconnect\n"
        "then provision the box:\n"
        "  python scripts/signals_connect.py provision --host <ssh-alias>\n"
        if cls == RECONNECT_REQUIRED
        else "This is NOT an expired login; reconnecting may not help. Check the Signals "
        "account's access/subscription, then run `signals_connect.py status` on the box.\n"
    )
    subject = f"[Brisket Ops] Signals connection needs attention ({cls})"
    body = (
        f"Signals authenticated collection has STOPPED.\n\n"
        f"Class:   {cls}\n"
        f"Reason:  {episode.get('reason')}\n"
        f"Since:   {episode.get('startedAt')}\n"
        f"Episode: {episode.get('id')}\n\n"
        f"Last-good Signals data is preserved with its true age.\n\n{action}\n"
        "Never paste a Signals email code, cookie or token into chat, an issue or a commit.\n"
    )
    return subject, body


def deliver_reconnect_notice(
    *,
    store: SignalsStore | None = None,
    delivery: Callable[[str, str, str], bool] | None,
    to_email: str | None,
) -> dict[str, Any]:
    """Deliver at most ONE notice per open episode.  Never raises.

    ``noticeDeliveredAt`` is stamped only after a delivery succeeded, so an
    unconfigured mailer does not silently consume the episode (same rule as
    ``src/api/ops_alerts.py`` audit F-20).
    """
    try:
        store = store or SignalsStore.open()
    except (StorePathError, OSError) as exc:
        return {"state": "store_unavailable", "error": type(exc).__name__}
    st = store.read_status()
    episode = st.get("episode")
    if not episode:
        return {"state": st.get("state") or STATE_NOT_CONNECTED, "pending": False}
    if episode.get("noticeDeliveredAt"):
        return {"state": st.get("state"), "pending": False, "episode": episode.get("id")}
    configured = delivery is not None and bool(to_email)
    delivered = False
    if configured:
        subject, body = format_reconnect_notice(episode)
        try:
            delivered = bool(delivery(to_email, subject, body))
        except Exception:  # noqa: BLE001 - a mailer fault must never break the sweep
            delivered = False
    episode["noticeAttempts"] = int(episode.get("noticeAttempts") or 0) + (1 if configured else 0)
    if delivered:
        episode["noticeDeliveredAt"] = _utc_iso(time.time())
    st["episode"] = episode
    with contextlib.suppress(OSError):
        store.write_status(st)
    return {
        "state": st.get("state"),
        "pending": not delivered,
        "delivered": delivered,
        "deliveryConfigured": configured,
        "episode": episode.get("id"),
    }
