"""
Dynasty Trade Calculator — Unified Server
==========================================
Single command to run everything:
    python server.py

Serves the dashboard at http://localhost:8000
Scrapes all sites on a configured interval (default: 4 hours).
Manual scrape: POST http://localhost:8000/api/scrape

Requirements:
    pip install fastapi uvicorn --break-system-packages
    (Playwright + other scraper deps assumed already installed)
"""

import asyncio
import html
import json
import os
import random
import sys
import time
import logging
import traceback
import smtplib
import gzip
import hashlib
import uuid
import urllib.request
import urllib.error
import urllib.parse
import shutil
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
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
    validate_api_data_contract,
)
from src.api.promotion_gate import (
    evaluate_promotion_candidate,
    load_promotion_gate_config,
)
from src.api.trade_scoring import score_trade_payload
from src.api.raw_fallback_health import scan_raw_fallback_health

# ── CONFIG ──────────────────────────────────────────────────────────────
def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return float(default)
    try:
        return float(raw)
    except Exception:
        return float(default)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return int(default)
    try:
        return int(float(raw))
    except Exception:
        return int(default)


SCRAPE_INTERVAL_HOURS = max(0.5, _env_float("SCRAPE_INTERVAL_HOURS", 4.0))
SCRAPE_INTERVAL_JITTER_MINUTES = max(0, _env_int("SCRAPE_INTERVAL_JITTER_MINUTES", 10))
SCRAPE_FAILURE_BACKOFF_MINUTES = max(0, _env_int("SCRAPE_FAILURE_BACKOFF_MINUTES", 60))
SCRAPE_MAX_BACKOFF_HOURS = max(
    SCRAPE_INTERVAL_HOURS,
    _env_float("SCRAPE_MAX_BACKOFF_HOURS", 12.0),
)
MAX_HEALTHY_SCRAPE_AGE_HOURS = max(
    SCRAPE_INTERVAL_HOURS,
    _env_float("MAX_HEALTHY_SCRAPE_AGE_HOURS", max(6.0, SCRAPE_INTERVAL_HOURS * 2.5)),
)
SCRAPE_SCHEDULER_ENABLED = str(os.getenv("SCRAPE_SCHEDULER_ENABLED", "true")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SCRAPE_STARTUP_ENABLED = str(os.getenv("SCRAPE_STARTUP_ENABLED", "true")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
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
FRONTEND_RUNTIME = (os.getenv("FRONTEND_RUNTIME") or "").strip().lower()
if FRONTEND_RUNTIME not in {"static", "next", "auto"}:
    # Explicit production default: static unless user intentionally overrides.
    FRONTEND_RUNTIME = "static"

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
_raw_jason_username_aliases = [
    str(part or "").strip()
    for part in str(os.getenv("JASON_LOGIN_USERNAME_ALIASES") or "").split(",")
]
JASON_LOGIN_USERNAME_ALIASES = tuple(
    alias
    for alias in dict.fromkeys(
        [JASON_LOGIN_USERNAME, "jason", *_raw_jason_username_aliases]
    )
    if alias
)


def _read_secret_file(path_like: str) -> str:
    path = Path(path_like).expanduser()
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


JASON_LOGIN_PASSWORD_FILE = str(
    os.getenv("JASON_LOGIN_PASSWORD_FILE")
    or ((Path(__file__).parent / ".secrets" / "jason_login_password").resolve())
).strip()
JASON_LOGIN_PASSWORD_DEFAULT = "Brisket2026!"
JASON_LOGIN_PASSWORD = str(
    os.getenv("JASON_LOGIN_PASSWORD")
    or _read_secret_file(JASON_LOGIN_PASSWORD_FILE)
    or JASON_LOGIN_PASSWORD_DEFAULT
    or ""
).strip()
JASON_AUTH_CONFIGURED = bool(JASON_LOGIN_PASSWORD)
JASON_AUTH_MISSING_PASSWORD_ERROR = (
    "Login unavailable: server auth is not configured. "
    "Set JASON_LOGIN_PASSWORD or JASON_LOGIN_PASSWORD_FILE."
)
JASON_AUTH_COOKIE_NAME = "jason_session"
JASON_AUTH_COOKIE_SECURE = _env_bool("JASON_AUTH_COOKIE_SECURE", False)

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


def _normalize_login_name(value: str | None) -> str:
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


def _is_valid_jason_username(username: str | None) -> bool:
    candidate = _normalize_login_name(username)
    if not candidate:
        return False
    allowed = {
        _normalize_login_name(alias)
        for alias in JASON_LOGIN_USERNAME_ALIASES
        if str(alias or "").strip()
    }
    return candidate in allowed


# ── PATHS ───────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"
LEGACY_STATIC_DIR = BASE_DIR / "Static"
FRONTEND_DIR = BASE_DIR / "frontend"
FRONTEND_NEXT_BUILD_DIR = FRONTEND_DIR / ".next"
FRONTEND_APP_DIR = FRONTEND_DIR / "app"
FRONTEND_LEAGUE_APP_DIR = FRONTEND_APP_DIR / "league"
SCRAPER_PATH = BASE_DIR / "Dynasty Scraper.py"
RUNTIME_JS_DIR = (LEGACY_STATIC_DIR / "js") if (LEGACY_STATIC_DIR / "js").exists() else (STATIC_DIR / "js")

LEAGUE_TOP_LEVEL_SLUGS = [
    "standings",
    "franchises",
    "awards",
    "draft",
    "trades",
    "records",
    "money",
    "constitution",
    "history",
    "league-media",
]
LEAGUE_TOP_LEVEL_ROUTES = ["/league", *[f"/league/{slug}" for slug in LEAGUE_TOP_LEVEL_SLUGS]]
LEAGUE_INLINE_FALLBACK_AUTHORITY = "public-league-inline-fallback-shell"

DATA_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)
VALIDATION_DIR = DATA_DIR / "validation"
VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
RUNTIME_LAST_GOOD_PATH = DATA_DIR / "runtime_last_good.json"
RUNTIME_LAST_GOOD_META_PATH = DATA_DIR / "runtime_last_good_meta.json"
DEPLOY_STATUS_PATH = DATA_DIR / "deploy_status.json"
PROMOTION_REPORT_LATEST_PATH = VALIDATION_DIR / "promotion_gate_latest.json"
PROMOTION_REPORT_GLOB = "promotion_gate_*.json"

# ── LOGGING ─────────────────────────────────────────────────────────────
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
# Lean runtime payload (drops heavy contract-only arrays not needed by Static app startup).
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
latest_source_health_snapshot: dict = {
    "total_sources": 0,
    "sources_with_data": 0,
    "source_counts": {},
    "missing_sources": [],
    "partial_run": False,
    "source_runtime": {},
    "source_failures": [],
}
promotion_gate_config = load_promotion_gate_config()
_runtime_route_authority_cache: dict | None = None
_runtime_route_authority_cache_at: float = 0.0
_deploy_status_cache: dict | None = None
_deploy_status_cache_at: float = 0.0
_deploy_status_cache_signature: tuple | None = None
_frontend_raw_fallback_health_cache: dict | None = None
_frontend_raw_fallback_health_cache_at: float = 0.0
promotion_gate_state: dict = {
    "lastAttemptAt": None,
    "lastSuccessAt": None,
    "lastFailureAt": None,
    "lastStatus": "unknown",
    "activePayloadPath": "",
    "activePayloadType": "",
    "lastReportPath": "",
    "lastFailureSummary": "",
    "lastGoodPath": str(RUNTIME_LAST_GOOD_PATH),
}
latest_promotion_report: dict = {
    "generatedAt": None,
    "status": "unknown",
    "summary": {
        "errors": ["promotion gate not initialized"],
        "warnings": [],
    },
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
    "consecutive_failures": 0,
    "run_events": [],
    "next_scrape_delay_sec": None,
}
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
    "configured": FRONTEND_RUNTIME,
    "active": "static",
    "reason": "configured_static_default",
    "fallbackFrom": None,
    "lastChecked": None,
}
# In-memory auth sessions for private-use gate.
auth_sessions: dict[str, dict] = {}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_snapshot(path: Path) -> dict:
    exists = path.exists()
    payload = {
        "path": str(path),
        "exists": bool(exists),
    }
    if exists:
        stat = path.stat()
        payload["sizeBytes"] = int(stat.st_size)
        payload["modifiedAt"] = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
    return payload


def _stamp_route_authority(response: Response, *, route_id: str, authority: str) -> Response:
    response.headers["X-Route-Id"] = route_id
    response.headers["X-Route-Authority"] = authority
    response.headers["X-Frontend-Runtime-Configured"] = FRONTEND_RUNTIME
    response.headers["X-Frontend-Runtime-Active"] = str(frontend_runtime_status.get("active") or "")
    return response


