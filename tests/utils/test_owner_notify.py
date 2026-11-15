"""The shared owner push path (``NOTIFY_WEBHOOK_URL``, same as the uptime probe)."""

from __future__ import annotations

import pytest

from src.utils import owner_notify as N


class Recorder:
    def __init__(self, status=200, exc=None):
        self.calls, self.status, self.exc = [], status, exc

    def __call__(self, url, title, body, timeout):
        self.calls.append((url, title, body, timeout))
        if self.exc:
            raise self.exc
        return self.status


def test_unset_means_nothing_is_contacted(monkeypatch):
    monkeypatch.delenv(N.WEBHOOK_ENV, raising=False)
    rec = Recorder()
    assert N.webhook_url() is None and N.channel(transport=rec) is None
    assert N.send("t", "b", transport=rec) is False
    assert rec.calls == []


def test_posts_plain_text_with_title_to_the_configured_topic(monkeypatch):
    monkeypatch.setenv(N.WEBHOOK_ENV, "https://ntfy.example/private-topic")
    rec = Recorder()
    assert N.channel(transport=rec)("Subject", "Body") is True
    url, title, body, timeout = rec.calls[0]
    assert url == "https://ntfy.example/private-topic" and title == "Subject"
    assert body == "Subject\n\nBody" and timeout <= N.DEFAULT_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "rec",
    [
        Recorder(status=500),
        Recorder(status=403),
        Recorder(exc=TimeoutError()),
        Recorder(exc=OSError()),
    ],
)
def test_an_unavailable_webhook_returns_false_and_never_raises(monkeypatch, rec):
    monkeypatch.setenv(N.WEBHOOK_ENV, "https://ntfy.example/t")
    assert N.send("t", "b", transport=rec) is False


@pytest.mark.parametrize(
    ("url", "ok"),
    [("http://ntfy.example/t", False), ("ftp://x/t", False), ("http://127.0.0.1:8080/t", True)],
)
def test_only_https_or_loopback(monkeypatch, url, ok):
    monkeypatch.setenv(N.WEBHOOK_ENV, url)
    assert (N.webhook_url() is not None) is ok
