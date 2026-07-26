"""``fetch.fetch_url`` behavior with a fake session — download,
stale-cache degradation for failures at request start AND mid-stream,
304 handling, and 404.  No network."""

from __future__ import annotations

import json

import pytest
import requests

from src.playerctx import fetch as fetch_mod
from src.playerctx.fetch import FetchResult, fetch_url


class _FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        chunks: list[bytes] | None = None,
        stream_exc: Exception | None = None,
        headers: dict | None = None,
    ):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks or []
        self._stream_exc = stream_exc
        self.closed = False

    def iter_content(self, chunk_size: int):
        yield from self._chunks
        if self._stream_exc is not None:
            raise self._stream_exc

    def close(self):
        self.closed = True


class _FakeSession:
    def __init__(self, response=None, request_exc: Exception | None = None):
        self._response = response
        self._request_exc = request_exc
        self.calls: list[dict] = []

    def get(self, url, headers=None, timeout=None, stream=None):
        self.calls.append({"url": url, "headers": headers})
        if self._request_exc is not None:
            raise self._request_exc
        return self._response


class TestDownload:
    def test_streams_to_dest_and_writes_meta(self, tmp_path):
        dest = tmp_path / "data.csv"
        session = _FakeSession(
            _FakeResponse(chunks=[b"abc", b"def"], headers={"ETag": '"e1"', "Last-Modified": "lm"})
        )
        res = fetch_url("https://x.invalid/d", dest, key="d", session=session)
        assert res.status == "downloaded"
        assert dest.read_bytes() == b"abcdef"
        meta = json.loads((tmp_path / "data.csv.meta.json").read_text())
        assert meta["etag"] == '"e1"'
        assert meta["size"] == 6
        assert list(tmp_path.glob("*.tmp-*")) == []

    def test_not_modified_touches_and_keeps_content(self, tmp_path):
        dest = tmp_path / "data.csv"
        dest.write_bytes(b"cached")
        session = _FakeSession(_FakeResponse(status_code=304))
        res = fetch_url("https://x.invalid/d", dest, key="d", max_age_hours=0.0, session=session)
        assert res.status == "not-modified"
        assert dest.read_bytes() == b"cached"

    def test_404_is_missing(self, tmp_path):
        session = _FakeSession(_FakeResponse(status_code=404))
        res = fetch_url("https://x.invalid/d", tmp_path / "d.csv", key="d", session=session)
        assert res == FetchResult(key="d", path=None, status="missing", detail="404")


class TestStaleCacheDegradation:
    def test_request_start_failure_keeps_stale_copy(self, tmp_path):
        dest = tmp_path / "data.csv"
        dest.write_bytes(b"stale")
        session = _FakeSession(request_exc=requests.ConnectionError("refused"))
        res = fetch_url("https://x.invalid/d", dest, key="d", max_age_hours=0.0, session=session)
        assert res.status == "error"
        assert res.path == dest
        assert dest.read_bytes() == b"stale"

    def test_mid_stream_failure_keeps_stale_copy(self, tmp_path):
        # Regression (Codex round 1, finding 2 on PR #539): a
        # connection reset DURING iter_content — realistic on the
        # 35-55 MB depth-chart file — previously escaped the stale-
        # cache fallback and failed the whole refresh.
        dest = tmp_path / "depth.csv"
        dest.write_bytes(b"stale-but-usable")
        session = _FakeSession(
            _FakeResponse(chunks=[b"partial"], stream_exc=requests.ConnectionError("reset"))
        )
        res = fetch_url("https://x.invalid/d", dest, key="d", max_age_hours=0.0, session=session)
        assert res.status == "error"
        assert "stream" in res.detail
        assert res.path == dest
        assert dest.read_bytes() == b"stale-but-usable"  # not clobbered by the partial
        assert list(tmp_path.glob("*.tmp-*")) == []  # temp cleaned up

    def test_mid_stream_failure_without_cache_returns_none(self, tmp_path):
        dest = tmp_path / "depth.csv"
        session = _FakeSession(
            _FakeResponse(chunks=[b"partial"], stream_exc=requests.ConnectionError("reset"))
        )
        res = fetch_url("https://x.invalid/d", dest, key="d", session=session)
        assert res.status == "error"
        assert res.path is None
        assert not dest.exists()
        assert list(tmp_path.glob("*.tmp-*")) == []

    def test_non_request_exception_still_propagates(self, tmp_path):
        # Only network-shaped failures degrade; programming errors must
        # stay loud.
        dest = tmp_path / "depth.csv"
        dest.write_bytes(b"stale")
        session = _FakeSession(_FakeResponse(chunks=[b"partial"], stream_exc=ValueError("bug")))
        with pytest.raises(ValueError):
            fetch_url("https://x.invalid/d", dest, key="d", max_age_hours=0.0, session=session)
        assert dest.read_bytes() == b"stale"
        assert list(tmp_path.glob("*.tmp-*")) == []


class TestSeasonalFallbackUsesStaleCopy:
    def test_seasonal_stream_failure_degrades_with_warning(self, tmp_path):
        dest = tmp_path / "snap_counts_2025.csv"
        dest.write_bytes(b"stale")
        session = _FakeSession(
            _FakeResponse(chunks=[b"x"], stream_exc=requests.ConnectionError("reset"))
        )
        path, season, warns = fetch_mod._fetch_seasonal(
            "https://x.invalid/snap_counts_{season}.csv",
            "snap_counts_{season}.csv",
            [2025],
            tmp_path,
            key="snap_counts",
            max_age_hours=0.0,
            force=False,
            session=session,
        )
        assert path == dest
        assert season == 2025
        assert any("stale" in w for w in warns)
