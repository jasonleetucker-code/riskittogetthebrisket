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
    """Single-response session, or per-URL via ``by_url`` — a mapping
    of url → response object or Exception to raise."""

    def __init__(self, response=None, request_exc: Exception | None = None, by_url=None):
        self._response = response
        self._request_exc = request_exc
        self._by_url = by_url
        self.calls: list[dict] = []

    def get(self, url, headers=None, timeout=None, stream=None):
        self.calls.append({"url": url, "headers": headers})
        if self._by_url is not None:
            entry = self._by_url[url]
            if isinstance(entry, Exception):
                raise entry
            return entry
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

    def test_404_with_cached_copy_degrades_to_stale(self, tmp_path):
        # Regression (Codex round 4 on PR #539): a 404 on a file we
        # already hold locally (asset removed / temporarily
        # unavailable upstream) must NOT discard the cache — that
        # would let the seasonal walk replace current-season data
        # with last year's.
        dest = tmp_path / "d.csv"
        dest.write_bytes(b"cached-current")
        session = _FakeSession(_FakeResponse(status_code=404))
        res = fetch_url("https://x.invalid/d", dest, key="d", max_age_hours=0.0, session=session)
        assert res.status == "error"  # NOT "missing" — the walk must stop here
        assert res.path == dest
        assert dest.read_bytes() == b"cached-current"


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


class TestSeasonalTransientFailures:
    """Regression (Codex round 3 on PR #539): the prior-season walk
    must engage ONLY on a genuine upstream 404.  A transient failure
    (timeout / 5xx / connection error) on the current season with no
    local cache must stop the walk — silently publishing last year's
    file mid-season looks plausible enough to pass the retention
    guards."""

    URL_TMPL = "https://x.invalid/snap_counts_{season}.csv"
    FILE_TMPL = "snap_counts_{season}.csv"

    def _seasonal(self, tmp_path, session, seasons=(2026, 2025)):
        return fetch_mod._fetch_seasonal(
            self.URL_TMPL,
            self.FILE_TMPL,
            list(seasons),
            tmp_path,
            key="snap_counts",
            max_age_hours=0.0,
            force=False,
            session=session,
        )

    def test_500_without_cache_stops_walk(self, tmp_path):
        session = _FakeSession(
            by_url={
                self.URL_TMPL.format(season=2026): _FakeResponse(status_code=500),
                self.URL_TMPL.format(season=2025): _FakeResponse(chunks=[b"last-year"]),
            }
        )
        path, season, warns = self._seasonal(tmp_path, session)
        assert path is None and season is None
        # The prior season must not even be requested.
        assert [c["url"] for c in session.calls] == [self.URL_TMPL.format(season=2026)]
        assert any("refusing prior-season fallback" in w for w in warns)
        assert not (tmp_path / self.FILE_TMPL.format(season=2025)).exists()

    def test_connection_error_without_cache_stops_walk(self, tmp_path):
        session = _FakeSession(
            by_url={
                self.URL_TMPL.format(season=2026): requests.ConnectTimeout("slow"),
                self.URL_TMPL.format(season=2025): _FakeResponse(chunks=[b"last-year"]),
            }
        )
        path, season, warns = self._seasonal(tmp_path, session)
        assert path is None and season is None
        assert len(session.calls) == 1
        assert any("refusing prior-season fallback" in w for w in warns)

    def test_404_still_falls_back_to_prior_season(self, tmp_path):
        session = _FakeSession(
            by_url={
                self.URL_TMPL.format(season=2026): _FakeResponse(status_code=404),
                self.URL_TMPL.format(season=2025): _FakeResponse(chunks=[b"real-2025"]),
            }
        )
        path, season, warns = self._seasonal(tmp_path, session)
        assert season == 2025
        assert path is not None and path.read_bytes() == b"real-2025"

    def test_500_with_local_current_season_copy_uses_stale(self, tmp_path):
        dest = tmp_path / self.FILE_TMPL.format(season=2026)
        dest.write_bytes(b"stale-current-season")
        session = _FakeSession(
            by_url={
                self.URL_TMPL.format(season=2026): _FakeResponse(status_code=500),
            }
        )
        path, season, warns = self._seasonal(tmp_path, session)
        assert path == dest
        assert season == 2026
        assert dest.read_bytes() == b"stale-current-season"
        assert any("stale" in w for w in warns)

    def test_404_with_cached_current_season_uses_stale_not_prior_season(self, tmp_path):
        # Regression (Codex round 4 on PR #539): current-season asset
        # 404s while a local current-season cache exists — the walk
        # must use the cached CURRENT season, never regress to the
        # prior season.
        dest = tmp_path / self.FILE_TMPL.format(season=2026)
        dest.write_bytes(b"cached-2026")
        session = _FakeSession(
            by_url={
                self.URL_TMPL.format(season=2026): _FakeResponse(status_code=404),
                self.URL_TMPL.format(season=2025): _FakeResponse(chunks=[b"last-year"]),
            }
        )
        path, season, warns = self._seasonal(tmp_path, session)
        assert path == dest
        assert season == 2026
        assert dest.read_bytes() == b"cached-2026"
        # The prior season must never even be requested.
        assert [c["url"] for c in session.calls] == [self.URL_TMPL.format(season=2026)]
        assert any("stale" in w for w in warns)


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
