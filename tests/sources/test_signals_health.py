"""Signals HEALTH mode — per-family truth, owners reused, public projection safe.

Plan PR-H §5.5 ("health mode").  Synthetic store only: every player, value
and token is invented; no systemd, no network, no real session.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest

from src.api import feature_flags
from src.sources import signals as S
from src.sources import signals_health as H
from tests.sources.test_signals_family_collection import _idp, _only
from tests.sources.test_signals_values import IDP_KEYS

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _floors(monkeypatch):
    monkeypatch.setattr(S, "MIN_BOARD_ROWS", dict.fromkeys(("signalsSf", *IDP_KEYS), 5))


class FakeAuthStore:
    """Duck-typed ``signals_auth.SignalsStore`` with a synthetic session."""

    def __init__(self, tmp):
        from src.sources import signals_auth as SA

        self._s = SA.SignalsStore(tmp / "auth")

    def __getattr__(self, name):
        return getattr(self._s, name)


def _show_factory(start_ts: str = "Mon 2026-10-05 07:20:00 UTC"):
    def show(unit, props):
        if unit.endswith(".timer"):
            return {"LoadState": "loaded", "ActiveState": "active", "UnitFileState": "enabled"}
        return {
            "LoadState": "loaded",
            "ActiveState": "inactive",
            "Result": "success",
            "ExecMainStatus": "0",
            "ExecMainStartTimestamp": start_ts,
        }

    return show


def _status(*, dl_enabled=False):
    return {
        "featureFlags": {
            "signals_active_source": {"enabled": True, "gateStatus": "LIVE"},
            "signals_idp_shared_market": {"enabled": False, "gateStatus": "LIVE"},
            "signals_idp_family_quarantine": {"enabled": False, "gateStatus": "LIVE"},
        },
        "served_private_absent_by_design": list(IDP_KEYS),
    }


def _app(tmp_path):
    """Lay the collector's store/state out as the app dir would."""
    app = tmp_path / "app"
    (app / "data" / "sources").mkdir(parents=True)
    return app


def _collect(app, items, *, at, monkeypatch=None):
    # reuse the collection helper against the app's own layout
    from tests.sources.test_signals_values import FakeAppSync, FakeTokens

    return S.collect_values(
        app / "data" / "sources" / "signals",
        repo_root=app,
        state_dir=app / "data" / "scrape_state",
        tokens=FakeTokens(),
        http_post=FakeAppSync(idp_pages=[items]),
        now=lambda: at,
        sleep=lambda s: None,
        season=2026,
        datasets=("idp",),
    )


def _report(app, tmp_path, **kw):
    return H.build_health_report(
        app,
        now=NOW,
        show=kw.get("show", _show_factory()),
        status_fetch=lambda: kw.get("status", _status()),
        auth_store=FakeAuthStore(tmp_path),
        meminfo=tmp_path / "no-meminfo",
    )


def test_a_healthy_collection_reports_every_family_consistent(tmp_path):
    app = _app(tmp_path)
    t = datetime(2026, 10, 5, 7, 20, tzinfo=timezone.utc)
    _collect(app, _idp(), at=t)
    rep = _report(app, tmp_path)
    for key in IDP_KEYS:
        b = rep["boards"][key]
        assert b["boardState"] == S.BOARD_ACCEPTED
        assert b["csvPresent"] and b["csvMatchesLatest"] and b["csvMatchesLastGood"]
        assert b["lastSuccessAgreesWithVerification"] is True
        assert b["datasetHealth"] == "HEALTHY"
        assert b["lastSuccessAgeHours"] == pytest.approx(4.7, abs=0.1)
    assert rep["collection"]["collectionRan"] is True
    assert rep["collection"]["skippedByMinInterval"] is False
    assert rep["served"]["absentByDesign"] == {
        "signalsSf": False,
        **dict.fromkeys(IDP_KEYS, True),
    }
    assert rep["served"]["flags"]["signals_idp_dl_vote"] == {"registered": False, "enabled": None}
    assert set(rep["weighting"]) == set(H.SIGNALS_KEYS)


