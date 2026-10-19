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

B0-h (2026-10-19): both headers are statements BY THE PROXY, so they are
believed only from a trusted peer (loopback, or ``RATE_LIMIT_TRUSTED_PROXIES``)
and only when they parse as an address — the backend binds 0.0.0.0, and a
client reaching it directly could otherwise name any address it liked.  The
owner is ``src/api/client_ip.py``; ``server._client_ip_from_request``
delegates to it.
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

    def test_real_ip_wins_over_everything(self, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXIES", "10.0.0.0/8")
        req = _request(
            {"X-Real-IP": "203.0.113.7", "X-Forwarded-For": "spoof-a, spoof-b"},
            client_host="10.0.0.1",
        )
        assert server._client_ip_from_request(req) == "203.0.113.7"


class TestUntrustedPeers:
    """B0-h: a peer that is not our proxy cannot choose its identity."""

    def test_real_ip_from_an_untrusted_peer_is_ignored(self, monkeypatch):
        monkeypatch.delenv("RATE_LIMIT_TRUSTED_PROXIES", raising=False)
        keys = {
            server._client_ip_from_request(
                _request({"X-Real-IP": f"198.51.100.{i}"}, client_host="192.0.2.50")
            )
            for i in range(5)
        }
        assert keys == {"192.0.2.50"}

    def test_forwarded_for_from_an_untrusted_peer_is_ignored(self, monkeypatch):
        monkeypatch.delenv("RATE_LIMIT_TRUSTED_PROXIES", raising=False)
        req = _request({"X-Forwarded-For": "a, 198.51.100.9"}, client_host="192.0.2.50")
        assert server._client_ip_from_request(req) == "192.0.2.50"

    def test_a_listed_cidr_is_trusted(self, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXIES", "192.0.2.0/24, 2001:db8::/32")
        req = _request({"X-Real-IP": "203.0.113.7"}, client_host="192.0.2.50")
        assert server._client_ip_from_request(req) == "203.0.113.7"

    def test_unparseable_header_text_is_never_the_key(self):
        req = _request({"X-Real-IP": "not-an-ip", "X-Forwarded-For": "also bad"})
        # Loopback peer (trusted), but neither header parses: the peer wins.
        assert server._client_ip_from_request(req) == "127.0.0.1"

    def test_ipv4_mapped_ipv6_collapses_to_ipv4(self):
        req = _request({"X-Real-IP": "::ffff:203.0.113.7"})
        assert server._client_ip_from_request(req) == "203.0.113.7"
        req = _request({}, client_host="::ffff:192.0.2.4")
        assert server._client_ip_from_request(req) == "192.0.2.4"

    def test_ipv6_loopback_peer_is_trusted(self):
        req = _request({"X-Real-IP": "2001:db8::1"}, client_host="::1")
        assert server._client_ip_from_request(req) == "2001:db8::1"


def test_limiter_keys_group_ipv6_by_slash_64_and_neighbourhoods():
    from src.api.client_ip import client_key, neighbourhood_key

    assert client_key("2001:db8:1:2::1") == client_key("2001:db8:1:2:ffff::9")
    assert client_key("2001:db8:1:2::1") != client_key("2001:db8:1:3::1")
    assert client_key("203.0.113.7") == "203.0.113.7"
    assert neighbourhood_key("203.0.113.7") == neighbourhood_key("203.0.113.200")
    assert neighbourhood_key("203.0.113.7") != neighbourhood_key("203.0.114.7")
    assert neighbourhood_key("2001:db8:1:2::1") == neighbourhood_key("2001:db8:1:ffff::1")


def test_region_key_groups_ipv4_slash_16_and_ipv6_slash_32():
    from src.api.client_ip import region_key

    assert region_key("203.0.113.7") == region_key("203.0.200.1")
    assert region_key("203.0.113.7") != region_key("203.1.113.7")
    assert region_key("2001:db8:1::1") == region_key("2001:db8:ffff::1")
    assert region_key("2001:db8::1") != region_key("2001:db9::1")


def test_every_client_ip_reader_routes_through_the_one_owner():
    """No module reads X-Real-IP / X-Forwarded-For except the owner."""
    import pathlib

    repo = pathlib.Path(server.__file__).parent
    readers = []
    for path in [*(repo / "src").rglob("*.py"), repo / "server.py"]:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if 'headers.get("x-real-ip"' in text or 'headers.get("x-forwarded-for"' in text:
            readers.append(path.relative_to(repo).as_posix())
    assert readers == ["src/api/client_ip.py"], readers


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