def _dedupe_paths_case_insensitive(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = os.path.normcase(str(path))
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def _league_static_root_candidates() -> list[Path]:
    return _dedupe_paths_case_insensitive([LEGACY_STATIC_DIR, STATIC_DIR])


def _league_asset_candidates(relative_path: str) -> list[Path]:
    rel = Path(relative_path)
    return [root / rel for root in _league_static_root_candidates()]


def _first_existing_path(candidates: list[Path]) -> Path | None:
    for path in candidates:
        if path.exists():
            return path
    return None


def _league_shell_artifact_status() -> dict[str, object]:
    entry_candidates = _league_asset_candidates("league/index.html")
    css_candidates = _league_asset_candidates("league/league.css")
    js_candidates = _league_asset_candidates("league/league.js")

    entry_path = _first_existing_path(entry_candidates)
    css_path = _first_existing_path(css_candidates)
    js_path = _first_existing_path(js_candidates)

    return {
        "entryCandidates": [str(path) for path in entry_candidates],
        "cssCandidates": [str(path) for path in css_candidates],
        "jsCandidates": [str(path) for path in js_candidates],
        "entryPath": str(entry_path) if entry_path else "",
        "cssPath": str(css_path) if css_path else "",
        "jsPath": str(js_path) if js_path else "",
        "entryExists": bool(entry_path),
        "cssExists": bool(css_path),
        "jsExists": bool(js_path),
        "fullyReady": bool(entry_path and css_path and js_path),
    }


def _normalize_league_route_slug(league_path: str = "") -> str:
    cleaned = str(league_path or "").strip().strip("/")
    if not cleaned:
        return "home"
    slug = cleaned.split("/", 1)[0].strip().lower()
    if slug in LEAGUE_TOP_LEVEL_SLUGS:
        return slug
    if slug == "home":
        return "home"
    return "unknown"


def _league_route_label(slug: str) -> str:
    if slug == "home":
        return "Home"
    if slug == "league-media":
        return "League Media"
    return slug.replace("-", " ").title()


def _build_league_inline_fallback_html(league_path: str = "") -> str:
    active_slug = _normalize_league_route_slug(league_path)
    raw_path = str(league_path or "").strip().strip("/")
    requested_path = "/league" if not raw_path else f"/league/{raw_path}"
    active_title = _league_route_label(active_slug) if active_slug != "unknown" else "League Route Not Found"
    safe_requested_path = html.escape(requested_path, quote=True)
    safe_title = html.escape(active_title, quote=True)
    safe_slug = html.escape(active_slug, quote=True)

    nav_rows = [("home", "Home", "/league")]
    nav_rows.extend((slug, _league_route_label(slug), f"/league/{slug}") for slug in LEAGUE_TOP_LEVEL_SLUGS)
    nav_html = []
    for slug, label, href in nav_rows:
        active = " active" if slug == active_slug else ""
        nav_html.append(
            (
                f'<a class="nav-link{active}" href="{html.escape(href, quote=True)}" '
                f'data-nav-slug="{html.escape(slug, quote=True)}">{html.escape(label)}</a>'
            )
        )
    nav_markup = "".join(nav_html)

    known_route_markup = "".join(
        f'<li><a href="{html.escape(route, quote=True)}">{html.escape(route)}</a></li>'
        for route in LEAGUE_TOP_LEVEL_ROUTES
    )

    template = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Risk It to Get the Brisket | League HQ (Fallback)</title>
  <style>
    :root {
      --bg: #f1f5f9;
      --card: #ffffff;
      --ink: #122338;
      --muted: #526072;
      --line: #d2d9e6;
      --warning-bg: #fff4dd;
      --warning-line: #ebb765;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Segoe UI", Arial, sans-serif;
      color: var(--ink);
      background:
        radial-gradient(900px 360px at 12% -10%, rgba(12, 55, 112, 0.12), transparent 60%),
        radial-gradient(700px 320px at 90% 110%, rgba(173, 83, 35, 0.09), transparent 60%),
        var(--bg);
    }
    .shell { width: min(1040px, 100%); margin: 0 auto; padding: 28px 20px 32px; }
    .header { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 14px; }
    .header h1 { margin: 0; font-size: clamp(1.35rem, 3vw, 1.9rem); }
    .header .sub { margin: 2px 0 0; color: var(--muted); font-size: 0.94rem; }
    .header a { color: var(--ink); text-decoration: none; font-weight: 600; }
    .warning {
      border: 1px solid var(--warning-line);
      background: var(--warning-bg);
      border-radius: 12px;
      padding: 12px 14px;
      margin-bottom: 14px;
      font-size: 0.92rem;
      line-height: 1.45;
    }
    .warning strong { display: block; margin-bottom: 4px; }
    .nav {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 8px;
      margin-bottom: 14px;
    }
    .nav-link {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 8px 11px;
      text-decoration: none;
      color: var(--ink);
      font-size: 0.89rem;
      background: rgba(255, 255, 255, 0.85);
      text-align: center;
    }
    .nav-link.active {
      background: #122338;
      color: #fff;
      border-color: #122338;
      font-weight: 700;
    }
    .grid {
      display: grid;
      grid-template-columns: 2fr 1fr;
      gap: 12px;
    }
    .card {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
      box-shadow: 0 10px 28px rgba(16, 25, 40, 0.08);
    }
    .card h2 { margin: 0 0 10px; font-size: 1.06rem; }
    .meta { color: var(--muted); font-size: 0.88rem; margin-bottom: 8px; }
    .list { margin: 0; padding-left: 18px; display: grid; gap: 4px; }
    .list a { color: #153861; }
    .kpi { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 8px; margin-top: 10px; }
    .kpi .tile { border: 1px solid var(--line); border-radius: 10px; padding: 10px; background: #fbfdff; }
    .tile .label { color: var(--muted); font-size: 0.79rem; margin-bottom: 4px; }
    .tile .value { font-size: 1.04rem; font-weight: 700; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace; }
    @media (max-width: 880px) {
      .grid { grid-template-columns: 1fr; }
      .shell { padding: 20px 14px 26px; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="header">
      <div>
        <h1>Risk It to Get the Brisket</h1>
        <p class="sub">Public League HQ</p>
      </div>
      <a href="/">Back to Landing</a>
    </header>

    <section class="warning">
      <strong>League shell fallback is active.</strong>
      The canonical static shell file (<span class="mono">Static/league/index.html</span>) was missing at runtime.
      This inline fallback keeps routes public and avoids a hard crash while deploy artifacts are repaired.
      Requested route: <span class="mono">__REQUESTED_PATH__</span>.
    </section>

    <nav class="nav" aria-label="League sections">
      __NAV_LINKS__
    </nav>

    <section class="grid">
      <article class="card">
        <h2>__ACTIVE_TITLE__</h2>
        <div class="meta">Active slug: <span class="mono">__ACTIVE_SLUG__</span></div>
        <p>This route is publicly accessible without Jason auth. The private valuation/trade routes remain gated.</p>
        <p>Known League top-level routes:</p>
        <ul class="list">__KNOWN_ROUTES__</ul>
      </article>

      <aside class="card">
        <h2>Live Public Data</h2>
        <div id="leagueFallbackData" class="meta">Loading /api/league/public…</div>
        <div class="kpi" id="leagueFallbackKpis"></div>
      </aside>
    </section>
  </main>

  <script>
    (() => {
      const dataNode = document.getElementById("leagueFallbackData");
      const kpiNode = document.getElementById("leagueFallbackKpis");

      const esc = (v) =>
        String(v ?? "")
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;");

      const setKpis = (pairs) => {
        if (!kpiNode) return;
        kpiNode.innerHTML = pairs
          .map(
            ([label, value]) =>
              `<div class="tile"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div></div>`,
          )
          .join("");
      };

      fetch("/api/league/public", { credentials: "same-origin" })
        .then(async (resp) => {
          const payload = await resp.json().catch(() => ({}));
          if (!resp.ok || !payload || payload.ok !== true) {
            const msg = payload && payload.error ? payload.error : `HTTP ${resp.status}`;
            throw new Error(msg);
          }
          const league = payload.league || {};
          const generatedAt = payload.generatedAt || payload.sourceLoadedAt || "unknown";
          if (dataNode) {
            dataNode.innerHTML =
              `League: <strong>${esc(league.leagueName || "League")}</strong><br/>` +
              `Generated: <span class="mono">${esc(generatedAt)}</span>`;
          }
          setKpis([
            ["Teams", league.teamCount ?? 0],
            ["Trades", league.tradeCount ?? 0],
            ["Draft Rounds", league.draftRounds ?? "n/a"],
          ]);
        })
        .catch((err) => {
          if (dataNode) {
            dataNode.textContent = `Public league payload unavailable: ${err && err.message ? err.message : "unknown error"}`;
          }
          setKpis([
            ["Teams", "n/a"],
            ["Trades", "n/a"],
            ["Draft Rounds", "n/a"],
          ]);
        });
    })();
  </script>
</body>
</html>
"""
    return (
        template
        .replace("__REQUESTED_PATH__", safe_requested_path)
        .replace("__ACTIVE_TITLE__", safe_title)
        .replace("__ACTIVE_SLUG__", safe_slug)
        .replace("__NAV_LINKS__", nav_markup)
        .replace("__KNOWN_ROUTES__", known_route_markup)
    )


def _runtime_route_authority_payload() -> dict:
    global _runtime_route_authority_cache, _runtime_route_authority_cache_at

    cache_ttl_sec = 15.0
    now = time.monotonic()
    if (
        _runtime_route_authority_cache is not None
        and (now - _runtime_route_authority_cache_at) < cache_ttl_sec
    ):
        return _runtime_route_authority_cache

    legacy_landing = LEGACY_STATIC_DIR / "landing.html"
    static_landing = STATIC_DIR / "landing.html"
    legacy_league_entry = LEGACY_STATIC_DIR / "league" / "index.html"
    static_league_entry = STATIC_DIR / "league" / "index.html"
    legacy_league_css = LEGACY_STATIC_DIR / "league" / "league.css"
    static_league_css = STATIC_DIR / "league" / "league.css"
    legacy_league_js = LEGACY_STATIC_DIR / "league" / "league.js"
    static_league_js = STATIC_DIR / "league" / "league.js"
    static_dashboard = STATIC_DIR / "index.html"
    legacy_dashboard = LEGACY_STATIC_DIR / "index.html"
    root_dashboard = BASE_DIR / "index.html"
    league_shell_status = _league_shell_artifact_status()
    league_runtime_authority = (
        "public-static-league-shell"
        if bool(league_shell_status.get("entryExists"))
        else LEAGUE_INLINE_FALLBACK_AUTHORITY
    )

    next_league_pages = []
    if FRONTEND_LEAGUE_APP_DIR.exists():
        next_league_pages = sorted(
            str(p.relative_to(BASE_DIR))
            for p in FRONTEND_LEAGUE_APP_DIR.rglob("page.*")
            if p.is_file()
        )

    warnings = []
    if FRONTEND_NEXT_BUILD_DIR.exists():
        warnings.append(
            "frontend/.next artifacts exist but are non-authoritative unless a separate Next server "
            "is reachable and FRONTEND_RUNTIME routes into next/auto proxy."
        )
    if FRONTEND_LEAGUE_APP_DIR.exists():
        if not next_league_pages:
            warnings.append(
                "frontend/app/league contains no page.* route sources; /league authority stays in Static/league/index.html."
            )
        else:
            warnings.append(
                "frontend/app/league page.* sources exist but are non-authoritative while /league is served by "
                "FastAPI static authority (serve_league_entry)."
            )
    if not bool(league_shell_status.get("entryExists")):
        warnings.append(
            "League static shell entry is missing; /league and /league/* will serve the inline emergency fallback "
            "authority instead of returning raw 500."
        )
    elif not bool(league_shell_status.get("fullyReady")):
        warnings.append(
            "League static shell entry exists but one or more dependent assets (league.css/league.js) are missing; "
            "route may render partially degraded."
        )

    routes = {
        "/": {
            "status": "complete",
            "access": "public",
            "handler": "serve_landing",
            "runtimeAuthority": "public-static-landing-shell",
            "sourceCandidates": [
                str(legacy_landing),
                str(static_landing),
            ],
        },
        "/league": {
            "status": "complete",
            "access": "public",
            "handler": "serve_league_entry",
            "runtimeAuthority": league_runtime_authority,
            "sourceCandidates": list(league_shell_status.get("entryCandidates") or []),
            "fallbackAuthority": LEAGUE_INLINE_FALLBACK_AUTHORITY,
            "fallbackEnabled": True,
            "nextProxyFallbackEnabled": False,
        },
        "/league/{league_path:path}": {
            "status": "complete",
            "access": "public",
            "handler": "serve_league_entry",
            "runtimeAuthority": league_runtime_authority,
            "expandedTopLevelRoutes": list(LEAGUE_TOP_LEVEL_ROUTES),
            "fallbackAuthority": LEAGUE_INLINE_FALLBACK_AUTHORITY,
            "fallbackEnabled": True,
            "nextProxyFallbackEnabled": False,
        },
        "/api/draft-capital": {
            "status": "complete",
            "access": "public",
            "handler": "get_draft_capital",
            "runtimeAuthority": "public-sleeper-pick-details-api",
            "sourceAuthority": "latest_data.sleeper.teams[].pickDetails",
        },
        "/app": {
            "status": "complete",
            "access": "auth-gated",
            "handler": "serve_dashboard",
            "authRedirect": "/?next=/app&jason=1",
            "runtimeAuthority": "private-shell-via-_serve_app_shell",
        },
        "/rankings": {
            "status": "complete",
            "access": "auth-gated",
            "handler": "serve_rankings",
            "authRedirect": "/?next=/rankings&jason=1",
            "runtimeAuthority": "private-shell-via-_serve_app_shell",
        },
        "/trade": {
            "status": "complete",
            "access": "auth-gated",
            "handler": "serve_trade",
            "authRedirect": "/?next=/trade&jason=1",
            "runtimeAuthority": "private-shell-via-_serve_app_shell",
        },
        "/calculator": {
            "status": "complete",
            "access": "auth-gated",
            "handler": "serve_calculator",
            "authRedirect": "/?next=/calculator&jason=1",
            "redirectTarget": "/trade",
            "runtimeAuthority": "private-trade-compat-redirect",
        },
    }
    for route in LEAGUE_TOP_LEVEL_ROUTES[1:]:
        routes[route] = {
            "status": "complete",
            "access": "public",
            "handler": "serve_league_entry",
            "runtimeAuthority": league_runtime_authority,
            "sourceAuthority": "/league/{league_path:path}",
            "fallbackAuthority": LEAGUE_INLINE_FALLBACK_AUTHORITY,
            "fallbackEnabled": True,
            "nextProxyFallbackEnabled": False,
        }

    payload = {
        "generatedAt": _utc_now_iso(),
        "configuredFrontendRuntime": FRONTEND_RUNTIME,
        "activeFrontendRuntime": frontend_runtime_status.get("active"),
        "frontendUrl": FRONTEND_URL,
        "routes": routes,
        "deployReadiness": {
            "leagueShell": {
                "ok": bool(league_shell_status.get("fullyReady")),
                "requiredForFullExperience": True,
                "runtimeFallbackEnabled": True,
                "runtimeFallbackAuthority": LEAGUE_INLINE_FALLBACK_AUTHORITY,
                "currentRuntimeAuthority": league_runtime_authority,
                "entryExists": bool(league_shell_status.get("entryExists")),
                "cssExists": bool(league_shell_status.get("cssExists")),
                "jsExists": bool(league_shell_status.get("jsExists")),
                "entryPath": league_shell_status.get("entryPath") or "",
                "cssPath": league_shell_status.get("cssPath") or "",
                "jsPath": league_shell_status.get("jsPath") or "",
            }
        },
        "privateShellResolutionOrder": {
            "static": [
                str(static_dashboard),
                str(legacy_dashboard),
                str(root_dashboard),
            ],
            "auto": [
                "next-proxy-if-reachable",
                str(static_dashboard),
                str(legacy_dashboard),
                str(root_dashboard),
            ],
            "next": [
                "next-proxy-only",
                "503 when unreachable (no static fallback)",
            ],
        },
        "artifacts": {
            "frontendNextBuild": _file_snapshot(FRONTEND_NEXT_BUILD_DIR),
            "frontendLeagueAppDir": _file_snapshot(FRONTEND_LEAGUE_APP_DIR),
            "frontendLeagueSourcePages": next_league_pages,
            "legacyLanding": _file_snapshot(legacy_landing),
            "legacyLeagueEntry": _file_snapshot(legacy_league_entry),
            "staticLeagueEntry": _file_snapshot(static_league_entry),
            "legacyLeagueCss": _file_snapshot(legacy_league_css),
            "staticLeagueCss": _file_snapshot(static_league_css),
            "legacyLeagueJs": _file_snapshot(legacy_league_js),
            "staticLeagueJs": _file_snapshot(static_league_js),
            "leagueShellStatus": league_shell_status,
            "legacyDashboard": _file_snapshot(legacy_dashboard),
        },
        "warnings": warnings,
    }
    _runtime_route_authority_cache = payload
    _runtime_route_authority_cache_at = now
    return payload


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
    response = RedirectResponse(url=f"/?next={encoded_next}&jason=1", status_code=302)
    return _stamp_route_authority(
        response,
        route_id=f"auth_gate:{request.url.path}",
        authority="auth-gate-redirect",
    )


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


def _file_signature(path: Path) -> tuple:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return ("missing", str(path))
    except Exception:
        return ("error", str(path))
    return ("present", str(path), int(stat.st_mtime_ns), int(stat.st_size))


def _load_deploy_status() -> dict:
    global _deploy_status_cache, _deploy_status_cache_at, _deploy_status_cache_signature

    cache_ttl_sec = 15.0
    now = time.monotonic()
    signature = _file_signature(DEPLOY_STATUS_PATH)
    if (
        _deploy_status_cache is not None
        and _deploy_status_cache_signature == signature
        and (now - _deploy_status_cache_at) < cache_ttl_sec
    ):
        return _deploy_status_cache

    payload = _load_json_from_path(DEPLOY_STATUS_PATH)
    if isinstance(payload, dict):
        _deploy_status_cache = payload
        _deploy_status_cache_at = now
        _deploy_status_cache_signature = signature
        return payload
    fallback = {
        "status": "unknown",
        "exists": False,
        "path": str(DEPLOY_STATUS_PATH),
    }
    _deploy_status_cache = fallback
    _deploy_status_cache_at = now
    _deploy_status_cache_signature = signature
    return fallback


def _load_frontend_raw_fallback_health() -> dict:
    global _frontend_raw_fallback_health_cache, _frontend_raw_fallback_health_cache_at
    now = time.time()
    cache_ttl_sec = 15.0
    if (
        _frontend_raw_fallback_health_cache is not None
        and (now - _frontend_raw_fallback_health_cache_at) < cache_ttl_sec
    ):
        return _frontend_raw_fallback_health_cache

    payload, _ = scan_raw_fallback_health(BASE_DIR, DATA_DIR, checked_at=_utc_now_iso())
    _frontend_raw_fallback_health_cache = payload
    _frontend_raw_fallback_health_cache_at = now
    return payload


def _compute_scrape_delay_seconds(
    *,
    failure_count: int,
    include_jitter: bool = True,
    forced_jitter_seconds: int | None = None,
) -> int:
    base_seconds = max(60, int(round(SCRAPE_INTERVAL_HOURS * 3600)))
    jitter_seconds = 0
    if forced_jitter_seconds is not None:
        jitter_seconds = max(0, int(forced_jitter_seconds))
    elif include_jitter and SCRAPE_INTERVAL_JITTER_MINUTES > 0:
        jitter_seconds = random.randint(0, SCRAPE_INTERVAL_JITTER_MINUTES * 60)

    failure_backoff_seconds = max(0, int(failure_count)) * max(0, SCRAPE_FAILURE_BACKOFF_MINUTES) * 60
    max_seconds = max(base_seconds, int(round(SCRAPE_MAX_BACKOFF_HOURS * 3600)))
    delay_seconds = min(max_seconds, base_seconds + failure_backoff_seconds + jitter_seconds)
    return max(60, int(delay_seconds))


def _set_next_scrape_from_policy(*, forced_jitter_seconds: int | None = None) -> int:
    delay_seconds = _compute_scrape_delay_seconds(
        failure_count=int(scrape_status.get("consecutive_failures", 0) or 0),
        include_jitter=True,
        forced_jitter_seconds=forced_jitter_seconds,
    )
    scrape_status["next_scrape_delay_sec"] = int(delay_seconds)
    scrape_status["next_scrape"] = (
        datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
    ).isoformat()
    return int(delay_seconds)


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


def _is_truthy_query_value(raw: str | None) -> bool:
    if raw is None:
        return False
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "y"}


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
            "consecutive_failures": 0,
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
            "consecutive_failures": int(scrape_status.get("consecutive_failures", 0) or 0) + 1,
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


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _load_json_from_path(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.error(f"Failed to load JSON from {path}: {e}")
        return None


def _summarize_gate_failure(report: dict) -> str:
    summary = report.get("summary") if isinstance(report, dict) else {}
    if not isinstance(summary, dict):
        return "promotion_gate_failed"
    errors = summary.get("errors") if isinstance(summary.get("errors"), list) else []
    critical = summary.get("criticalIssues") if isinstance(summary.get("criticalIssues"), list) else []
    pieces: list[str] = []
    if errors:
        pieces.append("errors=" + ",".join(str(x) for x in errors[:6]))
    if critical:
        pieces.append("critical=" + ",".join(str(x) for x in critical[:6]))
    if not pieces:
        pieces.append("promotion_gate_failed")
    return " | ".join(pieces)


def _persist_promotion_report(report: dict) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    status = str(report.get("status") or "unknown").lower()
    dated_path = VALIDATION_DIR / f"promotion_gate_{ts}_{status}.json"
    _write_json_atomic(dated_path, report)
    shutil.copy2(dated_path, PROMOTION_REPORT_LATEST_PATH)
    return dated_path


def _persist_last_good_payload(raw_payload: dict, report: dict, source_meta: dict) -> None:
    _write_json_atomic(RUNTIME_LAST_GOOD_PATH, raw_payload)
    meta = {
        "savedAt": _utc_now_iso(),
        "sourceMeta": source_meta,
        "promotionStatus": report.get("status"),
        "promotionReportPath": promotion_gate_state.get("lastReportPath"),
    }
    _write_json_atomic(RUNTIME_LAST_GOOD_META_PATH, meta)


def _load_last_good_payload() -> dict | None:
    payload = _load_json_from_path(RUNTIME_LAST_GOOD_PATH)
    if not isinstance(payload, dict):
        return None
    log.info("Loaded runtime last-known-good payload from %s", RUNTIME_LAST_GOOD_PATH)
    return payload


def _initialize_promotion_gate_state_from_disk() -> None:
    global latest_promotion_report
    existing_report = _load_json_from_path(PROMOTION_REPORT_LATEST_PATH)
    if isinstance(existing_report, dict):
        latest_promotion_report = existing_report
        promotion_gate_state["lastStatus"] = str(existing_report.get("status") or "unknown")
        promotion_gate_state["lastReportPath"] = str(PROMOTION_REPORT_LATEST_PATH)

    last_good_meta = _load_json_from_path(RUNTIME_LAST_GOOD_META_PATH)
    if isinstance(last_good_meta, dict):
        source_meta = last_good_meta.get("sourceMeta")
        if isinstance(source_meta, dict):
            promotion_gate_state["activePayloadPath"] = str(source_meta.get("path") or "")
            promotion_gate_state["activePayloadType"] = str(source_meta.get("type") or "")
        if last_good_meta.get("savedAt"):
            promotion_gate_state["lastSuccessAt"] = str(last_good_meta.get("savedAt"))


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


def _runtime_architecture_truth() -> dict:
    """
    Single truth block for what is actually authoritative in the live runtime.

    This intentionally de-scopes broad src/ pipeline authority claims until
    canonical/identity/league scaffolds are wired into /api/data publication.
    """
    return {
        "decision": "de_scope_src_pipeline_until_live",
        "authoritative_runtime_path": {
            "payload_producer": "Dynasty Scraper.py::run",
            "payload_contract_builder": "src.api.data_contract.build_api_data_contract",
            "runtime_endpoint": "/api/data",
            "frontend_runtime_mode": FRONTEND_RUNTIME,
            "contract_version": API_DATA_CONTRACT_VERSION,
        },
        "live_src_modules": [
            "src.api.data_contract",
            "src.scoring (optional import path used by Dynasty Scraper.py)",
        ],
        "non_authoritative_src_pipeline": [
            "src.adapters + scripts/source_pull.py",
            "src.identity + scripts/identity_resolve.py",
            "src.canonical + scripts/canonical_build.py",
            "src.league + scripts/league_refresh.py",
        ],
        "scaffold_endpoints": [
            "/api/scaffold/status",
            "/api/scaffold/raw",
            "/api/scaffold/canonical",
            "/api/scaffold/league",
            "/api/scaffold/identity",
            "/api/scaffold/validation",
            "/api/scaffold/report",
        ],
        "scaffold_authority": "non_authoritative_debug_only",
    }


def _set_frontend_runtime_status(active: str, reason: str, fallback_from: str | None = None) -> None:
    prev = (
        frontend_runtime_status.get("active"),
        frontend_runtime_status.get("reason"),
        frontend_runtime_status.get("fallbackFrom"),
    )
    frontend_runtime_status.update(
        {
            "configured": FRONTEND_RUNTIME,
            "active": active,
            "reason": reason,
            "fallbackFrom": fallback_from,
            "lastChecked": _utc_now_iso(),
        }
    )
    current = (active, reason, fallback_from)
    if current != prev:
        log.info(
            "[Frontend Runtime] configured=%s active=%s reason=%s fallback_from=%s",
            FRONTEND_RUNTIME,
            active,
            reason,
            fallback_from,
        )


def _resolve_frontend_path(path: str) -> Response | None:
    mode = FRONTEND_RUNTIME

    if mode == "static":
        _set_frontend_runtime_status("static", "configured_static_mode")
        return None

    proxied, err = _proxy_next(path)

    if mode == "next":
        if proxied is not None:
            _set_frontend_runtime_status("next", "configured_next_mode")
            return proxied
        _set_frontend_runtime_status("next-unavailable", "configured_next_mode_but_unreachable")
        return HTMLResponse(
            (
                "<h1>Next frontend unavailable</h1>"
                f"<p>FRONTEND_RUNTIME is set to <code>next</code> but proxy failed: {err or 'unknown error'}</p>"
                "<p>Start Next on FRONTEND_URL or set FRONTEND_RUNTIME=static/auto.</p>"
            ),
            status_code=503,
        )

    # auto mode
    if proxied is not None:
        _set_frontend_runtime_status("next", "auto_mode_next_available")
        return proxied
    _set_frontend_runtime_status("static", "auto_mode_fallback_to_static", fallback_from="next")
    return None


# Initialize runtime status at process boot.
if FRONTEND_RUNTIME == "static":
    _set_frontend_runtime_status("static", "configured_static_mode")
elif FRONTEND_RUNTIME == "next":
    _set_frontend_runtime_status("next", "configured_next_mode_pending_probe")
else:
    _set_frontend_runtime_status("auto", "configured_auto_mode_pending_probe")


# ── SCRAPER INTEGRATION ────────────────────────────────────────────────
def _prime_latest_payload(
    data: dict | None,
    *,
    contract_payload: dict | None = None,
    contract_report: dict | None = None,
) -> bool:
    """Pre-serialize latest payload once so /api/data returns instantly."""
    global latest_contract_data, latest_data_bytes, latest_data_gzip_bytes, latest_data_etag
    global latest_runtime_data, latest_runtime_data_bytes, latest_runtime_data_gzip_bytes, latest_runtime_data_etag
    global latest_startup_data, latest_startup_data_bytes, latest_startup_data_gzip_bytes, latest_startup_data_etag
    global latest_source_health_snapshot
    global contract_health
    if not data:
        return False
    try:
        built_contract = contract_payload or build_api_data_contract(data, data_source=latest_data_source)
        report = contract_report or validate_api_data_contract(built_contract)
        built_contract["contractHealth"] = {
            "ok": bool(report.get("ok")),
            "status": report.get("status"),
            "errorCount": int(report.get("errorCount", 0)),
            "warningCount": int(report.get("warningCount", 0)),
            "checkedAt": report.get("checkedAt"),
        }
        raw = json.dumps(built_contract, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        full_gzip = gzip.compress(raw, compresslevel=5)
        full_etag = hashlib.sha1(raw).hexdigest()

        # Static runtime payload: keep canonical top-level data shape used by the live UI,
        # but remove heavyweight contract array duplication to reduce parse/transfer cost.
        runtime_payload = dict(built_contract)
        runtime_payload.pop("playersArray", None)
        runtime_payload["payloadView"] = "runtime"
        runtime_raw = json.dumps(runtime_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        runtime_gzip = gzip.compress(runtime_raw, compresslevel=5)
        runtime_etag = hashlib.sha1(runtime_raw).hexdigest()

        # Startup payload: same contract shape, but strips heavyweight fields
        # not needed for first screen render so first data-visible is faster.
        startup_payload = build_api_startup_payload(runtime_payload)
        startup_raw = json.dumps(startup_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        startup_gzip = gzip.compress(startup_raw, compresslevel=5)
        startup_etag = hashlib.sha1(startup_raw).hexdigest()
    except Exception as e:
        if latest_contract_data is None:
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
        return False

    latest_contract_data = built_contract
    latest_data_bytes = raw
    latest_data_gzip_bytes = full_gzip
    latest_data_etag = full_etag
    latest_runtime_data = runtime_payload
    latest_runtime_data_bytes = runtime_raw
    latest_runtime_data_gzip_bytes = runtime_gzip
    latest_runtime_data_etag = runtime_etag
    latest_startup_data = startup_payload
    latest_startup_data_bytes = startup_raw
    latest_startup_data_gzip_bytes = startup_gzip
    latest_startup_data_etag = startup_etag
    contract_health = report
    latest_source_health_snapshot = _build_source_health_snapshot(data)
    if not report.get("ok"):
        log.error(
            "API contract validation failed: %s",
            "; ".join((report.get("errors") or [])[:5]),
        )
    return True


def load_from_disk() -> dict | None:
    """Load most recent dynasty_data_*.json from data/ directory."""
    last_good = _load_last_good_payload()
    if isinstance(last_good, dict) and isinstance(last_good.get("players"), dict) and last_good.get("players"):
        _set_latest_data_source("runtime_last_good", str(RUNTIME_LAST_GOOD_PATH))
        return last_good

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


def _safe_int(v) -> int | None:
    try:
        return int(v)
    except Exception:
        return None


def _trade_ts_to_iso(raw_ts) -> str | None:
    ts = _safe_int(raw_ts)
    if ts is None or ts <= 0:
        return None
    # Sleeper timestamps are normally ms, but normalize defensively.
    if ts < 1_000_000_000_000:
        ts *= 1000
    try:
        return datetime.fromtimestamp(ts / 1000.0, timezone.utc).isoformat()
    except Exception:
        return None


def _build_draft_capital_payload(source_data: dict | None) -> dict:
    if not isinstance(source_data, dict):
        return {
            "ok": False,
            "error": "Draft capital data not ready yet.",
            "generatedAt": _utc_now_iso(),
            "sourceLoadedAt": latest_data_source.get("loadedAt"),
            "sourceType": latest_data_source.get("type"),
        }

    sleeper = source_data.get("sleeper")
    if not isinstance(sleeper, dict):
        return {
            "ok": False,
            "error": "Sleeper league block is unavailable.",
            "generatedAt": _utc_now_iso(),
            "sourceLoadedAt": latest_data_source.get("loadedAt"),
            "sourceType": latest_data_source.get("type"),
        }

    teams_raw = sleeper.get("teams")
    if not isinstance(teams_raw, list):
        teams_raw = []

    league_settings = sleeper.get("leagueSettings")
    draft_rounds = _safe_int(league_settings.get("draft_rounds")) if isinstance(league_settings, dict) else None
    league_season_map: dict[int, dict] = {}
    teams = []
    total_pick_count = 0

    for team in teams_raw:
        if not isinstance(team, dict):
            continue

        roster_id = _safe_int(team.get("roster_id") or team.get("rosterId"))
        team_name = str(team.get("name") or "Team").strip()
        raw_pick_details = team.get("pickDetails")
        if not isinstance(raw_pick_details, list):
            raw_pick_details = []

        pick_details = []
        season_map: dict[int, dict] = {}
        own_pick_count = 0
        acquired_pick_count = 0

        for detail in raw_pick_details:
            if not isinstance(detail, dict):
                continue

            season = _safe_int(detail.get("season"))
            round_num = _safe_int(detail.get("round"))
            owner_roster_id = _safe_int(detail.get("ownerRosterId"))
            from_roster_id = _safe_int(detail.get("fromRosterId"))
            if season is None or round_num is None:
                continue

            slot = _safe_int(detail.get("slot"))
            is_original_owner = (
                owner_roster_id is not None
                and from_roster_id is not None
                and owner_roster_id == from_roster_id
            )
            if is_original_owner:
                own_pick_count += 1
            else:
                acquired_pick_count += 1

            pick_details.append(
                {
                    "season": season,
                    "round": round_num,
                    "slot": slot,
                    "label": str(detail.get("label") or "").strip() or None,
                    "baseLabel": str(detail.get("baseLabel") or "").strip() or None,
                    "fromTeam": str(detail.get("fromTeam") or "").strip() or None,
                    "fromRosterId": from_roster_id,
                    "ownerRosterId": owner_roster_id,
                    "isOriginalOwner": is_original_owner,
                }
            )

            team_season = season_map.setdefault(
                season,
                {
                    "season": season,
                    "total": 0,
                    "own": 0,
                    "acquired": 0,
                    "roundCounts": {},
                },
            )
            team_season["total"] += 1
            if is_original_owner:
                team_season["own"] += 1
            else:
                team_season["acquired"] += 1
            round_key = str(round_num)
            team_season["roundCounts"][round_key] = int(team_season["roundCounts"].get(round_key, 0) or 0) + 1

            league_season = league_season_map.setdefault(
                season,
                {
                    "season": season,
                    "teamCount": 0,
                    "total": 0,
                    "teams": {},
                },
            )
            league_season["total"] += 1
            if roster_id is not None:
                league_team = league_season["teams"].setdefault(
                    roster_id,
                    {
                        "rosterId": roster_id,
                        "team": team_name,
                        "total": 0,
                        "roundCounts": {},
                    },
                )
                league_team["total"] += 1
                league_team["roundCounts"][round_key] = int(league_team["roundCounts"].get(round_key, 0) or 0) + 1

        pick_details.sort(
            key=lambda item: (
                int(item.get("season") or 9999),
                int(item.get("round") or 9),
                int(item.get("slot") or 99),
                str(item.get("fromTeam") or ""),
            )
        )
        season_summaries = []
        for season in sorted(season_map):
            summary = season_map[season]
            summary["roundCounts"] = {
                key: summary["roundCounts"][key]
                for key in sorted(summary["roundCounts"], key=lambda value: int(value))
            }
            season_summaries.append(summary)

        total_pick_count += len(pick_details)
        teams.append(
            {
                "name": team_name,
                "rosterId": roster_id,
                "pickCount": len(pick_details),
                "ownPickCount": own_pick_count,
                "acquiredPickCount": acquired_pick_count,
                "seasonSummaries": season_summaries,
                "pickDetails": pick_details,
            }
        )

    teams.sort(key=lambda item: str(item.get("name") or "").lower())

    seasons = []
    for season in sorted(league_season_map):
        season_payload = league_season_map[season]
        teams_for_season = list(season_payload.get("teams", {}).values())
        teams_for_season.sort(key=lambda item: str(item.get("team") or "").lower())
        season_payload["teamCount"] = len(teams_for_season)
        season_payload["teams"] = teams_for_season
        seasons.append(season_payload)

    return {
        "ok": True,
        "generatedAt": _utc_now_iso(),
        "sourceLoadedAt": latest_data_source.get("loadedAt"),
        "sourceType": latest_data_source.get("type"),
        "league": {
            "leagueId": str(sleeper.get("leagueId") or "").strip() or None,
            "leagueName": str(sleeper.get("leagueName") or "").strip() or "League",
            "teamCount": len(teams),
            "draftRounds": draft_rounds,
        },
        "summary": {
            "teamCount": len(teams),
            "seasonCount": len(seasons),
            "pickCount": total_pick_count,
        },
        "teams": teams,
        "seasons": seasons,
    }


def _build_public_league_payload(source_data: dict | None) -> dict:
    """
    Build a strict public-safe League payload.

    This intentionally excludes private valuation/calculator internals and only
    ships league identity/context summary fields.
    """
    if not isinstance(source_data, dict):
        return {
            "ok": False,
            "error": "League data not ready yet.",
            "generatedAt": _utc_now_iso(),
            "sourceLoadedAt": latest_data_source.get("loadedAt"),
            "sourceType": latest_data_source.get("type"),
        }

    sleeper = source_data.get("sleeper")
    if not isinstance(sleeper, dict):
        return {
            "ok": False,
            "error": "Sleeper league block is unavailable.",
            "generatedAt": _utc_now_iso(),
            "sourceLoadedAt": latest_data_source.get("loadedAt"),
            "sourceType": latest_data_source.get("type"),
        }

    teams_raw = sleeper.get("teams")
    if not isinstance(teams_raw, list):
        teams_raw = []

    team_summaries = []
    for team in teams_raw:
        if not isinstance(team, dict):
            continue
        players = team.get("players")
        picks = team.get("picks")
        pick_details = team.get("pickDetails")
        team_summaries.append(
            {
                "name": str(team.get("name") or "Team").strip(),
                "rosterId": _safe_int(team.get("roster_id")),
                "playerCount": len(players) if isinstance(players, list) else 0,
                "pickCount": len(picks) if isinstance(picks, list) else 0,
                "pickDetailCount": len(pick_details) if isinstance(pick_details, list) else 0,
            }
        )
    team_summaries.sort(key=lambda row: str(row.get("name") or "").lower())

    trades_raw = sleeper.get("trades")
    if not isinstance(trades_raw, list):
        trades_raw = []
    trades_sorted = sorted(
        [t for t in trades_raw if isinstance(t, dict)],
        key=lambda t: int(t.get("timestamp") or 0),
        reverse=True,
    )

    recent_trades = []
    for trade in trades_sorted[:8]:
        sides = trade.get("sides")
        side_summaries = []
        if isinstance(sides, list):
            for side in sides[:4]:
                if not isinstance(side, dict):
                    continue
                got = side.get("got")
                gave = side.get("gave")
                side_summaries.append(
                    {
                        "team": str(side.get("team") or "Team").strip(),
                        "rosterId": _safe_int(side.get("rosterId")),
                        "gotCount": len(got) if isinstance(got, list) else 0,
                        "gaveCount": len(gave) if isinstance(gave, list) else 0,
                    }
                )
        recent_trades.append(
            {
                "leagueId": str(trade.get("leagueId") or "").strip() or None,
                "week": _safe_int(trade.get("week")),
                "timestampIso": _trade_ts_to_iso(trade.get("timestamp")),
                "sideSummaries": side_summaries,
            }
        )

    scoring_settings = sleeper.get("scoringSettings")
    league_settings = sleeper.get("leagueSettings")
    roster_positions = sleeper.get("rosterPositions")

    payload = {
        "ok": True,
        "generatedAt": _utc_now_iso(),
        "sourceLoadedAt": latest_data_source.get("loadedAt"),
        "sourceType": latest_data_source.get("type"),
        "league": {
            "leagueId": str(sleeper.get("leagueId") or "").strip() or None,
            "leagueName": str(sleeper.get("leagueName") or "").strip() or "League",
            "teamCount": len(team_summaries),
            "tradeCount": len(trades_sorted),
            "tradeWindowDays": _safe_int(sleeper.get("tradeWindowDays")),
            "tradeWindowStart": str(sleeper.get("tradeWindowStart") or "").strip() or None,
            "scoringSettingCount": len(scoring_settings) if isinstance(scoring_settings, dict) else 0,
            "draftRounds": (
                _safe_int(league_settings.get("draft_rounds"))
                if isinstance(league_settings, dict)
                else None
            ),
            "rosterSlotCount": len(roster_positions) if isinstance(roster_positions, list) else 0,
        },
        "teams": team_summaries,
        "recentTrades": recent_trades,
        "moduleStatus": {
            "home": "scaffold_live",
            "standings": "scaffold_waiting_historical_data",
            "franchises": "directory_live_detail_pending",
            "awards": "methodology_defined_data_gated",
            "draft": "scaffold_waiting_historical_data",
            "trades": "rolling_window_live_historical_pending",
            "records": "scaffold_waiting_historical_data",
            "money": "manual_ledger_pending",
            "constitution": "manual_content_pending",
            "history": "scaffold_waiting_historical_data",
            "leagueMedia": "manual_publishing_pending",
        },
        "note": (
            "Public-safe subset. Private valuation, rankings, and calculator internals "
            "are intentionally excluded."
        ),
    }
    return payload


def _attempt_runtime_promotion(
    *,
    candidate_payload: dict,
    trigger: str,
    source_type: str,
    source_path: str,
) -> tuple[bool, dict]:
    global latest_data, latest_promotion_report

    candidate_source_meta = {
        "type": str(source_type or ""),
        "path": str(source_path or ""),
        "loadedAt": _utc_now_iso(),
    }
    previous_source_meta = dict(latest_data_source)
    promotion_gate_state["lastAttemptAt"] = candidate_source_meta["loadedAt"]

    contract_payload = build_api_data_contract(candidate_payload, data_source=candidate_source_meta)
    contract_report = validate_api_data_contract(contract_payload)
    report = evaluate_promotion_candidate(
        raw_payload=candidate_payload,
        contract_payload=contract_payload,
        contract_report=contract_report,
        repo_root=BASE_DIR,
        trigger=trigger,
        source_meta=candidate_source_meta,
        baseline_raw_payload=latest_data if isinstance(latest_data, dict) else None,
        baseline_contract_payload=(
            latest_contract_data
            if isinstance(latest_contract_data, dict)
            else None
        ),
        config=promotion_gate_config,
    )

    report_path = _persist_promotion_report(report)
    latest_promotion_report = report
    promotion_gate_state["lastReportPath"] = str(report_path)
    promotion_gate_state["lastStatus"] = str(report.get("status") or "unknown")

    if str(report.get("status")) != "pass":
        summary_text = _summarize_gate_failure(report)
        promotion_gate_state["lastFailureAt"] = _utc_now_iso()
        promotion_gate_state["lastFailureSummary"] = summary_text
        return False, report

    _set_latest_data_source(candidate_source_meta["type"], candidate_source_meta["path"])
    primed = _prime_latest_payload(
        candidate_payload,
        contract_payload=contract_payload,
        contract_report=contract_report,
    )
    if not primed:
        latest_data_source.update(previous_source_meta)
        prime_failure_report = {
            "generatedAt": _utc_now_iso(),
            "status": "fail",
            "trigger": trigger,
            "sourceMeta": candidate_source_meta,
            "summary": {
                "errors": ["promotion_cache_prime_failed"],
                "warnings": [],
                "criticalIssues": [],
            },
            "gates": {
                "cachePrime": {
                    "ok": False,
                    "reason": "failed_to_prime_runtime_cache",
                }
            },
        }
        fail_path = _persist_promotion_report(prime_failure_report)
        latest_promotion_report = prime_failure_report
        promotion_gate_state["lastReportPath"] = str(fail_path)
        promotion_gate_state["lastStatus"] = "fail"
        promotion_gate_state["lastFailureAt"] = _utc_now_iso()
        promotion_gate_state["lastFailureSummary"] = "promotion_cache_prime_failed"
        return False, prime_failure_report

    latest_data = candidate_payload
    promotion_gate_state["lastSuccessAt"] = _utc_now_iso()
    promotion_gate_state["lastFailureSummary"] = ""
    promotion_gate_state["activePayloadPath"] = candidate_source_meta["path"]
    promotion_gate_state["activePayloadType"] = candidate_source_meta["type"]
    _persist_last_good_payload(candidate_payload, report, candidate_source_meta)
    return True, report


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

            _update_scrape_progress(
                step="publish",
                source="promotion_gate",
                step_index=4,
                step_total=4,
                event="phase_start",
                message="Running promotion validation + publish gate",
            )
            result_date = str(result.get("date") or "").strip()
            source_path = ""
            if result_date:
                candidate = DATA_DIR / f"dynasty_data_{result_date}.json"
                if candidate.exists():
                    source_path = str(candidate)
            promoted, promotion_report = _attempt_runtime_promotion(
                candidate_payload=result,
                trigger=trigger,
                source_type="scrape_run",
                source_path=source_path,
            )
            if not promoted:
                failure_summary = _summarize_gate_failure(promotion_report)
                raise RuntimeError(f"Promotion gate rejected scrape output: {failure_summary}")

            elapsed = time.time() - start
            player_count = len(result.get("players", {}))
            site_count = len([s for s in result.get("sites", []) if s.get("playerCount", 0) > 0])
            total_sites = len(result.get("sites", []))

            _mark_scrape_success(elapsed, player_count, site_count, total_sites)

            log.info(
                f"SCRAPE COMPLETE — {player_count} players, "
                f"{site_count}/{total_sites} sites, {elapsed:.1f}s"
            )

            # Alert if fewer than half the sites returned data
            if total_sites > 0 and site_count < total_sites / 2:
                send_alert(
                    f"Scrape partial: only {site_count}/{total_sites} sites",
                    (
                        f"Players: {player_count}\n"
                        f"Sites with data: {site_count}/{total_sites}\n"
                        f"Duration: {elapsed:.1f}s\n\n"
                        "Some sites may be down or blocking the scraper."
                    ),
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
    """Called by the background scheduler according to policy-configured cadence."""
    log.info(
        "Scheduled scrape triggered (base_interval=%.2fh, failure_streak=%s)",
        SCRAPE_INTERVAL_HOURS,
        int(scrape_status.get("consecutive_failures", 0) or 0),
    )
    await run_scraper(trigger="scheduled")
    _set_next_scrape_from_policy()


async def schedule_loop():
    """Async loop that runs scraper on policy-controlled cadence with backoff + jitter."""
    if not SCRAPE_SCHEDULER_ENABLED:
        scrape_status["next_scrape"] = None
        scrape_status["next_scrape_delay_sec"] = None
        _record_scrape_event(
            "scrape_scheduler_disabled",
            level="warning",
            message="SCRAPE_SCHEDULER_ENABLED=false; recurring scheduler loop is disabled",
        )
        return

    while True:
        delay_seconds = _set_next_scrape_from_policy()
        await asyncio.sleep(max(30, delay_seconds))
        try:
            await scheduled_scrape()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _record_scrape_event(
                "scrape_scheduler_loop_error",
                level="error",
                message=f"{type(exc).__name__}: {exc}",
            )
            await asyncio.sleep(60)


# ── APP LIFECYCLE ───────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: load cached data + optionally kick off first scrape + start scheduler."""
    global latest_data

    _initialize_promotion_gate_state_from_disk()

    # 1. Load cached data immediately so the dashboard is usable right away
    cached = load_from_disk()
    if cached:
        cached_source_type = str(latest_data_source.get("type") or "")
        cached_source_path = str(latest_data_source.get("path") or "")
        if cached_source_type == "runtime_last_good":
            latest_data = cached
            primed = _prime_latest_payload(latest_data)
            if primed:
                promotion_gate_state["lastStatus"] = "pass"
                promotion_gate_state["lastSuccessAt"] = _utc_now_iso()
                promotion_gate_state["activePayloadType"] = cached_source_type
                promotion_gate_state["activePayloadPath"] = cached_source_path
                log.info("Dashboard ready with runtime last-known-good data")
            else:
                log.error("Failed to prime runtime last-known-good payload at startup")
        else:
            promoted, report = _attempt_runtime_promotion(
                candidate_payload=cached,
                trigger="startup_cache_load",
                source_type=cached_source_type or "disk_cache",
                source_path=cached_source_path,
            )
            if promoted:
                log.info("Dashboard ready with startup cache data (promotion-gated)")
            else:
                latest_data = _load_last_good_payload()
                if latest_data and _prime_latest_payload(latest_data):
                    _set_latest_data_source("runtime_last_good", str(RUNTIME_LAST_GOOD_PATH))
                    log.warning(
                        "Startup cache failed promotion; serving last-known-good payload instead (%s)",
                        _summarize_gate_failure(report),
                    )
                else:
                    latest_data = None
                    log.error(
                        "Startup cache failed promotion and no last-known-good payload was available (%s)",
                        _summarize_gate_failure(report),
                    )
    else:
        log.info("No cached data found — dashboard will show empty until first scrape completes")

    # 2. Optionally start first scrape in background (don't block startup)
    scrape_task = None
    if SCRAPE_STARTUP_ENABLED:
        async def initial_scrape():
            await asyncio.sleep(3)  # small delay to let server finish booting
            await run_scraper(trigger="startup")

        scrape_task = asyncio.create_task(initial_scrape())
    else:
        log.info("Startup scrape disabled (SCRAPE_STARTUP_ENABLED=false)")

    # 3. Start the recurring schedule
    scheduler_task = asyncio.create_task(schedule_loop()) if SCRAPE_SCHEDULER_ENABLED else None
    uptime_task = asyncio.create_task(uptime_watchdog_loop())

    log.info(
        "Server started — scrape scheduler=%s base_interval=%.2fh jitter=%sm failure_backoff=%sm max_backoff=%.2fh",
        "enabled" if SCRAPE_SCHEDULER_ENABLED else "disabled",
        SCRAPE_INTERVAL_HOURS,
        SCRAPE_INTERVAL_JITTER_MINUTES,
        SCRAPE_FAILURE_BACKOFF_MINUTES,
        SCRAPE_MAX_BACKOFF_HOURS,
    )
    if os.getenv("FRONTEND_RUNTIME") is None:
        log.info(
            "FRONTEND_RUNTIME not set; defaulting to static. "
            "Set FRONTEND_RUNTIME=auto|next to proxy Next intentionally."
        )
    if os.getenv("ENABLE_NEXT_FRONTEND_PROXY") is not None:
        log.warning(
            "ENABLE_NEXT_FRONTEND_PROXY is deprecated and ignored. "
            "Use FRONTEND_RUNTIME=static|auto|next."
        )
    log.info("Frontend runtime configured: %s (frontend_url=%s)", FRONTEND_RUNTIME, FRONTEND_URL)
    if not JASON_AUTH_CONFIGURED:
        log.error(
            "JASON_LOGIN_PASSWORD is not set. Private routes remain auth-gated, "
            "but login is disabled until JASON_LOGIN_PASSWORD is configured."
        )
    authority = _runtime_route_authority_payload()
    for warning in authority.get("warnings", []):
        log.warning("[Route Authority] %s", warning)
    log.info(f"Dashboard: http://localhost:{PORT}")

    yield  # app is running

    # Cleanup
    if scrape_task is not None:
        scrape_task.cancel()
    if scheduler_task is not None:
        scheduler_task.cancel()
    uptime_task.cancel()
    log.info("Server shutting down")


# ── FASTAPI APP ─────────────────────────────────────────────────────────
app = FastAPI(
    title="Dynasty Trade Calculator",
    lifespan=lifespan,
)
app.add_middleware(GZipMiddleware, minimum_size=1024)

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


@app.post("/api/trade/score")
async def score_trade(request: Request):
    """
    Backend-authoritative trade package scoring endpoint.
    Resolves known assets against contract value bundles and returns package totals.
    """
    contract_payload = latest_contract_data
    if not isinstance(contract_payload, dict):
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": "No contract data available yet."},
        )

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "Invalid JSON request body."},
        )

    if not isinstance(payload, dict):
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "Trade scoring payload must be an object."},
        )

    try:
        result = score_trade_payload(contract_payload=contract_payload, request_payload=payload)
        result["contractVersion"] = API_DATA_CONTRACT_VERSION
        return JSONResponse(content=result)
    except Exception as e:
        log.error("Trade scoring failed: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "Trade scoring failed.", "detail": str(e)},
        )


