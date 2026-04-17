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
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles

from src.api.data_contract import (
    CONTRACT_VERSION as API_DATA_CONTRACT_VERSION,
    build_api_data_contract,
    build_api_startup_payload,
    build_canonical_comparison_block,
    build_rankings_delta_payload,
    build_shadow_comparison_report,
    get_ranking_source_registry,
    normalize_source_overrides,
    normalize_tep_multiplier,
    validate_api_data_contract,
)

# ── CONFIG ──────────────────────────────────────────────────────────────
SCRAPE_INTERVAL_HOURS = 2
PORT = 8000
HOST = "0.0.0.0"  # accessible from local network; use "127.0.0.1" for local only
SCRAPE_STALL_SECONDS = int(os.getenv("SCRAPE_STALL_SECONDS", "900"))
SCRAPE_RUN_TIMEOUT_SECONDS = int(os.getenv("SCRAPE_RUN_TIMEOUT_SECONDS", "7200"))

# R-6: Canonical data mode — controls how canonical pipeline data is used.
#   off              = ignore canonical pipeline output (default, current behavior)
#   shadow           = load canonical data, log comparison with legacy, serve legacy
#   internal_primary = serve canonical values to internal/dev only (gated, not public)
#   primary          = serve canonical data publicly, fallback to legacy if unavailable
# IMPORTANT: default is always "off". Only change after running
#   python scripts/check_promotion_readiness.py --target <mode>
CANONICAL_DATA_MODE = os.getenv("CANONICAL_DATA_MODE", "off").strip().lower()
if CANONICAL_DATA_MODE not in ("off", "shadow", "internal_primary", "primary"):
    CANONICAL_DATA_MODE = "off"

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
# R-6: Canonical pipeline data (shadow/primary mode)
canonical_data: dict | None = None
canonical_data_loaded_at: str | None = None
shadow_comparison_report: dict | None = None
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


def _create_auth_session(username: str) -> str:
    session_id = uuid.uuid4().hex
    auth_sessions[session_id] = {
        "username": str(username or ""),
        "created_at": _utc_now_iso(),
    }
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
def _prime_latest_payload(data: dict | None) -> None:
    """Pre-serialize latest payload once so /api/data returns instantly."""
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
        # R-6 shadow/internal_primary/primary: attach canonical comparison when available.
        if CANONICAL_DATA_MODE in ("shadow", "internal_primary", "primary") and canonical_data is not None:
            try:
                legacy_players = data.get("players") if isinstance(data, dict) else None
                cmp_block = build_canonical_comparison_block(
                    canonical_data,
                    loaded_at=canonical_data_loaded_at,
                    legacy_players=legacy_players,
                )
                contract_payload["canonicalComparison"] = cmp_block
                summary = cmp_block.get("summary", {})
                log.info(
                    "[SHADOW] Attached canonicalComparison block: %d assets "
                    "(%d matched to legacy, avg|delta|=%s)",
                    cmp_block.get("assetCount", 0),
                    summary.get("matchedToLegacy", 0),
                    summary.get("avgAbsDelta", "n/a"),
                )
            except Exception as cmp_err:
                log.warning("[SHADOW] Failed to build canonical comparison: %s", cmp_err)
                # Non-fatal — live payload still serves without comparison data.

        latest_contract_data = contract_payload
        contract_health = contract_report

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


def _load_canonical_snapshot() -> dict | None:
    """R-6: Load the latest canonical pipeline snapshot if available."""
    global canonical_data, canonical_data_loaded_at
    if CANONICAL_DATA_MODE == "off":
        return None
    canonical_dir = DATA_DIR / "canonical"
    canonical_file = _latest_file(canonical_dir, "canonical_snapshot_*.json")
    if canonical_file is None:
        return None
    try:
        with canonical_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
        canonical_data = data
        canonical_data_loaded_at = _utc_now_iso()
        log.info(f"Canonical snapshot loaded: {canonical_file.name} "
                 f"({len(data.get('assets', []))} assets, mode={CANONICAL_DATA_MODE})")
        return data
    except Exception as e:
        log.error(f"Failed to load canonical snapshot {canonical_file}: {e}")
        return None


