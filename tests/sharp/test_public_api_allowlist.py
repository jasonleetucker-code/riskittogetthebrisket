from fastapi.testclient import TestClient

import server
from src.sharp import service


def test_sharp_routes_stay_private_and_market_request_injection_works(monkeypatch):
    assert not server._is_public_api_path("/api/sharp/cohort")
    assert not server._is_public_api_path("/api/sharp/market")
    assert not server._is_public_api_path("/api/sharp/market/audit")

    monkeypatch.setattr(server, "_is_authenticated", lambda _request: True)
    monkeypatch.setattr(
        service.sharp_market,
        "market_payload",
        lambda **_kwargs: {"status": "ok", "assets": []},
    )

    with TestClient(server.app, raise_server_exceptions=True) as client:
        market = client.get(
            "/api/sharp/market",
            params={
                "window": "30d",
                "platform": "all",
                "qualification": "all",
                "sort": "strength",
                "limit": "25",
            },
        )

    assert market.status_code == 200
    assert market.json() == {"status": "ok", "assets": []}
    assert "private" in (market.headers.get("Cache-Control") or "")