def test_a_min_interval_skip_is_named(tmp_path):
    app = _app(tmp_path)
    _collect(app, _idp(), at=datetime(2026, 10, 5, 1, 20, tzinfo=timezone.utc))
    rep = _report(app, tmp_path, show=_show_factory("Mon 2026-10-05 07:21:00 UTC"))
    assert rep["collection"]["skippedByMinInterval"] is True
    assert rep["collection"]["collectionRan"] is False


def test_a_stamp_without_verification_or_a_tampered_csv_is_caught(tmp_path):
    app = _app(tmp_path)
    t = datetime(2026, 10, 5, 7, 20, tzinfo=timezone.utc)
    _collect(app, _idp(), at=t)
    state = app / "data" / "scrape_state"
    # a success stamp newer than any verification (a failed run refreshing a clock)
    (state / "signalsIdpLb_last_success").write_text(f"{int(NOW.timestamp())}\n", encoding="utf-8")
    csv = S.board_csv_path(app / "data" / "sources" / "signals", "signalsIdpDb")
    csv.write_text(
        csv.read_text(encoding="utf-8") + "Synthetic Extra,99,1,9,DB,CB,SYN,NATIVE_VALUE,1,,idp\n",
        encoding="utf-8",
    )
    rep = _report(app, tmp_path)
    assert rep["boards"]["signalsIdpLb"]["lastSuccessAgreesWithVerification"] is False
    assert rep["boards"]["signalsIdpDb"]["csvMatchesLatest"] is False
    assert rep["boards"]["signalsIdpDl"]["csvMatchesLatest"] is True


def test_a_family_carried_through_a_family_quarantine_points_at_its_last_good(
    tmp_path, monkeypatch
):
    app = _app(tmp_path)
    _collect(app, _idp(), at=datetime(2026, 10, 4, 7, 20, tzinfo=timezone.utc))
    monkeypatch.setenv("RISKIT_FEATURE_SIGNALS_IDP_FAMILY_QUARANTINE", "1")
    feature_flags.reload()
    try:
        later = _idp()
        for it in later:
            it["value"] += 1
        out = _collect(
            app, _only(later, "DB", 2), at=datetime(2026, 10, 5, 7, 20, tzinfo=timezone.utc)
        )
        assert out["datasets"]["idp"]["outcome"] == "partially_quarantined"
    finally:
        monkeypatch.delenv("RISKIT_FEATURE_SIGNALS_IDP_FAMILY_QUARANTINE")
        feature_flags.reload()
    rep = _report(app, tmp_path)
    db = rep["boards"]["signalsIdpDb"]
    assert db["boardState"] == S.BOARD_QUARANTINED
    assert db["csvMatchesLatest"] is True  # latest carries its rows verbatim
    assert db["csvMatchesLastGood"] is True
    assert db["lastGoodIsLatest"] is False
    assert db["lastSuccessAgreesWithVerification"] is True  # older, never newer
    assert db["datasetHealth"] == "DEGRADED"
    assert rep["collection"]["quarantineCensus"]["idp"]["family"] == 1


def test_unreachable_status_is_reported_not_guessed(tmp_path):
    app = _app(tmp_path)
    rep = H.build_health_report(
        app,
        now=NOW,
        show=_show_factory(),
        status_fetch=lambda: None,
        auth_store=FakeAuthStore(tmp_path),
        meminfo=tmp_path / "x",
    )
    assert rep["served"] == {"statusReachable": False}
    assert rep["collection"]["provisioned"] is False
    for key in H.SIGNALS_KEYS:
        assert rep["boards"][key]["csvPresent"] is False