def _run_canonical_shadow_comparison(legacy_data: dict | None) -> None:
    """R-6: In shadow mode, compare canonical vs legacy data and log differences."""
    global shadow_comparison_report
    if CANONICAL_DATA_MODE not in ("shadow", "internal_primary", "primary") or canonical_data is None or legacy_data is None:
        shadow_comparison_report = None
        return

    legacy_players = legacy_data.get("players", {})
    try:
        report = build_shadow_comparison_report(canonical_data, legacy_players)
    except Exception as e:
        log.warning("[SHADOW] Failed to build comparison report: %s", e)
        shadow_comparison_report = None
        return

    shadow_comparison_report = report
    s = report.get("summary", {})

    log.info(
        "[SHADOW] Comparison: canonical=%d legacy=%d matched=%d "
        "canonical_only=%d legacy_only=%d",
        s.get("canonicalAssetCount", 0),
        s.get("legacyPlayerCount", 0),
        s.get("matchedCount", 0),
        s.get("canonicalOnlyCount", 0),
        s.get("legacyOnlyCount", 0),
    )

    if s.get("avgAbsDelta") is not None:
        log.info(
            "[SHADOW] Delta stats: avg|delta|=%d median=%d p90=%d max=%d",
            s["avgAbsDelta"],
            s.get("medianAbsDelta", 0),
            s.get("p90AbsDelta", 0),
            s.get("maxAbsDelta", 0),
        )
        dist = s.get("deltaDistribution", {})
        if dist:
            log.info(
                "[SHADOW] Distribution: <200=%d  200-600=%d  600-1200=%d  >1200=%d",
                dist.get("under200", 0),
                dist.get("200to600", 0),
                dist.get("600to1200", 0),
                dist.get("over1200", 0),
            )

    log.info(
        "[SHADOW] Top-50 overlap: %d/50 (%d%%)",
        s.get("top50Overlap", 0),
        s.get("top50OverlapPct", 0),
    )

    risers = report.get("topRisers", [])[:5]
    fallers = report.get("topFallers", [])[:5]
    if risers:
        riser_strs = [f"{r['name']}(+{r['delta']})" for r in risers]
        log.info("[SHADOW] Top risers: %s", ", ".join(riser_strs))
    if fallers:
        faller_strs = [f"{r['name']}({r['delta']})" for r in fallers]
        log.info("[SHADOW] Top fallers: %s", ", ".join(faller_strs))


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
            _prime_latest_payload(result)

            _mark_scrape_success(elapsed, player_count, site_count, total_sites)

            log.info(
                f"SCRAPE COMPLETE — {player_count} players, "
                f"{site_count}/{total_sites} sites, {elapsed:.1f}s"
            )

            # R-6: Reload canonical data and run shadow comparison after each scrape
            if CANONICAL_DATA_MODE != "off":
                _load_canonical_snapshot()
                _run_canonical_shadow_comparison(result)

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
    global latest_data

    _metrics["server_start_time"] = _utc_now_iso()

    # 1. Load cached data immediately so the dashboard is usable right away
    latest_data = load_from_disk()
    _prime_latest_payload(latest_data)
    if latest_data:
        log.info("Dashboard ready with cached data")
    else:
        log.info("No cached data found — dashboard will show empty until first scrape completes")

    # R-6: Load canonical pipeline data if shadow/primary mode is enabled
    if CANONICAL_DATA_MODE != "off":
        _load_canonical_snapshot()
        _run_canonical_shadow_comparison(latest_data)
        log.info(f"Canonical data mode: {CANONICAL_DATA_MODE}")

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


