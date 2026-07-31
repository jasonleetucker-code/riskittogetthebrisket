from pathlib import Path

import pytest

from src.platforms.ffpc.client import (
    FFPCClientError,
    PublicFFPCClient,
    RequestBudgetExhausted,
)


class Response:
    def __init__(
        self,
        *,
        url="https://myffpc.com/public/league",
        status=200,
        text="ok",
        location=None,
    ):
        self.url = url
        self.status_code = status
        self.text = text
        self.headers = {
            "Content-Type": "text/html",
            "ETag": '"v1"',
            "Last-Modified": "Wed, 01 Jul 2026 00:00:00 GMT",
        }
        if location:
            self.headers["Location"] = location

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def test_client_is_get_only_cached_and_sends_no_credentials(tmp_path):
    session = Session([Response(text="<html>public</html>")])
    client = PublicFFPCClient(
        cache_dir=tmp_path,
        request_budget=1,
        cache_hours=12,
        session=session,
        sleep_fn=lambda _seconds: None,
    )
    first = client.fetch("https://myffpc.com/public/league")
    second = client.fetch("https://myffpc.com/public/league")
    assert first.from_cache is False
    assert second.from_cache is True
    assert len(session.calls) == 1
    headers = session.calls[0][1]["headers"]
    assert "Authorization" not in headers
    assert "Cookie" not in headers
    assert Path(first.cache_path).exists()


def test_client_rejects_non_allowlisted_or_credentialed_urls(tmp_path):
    client = PublicFFPCClient(cache_dir=tmp_path, request_budget=0)
    with pytest.raises(FFPCClientError):
        client.fetch("https://example.com/public")
    with pytest.raises(FFPCClientError):
        client.fetch("https://user:password@myffpc.com/public")


def test_request_budget_is_hard(tmp_path):
    client = PublicFFPCClient(cache_dir=tmp_path, request_budget=0)
    with pytest.raises(RequestBudgetExhausted):
        client.fetch("https://myffpc.com/public/league")


def test_redirect_is_validated_before_second_request(tmp_path):
    session = Session(
        [
            Response(status=302, location="https://example.com/private"),
        ]
    )
    client = PublicFFPCClient(
        cache_dir=tmp_path,
        request_budget=2,
        retry_limit=0,
        session=session,
        sleep_fn=lambda _seconds: None,
    )
    with pytest.raises(FFPCClientError):
        client.fetch("https://myffpc.com/public/league")
    assert len(session.calls) == 1


def test_allowlisted_redirect_consumes_budget_and_stays_get_only(tmp_path):
    session = Session(
        [
            Response(
                status=302,
                location="https://www.myffpc.com/public/league",
            ),
            Response(
                url="https://www.myffpc.com/public/league",
                text="redirected",
            ),
        ]
    )
    client = PublicFFPCClient(
        cache_dir=tmp_path,
        request_budget=2,
        retry_limit=0,
        session=session,
        sleep_fn=lambda _seconds: None,
    )
    result = client.fetch("https://myffpc.com/public/league")
    assert result.content == "redirected"
    assert client.calls_used == 2
    assert all(call[1]["allow_redirects"] is False for call in session.calls)
