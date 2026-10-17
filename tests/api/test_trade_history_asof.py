"""Trade History At-the-Time grades + the public current-grade band
(owner package 2026-10-17, SITEWIDE_TRADE_ADJUSTMENT_AND_HISTORY_INTEGRATION).

Pins:

* the private ``POST /api/trades/asof-grades`` grades each side against the
  canonical ledger strictly before the trade, through the SAME resolver and
  grading function as the public ``/league`` grade — so the two agree by
  construction (parity is asserted, not assumed);
* look-ahead: an observation after the trade never changes the answer;
* missing evidence is ``available: False`` with the asset named — never a
  partial total, today's value or zero;
* the public current-grade band is band + label only, fails closed on an
  asset today's board cannot price, and passes the public-payload guard.
"""

from __future__ import annotations

import functools
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from src.api import trade_history_asof
from src.api.public_activity_valuation import build_asof_valuation
from src.history import store
from src.public_league import activity, public_contract, trade_grading

URL = "/api/trades/asof-grades"


def _ms(date_str: str) -> int:
    return int(datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc).timestamp() * 1000)


def _write(ledger: Path, asset_key: str, observed_date: str, value: float) -> None:
    result = store.write_observations(
        [
            {
                "asset_key": asset_key,
                "asset_class": "offense",
                "lane": store.LANE_CANONICAL,
                "source_key": "",
                "observed_date": observed_date,
                "observed_at": f"{observed_date}T12:00:00+00:00",
                "value": value,
                "origin": "test",
            }
        ],
        path=ledger,
    )
    assert result["written"] == 1, result


STAR = {"kind": "player", "playerId": "star", "playerName": "Star", "position": "QB"}
MID = {"kind": "player", "playerId": "mid", "playerName": "Mid", "position": "RB"}
DART = {"kind": "player", "playerId": "dart", "playerName": "Dart", "position": "WR"}
PICK_2027_R1 = {"kind": "pick", "season": 2027, "round": 1, "label": "2027 1st"}


def _trade(created_at, *, a_got, a_gave, tid="tx-1"):
    return {
        "id": tid,
        "createdAt": created_at,
        "sides": [
            {"receivedAssets": a_got, "sentAssets": a_gave},
            {"receivedAssets": a_gave, "sentAssets": a_got},
        ],
    }


@pytest.fixture()
def ledger(tmp_path):
    path = tmp_path / "ledger.sqlite"
    store._reset_setup_cache_for_tests()
    _write(path, "player:star", "2026-07-16", 7200.0)
    _write(path, "player:mid", "2026-07-16", 6000.0)
    _write(path, "player:dart", "2026-07-16", 500.0)
    yield path
    store._reset_setup_cache_for_tests()


def _resolver(ledger, trades):
    return build_asof_valuation(trade_history_asof.asof_requests(trades), path=ledger)


def test_grades_each_side_at_the_trade_through_the_shared_grade_function(ledger):
    trades = [_trade(_ms("2026-07-20"), a_got=[STAR], a_gave=[MID, DART])]
    (graded,) = trade_history_asof.grade_trades_asof(trades, _resolver(ledger, trades))
    a, b = graded["sides"]
    expected_a, expected_b = trade_grading.grade_trade_sides(
        [([7200.0], [6000.0, 500.0]), ([6000.0, 500.0], [7200.0])]
    )
    assert a == {"available": True, **expected_a}
    assert b == {"available": True, **expected_b}
    # Zero-sum in a 2-team trade, on the adjusted net too.
    assert a["netAdjusted"] == pytest.approx(-b["netAdjusted"])
    assert graded["asOf"].startswith("2026-07-20")


def test_post_trade_observation_never_changes_the_at_time_grade(ledger):
    trades = [_trade(_ms("2026-07-20"), a_got=[STAR], a_gave=[MID, DART])]
    before = trade_history_asof.grade_trades_asof(trades, _resolver(ledger, trades))
    _write(ledger, "player:star", "2026-08-10", 9999.0)
    after = trade_history_asof.grade_trades_asof(trades, _resolver(ledger, trades))
    assert before == after