@app.get("/api/league/public")
async def get_public_league_data():
    """
    Public-safe League API subset.
    Intentionally avoids private valuation/calculator internals.
    """
    source_payload = latest_data or latest_contract_data
    payload = _build_public_league_payload(source_payload)
    headers = {"Cache-Control": "public, max-age=30, stale-while-revalidate=300"}
    if payload.get("ok"):
        return JSONResponse(content=payload, headers=headers)
    return JSONResponse(status_code=503, content=payload, headers=headers)


@app.get("/api/draft-capital")
async def get_draft_capital():
    source_payload = latest_data or load_from_disk()
    payload = _build_draft_capital_payload(source_payload)
    headers = {"Cache-Control": "public, max-age=30, stale-while-revalidate=300"}
    if payload.get("ok"):
        return JSONResponse(content=payload, headers=headers)
    return JSONResponse(status_code=503, content=payload, headers=headers)


@app.get("/api/status")
async def get_status(request: Request):
    """Return scraper status info."""
    status_payload = _scrape_status_payload()
    player_count = int((latest_contract_data or {}).get("playerCount") or 0)
    data_date = (latest_contract_data or {}).get("date")

    # Compact mode is intentionally tiny for high-frequency UI polling.
    if _is_truthy_query_value(request.query_params.get("compact")):
        return JSONResponse(content={
            "running": bool(status_payload.get("running")),
            "is_running": bool(status_payload.get("is_running")),
            "stalled": bool(status_payload.get("stalled")),
            "status_summary": status_payload.get("status_summary"),
            "next_scrape": status_payload.get("next_scrape"),
            "next_scrape_delay_sec": status_payload.get("next_scrape_delay_sec"),
            "consecutive_failures": int(status_payload.get("consecutive_failures", 0) or 0),
            "last_scrape": status_payload.get("last_scrape"),
            "last_error": status_payload.get("last_error"),
            "player_count": player_count,
            "data_date": data_date,
            "has_data": latest_contract_data is not None,
        })

    # Prefer full scrape payload for source-health truth (dlfImport/sourceRunSummary).
    # Contract payload is a compatibility fallback when full payload is unavailable.
    source_health = latest_source_health_snapshot or _build_source_health_snapshot(latest_data or latest_contract_data)
    full_bytes = len(latest_data_bytes) if latest_data_bytes else 0
    runtime_bytes = len(latest_runtime_data_bytes) if latest_runtime_data_bytes else 0
    startup_bytes = len(latest_startup_data_bytes) if latest_startup_data_bytes else 0
    full_gzip_bytes = len(latest_data_gzip_bytes) if latest_data_gzip_bytes else 0
    runtime_gzip_bytes = len(latest_runtime_data_gzip_bytes) if latest_runtime_data_gzip_bytes else 0
    startup_gzip_bytes = len(latest_startup_data_gzip_bytes) if latest_startup_data_gzip_bytes else 0
    authority_payload = _runtime_route_authority_payload()
    frontend_raw_fallback_health = _load_frontend_raw_fallback_health()
    frontend_runtime_payload = {
        **frontend_runtime_status,
        "raw_fallback_health": frontend_raw_fallback_health,
    }
    operator_report = (
        latest_promotion_report.get("operatorReport")
        if isinstance(latest_promotion_report.get("operatorReport"), dict)
        else {}
    )
    deploy_status = _load_deploy_status()
    return JSONResponse(content={
        **status_payload,
        "architecture": _runtime_architecture_truth(),
        "frontend_runtime": frontend_runtime_payload,
        "route_authority": {
            "endpoint": "/api/runtime/route-authority",
            "warnings": authority_payload.get("warnings", []),
        },
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
        "promotion_gate": {
            "state": promotion_gate_state,
            "latest_report": {
                "generatedAt": latest_promotion_report.get("generatedAt"),
                "status": latest_promotion_report.get("status"),
                "summary": latest_promotion_report.get("summary"),
                "operatorReport": operator_report,
            },
        },
        "uptime": uptime_status,
        "automation": {
            "scrape_scheduler": {
                "enabled": bool(SCRAPE_SCHEDULER_ENABLED),
                "base_interval_hours": float(SCRAPE_INTERVAL_HOURS),
                "jitter_minutes": int(SCRAPE_INTERVAL_JITTER_MINUTES),
                "failure_backoff_minutes": int(SCRAPE_FAILURE_BACKOFF_MINUTES),
                "max_backoff_hours": float(SCRAPE_MAX_BACKOFF_HOURS),
                "consecutive_failures": int(status_payload.get("consecutive_failures", 0) or 0),
                "next_delay_seconds": status_payload.get("next_scrape_delay_sec"),
            },
            "health_policy": {
                "max_healthy_scrape_age_hours": float(MAX_HEALTHY_SCRAPE_AGE_HOURS),
            },
            "deploy_status": deploy_status,
        },
        "has_data": latest_contract_data is not None,
        "player_count": player_count,
        "data_date": data_date,
    })