def test_the_public_projection_carries_no_timestamp_name_or_path(tmp_path):
    app = _app(tmp_path)
    _collect(app, _idp(), at=datetime(2026, 10, 5, 7, 20, tzinfo=timezone.utc))
    rep = _report(app, tmp_path)
    pub = H.public_projection(rep)
    text = json.dumps(pub)
    assert "Synthetic" not in text
    assert "2026-" not in text and "T07:" not in text
    assert str(app) not in text
    assert "_" + "lastRunAt" not in text
    assert pub["boards"]["signalsIdpDb"]["csvMatchesLatest"] is True


@pytest.mark.parametrize(
    "leaf",
    ["2026-10-05T07:20:00Z", "Synthetic Player", "/home/x/y", "eyJhbGciOi.token.value"],
)
def test_the_guard_refuses_any_unsafe_leaf(leaf):
    with pytest.raises(H.PublicLeak):
        H.assert_public_safe({"boards": {"signalsIdpDl": {"boardState": leaf}}})


def test_the_cli_never_prints_an_exception_message(tmp_path, monkeypatch, capsys):
    from scripts import verify_signals_health as V

    def boom(*a, **k):
        raise ValueError("Synthetic Player Name 4321 leaked")

    monkeypatch.setattr(H, "build_health_report", boom)
    app = _app(tmp_path)
    rc = V.main(["--app-dir", str(app)])
    out, err = capsys.readouterr()
    assert rc == 1
    assert json.loads(out) == {"error": "ValueError"}
    assert "Synthetic" not in out + err and "4321" not in out + err
    logs = list((app / "data" / "sources" / "signals" / "reports").glob("health-*.log"))
    assert logs
    if os.name == "posix":  # POSIX permission bits; Windows reports 0o666 (ACLs)
        assert (logs[0].stat().st_mode & 0o777) == 0o600


# -- redaction: a failing source must still be reportable --------------------


def test_a_free_text_leaf_is_withheld_not_fatal():
    sentence = "HTTP 401: token expired at 2026-11-02T07:20:00Z for user Synthetic Player"
    report = {
        "mode": "health",
        "weighting": {"error": sentence},
        "boards": {"signalsSf": {"boardState": "accepted", "lastOutcome": "fetch_failed: nope"}},
    }
    pub = H.public_projection(report)
    assert pub["weighting"]["error"] == H.WITHHELD_TOKEN
    assert pub["boards"]["signalsSf"]["lastOutcome"] == H.WITHHELD_TOKEN
    assert pub["boards"]["signalsSf"]["boardState"] == "accepted"
    assert pub["redacted"] == {"boards__signalsSf__lastOutcome": True, "weighting__error": True}
    text = json.dumps(pub)
    for raw in ("token expired", "2026-11", "Synthetic", "fetch_failed:"):
        assert raw not in text
    H.assert_public_safe(pub)


def test_an_unsafe_key_is_dropped_and_counted():
    report = {"served": {"absentByDesign": {"bad key/Synthetic": True, "signalsSf": False}}}
    pub = H.public_projection(report)
    assert pub["served"]["absentByDesign"] == {"signalsSf": False}
    assert pub["redactedUnsafeKeys"] == 1
    assert "Synthetic" not in json.dumps(pub)


def test_a_safe_report_is_unchanged_and_carries_no_redacted_key():
    report = {
        "mode": "health",
        "session": {"state": "healthy", "renewalObserved": True},
        "memAvailableMb": 512,
    }
    pub = H.public_projection(report)
    assert pub == report
    assert not any(k.startswith("redacted") for k in pub)


def test_systemd_hyphenated_results_are_identifiers():
    assert H._identifier_or_none("exit-code") == "exit_code"
    assert H._identifier_or_none("start-limit-hit") == "start_limit_hit"
    assert H._identifier_or_none("") is None
    assert H._identifier_or_none("a b c") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ReconnectRequired", "auth_expired"),
        ("HTTP 403 forbidden", "auth_expired"),
        ("TimeoutError", "timeout"),
        ("URLError", "http_status"),
        ("JSONDecodeError", "parse"),
        ("FileNotFoundError", "missing_file"),
        ("SomethingElse", "unclassified"),
        (None, "unclassified"),
    ],
)
def test_error_class_mapping(text, expected):
    assert H.classify_error(text) == expected


