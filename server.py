"""
Dynasty Trade Calculator — Unified Server
==========================================
Single command to run everything:
    python server.py

Serves the dashboard at http://localhost:8000
Scrapes all sites every 2 hours automatically.
Manual scrape: POST http://localhost:8000/api/scrape

Requirements:
    pip install fastapi uvicorn --break-system-packages
    (Playwright + other scraper deps assumed already installed)
"""

import asyncio
import json
import os
import sys
import threading
import time
import logging
import traceback
import smtplib
import gzip
import hashlib
import hmac
import shutil
import uuid
import urllib.request
import urllib.error
import urllib.parse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

try:
    import anthropic
except ImportError:  # pragma: no cover — optional dep; chat endpoint degrades gracefully
    anthropic = None

from src.api.data_contract import (
    CONTRACT_VERSION as API_DATA_CONTRACT_VERSION,
    build_api_data_contract,
    build_api_startup_payload,
    build_rankings_delta_payload,
    get_ranking_source_registry,
    normalize_source_overrides,
    normalize_tep_multiplier,
    validate_api_data_contract,
)
from src.api import rank_history as _rank_history
from src.api import source_history as _source_history
from src.api import signal_alerts as _signal_alerts
from src.api import terminal as _terminal
from src.api import trade_simulator as _trade_simulator
from src.api import user_kv as _user_kv
from src.api import league_registry as _league_registry
from src.api import sleeper_overlay as _sleeper_overlay
from src.news import NewsService, build_default_service

# ── CONFIG ──────────────────────────────────────────────────────────────
SCRAPE_INTERVAL_HOURS = 2
PORT = 8000
HOST = "0.0.0.0"  # accessible from local network; use "127.0.0.1" for local only
SCRAPE_STALL_SECONDS = int(os.getenv("SCRAPE_STALL_SECONDS", "900"))
SCRAPE_RUN_TIMEOUT_SECONDS = int(os.getenv("SCRAPE_RUN_TIMEOUT_SECONDS", "7200"))

# ── EMAIL ALERTS ────────────────────────────────────────────────────────
# Configure alerts via environment variables (no hardcoded secrets):
#   ALERT_ENABLED=true|false
#   ALERT_TO=you@example.com
#   ALERT_FROM=sender@gmail.com
#   ALERT_PASSWORD=<gmail app password>
# Optional alias:
#   GMAIL_APP_PASSWORD=<gmail app password>
def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://127.0.0.1:3000").rstrip("/")
FRONTEND_RUNTIME = "next"

ALERT_ENABLED = _env_bool("ALERT_ENABLED", False)
ALERT_TO = os.getenv("ALERT_TO", "")
ALERT_FROM = os.getenv("ALERT_FROM", "")
ALERT_PASSWORD = os.getenv("ALERT_PASSWORD") or os.getenv("GMAIL_APP_PASSWORD", "")

# Shared secret for the systemd signal-alert timer.  When set, any
# request to ``POST /api/signal-alerts/run`` with a matching
# ``Authorization: Bearer <token>`` header is accepted in place of
# the usual password-session gate.  Empty = cron auth disabled
# (only browser-sessioned admins can trigger the sweep).  Generate
# with e.g. ``openssl rand -hex 32`` and store in .env alongside the
# ALERT_* creds.  Treat it like a password: leaking it lets anyone
# force a full alert send.
SIGNAL_ALERT_CRON_TOKEN = os.getenv("SIGNAL_ALERT_CRON_TOKEN", "").strip()

# ── UPTIME WATCHDOG ────────────────────────────────────────────────────
UPTIME_CHECK_ENABLED = _env_bool("UPTIME_CHECK_ENABLED", True)
UPTIME_CHECK_URL = os.getenv(
    "UPTIME_CHECK_URL",
    "https://riskittogetthebrisket.org/api/health",
).strip()
UPTIME_CHECK_INTERVAL_SEC = int(os.getenv("UPTIME_CHECK_INTERVAL_SEC", "300"))
UPTIME_CHECK_TIMEOUT_SEC = float(os.getenv("UPTIME_CHECK_TIMEOUT_SEC", "5"))
UPTIME_ALERT_FAIL_THRESHOLD = int(os.getenv("UPTIME_ALERT_FAIL_THRESHOLD", "2"))

# ── LIGHTWEIGHT AUTH GATE (PRIVATE-USE) ────────────────────────────────
# App UI is intentionally gated behind Jason login.
JASON_LOGIN_USERNAME = (os.getenv("JASON_LOGIN_USERNAME") or "jasonleetucker").strip()
JASON_LOGIN_PASSWORD = (os.getenv("JASON_LOGIN_PASSWORD") or "Elliott21!").strip()
JASON_AUTH_COOKIE_NAME = "jason_session"
JASON_AUTH_COOKIE_SECURE = _env_bool("JASON_AUTH_COOKIE_SECURE", True)

# Private-app allowlist.  Only these Sleeper handles can sign in
# via /api/auth/sleeper-login.  Anyone else — even with a valid
# Sleeper account — gets 403.  Password auth (JASON_LOGIN_*) is
# the operator fallback and isn't constrained by this list.
# Env var is comma-separated, lowercase-normalised at load time.
PRIVATE_APP_ALLOWED_USERNAMES = frozenset(
    u.strip().lower()
    for u in (os.getenv("PRIVATE_APP_ALLOWED_USERNAMES") or "jasonleetucker").split(",")
    if u.strip()
)

# Rate limit: max 1 email per hour to avoid spam on repeated failures
_last_alert_time = 0
ALERT_COOLDOWN_SEC = 3600

def send_alert(subject: str, body: str):
    """Send an email alert. Fails silently if not configured."""
    global _last_alert_time

    if not ALERT_ENABLED or not ALERT_FROM or not ALERT_PASSWORD:
        return

    now = time.time()
    if now - _last_alert_time < ALERT_COOLDOWN_SEC:
        log.info(f"Alert suppressed (cooldown): {subject}")
        return

    try:
        msg = MIMEMultipart()
        msg["From"] = ALERT_FROM
        msg["To"] = ALERT_TO
        msg["Subject"] = f"[Dynasty Server] {subject}"

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        html = f"""
        <div style="font-family:monospace;font-size:14px;padding:16px;">
            <h2 style="color:#ff4060;">⚠ Dynasty Server Alert</h2>
            <p><strong>Time:</strong> {timestamp}</p>
            <p><strong>Issue:</strong> {subject}</p>
            <hr>
            <pre style="background:#1a1a2e;color:#e2e8f8;padding:12px;border-radius:8px;overflow-x:auto;">{body}</pre>
        </div>
        """
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(ALERT_FROM, ALERT_PASSWORD)
            server.send_message(msg)

        _last_alert_time = now
        log.info(f"Alert sent: {subject}")
    except Exception as e:
        log.error(f"Failed to send alert email: {e}")


# ── PATHS ───────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"
SCRAPER_PATH = BASE_DIR / "Dynasty Scraper.py"

DATA_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

# ── LOGGING ─────────────────────────────────────────────────────────────
# R-8: Structured JSON logging when LOG_FORMAT=json (for log aggregation).
# Default is human-readable for local dev and journalctl.
LOG_FORMAT = os.getenv("LOG_FORMAT", "text").strip().lower()

if LOG_FORMAT == "json":
    class _JsonFormatter(logging.Formatter):
        """Minimal JSON log formatter for structured log aggregation."""
        def format(self, record):
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            }
            if record.exc_info and record.exc_info[0]:
                entry["exception"] = self.formatException(record.exc_info)
            return json.dumps(entry, ensure_ascii=False)

    _handler = logging.StreamHandler()
    _handler.setFormatter(_JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[_handler])
else:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
log = logging.getLogger("dynasty-server")

# ── STATE ───────────────────────────────────────────────────────────────
# In-memory cache of latest scrape data
latest_data: dict | None = None
latest_contract_data: dict | None = None
latest_data_bytes: bytes | None = None
latest_data_gzip_bytes: bytes | None = None
latest_data_etag: str | None = None
# Lean runtime payload (drops heavy contract-only arrays not needed by frontend startup).
latest_runtime_data: dict | None = None
latest_runtime_data_bytes: bytes | None = None
latest_runtime_data_gzip_bytes: bytes | None = None
latest_runtime_data_etag: str | None = None
# Startup-slim payload for first paint and early interaction.
latest_startup_data: dict | None = None
latest_startup_data_bytes: bytes | None = None
latest_startup_data_gzip_bytes: bytes | None = None
latest_startup_data_etag: str | None = None
latest_data_source: dict = {
    "type": "",
    "path": "",
    "loadedAt": "",
}
contract_health: dict = {
    "ok": False,
    "status": "unknown",
    "errors": ["contract not initialized"],
    "warnings": [],
    "errorCount": 1,
    "warningCount": 0,
    "checkedAt": None,
    "contractVersion": API_DATA_CONTRACT_VERSION,
    "playerCount": 0,
}
# ── NEWS SERVICE ───────────────────────────────────────────────────────
# Lazy-built singleton.  Built on first request rather than at import
# so unit tests can monkey-patch the factory and the server can boot
# even if a transient DNS failure would block provider construction.
_news_service: NewsService | None = None
_news_service_lock = threading.Lock()


def _get_news_service() -> NewsService:
    global _news_service
    if _news_service is not None:
        return _news_service
    with _news_service_lock:
        if _news_service is None:
            _news_service = build_default_service()
    return _news_service


def _reset_news_service_for_tests(svc: NewsService | None = None) -> None:
    """Test hook — inject a stubbed service or clear the singleton."""
    global _news_service
    with _news_service_lock:
        _news_service = svc


def _live_player_names() -> list[str]:
    """Return every player name visible in the live contract.

    ESPN's RSS provider uses this set to tag headlines with matched
    players; returning an empty list when the contract hasn't
    loaded yet degrades gracefully — headlines still surface,
    they just arrive with empty ``players[]``.
    """
    contract = latest_contract_data or {}
    rows = contract.get("playersArray") or []
    names: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in ("displayName", "name", "canonicalName", "fullName"):
            v = row.get(key)
            if isinstance(v, str) and v.strip():
                names.append(v.strip())
                break
    return names


# R-9: Lightweight metrics counters
_metrics: dict = {
    "server_start_time": None,
    "request_count": 0,
    "scrape_total": 0,
    "scrape_failures": 0,
    "scrape_duration_seconds_last": 0.0,
    "data_age_seconds": 0.0,
}
# Canonical scrape lifecycle state.
# Compatibility aliases are maintained:
#   running -> is_running
#   error   -> last_error
scrape_status = {
    "running": False,
    "is_running": False,      # legacy alias for UI compatibility
    "hung": False,
    "stalled": False,
    "started_at": None,
    "finished_at": None,
    "last_heartbeat": None,
    "last_scrape": None,      # last successful scrape ISO timestamp
    "last_success_at": None,
    "last_failure_at": None,
    "last_duration_sec": None,
    "next_scrape": None,      # ISO timestamp
    "error": None,
    "last_error": None,       # legacy alias for UI compatibility
    "current_step": None,
    "current_source": None,
    "progress_step_index": 0,
    "progress_step_total": 0,
    "worker_id": None,
    "scrape_count": 0,
    "run_events": [],
}
# R-4: Rolling scrape history for success rate tracking.
SCRAPE_HISTORY_MAX = 50
scrape_history: list[dict] = []

# Single-owner run lock: only one scrape run can own mutable active state.
scrape_run_lock = asyncio.Lock()
uptime_status = {
    "enabled": UPTIME_CHECK_ENABLED,
    "target_url": UPTIME_CHECK_URL,
    "last_check": None,
    "last_ok": None,
    "last_error": None,
    "last_http_status": None,
    "consecutive_failures": 0,
}
frontend_runtime_status = {
    "configured": "next",
    "active": "next",
    "reason": "next_only",
    "fallbackFrom": None,
    "lastChecked": None,
}
# In-memory auth sessions for private-use gate.
auth_sessions: dict[str, dict] = {}

# Startup validation summary — populated by lifespan; surfaced via
# /api/health.  Default to an empty summary so the endpoint never
# references an unbound name before lifespan runs.
_startup_checks_summary: dict = {"total": 0, "ok": 0, "failed": 0, "fatal": 0, "checks": []}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# R-10: Disk space guard — minimum free space before writing data files (in MB)
DISK_SPACE_MIN_MB = int(os.getenv("DISK_SPACE_MIN_MB", "500"))


def _check_disk_space(path: Path | None = None) -> tuple[bool, int]:
    """Check if there's enough disk space. Returns (ok, free_mb)."""
    target = path or DATA_DIR
    try:
        usage = shutil.disk_usage(str(target))
        free_mb = usage.free // (1024 * 1024)
        return free_mb >= DISK_SPACE_MIN_MB, free_mb
    except OSError:
        # If we can't check, allow the write (fail-open)
        return True, -1


def _sanitize_next_path(raw: str | None, default: str = "/app") -> str:
    value = str(raw or "").strip()
    if not value:
        return default
    if value.startswith("http://") or value.startswith("https://"):
        return default
    if not value.startswith("/") or value.startswith("//"):
        return default
    if "\n" in value or "\r" in value:
        return default
    return value


def _get_auth_session(request: Request) -> dict | None:
    session_id = str(request.cookies.get(JASON_AUTH_COOKIE_NAME, "")).strip()
    if not session_id:
        return None
    session = auth_sessions.get(session_id)
    if not isinstance(session, dict):
        return None
    return session


def _is_authenticated(request: Request) -> bool:
    return _get_auth_session(request) is not None


