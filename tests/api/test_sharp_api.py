from src.sharp import service

import server


def test_sharp_api_routes_are_registered_once():
    service._register_http_routes()
    service._register_http_routes()

    paths = [getattr(route, "path", "") for route in server.app.routes]
    required = {
        "/api/sharp/cohort",
        "/api/sharp/market",
        "/api/sharp/market/audit",
        "/api/sharp/people",
        "/api/sharp/curated/summary",
        "/api/sharp/review",
    }
    assert required.issubset(set(paths))
    for path in required:
        assert paths.count(path) == 1