def test_missing_evidence_is_unavailable_never_partial_or_zero(ledger):
    unknown = {"kind": "player", "playerId": "nobody", "playerName": "Nobody", "position": "TE"}
    trades = [_trade(_ms("2026-07-20"), a_got=[STAR, unknown], a_gave=[MID])]
    (graded,) = trade_history_asof.grade_trades_asof(trades, _resolver(ledger, trades))
    for side in graded["sides"]:
        assert side["available"] is False
        assert side["reason"] == "no_historical_evidence"
        assert side["missingAssets"] == [{"kind": "player", "name": "Nobody"}]
        assert "netAdjusted" not in side


def test_only_a_future_observation_is_still_unavailable(ledger):
    trades = [_trade(_ms("2026-07-10"), a_got=[STAR], a_gave=[MID])]
    (graded,) = trade_history_asof.grade_trades_asof(trades, _resolver(ledger, trades))
    assert all(s["available"] is False for s in graded["sides"])


def test_untrusted_instant_is_unavailable_never_now(ledger):
    trades = [
        _trade(None, a_got=[STAR], a_gave=[MID]),
        _trade(0, a_got=[STAR], a_gave=[MID], tid="tx-2"),
    ]
    graded = trade_history_asof.grade_trades_asof(trades, _resolver(ledger, trades))
    for trade in graded:
        assert trade["asOf"] is None
        assert [s["reason"] for s in trade["sides"]] == ["invalid_trade_instant"] * 2


def test_picks_resolve_at_the_generic_season_round_grade(ledger):
    _write(ledger, "mpick:2027:r1", "2026-07-16", 3000.0)
    trades = [_trade(_ms("2026-07-20"), a_got=[PICK_2027_R1], a_gave=[DART])]
    (graded,) = trade_history_asof.grade_trades_asof(trades, _resolver(ledger, trades))
    assert graded["sides"][0]["available"] is True
    assert graded["sides"][0]["gotValue"] == pytest.approx(3000.0)
    # An unparseable pick label never borrows a value.
    bad = dict(PICK_2027_R1, season=None)
    trades = [_trade(_ms("2026-07-20"), a_got=[bad], a_gave=[DART])]
    (graded,) = trade_history_asof.grade_trades_asof(trades, _resolver(ledger, trades))
    assert graded["sides"][0]["available"] is False


def test_private_at_time_equals_public_activity_grade(ledger):
    """The private endpoint and the public /league grade cannot disagree."""
    created = _ms("2026-07-20")
    trades = [_trade(created, a_got=[STAR], a_gave=[MID, DART])]
    (private,) = trade_history_asof.grade_trades_asof(trades, _resolver(ledger, trades))

    feed = [
        {
            "createdAt": created,
            "sides": [
                {"receivedAssets": [STAR], "sentAssets": [MID, DART]},
                {"receivedAssets": [MID, DART], "sentAssets": [STAR]},
            ],
        }
    ]
    factory = functools.partial(build_asof_valuation, path=ledger)
    requests = [
        (a, activity.trade_instant_from_created_at(created))
        for s in feed[0]["sides"]
        for a in s["receivedAssets"] + s["sentAssets"]
    ]
    activity._apply_trade_grades(feed, factory(requests))
    assert [s["grade"] for s in private["sides"]] == [s["grade"] for s in feed[0]["sides"]]


def test_response_without_a_ledger_says_so():
    trades = [_trade(_ms("2026-07-20"), a_got=[STAR], a_gave=[MID])]
    body = trade_history_asof.response(trades, None)
    assert body["available"] is False
    assert body["reason"] == "history_ledger_missing"
    assert body["packageModel"]["id"]
    assert [s["reason"] for s in body["trades"][0]["sides"]] == ["history_ledger_missing"] * 2


