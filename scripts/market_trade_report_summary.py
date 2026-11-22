#!/usr/bin/env python3
"""Aggregate-only summary of the latest Chase Trade Market ledger report.

Run on the box by ``.github/workflows/market-trade-ledger-report.yml`` (read-only,
``workflow_dispatch``).  The workflow's log and step summary are PUBLIC, so this
prints a fixed WHITELIST of aggregate counts, dates and the report age -- nothing
else.  Unknown report fields are dropped, never passed through: no league ids,
user ids, usernames, player names, trade details or file paths.

Inputs, both read-only:

* ``data/market_trades/reports/latest.json`` (via ``src/api/market_trade_report_health``
  so the freshness rule is the alert's rule, not a second one);
* ``data/market_trades/archive.sqlite``, opened ``mode=ro``: counts and min/max
  dates only.

Exit codes: 0 summary printed; 2 no report could be read (missing / unreadable /
not provisioned -- stated, never silently empty); 3 the summary itself failed
(only the exception class is printed).  Stale is reported, exit 0.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.api import market_trade_report_health as health  # noqa: E402

_ARCHIVE_FILENAME = "archive.sqlite"

# A map label must look like an enum value (source family, disposition, cohort):
# it starts with a letter.  Sleeper / KTC league and user ids are numeric, so a
# future report keyed by an id is dropped here instead of reaching a public log.
_LABEL_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.:+-]{0,47}")


def _label(raw: Any) -> str | None:
    text = str(raw)
    return text if _LABEL_RE.fullmatch(text) else None


def _count_map(raw: Any) -> dict[str, int]:
    """``{label: int}`` -- labels are bounded enum-like strings; non-int values dropped."""
    out: dict[str, int] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            label = _label(k)
            if label is not None and isinstance(v, int) and not isinstance(v, bool):
                out[label] = v
    return dict(sorted(out.items()))


def _int(raw: Any) -> int | None:
    return raw if isinstance(raw, int) and not isinstance(raw, bool) else None


def _date(raw: Any) -> str | None:
    """A ``YYYY-MM-DD`` prefix only; anything else is dropped."""
    if isinstance(raw, str) and len(raw) >= 10:
        try:
            datetime.fromisoformat(raw[:10])
        except ValueError:
            return None
        return raw[:10]
    return None


def _date_coverage(raw: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if isinstance(raw, dict):
        for src, rng in raw.items():
            label = _label(src)
            if label is not None and isinstance(rng, dict):
                out[label] = {
                    "oldest": _date(rng.get("oldest")),
                    "newest": _date(rng.get("newest")),
                    "dated": _int(rng.get("dated")),
                }
    return dict(sorted(out.items()))


def _nested_counts(raw: Any) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            label = _label(k)
            if label is not None:
                out[label] = _count_map(v)
    return dict(sorted(out.items()))


def whitelist_report(report: Any) -> dict[str, Any]:
    """The aggregate whitelist of one ledger report.  Pure; unknown keys dropped."""
    report = report if isinstance(report, dict) else {}
    cov = report.get("coverage") if isinstance(report.get("coverage"), dict) else {}
    ev = report.get("evaluation") if isinstance(report.get("evaluation"), dict) else {}
    raw_obs = cov.get("rawSourceObservations")
    raw_obs = raw_obs if isinstance(raw_obs, dict) else {}
    estimator = ev.get("estimatorEvidence")
    estimator = estimator if isinstance(estimator, dict) else {}
    topology = ev.get("topology") if isinstance(ev.get("topology"), dict) else {}
    fmt = cov.get("formatCoverage") if isinstance(cov.get("formatCoverage"), dict) else {}
    return {
        "observations": _int(raw_obs.get("total")),
        "observationsBySource": _count_map(raw_obs.get("bySource")),
        "groups": _int(cov.get("underlyingTrades")),
        "confirmedUniqueGroups": _int(cov.get("confirmedUniqueUnderlyingTrades")),
        "probableDuplicateGroups": _int(cov.get("probableDuplicateGroups")),
        "possibleOverlapGroups": _int(cov.get("possibleOverlapGroups")),
        "unresolvedGroups": _int(cov.get("unresolvedGroups")),
        "nativeComparableTrades": _int(cov.get("nativeComparableTrades")),
        "dispositions": _count_map(cov.get("dispositions")),
        "dateCoverage": _date_coverage(cov.get("dateCoverage")),
        "formatCoverage": {
            "byFormatSource": _count_map(fmt.get("byFormatSource")),
            "groupsWithScoringCard": _int(fmt.get("groupsWithScoringCard")),
        },
        "topologyByFitSuitability": _count_map(topology.get("byFitSuitability")),
        "estimatorEvidence": {
            "representable": _int(estimator.get("representable")),
            "anyHardExclusion": _int(estimator.get("anyHardExclusion")),
            "maturityCohortsAmongRepresentable": _nested_counts(
                estimator.get("maturityCohortsAmongRepresentable")
            ),
        },
    }


def archive_stats(path: Path) -> dict[str, Any]:
    """Counts and min/max dates from the raw KTC archive, opened read-only."""
    if not path.is_file():
        return {"state": "absent"}
    try:
        uri = f"file:{path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    except sqlite3.Error:
        return {"state": "unreadable"}
    try:
        conn.execute("PRAGMA query_only = ON")

        def one(sql: str) -> tuple[Any, ...]:
            return conn.execute(sql).fetchone()

        obs = one("SELECT COUNT(*), MIN(observed_date), MAX(observed_date) FROM raw_observations")
        fetches = one("SELECT COUNT(*), MIN(fetched_at), MAX(fetched_at) FROM fetches")
        by_outcome = dict(conn.execute("SELECT outcome, COUNT(*) FROM fetches GROUP BY outcome"))
        by_family = dict(
            conn.execute("SELECT source_family, COUNT(*) FROM raw_observations GROUP BY 1")
        )
        return {
            "state": "ok",
            "observations": _int(obs[0]),
            "observedDateOldest": _date(obs[1]),
            "observedDateNewest": _date(obs[2]),
            "observationsBySource": _count_map(by_family),
            "fetches": _int(fetches[0]),
            "firstFetchDate": _date(fetches[1]),
            "lastFetchDate": _date(fetches[2]),
            "fetchesByOutcome": _count_map(by_outcome),
        }
    except sqlite3.Error:
        return {"state": "unreadable"}
    finally:
        conn.close()


def build_summary(*, base: Path | None = None, now: datetime | None = None) -> dict[str, Any]:
    """The full public-safe summary.  Never raises."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    root = base if base is not None else health.market_trades_dir()
    freshness = health.market_trade_report_health(now=now, base=root)
    summary: dict[str, Any] = {
        "asOf": now.isoformat(),
        "reportState": freshness["state"],
        "reportGeneratedAt": freshness["generatedAt"],
        "reportAgeHours": freshness["ageHours"],
        "staleAfterHours": freshness["staleAfterHours"],
        "report": None,
        "ktcArchive": archive_stats(root / _ARCHIVE_FILENAME),
    }
    if freshness["state"] in (health.STATE_FRESH, health.STATE_STALE):
        path = health.newest_report_path(root)
        payload = health.read_report(path) if path is not None else None
        summary["report"] = whitelist_report(payload)
    return summary


def render_markdown(summary: dict[str, Any]) -> str:
    """Step-summary text: a fenced JSON of the already-whitelisted aggregates."""
    head = (
        f"### Chase Trade Market ledger report\n\n"
        f"- report state: **{summary['reportState']}**\n"
        f"- generated: {summary['reportGeneratedAt']}\n"
        f"- age (h): {summary['reportAgeHours']} (budget {summary['staleAfterHours']})\n\n"
    )
    return head + "```json\n" + json.dumps(summary, indent=1, sort_keys=True) + "\n```\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=None, help="market_trades dir (tests)")
    parser.add_argument("--markdown", action="store_true", help="emit step-summary markdown")
    args = parser.parse_args(argv)
    try:
        summary = build_summary(base=args.dir)
    except Exception as exc:  # noqa: BLE001 -- the log is public: class name only
        print(f"summary failed: {type(exc).__name__}")
        return 3
    print(render_markdown(summary) if args.markdown else json.dumps(summary, indent=1))
    ok = summary["reportState"] in (health.STATE_FRESH, health.STATE_STALE)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
