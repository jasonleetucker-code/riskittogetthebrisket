from fastapi.testclient import TestClient

import server
from src.sharp import service


def test_aggregate_sharp_routes_are_public_but_audit_stays_private(monkeypatch):
    assert server._is_public_api_path("/api/sharp/cohort")
    assert server._is_public_api_path("/api/sharp/market")
    assert not server._is_public_api_path("/api/sharp/market/audit")

    monkeypatch.setattr(
        service,
        "cohort_status",
        lambda: {"status": "ok", "cohort": {"qualifiedManagers": 1}},
    )
    monkeypatch.setattr(
        service.sharp_market,
        "market_payload",
        lambda **_kwargs: {"status": "ok", "assets": []},
    )

    with TestClient(server.app, raise_server_exceptions=True) as client:
        cohort = client.get("/api/sharp/cohort")
        market = client.get("/api/sharp/market")
        audit = client.get("/api/sharp/market/audit?assetId=test")

    assert cohort.status_code == 200
    assert market.status_code == 200
    assert "public" in (market.headers.get("Cache-Control") or "")
    assert audit.status_code == 401
    assert audit.json().get("error") == "auth_required"