@app.get("/api/validation/promotion-gate")
async def get_promotion_gate_report():
    latest_file = _latest_file(VALIDATION_DIR, PROMOTION_REPORT_GLOB)
    file_payload = _load_json_file(latest_file)
    payload = file_payload if isinstance(file_payload, dict) else latest_promotion_report
    status = str(payload.get("status") or "unknown")
    return JSONResponse(
        status_code=200 if status == "pass" else 503 if status == "fail" else 200,
        content={
            "status": status,
            "state": promotion_gate_state,
            "reportFile": str(latest_file) if latest_file else "",
            "report": payload,
        },
    )


@app.get("/api/validation/operator-report")
async def get_operator_report():
    latest_file = _latest_file(VALIDATION_DIR, PROMOTION_REPORT_GLOB)
    file_payload = _load_json_file(latest_file)
    payload = file_payload if isinstance(file_payload, dict) else latest_promotion_report
    operator_report = payload.get("operatorReport") if isinstance(payload.get("operatorReport"), dict) else {}
    status = str(operator_report.get("status") or "unknown")
    http_status = 503 if status == "critical" else 200
    return JSONResponse(
        status_code=http_status,
        content={
            "status": status,
            "generatedAt": payload.get("generatedAt"),
            "reportFile": str(latest_file) if latest_file else "",
            "operatorReport": operator_report,
        },
    )