@app.middleware("http")
async def _count_requests(request: Request, call_next):
    """R-9: Count all HTTP requests for metrics."""
    _metrics["request_count"] = _metrics.get("request_count", 0) + 1
    return await call_next(request)

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
    """Return latest normalized/validated data contract JSON."""
    if latest_contract_data:
        view = (request.query_params.get("view") or "").strip().lower()
        startup_view = view in {"startup", "boot", "initial"}
        runtime_view = view in {"app", "runtime", "lite", "slim"}

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

        headers = {
            # Keep dashboard startup fast with a short cache window + conditional revalidation.
            "Cache-Control": "public, max-age=30, stale-while-revalidate=300",
            "X-Payload-View": payload_view_name,
        }
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

    headers = {
        "Cache-Control": "no-store",
        "X-Payload-View": "rankings-overrides-delta" if delta_view else "rankings-overrides",
    }
    return JSONResponse(content=contract_payload, headers=headers)


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
        # R-6: Canonical pipeline mode
        "canonical_data_mode": CANONICAL_DATA_MODE,
        "canonical_data_loaded": canonical_data is not None,
        "canonical_data_loaded_at": canonical_data_loaded_at,
        "canonical_shadow_comparison": {
            "available": shadow_comparison_report is not None,
            "summary": shadow_comparison_report.get("summary") if shadow_comparison_report else None,
            "generatedAt": shadow_comparison_report.get("generatedAt") if shadow_comparison_report else None,
        } if CANONICAL_DATA_MODE in ("shadow", "internal_primary") else None,
    })


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

    is_ok = (
        status_payload.get("last_error") in (None, "")
        and not status_payload.get("stalled")
        and not data_stale
        and bool(contract_health.get("ok", False))
    )
    status = "ok" if is_ok else "degraded"
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
        "canonical_data_mode": CANONICAL_DATA_MODE,
        "canonical_data_loaded": canonical_data is not None,
    })


