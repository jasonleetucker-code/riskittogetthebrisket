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


def test_registration_survives_being_imported_before_the_app_exists(monkeypatch):
    """The import-order trap, pinned.

    ``src/sharp/service.py`` registers its routes as an import-time side
    effect. When anything imports it BEFORE the app exists — a test
    module, a script, another package — that call finds no app and
    returns, and Python's module cache means importing it again later
    re-runs nothing. The routes then never attach and every
    ``/api/sharp/market`` request 404s.

    ``server.py`` therefore calls the public entry point explicitly
    after importing the module. This reproduces the bad ordering and
    asserts that the explicit call still fixes it.
    """
    # 1. Module imported while no app exists anywhere — the side effect
    #    is a no-op, exactly as on a cold import from a test module.
    monkeypatch.delitem(service.sys.modules, "server", raising=False)
    monkeypatch.delitem(service.sys.modules, "__main__", raising=False)
    service._register_http_routes()

    # 2. The app comes into existence afterwards.
    app = FastAPI()
    monkeypatch.setitem(service.sys.modules, "server", SimpleNamespace(app=app))
    assert "/api/sharp/market" not in [getattr(r, "path", None) for r in app.routes]

    # 3. The explicit call server.py makes attaches them.
    service.register_http_routes()

    paths = [getattr(route, "path", None) for route in app.routes]
    assert paths.count("/api/sharp/market") == 1
    assert paths.count("/api/sharp/market/audit") == 1


def test_server_calls_the_public_registrar_after_importing_the_service():
    """A source guard, because the failure is silent at runtime.

    Nothing in a normal request path reveals that the routes were never
    attached — the endpoint simply 404s, which reads as "not deployed
    yet". If this line is ever removed, the ordering bug returns.
    """
    from pathlib import Path

    source = Path(__file__).resolve().parents[2] / "server.py"
    text = source.read_text(encoding="utf-8")
    assert "_sharp_service.register_http_routes()" in text
