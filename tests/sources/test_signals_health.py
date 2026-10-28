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
    (state / "signalsIdpLb_last_success").write_text(f"{int(NOW.timestamp())}\n")
    csv = S.board_csv_path(app / "data" / "sources" / "signals", "signalsIdpDb")
    csv.write_text(csv.read_text() + "Synthetic Extra,99,1,9,DB,CB,SYN,NATIVE_VALUE,1,,idp\n")
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