@app.get("/api/architecture")
async def get_architecture():
    """Explicit runtime authority truth payload (non-marketing)."""
    return JSONResponse(content=_runtime_architecture_truth())


@app.get("/api/runtime/route-authority")
async def get_runtime_route_authority():
    """Machine-readable route authority map for runtime debugging and deploy audits."""
    return JSONResponse(content=_runtime_route_authority_payload())


@app.get("/api/health")
async def get_health():
    """Basic health endpoint for reverse proxy / uptime probes."""
    status_payload = _scrape_status_payload()
    frontend_raw_fallback_health = _load_frontend_raw_fallback_health()
    last_scrape_age_sec = _seconds_since_iso(status_payload.get("last_scrape"))
    last_scrape_age_hours = (
        round(float(last_scrape_age_sec) / 3600.0, 3)
        if last_scrape_age_sec is not None
        else None
    )
    scrape_age_exceeded = bool(
        last_scrape_age_hours is not None
        and last_scrape_age_hours > float(MAX_HEALTHY_SCRAPE_AGE_HOURS)
    )
    last_success = _parse_iso(promotion_gate_state.get("lastSuccessAt"))
    last_failure = _parse_iso(promotion_gate_state.get("lastFailureAt"))
    promotion_failed = bool(
        promotion_gate_state.get("lastStatus") == "fail"
        and (last_success is None or (last_failure is not None and last_failure >= last_success))
    )
    is_ok = (
        status_payload.get("last_error") in (None, "")
        and not status_payload.get("stalled")
        and bool(contract_health.get("ok", False))
        and not promotion_failed
        and not scrape_age_exceeded
    )
    status = "ok" if is_ok else "degraded"
    health_warnings: list[str] = []
    if int(frontend_raw_fallback_health.get("skipped_file_count") or 0) > 0:
        health_warnings.append("frontend_raw_fallback_skipped_files")
    return JSONResponse(
        status_code=200 if is_ok else 503,
        content={
            "status": status,
            "service": "dynasty-server",
            "time_utc": datetime.now(timezone.utc).isoformat(),
            "has_data": latest_contract_data is not None,
            "last_scrape": status_payload.get("last_scrape"),
            "scrape_running": status_payload.get("is_running"),
            "scrape_stalled": status_payload.get("stalled"),
            "current_step": status_payload.get("current_step"),
            "current_source": status_payload.get("current_source"),
            "contract_version": API_DATA_CONTRACT_VERSION,
            "contract_ok": contract_health.get("ok"),
            "promotion_gate_status": promotion_gate_state.get("lastStatus"),
            "promotion_gate_last_failure": promotion_gate_state.get("lastFailureSummary"),
            "last_scrape_age_hours": last_scrape_age_hours,
            "max_healthy_scrape_age_hours": float(MAX_HEALTHY_SCRAPE_AGE_HOURS),
            "scrape_age_exceeded": scrape_age_exceeded,
            "frontend_runtime": frontend_runtime_status.get("active"),
            "frontend_raw_fallback": {
                "status": frontend_raw_fallback_health.get("status"),
                "selected_source": frontend_raw_fallback_health.get("selected_source"),
                "skipped_file_count": int(frontend_raw_fallback_health.get("skipped_file_count") or 0),
            },
            "warnings": health_warnings,
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


@app.get("/api/scaffold/status")
async def get_scaffold_status():
    """Return latest scaffold snapshot metadata (non-authoritative diagnostics only)."""
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
            "authority": {
                "status": "non_authoritative_scaffold_artifacts",
                "authoritative_runtime_endpoint": "/api/data",
                "note": (
                    "Scaffold snapshots are diagnostics from scripts/*.py and are not "
                    "the live runtime authority for rankings/calculator/player detail."
                ),
            },
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
            "configured": JASON_AUTH_CONFIGURED,
            "authenticated": bool(session),
            "username": session.get("username") if session else None,
        }
    )