@app.get("/api/scaffold/status")
async def get_scaffold_status():
    """Return latest scaffold snapshot metadata for raw/canonical/league/report outputs."""
    raw_file = _latest_file(DATA_DIR / "raw_sources", "raw_source_snapshot_*.json")
    ingest_validation_file = _latest_file(DATA_DIR / "validation", "ingest_validation_*.json")
    canonical_file = _latest_file(DATA_DIR / "canonical", "canonical_snapshot_*.json")
    canonical_validation_file = _latest_file(DATA_DIR / "validation", "canonical_validation_*.json")
    league_file = _latest_file(DATA_DIR / "league", "league_snapshot_*.json")
    identity_file = _latest_file(DATA_DIR / "identity", "identity_resolution_*.json")
    if identity_file is None:
        identity_file = _latest_file(DATA_DIR / "identity", "identity_report_*.json")
    report_file = _latest_file(DATA_DIR / "reports", "ops_report_*.md")

    raw = _load_json_file(raw_file)
    ingest_validation = _load_json_file(ingest_validation_file)
    canonical = _load_json_file(canonical_file)
    canonical_validation = _load_json_file(canonical_validation_file)
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
            "canonical": {
                "file": _meta(canonical_file),
                "asset_count": canonical.get("asset_count", 0) if canonical else 0,
            },
            "canonical_validation": {
                "file": _meta(canonical_validation_file),
                "suspicious_jump_count": canonical_validation.get("suspicious_jump_count", 0) if canonical_validation else 0,
                "rookie_universe_warning_count": canonical_validation.get("rookie_universe_warning_count", 0) if canonical_validation else 0,
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


@app.get("/api/scaffold/canonical")
async def get_scaffold_canonical():
    """Return canonical pipeline data.

    In internal_primary mode: serves a curated player-values response with
    calibrated values and enrichment metadata — suitable
    for evaluation without affecting the public /api/data path.

    In other modes: serves the raw canonical snapshot JSON (debug view).
    """
    if CANONICAL_DATA_MODE == "internal_primary" and canonical_data is not None:
        # Build a lightweight player-values response (not the full snapshot)
        assets = canonical_data.get("assets", [])
        player_values = {}
        for a in assets:
            name = a.get("display_name", "")
            if not name:
                continue
            player_values[name] = {
                "calibrated_value": a.get("calibrated_value"),
                "display_value": a.get("display_value"),
                "blended_value": a.get("blended_value"),
                "universe": a.get("universe", ""),
                "source_count": len(a.get("source_values", {})),
                "position": (a.get("metadata") or {}).get("position"),
            }
        return JSONResponse(content={
            "mode": CANONICAL_DATA_MODE,
            "source_count": canonical_data.get("source_count", 0),
            "asset_count": canonical_data.get("asset_count", 0),
            "loaded_at": canonical_data_loaded_at,
            "run_id": canonical_data.get("run_id", ""),
            "calibration": canonical_data.get("calibration"),
            "enrichment_summary": canonical_data.get("enrichment_summary"),
            "player_count": len(player_values),
            "players": player_values,
            "_note": "This is internal-primary data for evaluation only. Public API at /api/data still serves legacy values.",
        })
    # Default: serve raw canonical snapshot
    file_path = _latest_file(DATA_DIR / "canonical", "canonical_snapshot_*.json")
    payload = _load_json_file(file_path)
    if payload is None:
        return JSONResponse(status_code=404, content={"error": "No canonical scaffold snapshot found"})
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


@app.get("/api/scaffold/shadow")
async def get_scaffold_shadow():
    """Return the latest shadow comparison report (canonical vs legacy).

    Available when CANONICAL_DATA_MODE=shadow and both a canonical
    snapshot and legacy data are loaded.  Shows overlap, deltas,
    top risers/fallers, rank correlation, and distribution analysis.
    """
    if CANONICAL_DATA_MODE not in ("shadow", "internal_primary", "primary"):
        return JSONResponse(
            status_code=404,
            content={"error": "Shadow comparison not available (CANONICAL_DATA_MODE must be 'shadow', 'internal_primary', or 'primary')"},
        )
    if shadow_comparison_report is None:
        return JSONResponse(
            status_code=404,
            content={"error": "No shadow comparison report generated yet. Ensure canonical snapshot and legacy data are both loaded."},
        )
    return JSONResponse(content=shadow_comparison_report)


@app.get("/api/scaffold/mode")
async def get_scaffold_mode():
    """Return current canonical data mode and status."""
    public_serves = (
        "canonical (primary mode — canonical calibrated values overlaid on legacy contract)"
        if CANONICAL_DATA_MODE == "primary"
        else "legacy (canonical data used for comparison/shadow only)"
    )
    return JSONResponse(content={
        "canonical_data_mode": CANONICAL_DATA_MODE,
        "canonical_loaded": canonical_data is not None,
        "canonical_loaded_at": canonical_data_loaded_at,
        "canonical_asset_count": len(canonical_data.get("assets", [])) if canonical_data else 0,
        "shadow_comparison_available": shadow_comparison_report is not None,
        "public_api_serves": public_serves,
        "internal_api_available": CANONICAL_DATA_MODE in ("internal_primary", "primary"),
        "rollback": "Set CANONICAL_DATA_MODE=off (or internal_primary) and restart to revert",
    })


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
    if canonical_data is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Canonical data not loaded. Trade suggestions require canonical values."},
        )
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON body"})

    roster = body.get("roster")
    if not isinstance(roster, list) or not roster:
        return JSONResponse(
            status_code=400,
            content={"error": "Request body must include 'roster' as a non-empty array of player names."},
        )

    from src.trade.suggestions import generate_suggestions

    league_rosters = body.get("league_rosters")
    if league_rosters is not None and not isinstance(league_rosters, list):
        league_rosters = None

    try:
        result = generate_suggestions(
            roster_names=roster,
            canonical_snapshot=canonical_data,
            league_rosters=league_rosters,
        )
    except Exception as e:
        log.error(f"Trade suggestion generation failed: {e}")
        return JSONResponse(status_code=500, content={"error": f"Suggestion generation failed: {e}"})

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
        result = find_trades(
            players=players,
            my_team=my_team,
            opponent_teams=opponent_teams,
            sleeper_teams=sleeper_teams,
        )
    except Exception as e:
        log.error(f"Trade Finder failed: {e}")
        return JSONResponse(status_code=500, content={"error": f"Trade Finder failed: {e}"})

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


