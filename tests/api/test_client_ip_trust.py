"""W22-F002 / V1-103 — the rate limiter keys on an identity the client cannot choose.

nginx (deploy/nginx/chaseupside-proxy.conf) sets two headers with different
trust semantics:

* ``X-Real-IP $remote_addr`` — REPLACED: whatever the client sent is gone,
  the value is the TCP peer nginx saw.
* ``X-Forwarded-For $proxy_add_x_forwarded_for`` — APPENDED: the client's
  own header survives in front, nginx adds the real address at the END.

Until 2026-08-25 ``server._client_ip_from_request`` took the FIRST
``X-Forwarded-For`` entry, so every public endpoint's rate limit keyed on
an attacker-chosen string — rotate one header value per request and the
limiter sees a new "client" every time.  These tests pin the repaired
trust order: X-Real-IP, then the LAST X-Forwarded-For entry, then the
socket peer.
"""

from __future__ import annotations

from starlette.requests import Request

import server


def _request(headers: dict[str, str] | None = None, client_host: str | None = "127.0.0.1"):
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/status",
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": (client_host, 12345) if client_host else None,
    }
    return Request(scope)


class TestProxiedRequests:
    def test_rotating_the_forwarded_for_header_does_not_change_the_key(self):
        """The defect, pinned: through nginx, the spoofable prefix of
        X-Forwarded-For must not move the limiter's key."""
        keys = set()
        for i in range(5):
            req = _request(
                {
                    "X-Real-IP": "203.0.113.7",
                    "X-Forwarded-For": f"junk-{i}, 203.0.113.7",
                }
            )
            keys.add(server._client_ip_from_request(req))
        assert keys == {"203.0.113.7"}, (
            "five requests differing only in the client-supplied X-Forwarded-For "
            f"prefix produced {len(keys)} distinct limiter keys: {sorted(keys)} — "
            "the limit is bypassable by rotating one header (W22-F002)"
        )

    def test_first_forwarded_entry_is_never_the_answer_when_a_proxy_appended(self):
        req = _request({"X-Forwarded-For": "attacker-chosen, 198.51.100.9"})
        assert server._client_ip_from_request(req) == "198.51.100.9"

    def test_real_ip_wins_over_everything(self):
        req = _request(
            {"X-Real-IP": "203.0.113.7", "X-Forwarded-For": "spoof-a, spoof-b"},
            client_host="10.0.0.1",
        )
        assert server._client_ip_from_request(req) == "203.0.113.7"


class TestDirectRequests:
    def test_no_headers_falls_back_to_the_socket_peer(self):
        req = _request({}, client_host="192.0.2.4")
        assert server._client_ip_from_request(req) == "192.0.2.4"

    def test_empty_header_values_fall_through(self):
        req = _request({"X-Real-IP": "  ", "X-Forwarded-For": ""}, client_host="192.0.2.4")
        assert server._client_ip_from_request(req) == "192.0.2.4"

    def test_no_client_and_no_headers_answers_empty_never_raises(self):
        req = _request({}, client_host=None)
        assert server._client_ip_from_request(req) == ""
