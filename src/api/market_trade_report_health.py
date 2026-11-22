"""Freshness of the Chase Trade Market ledger report, for the ops-alert sweep.

Owner of one question: "is the daily ``dynasty-market-trade-ledger`` job still
producing reports on this host?"  The report (``data/market_trades/reports/
latest.json``, written by ``scripts/market_trade_ledger.py``) is box-local and
gitignored, and some upstream rows exist only in a rolling window, so a silent
stop loses evidence.

The age is read from the report's OWN ``generatedAt``, never from the file
mtime alone (an mtime moves on copies and restores; the stamp is when the
ledger was built).  States, none of which collapses into another:

* ``fresh``            -- stamp readable and within the budget;
* ``stale``            -- stamp readable and older than the budget;
* ``missing``          -- the host IS provisioned (reports dir or the raw KTC
  archive exists) but no report exists: a real failure;
* ``unreadable``       -- a report exists but its stamp cannot be established
  (corrupt JSON, absent/unparseable ``generatedAt``, or a future stamp);
* ``not_provisioned``  -- neither the reports dir nor the archive exists (CI,
  dev, a fresh box): absent by design, never an alert.

The decision is made from files on this host only, never an environment label
(same precedent as ``data_contract.private_source_availability``).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: Staleness budget in hours.  The ledger timer is daily, so a run that is merely
#: a few hours late is ~24-30 h old; 36 h alerts on the first genuinely missed
#: day without paging on timer jitter or a slow build.
MARKET_TRADE_REPORT_STALE_AFTER_HOURS = 36.0

STATE_FRESH = "fresh"
STATE_STALE = "stale"
STATE_MISSING = "missing"
STATE_UNREADABLE = "unreadable"
STATE_NOT_PROVISIONED = "not_provisioned"

LATEST_FILENAME = "latest.json"
_DATED_PREFIX = "market_trade_ledger_"


def market_trades_dir() -> Path:
    """Resolved at CALL time so a test's monkeypatch of ``DEFAULT_DIR`` holds."""
    from src.trade import market_trade_archive as _archive  # noqa: PLC0415

    return Path(_archive.DEFAULT_DIR)


def reports_dir(base: Path | None = None) -> Path:
    return (base if base is not None else market_trades_dir()) / "reports"


def newest_report_path(base: Path | None = None) -> Path | None:
    """``latest.json``, else the newest dated report; ``None`` when neither exists."""
    rdir = reports_dir(base)
    latest = rdir / LATEST_FILENAME
    if latest.is_file():
        return latest
    try:
        dated = sorted(p for p in rdir.glob(f"{_DATED_PREFIX}*.json") if p.is_file())
    except OSError:
        return None
    return dated[-1] if dated else None


def read_report(path: Path) -> dict[str, Any] | None:
    """The parsed report, or ``None`` when it cannot be read as a JSON object."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def parse_generated_at(payload: Any) -> datetime | None:
    """The report's own ``generatedAt`` as an aware UTC datetime, else ``None``."""
    raw = payload.get("generatedAt") if isinstance(payload, dict) else None
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        stamp = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def market_trade_report_health(
    *,
    now: datetime | None = None,
    base: Path | None = None,
    stale_after_hours: float = MARKET_TRADE_REPORT_STALE_AFTER_HOURS,
) -> dict[str, Any]:
    """The report's freshness row.  Never raises; ``ageHours`` is ``None``
    unless a stamp was readable."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    row: dict[str, Any] = {
        "state": STATE_UNREADABLE,
        "ageHours": None,
        "staleAfterHours": float(stale_after_hours),
        "generatedAt": None,
    }
    try:
        root = base if base is not None else market_trades_dir()
        path = newest_report_path(root)
        if path is None:
            provisioned = reports_dir(root).is_dir() or (root / "archive.sqlite").is_file()
            row["state"] = STATE_MISSING if provisioned else STATE_NOT_PROVISIONED
            return row
        stamp = parse_generated_at(read_report(path))
        if stamp is None:
            return row
        age = (now - stamp).total_seconds() / 3600.0
        if age < -1.0:
            # A stamp from the future is a clock fault, not a fresh report.
            return row
        row["generatedAt"] = stamp.isoformat()
        row["ageHours"] = round(max(age, 0.0), 2)
        row["state"] = STATE_STALE if age > stale_after_hours else STATE_FRESH
    except Exception:  # noqa: BLE001 -- a monitoring probe must never raise
        row.update(state=STATE_UNREADABLE, ageHours=None, generatedAt=None)
    return row
