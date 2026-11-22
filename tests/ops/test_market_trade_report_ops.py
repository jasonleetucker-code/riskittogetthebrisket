"""DYN10-3 A1b (stale-report alert) + A3 (aggregate summary whitelist)."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from src.api import market_trade_report_health as health
from src.api import ops_alerts

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import market_trade_report_summary as summ  # noqa: E402

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)


def _write_report(base: Path, generated, **extra) -> None:
    rdir = base / "reports"
    rdir.mkdir(parents=True, exist_ok=True)
    body = dict(extra)
    if generated is not None:
        body["generatedAt"] = generated
    (rdir / "latest.json").write_text(json.dumps(body), encoding="utf-8")


def _row(base):
    return health.market_trade_report_health(now=NOW, base=base)


def test_fresh(tmp_path):
    _write_report(tmp_path, (NOW - timedelta(hours=5)).isoformat())
    row = _row(tmp_path)
    assert row["state"] == "fresh" and row["ageHours"] == 5.0
    assert ops_alerts._check_market_trade_report(row) == []


def test_stale_uses_generated_at_not_mtime(tmp_path):
    _write_report(tmp_path, (NOW - timedelta(hours=60)).isoformat())  # mtime is "now"
    row = _row(tmp_path)
    assert row["state"] == "stale"
    (alert,) = ops_alerts._check_market_trade_report(row)
    assert alert.category == ops_alerts.MARKET_TRADE_REPORT_CATEGORY
    assert "60 h" in alert.title


def test_budget_is_named_constant():
    assert health.MARKET_TRADE_REPORT_STALE_AFTER_HOURS == 36.0


def test_missing_on_provisioned_host(tmp_path):
    (tmp_path / "reports").mkdir()
    row = _row(tmp_path)
    assert row["state"] == "missing"
    assert len(ops_alerts._check_market_trade_report(row)) == 1


def test_missing_when_only_archive_exists(tmp_path):
    (tmp_path / "archive.sqlite").write_bytes(b"")
    assert _row(tmp_path)["state"] == "missing"


@pytest.mark.parametrize(
    "generated", [None, "not-a-date", "", (NOW + timedelta(days=3)).isoformat()]
)
def test_unreadable_timestamp(tmp_path, generated):
    _write_report(tmp_path, generated)
    row = _row(tmp_path)
    assert row["state"] == "unreadable" and row["ageHours"] is None
    assert len(ops_alerts._check_market_trade_report(row)) == 1


def test_corrupt_json_is_unreadable(tmp_path):
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "latest.json").write_text("{nope", encoding="utf-8")
    assert _row(tmp_path)["state"] == "unreadable"


def test_not_provisioned_never_alerts(tmp_path):
    row = _row(tmp_path / "nothing_here")
    assert row["state"] == "not_provisioned"
    assert ops_alerts._check_market_trade_report(row) == []


def test_not_checked_is_no_alert():
    assert ops_alerts._check_market_trade_report(None) == []


def _sweep(kv, row, sent):
    return ops_alerts.check_and_alert(
        market_trade_report=row,
        delivery=lambda to, s, b: (sent.append(s), True)[1],
        to_email="o@example.com",
        kv_path=kv,
    )


def test_sweep_dedup_recovery_and_not_checked(tmp_path):
    kv, sent = tmp_path / "kv.json", []
    stale = {"state": "stale", "ageHours": 50.0, "staleAfterHours": 36.0, "generatedAt": "x"}
    fresh = {"state": "fresh", "ageHours": 1.0, "staleAfterHours": 36.0, "generatedAt": "x"}
    assert _sweep(kv, stale, sent)["categories"] == [ops_alerts.MARKET_TRADE_REPORT_CATEGORY]
    assert _sweep(kv, stale, sent)["fired"] == 0  # cooldown
    assert _sweep(kv, None, sent)["recovered"] == 0  # unknown is not recovered
    assert _sweep(kv, fresh, sent)["recovered"] == 1
    assert len(sent) == 2


# ── A3 ──────────────────────────────────────────────────────────────────


def test_whitelist_drops_unknown_and_private_fields():
    report = {
        "generatedAt": "2026-11-22T00:00:00+00:00",
        "reportPath": "/secret/path",
        "canonicalLedger": "/secret/ledger",
        "coverage": {
            "rawSourceObservations": {"total": 7, "bySource": {"ktc": 4, "sleeper": 3}},
            "underlyingTrades": 5,
            "dispositions": {"NATIVE_COMPARABLE": 2, "bad": "x"},
            "dateCoverage": {"ktc": {"oldest": "2026-01-02T03", "newest": "junk", "dated": 4}},
            "targetLeague": "dynasty_main",
            "sampleTrades": [{"player": "Some Name", "leagueId": "123"}],
            "identity": {"x": {"user": "bob"}},
        },
        "evaluation": {
            "estimatorEvidence": {
                "representable": 3,
                "maturityCohortsAmongRepresentable": {"pointInTime": {"A": 1}},
                "leak": "player",
            }
        },
    }
    out = summ.whitelist_report(report)
    blob = json.dumps(out)
    for forbidden in ("secret", "Some Name", "123", "bob", "dynasty_main", "targetLeague"):
        assert forbidden not in blob
    assert out["observations"] == 7 and out["groups"] == 5
    assert out["dispositions"] == {"NATIVE_COMPARABLE": 2}
    assert out["dateCoverage"]["ktc"] == {"oldest": "2026-01-02", "newest": None, "dated": 4}
    assert out["estimatorEvidence"]["maturityCohortsAmongRepresentable"] == {
        "pointInTime": {"A": 1}
    }


def test_whitelist_of_garbage_is_all_unknown():
    out = summ.whitelist_report("nonsense")
    assert out["observations"] is None and out["dispositions"] == {}


def _make_archive(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE fetches (fetch_id TEXT, fetched_at TEXT, outcome TEXT);"
        "CREATE TABLE raw_observations (source_family TEXT, observed_date TEXT);"
        "INSERT INTO fetches VALUES ('a','2026-11-01T00:00:00','ok'),"
        "('b','2026-11-02T00:00:00','ok');"
        "INSERT INTO raw_observations VALUES ('ktc','2026-10-30'),('ktc','2026-11-01');"
    )
    conn.commit()
    conn.close()


def test_archive_stats_read_only_counts(tmp_path):
    db = tmp_path / "archive.sqlite"
    _make_archive(db)
    before = db.read_bytes()
    stats = summ.archive_stats(db)
    assert stats["observations"] == 2 and stats["observedDateNewest"] == "2026-11-01"
    assert stats["fetchesByOutcome"] == {"ok": 2}
    assert db.read_bytes() == before
    assert summ.archive_stats(tmp_path / "none.sqlite") == {"state": "absent"}


def test_summary_fresh_stale_missing(tmp_path):
    _write_report(
        tmp_path, (NOW - timedelta(hours=2)).isoformat(), coverage={"underlyingTrades": 9}
    )
    s = summ.build_summary(base=tmp_path, now=NOW)
    assert s["reportState"] == "fresh" and s["report"]["groups"] == 9
    _write_report(tmp_path, (NOW - timedelta(hours=99)).isoformat())
    assert summ.build_summary(base=tmp_path, now=NOW)["reportState"] == "stale"
    empty = tmp_path / "e"
    (empty / "reports").mkdir(parents=True)
    s = summ.build_summary(base=empty, now=NOW)
    assert s["reportState"] == "missing" and s["report"] is None


def test_cli_exit_codes(tmp_path):
    cmd = [sys.executable, str(REPO / "scripts" / "market_trade_report_summary.py"), "--dir"]
    assert subprocess.run([*cmd, str(tmp_path / "x")], capture_output=True).returncode == 2
    _write_report(tmp_path, datetime.now(timezone.utc).isoformat())
    assert subprocess.run([*cmd, str(tmp_path)], capture_output=True).returncode == 0


def test_workflow_shape():
    wf = yaml.safe_load(
        (REPO / ".github/workflows/market-trade-ledger-report.yml").read_text(encoding="utf-8")
    )
    assert list(wf[True]) == ["workflow_dispatch"]  # dispatch only, no schedule
    assert wf["permissions"] == {"contents": "read"}
    assert wf["concurrency"]["group"] != "production-deploy"
