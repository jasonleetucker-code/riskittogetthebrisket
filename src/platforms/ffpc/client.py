"""Conservative, read-only HTTP client for configured FFPC public pages.

No cookies, credentials, session replay, identifier enumeration, or write
methods are supported. Callers must provide exact public URLs in config.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse

import requests

DEFAULT_ALLOWED_HOSTS = ("myffpc.com", "www.myffpc.com")
DEFAULT_USER_AGENT = (
    "ChaseUpside-FFPC-Public-Reader/1.0 "
    "(read-only; configured public pages; contact repository owner)"
)
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_MAX_REDIRECTS = 3


class FFPCClientError(RuntimeError):
    """A configured public-page request failed safely."""


class RequestBudgetExhausted(FFPCClientError):
    """The hard per-run request budget has been consumed."""


@dataclass(frozen=True)
class FetchResult:
    url: str
    content: str
    fetched_ms: int
    status_code: int
    content_type: str | None
    etag: str | None
    last_modified: str | None
    from_cache: bool
    cache_path: Path


class PublicFFPCClient:
    def __init__(
        self,
        *,
        cache_dir: Path,
        request_budget: int = 100,
        sleep_seconds: float = 1.5,
        cache_hours: float = 12.0,
        timeout_seconds: float = 20.0,
        retry_limit: int = 2,
        allowed_hosts: tuple[str, ...] = DEFAULT_ALLOWED_HOSTS,
        user_agent: str = DEFAULT_USER_AGENT,
        session: requests.Session | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.remaining = max(0, int(request_budget))
        self.sleep_seconds = max(0.0, float(sleep_seconds))
        self.cache_ms = max(0, int(float(cache_hours) * 3600 * 1000))
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.retry_limit = max(0, int(retry_limit))
        self.allowed_hosts = {host.lower() for host in allowed_hosts}
        self.user_agent = user_agent
        self.session = session or requests.Session()
        # The adapter never sends Cookie or Authorization headers. The
        # cookie jar is cleared before and after every request because a
        # requests.Session would otherwise replay a public site's cookie.
        self.session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/json",
            }
        )
        self.sleep_fn = sleep_fn
        self.calls_used = 0

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(str(url))
        if parsed.scheme != "https":
            raise FFPCClientError("FFPC public URLs must use https")
        host = (parsed.hostname or "").lower()
        if host not in self.allowed_hosts:
            raise FFPCClientError(f"FFPC host is not allow-listed: {host!r}")
        if parsed.username or parsed.password:
            raise FFPCClientError("credentials in FFPC URLs are forbidden")

    def _paths(self, url: str) -> tuple[Path, Path]:
        digest = hashlib.sha256(url.encode()).hexdigest()
        return self.cache_dir / f"{digest}.body", self.cache_dir / f"{digest}.json"

    @staticmethod
    def _read_meta(path: Path) -> dict:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _consume_budget(self) -> None:
        if self.remaining <= 0:
            raise RequestBudgetExhausted("FFPC request budget exhausted")
        if self.calls_used > 0 and self.sleep_seconds:
            self.sleep_fn(self.sleep_seconds)
        self.remaining -= 1
        self.calls_used += 1

    def _clear_cookies(self) -> None:
        jar = getattr(self.session, "cookies", None)
        if jar is not None:
            try:
                jar.clear()
            except (AttributeError, KeyError):
                pass

    def _get_with_safe_redirects(
        self,
        url: str,
        *,
        headers: dict[str, str],
    ) -> requests.Response:
        current = url
        for redirect_count in range(_MAX_REDIRECTS + 1):
            self._validate_url(current)
            self._consume_budget()
            self._clear_cookies()
            response = self.session.get(
                current,
                headers=headers,
                timeout=self.timeout_seconds,
                allow_redirects=False,
            )
            self._clear_cookies()
            if response.status_code not in _REDIRECT_STATUSES:
                return response
            location = str(response.headers.get("Location") or "").strip()
            if not location:
                raise FFPCClientError("FFPC redirect omitted Location")
            if redirect_count >= _MAX_REDIRECTS:
                raise FFPCClientError("FFPC redirect limit exceeded")
            # Validate before issuing the redirected request. This avoids
            # following a configured FFPC URL onto an unapproved host.
            next_url = urljoin(current, location)
            self._validate_url(next_url)
            current = next_url
        raise FFPCClientError("FFPC redirect limit exceeded")

    def fetch(self, url: str, *, force_refresh: bool = False) -> FetchResult:
        self._validate_url(url)
        body_path, meta_path = self._paths(url)
        meta = self._read_meta(meta_path)
        now = int(time.time() * 1000)
        fetched_ms = int(meta.get("fetchedMs") or 0)
        cache_fresh = fetched_ms and now - fetched_ms <= self.cache_ms
        if not force_refresh and body_path.exists() and cache_fresh:
            return FetchResult(
                url=url,
                content=body_path.read_text(encoding="utf-8", errors="replace"),
                fetched_ms=fetched_ms,
                status_code=int(meta.get("statusCode") or 200),
                content_type=meta.get("contentType"),
                etag=meta.get("etag"),
                last_modified=meta.get("lastModified"),
                from_cache=True,
                cache_path=body_path,
            )

        headers: dict[str, str] = {}
        if meta.get("etag"):
            headers["If-None-Match"] = str(meta["etag"])
        if meta.get("lastModified"):
            headers["If-Modified-Since"] = str(meta["lastModified"])

        last_error: Exception | None = None
        for attempt in range(self.retry_limit + 1):
            try:
                response = self._get_with_safe_redirects(url, headers=headers)
                if response.status_code == 304 and body_path.exists():
                    meta["fetchedMs"] = now
                    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
                    return FetchResult(
                        url=url,
                        content=body_path.read_text(
                            encoding="utf-8",
                            errors="replace",
                        ),
                        fetched_ms=now,
                        status_code=304,
                        content_type=meta.get("contentType"),
                        etag=meta.get("etag"),
                        last_modified=meta.get("lastModified"),
                        from_cache=True,
                        cache_path=body_path,
                    )
                if response.status_code in (429, 500, 502, 503, 504):
                    raise FFPCClientError(
                        f"FFPC returned HTTP {response.status_code}"
                    )
                response.raise_for_status()
                content = response.text
                body_path.write_text(content, encoding="utf-8")
                saved = {
                    "url": url,
                    "finalUrl": response.url,
                    "fetchedMs": now,
                    "statusCode": response.status_code,
                    "contentType": response.headers.get("Content-Type"),
                    "etag": response.headers.get("ETag"),
                    "lastModified": response.headers.get("Last-Modified"),
                }
                meta_path.write_text(json.dumps(saved, indent=2), encoding="utf-8")
                return FetchResult(
                    url=url,
                    content=content,
                    fetched_ms=now,
                    status_code=response.status_code,
                    content_type=saved["contentType"],
                    etag=saved["etag"],
                    last_modified=saved["lastModified"],
                    from_cache=False,
                    cache_path=body_path,
                )
            except RequestBudgetExhausted:
                raise
            except (requests.RequestException, FFPCClientError) as exc:
                last_error = exc
                if attempt >= self.retry_limit:
                    break
                self.sleep_fn(min(30.0, 2.0**attempt))
        raise FFPCClientError(
            f"FFPC fetch failed for configured URL: {last_error}"
        )
