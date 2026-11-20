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
        "dlfSf",
        "dlfIdp",
        "dlfRookieSf",
        "dlfRookieIdp",
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
        delivery=delivery,
        to_email="test@example.com",
        kv_path=kv,
        cooldown_hours=72,
    )
    assert len(sends) == 1
    # Second call within cooldown — skipped.
    sha.check_and_alert(
        health,
        delivery=delivery,
        to_email="test@example.com",
        kv_path=kv,
        cooldown_hours=72,
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
        stale_health,
        delivery=delivery,
        to_email="test@example.com",
        kv_path=kv,
    )
    assert len(sends) == 1
    result = sha.check_and_alert(
        fresh_health,
        delivery=delivery,
        to_email="test@example.com",
        kv_path=kv,
    )
    assert result["recovered"] >= 1
    assert len(sends) == 2
    sha.check_and_alert(
        fresh_health,
        delivery=delivery,
        to_email="test@example.com",
        kv_path=kv,
    )
    assert len(sends) == 2


def test_no_delivery_hook_doesnt_crash(kv):
    health = {"ktc": {"lastFetched": _iso(30)}}
    result = sha.check_and_alert(
        health,
        delivery=None,
        to_email=None,
        kv_path=kv,
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
    for vendor in (
        "ktc",
        "dlf",
        "fantasyCalc",
        "dynastyDaddy",
        "fantasyPros",
        "yahooBoone",
        "idpShow",
    ):
        assert thresholds[vendor] == 24, f"{vendor} threshold drifted from the universal 24h policy"


# ── freshness D1: a first-observation baseline alert says what it knows ──


def _baseline_weighting(baseline: bool) -> dict:
    sub = {
        "state": "SEVERELY_STALE",
        "ageHours": 480.0,
        "expectedCadenceHours": 72.0,
        "sourceDataAsOf": None if baseline else "2026-09-17T12:00:00Z",
        "clockIsObservationBaseline": baseline,
        "observationBaselineAt": "2026-09-17T12:00:00Z" if baseline else None,
        "ageIsLowerBound": baseline,
    }
    return {"sources": {"dlfSf": {"health": "HEALTHY", "subsets": {"players": sub}}}}


def test_a_baseline_content_alert_carries_its_first_observation_time():
    alerts = [
        a
        for a in sha.detect_content_alerts(_baseline_weighting(True))
        if a.source == "content:dlfSf/players"
    ]
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.last_seen_iso == "2026-09-17T12:00:00Z"
    assert alert.age_is_lower_bound is True
    body = sha._format_body([alert])
    assert "at least 480.0h stale" in body
    assert "first observed 2026-09-17T12:00:00Z" in body
    assert "last seen" not in body


def test_a_measured_content_alert_keeps_its_wording():
    alert = next(
        a
        for a in sha.detect_content_alerts(_baseline_weighting(False))
        if a.source == "content:dlfSf/players"
    )
    assert alert.age_is_lower_bound is False
    assert "last seen 2026-09-17T12:00:00Z" in sha._format_body([alert])


# ── delivery spends the cooldown, a decision does not (2026-11-20) ─────────
# The 72 h window used to be stamped BEFORE delivery and never rolled back, so
# a sweep with no channel (or a failing one) silenced the source for three days,
# and an undelivered recovery was lost for good.  ``ops_alerts`` has followed
# the delivered-only rule since audit F-20; these pin the same rule here.


def _stale():
    return {"ktc": {"lastFetched": _iso(30)}}


def _fresh():
    return {"ktc": {"lastFetched": _iso(1)}}


class _Channel:
    """A delivery callable that records calls and returns scripted results."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls: list[str] = []

    def __call__(self, to, subject, body):
        self.calls.append(subject)
        result = self.results.pop(0) if self.results else True
        if isinstance(result, Exception):
            raise result
        return result


def _sweep(kv, health, channel=None, to="owner-channel"):
    return sha.check_and_alert(
        health,
        delivery=channel,
        to_email=to if channel is not None else None,
        kv_path=kv,
        cooldown_hours=72,
    )


def _entry(kv, src="ktc"):
    return user_kv.get_user_state("_system_source_health", path=kv)["sourceHealthAlertState"][src]


def _seed(kv, entry, src="ktc"):
    def _apply(state):
        state["sourceHealthAlertState"] = {src: entry}

    user_kv.mutate_user_state("_system_source_health", _apply, path=kv)


@pytest.mark.parametrize(
    "first",
    [None, False, RuntimeError("ntfy down")],
    ids=["unconfigured", "returns_false", "raises"],
)
def test_an_undelivered_alert_spends_no_cooldown(kv, first):
    if first is None:
        summary = _sweep(kv, _stale())  # no channel at all
        assert summary["deliveryConfigured"] is False
    else:
        summary = _sweep(kv, _stale(), _Channel(first))
        assert summary["deliveryConfigured"] is True
    assert summary["stale"] == 1 and summary["delivered"] == 0
    assert "lastDeliveredAt" not in _entry(kv)

    working = _Channel(True)
    summary = _sweep(kv, _stale(), working)
    assert summary["skipped_cooldown"] == 0
    assert summary["delivered"] == 1 and len(working.calls) == 1
    assert _entry(kv)["lastDeliveredAt"]

    # Once DELIVERED, the window holds.
    again = _Channel(True)
    summary = _sweep(kv, _stale(), again)
    assert summary["skipped_cooldown"] == 1 and again.calls == []


def test_an_undelivered_recovery_is_retried_until_delivered(kv):
    _sweep(kv, _stale(), _Channel(True))  # the owner is told: stale
    summary = _sweep(kv, _fresh(), _Channel(False))
    assert summary["recovered"] == 1 and summary["delivered"] == 0
    assert _entry(kv)["currentlyStale"] is True, "an undelivered recovery stays pending"

    working = _Channel(True)
    summary = _sweep(kv, _fresh(), working)
    assert summary["recovered"] == 1 and summary["delivered"] == 1
    assert working.calls == ["[Brisket Ops] 1 source recovered"]
    assert _entry(kv)["currentlyStale"] is False

    later = _Channel(True)
    assert _sweep(kv, _fresh(), later)["recovered"] == 0 and later.calls == []


def test_an_episode_nobody_was_told_about_ends_silently(kv):
    _sweep(kv, _stale())  # stale, but no channel: the owner never heard
    channel = _Channel(True)
    summary = _sweep(kv, _fresh(), channel)
    assert summary["recovered"] == 0 and channel.calls == []
    assert _entry(kv)["currentlyStale"] is False


def test_legacy_last_alerted_at_still_suppresses_after_upgrade(kv):
    """State written before 2026-11-20 carries only ``lastAlertedAt``: it keeps
    suppressing what it suppressed, so an upgrade is not a burst."""
    _seed(kv, {"currentlyStale": True, "lastAlertedAt": time.time() - 3600, "hoursStale": 30.0})
    channel = _Channel(True)
    summary = _sweep(kv, _stale(), channel)
    assert summary["skipped_cooldown"] == 1 and channel.calls == []

    # ...and a legacy episode still earns its recovery notice.
    summary = _sweep(kv, _fresh(), channel)
    assert summary["recovered"] == 1 and len(channel.calls) == 1


def test_an_expired_legacy_window_fires_and_is_replaced_by_a_delivery_stamp(kv):
    old = time.time() - 80 * 3600
    _seed(kv, {"currentlyStale": True, "lastAlertedAt": old})
    _sweep(kv, _stale(), _Channel(False))  # a failed re-alert keeps the old stamp
    assert _entry(kv)["lastAlertedAt"] == old
    _sweep(kv, _stale(), _Channel(True))  # ...so the next sweep retries and delivers
    entry = _entry(kv)
    assert "lastAlertedAt" not in entry and entry["lastDeliveredAt"] > old


def test_a_failed_re_alert_keeps_the_previous_delivery(kv):
    """An undelivered re-alert must not erase when the owner was last told."""
    delivered_at = time.time() - 80 * 3600
    _seed(kv, {"currentlyStale": True, "lastDeliveredAt": delivered_at})
    _sweep(kv, _stale(), _Channel(False))
    assert _entry(kv)["lastDeliveredAt"] == delivered_at
    assert "sendingAt" not in _entry(kv), "the in-flight claim is released"


def test_an_in_flight_claim_blocks_a_second_sender(kv):
    _seed(kv, {"currentlyStale": True, "sendingAt": time.time() - 5})
    channel = _Channel(True)
    summary = _sweep(kv, _stale(), channel)
    assert summary["skipped_in_flight"] == 1 and channel.calls == []


def test_an_abandoned_claim_expires(kv):
    _seed(kv, {"currentlyStale": True, "sendingAt": time.time() - 3600})
    assert _sweep(kv, _stale(), _Channel(True))["delivered"] == 1


def test_nothing_configured_is_one_warning_per_sweep(kv, caplog):
    import logging

    health = {"ktc": {"lastFetched": _iso(30)}, "dlfSf": {"lastFetched": _iso(30)}}
    with caplog.at_level(logging.WARNING, logger="src.api.source_health_alerts"):
        _sweep(kv, health)
    lines = [r.getMessage() for r in caplog.records if "no owner alert channel" in r.getMessage()]
    assert len(lines) == 1 and "2 notice(s)" in lines[0]
