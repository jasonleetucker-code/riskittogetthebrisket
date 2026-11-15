"""CW-10 follow-up: an unreadable FAAB config refuses the advisor and streaming routes.

Both routes consume ``find_waiver_targets`` bids, so they must answer the same
canonical 503 ``faab_config_invalid`` the other FAAB routes do (``server._faab_config_refusal``)
instead of quoting a bid from substituted defaults.  Missing is never $0.
"""

from __future__ import annotations

import json
import pathlib

import pytest

import server
from src.api import feature_flags
from src.trade import faab_engine as FE
from src.waivers import advisor, streaming
from tests.api.test_waiver_perfect_endpoint import AS, env  # noqa: F401 - fixture import

ROOT = pathlib.Path(__file__).resolve().parents[2]
ROUTES = ["/api/waiver/advisor", "/api/waiver/streaming"]


@pytest.fixture()
def flags_on(monkeypatch):
    real = feature_flags.is_enabled
    on = {"waiver_advisor", "idp_streaming"}
    monkeypatch.setattr(
        feature_flags, "is_enabled", lambda n, *a, **k: True if n in on else real(n, *a, **k)
    )


@pytest.fixture()
def broken_config(tmp_path, monkeypatch):
    shipped = json.loads((ROOT / "config" / "trade" / "faab.json").read_text(encoding="utf-8"))
    del shipped["market"]["rivalSigma"]
    path = tmp_path / "faab.json"
    path.write_text(json.dumps(shipped), encoding="utf-8")
    monkeypatch.setattr(FE, "_CONFIG_PATH", path)
    monkeypatch.setattr(FE, "_CONFIG_CACHE", None)


def _spy_inputs(monkeypatch):
    calls = []
    real = server._waiver_engine_inputs

    async def spy(*a, **k):
        calls.append(1)
        return await real(*a, **k)

    monkeypatch.setattr(server, "_waiver_engine_inputs", spy)
    return calls


@pytest.mark.parametrize("url", ROUTES)
def test_broken_faab_config_is_a_named_503_and_no_bid_work_runs(
    env,  # noqa: F811
    flags_on,
    broken_config,
    monkeypatch,
    url,
):
    def boom(*a, **k):
        raise AssertionError("composer must not run on a broken FAAB config")

    monkeypatch.setattr(advisor, "compute_waiver_advisor", boom)
    monkeypatch.setattr(streaming, "compute_streaming", boom)
    calls = _spy_inputs(monkeypatch)
    res = env.client.post(url, json={"leagueKey": "main", "teamOwnerId": "me"}, headers=AS)
    assert res.status_code == 503
    body = res.json()
    assert body["error"] == "faab_config_invalid"
    assert "market.rivalSigma" in body["message"]
    assert calls == []


def test_valid_config_leaves_advisor_response_unchanged(env, flags_on, monkeypatch):  # noqa: F811
    FE.load_faab_config(refresh=True)
    canned = {"contractVersion": "x", "candidates": [{"faab": {"recommendedBid": 7}}]}
    monkeypatch.setattr(advisor, "compute_waiver_advisor", lambda *a, **k: dict(canned))
    res = env.client.post(
        "/api/waiver/advisor", json={"leagueKey": "main", "teamOwnerId": "me"}, headers=AS
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["candidates"] == canned["candidates"]
    assert body["contractVersion"] == "x"


def test_valid_config_leaves_streaming_response_unchanged(env, flags_on, monkeypatch):  # noqa: F811
    FE.load_faab_config(refresh=True)
    canned = {"contractVersion": "y", "recommendMove": False, "noMoveReason": "below_materiality"}
    monkeypatch.setattr(streaming, "compute_streaming", lambda *a, **k: dict(canned))
    res = env.client.post(
        "/api/waiver/streaming", json={"leagueKey": "main", "teamOwnerId": "me"}, headers=AS
    )
    assert res.status_code == 200, res.text
    body = res.json()
    for key, value in canned.items():
        assert body[key] == value