# ── reconnect-notice attempt counts (owner directive 2026-11-18, Task 11) ──


def _session_with(monkeypatch, status):
    from src.sources import signals_auth as SA

    monkeypatch.setattr(SA, "status", lambda store: status)
    return H.session_section(auth_store=object())


def test_an_open_episode_with_no_attempts_reads_as_no_channel_configured(monkeypatch):
    sec = _session_with(
        monkeypatch,
        {
            "state": "reconnect_required",
            "episode": {"id": "e1", "failureClass": "reconnect_required"},
        },
    )
    assert sec["reconnectNoticeDelivered"] is False
    assert sec["reconnectNoticeAttempts"] == 0
    assert sec["reconnectNoticeChannelAttempts"] == {"ntfy": 0, "email": 0}


def test_failed_attempts_are_counted_per_known_channel_only(monkeypatch):
    sec = _session_with(
        monkeypatch,
        {
            "state": "reconnect_required",
            "episode": {
                "id": "e1",
                "noticeAttempts": 14,
                "noticeChannelAttempts": {"ntfy": 14, "email": 9, "https://hook.example/x": 3},
            },
        },
    )
    assert sec["reconnectNoticeAttempts"] == 14
    # An unknown (possibly unsafe) channel key is never published.
    assert sec["reconnectNoticeChannelAttempts"] == {"ntfy": 14, "email": 9}


def test_no_episode_publishes_no_counts(monkeypatch):
    sec = _session_with(monkeypatch, {"state": "healthy"})
    assert sec["reconnectNoticeAttempts"] is None
    assert sec["reconnectNoticeChannelAttempts"] is None


@pytest.mark.parametrize("bad", ["lots", -1, True])
def test_a_corrupt_count_is_unknown_not_zero(monkeypatch, bad):
    sec = _session_with(
        monkeypatch,
        {"state": "reconnect_required", "episode": {"id": "e1", "noticeAttempts": bad}},
    )
    assert sec["reconnectNoticeAttempts"] is None


def test_the_counts_reach_the_public_projection(monkeypatch):
    report = {
        "mode": "health",
        "session": {
            "state": "reconnect_required",
            "reconnectNoticeDelivered": False,
            "reconnectNoticeAttempts": 3,
            "reconnectNoticeChannelAttempts": {"ntfy": 3, "email": 0},
        },
    }
    out = H.public_projection(report)
    assert out["session"]["reconnectNoticeAttempts"] == 3
    assert out["session"]["reconnectNoticeChannelAttempts"] == {"ntfy": 3, "email": 0}
    assert "redacted" not in out


# ── owner-alert channel configuration (owner directive 2026-11-19, STAB-2) ──

_TOPIC = "https://ntfy.sh/private-topic-xyz"


def _routing(tmp_path, env_text, props=None):
    (tmp_path / ".env").write_text(env_text, encoding="utf-8")
    props = props or {}

    def show(unit, wanted):
        return props.get(unit, {})

    return H.alert_routing_section(tmp_path, {"alertSweep": {"timerActive": True}}, show)


def test_routing_reads_the_env_file_as_booleans(tmp_path):
    out = _routing(
        tmp_path, f"# comment\nexport NOTIFY_WEBHOOK_URL='{_TOPIC}'\nALERT_ENABLED=false\n"
    )
    assert out["envFileReadable"] is True
    assert out["ntfyConfigured"] is True
    assert out["emailConfigured"] is False
    assert out["sweepTimerActive"] is True