def _create_auth_session(
    username: str,
    *,
    sleeper_user_id: str | None = None,
    display_name: str | None = None,
    avatar: str | None = None,
    auth_method: str = "password",
) -> str:
    """Create an in-memory session for ``username``.

    ``sleeper_user_id`` / ``display_name`` / ``avatar`` are populated
    when the session was created via the Sleeper username sign-in
    flow (see ``POST /api/auth/sleeper-login``) so downstream
    handlers can resolve the user's Sleeper team by ownerId without
    another round-trip.  ``auth_method`` tags sessions as either
    ``password`` (admin login) or ``sleeper`` (username lookup)
    so logs and audit tooling can tell them apart.
    """
    session_id = uuid.uuid4().hex
    payload = {
        "username": str(username or ""),
        "sleeper_user_id": str(sleeper_user_id or ""),
        "display_name": str(display_name or username or ""),
        "avatar": str(avatar or ""),
        "auth_method": str(auth_method or "password"),
        "created_at": _utc_now_iso(),
    }
    auth_sessions[session_id] = payload
    # Persist the session so a deploy/restart doesn't force a re-login.
    # Best-effort: any SQLite failure falls through to in-memory-only
    # behavior (the existing behavior — no regression).
    try:
        from src.api import session_store as _ss
        _ss.persist(
            session_id, payload,
            allowlist=PRIVATE_APP_ALLOWED_USERNAMES,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("session_store persist in _create_auth_session failed: %s", exc)
    if len(auth_sessions) > 5000:
        oldest = sorted(
            auth_sessions.items(),
            key=lambda kv: str((kv[1] or {}).get("created_at") or ""),
        )[:500]
        for sid, _ in oldest:
            auth_sessions.pop(sid, None)
    return session_id


def _clear_auth_session(request: Request) -> None:
    session_id = str(request.cookies.get(JASON_AUTH_COOKIE_NAME, "")).strip()
    if session_id:
        auth_sessions.pop(session_id, None)
        try:
            from src.api import session_store as _ss
            _ss.evict(session_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("session_store evict failed: %s", exc)


def _auth_redirect_response(request: Request, default_next: str = "/app") -> RedirectResponse:
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    safe_next = _sanitize_next_path(next_path, default_next)
    encoded_next = urllib.parse.quote(safe_next, safe="/?=&")
    return RedirectResponse(url=f"/login?next={encoded_next}", status_code=302)


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _seconds_since_iso(ts: str | None) -> float | None:
    dt = _parse_iso(ts)
    if dt is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())


def _trim_run_events(limit: int = 50) -> None:
    events = scrape_status.get("run_events") or []
    if len(events) > limit:
        scrape_status["run_events"] = events[-limit:]


def _record_scrape_event(event: str, level: str = "info", message: str = "", **meta) -> None:
    payload = {
        "ts": _utc_now_iso(),
        "event": event,
        "message": message,
    }
    if meta:
        payload["meta"] = meta
    scrape_status.setdefault("run_events", []).append(payload)
    _trim_run_events()

    log_line = f"[Scrape] {event}"
    if message:
        log_line += f" — {message}"
    if meta:
        log_line += f" | {meta}"
    if level == "error":
        log.error(log_line)
    elif level == "warning":
        log.warning(log_line)
    else:
        log.info(log_line)


def _touch_scrape_heartbeat() -> None:
    scrape_status["last_heartbeat"] = _utc_now_iso()


def _is_scrape_stalled() -> bool:
    if not scrape_status.get("running"):
        return False
    age = _seconds_since_iso(scrape_status.get("last_heartbeat"))
    if age is None:
        return False
    return age > SCRAPE_STALL_SECONDS


def _sync_scrape_alias_fields() -> None:
    scrape_status["is_running"] = bool(scrape_status.get("running"))
    scrape_status["last_error"] = scrape_status.get("error")


def _reconcile_orphaned_running_state() -> None:
    # Safety net: if status says running but lock is free, a prior worker exited
    # unexpectedly before state cleanup. Reset running state explicitly.
    if scrape_status.get("running") and not scrape_run_lock.locked():
        _record_scrape_event(
            "orphaned_running_reset",
            level="warning",
            message="Detected running=True without active lock; resetting state",
            worker_id=scrape_status.get("worker_id"),
        )
        scrape_status["running"] = False
        scrape_status["hung"] = True
        scrape_status["stalled"] = True
        scrape_status["finished_at"] = _utc_now_iso()
        scrape_status["current_step"] = "stale_state_reset"
        scrape_status["current_source"] = None
        _touch_scrape_heartbeat()
        _sync_scrape_alias_fields()


def _start_scrape_run(trigger: str) -> str:
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    now_iso = _utc_now_iso()
    scrape_status.update(
        {
            "running": True,
            "hung": False,
            "stalled": False,
            "started_at": now_iso,
            "finished_at": None,
            "last_heartbeat": now_iso,
            "current_step": "bootstrap",
            "current_source": "server",
            "progress_step_index": 0,
            "progress_step_total": 0,
            "worker_id": run_id,
        }
    )
    _sync_scrape_alias_fields()
    _record_scrape_event("scrape_started", message=f"trigger={trigger}", trigger=trigger, worker_id=run_id)
    return run_id


def _update_scrape_progress(
    *,
    step: str | None = None,
    source: str | None = None,
    step_index: int | None = None,
    step_total: int | None = None,
    event: str | None = None,
    message: str | None = None,
    level: str = "info",
    meta: dict | None = None,
) -> None:
    if step is not None:
        scrape_status["current_step"] = step
    if source is not None:
        scrape_status["current_source"] = source
    if step_index is not None:
        scrape_status["progress_step_index"] = int(step_index)
    if step_total is not None:
        scrape_status["progress_step_total"] = int(step_total)
    scrape_status["hung"] = False
    scrape_status["stalled"] = False
    _touch_scrape_heartbeat()
    _sync_scrape_alias_fields()
    if event:
        _record_scrape_event(event, level=level, message=message or "", **(meta or {}))


def _mark_scrape_success(elapsed: float, player_count: int, site_count: int, total_sites: int) -> None:
    now_iso = _utc_now_iso()
    scrape_status.update(
        {
            "running": False,
            "hung": False,
            "stalled": False,
            "finished_at": now_iso,
            "last_scrape": now_iso,
            "last_success_at": now_iso,
            "last_duration_sec": round(elapsed, 1),
            "error": None,
            "current_step": "complete",
            "current_source": None,
            "scrape_count": int(scrape_status.get("scrape_count", 0)) + 1,
        }
    )
    _touch_scrape_heartbeat()
    _sync_scrape_alias_fields()
    _record_scrape_event(
        "scrape_succeeded",
        message=f"{player_count} players, {site_count}/{total_sites} sites, {elapsed:.1f}s",
        player_count=player_count,
        site_count=site_count,
        total_sites=total_sites,
        duration_sec=round(elapsed, 1),
    )
    # R-4: Record to rolling history
    _record_scrape_history("success", elapsed, player_count=player_count,
                           site_count=site_count, total_sites=total_sites)
    # R-9: Update metrics counters
    _metrics["scrape_total"] = _metrics.get("scrape_total", 0) + 1
    _metrics["scrape_duration_seconds_last"] = round(elapsed, 1)


def _mark_scrape_failure(exc: Exception, elapsed: float) -> None:
    now_iso = _utc_now_iso()
    error_text = f"{type(exc).__name__}: {str(exc)[:400]}"
    failed_step = scrape_status.get("current_step")
    failed_source = scrape_status.get("current_source")
    scrape_status.update(
        {
            "running": False,
            "hung": False,
            "stalled": False,
            "finished_at": now_iso,
            "last_failure_at": now_iso,
            "last_duration_sec": round(elapsed, 1),
            "error": error_text,
            "current_step": "failed",
        }
    )
    _touch_scrape_heartbeat()
    _sync_scrape_alias_fields()
    _record_scrape_event(
        "scrape_failed",
        level="error",
        message=error_text,
        failed_step=failed_step,
        failed_source=failed_source,
        duration_sec=round(elapsed, 1),
    )
    # R-4: Record to rolling history
    _record_scrape_history("failure", elapsed, error=error_text)
    # R-9: Update metrics counters
    _metrics["scrape_total"] = _metrics.get("scrape_total", 0) + 1
    _metrics["scrape_failures"] = _metrics.get("scrape_failures", 0) + 1
    _metrics["scrape_duration_seconds_last"] = round(elapsed, 1)


def _record_scrape_history(outcome: str, duration: float, **meta) -> None:
    """R-4: Append to rolling scrape history for success rate tracking."""
    entry = {
        "ts": _utc_now_iso(),
        "outcome": outcome,
        "duration_sec": round(duration, 1),
    }
    entry.update(meta)
    scrape_history.append(entry)
    # Trim to max size
    while len(scrape_history) > SCRAPE_HISTORY_MAX:
        scrape_history.pop(0)


def _scrape_success_rate_24h() -> dict:
    """R-4: Calculate scrape success rate over the last 24 hours."""
    now = datetime.now(timezone.utc)
    recent = []
    for entry in scrape_history:
        try:
            ts = datetime.fromisoformat(entry["ts"])
            if (now - ts).total_seconds() <= 86400:
                recent.append(entry)
        except (ValueError, TypeError, KeyError):
            continue
    total = len(recent)
    if total == 0:
        return {"total": 0, "success": 0, "failure": 0, "rate": None}
    successes = sum(1 for e in recent if e.get("outcome") == "success")
    return {
        "total": total,
        "success": successes,
        "failure": total - successes,
        "rate": round(successes / total, 2),
    }


def _finalize_scrape_run(worker_id: str) -> None:
    # Guaranteed cleanup path (always called in run_scraper finally).
    if scrape_status.get("worker_id") != worker_id:
        return
    if scrape_status.get("running"):
        scrape_status["running"] = False
        if not scrape_status.get("finished_at"):
            scrape_status["finished_at"] = _utc_now_iso()
        if scrape_status.get("current_step") not in {"complete", "failed"}:
            scrape_status["current_step"] = "finalized"
            _record_scrape_event(
                "scrape_finalized_with_running_true",
                level="warning",
                message="Forced running=False during finally cleanup",
                worker_id=worker_id,
            )
    if scrape_status.get("current_step") == "complete":
        scrape_status["current_source"] = None
    _touch_scrape_heartbeat()
    _sync_scrape_alias_fields()


def _build_scrape_progress_callback(worker_id: str):
    async def _on_progress(payload: dict):
        if scrape_status.get("worker_id") != worker_id:
            return
        if not isinstance(payload, dict):
            return
        _update_scrape_progress(
            step=payload.get("step"),
            source=payload.get("source"),
            step_index=payload.get("step_index"),
            step_total=payload.get("step_total"),
            event=payload.get("event"),
            message=payload.get("message"),
            level=payload.get("level", "info"),
            meta=payload.get("meta"),
        )

    return _on_progress


def _scrape_status_payload() -> dict:
    _reconcile_orphaned_running_state()
    stalled = _is_scrape_stalled()
    was_stalled = bool(scrape_status.get("stalled"))
    if stalled:
        scrape_status["hung"] = True
        scrape_status["stalled"] = True
        if not was_stalled:
            _record_scrape_event(
                "scrape_stalled_detected",
                level="warning",
                message=(
                    f"No heartbeat update for >{SCRAPE_STALL_SECONDS}s "
                    f"(step={scrape_status.get('current_step')}, "
                    f"source={scrape_status.get('current_source')})"
                ),
                stall_threshold_sec=SCRAPE_STALL_SECONDS,
                current_step=scrape_status.get("current_step"),
                current_source=scrape_status.get("current_source"),
            )
    else:
        scrape_status["hung"] = False
        scrape_status["stalled"] = False
    _sync_scrape_alias_fields()

    payload = dict(scrape_status)
    payload["stall_threshold_sec"] = SCRAPE_STALL_SECONDS
    payload["run_timeout_sec"] = SCRAPE_RUN_TIMEOUT_SECONDS
    payload["status_summary"] = (
        "stalled"
        if payload.get("stalled")
        else "running"
        if payload.get("running")
        else "failed"
        if payload.get("error")
        else "idle"
    )
    return payload


def _set_latest_data_source(source_type: str, path: str | None = None) -> None:
    latest_data_source.update(
        {
            "type": str(source_type or ""),
            "path": str(path or ""),
            "loadedAt": _utc_now_iso(),
        }
    )


# Identity-keyed cache for live rankDerivedValue lookups used by the
# trade-suggestions overlay.  ``latest_contract_data`` is replaced
# (never mutated) each time ``_prime_latest_payload`` runs, so the
# cache invalidates automatically when a fresh payload arrives.
_LIVE_BY_NAME_CACHE: dict = {"contract_id": None, "value": {}}


def _live_by_name_from_contract(contract: dict | None) -> dict[str, int]:
    """Return ``{displayName: rankDerivedValue}`` for the live contract.

    Cached by ``id(contract)`` so repeat trade-suggestion requests
    between scrapes skip the N-row walk.  Returns the cached dict by
    reference; callers must not mutate it.
    """
    cid = id(contract) if contract is not None else None
    if _LIVE_BY_NAME_CACHE["contract_id"] == cid and cid is not None:
        return _LIVE_BY_NAME_CACHE["value"]
    built: dict[str, int] = {}
    try:
        live_rows = (contract or {}).get("playersArray") or []
    except Exception:  # noqa: BLE001
        live_rows = []
    for row in live_rows:
        name = str(row.get("canonicalName") or row.get("displayName") or "").strip()
        if not name:
            continue
        rdv = row.get("rankDerivedValue")
        try:
            v = int(rdv) if rdv is not None else None
        except (TypeError, ValueError):
            continue
        if v is not None and v > 0:
            built[name] = v
    _LIVE_BY_NAME_CACHE["contract_id"] = cid
    _LIVE_BY_NAME_CACHE["value"] = built
    return built


def _build_source_health_snapshot(data: dict | None) -> dict:
    payload = data or {}
    sites = payload.get("sites")
    if not isinstance(sites, list):
        sites = []
    source_counts: dict[str, int] = {}
    missing: list[str] = []
    available = 0
    for row in sites:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip()
        if not key:
            continue
        count = int(row.get("playerCount") or 0)
        source_counts[key] = count
        if count > 0:
            available += 1
        else:
            missing.append(key)

    failures: list[dict] = []
    seen_failures: set[tuple[str, str, str]] = set()

    def _push_failure(source: str, reason: str, details: dict | None = None) -> None:
        src = str(source or "").strip()
        rsn = str(reason or "").strip() or "unknown"
        d = details if isinstance(details, dict) else {}
        detail_sig = str(d.get("error") or d.get("message") or "")
        key = (src, rsn, detail_sig)
        if key in seen_failures:
            return
        seen_failures.add(key)
        failures.append(
            {
                "source": src,
                "reason": rsn,
                "details": d,
            }
        )

    settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
    dlf_import = settings.get("dlfImport") if isinstance(settings.get("dlfImport"), dict) else {}
    for src_key, meta in dlf_import.items():
        if not isinstance(meta, dict):
            continue
        if not meta.get("loaded", False):
            _push_failure(
                str(src_key),
                "not_loaded",
                {
                    "file": meta.get("file"),
                    "parseMode": meta.get("parseMode"),
                    "badRows": meta.get("badRows"),
                },
            )
        elif meta.get("stale", False):
            _push_failure(
                str(src_key),
                "stale_csv",
                {
                    "file": meta.get("file"),
                    "ageDays": meta.get("ageDays"),
                },
            )

    source_run_summary = settings.get("sourceRunSummary")
    source_runtime = {}
    partial_run = False
    if isinstance(source_run_summary, dict):
        enabled_sources = source_run_summary.get("enabledSources")
        complete_sources = source_run_summary.get("completeSources")
        partial_sources = source_run_summary.get("partialSources")
        timed_out_sources = source_run_summary.get("timedOutSources")
        failed_sources = source_run_summary.get("failedSources")
        source_rows = source_run_summary.get("sources")
        if not isinstance(enabled_sources, list):
            enabled_sources = []
        if not isinstance(complete_sources, list):
            complete_sources = []
        if not isinstance(partial_sources, list):
            partial_sources = []
        if not isinstance(timed_out_sources, list):
            timed_out_sources = []
        if not isinstance(failed_sources, list):
            failed_sources = []
        if not isinstance(source_rows, dict):
            source_rows = {}

        for src in timed_out_sources:
            row = source_rows.get(src) if isinstance(source_rows.get(src), dict) else {}
            _push_failure(
                str(src),
                "timeout",
                {
                    "error": row.get("error"),
                    "message": row.get("message"),
                    "timeoutSec": row.get("timeoutSec"),
                    "valueCount": row.get("valueCount"),
                },
            )
        for src in failed_sources:
            row = source_rows.get(src) if isinstance(source_rows.get(src), dict) else {}
            _push_failure(
                str(src),
                "failed",
                {
                    "error": row.get("error"),
                    "message": row.get("message"),
                    "valueCount": row.get("valueCount"),
                },
            )
        for src in partial_sources:
            row = source_rows.get(src) if isinstance(source_rows.get(src), dict) else {}
            _push_failure(
                str(src),
                "partial",
                {
                    "message": row.get("message"),
                    "valueCount": row.get("valueCount"),
                },
            )

        partial_run = bool(
            source_run_summary.get("partialRun")
            or partial_sources
            or timed_out_sources
            or failed_sources
        )
        source_runtime = {
            "overall_status": source_run_summary.get("overallStatus"),
            "partial_run": partial_run,
            "started_at": source_run_summary.get("startedAt"),
            "finished_at": source_run_summary.get("finishedAt"),
            "duration_sec": source_run_summary.get("durationSec"),
            "enabled_sources": sorted([str(s) for s in enabled_sources]),
            "complete_sources": sorted([str(s) for s in complete_sources]),
            "partial_sources": sorted([str(s) for s in partial_sources]),
            "timed_out_sources": sorted([str(s) for s in timed_out_sources]),
            "failed_sources": sorted([str(s) for s in failed_sources]),
        }

    if not partial_run:
        partial_run = len(failures) > 0

    return {
        "total_sources": len(source_counts),
        "sources_with_data": available,
        "source_counts": source_counts,
        "missing_sources": sorted(missing),
        "partial_run": bool(partial_run),
        "source_runtime": source_runtime,
        "source_failures": failures,
    }




# ── SCRAPER INTEGRATION ────────────────────────────────────────────────
def _prime_latest_payload(data: dict | None, *, is_fresh_scrape: bool = False) -> None:
    """Pre-serialize latest payload once so /api/data returns instantly.

    ``is_fresh_scrape`` gates rank-history appends: startup priming
    from cached disk data must NOT append a new "today" entry (which
    would fabricate a history point after every server restart).
    Scrape-promotion callers pass ``is_fresh_scrape=True``; startup
    lifespan priming leaves it False so the history log stays read-
    only until a real scrape lands.
    """
    global latest_contract_data, latest_data_bytes, latest_data_gzip_bytes, latest_data_etag
    global latest_runtime_data, latest_runtime_data_bytes, latest_runtime_data_gzip_bytes, latest_runtime_data_etag
    global latest_startup_data, latest_startup_data_bytes, latest_startup_data_gzip_bytes, latest_startup_data_etag
    global contract_health
    latest_data_bytes = None
    latest_data_gzip_bytes = None
    latest_data_etag = None
    latest_contract_data = None
    latest_runtime_data = None
    latest_runtime_data_bytes = None
    latest_runtime_data_gzip_bytes = None
    latest_runtime_data_etag = None
    latest_startup_data = None
    latest_startup_data_bytes = None
    latest_startup_data_gzip_bytes = None
    latest_startup_data_etag = None
    if not data:
        return
    try:
        contract_payload = build_api_data_contract(data, data_source=latest_data_source)
        contract_report = validate_api_data_contract(contract_payload)
        contract_payload["contractHealth"] = {
            "ok": bool(contract_report.get("ok")),
            "status": contract_report.get("status"),
            "errorCount": int(contract_report.get("errorCount", 0)),
            "warningCount": int(contract_report.get("warningCount", 0)),
            "checkedAt": contract_report.get("checkedAt"),
        }
        # Rank-history integration:
        # - Append a new "today" snapshot ONLY on fresh scrape
        #   promotions.  Startup priming from cached disk data must
        #   stay read-only or every restart fabricates a redundant
        #   history entry (and /api/data/rank-history misleads
        #   consumers into thinking a scrape ran).
        # - Stamp ``rankHistory`` onto every row regardless of
        #   source — it's a pure read of the existing log and the
        #   frontend glyph needs it on startup-primed payloads too.
        try:
            if is_fresh_scrape:
                _rank_history.append_snapshot(contract_payload)
                # Sister snapshot: per-source value history.  Stored in
                # a separate JSONL so the rank-history log stays small
                # and readable while the popup chart can stream a
                # richer per-source series on demand.  Failures are
                # isolated so a source-history write error doesn't
                # nuke the rank-history append we just did.
                try:
                    _source_history.append_snapshot(contract_payload)
                except Exception as inner_exc:  # noqa: BLE001
                    log.warning(
                        "source_history: append failed: %s", inner_exc,
                    )
            stamped = _rank_history.stamp_contract_with_history(contract_payload)
            if stamped:
                log.info("rank_history: stamped %d rows with history series", stamped)
        except Exception as exc:  # noqa: BLE001
            # Non-fatal: a history log failure must NOT break the
            # contract response.  The glyph degrades gracefully when
            # rankHistory is absent.
            log.warning("rank_history: append/stamp failed: %s", exc)
        # Tag the contract with the league + scoring profile it was
        # built for.  Two different roles:
        #
        #   * ``meta.leagueKey`` — which specific league's Sleeper
        #     block (teams, rosters, ownerIds) is stamped here.
        #     Team-requiring endpoints (/api/terminal, /api/trade/*)
        #     reject requests for other leagues with 503.
        #   * ``meta.scoringProfile`` — which scoring rules produced
        #     these rankings.  Rankings endpoints (/api/data,
        #     /api/rankings/overrides) serve the same rankings to
        #     any league that shares the profile, and only 503 when
        #     profiles actually differ.
        #
        # This split is the core of the "scoring drives rankings,
        # league drives context" architecture — see CLAUDE.md.
        try:
            _default_cfg = _league_registry.get_default_league()
            if _default_cfg and isinstance(contract_payload, dict):
                meta_block = contract_payload.setdefault("meta", {})
                meta_block["leagueKey"] = _default_cfg.key
                meta_block["scoringProfile"] = _default_cfg.scoring_profile
        except Exception:  # noqa: BLE001
            pass
        latest_contract_data = contract_payload
        contract_health = contract_report

        # Post-scrape overlay warm — for every ACTIVE league other
        # than the one the scraper just built for, force-refresh the
        # Sleeper overlay so the first user request after a scrape
        # hits a warm 15-min cache instead of round-tripping to
        # Sleeper.  Non-fatal: any failure is logged + skipped.
        try:
            default_cfg = _league_registry.get_default_league()
            loaded_sleeper = contract_payload.get("sleeper") or {}
            id_map = loaded_sleeper.get("idToPlayer") if isinstance(loaded_sleeper, dict) else {}
            warmed: list[str] = []
            warm_failed: list[str] = []
            for cfg in _league_registry.active_leagues():
                if default_cfg and cfg.key == default_cfg.key:
                    continue
                try:
                    overlay = _sleeper_overlay.fetch_sleeper_overlay(
                        sleeper_league_id=cfg.sleeper_league_id,
                        id_to_player=id_map if isinstance(id_map, dict) else {},
                        force_refresh=True,
                    )
                    if overlay and overlay.get("teams"):
                        warmed.append(cfg.key)
                    else:
                        warm_failed.append(cfg.key)
                except Exception as inner:  # noqa: BLE001
                    log.warning(
                        "post-scrape overlay warm failed for %s: %s",
                        cfg.key, inner,
                    )
                    warm_failed.append(cfg.key)
            if warmed or warm_failed:
                log.info(
                    "post-scrape overlay warm: %d warmed, %d failed (warmed=%s failed=%s)",
                    len(warmed), len(warm_failed), warmed, warm_failed,
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("post-scrape overlay warm pass failed: %s", exc)

        if not contract_report.get("ok"):
            log.error(
                "API contract validation failed: %s",
                "; ".join((contract_report.get("errors") or [])[:5]),
            )

        raw = json.dumps(contract_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        latest_data_bytes = raw
        latest_data_gzip_bytes = gzip.compress(raw, compresslevel=5)
        latest_data_etag = hashlib.sha1(raw).hexdigest()

        # Runtime payload: keep canonical top-level data shape used by the live UI,
        # but remove heavyweight contract array duplication to reduce parse/transfer cost.
        runtime_payload = dict(contract_payload)
        runtime_payload.pop("playersArray", None)
        runtime_payload["payloadView"] = "runtime"
        runtime_raw = json.dumps(runtime_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        latest_runtime_data = runtime_payload
        latest_runtime_data_bytes = runtime_raw
        latest_runtime_data_gzip_bytes = gzip.compress(runtime_raw, compresslevel=5)
        latest_runtime_data_etag = hashlib.sha1(runtime_raw).hexdigest()

        # Startup payload: same contract shape, but strips heavyweight fields
        # not needed for first screen render so first data-visible is faster.
        startup_payload = build_api_startup_payload(runtime_payload)
        startup_raw = json.dumps(startup_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        latest_startup_data = startup_payload
        latest_startup_data_bytes = startup_raw
        latest_startup_data_gzip_bytes = gzip.compress(startup_raw, compresslevel=5)
        latest_startup_data_etag = hashlib.sha1(startup_raw).hexdigest()
    except Exception as e:
        contract_health = {
            "ok": False,
            "status": "invalid",
            "errors": [f"contract build failed: {type(e).__name__}: {e}"],
            "warnings": [],
            "errorCount": 1,
            "warningCount": 0,
            "checkedAt": _utc_now_iso(),
            "contractVersion": API_DATA_CONTRACT_VERSION,
            "playerCount": 0,
        }
        log.error(f"Failed to pre-serialize latest payload: {e}")


def load_from_disk() -> dict | None:
    """Load most recent dynasty_data_*.json from data/ directory."""
    json_files = sorted(DATA_DIR.glob("dynasty_data_*.json"), reverse=True)
    if not json_files:
        # Also check base dir for existing files from standalone scraper runs
        json_files = sorted(BASE_DIR.glob("dynasty_data_*.json"), reverse=True)
    if json_files:
        try:
            latest_path = json_files[0]
            with open(latest_path) as f:
                data = json.load(f)
            _set_latest_data_source("disk_cache", str(latest_path))
            log.info(f"Loaded cached data from {latest_path.name} "
                     f"({len(data.get('players', {}))} players)")
            return data
        except Exception as e:
            log.error(f"Failed to load {json_files[0]}: {e}")
    return None


def _latest_file(directory: Path, pattern: str) -> Path | None:
    if not directory.exists():
        return None
    files = sorted(directory.glob(pattern), reverse=True)
    return files[0] if files else None


def _load_json_file(path: Path | None) -> dict | None:
    if path is None or not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.error(f"Failed to load scaffold json {path}: {e}")
        return None


async def run_scraper(trigger: str = "manual") -> dict | None:
    """
    Import and run the scraper, returning the dashboard JSON dict.
    Runs in the same event loop as the server.
    """
    global latest_data
    _reconcile_orphaned_running_state()
    if scrape_run_lock.locked():
        _record_scrape_event(
            "scrape_rejected_already_running",
            level="warning",
            message="run_scraper called while lock already held",
        )
        return latest_data

    async with scrape_run_lock:
        start = time.time()
        worker_id = _start_scrape_run(trigger=trigger)
        log.info("=" * 60)
        log.info("SCRAPE STARTING")
        log.info("=" * 60)

        try:
            _update_scrape_progress(
                step="bootstrap",
                source="import_scraper",
                step_index=1,
                step_total=4,
                event="phase_start",
                message="Importing scraper module",
            )

            # Import the scraper module from its exact file path
            # (importlib handles spaces in directory names that normal import can't)
            import importlib.util

            spec = importlib.util.spec_from_file_location("Dynasty_Scraper", str(SCRAPER_PATH))
            scraper = importlib.util.module_from_spec(spec)
            sys.modules["Dynasty_Scraper"] = scraper
            spec.loader.exec_module(scraper)

            # Override SCRIPT_DIR so output goes to our data/ folder
            scraper.SCRIPT_DIR = str(DATA_DIR)

            _update_scrape_progress(
                step="scrape",
                source="Dynasty Scraper.py",
                step_index=2,
                step_total=4,
                event="phase_start",
                message="Executing scraper.run()",
            )

            progress_callback = _build_scrape_progress_callback(worker_id)

            # Top-level run timeout guard so a wedged scraper cannot hold running=True forever.
            result = await asyncio.wait_for(
                scraper.run(progress_callback=progress_callback),
                timeout=SCRAPE_RUN_TIMEOUT_SECONDS,
            )

            _update_scrape_progress(
                step="validate",
                source="result_payload",
                step_index=3,
                step_total=4,
                event="phase_start",
                message="Validating scraper output",
            )

            if not result or not result.get("players"):
                raise RuntimeError("Scraper returned empty result")

            # Mirror fresh site_raw CSVs from the scraper's DATA_DIR output
            # path (data/exports/latest/site_raw/) back to the repo's
            # tracked CSVs/site_raw/ directory so that the CSV
            # enrichment in data_contract.py (which reads relative to repo
            # root) sees up-to-date values.  Without this, enrichment reads
            # permanently-stale CSVs from git history.  Only copies KTC and
            # IDPTradeCalc — DLF is a rank-signal file with a different
            # format maintained separately.
            try:
                import shutil as _sh
                src_raw = DATA_DIR / "exports" / "latest" / "site_raw"
                dst_raw = BASE_DIR / "CSVs" / "site_raw"
                if src_raw.exists() and dst_raw.exists():
                    for fname in ("ktc.csv", "idpTradeCalc.csv"):
                        src_file = src_raw / fname
                        dst_file = dst_raw / fname
                        if src_file.exists():
                            _sh.copy2(src_file, dst_file)
                    # Also mirror the full dynasty_data JSON so other
                    # consumers (tests, CLI tools) see the fresh file.
                    date_str = str(result.get("date") or "")
                    if date_str:
                        src_json = DATA_DIR / "exports" / "latest" / f"dynasty_data_{date_str}.json"
                        dst_json = BASE_DIR / "exports" / "latest" / f"dynasty_data_{date_str}.json"
                        if src_json.exists():
                            _sh.copy2(src_json, dst_json)
            except Exception as _mirror_err:
                log.warning(f"Post-scrape CSV mirror failed: {_mirror_err}")

            # Refresh Dynasty Nerds SF-TEP rankings.  The DN board is
            # inlined in the page HTML as a ``window.DR_DATA`` JS
            # constant — no Playwright required — so we run the plain
            # ``scripts/fetch_dynasty_nerds.py`` helper inline on every
            # scheduled scrape cycle.  Failure is logged and ignored so
            # a transient network error cannot fail the entire scrape.
            try:
                from scripts import fetch_dynasty_nerds as _dn_fetch
                rc = _dn_fetch.main(["--mirror-data-dir"])
                if rc == 2:
                    # Schema / row-count regression — surface loudly as
                    # a structured scrape event so /api/status shows the
                    # failure instead of burying it as a log line.
                    _record_scrape_event(
                        "dynasty_nerds_schema_regression",
                        level="error",
                        message=(
                            "Dynasty Nerds fetch exit=2 "
                            "(DR_DATA shape changed or rows below floor)"
                        ),
                        exit_code=rc,
                    )
                elif rc != 0:
                    _record_scrape_event(
                        "dynasty_nerds_fetch_failed",
                        level="warning",
                        message=f"Dynasty Nerds fetch returned exit={rc}",
                        exit_code=rc,
                    )
            except Exception as _dn_err:
                _record_scrape_event(
                    "dynasty_nerds_fetch_exception",
                    level="warning",
                    message=f"Dynasty Nerds fetch raised: {_dn_err}",
                )

            # Refresh FantasyPros Dynasty Superflex (offense) rankings.
            # The dynasty-superflex page inlines an ``ecrData = {...}``
            # JS constant, so a plain ``requests.get`` with a browser
            # UA returns the full payload.  The fetch script extracts
            # QB/RB/WR/TE consensus ECR ranks and writes a rank-signal CSV.
            try:
                from scripts import fetch_fantasypros_offense as _fpoff_fetch
                rc = _fpoff_fetch.main(["--mirror-data-dir"])
                if rc == 2:
                    _record_scrape_event(
                        "fantasypros_offense_schema_regression",
                        level="error",
                        message=(
                            "FantasyPros Offense fetch exit=2 "
                            "(ecrData shape changed or rows below floor)"
                        ),
                        exit_code=rc,
                    )
                elif rc != 0:
                    _record_scrape_event(
                        "fantasypros_offense_fetch_failed",
                        level="warning",
                        message=f"FantasyPros Offense fetch returned exit={rc}",
                        exit_code=rc,
                    )
            except Exception as _fpoff_err:
                _record_scrape_event(
                    "fantasypros_offense_fetch_exception",
                    level="warning",
                    message=f"FantasyPros Offense fetch raised: {_fpoff_err}",
                )

            # Refresh FantasyPros Dynasty IDP rankings.  The combined
            # + DL/LB/DB pages inline their rankings in a JS
            # ``ecrData = {...}`` constant, so a plain ``requests.get``
            # with a browser UA returns the full payload.  The fetch
            # script derives per-player effective overall ranks via
            # anchor curves fit on the combined/individual overlap
            # and writes a rank-signal CSV.
            try:
                from scripts import fetch_fantasypros_idp as _fp_fetch
                rc = _fp_fetch.main(["--mirror-data-dir"])
                if rc == 2:
                    _record_scrape_event(
                        "fantasypros_idp_schema_regression",
                        level="error",
                        message=(
                            "FantasyPros IDP fetch exit=2 "
                            "(ecrData shape changed or rows below floor)"
                        ),
                        exit_code=rc,
                    )
                elif rc != 0:
                    _record_scrape_event(
                        "fantasypros_idp_fetch_failed",
                        level="warning",
                        message=f"FantasyPros IDP fetch returned exit={rc}",
                        exit_code=rc,
                    )
            except Exception as _fp_err:
                _record_scrape_event(
                    "fantasypros_idp_fetch_exception",
                    level="warning",
                    message=f"FantasyPros IDP fetch raised: {_fp_err}",
                )

            # Refresh The IDP Show (Adamidp) rankings.  The fetcher
            # reads cookies from ``idpshow_session.json`` at the repo
            # root — if the file is missing (e.g. fresh deploy before
            # the operator has pasted cookies) we skip silently.
            # When cookies have expired the fetcher returns non-zero
            # and we surface it as a warning so the stale-data banner
            # knows to prompt a cookie refresh.
            _idpshow_session = BASE_DIR / "idpshow_session.json"
            if _idpshow_session.exists():
                try:
                    from scripts import fetch_idpshow as _idpshow_fetch
                    rc = _idpshow_fetch.main([])
                    if rc != 0:
                        _record_scrape_event(
                            "idpshow_fetch_failed",
                            level="warning",
                            message=(
                                f"IDP Show fetch returned exit={rc}.  "
                                f"Session cookies may have expired — "
                                f"refresh idpshow_session.json."
                            ),
                            exit_code=rc,
                        )
                except Exception as _idpshow_err:
                    _record_scrape_event(
                        "idpshow_fetch_exception",
                        level="warning",
                        message=f"IDP Show fetch raised: {_idpshow_err}",
                    )
            else:
                log.info(
                    "IDP Show skipped — idpshow_session.json missing; "
                    "operator must paste cookies into that file to enable."
                )

            _update_scrape_progress(
                step="publish",
                source="api_cache",
                step_index=4,
                step_total=4,
                event="phase_start",
                message="Publishing data to in-memory cache",
            )

            elapsed = time.time() - start
            player_count = len(result.get("players", {}))
            site_count = len([s for s in result.get("sites", []) if s.get("playerCount", 0) > 0])
            total_sites = len(result.get("sites", []))

            # R-3: Block partial scrape promotion — don't overwrite good data
            # with degraded data when fewer than half the sites returned results.
            if total_sites > 0 and site_count < total_sites / 2:
                log.warning(
                    f"PARTIAL SCRAPE NOT PROMOTED — {site_count}/{total_sites} sites, "
                    f"{player_count} players, {elapsed:.1f}s. Keeping last-known-good data."
                )
                send_alert(
                    f"PARTIAL SCRAPE NOT PROMOTED: only {site_count}/{total_sites} sites",
                    (
                        f"Players: {player_count}\n"
                        f"Sites with data: {site_count}/{total_sites}\n"
                        f"Duration: {elapsed:.1f}s\n\n"
                        "Partial scrape data was NOT promoted to production.\n"
                        "The server continues serving last-known-good data.\n"
                        "Some sites may be down or blocking the scraper."
                    ),
                )
                _mark_scrape_success(elapsed, player_count, site_count, total_sites)
                _record_scrape_event(
                    "partial_scrape_blocked",
                    level="warning",
                    message=f"Only {site_count}/{total_sites} sites — data not promoted",
                    site_count=site_count,
                    total_sites=total_sites,
                )
                return latest_data  # Return existing data, not the partial result

            # R-10: Disk space guard — skip disk write if space is critically low.
            disk_ok, free_mb = _check_disk_space()
            if not disk_ok:
                log.error(
                    f"DISK SPACE LOW — only {free_mb}MB free (minimum {DISK_SPACE_MIN_MB}MB). "
                    "Scrape data will be served from memory but NOT written to disk."
                )
                send_alert(
                    f"DISK SPACE CRITICALLY LOW: {free_mb}MB free",
                    (
                        f"Available disk space: {free_mb}MB\n"
                        f"Minimum required: {DISK_SPACE_MIN_MB}MB\n\n"
                        "Scrape data was loaded into memory but NOT written to disk.\n"
                        "Please free disk space on the server."
                    ),
                )

            latest_data = result
            result_date = str(result.get("date") or "").strip()
            source_path = ""
            if result_date:
                candidate = DATA_DIR / f"dynasty_data_{result_date}.json"
                if candidate.exists():
                    source_path = str(candidate)
            _set_latest_data_source("scrape_run", source_path)
            # Fresh scrape promotion — rank-history log gets a new
            # "today" entry.  Startup priming from cached disk data
            # (``_prime_latest_payload`` called in the lifespan hook)
            # leaves is_fresh_scrape=False so the history log stays
            # read-only until a real scrape lands.
            _prime_latest_payload(result, is_fresh_scrape=True)

            _mark_scrape_success(elapsed, player_count, site_count, total_sites)

            log.info(
                f"SCRAPE COMPLETE — {player_count} players, "
                f"{site_count}/{total_sites} sites, {elapsed:.1f}s"
            )

            return result
        except Exception as e:
            elapsed = time.time() - start
            _mark_scrape_failure(e, elapsed)
            error_trace = traceback.format_exc()
            log.error(f"SCRAPE FAILED after {elapsed:.1f}s: {e}")
            log.error(error_trace)
            send_alert(
                f"Scrape failed: {type(e).__name__}",
                f"Error: {e}\n\nDuration: {elapsed:.1f}s\n\n{error_trace[-1500:]}",
            )
            return None
        finally:
            _finalize_scrape_run(worker_id)


def check_uptime_once() -> tuple[bool, str | None, int | None]:
    """Run one synchronous uptime probe against the configured URL."""
    if not UPTIME_CHECK_URL:
        return False, "UPTIME_CHECK_URL is empty", None

    req = urllib.request.Request(
        UPTIME_CHECK_URL,
        headers={"User-Agent": "dynasty-uptime-watchdog/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=UPTIME_CHECK_TIMEOUT_SEC) as resp:
            status_code = int(getattr(resp, "status", 200))
            if 200 <= status_code < 400:
                return True, None, status_code
            return False, f"Unexpected status code {status_code}", status_code
    except urllib.error.HTTPError as e:
        return False, f"HTTPError {e.code}", int(e.code)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}", None


async def uptime_watchdog_loop():
    """Periodic external uptime checks + alerting."""
    if not UPTIME_CHECK_ENABLED:
        log.info("Uptime watchdog disabled (UPTIME_CHECK_ENABLED=false)")
        return
    if not UPTIME_CHECK_URL:
        log.warning("Uptime watchdog enabled but UPTIME_CHECK_URL is empty; watchdog disabled.")
        uptime_status["enabled"] = False
        return

    log.info(
        "Uptime watchdog enabled — url=%s interval=%ss threshold=%s",
        UPTIME_CHECK_URL,
        UPTIME_CHECK_INTERVAL_SEC,
        UPTIME_ALERT_FAIL_THRESHOLD,
    )
    while True:
        now_iso = datetime.now(timezone.utc).isoformat()
        ok, error, status_code = await asyncio.to_thread(check_uptime_once)
        uptime_status["last_check"] = now_iso
        uptime_status["last_http_status"] = status_code

        if ok:
            was_down = uptime_status["consecutive_failures"] >= UPTIME_ALERT_FAIL_THRESHOLD
            uptime_status["consecutive_failures"] = 0
            uptime_status["last_ok"] = now_iso
            uptime_status["last_error"] = None
            if was_down:
                send_alert(
                    "Uptime recovered",
                    f"Recovered successfully.\nURL: {UPTIME_CHECK_URL}\nChecked at: {now_iso}\nStatus: {status_code}",
                )
        else:
            uptime_status["consecutive_failures"] += 1
            uptime_status["last_error"] = error
            failures = uptime_status["consecutive_failures"]
            log.warning("Uptime check failed (%s/%s): %s", failures, UPTIME_ALERT_FAIL_THRESHOLD, error)
            if failures >= UPTIME_ALERT_FAIL_THRESHOLD:
                send_alert(
                    f"Uptime check failing ({failures} consecutive)",
                    (
                        f"URL: {UPTIME_CHECK_URL}\n"
                        f"Consecutive failures: {failures}\n"
                        f"Last status code: {status_code}\n"
                        f"Last error: {error}\n"
                        f"Checked at: {now_iso}"
                    ),
                )

        await asyncio.sleep(max(30, UPTIME_CHECK_INTERVAL_SEC))


# ── SCHEDULER ───────────────────────────────────────────────────────────
async def scheduled_scrape():
    """Called by the background scheduler every SCRAPE_INTERVAL_HOURS."""
    log.info(f"Scheduled scrape triggered (every {SCRAPE_INTERVAL_HOURS}h)")
    await run_scraper(trigger="scheduled")
    # Update next scrape time
    from datetime import timedelta
    scrape_status["next_scrape"] = (
        datetime.now(timezone.utc) + timedelta(hours=SCRAPE_INTERVAL_HOURS)
    ).isoformat()


async def schedule_loop():
    """Simple async loop that runs the scraper on an interval."""
    from datetime import timedelta
    while True:
        scrape_status["next_scrape"] = (
            datetime.now(timezone.utc) + timedelta(hours=SCRAPE_INTERVAL_HOURS)
        ).isoformat()
        await asyncio.sleep(SCRAPE_INTERVAL_HOURS * 3600)
        await scheduled_scrape()



# ── APP LIFECYCLE ───────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: load cached data + kick off first scrape + start scheduler."""
    global latest_data, _startup_checks_summary

    _metrics["server_start_time"] = _utc_now_iso()

    # 0. Run startup validation FIRST so misconfiguration surfaces
    # before any heavy work.  Never raises — logs individual check
    # results and stores the summary for /api/health.
    try:
        from src.api import startup_validation as _sv
        _startup_checks = _sv.run_all()
        _startup_checks_summary = _sv.summary(_startup_checks)
    except Exception as exc:  # noqa: BLE001
        log.error("startup_validation crashed: %s", exc)
        _startup_checks_summary = {
            "error": str(exc), "total": 0, "ok": 0, "failed": 1, "fatal": 0,
        }

    # 1. Load cached data immediately so the dashboard is usable right away
    latest_data = load_from_disk()
    _prime_latest_payload(latest_data)
    if latest_data:
        log.info("Dashboard ready with cached data")
    else:
        log.info("No cached data found — dashboard will show empty until first scrape completes")

    # 1b. Hydrate persisted auth sessions so users don't have to re-login
    # on every deploy.  Any failure here falls through to empty in-memory
    # sessions — the existing pre-persistence behavior — so a broken
    # session store can never brick auth entirely.
    try:
        from src.api import session_store as _ss
        hydrated = _ss.hydrate(allowlist=PRIVATE_APP_ALLOWED_USERNAMES)
        auth_sessions.update(hydrated)
        log.info("session_store: hydrated %d sessions from disk", len(hydrated))
    except Exception as exc:  # noqa: BLE001
        log.warning("session_store hydrate on startup failed: %s", exc)

    # 2. Start first scrape in background (don't block startup)
    async def initial_scrape():
        await asyncio.sleep(3)  # small delay to let server finish booting
        await run_scraper(trigger="startup")

    scrape_task = asyncio.create_task(initial_scrape())

    # 3. Start the recurring schedule
    scheduler_task = asyncio.create_task(schedule_loop())
    uptime_task = asyncio.create_task(uptime_watchdog_loop())
    # Public league snapshot warmup — kicks a background rebuild if
    # no persisted snapshot was loaded at boot.  Name is resolved at
    # call time (Python late-binding), so the fact that the function
    # is defined further down in the module is fine.
    try:
        _warmup_public_snapshot()
    except Exception as exc:  # noqa: BLE001
        log.warning("public_league warmup failed at startup: %s", exc)

    # Per-source value history backfill — if the snapshot log is
    # missing or empty, mine the historical ``data/dynasty_data_*.json``
    # exports so the PlayerPopup chart has ~28 days of per-source
    # history on day one.  Skipped when the log already has entries
    # (idempotent, safe to re-run).  Runs sync at boot because it's
    # fast (<2s) and the data is needed before the first
    # /api/data/player-source-history request lands.
    try:
        history_path = _source_history.HISTORY_PATH
        needs_backfill = not history_path.exists() or history_path.stat().st_size == 0
        if needs_backfill:
            exports = sorted((DATA_DIR).glob("dynasty_data_*.json"))
            if exports:
                written = _source_history.backfill_from_exports(exports)
                log.info("source_history: backfilled %d snapshots from %d exports",
                         written, len(exports))
    except Exception as exc:  # noqa: BLE001
        log.warning("source_history: startup backfill failed: %s", exc)

    log.info(f"Server started — scraping every {SCRAPE_INTERVAL_HOURS}h")
    log.info("Frontend: Next.js at %s", FRONTEND_URL)
    log.info(f"Dashboard: http://localhost:{PORT}")

    yield  # app is running

    # Cleanup
    scrape_task.cancel()
    scheduler_task.cancel()
    uptime_task.cancel()
    log.info("Server shutting down")


# ── FASTAPI APP ─────────────────────────────────────────────────────────
app = FastAPI(
    title="Dynasty Trade Calculator",
    lifespan=lifespan,
)
app.add_middleware(GZipMiddleware, minimum_size=1024)

# Global exception handler — catches ANY unhandled exception from
# handlers, middleware, or dependency resolution.  Returns the
# standard error-envelope + logs with full context (requestId,
# path, method, IP, traceback).  Installed before any other
# middleware registers so it wraps everything.
from src.api.error_responses import install_exception_handler as _install_exc_handler  # noqa: E402
_install_exc_handler(app)


@app.middleware("http")
async def _count_requests(request: Request, call_next):
    """R-9: Count all HTTP requests for metrics."""
    _metrics["request_count"] = _metrics.get("request_count", 0) + 1
    return await call_next(request)


# Paths under /api/* that do NOT require an authenticated session.
# Anything else gets 401'd by ``_private_api_gate`` below.  Closes
# the scrape risk: without this gate, ``curl /api/data`` from a
# stranger returns the full private rankings contract.
_PUBLIC_API_EXACT = frozenset({
    "/api/health",
    "/api/status",
    "/api/uptime",
    "/api/metrics",
    "/api/leagues",
    "/api/rankings/sources",
    "/api/auth/status",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/sleeper-login",
    "/api/scaffold/status",
    # /league page is a public view — its draft-capital tab reads
    # this endpoint.  Payload is public Sleeper data (team names,
    # pick dollar values, owners) already viewable on Sleeper; no
    # private rankings / user state is leaked here.
    "/api/draft-capital",
})
# Endpoints that handle their own auth (bearer token, etc.) — the
# session-cookie middleware must skip them so the endpoint's own
# check runs.
_SELF_AUTHED_API_EXACT = frozenset({
    "/api/signal-alerts/run",
    # E2E test-session bootstrap — handles its own bearer-token auth.
    # Returns 404 unless E2E_TEST_MODE + matching bearer secret are
    # both set, so having it bypass the session gate doesn't leak
    # anything in prod (env vars aren't set there).
    "/api/test/create-session",
})
_PUBLIC_API_PREFIXES = (
    "/api/public/league",
)


def _is_public_api_path(path: str) -> bool:
    if path in _PUBLIC_API_EXACT:
        return True
    if path in _SELF_AUTHED_API_EXACT:
        return True
    for prefix in _PUBLIC_API_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


@app.middleware("http")
async def _private_api_gate(request: Request, call_next):
    """401 any /api/* call without a session, except the public
    allowlist.  Page routes still redirect via
    ``_require_auth_or_redirect``; static/_next assets aren't
    touched.

    Also applies rate limiting to public endpoints only — signed-
    in users on private endpoints aren't subject to the limit
    (they already paid the auth cost, and it's just Jason anyway).
    """
    path = request.url.path or ""
    # Rate limit public endpoints to protect against scraper abuse.
    if path.startswith("/api/") and _is_public_api_path(path):
        client_ip = _client_ip_from_request(request)
        try:
            from src.api import rate_limit as _rl
            limited, retry_after = _rl.should_rate_limit(client_ip)
        except Exception:  # noqa: BLE001 — never let rate-limiter break the gate
            limited, retry_after = False, 0
        if limited:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limited",
                    "message": "Too many requests — slow down.",
                    "retryAfterSeconds": retry_after,
                },
                headers={
                    "Cache-Control": "no-store",
                    "Retry-After": str(retry_after),
                },
            )
    if path.startswith("/api/") and not _is_public_api_path(path):
        if not _is_authenticated(request):
            return JSONResponse(
                status_code=401,
                content={"error": "auth_required", "message": "Sign-in required."},
                headers={"Cache-Control": "no-store"},
            )
    return await call_next(request)


@app.middleware("http")
async def _request_context_middleware(request: Request, call_next):
    """Generate + propagate a per-request correlation ID.

    Registered AFTER ``_private_api_gate`` so it wraps the gate —
    every response (including 401/429 from the gate) gets an
    ``X-Request-Id`` header + the ContextVar is set for any log
    lines emitted during request handling.

    Accepts an incoming ``X-Request-Id`` header (e.g. from nginx
    or an uptime monitor) when present + sane (1-64 chars);
    otherwise mints a fresh token-urlsafe 12-char ID.
    """
    from src.utils import request_context as _rc
    incoming = str(request.headers.get("x-request-id") or "").strip()
    rid = incoming if (1 <= len(incoming) <= 64) else _rc.new_request_id()
    token = _rc.set_request_id(rid)
    try:
        response = await call_next(request)
    finally:
        _rc.reset_request_id(token)
    try:
        response.headers["X-Request-Id"] = rid
    except Exception:  # noqa: BLE001 — some response types reject mutations
        pass
    return response


def _client_ip_from_request(request: Request) -> str:
    """Prefer ``X-Forwarded-For`` (nginx sets it for us in prod);
    fall back to ``request.client.host``."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        # First entry in the chain is the original client.
        first = xff.split(",")[0].strip()
        if first:
            return first
    client = request.client
    return client.host if client else ""

def _proxy_next(path: str) -> tuple[Response | None, str | None]:
    """
    Proxy frontend routes to local Next.js dev/prod server when available.
    Returns (response, error_message). response is None when proxy is unavailable.
    """
    try:
        target = f"{FRONTEND_URL}{path if path.startswith('/') else '/' + path}"
        req = urllib.request.Request(
            target,
            headers={"User-Agent": "dynasty-server-next-proxy/1.0"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            body = resp.read()
            headers = {}
            ctype = resp.headers.get("Content-Type")
            if ctype:
                headers["content-type"] = ctype
            cache_control = resp.headers.get("Cache-Control")
            if cache_control:
                headers["cache-control"] = cache_control
            return Response(content=body, status_code=getattr(resp, "status", 200), headers=headers), None
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = b""
        headers = {}
        ctype = e.headers.get("Content-Type") if e.headers else None
        if ctype:
            headers["content-type"] = ctype
        return Response(content=body, status_code=e.code, headers=headers), f"HTTPError {e.code}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# ── API ROUTES ──────────────────────────────────────────────────────────
@app.get("/api/data")
async def get_data(request: Request):
    """Return latest normalized/validated data contract JSON.

    Optional ``?leagueKey=...`` validates against the league registry.

    **Rankings are keyed by scoring profile, not by league.**  When
    two leagues share a profile, they share the rankings pipeline's
    output — the ``players`` / ``playersArray`` / ``sources`` blocks
    are identical and we serve them to any caller whose league
    resolves to the same profile.  Only the league-specific
    ``sleeper`` block (teams, rosters, owners) is per-league; when a
    different league is requested and we don't have that league's
    sleeper data loaded, the block is returned as ``None`` and
    ``meta.sleeperDataReady=false`` tells the client to show
    "no roster data yet" rather than rendering the default league's
    teams under the wrong name.

    503 ``data_not_ready`` only fires when the scoring profiles
    genuinely differ — i.e. the rankings themselves can't be reused.
    """
    # League validation comes first so a stale leagueKey returns 400
    # before we bother assembling the payload.  Skip the loaded-
    # contract check here and enforce below so the 503 path can
    # include the resolved league key in the response.
    try:
        league_cfg = _resolve_league_for_request(request)
    except LeagueResolutionError as err:
        return err.json_response()

    if latest_contract_data:
        loaded_meta = (
            latest_contract_data.get("meta") or {}
            if isinstance(latest_contract_data, dict) else {}
        )
        loaded_league = str(loaded_meta.get("leagueKey") or "")
        loaded_profile = str(loaded_meta.get("scoringProfile") or "")
        sleeper_matches = bool(loaded_league) and loaded_league == league_cfg.key

        # Scoring-profile mismatch → genuinely different data; 503.
        # Missing loaded_profile means we're running a contract built
        # before this refactor; treat it as if profiles match (the
        # rankings are global), and surface sleeper_matches only.
        if loaded_profile and loaded_profile != league_cfg.scoring_profile:
            return JSONResponse(
                status_code=503,
                content={
                    "error": "data_not_ready",
                    "message": (
                        f"League {league_cfg.key!r} uses scoring profile "
                        f"{league_cfg.scoring_profile!r}, but the loaded "
                        f"contract is {loaded_profile!r}.  Rankings are "
                        "not compatible."
                    ),
                    "leagueKey": league_cfg.key,
                    "scoringProfile": league_cfg.scoring_profile,
                },
            )

        view = (request.query_params.get("view") or "").strip().lower()
        startup_view = view in {"startup", "boot", "initial"}
        runtime_view = view in {"app", "runtime", "lite"}
        compact_view = view in {"compact", "slim"}

        payload_bytes = latest_data_bytes
        payload_gzip_bytes = latest_data_gzip_bytes
        payload_etag = latest_data_etag
        payload_obj = latest_contract_data
        payload_view_name = "full"

        if startup_view and latest_startup_data is not None:
            payload_bytes = latest_startup_data_bytes
            payload_gzip_bytes = latest_startup_data_gzip_bytes
            payload_etag = latest_startup_data_etag
            payload_obj = latest_startup_data
            payload_view_name = "startup"
        elif runtime_view and latest_runtime_data is not None:
            payload_bytes = latest_runtime_data_bytes
            payload_gzip_bytes = latest_runtime_data_gzip_bytes
            payload_etag = latest_runtime_data_etag
            payload_obj = latest_runtime_data
            payload_view_name = "runtime"
        elif compact_view and latest_contract_data is not None:
            # Mobile / slow-network view — prune ~20 audit + trust
            # fields.  ~90% byte reduction.  Additive: a frontend
            # that doesn't know to ignore pruned fields breaks only
            # if it READS one of them, which the compact shape test
            # pins against.
            from src.api.compact_view import compact_contract
            compact_obj = compact_contract(latest_contract_data)
            import json as _json
            payload_bytes = _json.dumps(compact_obj).encode("utf-8")
            payload_gzip_bytes = None  # regenerate-on-demand (no cached gzip)
            payload_etag = None
            payload_obj = compact_obj
            payload_view_name = "compact"

        headers = {
            # Keep dashboard startup fast with a short cache window + conditional revalidation.
            "Cache-Control": "public, max-age=30, stale-while-revalidate=300",
            "X-Payload-View": payload_view_name,
        }

        # Cross-league request for a same-scoring-profile league —
        # serve the shared rankings, then try to splice in a live
        # Sleeper overlay for the requested league.  The overlay
        # fetches rosters + trades + metadata from Sleeper on
        # demand (cached 15 min) so the terminal, /trades page,
        # team pickers, etc. work without running the full
        # scraper per league.
        if not sleeper_matches:
            scrubbed = dict(payload_obj) if isinstance(payload_obj, dict) else {}
            # Re-use the NFL-wide Sleeper-ID → display-name map from
            # the currently-loaded contract (League A's scrape) so
            # we don't have to refetch /v1/players/nfl (~5MB) for
            # every overlay.  The map is NFL-wide, not league-scoped,
            # so it's safe across leagues.
            loaded_sleeper = (
                (latest_contract_data or {}).get("sleeper") or {}
                if isinstance(latest_contract_data, dict) else {}
            )
            id_to_player = loaded_sleeper.get("idToPlayer") or {}
            try:
                overlay = await run_in_threadpool(
                    _sleeper_overlay.fetch_sleeper_overlay,
                    sleeper_league_id=league_cfg.sleeper_league_id,
                    id_to_player=id_to_player if isinstance(id_to_player, dict) else {},
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "sleeper_overlay fetch failed for %s: %s",
                    league_cfg.key, exc,
                )
                overlay = None

            meta = dict(scrubbed.get("meta") or {})
            meta["leagueKey"] = league_cfg.key
            meta["scoringProfile"] = league_cfg.scoring_profile
            meta["sleeperLoadedLeagueKey"] = loaded_league or None

            if overlay and overlay.get("teams"):
                # Carry forward the NFL-wide maps from the loaded
                # contract — the overlay is lean + doesn't refetch
                # them.  These keys power frontend lookups that
                # aren't league-scoped (positions, IDs, etc).
                overlay_full = {
                    **{
                        k: loaded_sleeper.get(k)
                        for k in ("positions", "playerIds", "idToPlayer",
                                  "scoringSettings", "rosterPositions",
                                  "leagueSettings")
                        if k in loaded_sleeper
                    },
                    **overlay,
                }
                scrubbed["sleeper"] = overlay_full
                meta["sleeperDataReady"] = True
                meta["sleeperSource"] = "overlay"
                headers["X-Payload-View"] = f"{payload_view_name}-cross-league-overlay"
            else:
                # Overlay unavailable (Sleeper down, empty league,
                # etc.) — null the sleeper block so the UI falls
                # back to the data-not-ready state.
                scrubbed["sleeper"] = None
                meta["sleeperDataReady"] = False
                headers["X-Payload-View"] = f"{payload_view_name}-cross-league"
            scrubbed["meta"] = meta
            return JSONResponse(content=scrubbed, headers=headers)

        if payload_etag:
            headers["ETag"] = payload_etag
            incoming = request.headers.get("if-none-match", "").strip('"')
            if incoming and incoming == payload_etag:
                return Response(status_code=304, headers=headers)

        accept_encoding = (request.headers.get("accept-encoding") or "").lower()
        if "gzip" in accept_encoding and payload_gzip_bytes:
            headers["Content-Encoding"] = "gzip"
            return Response(content=payload_gzip_bytes, media_type="application/json", headers=headers)
        if payload_bytes:
            return Response(content=payload_bytes, media_type="application/json", headers=headers)
        return JSONResponse(content=payload_obj, headers=headers)
    return JSONResponse(
        status_code=503,
        content={"error": "No data available yet. First scrape may still be running."}
    )


@app.get("/api/dynasty-data")
async def get_dynasty_data_alias(request: Request):
    """Compatibility alias for frontend consumers expecting /api/dynasty-data."""
    return await get_data(request)


@app.get("/api/data/rank-history")
async def get_rank_history(request: Request):
    """Per-player rank history series for the last ``days`` days.

    Every contract build appends the ranked board to a JSONL log
    (see ``src/api/rank_history.py``).  This endpoint reads the log
    and flips it into the per-player ``{name: [{date, rank}, ...]}``
    shape the frontend ``RankChangeGlyph`` consumes.

    Query params:
      * ``days`` — window in days (default 30, max 180).

    The log is already mirrored onto each row's ``rankHistory`` at
    contract build time, so most consumers don't need this endpoint
    — it exists for tools that want the raw series without fetching
    the full 4 MB contract.
    """
    try:
        requested = int(request.query_params.get("days", _rank_history.DEFAULT_HISTORY_WINDOW_DAYS))
    except (TypeError, ValueError):
        requested = _rank_history.DEFAULT_HISTORY_WINDOW_DAYS
    days = max(1, min(_rank_history.MAX_SNAPSHOTS, requested))
    history = _rank_history.load_history(days=days)
    return JSONResponse(
        content={"days": days, "history": history},
        headers={"Cache-Control": "public, max-age=60, stale-while-revalidate=300"},
    )


@app.get("/api/data/player-source-history")
async def get_player_source_history(request: Request):
    """Per-source value history for a single player.

    Returns the per-source and blended value timeline the PlayerPopup
    chart renders as multiple overlaid lines — one thin line per
    ranking source and one bold line for our blend.

    Query params:
      * ``name``        — player display name (required, case-insensitive)
      * ``days``        — window in days (default 180, max 180)
      * ``assetClass``  — optional disambiguator ("offense" / "idp" /
                          "pick") for cross-universe name collisions
    """
    name = (request.query_params.get("name") or "").strip()
    if not name:
        return JSONResponse(
            status_code=400,
            content={"error": "Missing required 'name' query param."},
        )
    try:
        requested = int(request.query_params.get("days", _source_history.DEFAULT_HISTORY_WINDOW_DAYS))
    except (TypeError, ValueError):
        requested = _source_history.DEFAULT_HISTORY_WINDOW_DAYS
    days = max(1, min(_source_history.MAX_SNAPSHOTS, requested))
    asset_class = (request.query_params.get("assetClass") or "").strip() or None
    history = _source_history.load_player_history(
        name,
        days=days,
        asset_class=asset_class,
    )
    return JSONResponse(
        content={
            "name": name,
            "days": days,
            "assetClass": asset_class,
            **history,
        },
        headers={"Cache-Control": "public, max-age=120, stale-while-revalidate=600"},
    )


# ── Rankings override API ──────────────────────────────────────────
# These endpoints are the single authoritative path for custom-source
# configurations.  The frontend NEVER runs its own blended ranking
# engine when a user customizes source weights — instead it POSTs
# the override map here and receives either a full canonical
# contract or a compact delta payload re-computed by
# ``build_api_data_contract()`` / ``build_rankings_delta_payload()``
# with the overrides threaded into ``_compute_unified_rankings()``.

@app.get("/api/rankings/sources")
async def get_rankings_sources():
    """Return the canonical ranking-source registry.

    The frontend mirrors this registry statically in
    ``frontend/lib/dynasty-data.js::RANKING_SOURCES``; this endpoint
    exists so runtime tools, tests, and future builds can fetch the
    authoritative Python registry without reaching into module
    internals.  The shape matches the frontend entry exactly —
    ``assert_ranking_source_registry_parity()`` enforces that.
    """
    return JSONResponse(content={
        "sources": get_ranking_source_registry(),
        "contractVersion": API_DATA_CONTRACT_VERSION,
    })


@app.post("/api/rankings/overrides")
async def post_rankings_overrides(request: Request):
    """Rebuild the canonical rankings with user-supplied source overrides.

    Accepts two equivalent body shapes:

      * ``{"enabled_sources": [...], "weights": {key: float, ...}}``
      * ``{"<source_key>": {"include": bool, "weight": float}, ...}``
        (legacy ``siteWeights`` shape from the frontend settings store)

    Response shape is controlled by the ``view`` query parameter:

      * ``view=full`` (default) — returns the full canonical
        contract (~4 MB uncompressed, identical shape to ``GET
        /api/data``).
      * ``view=delta`` (frontend default) — returns the compact
        delta payload (~70% smaller) containing only the
        override-sensitive fields per player.  The frontend merges
        the delta onto its cached base contract.
    """
    if not latest_data or not isinstance(latest_data, dict):
        return JSONResponse(
            status_code=503,
            content={
                "error": "No data available yet. First scrape may still be running.",
            },
        )

    try:
        body = await request.json()
    except Exception:
        body = None

    # Rankings follow scoring profile, not league key.  Validate the
    # key but only 503 when profiles actually differ — otherwise the
    # override pipeline can serve the same recomputed rankings to any
    # league that shares scoring.  The league-specific sleeper block
    # in the response is nulled below when the loaded contract was
    # built for a different league.
    try:
        league_cfg = _resolve_league_for_request(
            request,
            body=body if isinstance(body, dict) else None,
        )
    except LeagueResolutionError as err:
        return err.json_response()
    loaded_meta = (
        latest_contract_data.get("meta") or {}
        if isinstance(latest_contract_data, dict) else {}
    )
    loaded_league = str(loaded_meta.get("leagueKey") or "")
    loaded_profile = str(loaded_meta.get("scoringProfile") or "")
    sleeper_matches = bool(loaded_league) and loaded_league == league_cfg.key
    if loaded_profile and loaded_profile != league_cfg.scoring_profile:
        return JSONResponse(
            status_code=503,
            content={
                "error": "data_not_ready",
                "message": (
                    f"League {league_cfg.key!r} uses scoring profile "
                    f"{league_cfg.scoring_profile!r}, not {loaded_profile!r}."
                ),
                "leagueKey": league_cfg.key,
                "scoringProfile": league_cfg.scoring_profile,
            },
        )

    overrides, warnings = normalize_source_overrides(body)
    tep_multiplier = normalize_tep_multiplier(body)

    view = (request.query_params.get("view") or "").strip().lower()
    delta_view = view in {"delta", "compact", "slim"}

    try:
        if delta_view:
            contract_payload = build_rankings_delta_payload(
                latest_data,
                data_source=latest_data_source,
                source_overrides=overrides if overrides else None,
                tep_multiplier=tep_multiplier,
            )
        else:
            contract_payload = build_api_data_contract(
                latest_data,
                data_source=latest_data_source,
                source_overrides=overrides if overrides else None,
                tep_multiplier=tep_multiplier,
            )
    except Exception as exc:
        log.exception("Failed to rebuild contract with overrides: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": f"Failed to rebuild rankings with overrides: {exc}",
                "warnings": warnings,
            },
        )

    if warnings:
        contract_payload.setdefault("warnings", []).extend(warnings)

    # Stamp meta fields so the frontend can assert compatibility:
    # ``leagueKey`` = resolved league; ``scoringProfile`` = which
    # rules the pipeline used; ``sleeperDataReady`` = whether the
    # ``sleeper`` block can be trusted for this league.  When the
    # loaded contract was built for a different league (same scoring
    # profile though — we'd have 503'd above if profiles differed),
    # null the sleeper block so callers don't render the wrong
    # league's teams.
    if isinstance(contract_payload, dict):
        meta = contract_payload.setdefault("meta", {})
        meta["leagueKey"] = league_cfg.key
        meta["scoringProfile"] = league_cfg.scoring_profile
        meta["sleeperDataReady"] = sleeper_matches
        if not sleeper_matches:
            contract_payload["sleeper"] = None
            meta["sleeperLoadedLeagueKey"] = loaded_league or None

    headers = {
        "Cache-Control": "no-store",
        "X-Payload-View": "rankings-overrides-delta" if delta_view else "rankings-overrides",
    }
    return JSONResponse(content=contract_payload, headers=headers)


# Cache of Sleeper league ``name`` fields.  Refreshed every
# ``_SLEEPER_NAME_TTL_SEC`` so a rename in Sleeper propagates to the
# UI without a deploy, but we don't hammer Sleeper on every
# /api/leagues request.
_SLEEPER_NAME_CACHE: dict[str, dict] = {}
_SLEEPER_NAME_TTL_SEC = 300


def _fetch_sleeper_league_name(sleeper_league_id: str) -> str | None:
    """Return the live ``name`` from ``/v1/league/<id>`` or None on
    any failure.  Cached per-league for 5 minutes.  Used by
    ``/api/leagues`` to label each league with its actual Sleeper
    name (e.g. "Risk It To Get The Brisket") instead of whatever
    operator-edited string lives in the registry's ``displayName``.
    """
    import time as _time

    sleeper_league_id = str(sleeper_league_id or "").strip()
    if not sleeper_league_id:
        return None
    now = _time.time()
    cached = _SLEEPER_NAME_CACHE.get(sleeper_league_id)
    if cached and (now - float(cached.get("fetched_at") or 0)) < _SLEEPER_NAME_TTL_SEC:
        return cached.get("name")

    try:
        url = f"https://api.sleeper.app/v1/league/{sleeper_league_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "brisket-league-name/1.0"})
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            body = resp.read()
        parsed = json.loads(body)
    except Exception:  # noqa: BLE001 — transient failures cache None so we don't refetch every call
        _SLEEPER_NAME_CACHE[sleeper_league_id] = {"name": None, "fetched_at": now}
        return None

    name = str((parsed or {}).get("name") or "").strip() or None
    _SLEEPER_NAME_CACHE[sleeper_league_id] = {"name": name, "fetched_at": now}
    return name


# Cache of (league_id, user_id) → {ownerId, teamName} so the user's
# default team in a given league can be auto-selected by
# ``/api/leagues`` without a second round-trip.  Same 5-min TTL as
# the league-name cache; a rename of the user's team in Sleeper
# propagates within that window.
_SLEEPER_USER_TEAM_CACHE: dict[tuple[str, str], dict] = {}


def _fetch_sleeper_user_team(
    sleeper_league_id: str, sleeper_user_id: str,
) -> dict | None:
    """Return ``{"ownerId", "teamName"}`` for the user in the given
    league, or ``None`` if the user isn't in the league or Sleeper
    is unreachable.

    Falls back gracefully: a single failure caches ``None`` for
    ``_SLEEPER_NAME_TTL_SEC`` so a flaky Sleeper doesn't force a
    refetch on every authed request.

    Used by ``/api/leagues`` so a user who isn't enumerated in a
    league's registry ``defaultTeamMap`` still gets their team
    auto-selected on that league (resolved via ownerId match from
    the session's ``sleeper_user_id``).
    """
    import time as _time

    sleeper_league_id = str(sleeper_league_id or "").strip()
    sleeper_user_id = str(sleeper_user_id or "").strip()
    if not sleeper_league_id or not sleeper_user_id:
        return None
    now = _time.time()
    cache_key = (sleeper_league_id, sleeper_user_id)
    cached = _SLEEPER_USER_TEAM_CACHE.get(cache_key)
    if cached and (now - float(cached.get("fetched_at") or 0)) < _SLEEPER_NAME_TTL_SEC:
        return cached.get("value")

    try:
        users_url = (
            f"https://api.sleeper.app/v1/league/{sleeper_league_id}/users"
        )
        req = urllib.request.Request(
            users_url, headers={"User-Agent": "brisket-user-team/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            users = json.loads(resp.read())
    except Exception:  # noqa: BLE001 — cache None on any transient failure
        _SLEEPER_USER_TEAM_CACHE[cache_key] = {"value": None, "fetched_at": now}
        return None

    # Find the authed user in the league.
    team_name = ""
    for u in users or []:
        if str(u.get("user_id") or "") == sleeper_user_id:
            team_name = (
                (u.get("metadata") or {}).get("team_name")
                or u.get("display_name")
                or ""
            )
            break
    if not team_name:
        _SLEEPER_USER_TEAM_CACHE[cache_key] = {"value": None, "fetched_at": now}
        return None

    value = {"ownerId": sleeper_user_id, "teamName": str(team_name).strip()}
    _SLEEPER_USER_TEAM_CACHE[cache_key] = {"value": value, "fetched_at": now}
    return value


@app.get("/api/leagues")
async def get_leagues(request: Request):
    """List every configured league.

    Public endpoint — the response contains no secrets (no Sleeper
    league IDs, no auth tokens).  The ``key`` is the stable identifier
    callers thread through the rest of the API when we eventually
    add ``?leagueId=`` parameters to league-scoped endpoints.

    ``displayName`` is pulled LIVE from Sleeper (``/v1/league/<id>``
    ``.name``) and cached for 5 minutes.  This way a league rename
    in Sleeper propagates to the switcher without a registry edit
    or redeploy.  Falls back to the registry's configured
    ``displayName`` when Sleeper is unreachable.

    Views:
      * Anonymous:     active leagues only.
      * Authenticated: active leagues + ``userDefaultKey`` (which
                       league the UI should land this user on by
                       default) + per-league ``userDefaultTeam``
                       entries from each league's ``defaultTeamMap``
                       so the frontend can auto-select the right
                       team in each league without a second round-
                       trip to user_kv.
    """
    session = _get_auth_session(request)
    active_cfgs = _league_registry.active_leagues()
    leagues = [cfg.public_dict() for cfg in active_cfgs]

    # Overlay the live Sleeper name for each league.  Run the
    # fetches in a threadpool so we don't block the event loop on
    # the Sleeper round-trip.  Cached 5 min so steady-state traffic
    # doesn't hammer Sleeper.
    def _fetch_names(cfgs):
        return [_fetch_sleeper_league_name(c.sleeper_league_id) for c in cfgs]
    sleeper_names = await run_in_threadpool(_fetch_names, active_cfgs)
    for i, live_name in enumerate(sleeper_names):
        if live_name:
            leagues[i]["displayName"] = live_name

    if session:
        username = (session.get("username") or "").strip().lower()
        sleeper_user_id = str(session.get("sleeper_user_id") or "").strip()
        # Stamp each league's entry with this user's default team
        # when the registry knows about one.  Only this authed user
        # sees their own default — we don't expose other usernames'
        # mappings even though the registry file holds them.
        #
        # Fallback: when the registry has no default_team_map entry
        # for this user on this league (common for newly-added
        # leagues), auto-resolve the user's team from Sleeper via
        # their ``sleeper_user_id`` → league users lookup.  Without
        # this fallback the team picker stays on "Pick your team"
        # forever for any league the registry hasn't been edited
        # for, forcing every dashboard block to sit at "Pick a team
        # to see..." until the user manually selects one.
        def _resolve_team(cfg):
            mapped = cfg.default_team_map.get(username) if username else None
            if mapped:
                return {
                    "ownerId": mapped.get("ownerId", "") or sleeper_user_id,
                    "teamName": mapped.get("teamName", ""),
                }
            if sleeper_user_id:
                return _fetch_sleeper_user_team(
                    cfg.sleeper_league_id, sleeper_user_id,
                )
            return None

        resolved = await run_in_threadpool(
            lambda: [_resolve_team(c) for c in active_cfgs]
        )
        for i, team in enumerate(resolved):
            if team:
                leagues[i]["userDefaultTeam"] = team

    body: dict[str, Any] = {
        "leagues": leagues,
        "defaultKey": _league_registry.default_league_key(),
    }
    if session:
        user_default = _league_registry.get_user_default_league(
            session.get("username") or ""
        )
        body["userDefaultKey"] = user_default.key if user_default else None
    return JSONResponse(content=body, headers={"Cache-Control": "no-store"})


@app.get("/api/status")
async def get_status():
    """Return scraper status info."""
    status_payload = _scrape_status_payload()
    # Prefer full scrape payload for source-health truth (dlfImport/sourceRunSummary).
    # Contract payload is a compatibility fallback when full payload is unavailable.
    source_health = _build_source_health_snapshot(latest_data or latest_contract_data)
    full_bytes = len(latest_data_bytes) if latest_data_bytes else 0
    runtime_bytes = len(latest_runtime_data_bytes) if latest_runtime_data_bytes else 0
    startup_bytes = len(latest_startup_data_bytes) if latest_startup_data_bytes else 0
    full_gzip_bytes = len(latest_data_gzip_bytes) if latest_data_gzip_bytes else 0
    runtime_gzip_bytes = len(latest_runtime_data_gzip_bytes) if latest_runtime_data_gzip_bytes else 0
    startup_gzip_bytes = len(latest_startup_data_gzip_bytes) if latest_startup_data_gzip_bytes else 0
    return JSONResponse(content={
        **status_payload,
        "frontend_runtime": frontend_runtime_status,
        "contract": {
            "version": API_DATA_CONTRACT_VERSION,
            "health": contract_health,
            "value_authority": (latest_contract_data or {}).get("valueAuthority"),
        },
        "data_runtime": {
            "last_data_refresh_at": latest_data_source.get("loadedAt"),
            "active_data_source": latest_data_source,
            "payload_bytes_full": full_bytes,
            "payload_bytes_runtime": runtime_bytes,
            "payload_bytes_startup": startup_bytes,
            "payload_gzip_bytes_full": full_gzip_bytes,
            "payload_gzip_bytes_runtime": runtime_gzip_bytes,
            "payload_gzip_bytes_startup": startup_gzip_bytes,
            "runtime_payload_savings_bytes": max(0, full_bytes - runtime_bytes),
            "runtime_payload_savings_gzip_bytes": max(0, full_gzip_bytes - runtime_gzip_bytes),
            "startup_payload_savings_bytes": max(0, full_bytes - startup_bytes),
            "startup_payload_savings_gzip_bytes": max(0, full_gzip_bytes - startup_gzip_bytes),
        },
        "source_health": source_health,
        "uptime": uptime_status,
        "has_data": latest_contract_data is not None,
        "player_count": int((latest_contract_data or {}).get("playerCount") or 0),
        "data_date": (latest_contract_data or {}).get("date"),
        # R-4: Scrape success rate tracking
        "scrape_success_rate_24h": _scrape_success_rate_24h(),
        "last_n_scrapes": scrape_history[-20:],
        "leagues": _league_status_snapshot(),
        # 2026-04 upgrade observability — feature-flag state +
        # unified-mapper coverage.  All flags default off so this
        # is additive/informational; enabling a flag at runtime is
        # the operator's decision.
        "featureFlags": _feature_flag_snapshot_safe(),
        "idMappingCoverage": _id_mapping_coverage_safe(),
        "nflDataProvider": _nfl_data_provider_status_safe(),
        "normalizationHealth": _normalization_health_safe(),
    })


def _feature_flag_snapshot_safe() -> dict:
    """Return the feature-flag snapshot, tolerant of import errors
    so a malformed upgrade doesn't 500 /api/status."""
    try:
        from src.api import feature_flags as _ff
        return _ff.snapshot()
    except Exception as exc:  # noqa: BLE001
        log.warning("feature_flag snapshot failed: %s", exc)
        return {}


def _id_mapping_coverage_safe() -> dict:
    try:
        from src.identity import unified_mapper as _um
        return _um.mapping_coverage_snapshot()
    except Exception as exc:  # noqa: BLE001
        log.warning("id mapping coverage snapshot failed: %s", exc)
        return {}


def _nfl_data_provider_status_safe() -> dict:
    try:
        from src.nfl_data import ingest as _ing
        return _ing.provider_status()
    except Exception as exc:  # noqa: BLE001
        log.warning("nfl_data provider status failed: %s", exc)
        return {}


def _normalization_health_safe() -> dict:
    """Return the contract validation summary for /api/status.
    Runs on every status hit (not cached) — it's O(N) over the
    playersArray, ~5ms for ~1100 rows."""
    try:
        from src.canonical import normalization_validator as _nv
        return _nv.validate_contract(latest_contract_data or {})
    except Exception as exc:  # noqa: BLE001
        log.warning("normalization validator failed: %s", exc)
        return {}


def _league_status_snapshot() -> list[dict]:
    """Per-league data-health snapshot for /api/status.

    Reports for each ACTIVE league:
      * ``key`` / ``displayName``                — identity
      * ``source``                                — "primary-scrape" | "overlay" | "none"
      * ``teamCount``                             — rosters resolved
      * ``tradeCount``                            — trades loaded
      * ``overlayFetchedAt`` / ``overlayAgeSec``  — staleness (None when primary)
      * ``sleeperLeagueId``                       — raw id for correlation with logs

    This is the diagnostic surface for answering "does League B have
    fresh data, or am I serving the stale overlay again?".  When the
    source is ``none`` the UI surfaces the data-not-ready state.
    """
    import time as _time
    snapshot: list[dict[str, Any]] = []
    loaded = latest_contract_data or {}
    loaded_meta = loaded.get("meta") or {}
    loaded_key = loaded_meta.get("leagueKey")
    loaded_sleeper = loaded.get("sleeper") or {}
    for cfg in _league_registry.active_leagues():
        entry: dict[str, Any] = {
            "key": cfg.key,
            "displayName": cfg.display_name,
            "sleeperLeagueId": cfg.sleeper_league_id,
            "idpEnabled": cfg.idp_enabled,
            "scoringProfile": cfg.scoring_profile,
        }
        if cfg.key == loaded_key and isinstance(loaded_sleeper, dict):
            entry["source"] = "primary-scrape"
            entry["teamCount"] = len(loaded_sleeper.get("teams") or [])
            entry["tradeCount"] = len(loaded_sleeper.get("trades") or [])
            entry["overlayFetchedAt"] = None
            entry["overlayAgeSec"] = None
        else:
            cached = _sleeper_overlay._CACHE.get(cfg.sleeper_league_id) or {}
            payload = cached.get("payload") or {}
            fetched_at = float(cached.get("_cached_at") or 0)
            if payload.get("teams"):
                entry["source"] = "overlay"
                entry["teamCount"] = len(payload.get("teams") or [])
                entry["tradeCount"] = len(payload.get("trades") or [])
                entry["overlayFetchedAt"] = payload.get("overlayFetchedAt")
                entry["overlayAgeSec"] = (
                    round(_time.time() - fetched_at, 1) if fetched_at > 0 else None
                )
            else:
                entry["source"] = "none"
                entry["teamCount"] = 0
                entry["tradeCount"] = 0
                entry["overlayFetchedAt"] = None
                entry["overlayAgeSec"] = None
        snapshot.append(entry)
    return snapshot


@app.api_route("/api/health", methods=["GET", "HEAD"])
async def get_health():
    """Basic health endpoint for reverse proxy / uptime probes."""
    status_payload = _scrape_status_payload()

    # R-1: Data freshness check — flag stale if no refresh in SCRAPE_INTERVAL_HOURS * 3
    data_stale = False
    data_age_hours = None
    loaded_at = latest_data_source.get("loadedAt")
    if loaded_at:
        try:
            loaded_dt = datetime.fromisoformat(loaded_at)
            data_age_hours = round(
                (datetime.now(timezone.utc) - loaded_dt).total_seconds() / 3600, 1
            )
            data_stale = data_age_hours > SCRAPE_INTERVAL_HOURS * 3
        except (ValueError, TypeError):
            pass

    # Session-cookie age surface.  Distinguishes AUTO-refreshing
    # sessions (scraper re-logs-in via stored credentials when the
    # cached cookies fail) from MANUAL-only sessions (operator
    # pastes browser cookies because the site blocks automated
    # login — currently just IDP Show, whose Substack paywall has
    # a captcha on password auth).  The frontend banner only alarms
    # on manual-only sessions since auto-refresh sessions fix
    # themselves on the next scrape.
    _session_ages: dict[str, dict] = {}
    import os as _os
    _session_configs = {
        # Scraper POSTs DLF_USERNAME/PASSWORD to wp-login on failure,
        # so this file auto-refreshes.  Tracked for visibility only.
        "dlf_session.json": {"lifetimeDays": 14, "autoRefresh": True},
        # Scraper POSTs DRAFTSHARKS_EMAIL/PASSWORD on failure.
        "draftsharks_session.json": {"lifetimeDays": 30, "autoRefresh": True},
        # Scraper POSTs FOOTBALLGUYS_EMAIL/PASSWORD on failure.
        "footballguys_session.json": {"lifetimeDays": 30, "autoRefresh": True},
        # Substack captcha-gates password login — the ONLY way to
        # refresh these cookies is a manual browser dump.  Banner
        # alarms on this file specifically.
        "idpshow_session.json": {"lifetimeDays": 90, "autoRefresh": False},
    }
    for fname, cfg in _session_configs.items():
        lifetime_days = cfg["lifetimeDays"]
        auto_refresh = cfg["autoRefresh"]
        fpath = BASE_DIR / fname
        try:
            if not fpath.exists():
                _session_ages[fname] = {"present": False, "autoRefresh": auto_refresh}
                continue
            mtime_ts = fpath.stat().st_mtime
            age_days = round(
                (datetime.now(timezone.utc).timestamp() - mtime_ts) / 86400, 1
            )
            days_remaining = max(0.0, round(lifetime_days - age_days, 1))
            # Only MANUAL sessions get the warnSoon flag — auto-refresh
            # sessions silently rotate when cached cookies expire, so
            # the banner shouldn't nag about them.
            warn_soon = (
                not auto_refresh
                and days_remaining <= 14
                and age_days > 0
            )
            expired = (not auto_refresh) and days_remaining <= 0
            _session_ages[fname] = {
                "present": True,
                "autoRefresh": auto_refresh,
                "ageDays": age_days,
                "lifetimeDays": lifetime_days,
                "daysRemaining": days_remaining,
                "warnSoon": warn_soon,
                "expired": expired,
            }
        except Exception:
            _session_ages[fname] = {"present": False, "autoRefresh": auto_refresh}

    is_ok = (
        status_payload.get("last_error") in (None, "")
        and not status_payload.get("stalled")
        and not data_stale
        and bool(contract_health.get("ok", False))
    )
    status = "ok" if is_ok else "degraded"
    # Deeper health: startup checks + circuit breakers + session
    # store size.  Wrapped so a dependency import error can't bring
    # down the health endpoint itself.
    def _circuits_safe():
        try:
            from src.utils import circuit_breaker as _cb
            return _cb.snapshot_all()
        except Exception as exc:  # noqa: BLE001
            log.warning("health: circuit_breaker snapshot failed: %s", exc)
            return []

    def _sessions_safe():
        try:
            from src.api import session_store as _ss
            return {"persistedCount": _ss.count_active()}
        except Exception as exc:  # noqa: BLE001
            log.warning("health: session_store count failed: %s", exc)
            return {"persistedCount": None}

    circuits = _circuits_safe()
    # Any breaker in OPEN state flips overall status to degraded.
    any_breaker_open = any(c.get("state") == "open" for c in circuits)
    return JSONResponse(
        status_code=200 if is_ok else 503,
        content={
            "status": status,
            "service": "dynasty-server",
            "time_utc": datetime.now(timezone.utc).isoformat(),
            "has_data": latest_contract_data is not None,
            "data_stale": data_stale,
            "data_age_hours": data_age_hours,
            "last_scrape": status_payload.get("last_scrape"),
            "scrape_running": status_payload.get("is_running"),
            "scrape_stalled": status_payload.get("stalled"),
            "current_step": status_payload.get("current_step"),
            "current_source": status_payload.get("current_source"),
            "contract_version": API_DATA_CONTRACT_VERSION,
            "contract_ok": contract_health.get("ok"),
            "frontend_runtime": frontend_runtime_status.get("active"),
            "uptime_watchdog": {
                "enabled": uptime_status.get("enabled"),
                "target_url": uptime_status.get("target_url"),
            },
            "session_cookies": _session_ages,
            "sessions": _sessions_safe(),
            "circuitBreakers": circuits,
            "anyBreakerOpen": any_breaker_open,
            "startupChecks": _startup_checks_summary,
            "memberInMemorySessions": len(auth_sessions) if isinstance(auth_sessions, dict) else None,
        },
    )


@app.get("/api/uptime")
async def get_uptime_status():
    """Detailed uptime watchdog state."""
    return JSONResponse(content=uptime_status)


@app.get("/api/metrics")
async def get_metrics():
    """R-9: Lightweight metrics endpoint for dashboards and monitoring."""
    now = datetime.now(timezone.utc)
    # Calculate data age
    data_age_seconds = None
    loaded_at = latest_data_source.get("loadedAt")
    if loaded_at:
        try:
            loaded_dt = datetime.fromisoformat(loaded_at)
            data_age_seconds = round((now - loaded_dt).total_seconds(), 0)
        except (ValueError, TypeError):
            pass

    # Calculate uptime
    uptime_seconds = None
    if _metrics.get("server_start_time"):
        try:
            start_dt = datetime.fromisoformat(_metrics["server_start_time"])
            uptime_seconds = round((now - start_dt).total_seconds(), 0)
        except (ValueError, TypeError):
            pass

    disk_ok, free_mb = _check_disk_space()

    return JSONResponse(content={
        "server_start_time": _metrics.get("server_start_time"),
        "uptime_seconds": uptime_seconds,
        "request_count": _metrics.get("request_count", 0),
        "scrape_total": _metrics.get("scrape_total", 0),
        "scrape_failures": _metrics.get("scrape_failures", 0),
        "scrape_duration_seconds_last": _metrics.get("scrape_duration_seconds_last", 0),
        "data_age_seconds": data_age_seconds,
        "data_stale": (data_age_seconds or 0) > SCRAPE_INTERVAL_HOURS * 3 * 3600,
        "has_data": latest_contract_data is not None,
        "player_count": int((latest_contract_data or {}).get("playerCount") or 0),
        "disk_free_mb": free_mb,
        "disk_ok": disk_ok,
        "scrape_running": scrape_status.get("running", False),
    })


# ── NEWS ───────────────────────────────────────────────────────────────
# Normalized news feed aggregating Sleeper trending + ESPN RSS.  The
# service layer owns caching, per-provider fault isolation, and the
# normalized NewsItem shape (see ``src/news/base.py``).  The route is
# a thin adapter: parse query args, delegate, and surface per-provider
# diagnostics so the frontend can distinguish "empty feed" from "all
# providers degraded".
@app.get("/api/news")
async def get_news(request: Request):
    limit_raw = request.query_params.get("limit")
    try:
        limit = int(limit_raw) if limit_raw else 50
    except ValueError:
        limit = 50
    limit = max(1, min(limit, 100))

    # Optional team-name filter.  Repeatable ?team=... or comma
    # separated.  Items that don't mention at least one of those
    # players are dropped from the response (client-side filtering
    # stays available for scope="roster"/"league" already).
    team_params = request.query_params.getlist("team") if hasattr(
        request.query_params, "getlist"
    ) else []
    team_names: list[str] = []
    for raw in team_params:
        for part in str(raw).split(","):
            if part.strip():
                team_names.append(part.strip())

    svc = _get_news_service()
    try:
        aggregated = await run_in_threadpool(
            svc.aggregate,
            player_names=_live_player_names(),
            team_names=team_names or None,
        )
    except Exception as exc:
        log.warning("/api/news aggregation failed: %s", exc)
        # Signal "temporarily unavailable" — the frontend falls back
        # to the mock fixture on 503 so the page stays functional.
        return JSONResponse(
            status_code=503,
            content={
                "items": [],
                "providersUsed": [],
                "providerRuns": [],
                "error": f"{type(exc).__name__}",
                "generatedAt": datetime.now(timezone.utc).isoformat(),
            },
        )

    payload = aggregated.to_dict()
    payload["source"] = "backend"
    payload["limit"] = limit
    if len(payload.get("items", [])) > limit:
        payload["items"] = payload["items"][:limit]
        payload["count"] = len(payload["items"])

    # Distinguish "providers worked, nothing trending" (legit 200
    # with empty items — DEMO badge stays OFF) from "every provider
    # errored out" (503 — frontend falls back to its mock fixture
    # and re-shows the DEMO badge).
    provider_runs = aggregated.provider_runs or []
    all_failed = bool(provider_runs) and not any(r.ok for r in provider_runs)
    if all_failed:
        return JSONResponse(
            status_code=503,
            content={
                **payload,
                "source": "backend",
                "error": "all_providers_failed",
            },
        )
    return JSONResponse(content=payload)


@app.get("/api/scaffold/status")
async def get_scaffold_status():
    """Return latest scaffold snapshot metadata for raw/canonical/league/report outputs."""
    raw_file = _latest_file(DATA_DIR / "raw_sources", "raw_source_snapshot_*.json")
    ingest_validation_file = _latest_file(DATA_DIR / "validation", "ingest_validation_*.json")
    league_file = _latest_file(DATA_DIR / "league", "league_snapshot_*.json")
    identity_file = _latest_file(DATA_DIR / "identity", "identity_resolution_*.json")
    if identity_file is None:
        identity_file = _latest_file(DATA_DIR / "identity", "identity_report_*.json")
    report_file = _latest_file(DATA_DIR / "reports", "ops_report_*.md")

    raw = _load_json_file(raw_file)
    ingest_validation = _load_json_file(ingest_validation_file)
    league = _load_json_file(league_file)
    identity = _load_json_file(identity_file)

    def _meta(path: Path | None) -> dict | None:
        if path is None or not path.exists():
            return None
        stat = path.stat()
        return {
            "name": path.name,
            "path": str(path),
            "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            "size_bytes": stat.st_size,
        }

    return JSONResponse(
        content={
            "raw_sources": {
                "file": _meta(raw_file),
                "source_count": len(raw.get("snapshots", [])) if raw else 0,
                "record_count": (
                    sum(len(s.get("records", [])) for s in raw.get("snapshots", []))
                    if raw
                    else 0
                ),
            },
            "ingest_validation": {
                "file": _meta(ingest_validation_file),
                "status": ingest_validation.get("status", "missing") if ingest_validation else "missing",
                "missing_snapshot_field_count": ingest_validation.get("missing_snapshot_field_count", 0) if ingest_validation else 0,
                "missing_asset_field_count": ingest_validation.get("missing_asset_field_count", 0) if ingest_validation else 0,
            },
            "league": {
                "file": _meta(league_file),
                "asset_count": league.get("asset_count", 0) if league else 0,
            },
            "identity": {
                "file": _meta(identity_file),
                "master_player_count": identity.get("master_player_count", 0) if identity else 0,
                "single_source_count": identity.get("single_source_count", 0) if identity else 0,
                "conflict_count": identity.get("conflict_count", 0) if identity else 0,
            },
            "report": {
                "file": _meta(report_file),
            },
        }
    )


@app.get("/api/scaffold/raw")
async def get_scaffold_raw():
    file_path = _latest_file(DATA_DIR / "raw_sources", "raw_source_snapshot_*.json")
    payload = _load_json_file(file_path)
    if payload is None:
        return JSONResponse(status_code=404, content={"error": "No raw scaffold snapshot found"})
    return JSONResponse(content=payload)


@app.get("/api/scaffold/league")
async def get_scaffold_league():
    file_path = _latest_file(DATA_DIR / "league", "league_snapshot_*.json")
    payload = _load_json_file(file_path)
    if payload is None:
        return JSONResponse(status_code=404, content={"error": "No league scaffold snapshot found"})
    return JSONResponse(content=payload)


@app.get("/api/scaffold/identity")
async def get_scaffold_identity():
    file_path = _latest_file(DATA_DIR / "identity", "identity_resolution_*.json")
    if file_path is None:
        file_path = _latest_file(DATA_DIR / "identity", "identity_report_*.json")
    payload = _load_json_file(file_path)
    if payload is None:
        return JSONResponse(status_code=404, content={"error": "No identity report found"})
    return JSONResponse(content=payload)


@app.post("/api/trade/suggestions")
async def post_trade_suggestions(request: Request):
    """Generate trade suggestions for a given roster.

    Accepts JSON body:
        {
          "roster": ["Josh Allen", "Bijan Robinson", ...],
          "league_rosters": [                              // optional
            {"team_name": "Team A", "players": ["Player1", ...]},
            ...
          ]
        }

    Requires canonical data to be loaded. Returns roster analysis
    and categorized trade suggestions with market-edge signals
    and optional opponent-fit labels.
    """
    # The suggestion engine now reads the live contract
    # (``playersArray``) directly — no offline canonical snapshot
    # required.  We only 503 if the live contract itself hasn't
    # loaded, which indicates a server-bootstrap problem rather than
    # a missing canonical build.
    if not latest_contract_data or not latest_contract_data.get("playersArray"):
        return JSONResponse(
            status_code=503,
            content={"error": "Live contract not loaded yet. Retry in a moment."},
        )
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON body"})

    # Validate leagueKey (body or query) against the registry.
    try:
        league_cfg = _resolve_league_for_request(
            request, body=body, require_loaded_contract=True,
        )
    except LeagueResolutionError as err:
        return err.json_response()

    roster = body.get("roster")
    if not isinstance(roster, list) or not roster:
        return JSONResponse(
            status_code=400,
            content={"error": "Request body must include 'roster' as a non-empty array of player names."},
        )

    from src.trade.suggestions import (
        build_asset_pool_from_contract,
        generate_suggestions_from_pool,
    )

    league_rosters = body.get("league_rosters")
    if league_rosters is not None and not isinstance(league_rosters, list):
        league_rosters = None

    # Build the asset pool directly from the live contract.  Every
    # field the suggestion engine needs already lives on the
    # ``playersArray`` rows (see ``build_asset_pool_from_contract``
    # docstring for the field map).  This replaces the old two-step
    # flow of (a) loading the offline canonical snapshot and
    # (b) overlaying live values on top — with the contract-native
    # path there's only one source of truth.
    pool = build_asset_pool_from_contract(latest_contract_data)

    try:
        result = generate_suggestions_from_pool(
            roster_names=roster,
            pool=pool,
            league_rosters=league_rosters,
        )
    except Exception as e:
        log.error(f"Trade suggestion generation failed: {e}")
        return JSONResponse(status_code=500, content={"error": f"Suggestion generation failed: {e}"})

    if isinstance(result, dict):
        result["leagueKey"] = league_cfg.key
    return JSONResponse(content=result)


@app.post("/api/trade/finder")
async def post_trade_finder(request: Request):
    """Find board-arbitrage trades: good for me on our model, plausible for them on KTC.

    Accepts JSON body:
        {
          "myTeam": "Team Name",
          "opponentTeams": ["Opponent 1", "Opponent 2"]   // or ["all"] for all teams
        }

    Requires live data to be loaded. Works against the production data payload
    (players dict with _rawComposite / _canonicalSiteValues fields).
    """
    if latest_contract_data is None:
        return JSONResponse(
            status_code=503,
            content={"error": "No data loaded. Trade Finder requires live player data."},
        )
    players = latest_contract_data.get("players")
    sleeper = latest_contract_data.get("sleeper") or {}
    sleeper_teams = sleeper.get("teams") or []
    if not players or not sleeper_teams:
        return JSONResponse(
            status_code=503,
            content={"error": "Player data or Sleeper rosters not available."},
        )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON body"})

    # Validate leagueKey (body or query).
    try:
        league_cfg = _resolve_league_for_request(
            request, body=body, require_loaded_contract=True,
        )
    except LeagueResolutionError as err:
        return err.json_response()

    my_team = body.get("myTeam")
    if not my_team or not isinstance(my_team, str):
        return JSONResponse(
            status_code=400,
            content={"error": "Request body must include 'myTeam' as a team name string."},
        )

    opponent_teams = body.get("opponentTeams", [])
    if not isinstance(opponent_teams, list):
        return JSONResponse(status_code=400, content={"error": "'opponentTeams' must be a list."})

    # "all" means trade with every team except mine
    if opponent_teams == ["all"] or not opponent_teams:
        opponent_teams = [t["name"] for t in sleeper_teams if t.get("name") != my_team]

    from src.trade.finder import find_trades

    try:
        result = await run_in_threadpool(
            find_trades,
            players=players,
            my_team=my_team,
            opponent_teams=opponent_teams,
            sleeper_teams=sleeper_teams,
        )
    except Exception as e:
        log.error(f"Trade Finder failed: {e}")
        return JSONResponse(status_code=500, content={"error": f"Trade Finder failed: {e}"})

    if isinstance(result, dict):
        result["leagueKey"] = league_cfg.key
    return JSONResponse(content=result)


@app.post("/api/trade/import-ktc")
async def post_trade_import_ktc(request: Request):
    """Resolve a KeepTradeCut trade-calculator URL into ordered
    player lists the frontend can load into its sides.

    Body: ``{"url": "https://keeptradecut.com/trade-calculator?...&teamOne=1274&teamTwo=1555..."}``.

    Returns ``{sideOne, sideTwo, unresolved, sourceUrl}`` — see
    ``src/trade/ktc_import.py::resolve_trade_url`` for the shape.
    Public endpoint (same as the other /api/trade/* endpoints) so
    the drawer-less trade page works without re-authing.
    """
    from src.trade.ktc_import import resolve_trade_url  # noqa: PLC0415 — lazy import

    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "JSON body required."},
        )
    url = str(body.get("url") or "").strip()
    if not url:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "Missing 'url' field."},
        )
    if "keeptradecut.com" not in url:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": "URL must be a keeptradecut.com trade-calculator link.",
            },
        )

    # KTC HTML fetch + regex is blocking — run in threadpool so we
    # don't stall the event loop for other in-flight requests.
    try:
        result = await run_in_threadpool(resolve_trade_url, url)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": str(exc)},
        )
    except Exception as exc:  # noqa: BLE001 — surface upstream failures
        return JSONResponse(
            status_code=502,
            content={
                "ok": False,
                "error": "Failed to fetch KTC player map.",
                "detail": f"{type(exc).__name__}: {exc}",
            },
        )
    return JSONResponse(content={"ok": True, **result})