@app.post("/api/auth/login")
async def auth_login(request: Request):
    if not JASON_AUTH_CONFIGURED:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": JASON_AUTH_MISSING_PASSWORD_ERROR},
        )

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
    username_match = _is_valid_jason_username(username)

    if not username_match or password != JASON_LOGIN_PASSWORD:
        return JSONResponse(
            status_code=401,
            content={"ok": False, "error": "Invalid username or password."},
        )

    session_id = _create_auth_session(JASON_LOGIN_USERNAME)
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


@app.get("/", response_class=HTMLResponse)
async def serve_landing():
    for path in [LEGACY_STATIC_DIR / "landing.html", STATIC_DIR / "landing.html"]:
        if path.exists():
            return _stamp_route_authority(
                FileResponse(path, media_type="text/html"),
                route_id="/",
                authority="public-static-landing-shell",
            )
    return _stamp_route_authority(
        HTMLResponse(
        "<h1>Landing page missing</h1><p>Expected Static/landing.html.</p>",
        status_code=500,
        ),
        route_id="/",
        authority="public-static-landing-shell-missing",
    )


@app.get("/league", response_class=HTMLResponse)
@app.get("/league/{league_path:path}", response_class=HTMLResponse)
async def serve_league_entry(league_path: str = ""):
    # Public League shell is intentionally served from static assets and does not
    # depend on private Jason auth/session.
    for path in _league_asset_candidates("league/index.html"):
        if path.exists():
            return _stamp_route_authority(
                FileResponse(path, media_type="text/html"),
                route_id="/league",
                authority="public-static-league-shell",
            )

    # Never proxy League routes into Next runtime. This public area remains
    # public/static-owned by FastAPI and must not depend on Next route wiring.
    # If static artifacts are missing, use an explicit inline fallback instead
    # of hard-failing with a raw 500.
    return _stamp_route_authority(
        HTMLResponse(
            _build_league_inline_fallback_html(league_path),
            status_code=200,
            headers={"Cache-Control": "no-store"},
        ),
        route_id="/league",
        authority=LEAGUE_INLINE_FALLBACK_AUTHORITY,
    )


