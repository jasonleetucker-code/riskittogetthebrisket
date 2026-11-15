"""Route tests for ``POST /api/waiver/advisor`` error bodies.

The 503 for unreadable league settings carries a STABLE code; the exception
text stays in the server log, never in the response.
"""

from __future__ import annotations

import logging

import server
from src.api import feature_flags
from tests.api.test_waiver_perfect_endpoint import AS, env  # noqa: F401 - fixture import

URL = "/api/waiver/advisor"


def test_unreadable_league_settings_503_carries_no_exception_text(
    env,  # noqa: F811
    monkeypatch,
    caplog,
):
    real_is_enabled = feature_flags.is_enabled
    monkeypatch.setattr(
        feature_flags,
        "is_enabled",
        lambda name, *a, **k: True if name == "waiver_advisor" else real_is_enabled(name, *a, **k),
    )
    secret = "invalid literal for int() with base 10: 'SECRET-DETAIL'"

    async def broken_inputs(league_cfg, team_owner_id):
        return {"input_error": ValueError(secret)}

    monkeypatch.setattr(server, "_waiver_engine_inputs", broken_inputs)
    with caplog.at_level(logging.ERROR):
        res = env.client.post(URL, json={"leagueKey": "main", "teamOwnerId": "me"}, headers=AS)
    assert res.status_code == 503
    assert res.json() == {
        "error": "waiver_advisor_unavailable",
        "reason": "league_settings_unreadable",
        "leagueKey": "main",
    }
    assert "SECRET-DETAIL" not in res.text
    # ...but it is logged server-side.
    assert "SECRET-DETAIL" in caplog.text