@app.post("/api/angle/find")
async def post_angle_find(request: Request):
    """Player-specific arbitrage: pick a player on your team, get
    targets on other teams where your rankings say win but KTC says
    fair-to-neutral (easy to pitch as "KTC says this is even").

    Accepts JSON body:
        {
          "ownerId": "472206636534984704",       // your sleeper ownerId
          "playerName": "Jayden Daniels",        // canonical name
          "minMyGainPct": 5.0,                    // optional, default 5
          "maxMarketGainPct": 5.0,                // optional, default 5
          "limit": 50                             // optional, default 50
        }

    Market value is per-position: IDPTradeCalc for IDP (DL/LB/DB),
    KTC for everyone else. Legacy body key ``maxKtcGainPct`` is
    still accepted for backward compatibility.
    """
    if latest_contract_data is None:
        return JSONResponse(
            status_code=503,
            content={"error": "No data loaded. Angle requires live player data."},
        )
    players_array = (latest_contract_data or {}).get("playersArray")
    sleeper = latest_contract_data.get("sleeper") or {}
    sleeper_teams = sleeper.get("teams") or []
    if not players_array or not sleeper_teams:
        return JSONResponse(
            status_code=503,
            content={"error": "Player data or Sleeper rosters not available."},
        )
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON body"})

    # League routing: accept leagueKey in body or query, reject
    # unknown/inactive, 503 when the loaded contract is for a
    # different league.
    try:
        league_cfg = _resolve_league_for_request(
            request, body=body, require_loaded_contract=True,
        )
    except LeagueResolutionError as err:
        return err.json_response()

    owner_id = str(body.get("ownerId") or "").strip()
    player_name = str(body.get("playerName") or "").strip()
    if not owner_id or not player_name:
        return JSONResponse(
            status_code=400,
            content={"error": "Request body must include 'ownerId' and 'playerName'."},
        )

    try:
        min_my = float(body.get("minMyGainPct", 5.0))
        # Accept new key, fall back to legacy for pre-rename clients.
        max_market = float(
            body.get("maxMarketGainPct", body.get("maxKtcGainPct", 5.0))
        )
        limit = int(body.get("limit", 50))
    except (TypeError, ValueError):
        return JSONResponse(
            status_code=400,
            content={"error": "minMyGainPct, maxMarketGainPct, limit must be numeric."},
        )

    from src.trade.angle import find_angles

    try:
        result = await run_in_threadpool(
            find_angles,
            players_array,
            player_name,
            owner_id,
            sleeper_teams,
            min_my_gain_pct=min_my,
            max_market_gain_pct=max_market,
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001
        log.error(f"Angle find failed: {exc}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Angle find failed: {exc}"},
        )
    if isinstance(result, dict):
        result["leagueKey"] = league_cfg.key
    return JSONResponse(content=result)


