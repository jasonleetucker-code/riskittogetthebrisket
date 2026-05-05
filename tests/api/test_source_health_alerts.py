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
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat()


def test_fresh_sources_produce_no_alerts():
    health = {
        "ktc": {"lastFetched": _iso(1)},
        "fantasyCalc": {"lastFetched": _iso(12)},
    }
    alerts = sha.detect_stale_sources(health)
    assert alerts == []


def test_stale_source_detected():
    """Default 24h policy: a source 30h since last fetch is stale."""
    health = {"ktc": {"lastFetched": _iso(30)}}
    alerts = sha.detect_stale_sources(health)
    assert len(alerts) == 1
    assert alerts[0].source == "ktc"
    assert alerts[0].transition == "stale"
    assert alerts[0].threshold_hours == 24.0


def test_universal_24h_policy_flags_dlf_after_one_day():
    """DLF used to have a 31-day threshold; the universal policy now
    catches a single-day fetch outage on every source, including the
    four DLF boards."""
    health = {
        "dlfSf": {"lastFetched": _iso(30)},
        "dlfIdp": {"lastFetched": _iso(30)},
        "dlfRookieSf": {"lastFetched": _iso(30)},
        "dlfRookieIdp": {"lastFetched": _iso(30)},
    }
    alerts = sha.detect_stale_sources(health)
    assert {a.source for a in alerts} == {
        "dlfSf", "dlfIdp", "dlfRookieSf", "dlfRookieIdp",
    }
    assert all(a.threshold_hours == 24.0 for a in alerts)


def test_source_within_24h_window_not_flagged():
    """Missing one or two 2h cron windows is fine — only flag when the
    gap exceeds 24h."""
    health = {"ktc": {"lastFetched": _iso(20)}}
    alerts = sha.detect_stale_sources(health)
    assert alerts == []


@pytest.mark.parametrize(
    "src",
    ["dlfSf", "dlfIdp", "dlfRookieSf", "dlfRookieIdp"],
)
def test_dlf_vendor_prefix_inherits_override(src):
    """Operators can still raise the threshold for a single vendor by
    setting a prefix entry — verifies the matching machinery is
    wired even though the production policy is uniform 24h."""
    custom = {"dlf": 72.0}
    # 48h ago: above the default 24h, below the 72h dlf override.
    health = {src: {"lastFetched": _iso(48)}}
    alerts = sha.detect_stale_sources(health, thresholds=custom)
    assert alerts == [], f"{src} flagged at 48h despite 72h dlf override"


def test_resolve_threshold_default_is_24h():
    assert sha.resolve_threshold("anySource", {}) == 24.0


def test_resolve_threshold_prefers_exact_over_prefix():
    """Pinning a single board (e.g. ``dlfSf``) overrides the vendor
    prefix (``dlf``) so operators can carve out exceptions."""
    thresholds = {"dlf": 72.0, "dlfSf": 12.0}
    assert sha.resolve_threshold("dlfSf", thresholds) == 12.0
    assert sha.resolve_threshold("dlfIdp", thresholds) == 72.0


def test_resolve_threshold_prefix_requires_camel_boundary():
    """A prefix only matches if the next character in the source is
    uppercase — guards against accidental matches on unrelated
    keys that share leading letters."""
    thresholds = {"ktc": 48.0}
    assert sha.resolve_threshold("ktcSfTep", thresholds) == 48.0
    # no boundary → no prefix match, falls back to default
    assert sha.resolve_threshold("ktcdraft", thresholds) == 24.0
    assert sha.resolve_threshold("somethingElse", thresholds) == 24.0


def test_resolve_threshold_picks_longest_prefix():
    """When multiple vendor prefixes match, the most specific one
    wins (``dynastyDaddy`` beats ``dynasty``)."""
    thresholds = {"dynasty": 999.0, "dynastyDaddy": 48.0}
    assert sha.resolve_threshold("dynastyDaddySf", thresholds) == 48.0


def test_sources_nested_under_sources_key():
    """Tolerate both flat + nested shapes."""
    flat = {"ktc": {"lastFetched": _iso(30)}}
    nested = {"sources": {"ktc": {"lastFetched": _iso(30)}}}
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
    health = {"ktc": {"lastFetched": _iso(30)}}
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
    stale_health = {"ktc": {"lastFetched": _iso(30)}}
    fresh_health = {"ktc": {"lastFetched": _iso(1)}}
    sha.check_and_alert(
        stale_health, delivery=delivery, to_email="test@example.com", kv_path=kv,
    )
    assert len(sends) == 1
    result = sha.check_and_alert(
        fresh_health, delivery=delivery, to_email="test@example.com", kv_path=kv,
    )
    assert result["recovered"] >= 1
    assert len(sends) == 2
    sha.check_and_alert(
        fresh_health, delivery=delivery, to_email="test@example.com", kv_path=kv,
    )
    assert len(sends) == 2


def test_no_delivery_hook_doesnt_crash(kv):
    health = {"ktc": {"lastFetched": _iso(30)}}
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
    assert t["ktc"] == 24


def test_production_config_is_uniform_24h():
    """The shipped config/source_staleness.json should encode the
    documented 24h-everywhere policy."""
    from pathlib import Path
    repo = Path(__file__).resolve().parents[2]
    thresholds = sha.load_thresholds(repo / "config" / "source_staleness.json")
    for vendor in ("ktc", "dlf", "fantasyCalc", "dynastyDaddy",
                   "fantasyPros", "footballGuys", "yahooBoone", "idpShow"):
        assert thresholds[vendor] == 24, (
            f"{vendor} threshold drifted from the universal 24h policy"
        )
