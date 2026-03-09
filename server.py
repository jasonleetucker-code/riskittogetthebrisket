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
import time
import logging
import traceback
import smtplib
import urllib.request
import urllib.error
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles

# ── CONFIG ──────────────────────────────────────────────────────────────
SCRAPE_INTERVAL_HOURS = 2
PORT = 8000
HOST = "0.0.0.0"  # accessible from local network; use "127.0.0.1" for local only

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
ENABLE_NEXT_FRONTEND_PROXY = _env_bool("ENABLE_NEXT_FRONTEND_PROXY", True)

ALERT_ENABLED = _env_bool("ALERT_ENABLED", False)
ALERT_TO = os.getenv("ALERT_TO", "")
ALERT_FROM = os.getenv("ALERT_FROM", "")
ALERT_PASSWORD = os.getenv("ALERT_PASSWORD") or os.getenv("GMAIL_APP_PASSWORD", "")

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
LEGACY_STATIC_DIR = BASE_DIR / "Static"
SCRAPER_PATH = BASE_DIR / "Dynasty Scraper.py"

DATA_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

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
scrape_status = {
    "last_scrape": None,      # ISO timestamp
    "last_duration_sec": None,
    "next_scrape": None,       # ISO timestamp
    "is_running": False,
    "last_error": None,
    "scrape_count": 0,
}


