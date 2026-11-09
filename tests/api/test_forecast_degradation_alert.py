"""MD-104: degradation review requests ride the existing ops_alerts path, deduplicated."""

from __future__ import annotations

import json

import pytest

from src.api import ops_alerts

CATEGORY = "forecast_degradation:lg:game_day_win:winMatchup:m1:forecast_degradation_v1"


def _review(**over) -> dict:
    row = {
        "ruleVersion": "forecast_degradation_v1",
        "leagueKey": "lg",
        "family": "game_day_win",
        "target": "winMatchup",
        "modelVersion": "m1",
        "metric": "brier",
        "baseline": "coin_flip_0.5",
        "margin": 0.005,
        "delta": 0.0123,
        "deltaCi95": [0.001, 0.02],
        "eligible": 200,
        "streak": 3,
        "streakRequired": 3,
        "category": CATEGORY,
    }
    row.update(over)
    return row


@pytest.fixture
def kv(tmp_path):
    return tmp_path / "ops_state.json"


def _sweep(kv, reviews, sent):
    return ops_alerts.check_and_alert(
        forecast_degradation=reviews,
        delivery=lambda to, s, b: (sent.append((s, b)), True)[1],
        to_email="ops@example.com",
        kv_path=kv,
    )


def test_alert_names_the_rule_version_and_is_review_only(kv) -> None:
    sent: list = []
    out = _sweep(kv, [_review()], sent)
    assert out["fired"] == 1 and out["delivered"] is True
    _subject, body = sent[0]
    assert "forecast_degradation_v1" in body
    assert "REVIEW REQUEST" in body and "nothing was promoted, demoted, disabled or changed" in body
    assert "game_day_win" in body and "0.0123" in body


def test_a_persisting_condition_is_deduplicated_even_past_the_cooldown(kv, monkeypatch) -> None:
    sent: list = []
    _sweep(kv, [_review()], sent)
    _sweep(kv, [_review()], sent)
    real = ops_alerts.time.time
    monkeypatch.setattr(ops_alerts.time, "time", lambda: real() + 30 * 86400)
    third = _sweep(kv, [_review()], sent)
    assert third["fired"] == 0
    assert len(sent) == 1


def test_a_new_model_version_is_a_new_review(kv) -> None:
    sent: list = []
    _sweep(kv, [_review()], sent)
    other = _review(modelVersion="m2", category=CATEGORY.replace(":m1:", ":m2:"))
    again = _sweep(kv, [_review(), other], sent)
    assert again["fired"] == 1 and len(sent) == 2


def test_cleared_condition_recovers_once_then_rearms(kv) -> None:
    sent: list = []
    _sweep(kv, [_review()], sent)
    cleared = _sweep(kv, [], sent)
    assert cleared["recovered"] == 1
    refire = _sweep(kv, [_review()], sent)
    assert refire["fired"] == 1


def test_unreadable_scorecard_is_unknown_not_recovered(kv) -> None:
    sent: list = []
    _sweep(kv, [_review()], sent)
    unknown = _sweep(kv, None, sent)
    assert unknown["recovered"] == 0 and len(sent) == 1


def test_a_row_without_the_review_prefix_is_ignored() -> None:
    assert ops_alerts._check_forecast_degradation([_review(category="scrape_failure")]) == []
    assert ops_alerts._check_forecast_degradation([{"nope": 1}, "x"]) == []


def test_malformed_scorecard_content_cannot_break_the_sweep(kv, monkeypatch) -> None:
    sent: list = []
    bad = _review(deltaCi95=["a", "b"], delta="oops")
    out = _sweep(kv, [bad, _review(deltaCi95="not a list")], sent)
    assert out["fired"] >= 1

    def boom(rows):
        raise RuntimeError("x")

    monkeypatch.setattr(ops_alerts, "_check_forecast_degradation", boom)
    result = ops_alerts.check_and_alert(forecast_degradation=[_review()], kv_path=kv)
    assert result["active"] == 0


def _stamped(tmp_path, evaluated_at, name):
    p = tmp_path / name
    p.write_text(
        json.dumps({"evaluatedAt": evaluated_at, "degradationReviews": [_review()]}),
        encoding="utf-8",
    )
    return p


def test_reader_stale_is_unknown_and_fresh_is_read(tmp_path) -> None:
    from datetime import datetime, timezone

    now = datetime(2026, 11, 20, tzinfo=timezone.utc).timestamp()
    fresh = _stamped(tmp_path, "2026-11-19T00:00:00+00:00", "fresh.json")
    stale = _stamped(tmp_path, "2026-11-01T00:00:00+00:00", "stale.json")  # 19 days old
    garbled = _stamped(tmp_path, "not a time", "garbled.json")
    unstamped = tmp_path / "u.json"
    unstamped.write_text(json.dumps({"degradationReviews": [_review()]}), encoding="utf-8")
    assert ops_alerts.forecast_degradation_reviews(fresh, now=now) == [_review()]
    assert ops_alerts.forecast_degradation_reviews(stale, now=now) is None
    assert ops_alerts.forecast_degradation_reviews(garbled, now=now) is None
    assert ops_alerts.forecast_degradation_reviews(unstamped, now=now) is None
    assert ops_alerts.forecast_degradation_reviews(tmp_path / "absent.json", now=now) == []


def test_reader_missing_corrupt_and_valid(tmp_path) -> None:
    from datetime import datetime, timezone

    stamp = datetime.now(timezone.utc).isoformat()
    assert ops_alerts.forecast_degradation_reviews(tmp_path / "absent.json") == []
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert ops_alerts.forecast_degradation_reviews(bad) is None
    good = tmp_path / "good.json"
    good.write_text(
        json.dumps({"evaluatedAt": stamp, "degradationReviews": [_review()]}), encoding="utf-8"
    )
    assert ops_alerts.forecast_degradation_reviews(good) == [_review()]
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"evaluatedAt": stamp, "other": 1}), encoding="utf-8")
    assert ops_alerts.forecast_degradation_reviews(wrong) is None