@app.post("/api/angle/packages")
async def post_angle_packages(request: Request):
    """Multi-player variant of Angle. Two modes:

    * ``mode: "offer"`` (default) — offer a list of your players, get
      back counter-packages from other teams sized within ±1 of your
      offer that lean your way on my-value but look fair-or-better to
      the counterparty on market.
    * ``mode: "acquire"`` — pick players on opposing rosters you want
      to acquire; get back offer-side packages from YOUR OWN roster
      (size within ±1 of the desired count) that satisfy the same
      arbitrage math. Lets you skip picking your own players upfront.

    Body (offer mode):
        {
          "mode": "offer",                      // optional, default
          "ownerId": "472206636534984704",
          "playerNames": ["Jayden Daniels", ...],
          "minMyGainPct": 5.0,
          "maxMarketGainPct": 5.0,
          "limit": 50,
          "candidatePoolPerTeam": 25
        }

    Body (acquire mode):
        {
          "mode": "acquire",
          "ownerId": "472206636534984704",
          "acquirePlayerNames": ["Ja'Marr Chase", "Bijan Robinson"],
          "minMyGainPct": 5.0,
          "maxMarketGainPct": 5.0,
          "limit": 50,
          "candidatePoolPerTeam": 25
        }

    Market value is per-position: IDPTradeCalc for IDP (DL/LB/DB),
    KTC for everyone else. Legacy body key ``maxKtcGainPct`` is
    still accepted.
    """
    if latest_contract_data is None:
        return JSONResponse(
            status_code=503,
            content={"error": "No data loaded. Angle requires live player data."},
        )
    players_array = (latest_contract_data or {}).get("playersArray")
    sleeper = latest_contract_data.get("sleeper") or {}
    sleeper_teams = sleeper.get("teams") or []
    if not players_array or not sleeper_teams:
        return JSONResponse(
            status_code=503,
            content={"error": "Player data or Sleeper rosters not available."},
        )
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON body"})

    # League routing (same pattern as /api/angle/find).
    try:
        league_cfg = _resolve_league_for_request(
            request, body=body, require_loaded_contract=True,
        )
    except LeagueResolutionError as err:
        return err.json_response()

    owner_id = str(body.get("ownerId") or "").strip()
    mode = str(body.get("mode") or "offer").strip().lower()
    if mode not in ("offer", "acquire"):
        return JSONResponse(
            status_code=400,
            content={"error": "'mode' must be 'offer' or 'acquire'."},
        )

    # In offer mode the user builds an offer from their roster and the
    # search returns counter-packages from other teams. In acquire
    # mode the user picks players on opposing rosters they want to
    # acquire and the search returns offer-side packages from their
    # own roster.
    if mode == "acquire":
        names_key = "acquirePlayerNames"
        names = body.get(names_key) or body.get("playerNames") or []
    else:
        names_key = "playerNames"
        names = body.get(names_key) or []
    if not owner_id or not isinstance(names, list) or not names:
        return JSONResponse(
            status_code=400,
            content={
                "error": (
                    f"Request body must include 'ownerId' and a non-empty "
                    f"{names_key!r} list."
                )
            },
        )
    player_names = [str(n).strip() for n in names if str(n).strip()]

    try:
        min_my = float(body.get("minMyGainPct", 5.0))
        # Accept renamed key; fall back to legacy for pre-rename clients.
        max_market = float(
            body.get("maxMarketGainPct", body.get("maxKtcGainPct", 5.0))
        )
        limit = int(body.get("limit", 50))
        pool = int(body.get("candidatePoolPerTeam", 25))
        per_team = int(body.get("perTeamLimit", 4))
        min_player = float(body.get("minPlayerMyValue", 0.0))
    except (TypeError, ValueError):
        return JSONResponse(
            status_code=400,
            content={"error": "numeric params must be numeric."},
        )
    positions_req = body.get("positions") or []
    if not isinstance(positions_req, list):
        positions_req = []
    positions_req = [str(p).strip() for p in positions_req if str(p).strip()]

    include_idp_raw = body.get("includeIdp", False)
    include_idp = bool(include_idp_raw) and include_idp_raw not in ("false", "0", "")
    # Back-compat: if the caller explicitly requested an IDP position
    # via ``positions`` but didn't set ``includeIdp`` (e.g. legacy
    # scripts predating the toggle), treat that as an implicit opt-in.
    # Otherwise ``positions=["DL"]`` alone would filter the pool down
    # to zero candidates, which silently breaks those callers.
    from src.trade.angle import _IDP_POSITIONS as _ANGLE_IDP_POSITIONS
    if not include_idp and any(
        str(p).strip().upper() in _ANGLE_IDP_POSITIONS for p in positions_req
    ):
        include_idp = True

    if mode == "acquire":
        from src.trade.angle import find_acquisition_packages

        try:
            result = await run_in_threadpool(
                find_acquisition_packages,
                players_array,
                player_names,
                owner_id,
                sleeper_teams,
                min_my_gain_pct=min_my,
                max_market_gain_pct=max_market,
                limit=limit,
                candidate_pool=pool,
                positions=positions_req or None,
                min_player_my_value=min_player,
                include_idp=include_idp,
            )
        except Exception as exc:  # noqa: BLE001
            log.error(f"Angle acquire failed: {exc}")
            return JSONResponse(
                status_code=500,
                content={"error": f"Angle acquire failed: {exc}"},
            )
        result = {"mode": "acquire", **result, "leagueKey": league_cfg.key}
        return JSONResponse(content=result)

    target_teams_req = body.get("targetTeamOwnerIds") or []
    if not isinstance(target_teams_req, list):
        target_teams_req = []
    target_teams_req = [str(t).strip() for t in target_teams_req if str(t).strip()]

    seeds_req = body.get("seedPlayerNames") or []
    if not isinstance(seeds_req, list):
        seeds_req = []
    seeds_req = [str(s).strip() for s in seeds_req if str(s).strip()]

    from src.trade.angle import find_angle_packages

    try:
        result = await run_in_threadpool(
            find_angle_packages,
            players_array,
            player_names,
            owner_id,
            sleeper_teams,
            min_my_gain_pct=min_my,
            max_market_gain_pct=max_market,
            limit=limit,
            candidate_pool_per_team=pool,
            per_team_limit=per_team,
            positions=positions_req or None,
            min_player_my_value=min_player,
            target_team_owner_ids=target_teams_req or None,
            seed_player_names=seeds_req or None,
            include_idp=include_idp,
        )
    except Exception as exc:  # noqa: BLE001
        log.error(f"Angle packages failed: {exc}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Angle packages failed: {exc}"},
        )
    result = {"mode": "offer", **result, "leagueKey": league_cfg.key}
    return JSONResponse(content=result)