# ── SCRAPER INTEGRATION ────────────────────────────────────────────────
def load_from_disk() -> dict | None:
    """Load most recent dynasty_data_*.json from data/ directory."""
    json_files = sorted(DATA_DIR.glob("dynasty_data_*.json"), reverse=True)
    if not json_files:
        # Also check base dir for existing files from standalone scraper runs
        json_files = sorted(BASE_DIR.glob("dynasty_data_*.json"), reverse=True)
    if json_files:
        try:
            with open(json_files[0]) as f:
                data = json.load(f)
            log.info(f"Loaded cached data from {json_files[0].name} "
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


async def run_scraper() -> dict | None:
    """
    Import and run the scraper, returning the dashboard JSON dict.
    Runs in the same event loop as the server.
    """
    global latest_data, scrape_status

    if scrape_status["is_running"]:
        log.warning("Scrape already in progress, skipping")
        return latest_data

    scrape_status["is_running"] = True
    scrape_status["last_error"] = None
    start = time.time()
    log.info("=" * 60)
    log.info("SCRAPE STARTING")
    log.info("=" * 60)

    try:
        # Import the scraper module from its exact file path
        # (importlib handles spaces in directory names that normal import can't)
        import importlib.util
        spec = importlib.util.spec_from_file_location("Dynasty_Scraper", str(SCRAPER_PATH))
        scraper = importlib.util.module_from_spec(spec)
        sys.modules["Dynasty_Scraper"] = scraper
        spec.loader.exec_module(scraper)

        # Override SCRIPT_DIR so output goes to our data/ folder
        scraper.SCRIPT_DIR = str(DATA_DIR)

        # Run the scraper's main async function
        result = await scraper.run()

        if result and result.get("players"):
            latest_data = result
            elapsed = time.time() - start
            player_count = len(result.get("players", {}))
            site_count = len([s for s in result.get("sites", [])
                              if s.get("playerCount", 0) > 0])
            total_sites = len(result.get("sites", []))

            scrape_status.update({
                "last_scrape": datetime.now(timezone.utc).isoformat(),
                "last_duration_sec": round(elapsed, 1),
                "is_running": False,
                "scrape_count": scrape_status["scrape_count"] + 1,
            })

            log.info(f"SCRAPE COMPLETE — {player_count} players, "
                     f"{site_count}/{total_sites} sites, {elapsed:.1f}s")

            # Alert if fewer than half the sites returned data
            if total_sites > 0 and site_count < total_sites / 2:
                send_alert(
                    f"Scrape partial: only {site_count}/{total_sites} sites",
                    f"Players: {player_count}\nSites with data: {site_count}/{total_sites}\nDuration: {elapsed:.1f}s\n\nSome sites may be down or blocking the scraper."
                )

            return result
        else:
            raise RuntimeError("Scraper returned empty result")

    except Exception as e:
        elapsed = time.time() - start
        scrape_status["is_running"] = False
        scrape_status["last_error"] = f"{type(e).__name__}: {str(e)[:200]}"
        log.error(f"SCRAPE FAILED after {elapsed:.1f}s: {e}")
        error_trace = traceback.format_exc()
        log.error(error_trace)
        send_alert(
            f"Scrape failed: {type(e).__name__}",
            f"Error: {e}\n\nDuration: {elapsed:.1f}s\n\n{error_trace[-1500:]}"
        )
        return None


# ── SCHEDULER ───────────────────────────────────────────────────────────
async def scheduled_scrape():
    """Called by the background scheduler every SCRAPE_INTERVAL_HOURS."""
    log.info(f"Scheduled scrape triggered (every {SCRAPE_INTERVAL_HOURS}h)")
    await run_scraper()
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

    # 1. Load cached data immediately so the dashboard is usable right away
    latest_data = load_from_disk()
    if latest_data:
        log.info("Dashboard ready with cached data")
    else:
        log.info("No cached data found — dashboard will show empty until first scrape completes")

    # 2. Start first scrape in background (don't block startup)
    async def initial_scrape():
        await asyncio.sleep(3)  # small delay to let server finish booting
        await run_scraper()

    scrape_task = asyncio.create_task(initial_scrape())

    # 3. Start the recurring schedule
    scheduler_task = asyncio.create_task(schedule_loop())

    log.info(f"Server started — scraping every {SCRAPE_INTERVAL_HOURS}h")
    log.info(f"Dashboard: http://localhost:{PORT}")

    yield  # app is running

    # Cleanup
    scrape_task.cancel()
    scheduler_task.cancel()
    log.info("Server shutting down")


# ── FASTAPI APP ─────────────────────────────────────────────────────────
app = FastAPI(
    title="Dynasty Trade Calculator",
    lifespan=lifespan,
)

def _proxy_next(path: str) -> Response | None:
    """
    Proxy frontend routes to local Next.js dev/prod server when available.
    Returns None if proxy disabled/unavailable so legacy static fallback can handle it.
    """
    if not ENABLE_NEXT_FRONTEND_PROXY:
        return None
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
            return Response(content=body, status_code=getattr(resp, "status", 200), headers=headers)
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = b""
        headers = {}
        ctype = e.headers.get("Content-Type") if e.headers else None
        if ctype:
            headers["content-type"] = ctype
        return Response(content=body, status_code=e.code, headers=headers)
    except Exception:
        return None


# ── API ROUTES ──────────────────────────────────────────────────────────
@app.get("/api/data")
async def get_data():
    """Return latest scrape data as JSON."""
    if latest_data:
        return JSONResponse(content=latest_data)
    return JSONResponse(
        status_code=503,
        content={"error": "No data available yet. First scrape may still be running."}
    )


@app.get("/api/status")
async def get_status():
    """Return scraper status info."""
    return JSONResponse(content={
        **scrape_status,
        "has_data": latest_data is not None,
        "player_count": len(latest_data.get("players", {})) if latest_data else 0,
        "data_date": latest_data.get("date") if latest_data else None,
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
    if scrape_status["is_running"]:
        return JSONResponse(
            status_code=409,
            content={"error": "Scrape already in progress",
                     "status": scrape_status}
        )

    # Run in background so the API returns immediately
    background_tasks.add_task(run_scraper)
    return JSONResponse(content={
        "message": "Scrape started in background",
        "status": scrape_status,
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


# ── DASHBOARD ROUTES ────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve the main dashboard HTML."""
    proxied = _proxy_next("/")
    if proxied is not None:
        return proxied

    # Look for index.html in static/ first, then base dir
    for path in [STATIC_DIR / "index.html", LEGACY_STATIC_DIR / "index.html", BASE_DIR / "index.html"]:
        if path.exists():
            return FileResponse(path, media_type="text/html")
    return HTMLResponse(
        "<h1>Dashboard not found</h1>"
        "<p>Place index.html in the static/ directory or project root.</p>",
        status_code=404,
    )

@app.get("/rankings", response_class=HTMLResponse)
async def serve_rankings():
    proxied = _proxy_next("/rankings")
    if proxied is not None:
        return proxied
    return await serve_dashboard()

@app.get("/trade", response_class=HTMLResponse)
async def serve_trade():
    proxied = _proxy_next("/trade")
    if proxied is not None:
        return proxied
    return await serve_dashboard()

@app.get("/_next/{full_path:path}")
async def serve_next_assets(full_path: str):
    proxied = _proxy_next(f"/_next/{full_path}")
    if proxied is not None:
        return proxied
    return Response(status_code=404)

@app.get("/favicon.ico")
async def serve_favicon():
    proxied = _proxy_next("/favicon.ico")
    if proxied is not None:
        return proxied
    return Response(status_code=404)


# Serve any other static files (CSS, JS, images, etc.)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
if LEGACY_STATIC_DIR.exists():
    app.mount("/Static", StaticFiles(directory=str(LEGACY_STATIC_DIR)), name="legacy-static")


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
