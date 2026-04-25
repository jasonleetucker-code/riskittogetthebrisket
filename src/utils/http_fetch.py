"""Shared HTTP fetch helper with timeout + retry + structured logging.

Centralizes the retry / timeout / user-agent / error-logging
boilerplate that was duplicated across every scraper, Sleeper
call, and ESPN call.  Every call through this helper produces a
structured log line that `grep http_fetch=` can triage.

Design
------
* Default: 1 retry on transient errors (network / 5xx), 10s timeout.
* Exponential backoff: 0.5s, 1.0s, 2.0s between retries.
* Never raises to the caller — returns (status_code, body_bytes,
  error_kind).  ``error_kind`` is one of: ``"ok"``, ``"http"``,
  ``"network"``, ``"timeout"``, ``"parse"``, ``"retries_exhausted"``.

Callers opt IN to retry; a safe default is "no retry, just log and
return on failure" — preserves existing behavior across the
codebase where retry would be a surprising change.
"""
from __future__ import annotations

import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchResult:
    status_code: int
    body: bytes
    error_kind: str  # "ok" | "http" | "network" | "timeout" | "retries_exhausted"
    attempts: int
    elapsed_sec: float

    def ok(self) -> bool:
        return self.error_kind == "ok"


def fetch(
    url: str,
    *,
    timeout: float = 10.0,
    retries: int = 0,
    user_agent: str = "brisket-fetch/1.0",
    extra_headers: dict[str, str] | None = None,
    retry_delay_base: float = 0.5,
    label: str | None = None,
    breaker: str | None = None,
) -> FetchResult:
    """Fetch a URL with optional retry.  Never raises.

    ``label`` tags log lines for filtering — pass the logical
    purpose (e.g. ``"sleeper_rosters"``, ``"espn_injuries"``).

    ``breaker`` names a circuit breaker.  When provided:
      * If the named breaker is OPEN, returns immediately with
        ``error_kind="circuit_open"`` — no network call.
      * Successful calls close/keep-closed the breaker.
      * Failed calls (network / timeout / unexpected) count
        toward the breaker's trip threshold.
    """
    headers = {"User-Agent": user_agent}
    if extra_headers:
        headers.update(extra_headers)
    started = time.time()

    # Pre-check the circuit breaker.
    bp = None
    if breaker:
        from src.utils import circuit_breaker as _cb
        bp = _cb.get_or_create(breaker)
        if not bp.can_call():
            _LOGGER.warning(
                "http_fetch=circuit_open label=%s breaker=%s url=%s",
                label or "unlabeled", breaker, _truncate(url),
            )
            return FetchResult(
                status_code=0, body=b"",
                error_kind="circuit_open",
                attempts=0, elapsed_sec=0.0,
            )

    last_error_kind = "retries_exhausted"
    last_status = 0
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                status = getattr(resp, "status", 200)
            elapsed = time.time() - started
            _LOGGER.info(
                "http_fetch=ok label=%s url=%s status=%d bytes=%d attempts=%d elapsed=%.3fs",
                label or "unlabeled", _truncate(url), status, len(body),
                attempt + 1, elapsed,
            )
            if bp is not None:
                bp.report_success()
            return FetchResult(
                status_code=status, body=body, error_kind="ok",
                attempts=attempt + 1, elapsed_sec=elapsed,
            )
        except urllib.error.HTTPError as exc:
            last_status = getattr(exc, "code", 0)
            last_error_kind = "http"
            try:
                body = exc.read()
            except Exception:  # noqa: BLE001
                body = b""
            # Don't retry on 4xx — caller's fault (likely); do retry on 5xx.
            if 500 <= last_status < 600 and attempt < retries:
                _LOGGER.warning(
                    "http_fetch=retry label=%s url=%s status=%d attempt=%d",
                    label or "unlabeled", _truncate(url), last_status, attempt + 1,
                )
                time.sleep(retry_delay_base * (2 ** attempt))
                continue
            elapsed = time.time() - started
            _LOGGER.warning(
                "http_fetch=http label=%s url=%s status=%d attempts=%d elapsed=%.3fs",
                label or "unlabeled", _truncate(url), last_status,
                attempt + 1, elapsed,
            )
            return FetchResult(
                status_code=last_status, body=body, error_kind="http",
                attempts=attempt + 1, elapsed_sec=elapsed,
            )
        except (TimeoutError,) as exc:
            last_error_kind = "timeout"
            if attempt < retries:
                _LOGGER.warning(
                    "http_fetch=retry label=%s url=%s kind=timeout attempt=%d",
                    label or "unlabeled", _truncate(url), attempt + 1,
                )
                time.sleep(retry_delay_base * (2 ** attempt))
                continue
        except urllib.error.URLError as exc:
            last_error_kind = "network"
            if attempt < retries:
                _LOGGER.warning(
                    "http_fetch=retry label=%s url=%s kind=network err=%r attempt=%d",
                    label or "unlabeled", _truncate(url), exc, attempt + 1,
                )
                time.sleep(retry_delay_base * (2 ** attempt))
                continue
        except Exception as exc:  # noqa: BLE001 — catch everything; never raise
            last_error_kind = "network"
            if attempt < retries:
                _LOGGER.warning(
                    "http_fetch=retry label=%s url=%s kind=unexpected err=%r attempt=%d",
                    label or "unlabeled", _truncate(url), exc, attempt + 1,
                )
                time.sleep(retry_delay_base * (2 ** attempt))
                continue
    elapsed = time.time() - started
    _LOGGER.warning(
        "http_fetch=%s label=%s url=%s attempts=%d elapsed=%.3fs",
        last_error_kind, label or "unlabeled", _truncate(url),
        retries + 1, elapsed,
    )
    # Report terminal failure to the breaker (network/timeout errors
    # only — HTTP errors reported above inside the 5xx branch when
    # retries are exhausted).
    if bp is not None and last_error_kind in ("timeout", "network", "retries_exhausted"):
        bp.report_failure(last_error_kind)
    return FetchResult(
        status_code=last_status, body=b"",
        error_kind=last_error_kind,
        attempts=retries + 1, elapsed_sec=elapsed,
    )


def _truncate(s: str, limit: int = 120) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + "..."
