import asyncio
import json
import unittest

import server


class _JsonRequest:
    def __init__(self, payload: dict | None = None, cookies: dict | None = None):
        self._payload = payload or {}
        self.cookies = cookies or {}

    async def json(self):
        return self._payload


class AuthAndDraftCapitalTests(unittest.TestCase):
    def test_auth_login_accepts_jason_alias(self):
        prev_configured = server.JASON_AUTH_CONFIGURED
        prev_password = server.JASON_LOGIN_PASSWORD
        prev_username = server.JASON_LOGIN_USERNAME
        prev_aliases = server.JASON_LOGIN_USERNAME_ALIASES
        prev_sessions = dict(server.auth_sessions)
        try:
            server.JASON_AUTH_CONFIGURED = True
            server.JASON_LOGIN_PASSWORD = "unit-secret"
            server.JASON_LOGIN_USERNAME = "jasonleetucker"
            server.JASON_LOGIN_USERNAME_ALIASES = ("jasonleetucker", "jason")
            response = asyncio.run(
                server.auth_login(
                    _JsonRequest(
                        {"username": "Jason", "password": "unit-secret", "next": "/app"}
                    )
                )
            )
            payload = json.loads(response.body.decode("utf-8"))

            self.assertEqual(response.status_code, 200)
            self.assertTrue(payload.get("ok"))
            self.assertEqual(payload.get("redirect"), "/app")
            self.assertIn(server.JASON_AUTH_COOKIE_NAME, response.headers.get("set-cookie", ""))
        finally:
            server.JASON_AUTH_CONFIGURED = prev_configured
            server.JASON_LOGIN_PASSWORD = prev_password
            server.JASON_LOGIN_USERNAME = prev_username
            server.JASON_LOGIN_USERNAME_ALIASES = prev_aliases
            server.auth_sessions.clear()
            server.auth_sessions.update(prev_sessions)

    def test_auth_login_reports_missing_password_configuration(self):
        prev_configured = server.JASON_AUTH_CONFIGURED
        prev_password = server.JASON_LOGIN_PASSWORD
        try:
            server.JASON_AUTH_CONFIGURED = False
            server.JASON_LOGIN_PASSWORD = ""
            response = asyncio.run(
                server.auth_login(
                    _JsonRequest({"username": "Jason", "password": "anything", "next": "/app"})
                )
            )
            payload = json.loads(response.body.decode("utf-8"))

            self.assertEqual(response.status_code, 503)
            self.assertFalse(payload.get("ok"))
            self.assertIn("not configured", str(payload.get("error") or "").lower())
        finally:
            server.JASON_AUTH_CONFIGURED = prev_configured
            server.JASON_LOGIN_PASSWORD = prev_password

    def test_draft_capital_route_returns_pick_details_summary(self):
        prev_latest_data = server.latest_data
        prev_latest_source = dict(server.latest_data_source)
        try:
            server.latest_data = {
                "sleeper": {
                    "leagueId": "league-123",
                    "leagueName": "Unit Test League",
                    "leagueSettings": {"draft_rounds": 4},
                    "teams": [
                        {
                            "name": "Jason",
                            "roster_id": 1,
                            "pickDetails": [
                                {
                                    "season": 2026,
                                    "round": 1,
                                    "fromRosterId": 1,
                                    "fromTeam": "Jason",
                                    "ownerRosterId": 1,
                                    "slot": 1,
                                    "label": "2026 1.01 (own)",
                                    "baseLabel": "2026 1.01",
                                },
                                {
                                    "season": 2026,
                                    "round": 2,
                                    "fromRosterId": 2,
                                    "fromTeam": "Other Team",
                                    "ownerRosterId": 1,
                                    "slot": 4,
                                    "label": "2026 2.04 (from Other Team)",
                                    "baseLabel": "2026 2.04",
                                },
                            ],
                        },
                        {
                            "name": "Other Team",
                            "roster_id": 2,
                            "pickDetails": [
                                {
                                    "season": 2027,
                                    "round": 1,
                                    "fromRosterId": 2,
                                    "fromTeam": "Other Team",
                                    "ownerRosterId": 2,
                                    "slot": None,
                                    "label": "2027 Early 1st (own)",
                                    "baseLabel": "2027 Early 1st",
                                }
                            ],
                        },
                    ],
                }
            }
            server.latest_data_source.update(
                {"loadedAt": "2026-03-20T20:00:00+00:00", "type": "unit-test"}
            )
            response = asyncio.run(server.get_draft_capital())
            payload = json.loads(response.body.decode("utf-8"))

            self.assertEqual(response.status_code, 200)
            self.assertTrue(payload.get("ok"))
            self.assertEqual(payload.get("league", {}).get("leagueId"), "league-123")
            self.assertEqual(payload.get("summary", {}).get("pickCount"), 3)

            jason_team = next(team for team in payload.get("teams", []) if team.get("name") == "Jason")
            self.assertEqual(jason_team.get("pickCount"), 2)
            self.assertEqual(jason_team.get("ownPickCount"), 1)
            self.assertEqual(jason_team.get("acquiredPickCount"), 1)
            self.assertEqual(jason_team.get("seasonSummaries", [])[0].get("roundCounts", {}).get("1"), 1)
            self.assertEqual(jason_team.get("seasonSummaries", [])[0].get("roundCounts", {}).get("2"), 1)

            season_2026 = next(item for item in payload.get("seasons", []) if item.get("season") == 2026)
            season_team = next(item for item in season_2026.get("teams", []) if item.get("team") == "Jason")
            self.assertEqual(season_team.get("total"), 2)
        finally:
            server.latest_data = prev_latest_data
            server.latest_data_source.clear()
            server.latest_data_source.update(prev_latest_source)

    def test_route_authority_lists_draft_capital_endpoint(self):
        original_cache = server._runtime_route_authority_cache
        original_cache_at = server._runtime_route_authority_cache_at
        try:
            server._runtime_route_authority_cache = None
            server._runtime_route_authority_cache_at = 0.0
            payload = server._runtime_route_authority_payload()
            routes = payload.get("routes") if isinstance(payload.get("routes"), dict) else {}
            self.assertIn("/api/draft-capital", routes)
            self.assertEqual(routes["/api/draft-capital"].get("handler"), "get_draft_capital")
            self.assertEqual(routes["/api/draft-capital"].get("access"), "public")
        finally:
            server._runtime_route_authority_cache = original_cache
            server._runtime_route_authority_cache_at = original_cache_at


if __name__ == "__main__":
    unittest.main()