@app.get("/api/scaffold/promotion")
async def get_scaffold_promotion():
    """Return promotion readiness check results for all modes.

    Evaluates the current state against thresholds defined in
    config/promotion/promotion_thresholds.json.
    """
    repo = Path(__file__).parent
    try:
        sys_path_backup = list(sys.path)
        if str(repo) not in sys.path:
            sys.path.insert(0, str(repo))
        from scripts.check_promotion_readiness import (
            check_shadow_readiness,
            check_internal_primary_readiness,
            check_public_primary_readiness,
        )
        results = {}
        for target, checker in [
            ("shadow", check_shadow_readiness),
            ("internal_primary", check_internal_primary_readiness),
            ("public_primary", check_public_primary_readiness),
        ]:
            checks = checker(repo)
            passed = sum(1 for c in checks if c.get("pass") is True)
            failed = sum(1 for c in checks if c.get("pass") is False)
            manual = sum(1 for c in checks if c.get("pass") is None)
            results[target] = {
                "ready": failed == 0 and manual == 0,
                "passed": passed,
                "failed": failed,
                "manual_verification": manual,
                "checks": checks,
            }
        results["current_mode"] = CANONICAL_DATA_MODE
        return JSONResponse(content=results)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Promotion check failed: {e}"},
        )


# ── DRAFT CAPITAL ──────────────────────────────────────────────────────
# Pick dollar values from CSV, rookie rankings from KTC (live) or CSV (fallback).
# Uses a decay curve to fill/extrapolate KTC values to all 72 picks.
DRAFT_DATA_XLSX = Path(__file__).parent / "CSVs" / "Draft Data.xlsx"
DRAFT_DATA_CSV = Path(__file__).parent / "CSVs" / "draft_data.csv"
SLEEPER_LEAGUE_ID_FOR_DRAFT = os.getenv("SLEEPER_LEAGUE_ID", "1312006700437352448")
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


