"""Startup validation checks.

Run during app lifespan to verify:
  * required env vars are set
  * required directories exist + are writable
  * SQLite files are reachable
  * league registry loads

Each check returns a ``CheckResult``.  The overall startup summary
logs every check with status.  **No check raises** — a check
failing logs a structured warning/error and the app continues
booting (degraded mode).  Fatal conditions are separately signalled
via ``CheckResult.fatal = True`` so the caller can decide to exit.

The goal is "observable degraded startup" over "silent
misconfiguration".  A broken .env file produces 15 explicit log
lines telling you what's wrong, not a mysterious 503.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

_LOGGER = logging.getLogger(__name__)


@dataclass
class CheckResult:
    name: str
    ok: bool
    message: str
    fatal: bool = False  # Non-recoverable — caller should stop.
    context: dict[str, Any] | None = None


def check_env_var(name: str, *, required: bool = True) -> CheckResult:
    val = os.getenv(name)
    if val:
        return CheckResult(name=f"env:{name}", ok=True, message="set", fatal=False)
    return CheckResult(
        name=f"env:{name}",
        ok=not required,
        message="missing" if required else "missing (optional)",
        fatal=required,
    )


def check_dir_writable(path: Path, *, create: bool = True) -> CheckResult:
    try:
        if create:
            path.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            return CheckResult(
                name=f"dir:{path}", ok=False, message="missing",
                fatal=False,
            )
        # Try to write a probe.
        probe = path / ".writable_probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return CheckResult(
            name=f"dir:{path}", ok=True, message="writable",
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name=f"dir:{path}", ok=False,
            message=f"not writable: {exc}",
            fatal=False,
            context={"error": str(exc)},
        )


def check_sqlite_reachable(path: Path) -> CheckResult:
    """Open + integrity_check a SQLite file.  Creating the file if
    missing (normal SQLite behavior) is allowed — we just want to
    know the path is usable."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=2.0)
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            if row and row[0] == "ok":
                return CheckResult(
                    name=f"sqlite:{path.name}", ok=True, message="ok",
                )
            return CheckResult(
                name=f"sqlite:{path.name}", ok=False,
                message=f"integrity_check: {row}",
                fatal=False,
            )
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name=f"sqlite:{path.name}", ok=False,
            message=f"open failed: {exc}",
            fatal=False,
            context={"error": str(exc)},
        )


def check_league_registry() -> CheckResult:
    """Verify the league registry loads and has at least one
    active league."""
    try:
        from src.api import league_registry
        leagues = league_registry.active_leagues()
        if not leagues:
            return CheckResult(
                name="league_registry", ok=False,
                message="no active leagues configured",
                fatal=False,
            )
        return CheckResult(
            name="league_registry", ok=True,
            message=f"{len(leagues)} active",
            context={"keys": [lg.key for lg in leagues]},
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="league_registry", ok=False,
            message=f"load failed: {exc}",
            fatal=True,
            context={"error": str(exc)},
        )


def run_all(
    *,
    extra_checks: list[Callable[[], CheckResult]] | None = None,
    data_dir: Path | None = None,
) -> list[CheckResult]:
    """Run all startup checks and return the list.  Logs each
    result.  Never raises."""
    repo_root = Path(__file__).resolve().parents[2]
    data_dir = data_dir or (repo_root / "data")

    checks: list[CheckResult] = []
    # Directories.
    checks.append(check_dir_writable(data_dir))
    checks.append(check_dir_writable(data_dir / "nfl_data_cache"))
    # SQLite files.
    checks.append(check_sqlite_reachable(data_dir / "user_kv.sqlite"))
    checks.append(check_sqlite_reachable(data_dir / "session_store.sqlite"))
    # Registry.
    checks.append(check_league_registry())
    # Env vars (soft — app has safe defaults for most).
    checks.append(check_env_var("PRIVATE_APP_ALLOWED_USERNAMES", required=False))
    checks.append(check_env_var("SLEEPER_LEAGUE_ID", required=False))

    if extra_checks:
        for cf in extra_checks:
            try:
                checks.append(cf())
            except Exception as exc:  # noqa: BLE001
                checks.append(CheckResult(
                    name=f"extra:{cf.__name__}", ok=False,
                    message=f"check raised: {exc}",
                    fatal=False,
                ))

    # Log every check.
    for r in checks:
        level = logging.INFO if r.ok else (
            logging.ERROR if r.fatal else logging.WARNING
        )
        _LOGGER.log(
            level,
            "startup_check=%s ok=%s message=%r%s",
            r.name, r.ok, r.message,
            f" context={r.context}" if r.context else "",
        )

    n_failures = sum(1 for r in checks if not r.ok)
    n_fatal = sum(1 for r in checks if r.fatal)
    if n_fatal:
        _LOGGER.error(
            "startup_summary=degraded failures=%d fatal=%d total=%d",
            n_failures, n_fatal, len(checks),
        )
    elif n_failures:
        _LOGGER.warning(
            "startup_summary=degraded failures=%d total=%d",
            n_failures, len(checks),
        )
    else:
        _LOGGER.info("startup_summary=healthy checks=%d", len(checks))

    return checks


def summary(checks: list[CheckResult]) -> dict[str, Any]:
    """Convert check list to a dict for /api/status / /api/health."""
    return {
        "total": len(checks),
        "ok": sum(1 for r in checks if r.ok),
        "failed": sum(1 for r in checks if not r.ok),
        "fatal": sum(1 for r in checks if r.fatal),
        "checks": [
            {
                "name": r.name, "ok": r.ok, "message": r.message,
                "fatal": r.fatal, "context": r.context or {},
            }
            for r in checks
        ],
    }
