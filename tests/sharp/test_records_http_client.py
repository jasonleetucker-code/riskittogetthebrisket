from src.public_league import sleeper_client
from src.sharp import records


def test_records_default_client_bypasses_request_circuit_breaker(monkeypatch):
    captured = []

    def request_json(url):
        captured.append(url)
        return {"league_id": "L1"}

    monkeypatch.setattr(sleeper_client, "_request_json", request_json)

    result = records._default_http_get("https://api.sleeper.app/v1/league/L1")

    assert result == {"league_id": "L1"}
    assert captured == ["https://api.sleeper.app/v1/league/L1"]