@app.get("/api/scaffold/validation")
async def get_scaffold_validation():
    ingest_file = _latest_file(DATA_DIR / "validation", "ingest_validation_*.json")
    canonical_file = _latest_file(DATA_DIR / "validation", "canonical_validation_*.json")
    ingest = _load_json_file(ingest_file)
    canonical = _load_json_file(canonical_file)
    return JSONResponse(
        content={
            "ingest_validation_file": str(ingest_file) if ingest_file else None,
            "canonical_validation_file": str(canonical_file) if canonical_file else None,
            "ingest": ingest or {},
            "canonical": canonical or {},
        }
    )


@app.get("/api/scaffold/report")
async def get_scaffold_report():
    file_path = _latest_file(DATA_DIR / "reports", "ops_report_*.md")
    if file_path is None or not file_path.exists():
        return JSONResponse(status_code=404, content={"error": "No scaffold report found"})
    return FileResponse(file_path, media_type="text/markdown")


# ── DRAFT CAPITAL ──────────────────────────────────────────────────────
# Pick dollar values from CSV, rookie rankings from KTC (live) or CSV (fallback).
# Uses a decay curve to fill/extrapolate KTC values to all 72 picks.
DRAFT_DATA_XLSX = Path(__file__).parent / "CSVs" / "Draft Data.xlsx"
DRAFT_DATA_CSV = Path(__file__).parent / "CSVs" / "draft_data.csv"


def _sleeper_league_id_for_draft(league_key: str | None = None) -> str:
    """Resolve the Sleeper league ID for draft endpoints via the
    league registry.  Previously a module-level constant read from
    ``SLEEPER_LEAGUE_ID`` env var; now routes through
    ``league_registry.get_sleeper_league_id()`` which itself falls
    back to the env var when no registry.json is configured.

    If ``league_key`` is provided, that specific league's Sleeper ID
    is returned (after validation).  ``None`` resolves to the
    default league — the existing single-league behavior.

    Returns empty string when no league is configured at all so
    callers can short-circuit instead of making a Sleeper call to
    ``/league/``.
    """
    sid = _league_registry.get_sleeper_league_id(league_key)
    return sid or ""


class LeagueResolutionError(Exception):
    """Raised when a request references a league the server can't
    serve.  Carries an HTTP status + body so route handlers can
    ``except`` once and return a uniform error response.

    Status codes:
      * 400 — ``leagueKey`` is present but unknown or inactive
      * 503 — requested league is valid but no contract is loaded
              for it yet (single-league instance, or scrape in progress)
      * 404 — no leagues configured at all (fresh dev machine)
    """

    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message
        super().__init__(message)

    def json_response(self) -> "JSONResponse":
        return JSONResponse(
            status_code=self.status,
            content={"error": self.code, "message": self.message},
        )


def _resolve_league_for_request(
    request: "Request",
    *,
    body: dict | None = None,
    require_loaded_contract: bool = False,
) -> "_league_registry.LeagueConfig":
    """Pick the right league for this request.

    Resolution order:
      1. Explicit ``leagueKey`` in the query string
      2. Explicit ``leagueKey`` in the request body (when provided)
      3. The authenticated user's ``activeLeagueKey`` (from user_kv)
      4. The registry's default league

    Passes 1 + 2 go through ``get_league_by_key`` which also accepts
    aliases.  Passes 3 + 4 always resolve to a canonical key.  An
    inactive league at passes 1–2 raises 400 so a stale frontend
    can't accidentally keep hitting a retired league.

    When ``require_loaded_contract=True`` and the resolved league
    doesn't match the league that built ``latest_contract_data``,
    raises 503 ``data_not_ready``.  This is the guard that keeps
    single-instance deployments from returning garbage for a league
    they haven't scraped yet.
    """
    # 1 + 2: explicit leagueKey in query or body.
    explicit = (request.query_params.get("leagueKey") or "").strip()
    if not explicit and isinstance(body, dict):
        explicit = str(body.get("leagueKey") or "").strip()
    if explicit:
        cfg = _league_registry.get_league_by_key(explicit)
        if cfg is None:
            raise LeagueResolutionError(
                400, "unknown_league",
                f"Unknown leagueKey {explicit!r}",
            )
        if not cfg.active:
            raise LeagueResolutionError(
                400, "inactive_league",
                f"League {cfg.key!r} is not active",
            )
    else:
        # 3: user's saved preference.
        cfg = None
        session = _get_auth_session(request)
        if session:
            username = str(session.get("username") or "").strip()
            if username:
                try:
                    state = _user_kv.get_user_state(username) or {}
                    saved = (state.get("activeLeagueKey") or "").strip()
                    if saved:
                        candidate = _league_registry.get_league_by_key(saved)
                        if candidate is not None and candidate.active:
                            cfg = candidate
                except Exception:  # noqa: BLE001
                    cfg = None
        # 4: registry default.
        if cfg is None:
            cfg = _league_registry.get_default_league()
        if cfg is None:
            raise LeagueResolutionError(
                404, "no_leagues_configured",
                "No leagues configured on this server",
            )

    if require_loaded_contract:
        loaded_key = None
        try:
            loaded_key = (
                (latest_contract_data or {}).get("meta", {}).get("leagueKey")
            )
        except Exception:  # noqa: BLE001
            loaded_key = None
        if loaded_key and loaded_key != cfg.key:
            raise LeagueResolutionError(
                503, "data_not_ready",
                f"No data loaded for league {cfg.key!r} yet",
            )
    return cfg
_KTC_TOTAL_PICKS = 72  # fill rookie data for all 6 rounds (12 teams × 6 rounds)
DRAFT_TOTAL_BUDGET = 1200  # $100 × 12 teams

# Cache for KTC live data: {"rookies": [...], "fetched_at": timestamp}
_ktc_cache = {"rookies": None, "fetched_at": 0}
_KTC_CACHE_TTL = 6 * 3600  # 6 hours


import math
import re


def _ktc_decay_curve(known_rookies, total_picks=72):
    """Extend rookie KTC values to `total_picks` using an exponential decay curve.

    Fits an exponential decay  value = A * e^(-k * pick)  to the known data points,
    then extrapolates for any missing picks beyond what KTC provides.
    If fewer than `total_picks` rookies exist from KTC, synthetic entries are
    generated with the curve values and placeholder names.
    """
    if not known_rookies:
        return known_rookies

    # Already have enough rookies
    if len(known_rookies) >= total_picks:
        return known_rookies[:total_picks]

    # Fit exponential decay: ln(value) = ln(A) - k * pick
    # Use first and last known data points for a robust fit
    v1 = known_rookies[0]["value"]
    vn = known_rookies[-1]["value"]
    n = len(known_rookies)

    if v1 <= 0 or vn <= 0 or n < 2:
        return known_rookies

    # k = (ln(v1) - ln(vn)) / (n - 1)
    k = (math.log(v1) - math.log(vn)) / (n - 1)
    A = v1 * math.exp(k)  # A = v1 / e^(-k*0) adjusted so pick index 0 → v1

    extended = list(known_rookies)
    for i in range(n, total_picks):
        projected_value = max(1, int(round(A * math.exp(-k * i))))
        extended.append({
            "name": f"Rookie #{i + 1}",
            "pos": "—",
            "value": projected_value,
        })
    return extended


def _fetch_ktc_rookies_live():
    """Try to scrape KTC rookie rankings from keeptradecut.com.

    Parses the HTML for player entries with class 'onePlayer'.
    Returns list of {"name", "pos", "value"} or None on failure.
    """
    import html.parser

    url = "https://keeptradecut.com/dynasty-rankings/rookie-rankings"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=15)
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
        page_html = raw.decode(charset, errors="replace")
    except Exception as e:
        logging.info(f"KTC live fetch failed: {e}")
        return None

    # Parse player data from HTML — KTC uses divs with class "onePlayer"
    # Each player has: .player-name (a tag text), .position, .value
    rookies = []

    class KTCParser(html.parser.HTMLParser):
        def __init__(self):
            super().__init__()
            self._in_player = False
            self._in_name = False
            self._in_pos = False
            self._in_value = False
            self._current = {}

        def handle_starttag(self, tag, attrs):
            cls = dict(attrs).get("class", "")
            if "onePlayer" in cls:
                self._in_player = True
                self._current = {}
            elif self._in_player:
                if "player-name" in cls:
                    self._in_name = True
                elif cls.strip() == "position":
                    self._in_pos = True
                elif cls.strip() == "value":
                    self._in_value = True

        def handle_data(self, data):
            text = data.strip()
            if not text:
                return
            if self._in_name:
                self._current["name"] = self._current.get("name", "") + text
            elif self._in_pos:
                self._current["pos"] = text
            elif self._in_value:
                self._current["value_str"] = text

        def handle_endtag(self, tag):
            if self._in_name and tag == "a":
                self._in_name = False
            elif self._in_pos and tag in ("span", "div", "p"):
                self._in_pos = False
            elif self._in_value and tag in ("span", "div", "p"):
                self._in_value = False
            elif self._in_player and tag == "div":
                # Try to finalize this player
                name = self._current.get("name", "").strip()
                pos = self._current.get("pos", "").strip()
                val_str = self._current.get("value_str", "").strip().replace(",", "")
                if name and val_str:
                    # Clean team suffix from name (e.g. "Player NAMEnyj" -> "Player NAME")
                    # KTC appends 2-3 letter team codes or "FA"/"RFA"/"R" suffix
                    clean_name = re.sub(r'\s+(FA|RFA|R|[A-Z]{2,3})$', '', name)
                    try:
                        value = int(val_str)
                        if value > 0:
                            # Filter to fantasy-relevant positions
                            pos_upper = pos.upper()
                            if any(p in pos_upper for p in ("QB", "RB", "WR", "TE")):
                                rookies.append({"name": clean_name or name, "pos": pos, "value": value})
                    except ValueError:
                        pass
                self._in_player = False

    try:
        parser = KTCParser()
        parser.feed(page_html)
    except Exception as e:
        logging.warning(f"KTC HTML parse failed: {e}")
        return None

    if len(rookies) < 5:
        logging.info(f"KTC parse returned only {len(rookies)} rookies, likely blocked")
        return None

    # Sort by value descending (should already be, but ensure)
    rookies.sort(key=lambda r: -r["value"])
    logging.info(f"KTC live: fetched {len(rookies)} rookies (top: {rookies[0]['name']} = {rookies[0]['value']})")
    return rookies


def _get_ktc_rookies():
    """Get KTC rookie rankings: try live fetch (cached 6h), fall back to CSV."""
    now = time.time()

    # Return cache if fresh
    if _ktc_cache["rookies"] is not None and (now - _ktc_cache["fetched_at"]) < _KTC_CACHE_TTL:
        return _ktc_cache["rookies"]

    # Try live fetch
    live = _fetch_ktc_rookies_live()
    if live:
        _ktc_cache["rookies"] = live
        _ktc_cache["fetched_at"] = now
        return live

    # Fall back to CSV
    csv_rookies = _parse_csv_rookies()
    if csv_rookies:
        logging.info(f"Using CSV fallback: {len(csv_rookies)} rookies")
        return csv_rookies

    return []


