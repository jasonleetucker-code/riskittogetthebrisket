from types import SimpleNamespace

from fastapi import FastAPI

from src.sharp import service


def test_market_routes_register_when_server_executes_as_main(monkeypatch):
    app = FastAPI()
    monkeypatch.delitem(service.sys.modules, "server", raising=False)
    monkeypatch.setitem(service.sys.modules, "__main__", SimpleNamespace(app=app))

    service._register_http_routes()
    service._register_http_routes()

    paths = [getattr(route, "path", None) for route in app.routes]
    assert paths.count("/api/sharp/market") == 1
    assert paths.count("/api/sharp/market/audit") == 1
