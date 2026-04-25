"""Tests for the shared HTTP fetch helper."""
from __future__ import annotations

import io
import urllib.error
from unittest.mock import patch

from src.utils import http_fetch as hf


def _fake_response(body=b"{}", status=200):
    class _R:
        def __init__(self):
            self.status = status
            self._body = body
        def read(self):
            return self._body
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
    return _R()


def test_successful_fetch_returns_ok():
    with patch.object(hf.urllib.request, "urlopen", return_value=_fake_response(b"hi")):
        result = hf.fetch("https://example.com", label="test")
    assert result.ok()
    assert result.body == b"hi"
    assert result.status_code == 200
    assert result.attempts == 1


def test_http_4xx_does_not_retry():
    def _raise(*_a, **_kw):
        raise urllib.error.HTTPError(
            "https://x", 404, "Not Found", {}, io.BytesIO(b"not found"),
        )
    with patch.object(hf.urllib.request, "urlopen", side_effect=_raise):
        result = hf.fetch("https://example.com", retries=3, label="t")
    # 404 is caller error; only ONE attempt.
    assert result.attempts == 1
    assert result.error_kind == "http"
    assert result.status_code == 404


def test_http_5xx_retries_until_exhausted():
    def _raise(*_a, **_kw):
        raise urllib.error.HTTPError(
            "https://x", 502, "Bad Gateway", {}, io.BytesIO(b""),
        )
    with patch.object(hf.urllib.request, "urlopen", side_effect=_raise):
        result = hf.fetch("https://example.com", retries=2, retry_delay_base=0, label="t")
    # 1 initial + 2 retries = 3.
    assert result.attempts == 3
    assert result.error_kind == "http"


def test_timeout_retries():
    def _raise(*_a, **_kw):
        raise TimeoutError("too slow")
    with patch.object(hf.urllib.request, "urlopen", side_effect=_raise):
        result = hf.fetch("https://example.com", retries=2, retry_delay_base=0)
    assert result.attempts == 3
    assert result.error_kind == "timeout"


def test_url_error_retries():
    def _raise(*_a, **_kw):
        raise urllib.error.URLError("connection refused")
    with patch.object(hf.urllib.request, "urlopen", side_effect=_raise):
        result = hf.fetch("https://example.com", retries=2, retry_delay_base=0)
    assert result.attempts == 3
    assert result.error_kind == "network"


def test_unexpected_exception_doesnt_crash():
    def _raise(*_a, **_kw):
        raise RuntimeError("boom")
    with patch.object(hf.urllib.request, "urlopen", side_effect=_raise):
        result = hf.fetch("https://example.com", retries=1, retry_delay_base=0)
    assert result.attempts == 2
    assert result.error_kind == "network"


def test_retry_delay_exponential(monkeypatch):
    sleeps = []
    monkeypatch.setattr(hf.time, "sleep", lambda s: sleeps.append(s))
    def _raise(*_a, **_kw):
        raise urllib.error.URLError("x")
    with patch.object(hf.urllib.request, "urlopen", side_effect=_raise):
        hf.fetch("https://example.com", retries=3, retry_delay_base=0.5)
    # 0.5, 1.0, 2.0 — exponential base × 2^attempt.
    assert sleeps == [0.5, 1.0, 2.0]


def test_ok_logs_structured_line(caplog):
    import logging
    with patch.object(hf.urllib.request, "urlopen", return_value=_fake_response(b"x")):
        with caplog.at_level(logging.INFO):
            hf.fetch("https://example.com", label="my_fetch")
    assert any("http_fetch=ok" in r.message for r in caplog.records)
    assert any("my_fetch" in r.message for r in caplog.records)


def test_elapsed_time_reasonable():
    with patch.object(hf.urllib.request, "urlopen", return_value=_fake_response(b"x")):
        result = hf.fetch("https://example.com")
    assert 0 <= result.elapsed_sec < 1.0


def test_circuit_breaker_short_circuits_when_open():
    """When the named breaker is open, no network call happens."""
    from src.utils import circuit_breaker as cb
    cb.reset_all_for_tests()
    bp = cb.get_or_create("test_external", failure_threshold=1, failure_window_sec=60)
    bp.report_failure("priming")  # trip it
    calls = []
    def _never(*_a, **_kw):
        calls.append(1)
        return _fake_response(b"shouldn't see this")
    with patch.object(hf.urllib.request, "urlopen", side_effect=_never):
        result = hf.fetch("https://example.com", breaker="test_external")
    assert result.error_kind == "circuit_open"
    assert result.attempts == 0
    assert calls == []
    cb.reset_all_for_tests()


def test_circuit_breaker_success_reports_to_breaker():
    from src.utils import circuit_breaker as cb
    cb.reset_all_for_tests()
    bp = cb.get_or_create("test_ext2", failure_threshold=2, failure_window_sec=60)
    with patch.object(hf.urllib.request, "urlopen", return_value=_fake_response(b"ok")):
        result = hf.fetch("https://example.com", breaker="test_ext2")
    assert result.ok()
    assert bp.snapshot()["counters"]["success"] >= 1
    cb.reset_all_for_tests()


def test_circuit_breaker_network_failures_trip_it():
    from src.utils import circuit_breaker as cb
    cb.reset_all_for_tests()
    bp = cb.get_or_create("test_ext3", failure_threshold=3, failure_window_sec=60)
    def _raise(*_a, **_kw):
        raise urllib.error.URLError("refused")
    with patch.object(hf.urllib.request, "urlopen", side_effect=_raise):
        for _ in range(3):
            hf.fetch("https://example.com", breaker="test_ext3", retry_delay_base=0)
    assert bp.snapshot()["state"] == "open"
    cb.reset_all_for_tests()