def _parse_csv_rookies():
    """Parse rookie rankings from the draft data CSV (cols 22-25)."""
    import csv
    if not DRAFT_DATA_CSV.exists():
        return []
    try:
        with open(DRAFT_DATA_CSV, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
    except Exception:
        return []

    rookies = []
    rank_header_idx = None
    for i, row in enumerate(rows):
        if len(row) > 22 and row[22].strip() == "Rank":
            rank_header_idx = i
            break
    if rank_header_idx is not None:
        for row in rows[rank_header_idx + 1:]:
            if len(row) < 26:
                continue
            rank_str = row[22].strip() if row[22] else ""
            player = row[23].strip() if row[23] else ""
            pos = row[24].strip() if row[24] else ""
            value_str = row[25].strip() if row[25] else ""
            if not rank_str or not player:
                continue
            try:
                int(rank_str)
                value = int(value_str)
            except (ValueError, TypeError):
                continue
            if value > 0:
                rookies.append({"name": player, "pos": pos, "value": value})
    return rookies


def _parse_draft_xlsx():
    """Read the Draft Data workbook (.xlsx) directly for exact decimal
    values.  Returns (pick_dollars, workbook_picks, slot_to_original, wb_team_totals)
    or None if unavailable.

    Cell references (1-indexed Excel columns):
        P2:AA7   — round/pick value grid (raw per-slot values)
        Q45:Q116 — final per-pick dollar values (post-expansion-averaging)
        R45:R116 — final per-pick owners
        O30:R42  — standings (slot → original owner)
        T63:U74  — team totals (authoritative)
    """
    try:
        import openpyxl
    except ImportError:
        logging.warning("openpyxl not installed — falling back to CSV")
        return None

    if not DRAFT_DATA_XLSX.exists():
        return None

    try:
        wb = openpyxl.load_workbook(DRAFT_DATA_XLSX, data_only=True)
    except Exception as e:
        logging.warning(f"Could not open {DRAFT_DATA_XLSX}: {e}")
        return None

    ws = wb["Draft Data"]

    # ── Raw per-slot values from the grid P2:AA7 (pre-expansion) ──
    pick_dollars: list[float] = []
    for row in range(2, 8):
        for col in range(16, 28):  # P=16 .. AA=27
            v = ws.cell(row, col).value
            pick_dollars.append(float(v) if v is not None else 0.0)

    # ── Final pick assignments Q45:R116 ──
    workbook_picks: list[dict] = []
    for row in range(45, 117):
        rnd = ws.cell(row, 15).value   # O
        pk  = ws.cell(row, 16).value   # P
        val = ws.cell(row, 17).value   # Q
        own = ws.cell(row, 18).value   # R
        if rnd is None or pk is None or val is None or own is None:
            continue
        workbook_picks.append({
            "round": int(rnd), "pick": int(pk),
            "value": float(val), "owner": str(own).strip(),
        })

    # ── Standings O30:R42 — slot → original owner ──
    slot_to_original_owner: dict[int, str] = {}
    for row in range(30, 43):
        owner = ws.cell(row, 16).value  # P = Owner
        slot  = ws.cell(row, 18).value  # R = Pick #
        if owner and slot is not None:
            try:
                slot_to_original_owner[int(slot)] = str(owner).strip()
            except (ValueError, TypeError):
                pass

    # ── Team totals T63:U74 ──
    workbook_team_totals: dict[str, float] = {}
    for row in range(63, 75):
        team = ws.cell(row, 20).value  # T
        val  = ws.cell(row, 21).value  # U
        if team and val is not None:
            workbook_team_totals[str(team).strip()] = float(val)

    wb.close()
    return pick_dollars, workbook_picks, slot_to_original_owner, workbook_team_totals


def _parse_draft_csv_fallback():
    """Parse the draft data CSV (legacy fallback when .xlsx is unavailable).
    Returns (pick_dollars, workbook_picks, slot_to_original, wb_totals) or None.
    """
    import csv
    if not DRAFT_DATA_CSV.exists():
        return None
    try:
        with open(DRAFT_DATA_CSV, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
    except Exception:
        return None

    pick_dollars: list[float] = []
    for row in rows[1:]:
        if len(row) < 12:
            continue
        pick_str = row[0].strip() if row[0] else ""
        val_str = row[11].strip() if row[11] else ""
        if not pick_str or not val_str:
            break
        try:
            pick_dollars.append(float(val_str))
        except (ValueError, TypeError):
            break

    workbook_picks: list[dict] = []
    slot_to_original_owner: dict[int, str] = {}
    in_picks, in_standings = False, False
    for row in rows:
        if len(row) <= 17:
            continue
        c14, c15, c16, c17 = [(row[i].strip() if row[i] else "") for i in (14, 15, 16, 17)]
        if c14 == "Round" and c15 == "Pick" and c16 == "Value" and c17 == "Owner":
            in_picks, in_standings = True, False
            continue
        if c14 == "Standings":
            in_standings, in_picks = True, False
            continue
        if in_standings and c14 and c15 and c17:
            try:
                slot_to_original_owner[int(c17)] = c15
            except (ValueError, TypeError):
                pass
            continue
        if in_picks:
            if not c14:
                in_picks = False
                continue
            try:
                rnd, pk, val = int(c14), int(c15), float(c16)
                if rnd >= 1 and pk >= 1 and c17:
                    workbook_picks.append({"round": rnd, "pick": pk, "value": val, "owner": c17})
            except (ValueError, TypeError):
                continue

    wb_totals: dict[str, float] = {}
    in_team = False
    for row in rows:
        if len(row) <= 20:
            continue
        c19 = (row[19].strip() if row[19] else "")
        c20 = (row[20].strip() if row[20] else "")
        if c19 == "Team" and c20.startswith("Auction"):
            in_team = True
            continue
        if in_team:
            if not c19 or not c20:
                in_team = False
                continue
            try:
                wb_totals[c19] = float(c20)
            except (ValueError, TypeError):
                in_team = False

    return pick_dollars, workbook_picks, slot_to_original_owner, wb_totals


def _parse_draft_data():
    """Read draft capital data from the workbook (.xlsx preferred) or CSV.
    Returns (pick_dollars, workbook_picks, slot_to_original, wb_team_totals, rookies).
    """
    result = _parse_draft_xlsx()
    if result is None:
        result = _parse_draft_csv_fallback()
    if result is None:
        return [], [], {}, {}, []

    pick_dollars, workbook_picks, slot_to_original, wb_totals = result

    rookies = _get_ktc_rookies()
    rookies = _ktc_decay_curve(rookies, _KTC_TOTAL_PICKS)

    return pick_dollars, workbook_picks, slot_to_original, wb_totals, rookies


def _round_to_budget(values: list[float], budget: int = 1200) -> list[int]:
    """Round a list of floats to integers that sum to exactly *budget*.

    Uses largest-remainder rounding: floor each value, then distribute
    the deficit to the values with the largest fractional parts.
    """
    import math
    floors = [math.floor(v) for v in values]
    remainders = [(v - math.floor(v), i) for i, v in enumerate(values)]
    deficit = budget - sum(floors)
    # Sort by fractional part descending; break ties by index
    remainders.sort(key=lambda x: (-x[0], x[1]))
    for k in range(int(deficit)):
        floors[remainders[k][1]] += 1
    return floors


def _fetch_draft_capital(league_key: str | None = None):
    """Compute draft capital per team.

    The Draft Data workbook is the authoritative source for BOTH pick
    values AND pick ownership:

        Q45:Q116 — per-pick dollar values (decimal, sum = 1200)
        R45:R116 — per-pick current owner (first name)
        O30:R42  — standings: slot → original owner (first name)

    Sleeper is used only to resolve the sheet's first-name owners into
    display team names (``user.metadata.team_name`` / ``display_name``)
    by joining the sheet's standings on Sleeper's draft
    ``slot_to_roster_id``.  If Sleeper is unavailable we fall back to
    showing first names directly.

    ``league_key`` selects which league's Sleeper IDs to use for the
    team-name join.  None resolves to the registry default.
    """
    pick_dollars, workbook_picks, slot_to_original, wb_team_totals, rookies = _parse_draft_data()
    if not workbook_picks:
        return {"error": "Draft data workbook not found or empty"}

    current_year = datetime.now(timezone.utc).year
    num_teams = len(slot_to_original) or 12
    draft_rounds = max(1, len(workbook_picks) // num_teams)
    raw_values = [wp["value"] for wp in workbook_picks]
    int_pick_values = _round_to_budget(raw_values, DRAFT_TOTAL_BUDGET)

    # ── First-name → Sleeper team-name mapping ──
    # Built by joining sheet standings (slot → first name) with
    # Sleeper's draft slot_to_roster_id (slot → roster id → team name).
    first_name_to_team: dict[str, str] = {}
    all_team_names: list[str] = []
    try:
        _league_id_for_draft = _sleeper_league_id_for_draft(league_key)
        if not _league_id_for_draft:
            # No league configured at all — skip the Sleeper joins and
            # leave the mapping empty; downstream code renders draft
            # capital without a team-name column.
            raise RuntimeError("no_sleeper_league_configured")
        rosters_resp = urllib.request.urlopen(
            f"https://api.sleeper.app/v1/league/{_league_id_for_draft}/rosters", timeout=15
        )
        rosters = json.loads(rosters_resp.read())

        users_resp = urllib.request.urlopen(
            f"https://api.sleeper.app/v1/league/{_league_id_for_draft}/users", timeout=15
        )
        user_map: dict[str, str] = {}
        for u in json.loads(users_resp.read()):
            uid = u.get("user_id")
            user_map[uid] = (u.get("metadata", {}).get("team_name")
                             or u.get("display_name")
                             or f"Team {uid}")

        roster_name_by_id: dict[int, str] = {}
        owner_to_roster_id: dict[str, int] = {}
        for r in rosters:
            rid = r.get("roster_id")
            if rid is None:
                continue
            rid = int(rid)
            oid = r.get("owner_id", "")
            if oid:
                owner_to_roster_id[str(oid)] = rid
            roster_name_by_id[rid] = user_map.get(oid, f"Team {rid}")
        all_team_names = list(roster_name_by_id.values())

        drafts_resp = urllib.request.urlopen(
            f"https://api.sleeper.app/v1/league/{_league_id_for_draft}/drafts", timeout=15
        )
        slot_to_roster: dict[int, int] = {}
        for draft in json.loads(drafts_resp.read()):
            try:
                season = int(draft.get("season"))
            except (TypeError, ValueError):
                continue
            draft_id = draft.get("draft_id")
            if season != current_year or not draft_id:
                continue
            try:
                detail_resp = urllib.request.urlopen(
                    f"https://api.sleeper.app/v1/draft/{draft_id}", timeout=15
                )
                draft_detail = json.loads(detail_resp.read())
            except Exception:
                draft_detail = {}
            slot_map = draft_detail.get("slot_to_roster_id") or draft.get("slot_to_roster_id") or {}
            if isinstance(slot_map, dict):
                for slot, rid_val in slot_map.items():
                    try:
                        s, rv = int(slot), int(rid_val)
                    except (TypeError, ValueError):
                        continue
                    if s > 0 and rv in roster_name_by_id:
                        slot_to_roster[s] = rv
            if not slot_to_roster:
                draft_order = draft_detail.get("draft_order") or draft.get("draft_order") or {}
                if isinstance(draft_order, dict):
                    for uid, slot in draft_order.items():
                        rid = owner_to_roster_id.get(str(uid))
                        try:
                            s = int(slot)
                        except (TypeError, ValueError):
                            continue
                        if rid in roster_name_by_id and s > 0:
                            slot_to_roster[s] = rid

        for slot, first_name in slot_to_original.items():
            rid = slot_to_roster.get(int(slot))
            if rid is not None and first_name:
                first_name_to_team[str(first_name).strip()] = roster_name_by_id[rid]

    except Exception as e:
        logging.warning(f"Sleeper API failed for draft capital team-name mapping: {e}")

    def display(first_name) -> str:
        fn = str(first_name).strip() if first_name else ""
        return first_name_to_team.get(fn, fn) if fn else "Unknown"

    # ── Build pick list + team totals from sheet ownership ──
    all_picks: list[dict] = []
    team_totals_decimal: dict[str, float] = {}

    # Seed every known team at $0 so teams that own no picks still
    # show up in the output (the /draft dashboard relies on this to
    # render the full 12-team roster).
    if all_team_names:
        for t in all_team_names:
            team_totals_decimal.setdefault(t, 0.0)
    else:
        for first_name in slot_to_original.values():
            team_totals_decimal.setdefault(display(first_name), 0.0)

    for overall_idx, wp in enumerate(workbook_picks):
        rnd = wp["round"]
        slot = wp["pick"]
        val = wp["value"]
        owner_first = wp["owner"]
        origin_first = slot_to_original.get(slot, owner_first)

        owner_team = display(owner_first)
        origin_team = display(origin_first)

        dollar = int_pick_values[overall_idx] if overall_idx < len(int_pick_values) else int(round(val))

        all_picks.append({
            "pick": f"{rnd}.{str(slot).zfill(2)}",
            "round": rnd,
            "pickInRound": slot,
            "overallPick": overall_idx + 1,
            "dollarValue": dollar,
            "adjustedDollarValue": dollar,
            "originalOwner": origin_team,
            "currentOwner": owner_team,
            "isTraded": str(origin_first).strip() != str(owner_first).strip(),
            "isExpansion": slot <= 2,
            "rookieName": None,
            "rookiePos": None,
            "rookieKtcValue": None,
        })
        team_totals_decimal.setdefault(owner_team, 0.0)
        team_totals_decimal[owner_team] += float(val)

    # Round team totals to integers summing to exactly 1200, matching the
    # workbook's SUMIF-over-decimals approach.
    team_names = sorted(team_totals_decimal, key=lambda t: -team_totals_decimal[t])
    team_decimal_list = [team_totals_decimal[t] for t in team_names]
    team_int_list = _round_to_budget(team_decimal_list, DRAFT_TOTAL_BUDGET)
    team_totals = {t: v for t, v in zip(team_names, team_int_list)}
    total_budget = sum(team_int_list)

    # Fill rookie rankings (from KTC live or CSV fallback, extended via decay curve)
    for i, pick in enumerate(all_picks):
        if i < len(rookies):
            pick["rookieName"] = rookies[i]["name"]
            pick["rookiePos"] = rookies[i]["pos"]
            pick["rookieKtcValue"] = rookies[i]["value"]

    sorted_teams = sorted(team_totals.items(), key=lambda x: -x[1])

    # KTC data source info
    ktc_source = "live" if (_ktc_cache["rookies"] is not None and (time.time() - _ktc_cache["fetched_at"]) < _KTC_CACHE_TTL) else "csv"
    ktc_count = len([r for r in rookies if not r["name"].startswith("Rookie #")]) if rookies else 0

    return {
        "picks": all_picks,
        "teamTotals": [{"team": t, "auctionDollars": v} for t, v in sorted_teams],
        "totalBudget": total_budget,
        "numTeams": num_teams,
        "draftRounds": draft_rounds,
        "season": current_year,
        "ktcSource": ktc_source,
        "ktcRookieCount": ktc_count,
        "ktcTotalFilled": len(rookies),
    }


@app.get("/api/draft-capital")
async def get_draft_capital(request: Request, refresh: str = ""):
    """Return draft capital breakdown per team using Sleeper pick ownership
    and the pick value curve from the draft data spreadsheet.

    Accepts ``?leagueKey=...`` to scope the Sleeper roster + users +
    drafts calls to a specific league; absent, falls through to the
    user's saved pref and then the registry default.  Unknown or
    inactive keys return 400.

    The pick-value Excel workbook (``CSVs/Draft Data.xlsx``) is
    wired to the default league's draft — per-team budgets,
    carry-over balances, and standings all reflect that league's
    actual data.  Non-default leagues 501 with
    ``not_configured_for_league`` rather than serving league-A
    numbers under league-B's team names.  Angle-finder + roster
    picks still work across leagues via the Sleeper overlay; only
    the workbook-sourced budget column is league-specific.

    Pass ``?refresh=1`` to force a fresh KTC fetch."""
    try:
        league_cfg = _resolve_league_for_request(request)
    except LeagueResolutionError as err:
        return err.json_response()
    default_cfg = _league_registry.get_default_league()
    is_default_league = default_cfg and league_cfg.key == default_cfg.key
    if refresh:
        _ktc_cache["fetched_at"] = 0  # invalidate cache
    try:
        if is_default_league:
            # Workbook path — rich per-pick values pinned to League A's
            # rookie pool.
            result = _fetch_draft_capital(league_cfg.key)
        else:
            # Sleeper-derived fallback for non-default leagues.
            # Uses the canonical contract's pick values (Hill-curve-
            # calibrated) + Sleeper's traded_picks.  Clearly labeled
            # in the UI so users see "Sleeper-derived" vs.
            # "workbook-calibrated".
            from src.api.draft_capital_fallback import build_sleeper_derived
            result = build_sleeper_derived(
                league_cfg.sleeper_league_id,
                latest_contract_data or {},
                current_season=datetime.now(timezone.utc).year,
                num_teams=league_cfg.roster_settings.get("teamCount", 12) if hasattr(league_cfg, "roster_settings") else 12,
            )
        if isinstance(result, dict):
            result["leagueKey"] = league_cfg.key
        return JSONResponse(content=result)
    except Exception as e:
        logging.error(f"Draft capital computation failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Draft capital computation failed: {str(e)}"}
        )


# ── PUBLIC LEAGUE ROUTES ───────────────────────────────────────────────
# The /api/public/league* endpoints serve the public /league page.
# They are intentionally fork-isolated from the private canonical
# pipeline — no dependence on latest_data / latest_contract_data, no
# private ranking / valuation signals.  The public contract is
# assembled in src/public_league/public_contract.py and runs through
# an allowlist guard before it is serialized.
from src.public_league import (  # noqa: E402 — grouped after route block above
    PUBLIC_SECTION_KEYS,
    build_public_contract,
    build_public_snapshot,
    build_section_payload,
)
from src.public_league.public_contract import assert_public_payload_safe
from src.public_league.sleeper_client import PUBLIC_MAX_SEASONS
from src.public_league import snapshot_store as public_snapshot_store
from src.public_league import csv_export as public_csv_export
from src.public_league import matchup_recap as public_matchup_recap
from src.public_league import player_journey as public_player_journey

_PUBLIC_LEAGUE_CACHE_TTL_SECONDS = int(os.getenv("PUBLIC_LEAGUE_CACHE_TTL", "300"))
_PUBLIC_LEAGUE_PERSIST = _env_bool("PUBLIC_LEAGUE_PERSIST_SNAPSHOT", True)
_PUBLIC_LEAGUE_WARMUP = _env_bool("PUBLIC_LEAGUE_WARMUP_AT_STARTUP", True)


from src.api.public_activity_valuation import (
    build_valuation_from_contract as _build_valuation_from_contract,
)


def _build_public_activity_valuation():
    """Build a valuation callable for the public activity trade feed.

    Reads the cached private canonical contract (``latest_contract_data``)
    and returns a callable ``(asset_dict) -> float``.  The public
    activity section uses this callable server-side to compute trade
    letter grades on the public timeline.  The raw values themselves
    never leave the backend — only the derived ``{grade, color,
    label}`` block is emitted on the public payload.

    Returns ``None`` when the private contract is unavailable (fresh
    server, scraper failure).  In that case the public activity feed
    ships without grade annotations.

    The actual contract parsing lives in
    ``src.api.public_activity_valuation.build_valuation_from_contract``
    so it can be unit-tested without pulling in FastAPI.
    """
    return _build_valuation_from_contract(latest_contract_data)
_public_league_cache: dict = {
    "snapshot": None,
    "snapshot_league_id": None,
    "fetched_at": 0.0,
    "refreshing": False,
}
_public_league_refresh_lock = threading.Lock()

# Observability counters for the public-league snapshot cache.  Logged
# at every serve path via ``_log_public_league_event`` so the uptime
# watchdog + log-scraping tooling can track cold-fetch regressions, the
# cache hit ratio, and thundering-herd refresh suppression.
_public_league_metrics: dict = {
    "cache_hit": 0,
    "cache_stale_served": 0,
    "cache_miss_cold_rebuild": 0,
    "force_refresh": 0,
    "background_refresh_started": 0,
    "background_refresh_suppressed": 0,
    "rebuild_count": 0,
    "rebuild_failures": 0,
    "total_rebuild_seconds": 0.0,
    "last_rebuild_seconds": None,
    "last_rebuild_iso": None,
    "last_contract_bytes": None,
    "last_season_count": None,
    "last_manager_count": None,
}


def _log_public_league_event(event: str, **fields) -> None:
    """Emit a single structured log line for a public_league event.

    Keeps the shape ``public_league_event=<name> key=value ...`` so a
    log shipper can ingest it directly without regex-wrangling.  All
    values are JSON-stringified for safety.
    """
    parts = [f"public_league_event={event}"]
    for key, value in fields.items():
        try:
            rendered = json.dumps(value, default=str)
        except (TypeError, ValueError):
            rendered = json.dumps(str(value))
        parts.append(f"{key}={rendered}")
    logging.info(" ".join(parts))


def _public_league_metrics_snapshot() -> dict:
    """Copy of the metrics dict safe to ship out of the process."""
    snap = dict(_public_league_metrics)
    # Derived fields.
    total = (
        snap["cache_hit"]
        + snap["cache_stale_served"]
        + snap["cache_miss_cold_rebuild"]
    )
    snap["total_served"] = total
    snap["cache_hit_ratio"] = (
        round(snap["cache_hit"] / total, 4) if total else None
    )
    snap["avg_rebuild_seconds"] = (
        round(snap["total_rebuild_seconds"] / snap["rebuild_count"], 4)
        if snap["rebuild_count"]
        else None
    )
    return snap

# Best-effort: load the most recent persisted snapshot at process
# start so a cold-started server can still serve the public /league
# page while the first Sleeper rebuild is running in the background.
try:
    _persisted = public_snapshot_store.load_snapshot()
    if _persisted is not None and _persisted.seasons:
        _public_league_cache["snapshot"] = _persisted
        _public_league_cache["snapshot_league_id"] = _persisted.root_league_id
        _public_league_cache["fetched_at"] = 0.0  # forces refresh on next hit
        logging.info(
            "Loaded persisted public_league snapshot for league %s (%d seasons)",
            _persisted.root_league_id,
            len(_persisted.seasons),
        )
except Exception as _exc:  # noqa: BLE001
    logging.warning("Public league snapshot load at startup failed: %s", _exc)


def _public_league_id() -> str:
    """Return the current public-facing league id.

    Routes through the league registry (``league_registry``) so that
    the ID comes from ``config/leagues/registry.json`` when present
    and from ``SLEEPER_LEAGUE_ID`` env var as a back-compat fallback.
    Returns empty string when no league is configured — callers that
    immediately hit Sleeper should treat that as "no snapshot
    available" rather than calling ``/league/`` with an empty path.
    """
    sid = _league_registry.get_sleeper_league_id()
    return (sid or "").strip()


def _rebuild_public_snapshot(league_id: str, *, trigger: str = "sync"):
    """Synchronously rebuild the public snapshot for ``league_id``.

    Guarded by ``_public_league_refresh_lock`` so a burst of requests
    while the background refresh is running doesn't multiply work.
    """
    with _public_league_refresh_lock:
        now = time.time()
        cached = _public_league_cache.get("snapshot")
        cached_id = _public_league_cache.get("snapshot_league_id")
        fetched_at = float(_public_league_cache.get("fetched_at") or 0.0)
        # If another thread just refreshed while we were waiting on the
        # lock, reuse that work.
        if (
            cached is not None
            and cached_id == league_id
            and (now - fetched_at) < _PUBLIC_LEAGUE_CACHE_TTL_SECONDS
        ):
            _log_public_league_event(
                "refresh_deduped",
                trigger=trigger,
                league_id=league_id,
            )
            return cached
        started = time.time()
        snapshot = None
        error = None
        try:
            snapshot = build_public_snapshot(league_id, max_seasons=PUBLIC_MAX_SEASONS)
        except Exception as exc:  # noqa: BLE001
            error = exc
            _public_league_metrics["rebuild_failures"] += 1
            _log_public_league_event(
                "rebuild_failed",
                trigger=trigger,
                league_id=league_id,
                error=str(exc),
            )
            raise
        finally:
            _public_league_cache["refreshing"] = False

        elapsed = round(time.time() - started, 4)
        _public_league_cache["snapshot"] = snapshot
        _public_league_cache["snapshot_league_id"] = league_id
        _public_league_cache["fetched_at"] = time.time()
        _public_league_metrics["rebuild_count"] += 1
        _public_league_metrics["total_rebuild_seconds"] += elapsed
        _public_league_metrics["last_rebuild_seconds"] = elapsed
        _public_league_metrics["last_rebuild_iso"] = _utc_now_iso()
        _public_league_metrics["last_season_count"] = len(snapshot.seasons)
        _public_league_metrics["last_manager_count"] = len(snapshot.managers.by_owner_id)

        contract_bytes = None
        if _PUBLIC_LEAGUE_PERSIST and snapshot.seasons:
            try:
                contract = build_public_contract(
                    snapshot,
                    activity_valuation=_build_public_activity_valuation(),
                )
                public_snapshot_store.persist_snapshot(snapshot, contract=contract)
                contract_bytes = len(json.dumps(contract).encode("utf-8"))
                _public_league_metrics["last_contract_bytes"] = contract_bytes
            except Exception as exc:  # noqa: BLE001
                logging.warning("Failed to persist public_league snapshot: %s", exc)

        _log_public_league_event(
            "rebuild_complete",
            trigger=trigger,
            league_id=league_id,
            elapsed_seconds=elapsed,
            seasons=len(snapshot.seasons),
            managers=len(snapshot.managers.by_owner_id),
            contract_bytes=contract_bytes,
        )
        return snapshot


def _kick_background_refresh(league_id: str, *, trigger: str = "stale-while-revalidate"):
    """Start a daemon thread that refreshes the public snapshot in the
    background.  No-op if another refresh is already running."""
    if _public_league_cache.get("refreshing"):
        _public_league_metrics["background_refresh_suppressed"] += 1
        return
    _public_league_cache["refreshing"] = True
    _public_league_metrics["background_refresh_started"] += 1
    _log_public_league_event(
        "background_refresh_started",
        trigger=trigger,
        league_id=league_id,
    )

    def _worker():
        try:
            _rebuild_public_snapshot(league_id, trigger=trigger)
        except Exception as exc:  # noqa: BLE001
            logging.warning("Background public_league refresh failed: %s", exc)
        finally:
            _public_league_cache["refreshing"] = False

    threading.Thread(
        target=_worker,
        name="public-league-warmup",
        daemon=True,
    ).start()


def _get_public_snapshot(force_refresh: bool = False):
    """Return (possibly cached) public snapshot for the current league.

    Stale-while-revalidate behavior: if a cached snapshot exists but
    has passed TTL, we still return the stale payload immediately and
    kick a background refresh.  The NEXT request gets the fresh data.
    First-request latency is therefore bounded by whatever the client
    already has on disk, not by the Sleeper fetch time.

    ``force_refresh`` bypasses this and blocks on a fresh fetch —
    used by the manual ``?refresh=1`` query and the warmup path.
    """
    league_id = _public_league_id()
    now = time.time()
    cached = _public_league_cache.get("snapshot")
    cached_id = _public_league_cache.get("snapshot_league_id")
    fetched_at = float(_public_league_cache.get("fetched_at") or 0.0)
    fresh = (
        cached is not None
        and cached_id == league_id
        and (now - fetched_at) < _PUBLIC_LEAGUE_CACHE_TTL_SECONDS
    )
    if fresh and not force_refresh:
        _public_league_metrics["cache_hit"] += 1
        return cached
    if force_refresh:
        _public_league_metrics["force_refresh"] += 1
        return _rebuild_public_snapshot(league_id, trigger="force-refresh")
    # Stale-but-serveable: return the cached payload and refresh in
    # the background so subsequent requests get fresh data.
    if cached is not None and cached_id == league_id:
        _public_league_metrics["cache_stale_served"] += 1
        _kick_background_refresh(league_id)
        return cached
    # Cold start — block on a sync rebuild.
    _public_league_metrics["cache_miss_cold_rebuild"] += 1
    return _rebuild_public_snapshot(league_id, trigger="cold-start")


def _warmup_public_snapshot():
    """Kick a background snapshot rebuild at startup when no warm cache
    was loaded from disk.  Bounded by the same lock as the request-path
    refresher so the first request still benefits.

    Invoked from the FastAPI ``lifespan`` contextmanager (see the
    ``lifespan`` function earlier in this file); do not register it as
    an ``@app.on_event`` handler — that API is deprecated.
    """
    if not _PUBLIC_LEAGUE_WARMUP:
        return
    league_id = _public_league_id()
    if not league_id:
        return
    cached = _public_league_cache.get("snapshot")
    cached_id = _public_league_cache.get("snapshot_league_id")
    needs_refresh = (
        cached is None
        or cached_id != league_id
        or float(_public_league_cache.get("fetched_at") or 0.0) == 0.0
    )
    if not needs_refresh:
        return
    _kick_background_refresh(league_id, trigger="startup-warmup")


_PUBLIC_LEAGUE_CACHE_CONTROL = (
    f"public, max-age=60, stale-while-revalidate={_PUBLIC_LEAGUE_CACHE_TTL_SECONDS}"
)


@app.get("/api/public/league/metrics")
async def get_public_league_metrics():
    """Small, public-safe observability endpoint for the snapshot cache.

    Exposes the counters that ``_log_public_league_event`` has been
    emitting: cache hit ratio, rebuild wall-clock, contract byte-size,
    last rebuild timestamp.  Useful for the uptime watchdog, for
    external dashboards, and for smoke-testing cold-fetch regressions.

    NOTE: no private data — just aggregated counters for the cache.
    """
    snap = _public_league_metrics_snapshot()
    # Diagnostic: is the valuation pipeline wired up right now?  This
    # only surfaces the boolean — never any private values — and lets
    # us answer "why are no grades showing on /league activity?" by
    # hitting one URL.  ``valuationReady=False`` means the public
    # activity feed will ship without grade badges (no asset value
    # source available), which is the documented graceful degradation
    # path; the page itself does not break.
    valuation_ready = _build_public_activity_valuation() is not None
    return JSONResponse(
        content={
            "leagueId": _public_league_id(),
            "cacheTtlSeconds": _PUBLIC_LEAGUE_CACHE_TTL_SECONDS,
            "warmupEnabled": _PUBLIC_LEAGUE_WARMUP,
            "persistEnabled": _PUBLIC_LEAGUE_PERSIST,
            "tradeGrading": {
                "valuationReady": valuation_ready,
                "privateContractLoaded": latest_contract_data is not None,
                "privateContractPlayerCount": int(
                    (latest_contract_data or {}).get("playerCount") or 0
                ),
            },
            "metrics": snap,
        },
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/public/league")
async def get_public_league(refresh: str = ""):
    """Full public league contract — every section + league header.

    This endpoint is intentionally separate from /api/data.  It never
    reads the private canonical pipeline, never exposes private
    rankings / edge signals, and runs through an allowlist guard
    before serialization.
    """
    try:
        snapshot = _get_public_snapshot(force_refresh=bool(refresh))
        payload = build_public_contract(
            snapshot,
            activity_valuation=_build_public_activity_valuation(),
        )
        assert_public_payload_safe(payload)
        return JSONResponse(
            content=payload,
            headers={"Cache-Control": _PUBLIC_LEAGUE_CACHE_CONTROL},
        )
    except AssertionError as exc:
        logging.error("Public league contract tripped safety assert: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": "Public league contract safety violation."},
        )
    except Exception as exc:  # noqa: BLE001
        logging.error("Public league contract build failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"error": f"Public league data unavailable: {exc}"},
        )


@app.get("/api/public/league/matchup/{season}/{week}/{matchup_id}")
async def get_public_league_matchup(
    season: str,
    week: int,
    matchup_id: int,
    refresh: str = "",
):
    """Per-matchup public recap — full lineups, scoring, pre-week standings.

    ``season`` is the season year string (e.g. ``"2025"``).
    Runs through the same safety allowlist as the rest of the contract.
    """
    try:
        snapshot = _get_public_snapshot(force_refresh=bool(refresh))
        recap = public_matchup_recap.build_matchup_recap(
            snapshot, season, int(week), int(matchup_id),
        )
        if recap is None:
            return JSONResponse(
                status_code=404,
                content={
                    "error": f"No matchup found at season={season} week={week} matchup_id={matchup_id}",
                },
            )
        payload = {
            "contractVersion": "public-league-matchup/2026-04-17.v1",
            "league": {
                "rootLeagueId": snapshot.root_league_id,
                "currentLeagueId": snapshot.current_season.league_id if snapshot.current_season else "",
                "leagueName": str((snapshot.current_season.league or {}).get("name") or "") if snapshot.current_season else "",
                "managers": snapshot.managers.to_public_list(),
                "seasonsCovered": snapshot.season_ids,
                "generatedAt": snapshot.generated_at,
            },
            "matchup": recap,
        }
        assert_public_payload_safe(payload)
        return JSONResponse(
            content=payload,
            headers={"Cache-Control": _PUBLIC_LEAGUE_CACHE_CONTROL},
        )
    except AssertionError as exc:
        logging.error("Matchup recap tripped safety assert: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": "Public league contract safety violation."},
        )
    except Exception as exc:  # noqa: BLE001
        logging.error("Matchup recap build failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"error": f"Matchup recap unavailable: {exc}"},
        )


@app.get("/api/public/league/matchups")
async def list_public_league_matchups(refresh: str = ""):
    """Index endpoint — every (season, week, matchup_id) that has a
    scored pair.  Useful for sitemap generation + the index landing."""
    try:
        snapshot = _get_public_snapshot(force_refresh=bool(refresh))
        payload = {
            "seasonsCovered": snapshot.season_ids,
            "matchups": public_matchup_recap.list_matchups(snapshot),
            "generatedAt": snapshot.generated_at,
        }
        assert_public_payload_safe(payload)
        return JSONResponse(
            content=payload,
            headers={"Cache-Control": _PUBLIC_LEAGUE_CACHE_CONTROL},
        )
    except Exception as exc:  # noqa: BLE001
        logging.error("Matchup index failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"error": f"Matchup index unavailable: {exc}"},
        )


@app.get("/api/public/league/player/{player_id}")
async def get_public_league_player(player_id: str, refresh: str = ""):
    """Public player-journey view: every trade, waiver, weekly starter
    slot, per-manager scoring summary for a given Sleeper player_id."""
    try:
        snapshot = _get_public_snapshot(force_refresh=bool(refresh))
        journey = public_player_journey.build_player_journey(snapshot, player_id)
        if journey is None:
            return JSONResponse(
                status_code=404,
                content={"error": f"No public journey data for player_id={player_id!r}"},
            )
        payload = {
            "contractVersion": "public-league-player/2026-04-17.v1",
            "league": {
                "rootLeagueId": snapshot.root_league_id,
                "leagueName": str((snapshot.current_season.league or {}).get("name") or "") if snapshot.current_season else "",
                "managers": snapshot.managers.to_public_list(),
                "seasonsCovered": snapshot.season_ids,
                "generatedAt": snapshot.generated_at,
            },
            "player": journey,
        }
        assert_public_payload_safe(payload)
        return JSONResponse(
            content=payload,
            headers={"Cache-Control": _PUBLIC_LEAGUE_CACHE_CONTROL},
        )
    except AssertionError as exc:
        logging.error("Player journey tripped safety assert: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": "Public league contract safety violation."},
        )
    except Exception as exc:  # noqa: BLE001
        logging.error("Player journey build failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"error": f"Player journey unavailable: {exc}"},
        )


@app.get("/api/public/league/players")
async def list_public_league_players(refresh: str = ""):
    """Index endpoint — every player who appears on a roster or in a
    transaction in the 2-season window.  Lightweight so the frontend
    can build a player-autocomplete."""
    try:
        snapshot = _get_public_snapshot(force_refresh=bool(refresh))
        payload = {
            "seasonsCovered": snapshot.season_ids,
            "players": public_player_journey.list_players_with_activity(snapshot),
            "generatedAt": snapshot.generated_at,
        }
        assert_public_payload_safe(payload)
        return JSONResponse(
            content=payload,
            headers={"Cache-Control": _PUBLIC_LEAGUE_CACHE_CONTROL},
        )
    except Exception as exc:  # noqa: BLE001
        logging.error("Players index failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"error": f"Players index unavailable: {exc}"},
        )


@app.get("/api/public/league/{section}.csv")
async def get_public_league_section_csv(
    section: str,
    owner: str = "",
    kind: str = "",
    refresh: str = "",
):
    """CSV download for any public-league section.

    Matches the JSON endpoint at ``/api/public/league/{section}`` but
    serializes the underlying payload as CSV via ``csv_export``.
    Supports the same ``owner`` qualifier for franchise and a ``kind``
    qualifier for archives (``trades|waivers|weeklyMatchups|rookieDrafts|
    seasonResults|managers``).

    The CSV is generated from the same safety-checked JSON payload the
    /api/public/league route serves, so no new leak surface is added.

    Registered BEFORE the generic /{section} handler so FastAPI's path
    matching resolves the ``.csv`` suffix first.
    """
    if section == "hall_of_fame":
        # Hall of Fame is a derived projection of the history section.
        try:
            snapshot = _get_public_snapshot(force_refresh=bool(refresh))
            history_payload = build_section_payload(snapshot, "history")
            assert_public_payload_safe(history_payload)
            filename, text = public_csv_export.export_hall_of_fame(history_payload["data"])
            return Response(
                content=text,
                media_type="text/csv; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                    "Cache-Control": _PUBLIC_LEAGUE_CACHE_CONTROL,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logging.error("CSV export hall_of_fame failed: %s", exc)
            return JSONResponse(
                status_code=503,
                content={"error": f"CSV export unavailable: {exc}"},
            )

    if section not in PUBLIC_SECTION_KEYS:
        return JSONResponse(
            status_code=404,
            content={
                "error": f"Unknown public league section: {section!r}",
                "availableSections": list(PUBLIC_SECTION_KEYS) + ["hall_of_fame"],
            },
        )
    try:
        snapshot = _get_public_snapshot(force_refresh=bool(refresh))
        payload = build_section_payload(snapshot, section)
        assert_public_payload_safe(payload)
        kwargs = {}
        if section == "franchise" and owner:
            kwargs["owner_id"] = str(owner).strip()
        if section == "archives" and kind:
            kwargs["kind"] = str(kind).strip()
        filename, text = public_csv_export.export_section(
            section, payload["data"], **kwargs
        )
        return Response(
            content=text,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": _PUBLIC_LEAGUE_CACHE_CONTROL,
            },
        )
    except AssertionError as exc:
        logging.error("CSV export safety violation in section %s: %s", section, exc)
        return JSONResponse(
            status_code=500,
            content={"error": "Public league contract safety violation."},
        )
    except Exception as exc:  # noqa: BLE001
        logging.error("CSV export for section %s failed: %s", section, exc)
        return JSONResponse(
            status_code=503,
            content={"error": f"CSV export unavailable: {exc}"},
        )