def _require_auth_or_redirect(request: Request, default_next: str = "/app") -> RedirectResponse | None:
    if _is_authenticated(request):
        return None
    return _auth_redirect_response(request, default_next)


async def _serve_app_shell(frontend_path: str, route_id: str) -> Response:
    routed = _resolve_frontend_path(frontend_path)
    if routed is not None:
        if isinstance(routed, Response) and routed.status_code == 503:
            return _stamp_route_authority(
                routed,
                route_id=route_id,
                authority="private-next-proxy-unavailable",
            )
        if FRONTEND_RUNTIME in {"next", "auto"} and frontend_runtime_status.get("active") == "next":
            return _stamp_route_authority(
                routed,
                route_id=route_id,
                authority="private-next-proxy-shell",
            )

    if FRONTEND_RUNTIME == "next":
        fallback = routed if routed is not None else HTMLResponse("Next frontend unavailable", status_code=503)
        return _stamp_route_authority(
            fallback,
            route_id=route_id,
            authority="private-next-proxy-unavailable",
        )

    for path in [STATIC_DIR / "index.html", LEGACY_STATIC_DIR / "index.html", BASE_DIR / "index.html"]:
        if path.exists():
            _set_frontend_runtime_status("static", "serving_static_index")
            return _stamp_route_authority(
                FileResponse(path, media_type="text/html"),
                route_id=route_id,
                authority="private-static-dashboard-shell",
            )
    return _stamp_route_authority(
        HTMLResponse(
        "<h1>Dashboard not found</h1>"
        "<p>Place index.html in the static/ directory or project root.</p>",
        status_code=404,
        ),
        route_id=route_id,
        authority="private-dashboard-shell-missing",
    )


