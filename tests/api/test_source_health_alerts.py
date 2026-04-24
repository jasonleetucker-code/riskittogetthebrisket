"""Tests for the source-health staleness alert engine."""
from __future__ import annotations

import time

import pytest

from src.api import source_health_alerts as sha
from src.api import user_kv


@pytest.fixture()
def kv(tmp_path):
    path = tmp_path / "user_kv.sqlite"
    user_kv._SETUP_DONE.clear()
    yield path
    user_kv._SETUP_DONE.clear()


def _iso(hours_ago):
    t = time.time() - hours_ago * 3600
    import datetime as dt
    return dt.datetime.utcfromtimestamp(t).isoformat() + "+00:00"


def test_fresh_sources_produce_no_alerts():
    health = {
        "ktc": {"lastFetched": _iso(1)},  # 1h ago, threshold 48h
        "fantasyCalc": {"lastFetched": _iso(12)},
    }
    alerts = sha.detect_stale_sources(health)
    assert alerts == []


def test_stale_source_detected():
    health = {
        "ktc": {"lastFetched": _iso(72)},  # 72h ago, threshold 48h → stale
    }
    alerts = sha.detect_stale_sources(health)
    assert len(alerts) == 1
    assert alerts[0].source == "ktc"
    assert alerts[0].transition == "stale"


def test_dlf_monthly_source_not_flagged_at_7d():
    """DLF updates monthly; 7 days stale should NOT trigger (threshold 31d)."""
    health = {"dlf": {"lastFetched": _iso(7 * 24)}}
    alerts = sha.detect_stale_sources(health)
    assert alerts == []


def test_sources_nested_under_sources_key():
    """Tolerate both flat + nested shapes."""
    flat = {"ktc": {"lastFetched": _iso(100)}}
    nested = {"sources": {"ktc": {"lastFetched": _iso(100)}}}
    assert len(sha.detect_stale_sources(flat)) == 1
    assert len(sha.detect_stale_sources(nested)) == 1


def test_missing_last_fetched_is_skipped():
    health = {"ktc": {"status": "ok"}}
    alerts = sha.detect_stale_sources(health)
    assert alerts == []


def test_check_and_alert_fires_once_then_cools_down(kv):
    sends = []
    def delivery(to, subj, body):
        sends.append((to, subj, body))
        return True
    health = {"ktc": {"lastFetched": _iso(72)}}
    # First call — should send.
    sha.check_and_alert(
        health,
        delivery=delivery, to_email="test@example.com",
        kv_path=kv, cooldown_hours=72,
    )
    assert len(sends) == 1
    # Second call within cooldown — skipped.
    sha.check_and_alert(
        health,
        delivery=delivery, to_email="test@example.com",
        kv_path=kv, cooldown_hours=72,
    )
    assert len(sends) == 1


def test_recovery_alert_fires_when_source_returns(kv):
    sends = []
    def delivery(to, subj, body):
        sends.append((to, subj, body))
        return True
    stale_health = {"ktc": {"lastFetched": _iso(72)}}
    fresh_health = {"ktc": {"lastFetched": _iso(1)}}
    # First pass — alert fires.
    sha.check_and_alert(
        stale_health, delivery=delivery, to_email="test@example.com", kv_path=kv,
    )
    assert len(sends) == 1
    # Source recovers — recovery alert fires.
    result = sha.check_and_alert(
        fresh_health, delivery=delivery, to_email="test@example.com", kv_path=kv,
    )
    assert result["recovered"] >= 1
    assert len(sends) == 2
    # Next run — nothing new.
    sha.check_and_alert(
        fresh_health, delivery=delivery, to_email="test@example.com", kv_path=kv,
    )
    assert len(sends) == 2


def test_no_delivery_hook_doesnt_crash(kv):
    health = {"ktc": {"lastFetched": _iso(72)}}
    result = sha.check_and_alert(
        health, delivery=None, to_email=None, kv_path=kv,
    )
    assert result["delivered"] == 0
    assert result["stale"] == 1


def test_load_thresholds_reads_config(tmp_path):
    cfg = tmp_path / "st.json"
    import json
    cfg.write_text(json.dumps({"thresholds": {"customSrc": 12}}), encoding="utf-8")
    t = sha.load_thresholds(cfg)
    assert t["customSrc"] == 12
    # Defaults still present.
    assert "ktc" in t


def test_load_thresholds_absent_file_returns_defaults(tmp_path):
    t = sha.load_thresholds(tmp_path / "none.json")
    assert t["ktc"] == 48