def test_last_assignment_wins_and_empty_is_unconfigured(tmp_path):
    out = _routing(tmp_path, f"NOTIFY_WEBHOOK_URL={_TOPIC}\nNOTIFY_WEBHOOK_URL=\n")
    assert out["ntfyConfigured"] is False


def test_unreadable_env_is_unknown_not_unconfigured(tmp_path):
    out = H.alert_routing_section(tmp_path / "missing", {}, lambda u, p: {})
    assert out["envFileReadable"] is False
    assert out["ntfyConfigured"] is None and out["emailConfigured"] is None


def test_dropin_units_report_push_presence(tmp_path):
    props = {
        "riskit-uptime.service": {
            "LoadState": "loaded",
            "Environment": f"LOG_FILE=/dev/stdout NOTIFY_WEBHOOK_URL={_TOPIC}",
        },
        "dynasty-signals-auth-renew.service": {
            "LoadState": "loaded",
            "Environment": "RISKIT_SIGNALS_AUTH_DIR=/var/lib/signals-auth",
        },
    }
    out = _routing(tmp_path, "", props)
    assert out["uptimeProbeNtfyConfigured"] is True
    assert out["renewalNtfyConfigured"] is False


def test_a_missing_unit_is_unknown(tmp_path):
    out = _routing(tmp_path, "", {"riskit-uptime.service": {"LoadState": "not-found"}})
    assert out["uptimeProbeNtfyConfigured"] is None
    assert out["renewalNtfyConfigured"] is None


@pytest.mark.parametrize(
    ("value", "state", "configured"),
    [
        (_TOPIC, "ok", True),
        ("", "unset", False),
        ("http://ntfy.sh/private-topic-xyz", "rejected_scheme", False),
        ("https://u:p@ntfy.sh/private-topic-xyz", "rejected_userinfo", False),
    ],
)
def test_routing_says_why_the_webhook_is_off(tmp_path, value, state, configured):
    out = _routing(tmp_path, f"NOTIFY_WEBHOOK_URL={value}\n")
    assert out["ntfyState"] == state and out["ntfyConfigured"] is configured
    projected = H.public_projection({"mode": "health", "alertRouting": out})
    assert projected["alertRouting"]["ntfyState"] == state
    assert "redacted" not in projected
    assert "private-topic" not in json.dumps(projected)


def test_unreadable_env_has_no_state(tmp_path):
    out = H.alert_routing_section(tmp_path / "missing", {}, lambda u, p: {})
    assert out["ntfyState"] is None


@pytest.mark.parametrize(
    ("value", "configured"),
    [
        ("HTTPS://ntfy.sh/private-topic-xyz", False),  # the one validator: lower-case scheme
        ("https://u:p@ntfy.sh/private-topic-xyz", False),
        ("http://127.0.0.1:8080/relay", True),  # what owner_notify itself would send to
    ],
)
def test_dropins_are_judged_by_the_one_validator(tmp_path, value, configured):
    props = {
        "dynasty-signals-auth-renew.service": {
            "LoadState": "loaded",
            "Environment": f"NOTIFY_WEBHOOK_URL={value}",
        }
    }
    assert _routing(tmp_path, "", props)["renewalNtfyConfigured"] is configured


def test_routing_never_leaks_the_topic_through_the_projection(tmp_path):
    props = {
        "riskit-uptime.service": {
            "LoadState": "loaded",
            "Environment": f"NOTIFY_WEBHOOK_URL={_TOPIC}",
        }
    }
    routing = _routing(tmp_path, f"NOTIFY_WEBHOOK_URL={_TOPIC}\n", props)
    out = H.public_projection({"mode": "health", "alertRouting": routing})
    text = json.dumps(out)
    assert "ntfy.sh" not in text and "private-topic" not in text
    assert out["alertRouting"]["ntfyConfigured"] is True
    assert out["alertRouting"]["uptimeProbeNtfyConfigured"] is True
    assert "redacted" not in out