@app.get("/api/public/league/{section}")
async def get_public_league_section(section: str, owner: str = "", refresh: str = ""):
    """Single public-league section JSON payload.

    ``section`` must be one of ``PUBLIC_SECTION_KEYS``.  When the
    ``franchise`` section is requested with ``?owner=<owner_id>`` we
    also include a narrowed ``franchiseDetail`` block so the frontend
    can render a single franchise page without downloading every
    franchise's detail dict.

    NOTE: the ``.csv`` variant above MUST remain registered before this
    route — FastAPI otherwise matches ``/{section}`` against
    ``history.csv`` with ``section="history.csv"``.
    """
    if section not in PUBLIC_SECTION_KEYS:
        return JSONResponse(
            status_code=404,
            content={"error": f"Unknown public league section: {section!r}",
                     "availableSections": list(PUBLIC_SECTION_KEYS)},
        )
    try:
        snapshot = _get_public_snapshot(force_refresh=bool(refresh))
        payload = build_section_payload(
            snapshot,
            section,
            activity_valuation=_build_public_activity_valuation(),
        )
        if section == "franchise" and owner:
            detail_map = payload.get("data", {}).get("detail") or {}
            payload["franchiseDetail"] = detail_map.get(str(owner).strip())
        assert_public_payload_safe(payload)
        return JSONResponse(
            content=payload,
            headers={"Cache-Control": _PUBLIC_LEAGUE_CACHE_CONTROL},
        )
    except AssertionError as exc:
        logging.error("Public section %s tripped safety assert: %s", section, exc)
        return JSONResponse(
            status_code=500,
            content={"error": "Public league contract safety violation."},
        )
    except Exception as exc:  # noqa: BLE001
        logging.error("Public league section %s failed: %s", section, exc)
        return JSONResponse(
            status_code=503,
            content={"error": f"Public league section unavailable: {exc}"},
        )


@app.post("/api/scrape")
async def trigger_scrape(request: Request, background_tasks: BackgroundTasks):
    """Manually trigger a scrape. Returns immediately; scrape runs in background.

    Accepts optional ``?leagueKey=...`` — today the scraper runs the
    registry's default league regardless, but we still validate the
    key so a multi-league-aware frontend can't accidentally ask for a
    retired league.  A non-default key currently returns 501
    ``not_implemented`` because multi-league scraping isn't wired up
    yet (that's a future refactor of Dynasty Scraper.py).
    """
    # Validate the key first.  Non-default leagues don't run the
    # full ranking scrape (the pipeline is single-league) — instead
    # they refresh the on-demand Sleeper overlay (rosters + trades
    # + pick ownership) so the UI picks up new trades / roster
    # moves without waiting for the 15-min cache to expire.  Same
    # shape of response either way.
    try:
        league_cfg = _resolve_league_for_request(request)
    except LeagueResolutionError as err:
        return err.json_response()
    default_cfg = _league_registry.get_default_league()
    if default_cfg and league_cfg.key != default_cfg.key:
        # Invalidate + rewarm the overlay for this league.  Returns
        # immediately with the refreshed team/trade counts so the
        # UI can show "X trades loaded" right away.
        loaded_sleeper = (
            latest_contract_data.get("sleeper") or {}
            if isinstance(latest_contract_data, dict) else {}
        )
        id_map = loaded_sleeper.get("idToPlayer") if isinstance(loaded_sleeper, dict) else {}
        _sleeper_overlay.invalidate_overlay_cache(league_cfg.sleeper_league_id)
        try:
            overlay = await run_in_threadpool(
                _sleeper_overlay.fetch_sleeper_overlay,
                sleeper_league_id=league_cfg.sleeper_league_id,
                id_to_player=id_map if isinstance(id_map, dict) else {},
                force_refresh=True,
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                status_code=502,
                content={
                    "error": "sleeper_overlay_fetch_failed",
                    "message": f"Sleeper overlay refresh failed: {exc}",
                    "leagueKey": league_cfg.key,
                },
            )
        if not overlay:
            return JSONResponse(
                status_code=502,
                content={
                    "error": "sleeper_overlay_empty",
                    "message": "Overlay fetch succeeded but returned no data.",
                    "leagueKey": league_cfg.key,
                },
            )
        return JSONResponse(content={
            "message": f"Sleeper overlay refreshed for {league_cfg.key!r}.",
            "leagueKey": league_cfg.key,
            "teamCount": len(overlay.get("teams") or []),
            "tradeCount": len(overlay.get("trades") or []),
            "overlayFetchedAt": overlay.get("overlayFetchedAt"),
        })

    status_payload = _scrape_status_payload()
    if status_payload.get("is_running") or scrape_run_lock.locked():
        _record_scrape_event(
            "scrape_request_rejected",
            level="warning",
            message="Manual trigger rejected because scrape is already active",
            stalled=status_payload.get("stalled"),
            current_step=status_payload.get("current_step"),
            current_source=status_payload.get("current_source"),
        )
        return JSONResponse(
            status_code=409,
            content={"error": "Scrape already in progress",
                     "status": status_payload}
        )

    # Run in background so the API returns immediately
    _record_scrape_event("scrape_requested", message="Manual scrape trigger accepted", trigger="manual_api")
    background_tasks.add_task(run_scraper, "manual_api")
    return JSONResponse(content={
        "message": "Scrape started in background",
        "status": _scrape_status_payload(),
    })


@app.post("/api/test-alert")
async def test_alert():
    """Send a test alert email to verify configuration."""
    if not ALERT_ENABLED:
        return JSONResponse(
            status_code=400,
            content={"error": "Alerts not enabled. Set environment variable ALERT_ENABLED=true"}
        )
    try:
        send_alert("Test Alert", "If you're reading this, email alerts are working!")
        return JSONResponse(content={"message": f"Test alert sent to {ALERT_TO}"})
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed: {str(e)}"}
        )


# ── AUTH + ENTRY GATE ROUTES ────────────────────────────────────────────
@app.get("/api/auth/status")
async def auth_status(request: Request):
    session = _get_auth_session(request)
    if not session:
        return JSONResponse(content={"authenticated": False})
    return JSONResponse(
        content={
            "authenticated": True,
            "username": session.get("username"),
            "displayName": session.get("display_name") or session.get("username"),
            "sleeperUserId": session.get("sleeper_user_id") or None,
            "avatar": session.get("avatar") or None,
            "authMethod": session.get("auth_method") or "password",
        }
    )


@app.post("/api/auth/login")
async def auth_login(request: Request):
    payload: dict = {}
    try:
        raw = await request.json()
        if isinstance(raw, dict):
            payload = raw
    except Exception:
        payload = {}

    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    next_path = _sanitize_next_path(payload.get("next"), "/app")

    if username != JASON_LOGIN_USERNAME or password != JASON_LOGIN_PASSWORD:
        return JSONResponse(
            status_code=401,
            content={"ok": False, "error": "Invalid username or password."},
        )

    session_id = _create_auth_session(username, auth_method="password")
    response = JSONResponse(content={"ok": True, "redirect": next_path})
    response.set_cookie(
        key=JASON_AUTH_COOKIE_NAME,
        value=session_id,
        path="/",
        httponly=True,
        samesite="lax",
        secure=JASON_AUTH_COOKIE_SECURE,
    )
    return response


@app.post("/api/auth/sleeper-login")
async def auth_sleeper_login(request: Request):
    """Sign in as any user known to the Sleeper API.

    Flow:
      1. Client POSTs ``{"username": "<sleeper-handle>"}``.
      2. We call https://api.sleeper.app/v1/user/<username> which
         returns ``{user_id, username, display_name, avatar}`` on
         success or 404 for unknown users.
      3. On success, create a session keyed on the Sleeper
         ``user_id`` so the user_kv store partitions per-person
         (not per-handle — Sleeper usernames CAN be changed, IDs
         cannot).
      4. ``useUserState``'s first ``GET /api/user/state`` after
         login hydrates the returned ``username`` → the Sleeper
         handle, and any roster team in the configured league
         whose ``ownerId`` matches ``sleeper_user_id`` becomes the
         default selection on the terminal.

    Security note: this is a trust-on-first-use sign-in — anyone
    who knows a valid Sleeper username can sign in as that user.
    That's fine for a league-scoped tool (your leaguemates know
    if someone claims their identity) but NOT suitable for
    anything with financial or account-recovery exposure.  The
    hardcoded-password admin path at ``/api/auth/login`` stays
    available for operator access.
    """
    payload: dict = {}
    try:
        raw = await request.json()
        if isinstance(raw, dict):
            payload = raw
    except Exception:
        payload = {}

    username = str(payload.get("username") or "").strip().lower()
    next_path = _sanitize_next_path(payload.get("next"), "/app")

    if not username or len(username) > 64:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "Invalid username."},
        )
    if not all(c.isalnum() or c in "_-." for c in username):
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "Invalid username."},
        )

    # Fetch the Sleeper user record.  Run in a threadpool because
    # urllib is sync and we don't want to block the event loop.
    def _fetch() -> dict | None:
        url = f"https://api.sleeper.app/v1/user/{username}"
        req = urllib.request.Request(url, headers={"User-Agent": "brisket-sleeper-login/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                body = resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise
        except (urllib.error.URLError, TimeoutError):
            return None
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(parsed, dict):
            return None
        return parsed

    try:
        user_record = await run_in_threadpool(_fetch)
    except Exception as exc:  # noqa: BLE001
        log.warning("sleeper-login fetch error for %s: %s", username, exc)
        return JSONResponse(
            status_code=502,
            content={"ok": False, "error": "Sleeper API unreachable; try again shortly."},
        )

    if not user_record or not user_record.get("user_id"):
        return JSONResponse(
            status_code=404,
            content={
                "ok": False,
                "error": "No Sleeper user with that username.  Double-check spelling.",
            },
        )

    # Private-app allowlist.  A valid Sleeper handle is necessary but
    # NOT sufficient — the app is a single-user dashboard.  Anyone
    # whose username isn't in PRIVATE_APP_ALLOWED_USERNAMES (default:
    # ``jasonleetucker`` only) gets 403.  Password auth remains the
    # operator fallback.
    if username not in PRIVATE_APP_ALLOWED_USERNAMES:
        log.warning(
            "sleeper-login rejected for non-allowlisted user %r", username,
        )
        return JSONResponse(
            status_code=403,
            content={
                "ok": False,
                "error": "This app is private.  Contact the operator for access.",
            },
        )

    sleeper_user_id = str(user_record.get("user_id") or "")
    display_name = str(user_record.get("display_name") or user_record.get("username") or username)
    avatar = str(user_record.get("avatar") or "")

    # Use the Sleeper username as the session ``username`` so
    # user_kv rows partition per-handle.  Sleeper handles are
    # globally unique and stable-enough for this scope.
    session_id = _create_auth_session(
        username,
        sleeper_user_id=sleeper_user_id,
        display_name=display_name,
        avatar=avatar,
        auth_method="sleeper",
    )
    response = JSONResponse(content={
        "ok": True,
        "redirect": next_path,
        "username": username,
        "displayName": display_name,
        "sleeperUserId": sleeper_user_id,
        "avatar": avatar,
    })
    response.set_cookie(
        key=JASON_AUTH_COOKIE_NAME,
        value=session_id,
        path="/",
        httponly=True,
        samesite="lax",
        secure=JASON_AUTH_COOKIE_SECURE,
    )
    return response


@app.post("/api/auth/logout")
async def auth_logout(request: Request):
    _clear_auth_session(request)
    response = JSONResponse(content={"ok": True})
    response.delete_cookie(key=JASON_AUTH_COOKIE_NAME, path="/")
    return response


@app.get("/logout")
async def auth_logout_redirect(request: Request):
    _clear_auth_session(request)
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie(key=JASON_AUTH_COOKIE_NAME, path="/")
    return response


# ── USER PREFERENCE PERSISTENCE (AUTH-GATED) ────────────────────────────
# Durable per-user state that follows the authenticated session across
# devices.  Backed by SQLite at ``data/user_kv.sqlite`` (see
# ``src/api/user_kv.py``).  Anonymous requests get 401 — the frontend
# hook falls back to a localStorage-only path when unauthenticated, so
# a logged-out visitor still sees defaults without polluting the
# shared store.

@app.get("/api/user/state")
async def get_user_state_api(request: Request):
    session = _get_auth_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"error": "auth_required"})
    username = str(session.get("username") or "").strip()
    state = await run_in_threadpool(_user_kv.get_user_state, username)
    return JSONResponse(
        content={"username": username, "state": state},
        headers={"Cache-Control": "no-store"},
    )


@app.put("/api/user/state")
async def put_user_state_api(request: Request):
    session = _get_auth_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"error": "auth_required"})
    username = str(session.get("username") or "").strip()
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content={"error": "invalid_body"})
    patch: dict = {}
    if "selectedTeam" in body:
        sel = body.get("selectedTeam")
        if sel is None:
            patch["selectedTeam"] = None
        elif isinstance(sel, dict):
            patch["selectedTeam"] = {
                "ownerId": str(sel.get("ownerId") or ""),
                "name": str(sel.get("name") or ""),
            }
    if "watchlist" in body:
        wl = body.get("watchlist")
        if wl is None:
            patch["watchlist"] = None
        elif isinstance(wl, list):
            patch["watchlist"] = [str(x) for x in wl if isinstance(x, (str, int))]
    if "dismissedSignals" in body:
        ds = body.get("dismissedSignals")
        if ds is None:
            patch["dismissedSignals"] = None
        elif isinstance(ds, dict):
            clean: dict[str, int] = {}
            for k, v in ds.items():
                try:
                    clean[str(k)] = int(v)
                except (TypeError, ValueError):
                    continue
            patch["dismissedSignals"] = clean
    if "dismissalAliases" in body:
        da = body.get("dismissalAliases")
        if da is None:
            patch["dismissalAliases"] = None
        elif isinstance(da, dict):
            patch["dismissalAliases"] = {
                str(k): str(v) for k, v in da.items()
                if isinstance(k, str) and isinstance(v, (str, int))
            }
    if "notificationsEmail" in body:
        # Optional email for signal-alert digests.  Stored per-user
        # in user_kv under the ``notificationsEmail`` key so the
        # alert loop can resolve it without a separate table.  We
        # only accept plausible-looking addresses — no MX check,
        # just format validation.
        ne = body.get("notificationsEmail")
        if ne is None or ne == "":
            patch["notificationsEmail"] = None
        elif isinstance(ne, str):
            s = ne.strip()
            if "@" in s and "." in s.split("@")[-1] and len(s) <= 254:
                patch["notificationsEmail"] = s
    if "notificationsEnabled" in body:
        patch["notificationsEnabled"] = bool(body.get("notificationsEnabled"))
    if "activeLeagueKey" in body:
        # The user's preferred league from the registry.  Validate
        # against the live registry so a stale/typo value can't
        # silently land a user on a nonexistent league on next load.
        # ``None`` / empty string clears the preference → callers fall
        # back to the registry's default league on next read.
        raw = body.get("activeLeagueKey")
        if raw is None or raw == "":
            patch["activeLeagueKey"] = None
        elif isinstance(raw, str):
            candidate = raw.strip()
            cfg = _league_registry.get_league_by_key(candidate)
            if cfg is not None and cfg.active:
                patch["activeLeagueKey"] = cfg.key  # canonicalize via alias lookup
            # Unknown or inactive league → silently drop.  The
            # frontend will notice the server didn't echo the key back
            # and fall through to the default.
    if "selectedTeamsByLeague" in body:
        # Per-league selected team map.  Accepts
        #   {"leagueKey": {"ownerId": "...", "teamName": "...",
        #                  "rosterId": <int|str>, "managerName": "..."}}
        # Each entry's leagueKey must resolve against the registry
        # (aliases canonicalized); unknown / inactive leagues are
        # dropped.  Null/"" clears the entire map.
        raw = body.get("selectedTeamsByLeague")
        if raw is None or raw == "":
            patch["selectedTeamsByLeague"] = None
        elif isinstance(raw, dict):
            clean: dict[str, dict[str, object]] = {}
            for lkey, spec in raw.items():
                if not isinstance(lkey, str) or not isinstance(spec, dict):
                    continue
                cfg = _league_registry.get_league_by_key(lkey.strip())
                if cfg is None or not cfg.active:
                    continue
                owner_id = str(spec.get("ownerId") or "").strip()
                team_name = str(spec.get("teamName") or "").strip()
                if not owner_id and not team_name:
                    # An empty entry clears that league's selection
                    # (distinct from not touching the map at all).
                    clean[cfg.key] = {"ownerId": "", "teamName": ""}
                    continue
                entry: dict[str, object] = {
                    "ownerId": owner_id,
                    "teamName": team_name,
                }
                roster_id = spec.get("rosterId")
                if roster_id is not None:
                    entry["rosterId"] = str(roster_id)
                manager_name = str(spec.get("managerName") or "").strip()
                if manager_name:
                    entry["managerName"] = manager_name
                clean[cfg.key] = entry
            patch["selectedTeamsByLeague"] = clean
    state = await run_in_threadpool(_user_kv.merge_user_state, username, patch)
    return JSONResponse(
        content={"username": username, "state": state},
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/user/signals/dismiss")
async def dismiss_signal_api(request: Request):
    session = _get_auth_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"error": "auth_required"})
    username = str(session.get("username") or "").strip()
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content={"error": "invalid_body"})
    signal_key = str(body.get("signalKey") or "").strip()
    if not signal_key:
        return JSONResponse(
            status_code=400,
            content={"error": "signalKey_required"},
        )
    try:
        ttl_ms = int(body.get("ttlMs") or 7 * 24 * 3600 * 1000)
    except (TypeError, ValueError):
        ttl_ms = 7 * 24 * 3600 * 1000
    alias_sid = str(body.get("aliasSleeperId") or "").strip() or None
    alias_name = str(body.get("aliasDisplayName") or "").strip() or None
    # Scope the dismissal to the active league.  Validated against
    # the registry; unknown/inactive keys fall through to legacy flat
    # dismissal.  See user_kv.dismiss_signal docstring.
    raw_league = str(body.get("leagueKey") or "").strip()
    scoped_key: str | None = None
    if raw_league:
        cfg = _league_registry.get_league_by_key(raw_league)
        if cfg is not None and cfg.active:
            scoped_key = cfg.key
    state = await run_in_threadpool(
        _user_kv.dismiss_signal,
        username,
        signal_key,
        ttl_ms=ttl_ms,
        alias_sleeper_id=alias_sid,
        alias_display_name=alias_name,
        league_key=scoped_key,
    )
    return JSONResponse(
        content={"username": username, "state": state},
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/user/signals/restore")
async def restore_signal_api(request: Request):
    session = _get_auth_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"error": "auth_required"})
    username = str(session.get("username") or "").strip()
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content={"error": "invalid_body"})
    signal_key = str(body.get("signalKey") or "").strip()
    if not signal_key:
        return JSONResponse(
            status_code=400,
            content={"error": "signalKey_required"},
        )
    raw_league = str(body.get("leagueKey") or "").strip()
    scoped_key: str | None = None
    if raw_league:
        cfg = _league_registry.get_league_by_key(raw_league)
        if cfg is not None and cfg.active:
            scoped_key = cfg.key
    state = await run_in_threadpool(
        _user_kv.undismiss_signal, username, signal_key, league_key=scoped_key,
    )
    return JSONResponse(
        content={"username": username, "state": state},
        headers={"Cache-Control": "no-store"},
    )


# ── TERMINAL AGGREGATION ENDPOINT ───────────────────────────────────────
#
# Server-side aggregate of everything the landing page needs: team
# aggregates, market movers, signals, news, portfolio.  See
# ``src/api/terminal.py`` for the builder.  Two modes:
#
#   * Authenticated users get the full payload including signals,
#     portfolio, watchlist, and roster-aware team aggregates.
#   * Anonymous users get a public slice (league + top150 movers,
#     news for top-150 players) — enough for an at-a-glance "market
#     pulse" without leaking private identifiers or roster state.
#
# Availability:
#   * When the live contract is loaded: serve the fresh aggregation.
#   * When the live contract hasn't loaded yet (cold start): fall
#     back to the most recent cached dynasty_data_*.json export
#     from disk.  The frontend sees a ``stale: true`` flag and a
#     ``staleAs`` date so it can surface "last good data from
#     YYYY-MM-DD" instead of spinning forever.
#   * If even the cached export is absent, surface a 503 with the
#     same shape so the frontend error UI can render a coherent
#     message.

def _latest_cached_contract_from_disk() -> tuple[dict | None, str | None]:
    """Return the most recent on-disk ``dynasty_data_*.json`` export
    parsed as a contract, plus the date string it was stamped with.
    Used when ``latest_contract_data`` hasn't been primed yet (cold
    start between process-restart and first scrape).
    """
    try:
        candidates = sorted(
            DATA_DIR.glob("dynasty_data_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return None, None
    for candidate in candidates:
        try:
            with candidate.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        # Older exports are pre-contract-builder and lack
        # ``playersArray``; the terminal builder handles that path
        # via the legacy dict, so we can still serve.
        if not raw.get("players") and not raw.get("playersArray"):
            continue
        return raw, raw.get("date") or candidate.stem.replace("dynasty_data_", "")
    return None, None


@app.get("/api/terminal")
async def get_terminal(request: Request):
    session = _get_auth_session(request)
    authed = bool(session)
    username = str((session or {}).get("username") or "").strip() if authed else ""

    # League routing — validate the key, but DON'T require a loaded
    # contract yet (we want to fall through to the disk cache below
    # for the default league).  The loaded-contract check fires
    # after the in-memory contract is available.
    try:
        league_cfg = _resolve_league_for_request(request)
    except LeagueResolutionError as err:
        return err.json_response()

    contract = latest_contract_data
    stale = False
    stale_as = None
    if not contract:
        # 503 fallback (Item 3 from the TODO list): try the most
        # recent cached export before giving up.  Disk cache is for
        # the default league only — if a non-default league is
        # requested we skip the cache and return 503 cleanly.
        default_cfg = _league_registry.get_default_league()
        if default_cfg and league_cfg.key == default_cfg.key:
            cached, cached_date = _latest_cached_contract_from_disk()
            if cached:
                contract = cached
                stale = True
                stale_as = cached_date
        if not contract:
            return JSONResponse(
                status_code=503,
                content={
                    "error": "No data available yet. First scrape may still be running.",
                    "stale": False,
                    "leagueKey": league_cfg.key,
                },
            )

    # Cross-league request: the loaded contract is for a different
    # league than the one requested.  If the scoring profiles match,
    # splice in a live Sleeper overlay (rosters + trades) so the
    # terminal + team widgets actually have data to render.  Only
    # 503 when the overlay fetch fails completely — Sleeper
    # unreachable, invalid league ID, etc.
    loaded_meta = (contract.get("meta") or {}) if isinstance(contract, dict) else {}
    loaded_league = loaded_meta.get("leagueKey")
    loaded_profile = loaded_meta.get("scoringProfile")
    if loaded_league and loaded_league != league_cfg.key:
        if loaded_profile and loaded_profile != league_cfg.scoring_profile:
            # Rankings incompatible; the /api/data 503 path already
            # explains this shape.  Terminal can't do anything.
            return JSONResponse(
                status_code=503,
                content={
                    "error": "data_not_ready",
                    "message": (
                        f"League {league_cfg.key!r} uses scoring profile "
                        f"{league_cfg.scoring_profile!r}, not {loaded_profile!r}."
                    ),
                    "leagueKey": league_cfg.key,
                },
            )
        loaded_sleeper = contract.get("sleeper") or {}
        id_map = loaded_sleeper.get("idToPlayer") if isinstance(loaded_sleeper, dict) else None
        try:
            overlay = await run_in_threadpool(
                _sleeper_overlay.fetch_sleeper_overlay,
                sleeper_league_id=league_cfg.sleeper_league_id,
                id_to_player=id_map if isinstance(id_map, dict) else {},
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "terminal overlay fetch failed for %s: %s", league_cfg.key, exc,
            )
            overlay = None
        if not overlay or not overlay.get("teams"):
            return JSONResponse(
                status_code=503,
                content={
                    "error": "data_not_ready",
                    "message": f"Sleeper overlay for league {league_cfg.key!r} unavailable.",
                    "leagueKey": league_cfg.key,
                },
            )
        # Build a hybrid contract: global rankings + per-league
        # sleeper.  Carry forward the NFL-wide maps so the terminal
        # builder can resolve positions/IDs the same as for the
        # primary league.
        hybrid_sleeper = {
            **{
                k: loaded_sleeper.get(k)
                for k in ("positions", "playerIds", "idToPlayer",
                          "scoringSettings", "rosterPositions",
                          "leagueSettings")
                if isinstance(loaded_sleeper, dict) and k in loaded_sleeper
            },
            **overlay,
        }
        contract = {**contract, "sleeper": hybrid_sleeper, "meta": {
            **loaded_meta,
            "leagueKey": league_cfg.key,
            "sleeperDataReady": True,
            "sleeperSource": "overlay",
            "sleeperLoadedLeagueKey": loaded_league,
        }}

    params = request.query_params
    team_owner_id = (params.get("team") or params.get("ownerId") or "").strip()
    team_name = (params.get("teamName") or "").strip()
    try:
        window_days = int(params.get("windowDays") or 30)
    except (TypeError, ValueError):
        window_days = 30
    window_days = max(7, min(180, window_days))

    user_state: dict = {}
    if authed and username:
        try:
            user_state = await run_in_threadpool(_user_kv.get_user_state, username)
        except Exception as exc:  # noqa: BLE001
            log.warning("/api/terminal user_kv read failed: %s", exc)

    resolved_team = None
    if authed:
        # Anonymous callers get the public slice even if they pass a
        # ``team`` param — we never expose per-roster state without
        # authentication.  ``resolved_team=None`` is enforced below.
        resolved_team = _terminal.resolve_team(
            contract, owner_id=team_owner_id, name=team_name,
        )
        # Auto-resolve via the authenticated Sleeper user id when the
        # client didn't pass an explicit team.  This is the "Sleeper
        # login → your team lights up on first page load" path — no
        # manual team picker needed when the authed user owns a team
        # in this league.
        if resolved_team is None and not team_owner_id and not team_name:
            session_sleeper_id = str((session or {}).get("sleeper_user_id") or "").strip()
            if session_sleeper_id:
                resolved_team = _terminal.resolve_team(
                    contract, owner_id=session_sleeper_id, name=None,
                )

    try:
        payload = await run_in_threadpool(
            _terminal.build_terminal_payload,
            contract,
            resolved_team=resolved_team,
            window_days=window_days,
            news_items=_terminal.gather_news_items(
                lambda: _get_news_service(),
                _live_player_names(),
                (resolved_team or {}).get("name") if resolved_team else None,
            ),
            user_state=user_state,
            public_mode=not authed,
            # Scope dismissals to the active league so a dismissal
            # on league A doesn't silence the same player's signal
            # on league B.  See terminal.build_terminal_payload +
            # user_kv.active_dismissals docstrings.
            league_key=league_cfg.key if league_cfg else None,
        )
    except Exception as exc:
        log.exception("/api/terminal build failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": f"terminal_build_failed: {type(exc).__name__}"},
        )

    # Stale-data stamp: consumers can render a "last good data from
    # YYYY-MM-DD" banner when the live scrape hasn't caught up.
    payload["stale"] = stale
    payload["staleAs"] = stale_as
    payload["authenticated"] = authed

    cache_control = (
        "public, max-age=60, stale-while-revalidate=600"
        if not authed
        else "private, max-age=30, stale-while-revalidate=120"
    )
    return JSONResponse(
        content=payload,
        headers={"Cache-Control": cache_control},
    )


@app.post("/api/trade/simulate")
async def post_trade_simulate(request: Request):
    """Pure-function what-if: apply a hypothetical trade to the
    authenticated user's team and return the delta payload.

    Body::

        {
          "team":       "<ownerId>" (optional — defaults to session
                        owner when signed in via Sleeper),
          "teamName":   "<teamName>" (optional fallback lookup),
          "playersIn":  ["Ja'Marr Chase", ...],   # inbound players
          "playersOut": ["Drake London", ...],     # outbound players
          "picksIn":    ["2026 1.04", ...],        # inbound picks
          "picksOut":   ["2027 2.08", ...]         # outbound picks
        }

    Response shape matches ``trade_simulator.simulate_trade``.
    No persistence — the live contract is never mutated.
    """
    session = _get_auth_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"error": "auth_required"})
    if not latest_contract_data:
        return JSONResponse(
            status_code=503,
            content={"error": "No data available yet."},
        )
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content={"error": "invalid_body"})

    # Validate leagueKey but don't require the loaded contract's
    # leagueKey to match — when the user is on a non-default league
    # we can splice in a live Sleeper overlay (same trick the
    # /api/terminal endpoint uses).  Without this, every trade
    # simulation on League B returns data_not_ready.
    try:
        league_cfg = _resolve_league_for_request(request, body=body)
    except LeagueResolutionError as err:
        return err.json_response()

    # Build the contract this trade sim runs against.  When the
    # request league matches the loaded contract, just use it.
    # When they differ but the scoring profile matches, splice in
    # the per-league Sleeper overlay so the resolver can find the
    # user's team in this league's rosters.
    contract = latest_contract_data
    loaded_meta = (contract.get("meta") or {}) if isinstance(contract, dict) else {}
    loaded_league = loaded_meta.get("leagueKey")
    loaded_profile = loaded_meta.get("scoringProfile")
    if loaded_league and loaded_league != league_cfg.key:
        if loaded_profile and loaded_profile != league_cfg.scoring_profile:
            return JSONResponse(
                status_code=503,
                content={
                    "error": "data_not_ready",
                    "message": (
                        f"League {league_cfg.key!r} uses scoring profile "
                        f"{league_cfg.scoring_profile!r}, not {loaded_profile!r}. "
                        "Trade simulation needs matching rankings."
                    ),
                    "leagueKey": league_cfg.key,
                },
            )
        # Splice in a live overlay for the requested league.
        loaded_sleeper = contract.get("sleeper") or {}
        id_map = loaded_sleeper.get("idToPlayer") if isinstance(loaded_sleeper, dict) else None
        try:
            overlay = await run_in_threadpool(
                _sleeper_overlay.fetch_sleeper_overlay,
                sleeper_league_id=league_cfg.sleeper_league_id,
                id_to_player=id_map if isinstance(id_map, dict) else {},
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "trade-simulate overlay fetch failed for %s: %s", league_cfg.key, exc,
            )
            overlay = None
        if not overlay or not overlay.get("teams"):
            return JSONResponse(
                status_code=503,
                content={
                    "error": "data_not_ready",
                    "message": f"Sleeper overlay for league {league_cfg.key!r} unavailable.",
                    "leagueKey": league_cfg.key,
                },
            )
        hybrid_sleeper = {
            **{
                k: loaded_sleeper.get(k)
                for k in ("positions", "playerIds", "idToPlayer",
                          "scoringSettings", "rosterPositions",
                          "leagueSettings")
                if isinstance(loaded_sleeper, dict) and k in loaded_sleeper
            },
            **overlay,
        }
        contract = {**latest_contract_data, "sleeper": hybrid_sleeper}

    team_owner_id = str(body.get("team") or "").strip()
    team_name = str(body.get("teamName") or "").strip()

    # Session auto-resolve: if the user didn't pass a team, use
    # the Sleeper user_id attached to their session.
    if not team_owner_id and not team_name:
        team_owner_id = str(session.get("sleeper_user_id") or "").strip()

    resolved_team = _terminal.resolve_team(
        contract, owner_id=team_owner_id, name=team_name,
    )
    if resolved_team is None:
        return JSONResponse(
            status_code=404,
            content={"error": "team_not_found", "leagueKey": league_cfg.key},
        )

    def _str_list(key):
        vs = body.get(key) or []
        if not isinstance(vs, list):
            return []
        return [str(x) for x in vs if isinstance(x, (str, int)) and str(x).strip()]

    result = await run_in_threadpool(
        _trade_simulator.simulate_trade,
        contract,
        resolved_team=resolved_team,
        players_in=_str_list("playersIn"),
        players_out=_str_list("playersOut"),
        picks_in=_str_list("picksIn"),
        picks_out=_str_list("picksOut"),
    )
    result["leagueKey"] = league_cfg.key
    return JSONResponse(
        content=result,
        headers={"Cache-Control": "no-store"},
    )


