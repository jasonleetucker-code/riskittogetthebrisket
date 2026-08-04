from types import SimpleNamespace

from fastapi import FastAPI

from src.sharp import service


def test_cohort_status_self_heals_missing_market_routes(monkeypatch):
    app = FastAPI()
    monkeypatch.delitem(service.sys.modules, "server", raising=False)
    monkeypatch.setitem(service.sys.modules, "__main__", SimpleNamespace(app=app))

    monkeypatch.setattr(service.ledger, "coverage", lambda: {})
    monkeypatch.setattr(
        service.platform_ledger,
        "platform_coverage",
        lambda: {"sleeper": {}, "ffpc": {}},
    )
    monkeypatch.setattr(service.discovery, "graph_stats", lambda: {})
    monkeypatch.setattr(service, "load_manager_records", lambda: [])
    monkeypatch.setattr(service, "_records_coverage", lambda: {})
    monkeypatch.setattr(service.sharp_market, "load_ffpc_config", lambda: {})
    monkeypatch.setattr(service.sharp_market, "provisional_members", lambda _config: [])

    payload = service.cohort_status()

    paths = [getattr(route, "path", None) for route in app.routes]
    assert payload["status"] == service.STATUS_BUILDING
    assert paths.count("/api/sharp/market") == 1
    assert paths.count("/api/sharp/market/audit") == 1
