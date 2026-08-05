from types import SimpleNamespace

from fastapi import FastAPI

from src.sharp import curated_service


def test_curated_sharp_routes_register_once(monkeypatch):
    app = FastAPI()
    monkeypatch.delitem(curated_service.sys.modules, "server", raising=False)
    monkeypatch.setitem(curated_service.sys.modules, "__main__", SimpleNamespace(app=app))
    curated_service._register_http_routes()
    curated_service._register_http_routes()
    paths = [getattr(route, "path", None) for route in app.routes]
    for expected in (
        "/api/sharp/people",
        "/api/sharp/people/{person_id}",
        "/api/sharp/review",
        "/api/sharp/review/{candidate_id}",
        "/api/sharp/curated/summary",
        "/api/sharp/curated/refresh",
    ):
        assert paths.count(expected) == 1