def _deliver_email_smtp(to: str, subject: str, body: str) -> bool:
    """SMTP delivery bound to the existing ALERT_* env vars.

    Returns True on successful send, False on any error.  Errors
    are logged but never raised — the alert runner catches
    exceptions itself and we want deliver-per-user to be isolated.
    """
    if not ALERT_ENABLED or not ALERT_FROM or not ALERT_PASSWORD or not to:
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = ALERT_FROM
    msg["To"] = to
    msg.attach(MIMEText(body, "plain"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as s:
            s.login(ALERT_FROM, ALERT_PASSWORD)
            s.send_message(msg)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("signal-alert SMTP delivery error to %s: %s", to, exc)
        return False


# ── Admin endpoints (Phase 11 follow-ons) ────────────────────────
#
# Gated on both: (1) a valid session AND (2) an explicit admin
# username check against PRIVATE_APP_ALLOWED_USERNAMES.  Every
# admin action is logged with username + action for audit.

def _require_admin_session(request: Request):
    """Returns the session dict on success; returns a JSONResponse
    error on failure.  Caller pattern:

        session_or_err = _require_admin_session(request)
        if isinstance(session_or_err, JSONResponse):
            return session_or_err
        session = session_or_err
    """
    session = _get_auth_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"error": "auth_required"})
    username = str(session.get("username") or "").strip().lower()
    if not PRIVATE_APP_ALLOWED_USERNAMES or username not in PRIVATE_APP_ALLOWED_USERNAMES:
        return JSONResponse(
            status_code=403,
            content={"error": "admin_required", "message": "Allowlisted users only."},
        )
    return session


@app.post("/api/test/create-session")
async def post_test_create_session(request: Request):
    """E2E-only session bootstrap — gated behind two env vars.

    Returns 404 (NOT 401) unless BOTH:
      * ``E2E_TEST_MODE=1`` (or true/yes/on)
      * ``E2E_TEST_SECRET`` matches the caller's ``Authorization:
        Bearer <secret>`` header

    In prod neither var is set, so this endpoint is invisible.
    """
    mode_raw = os.getenv("E2E_TEST_MODE", "").strip().lower()
    if mode_raw not in ("1", "true", "yes", "on"):
        return JSONResponse(status_code=404, content={"error": "not_found"})
    expected = os.getenv("E2E_TEST_SECRET", "").strip()
    auth = str(request.headers.get("authorization", "")).strip()
    provided = auth[len("Bearer "):].strip() if auth.lower().startswith("bearer ") else ""
    if not expected or provided != expected:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    username = (os.getenv("E2E_TEST_USERNAME") or "jasonleetucker").strip().lower()
    session_id = _create_auth_session(
        username=username,
        sleeper_user_id=os.getenv("E2E_TEST_SLEEPER_USER_ID", "").strip() or None,
        display_name=username,
        auth_method="e2e_test",
    )
    res = JSONResponse(content={
        "ok": True, "username": username, "sessionId": session_id,
    })
    res.set_cookie(
        JASON_AUTH_COOKIE_NAME, session_id,
        max_age=3600, httponly=True, samesite="lax",
    )
    return res


@app.post("/api/admin/nfl-data/flush")
async def post_admin_nfl_data_flush(request: Request):
    """Flush every nfl_data cache entry (forces next fetch to go
    upstream).  Use when an upstream schema change is suspected
    and cached parquet is stale.
    """
    session_or_err = _require_admin_session(request)
    if isinstance(session_or_err, JSONResponse):
        return session_or_err
    session = session_or_err
    from src.nfl_data import cache as _nflc
    cache_dir = _nflc._default_cache_dir()  # noqa: SLF001
    deleted = 0
    try:
        if cache_dir.exists():
            for p in cache_dir.iterdir():
                try:
                    p.unlink()
                    deleted += 1
                except OSError:
                    pass
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content={"error": "flush_failed", "message": str(exc)},
        )
    log.info(
        "admin action: nfl_data flush by %s — %d entries evicted",
        session.get("username"), deleted,
    )
    return JSONResponse(content={"ok": True, "evicted": deleted})


@app.post("/api/admin/sessions/force-logout-all")
async def post_admin_force_logout_all(request: Request):
    """Emergency: sign-out-everyone hammer.  Wipes both the in-memory
    dict AND the persistent store so a stolen session / compromise
    can be remediated without a deploy."""
    session_or_err = _require_admin_session(request)
    if isinstance(session_or_err, JSONResponse):
        return session_or_err
    session = session_or_err
    in_mem_count = len(auth_sessions)
    auth_sessions.clear()
    persisted = 0
    try:
        from src.api import session_store as _ss
        persisted = _ss.force_clear_all()
    except Exception as exc:  # noqa: BLE001
        log.warning("force_clear_all session_store: %s", exc)
    log.warning(
        "admin action: FORCE-LOGOUT-ALL by %s — %d in-memory + %d persisted",
        session.get("username"), in_mem_count, persisted,
    )
    return JSONResponse(content={
        "ok": True,
        "inMemoryCleared": in_mem_count,
        "persistedCleared": persisted,
    })


@app.post("/api/admin/signal-state/migrate")
async def post_admin_signal_state_migrate(request: Request):
    """One-shot migration: legacy ``signalAlertState`` →
    ``signalAlertStateByLeague[defaultLeagueKey]`` for every user.
    Idempotent."""
    session_or_err = _require_admin_session(request)
    if isinstance(session_or_err, JSONResponse):
        return session_or_err
    session = session_or_err
    from src.api import signal_state_migration as _mig
    default_cfg = _league_registry.get_default_league()
    if default_cfg is None:
        return JSONResponse(
            status_code=500,
            content={"error": "no_default_league"},
        )
    result = _mig.migrate_all(default_league_key=default_cfg.key)
    log.info(
        "admin action: signal-state migrate by %s — counts=%s",
        session.get("username"), result.get("counts"),
    )
    return JSONResponse(content=result)


@app.get("/api/player/{sleeper_id}/realized")
async def get_player_realized(sleeper_id: str, request: Request):
    """Return realized weekly fantasy points for a player against the
    authed user's active league scoring settings.

    Gated on ``realized_points_api`` feature flag (default OFF).
    When the flag is off, returns 503 feature_disabled.  When ON
    but ``nfl_data_ingest`` is also needed to fetch stats — which
    is why this endpoint returns an empty weeks list with a clear
    `reason` when no stats are available, rather than 500-ing.
    """
    from src.api import feature_flags as _ff
    session = _get_auth_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"error": "auth_required"})
    if not _ff.is_enabled("realized_points_api"):
        return JSONResponse(
            status_code=503,
            content={
                "error": "feature_disabled",
                "flag": "realized_points_api",
            },
        )
    try:
        league_cfg = _resolve_league_for_request(request)
    except LeagueResolutionError as err:
        return err.json_response()

    # Pull the Sleeper scoring settings from the overlay or primary
    # contract — whichever belongs to this league.
    sleeper_block = (latest_contract_data or {}).get("sleeper") or {}
    scoring_settings = sleeper_block.get("scoringSettings") or {}

    # Fetch weekly stats via nfl_data_ingest (already flag-gated —
    # returns [] when nfl_data_ingest is off).  We scope to the
    # current season for freshness + prior season for comparison.
    from src.nfl_data import ingest as _ing
    from src.nfl_data import realized_points as _rp
    now_year = datetime.now(timezone.utc).year
    years = [now_year - 1, now_year]
    weekly = _ing.fetch_weekly_stats(years)

    if not weekly:
        return JSONResponse(content={
            "sleeperId": sleeper_id,
            "leagueKey": league_cfg.key,
            "reason": "no_stats_available",
            "weeks": [],
            "totalPoints": 0.0,
            "weekCount": 0,
        })

    # Find this player's GSIS via the unified mapper, then filter.
    from src.identity import unified_mapper as _um
    players_dir = sleeper_block.get("players") or sleeper_block.get("playerDict")
    resolved = _um.resolve_player(players_dir, sleeper_id=str(sleeper_id))
    if resolved is None or not resolved.gsis_id:
        return JSONResponse(content={
            "sleeperId": sleeper_id,
            "leagueKey": league_cfg.key,
            "reason": "unmapped_player",
            "weeks": [],
        })
    player_rows = [r for r in weekly if str(r.get("player_id_gsis") or "") == resolved.gsis_id]
    cumulative = _rp.compute_cumulative_points(
        player_rows, scoring_settings, position=resolved.position,
    )
    return JSONResponse(content={
        "sleeperId": sleeper_id,
        "gsisId": resolved.gsis_id,
        "fullName": resolved.full_name,
        "position": resolved.position,
        "leagueKey": league_cfg.key,
        **cumulative,
    })


@app.post("/api/trade/simulate-mc")
async def post_trade_simulate_mc(request: Request):
    """Monte Carlo trade simulator (Phase 9 of the 2026-04 upgrade).

    Uses the consensus-band distribution from Phase 4 (`valueBand`
    on each player row) to produce a probabilistic view of trade
    outcomes: win probability, delta distribution, range of outcomes.

    Lives alongside `/api/trade/simulate` — the existing endpoint
    is unchanged.  This is additive, behind the `monte_carlo_trade`
    feature flag.  When the flag is off this endpoint returns 503
    `feature_disabled` so clients can fall back cleanly.

    Body::

        {
          "sideA": [{"name": "...", "rankDerivedValue": N,
                     "team": "...", "pos": "...",
                     "valueBand": {"p10":, "p50":, "p90":}}],
          "sideB": [...],
          "nSims": 50000,          # optional, default 50000
          "sameTeamRho": 0.25,     # optional correlation knob
          "samePosGroupRho": 0.10, # optional correlation knob
          "seed": 42               # optional for reproducible runs
        }

    Response (on success)::

        {
          "winProbA": 0.62,
          "winProbB": 0.38,
          "meanDelta": 450.2,
          "stdDelta": 1240.5,
          "deltaRange": {"p10": ..., "p50": ..., "p90": ...},
          "nSims": 50000,
          "method": "consensus_based_win_rate",
          "labelHint": "consensus_based_win_rate",
          "disclaimer": "..."
        }

    The ``labelHint`` + ``disclaimer`` fields are PART OF THE
    CONTRACT — the frontend MUST render the disclaimer somewhere
    visible so users don't mis-read win probability as real-world
    odds.
    """
    from src.api import feature_flags as _ff
    from src.trade import monte_carlo as _mc

    session = _get_auth_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"error": "auth_required"})
    if not _ff.is_enabled("monte_carlo_trade"):
        return JSONResponse(
            status_code=503,
            content={
                "error": "feature_disabled",
                "flag": "monte_carlo_trade",
                "message": "Monte Carlo simulator is not yet enabled.",
            },
        )
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content={"error": "invalid_body"})
    side_a_raw = body.get("sideA") or []
    side_b_raw = body.get("sideB") or []
    if not isinstance(side_a_raw, list) or not isinstance(side_b_raw, list):
        return JSONResponse(status_code=400, content={"error": "sides_must_be_lists"})
    side_a = [tp for tp in (_mc.build_trade_player(r) for r in side_a_raw) if tp is not None]
    side_b = [tp for tp in (_mc.build_trade_player(r) for r in side_b_raw) if tp is not None]
    try:
        n_sims = int(body.get("nSims") or 50000)
    except (TypeError, ValueError):
        n_sims = 50000
    # Guardrail — don't let a caller request a million sims.
    n_sims = max(1000, min(200_000, n_sims))
    try:
        rho_t = float(body.get("sameTeamRho", 0.25))
        rho_p = float(body.get("samePosGroupRho", 0.10))
    except (TypeError, ValueError):
        rho_t, rho_p = 0.25, 0.10
    seed = body.get("seed")
    try:
        seed = int(seed) if seed is not None else None
    except (TypeError, ValueError):
        seed = None
    # Symmetrize the direction (A→B averaged with B→A) so ordering
    # never biases the result — critical invariant per the Phase 11
    # integration pass.  Then enrich with the decision-layer fields
    # (valueDelta / adjustedDelta / winPct / riskLevel / tierImpact)
    # the trade calculator UI consumes.
    from src.trade import symmetrize as _sym
    base = _sym.simulate_symmetric(
        side_a, side_b,
        n_sims=n_sims, same_team_rho=rho_t,
        same_pos_group_rho=rho_p, seed=seed,
    )
    enriched = _sym.enrich_with_decision_shape(base, side_a, side_b)
    return JSONResponse(content=enriched)


@app.post("/api/signal-alerts/run")
async def run_signal_alerts(request: Request):
    """Trigger a signal-alert sweep for every user with email
    notifications enabled.  Admin-only — requires the password
    session method; a Sleeper-login session is NOT authorized
    since that auth method is trust-on-first-use and shouldn't be
    able to trigger mass-email sends.

    The alert runner:
      1. Loads every user from user_kv.
      2. For each with ``notificationsEnabled: true`` AND a valid
         ``notificationsEmail``, builds a terminal payload for that
         user (resolving their team by ``sleeper_user_id`` when
         present) and runs ``signal_alerts.process_user_alerts``.
      3. Returns a summary.

    Wire this to a cron / systemd timer for automated daily digests.
    Cron clients authenticate via the shared ``SIGNAL_ALERT_CRON_TOKEN``
    as a Bearer token; browser clients still need a password session.
    """
    # Two auth paths: (1) a password-session admin from the browser,
    # (2) an opaque bearer token for cron / systemd timers.  Either is
    # sufficient on its own.  Failure mode: if no session AND no token
    # (or token mismatch), reject.  Short-circuit the token check
    # before touching cookies so an unset token can never authorize.
    cron_auth_ok = False
    if SIGNAL_ALERT_CRON_TOKEN:
        header = (request.headers.get("authorization") or "").strip()
        if header.lower().startswith("bearer "):
            presented = header.split(None, 1)[1].strip()
            # Constant-time compare to avoid timing leaks.
            if hmac.compare_digest(presented, SIGNAL_ALERT_CRON_TOKEN):
                cron_auth_ok = True
    if not cron_auth_ok:
        session = _get_auth_session(request)
        if not session or session.get("auth_method") != "password":
            return JSONResponse(
                status_code=401,
                content={"error": "admin_auth_required"},
            )
    if not latest_contract_data:
        return JSONResponse(
            status_code=503,
            content={"error": "no_live_contract"},
        )
    # Walk every user_kv row.  No pagination — at current scale
    # (dozens of users tops) this is fine.  For each user, loop
    # over every active league: build a league-specific terminal
    # payload (via Sleeper overlay for non-default leagues) and
    # run the alert detector with the league_key scoped.  Cooldowns
    # are now nested per league so a SELL in league A doesn't
    # silently eat a SELL in league B for the same player.
    def _run_sweep() -> dict[str, object]:
        db = _user_kv.all_user_states()
        summary: list[dict] = []
        loaded_league = (
            (latest_contract_data or {}).get("meta", {}).get("leagueKey")
            if isinstance(latest_contract_data, dict) else None
        )
        loaded_profile = (
            (latest_contract_data or {}).get("meta", {}).get("scoringProfile")
            if isinstance(latest_contract_data, dict) else None
        )
        loaded_sleeper = (
            latest_contract_data.get("sleeper") or {}
            if isinstance(latest_contract_data, dict) else {}
        )
        active_leagues = _league_registry.active_leagues()
        for username, state in db.items():
            if not isinstance(state, dict):
                continue
            if not state.get("notificationsEnabled"):
                continue
            email = str(state.get("notificationsEmail") or "").strip()
            if not email:
                continue
            owner_id = str((state.get("selectedTeam") or {}).get("ownerId") or "")
            selected_teams = state.get("selectedTeamsByLeague") or {}
            if not isinstance(selected_teams, dict):
                selected_teams = {}
            user_summary: list[dict] = []
            for cfg in active_leagues:
                # Skip leagues the user isn't in — if there's no
                # team-map entry and the contract doesn't resolve a
                # team, they have nothing to alert on here.
                league_entry = selected_teams.get(cfg.key) or {}
                league_owner_id = (
                    str(league_entry.get("ownerId") or "").strip()
                    or owner_id
                )
                # Build the league-specific contract.  For the
                # loaded league this is just latest_contract_data;
                # for other active leagues we splice in the overlay.
                if cfg.key == loaded_league:
                    contract = latest_contract_data
                elif loaded_profile and loaded_profile == cfg.scoring_profile:
                    id_map = loaded_sleeper.get("idToPlayer") if isinstance(loaded_sleeper, dict) else {}
                    try:
                        overlay = _sleeper_overlay.fetch_sleeper_overlay(
                            sleeper_league_id=cfg.sleeper_league_id,
                            id_to_player=id_map if isinstance(id_map, dict) else {},
                        )
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "signal-alerts overlay failed for %s / %s: %s",
                            username, cfg.key, exc,
                        )
                        overlay = None
                    if not overlay or not overlay.get("teams"):
                        # No data for this league — skip, not a
                        # failure (e.g. Sleeper transient error).
                        continue
                    hybrid_sleeper = {
                        **{
                            k: loaded_sleeper.get(k)
                            for k in ("positions", "playerIds", "idToPlayer",
                                      "scoringSettings", "rosterPositions",
                                      "leagueSettings")
                            if isinstance(loaded_sleeper, dict) and k in loaded_sleeper
                        },
                        **overlay,
                    }
                    contract = {**latest_contract_data, "sleeper": hybrid_sleeper}
                else:
                    # Different scoring profile — rankings aren't
                    # comparable, skip this league for this run.
                    continue

                team = _terminal.resolve_team(
                    contract, owner_id=league_owner_id, name=None,
                )
                if team is None:
                    # User isn't in this league — nothing to alert on.
                    continue
                try:
                    payload = _terminal.build_terminal_payload(
                        contract,
                        resolved_team=team,
                        window_days=30,
                        user_state=state,
                        league_key=cfg.key,
                    )
                except Exception as exc:  # noqa: BLE001
                    user_summary.append({
                        "leagueKey": cfg.key, "ok": False,
                        "reason": f"build_error:{type(exc).__name__}",
                    })
                    continue
                result = _signal_alerts.process_user_alerts(
                    username,
                    signals=payload.get("signals") or [],
                    display_name=username,
                    email=email,
                    delivery=_deliver_email_smtp,
                    league_key=cfg.key,
                )
                user_summary.append({"leagueKey": cfg.key, **result})
            if user_summary:
                summary.append({"username": username, "byLeague": user_summary})
        return {
            "total_users_checked": len(db),
            "processed": len(summary),
            "results": summary,
        }

    result = await run_in_threadpool(_run_sweep)

    # Operator alerts piggyback on the signal-alert cron so we don't
    # need another timer.  Checks: scrape success rate, circuit
    # breakers, contract health, data freshness.  Never raises.
    try:
        from src.api import ops_alerts as _ops
        from src.utils import circuit_breaker as _cb
        status_payload = _scrape_status_payload()
        data_age_hours = None
        loaded_at = latest_data_source.get("loadedAt")
        if loaded_at:
            try:
                loaded_dt = datetime.fromisoformat(loaded_at)
                data_age_hours = (
                    datetime.now(timezone.utc) - loaded_dt
                ).total_seconds() / 3600.0
            except (ValueError, TypeError):
                pass
        ops_summary = _ops.check_and_alert(
            status_payload=status_payload,
            circuit_snapshots=_cb.snapshot_all(),
            contract_health=contract_health,
            data_age_hours=data_age_hours,
            scrape_interval_hours=float(SCRAPE_INTERVAL_HOURS),
            delivery=_deliver_email_smtp if ALERT_TO else None,
            to_email=ALERT_TO or None,
        )
        result["opsAlerts"] = ops_summary
    except Exception as exc:  # noqa: BLE001
        log.warning("ops_alerts check failed: %s", exc)
        result["opsAlerts"] = {"error": str(exc)}

    return JSONResponse(content=result, headers={"Cache-Control": "no-store"})


@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def serve_landing(request: Request):
    redirect = _require_auth_or_redirect(request, "/")
    if redirect is not None:
        return redirect
    return await _serve_app_shell("/")


@app.get("/league", response_class=HTMLResponse)
async def serve_league_entry(request: Request):
    # Public page — no auth required.  The /league frontend hydrates
    # exclusively from /api/public/league, never /api/data.  See
    # src/public_league/ for the isolated pipeline powering this page.
    return await _serve_app_shell("/league")


def _require_auth_or_redirect(request: Request, default_next: str = "/app") -> RedirectResponse | None:
    if _is_authenticated(request):
        return None
    return _auth_redirect_response(request, default_next)


async def _serve_app_shell(frontend_path: str) -> Response:
    """Proxy the request to the Next.js frontend."""
    proxied, err = _proxy_next(frontend_path)
    if proxied is not None:
        return proxied
    return HTMLResponse(
        f"<h1>Next frontend unavailable</h1><p>{err or 'unknown error'}</p>",
        status_code=503,
    )


# ── DASHBOARD ROUTES (AUTH REQUIRED) ────────────────────────────────────
@app.get("/app", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    redirect = _require_auth_or_redirect(request, "/app")
    if redirect is not None:
        return redirect
    return await _serve_app_shell("/")


@app.get("/rankings", response_class=HTMLResponse)
async def serve_rankings(request: Request):
    redirect = _require_auth_or_redirect(request, "/rankings")
    if redirect is not None:
        return redirect
    return await _serve_app_shell("/rankings")


@app.get("/trade", response_class=HTMLResponse)
async def serve_trade(request: Request):
    redirect = _require_auth_or_redirect(request, "/trade")
    if redirect is not None:
        return redirect
    return await _serve_app_shell("/trade")


@app.get("/settings", response_class=HTMLResponse)
async def serve_settings(request: Request):
    redirect = _require_auth_or_redirect(request, "/settings")
    if redirect is not None:
        return redirect
    return await _serve_app_shell("/settings")


@app.get("/tools/trade-coverage", response_class=HTMLResponse)
async def serve_trade_coverage(request: Request):
    """Internal diagnostic dashboard: per-team /api/terminal delta
    coverage.  Auth-gated — the page itself hits /api/terminal for
    every team in the league, which requires a session."""
    redirect = _require_auth_or_redirect(request, "/tools/trade-coverage")
    if redirect is not None:
        return redirect
    return await _serve_app_shell("/tools/trade-coverage")


@app.get("/tools/source-health", response_class=HTMLResponse)
async def serve_source_health(request: Request):
    """Scraper source-health dashboard.  Auth-gated so the scraper
    diagnostics aren't exposed to anonymous visitors."""
    redirect = _require_auth_or_redirect(request, "/tools/source-health")
    if redirect is not None:
        return redirect
    return await _serve_app_shell("/tools/source-health")


@app.get("/edge", response_class=HTMLResponse)
async def serve_edge(request: Request):
    redirect = _require_auth_or_redirect(request, "/edge")
    if redirect is not None:
        return redirect
    return await _serve_app_shell("/edge")


@app.get("/finder", response_class=HTMLResponse)
async def serve_finder(request: Request):
    redirect = _require_auth_or_redirect(request, "/finder")
    if redirect is not None:
        return redirect
    return await _serve_app_shell("/finder")


@app.get("/trades", response_class=HTMLResponse)
async def serve_trades(request: Request):
    # Public page — no auth required
    return await _serve_app_shell("/trades")


@app.get("/rosters", response_class=HTMLResponse)
async def serve_rosters(request: Request):
    redirect = _require_auth_or_redirect(request, "/rosters")
    if redirect is not None:
        return redirect
    return await _serve_app_shell("/rosters")


@app.get("/draft-capital", response_class=HTMLResponse)
async def serve_draft_capital(request: Request):
    # Public page — no auth required
    return await _serve_app_shell("/draft-capital")


@app.get("/more", response_class=HTMLResponse)
async def serve_more(request: Request):
    redirect = _require_auth_or_redirect(request, "/more")
    if redirect is not None:
        return redirect
    return await _serve_app_shell("/more")


@app.get("/admin", response_class=HTMLResponse)
async def serve_admin(request: Request):
    """Admin dashboard — auth-gated + admin-allowlist-gated.
    The page itself makes its own /api/admin/* calls which enforce
    admin-allowlist; this route just guards access to the shell."""
    redirect = _require_auth_or_redirect(request, "/admin")
    if redirect is not None:
        return redirect
    return await _serve_app_shell("/admin")


@app.get("/login", response_class=HTMLResponse)
async def serve_login(request: Request):
    """Login page — no auth required (avoids redirect loop)."""
    return await _serve_app_shell("/login")


@app.get("/index.html", response_class=HTMLResponse)
async def serve_index_alias(request: Request):
    """Legacy alias — redirect to root."""
    return RedirectResponse(url="/", status_code=301)


@app.get("/_next/{full_path:path}")
async def serve_next_assets(full_path: str):
    proxied, _ = _proxy_next(f"/_next/{full_path}")
    if proxied is not None:
        return proxied
    return Response(status_code=404)


@app.get("/favicon.ico")
async def serve_favicon():
    proxied, _ = _proxy_next("/favicon.ico")
    if proxied is not None:
        return proxied
    return Response(status_code=404)


# Static file mount for backend-generated assets (CSS, images if any).
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── MAIN ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    print()
    print("  ╔═══════════════════════════════════════════╗")
    print("  ║   Dynasty Trade Calculator — Server       ║")
    print(f"  ║   Dashboard: http://localhost:{PORT:<13}║")
    print(f"  ║   Scrape interval: {SCRAPE_INTERVAL_HOURS}h{' ' * 21}║")
    print(f"  ║   Alerts: {'ON → ' + ALERT_TO[:20] if ALERT_ENABLED else 'OFF':<30}║")
    print("  ╚═══════════════════════════════════════════╝")
    print()

    uvicorn.run(
        "server:app",
        host=HOST,
        port=PORT,
        log_level="info",
        reload=False,
    )