# ── DASHBOARD ROUTES (AUTH REQUIRED) ────────────────────────────────────
@app.get("/app", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    redirect = _require_auth_or_redirect(request, "/app")
    if redirect is not None:
        return redirect
    return await _serve_app_shell("/", "/app")


@app.get("/rankings", response_class=HTMLResponse)
async def serve_rankings(request: Request):
    redirect = _require_auth_or_redirect(request, "/rankings")
    if redirect is not None:
        return redirect
    return await _serve_app_shell("/rankings", "/rankings")


@app.get("/trade", response_class=HTMLResponse)
async def serve_trade(request: Request):
    redirect = _require_auth_or_redirect(request, "/trade")
    if redirect is not None:
        return redirect
    return await _serve_app_shell("/trade", "/trade")


@app.get("/calculator", response_class=HTMLResponse)
async def serve_calculator(request: Request):
    redirect = _require_auth_or_redirect(request, "/calculator")
    if redirect is not None:
        return redirect
    response = RedirectResponse(url="/trade", status_code=302)
    return _stamp_route_authority(
        response,
        route_id="/calculator",
        authority="private-trade-compat-redirect",
    )


@app.get("/login", response_class=HTMLResponse)
async def serve_login(request: Request):
    redirect = _require_auth_or_redirect(request, "/login")
    if redirect is not None:
        return redirect
    return await _serve_app_shell("/login", "/login")


@app.get("/index.html", response_class=HTMLResponse)
async def serve_index_alias(request: Request):
    redirect = _require_auth_or_redirect(request, "/app")
    if redirect is not None:
        return redirect
    return await _serve_app_shell("/", "/index.html")


@app.get("/Static/index.html", response_class=HTMLResponse)
async def serve_legacy_index_alias(request: Request):
    redirect = _require_auth_or_redirect(request, "/app")
    if redirect is not None:
        return redirect
    return await _serve_app_shell("/", "/Static/index.html")


@app.get("/_next/{full_path:path}")
async def serve_next_assets(full_path: str):
    routed = _resolve_frontend_path(f"/_next/{full_path}")
    if routed is not None:
        return routed
    return Response(status_code=404)


@app.get("/favicon.ico")
async def serve_favicon():
    routed = _resolve_frontend_path("/favicon.ico")
    if routed is not None:
        return routed
    return Response(status_code=404)


# Serve any other static files (CSS, JS, images, etc.)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
if LEGACY_STATIC_DIR.exists():
    app.mount("/Static", StaticFiles(directory=str(LEGACY_STATIC_DIR)), name="legacy-static")
if RUNTIME_JS_DIR.exists():
    # Expose extracted runtime modules for root-served index.html (`src="js/runtime/*"`).
    app.mount("/js", StaticFiles(directory=str(RUNTIME_JS_DIR)), name="runtime-js")


# ── MAIN ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    print()
    print("Dynasty Trade Calculator - Server")
    print(f"Dashboard: http://localhost:{PORT}")
    print(
        "Scrape scheduler: "
        f"{'enabled' if SCRAPE_SCHEDULER_ENABLED else 'disabled'} "
        f"(base={SCRAPE_INTERVAL_HOURS:.2f}h, jitter={SCRAPE_INTERVAL_JITTER_MINUTES}m, "
        f"failure_backoff={SCRAPE_FAILURE_BACKOFF_MINUTES}m, max_backoff={SCRAPE_MAX_BACKOFF_HOURS:.2f}h)"
    )
    print(f"Alerts: {'ON -> ' + ALERT_TO[:20] if ALERT_ENABLED else 'OFF'}")
    print()

    uvicorn.run(
        "server:app",
        host=HOST,
        port=PORT,
        log_level="info",
        reload=False,
    )
