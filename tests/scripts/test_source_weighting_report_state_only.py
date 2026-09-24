"""``source_weighting_report.py --state-only`` — the production evidence print.

It runs on the box after every deploy (``deploy/verify-deploy.sh``) because the
weighting endpoints are auth-gated.  Pinned here:

* a stale source's effective weight is reduced, a fresh one's is not;
* a re-fetch stamp newer than the data does NOT make the data look fresh —
  last FETCH and DATA AS OF are reported side by side;
* KTC Market is reported as a benchmark with no effective weight;
* the deploy hook is advisory: it can never fail the deploy.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import source_weighting_report as report
from src.sources.ktc_market import KTC_CROWD_KEY, KTC_MARKET_KEY

REPO = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)


def _state(days_ago: float) -> dict:
    at = NOW - timedelta(days=days_ago)
    events = [
        {
            "at": (at - timedelta(hours=12 * k)).isoformat(),
            "broad": True,
            "rowsChanged": 90,
            "rowsTotal": 100,
        }
        for k in range(6, -1, -1)
    ]
    iso = at.isoformat()
    return {
        "subsets": {
            "players": {
                "changeHistory": events,
                "lastAnyMeaningfulChangeAt": iso,
                "lastBroadDatasetChangeAt": iso,
                "rowCount": 100,
                "rowCountHistory": [100],
            }
        },
        "health": {"state": "HEALTHY", "errors": []},
        "upstream": {},
    }


def _write(state_dir: Path, key: str, state: dict) -> None:
    (state_dir / f"{key}_dataset.json").write_text(json.dumps(state), encoding="utf-8")


def _rows(tmp_path: Path) -> dict[tuple[str, str], dict]:
    _write(tmp_path, KTC_CROWD_KEY, _state(0.1))  # fresh
    _write(tmp_path, "fantasyCalc", _state(10))  # KTC-like cadence, 10 days dark
    _write(tmp_path, KTC_MARKET_KEY, _state(0.1))
    # Fetched a minute ago — the content is still ten days old.
    (tmp_path / "fantasyCalc_last_success").write_text(str((NOW).timestamp()))
    rows = report.state_only_rows(tmp_path, NOW)
    return {(r["source"], r["subset"]): r for r in rows}


def test_fresh_source_keeps_full_weight(tmp_path):
    row = _rows(tmp_path)[(KTC_CROWD_KEY, "players")]
    assert row["role"] == "model_input"
    assert row["effectiveWeight"] == 1.0


def test_stale_source_is_reduced_and_a_refetch_does_not_freshen_it(tmp_path):
    row = _rows(tmp_path)[("fantasyCalc", "players")]
    assert row["effectiveWeight"] is not None and row["effectiveWeight"] < 0.05
    assert row["lastFetchedAt"] == "2026-09-23T18:00:00Z"
    assert row["sourceDataAsOf"].startswith("2026-09-13")


def test_ktc_market_is_a_benchmark_without_a_weight(tmp_path):
    row = _rows(tmp_path)[(KTC_MARKET_KEY, "players")]
    assert row["role"] == "benchmark"
    assert row["effectiveWeight"] is None


def test_unmeasured_source_is_reported_not_zeroed(tmp_path):
    rows = _rows(tmp_path)
    missing = [r for (k, _), r in rows.items() if k == "yahooBoone"]
    assert missing and missing[0]["measured"] is False
    assert missing[0]["effectiveWeight"] is None


def test_the_deploy_hook_is_advisory():
    text = (REPO / "deploy" / "verify-deploy.sh").read_text(encoding="utf-8")
    start = text.index("Source weighting report — ADVISORY")
    block = text[start : text.index('log "Deploy verification checks passed."', start)]
    assert "source_weighting_report.py --state-only" in block
    assert re.search(r"else\s+warn ", block), "a failure must only warn"
    assert "exit 1" not in block and "error " not in block