def _fetch_draft_capital():
    """Compute draft capital per team.

    Values: workbook Q45:Q116 (rounded to integers summing to 1200).
    Ownership: Sleeper API (live traded-pick data).
    """
    pick_dollars, workbook_picks, slot_to_original, wb_team_totals, rookies = _parse_draft_data()
    if not pick_dollars:
        return {"error": "Draft data CSV not found or empty"}

    current_year = datetime.now(timezone.utc).year
    num_teams = 12
    draft_rounds = max(1, len(pick_dollars) // num_teams) if pick_dollars else 6

    # ── Per-pick dollar values from workbook (rounded to int, sum = 1200) ──
    if workbook_picks and len(workbook_picks) == len(pick_dollars):
        raw_values = [wp["value"] for wp in workbook_picks]
    else:
        raw_values = list(pick_dollars)
    int_values = _round_to_budget(raw_values, DRAFT_TOTAL_BUDGET)

    # ── Sleeper API: get team names + pick ownership ──
    roster_name_by_id = {}
    roster_ids = []
    owner_to_roster_id = {}
    roster_id_set = set()
    draft_slot_by_origin = {}
    pick_owner = {}  # (round, origin_rid) -> owner_rid

    try:
        rosters_resp = urllib.request.urlopen(
            f"https://api.sleeper.app/v1/league/{SLEEPER_LEAGUE_ID_FOR_DRAFT}/rosters", timeout=15
        )
        rosters = json.loads(rosters_resp.read())

        users_resp = urllib.request.urlopen(
            f"https://api.sleeper.app/v1/league/{SLEEPER_LEAGUE_ID_FOR_DRAFT}/users", timeout=15
        )
        user_map = {}
        for u in json.loads(users_resp.read()):
            uid = u.get("user_id")
            name = (u.get("metadata", {}).get("team_name")
                    or u.get("display_name")
                    or f"Team {uid}")
            user_map[uid] = name

        for r in rosters:
            rid = r.get("roster_id")
            if rid is not None:
                rid = int(rid)
                roster_ids.append(rid)
                oid = r.get("owner_id", "")
                if oid:
                    owner_to_roster_id[str(oid)] = rid
                roster_name_by_id[rid] = user_map.get(oid, f"Team {rid}")
        roster_id_set = set(roster_ids)
        num_teams = len(roster_ids) or 12
        draft_rounds = len(int_values) // num_teams

        drafts_resp = urllib.request.urlopen(
            f"https://api.sleeper.app/v1/league/{SLEEPER_LEAGUE_ID_FOR_DRAFT}/drafts", timeout=15
        )
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
            slot_to_roster = draft_detail.get("slot_to_roster_id") or draft.get("slot_to_roster_id") or {}
            if isinstance(slot_to_roster, dict):
                for slot, rid_val in slot_to_roster.items():
                    try:
                        s, r = int(slot), int(rid_val)
                    except (TypeError, ValueError):
                        continue
                    if r in roster_id_set and s > 0:
                        draft_slot_by_origin[r] = s
            if not draft_slot_by_origin:
                draft_order = draft_detail.get("draft_order") or draft.get("draft_order") or {}
                if isinstance(draft_order, dict):
                    for uid, slot in draft_order.items():
                        rid = owner_to_roster_id.get(str(uid))
                        try:
                            s = int(slot)
                        except (TypeError, ValueError):
                            continue
                        if rid in roster_id_set and s > 0:
                            draft_slot_by_origin[rid] = s

        if not draft_slot_by_origin:
            for i, rid in enumerate(sorted(roster_ids), 1):
                draft_slot_by_origin[rid] = i

        for rnd in range(1, draft_rounds + 1):
            for rid in roster_ids:
                pick_owner[(rnd, rid)] = rid

        tp_resp = urllib.request.urlopen(
            f"https://api.sleeper.app/v1/league/{SLEEPER_LEAGUE_ID_FOR_DRAFT}/traded_picks", timeout=15
        )
        for tp in json.loads(tp_resp.read()):
            try:
                season = int(tp.get("season"))
                rnd = int(tp.get("round"))
                origin_rid = int(tp.get("roster_id"))
                owner_rid = int(tp.get("owner_id"))
            except (TypeError, ValueError):
                continue
            if (season == current_year
                    and 1 <= rnd <= draft_rounds
                    and origin_rid in roster_id_set
                    and owner_rid in roster_id_set):
                pick_owner[(rnd, origin_rid)] = owner_rid

    except Exception as e:
        logging.warning(f"Sleeper API failed for draft capital, using workbook owners: {e}")
        roster_ids = []

    # ── Build pick list ──
    # Accumulate team totals from DECIMAL Q45:Q116 values so rounding
    # happens at the team level (matching the workbook), not per-pick.
    all_picks: list[dict] = []
    team_totals_decimal: dict[str, float] = {}

    if roster_ids:
        # Sleeper ownership available — pair workbook values with live owners
        for rnd in range(1, draft_rounds + 1):
            round_picks = []
            for origin_rid in roster_ids:
                slot = draft_slot_by_origin.get(origin_rid, 99)
                owner_rid = pick_owner.get((rnd, origin_rid), origin_rid)
                round_picks.append({"origin_rid": origin_rid, "owner_rid": owner_rid, "slot": slot})
            round_picks.sort(key=lambda p: p["slot"])

            for pick_in_round, pi in enumerate(round_picks):
                overall = (rnd - 1) * num_teams + pick_in_round
                dollar = int_values[overall] if overall < len(int_values) else 1
                origin_name = roster_name_by_id.get(pi["origin_rid"], f"Team {pi['origin_rid']}")
                owner_name = roster_name_by_id.get(pi["owner_rid"], f"Team {pi['owner_rid']}")
                is_traded = pi["origin_rid"] != pi["owner_rid"]

                # Use the decimal value from workbook for team total accumulation
                decimal_val = raw_values[overall] if overall < len(raw_values) else 1.0

                all_picks.append({
                    "pick": f"{rnd}.{str(pi['slot']).zfill(2)}",
                    "round": rnd,
                    "pickInRound": pick_in_round + 1,
                    "overallPick": overall + 1,
                    "dollarValue": dollar,
                    "adjustedDollarValue": dollar,
                    "originalOwner": origin_name,
                    "currentOwner": owner_name,
                    "isTraded": is_traded,
                    "isExpansion": pick_in_round < 2,
                    "rookieName": None,
                    "rookiePos": None,
                    "rookieKtcValue": None,
                })
                team_totals_decimal.setdefault(owner_name, 0.0)
                team_totals_decimal[owner_name] += decimal_val
    else:
        # No Sleeper data — use workbook owners as fallback
        for i, dollar in enumerate(int_values):
            rnd = i // num_teams + 1
            slot = i % num_teams + 1
            owner = workbook_picks[i]["owner"] if i < len(workbook_picks) else f"Pick {slot}"
            orig = slot_to_original.get(slot, owner)
            decimal_val = raw_values[i] if i < len(raw_values) else 1.0

            all_picks.append({
                "pick": f"{rnd}.{str(slot).zfill(2)}",
                "round": rnd,
                "pickInRound": slot,
                "overallPick": i + 1,
                "dollarValue": dollar,
                "adjustedDollarValue": dollar,
                "originalOwner": orig,
                "currentOwner": owner,
                "isTraded": orig != owner,
                "isExpansion": (i % num_teams) < 2,
                "rookieName": None,
                "rookiePos": None,
                "rookieKtcValue": None,
            })
            team_totals_decimal.setdefault(owner, 0.0)
            team_totals_decimal[owner] += decimal_val

    # ── Round team totals to integers summing to 1200 ──
    # Rounding at the team level (not per-pick) matches the workbook's
    # SUMIF-over-decimals approach and avoids ±$1 drift.
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
async def get_draft_capital(refresh: str = ""):
    """Return draft capital breakdown per team using Sleeper pick ownership
    and the pick value curve from the draft data spreadsheet.
    Pass ?refresh=1 to force a fresh KTC fetch."""
    if refresh:
        _ktc_cache["fetched_at"] = 0  # invalidate cache
    try:
        result = _fetch_draft_capital()
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


# Round ordinals used when synthesizing canonical pick names from the
# ``(season, round)`` the public activity feed carries.  Matches the
# labels used in ``src/api/data_contract.py`` and the frontend
# ``frontend/lib/trade-logic.js`` pick candidate builder.
_PUBLIC_ACTIVITY_ROUND_LABELS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", 6: "6th"}


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
    ships without grade annotations, which is the pre-existing
    behavior.
    """
    contract = latest_contract_data
    if not contract:
        return None
    players_array = contract.get("playersArray") or []
    if not players_array:
        return None

    # Alias map authored by the canonical pipeline — redirects generic
    # tier labels ("2026 Mid 1st") to slot-specific siblings
    # ("2026 Pick 1.06") when the latter exists.  Normalized to
    # lowercase so lookups match our tier-candidate probes.
    raw_aliases = contract.get("pickAliases") or {}
    pick_aliases: dict[str, str] = {}
    if isinstance(raw_aliases, dict):
        for k, v in raw_aliases.items():
            if isinstance(k, str) and isinstance(v, str):
                pick_aliases[k.lower()] = v.lower()

    by_id: dict[str, float] = {}
    by_name: dict[str, float] = {}
    for row in players_array:
        if not isinstance(row, dict):
            continue
        raw_val = (row.get("values") or {}).get("full")
        try:
            val = float(raw_val)
        except (TypeError, ValueError):
            continue
        if val <= 0:
            continue
        # Suppressed generic-tier pick rows keep a stale legacy value
        # for name-search purposes but are NOT authoritative — the
        # canonical pipeline aliases them to slot-specific siblings.
        # Excluding them from ``by_name`` ensures our tier probes
        # either hit the alias redirect or fall through to the real
        # slot row instead of returning stale tier data.
        suppressed = bool(row.get("pickGenericSuppressed"))
        pid = str(row.get("playerId") or "").strip()
        if pid and not suppressed:
            by_id[pid] = val
        name = str(row.get("displayName") or row.get("canonicalName") or "").strip()
        if name and not suppressed:
            by_name[name.lower()] = val

    if not by_id and not by_name:
        return None

    # Tier-center slot mapping.  Matches the canonical pipeline's
    # generic-tier suppression centers and the frontend's
    # ``TIER_CENTRE_SLOT`` in ``frontend/lib/trade-logic.js``:
    # Early=2, Mid=6, Late=10.  The public trade feed carries only
    # ``(season, round)``, so we probe the Mid (tier-center-6) slot
    # first and fall back to Early/Late centers.
    _TIER_CENTER_SLOTS = (("Mid", 6), ("Early", 2), ("Late", 10))

    def _resolve(name: str) -> float | None:
        key = name.lower()
        # Apply alias redirect first so generic tier labels hop to
        # their slot-specific siblings before hitting ``by_name``.
        aliased = pick_aliases.get(key)
        if aliased is not None:
            hit = by_name.get(aliased)
            if hit is not None:
                return hit
        return by_name.get(key)

    def _pick_value(season, round_) -> float:
        try:
            round_int = int(round_)
        except (TypeError, ValueError):
            return 0.0
        label = _PUBLIC_ACTIVITY_ROUND_LABELS.get(round_int)
        season_str = str(season or "").strip()
        if not label or not season_str:
            return 0.0
        # Tier labels first (redirected via pickAliases when the
        # canonical pipeline has a slot-specific sibling), then
        # slot-specific rows at the canonical tier centers.
        for tier, _slot in _TIER_CENTER_SLOTS:
            hit = _resolve(f"{season_str} {tier} {label}")
            if hit is not None:
                return hit
        for _tier, slot in _TIER_CENTER_SLOTS:
            hit = _resolve(
                f"{season_str} Pick {round_int}.{slot:02d}"
            )
            if hit is not None:
                return hit
        return 0.0

    def _valuation(asset) -> float:
        if not isinstance(asset, dict):
            return 0.0
        kind = asset.get("kind")
        if kind == "player":
            pid = str(asset.get("playerId") or "").strip()
            if pid:
                v = by_id.get(pid)
                if v is not None:
                    return v
            name = str(asset.get("playerName") or "").strip()
            if name:
                return by_name.get(name.lower(), 0.0)
            return 0.0
        if kind == "pick":
            return _pick_value(asset.get("season"), asset.get("round"))
        return 0.0

    return _valuation
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
    """Return the current public-facing league id.  Falls back to the
    same env default used by the private draft-capital route."""
    return os.getenv("SLEEPER_LEAGUE_ID", SLEEPER_LEAGUE_ID_FOR_DRAFT).strip()


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
async def trigger_scrape(background_tasks: BackgroundTasks):
    """Manually trigger a scrape. Returns immediately; scrape runs in background."""
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
    return JSONResponse(
        content={
            "authenticated": bool(session),
            "username": session.get("username") if session else None,
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

    session_id = _create_auth_session(username)
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
