"""The ONE answer to "which client is this request from?" (B0-h, 2026-10-19).

Every rate limiter and throttle in this process keys on it, so it must be an
identity the client cannot choose.

nginx (``deploy/nginx/chaseupside-proxy.conf``) sets two headers with
different trust semantics:

* ``X-Real-IP $remote_addr`` — REPLACED: whatever the client sent is gone,
  the value is the TCP peer nginx saw;
* ``X-Forwarded-For $proxy_add_x_forwarded_for`` — APPENDED: only the LAST
  entry is the one our proxy wrote.

Both are statements made BY THE PROXY, so they are believed only when the
request actually came from the proxy.  Until this module the server trusted
``X-Real-IP`` from any peer, while the backend binds ``0.0.0.0``: a client
reaching ``:8000`` directly could name any address it liked and dissolve every
per-IP limit by rotating one header.  Now:

* proxy headers are honoured only when the TCP peer is loopback (nginx on the
  same box, the production topology) or listed in ``RATE_LIMIT_TRUSTED_PROXIES``
  (comma-separated; entries are IP addresses, CIDR networks, or a literal peer
  host such as Starlette TestClient's ``testclient``);
* a header value is parsed with :mod:`ipaddress`; an unparseable one is never
  used — the TCP peer is, never raw header text;
* an IPv4-mapped IPv6 address (``::ffff:203.0.113.7``) is reported as IPv4,
  so one client cannot hold two identities.

:func:`neighbourhood_key` / :func:`client_key` give the Trade Advisor limiter's
coarser keys (IPv6 ``/64`` per client, ``/24`` / ``/48`` per neighbourhood).
"""

from __future__ import annotations

import ipaddress
import os
from typing import Any

TRUSTED_PROXIES_ENV = "RATE_LIMIT_TRUSTED_PROXIES"


def _parse_ip(raw: Any) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def _trusted_entries() -> tuple[list[Any], set[str]]:
    """``(networks, literal_hosts)`` from the environment, read per call so a
    deploy-time change (or a test's ``monkeypatch.setenv``) applies at once."""
    nets: list[Any] = []
    literals: set[str] = set()
    for item in (os.getenv(TRUSTED_PROXIES_ENV) or "").split(","):
        entry = item.strip()
        if not entry:
            continue
        try:
            nets.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            literals.add(entry)
    return nets, literals


def peer_is_trusted_proxy(peer_host: str | None) -> bool:
    """Whether the TCP peer may make statements about the client."""
    host = str(peer_host or "").strip()
    if not host:
        return False
    nets, literals = _trusted_entries()
    if host in literals:
        return True
    addr = _parse_ip(host)
    if addr is None:
        return False
    if addr.is_loopback:
        return True
    return any(addr.version == n.version and addr in n for n in nets)


def _peer_host(request: Any) -> str:
    client = getattr(request, "client", None)
    return str(getattr(client, "host", "") or "") if client else ""


def client_ip_from_request(request: Any) -> str:
    """The client identity the rate limiters key on (see the module doc).

    Through a trusted proxy: ``X-Real-IP``, then the LAST ``X-Forwarded-For``
    entry, each only when it parses as an IP address.  Otherwise (or when
    neither parses) the TCP peer, normalised when it is an address.  ``""``
    when there is no peer at all.
    """
    peer = _peer_host(request)
    if peer_is_trusted_proxy(peer):
        headers = getattr(request, "headers", None) or {}
        real = _parse_ip(headers.get("x-real-ip", ""))
        if real is not None:
            return str(real)
        xff = headers.get("x-forwarded-for", "") or ""
        if xff:
            last = _parse_ip(xff.split(",")[-1])
            if last is not None:
                return str(last)
    addr = _parse_ip(peer)
    return str(addr) if addr is not None else peer


def client_key(ip: str) -> str:
    """Per-client limiter key: the IPv4 address, or the IPv6 ``/64`` (one
    subscriber is typically handed a whole /64).  Non-IP identities (a test
    client's literal host) are used as-is."""
    addr = _parse_ip(ip)
    if addr is None:
        return str(ip or "")
    if addr.version == 6:
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return str(addr)


def neighbourhood_key(ip: str) -> str:
    """Neighbourhood limiter key: IPv4 ``/24`` or IPv6 ``/48``."""
    addr = _parse_ip(ip)
    if addr is None:
        return str(ip or "")
    prefix = 48 if addr.version == 6 else 24
    return str(ipaddress.ip_network(f"{addr}/{prefix}", strict=False))