# ── Route ─────────────────────────────────────────────────────────────


def test_route_requires_auth():
    res = TestClient(server.app).post(URL, json={"trades": []})
    assert res.status_code == 401


def test_route_grades_and_never_caches(ledger, monkeypatch):
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    monkeypatch.setattr(store, "DB_PATH", ledger)
    monkeypatch.setattr(
        server, "_build_asof_valuation", functools.partial(build_asof_valuation, path=ledger)
    )
    trades = [_trade(_ms("2026-07-20"), a_got=[STAR], a_gave=[MID, DART])]
    with TestClient(server.app) as client:
        res = client.post(URL, json={"trades": trades})
        assert res.status_code == 200, res.text
        assert res.headers["cache-control"] == "no-store"
        body = res.json()
        assert body["available"] is True
        assert body["packageModel"]["id"] == "ktc_2026_04"
        assert body["trades"][0]["sides"][0]["available"] is True

        assert client.post(URL, json={"trades": "nope"}).status_code == 400
        too_many = [
            {"id": i, "createdAt": 1, "sides": []} for i in range(trade_history_asof.MAX_TRADES + 1)
        ]
        assert client.post(URL, json={"trades": too_many}).status_code == 400


# ── Public current-grade band ─────────────────────────────────────────


def _feed():
    return [
        {
            "createdAt": _ms("2026-07-20"),
            "sides": [
                {"receivedAssets": [STAR], "sentAssets": [MID, DART]},
                {"receivedAssets": [MID, DART], "sentAssets": [STAR]},
            ],
        }
    ]


TODAY = {"star": 8000.0, "mid": 5000.0, "dart": 400.0}


def _today(asset):
    return TODAY.get(asset.get("playerId"))


def test_current_band_is_the_shared_grade_at_todays_values():
    feed = _feed()
    activity._apply_current_grades(feed, _today)
    expected = trade_grading.grade_trade_sides(
        [([8000.0], [5000.0, 400.0]), ([5000.0, 400.0], [8000.0])]
    )
    assert [s["currentGrade"] for s in feed[0]["sides"]] == [e["grade"] for e in expected]


def test_current_band_fails_closed_on_an_asset_unpriced_today():
    feed = _feed()
    activity._apply_current_grades(
        feed, lambda a: None if a.get("playerId") == "dart" else _today(a)
    )
    for side in feed[0]["sides"]:
        band = side["currentGrade"]
        assert band["available"] is False
        assert band["grade"] is None
        assert band["reason"] == "unpriced_today"
        assert band["label"] == "Current value unavailable"


def test_current_band_carries_no_numbers_and_passes_the_public_guard():
    feed = _feed()
    activity._apply_current_grades(feed, _today)
    for side in feed[0]["sides"]:
        assert set(side["currentGrade"]) <= {"grade", "label", "color"}
        for value in side["currentGrade"].values():
            assert not isinstance(value, (int, float)) or isinstance(value, bool)
    public_contract.assert_public_payload_safe(feed)


def test_build_section_reads_the_current_resolver_off_the_factory(ledger):
    class Factory:
        def __init__(self):
            self.current_valuation = _today

        def __call__(self, requests):
            return build_asof_valuation(requests, path=ledger)

    from tests.public_league.test_activity_asof_grading import _season, _snapshot

    trade = {
        "transaction_id": "tx-1",
        "type": "trade",
        "status": "complete",
        "created": _ms("2026-07-20"),
        "roster_ids": [1, 2],
        "adds": {"star": 1, "mid": 2},
        "drops": {"star": 2, "mid": 1},
        "draft_picks": [],
    }
    section = activity.build_section(
        _snapshot(_season("L", 3, [trade])), valuation_factory=Factory()
    )
    for side in section["feed"][0]["sides"]:
        assert "grade" in side
        assert "currentGrade" in side
