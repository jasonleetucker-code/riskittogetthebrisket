#!/usr/bin/env python3
"""Signals collection HEALTH (per family) — the ``health`` mode, read-only.

    python scripts/verify_signals_health.py --app-dir /home/dynasty/trade-calculator

Runs on the production host from the DEPLOYED checkout
(``.github/workflows/signals-health-probe.yml``, ``mode: health``).  All logic
lives in ``src/sources/signals_health.py``; this is a thin CLI.

It reads, never writes, anything but its own private report: no collection is
started, no session is renewed, no flag is toggled.  stdout carries ONLY the
public projection (allowlisted key paths, identifier-shaped leaves); the full
report is written 0600 under ``data/sources/signals/reports/``.  Any failure
prints ``{"error": "<ExceptionClass>"}`` and exits 1 — a traceback could carry
a path or a value, and this log is public.

Exit 0 when the report ran (a failed CHECK is a finding in the JSON).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _private_reports_dir(app_dir: Path) -> Path:
    path = app_dir / "data" / "sources" / "signals" / "reports"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def _write_private(path: Path, obj: object) -> None:
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True, default=str)


def _quiet_failures(private_log: Path | None) -> None:
    """Never let a traceback reach the public log."""
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    if private_log is not None:
        handler = logging.FileHandler(private_log, encoding="utf-8")
        os.chmod(private_log, 0o600)
        root.addHandler(handler)
    else:
        root.addHandler(logging.NullHandler())

    def _hook(exc_type, exc, tb):  # pragma: no cover — exercised via main()
        logging.getLogger("signals-health").error("unhandled", exc_info=(exc_type, exc, tb))
        print(json.dumps({"error": exc_type.__name__}), flush=True)

    sys.excepthook = _hook


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--app-dir", type=Path, default=REPO)
    ap.add_argument("--status-url", default="http://127.0.0.1:8000/api/status")
    args = ap.parse_args(argv)
    app_dir = args.app_dir.resolve()
    utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    try:
        reports = _private_reports_dir(app_dir)
        _quiet_failures(reports / f"health-{utc}.log")
        sys.path.insert(0, str(app_dir))
        from src.sources import signals_health as H  # noqa: PLC0415

        report = H.build_health_report(
            app_dir, status_fetch=lambda: H.local_status(args.status_url)
        )
        _write_private(reports / f"health_{utc}.json", report)
        public = H.public_projection(report)
    except BaseException as exc:  # noqa: BLE001 — class name only, never a message
        logging.getLogger("signals-health").error("failed", exc_info=True)
        print(json.dumps({"error": type(exc).__name__}), flush=True)
        return 1
    print(json.dumps(public, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
