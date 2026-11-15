"""KTC Trade Database adapter: parser on synthetic pages + polite collection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.sources import ktc_trades as K
from src.trade import market_trade_archive as A
from tests.trade.market_trade_fixtures import ktc_page, ktc_row, ktc_settings

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, dict(headers)))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def ok(html: str, **headers):
    return 200, {k.lower(): v for k, v in headers.items()}, html.encode("utf-8")


@pytest.fixture
def root(tmp_path):
    A._reset_setup_cache_for_tests()
    yield tmp_path / "market_trades"
    A._reset_setup_cache_for_tests()


def _collect(root, http, at=T0, **kw):
    return K.collect(
        root=root,
        archive_path=root / "archive.sqlite",
        http=http,
        now=lambda: at,
        sleep=lambda s: None,
        **kw,
    )


ROWS = [ktc_row(101, [11], [12]), ktc_row(102, [13, 14], [901])]


class TestParser:
    def test_rows_and_index_are_extracted_verbatim(self):
        page = K.parse_trade_page(ktc_page(ROWS))
        assert not page.errors
        assert [r["id"] for r in page.trades] == [101, 102]
        assert page.trades[0]["settings"]["id"] == "L-SYN-1"
        assert {r["playerID"] for r in page.identity_rows} >= {11, 901}

    def test_structurally_unusable_rows_are_counted_not_silently_dropped(self):
        bad = {"id": 7, "teamOne": {"playerIds": ["1"]}}  # no teamTwo / settings
        page = K.parse_trade_page(ktc_page([*ROWS, bad]))
        assert len(page.trades) == 2
        assert any("missing_teamTwo_playerIds" in w for w in page.warnings)

    def test_missing_trades_array_is_an_error_not_an_empty_market(self):
        page = K.parse_trade_page("<html>nothing here</html>")
        assert page.errors == ["trades_array_missing_or_unparseable"]

    def test_platform_comes_from_the_rows_own_league_url(self):
        assert K.host_platform(ktc_settings(platform="sleeper")) == "sleeper"
        assert K.host_platform(ktc_settings(platform="mfl")) == "mfl"
        assert K.host_platform({"leagueUrl": "https://example.org/x"}) == "unknown"

    def test_observed_date_is_day_granularity(self):
        assert K.observed_date({"date": "2026-10-01T00:00:00"}) == "2026-10-01"
        assert K.observed_date({"date": None}) is None


class TestCollection:
    def test_first_fetch_archives_every_row_unconditionally(self, root):
        http = FakeHttp([ok(ktc_page(ROWS), ETag='W/"e1"')])
        out = _collect(root, http)
        assert out["outcome"] == "archived"
        assert out["newCount"] == 2
        assert "If-None-Match" not in http.calls[0][1], "no validator before content exists"
        assert A.coverage(K.SOURCE_FAMILY, path=root / "archive.sqlite")["observations"] == 2

    def test_refetch_of_the_same_window_adds_nothing_and_sends_validators(self, root):
        http = FakeHttp([ok(ktc_page(ROWS), ETag='W/"e1"'), ok(ktc_page(ROWS), ETag='W/"e1"')])
        _collect(root, http)
        out = _collect(root, http, at=T0 + timedelta(minutes=30))
        assert (out["newCount"], out["knownCount"]) == (0, 2)
        assert http.calls[1][1]["If-None-Match"] == 'W/"e1"'

    def test_304_is_not_modified(self, root):
        http = FakeHttp([ok(ktc_page(ROWS), ETag='W/"e1"'), (304, {}, b"")])
        _collect(root, http)
        assert _collect(root, http, at=T0 + timedelta(hours=1))["outcome"] == "not_modified"

    @pytest.mark.parametrize("status", [401, 403])
    def test_access_denial_persists_a_stop_that_later_runs_obey(self, root, status):
        http = FakeHttp([(status, {}, b"no")])
        assert _collect(root, http)["outcome"] == "auth_stopped"
        later = FakeHttp([ok(ktc_page(ROWS))])
        out = _collect(root, later, at=T0 + timedelta(hours=2))
        assert out["outcome"] == "stopped"
        assert later.calls == [], "a stopped collector must not touch the network"
        assert K.clear_stop(root) is True

    def test_challenge_page_is_an_access_stop_not_a_parse_failure(self, root):
        http = FakeHttp([ok("<html><title>Just a moment...</title>cf-challenge</html>")])
        out = _collect(root, http)
        assert out["outcome"] == "auth_stopped" and out["reason"] == "challenge_page"

    def test_redirect_to_a_login_wall_stops(self, root):
        http = FakeHttp([(302, {"location": "https://keeptradecut.com/login"}, b"")])
        assert _collect(root, http)["outcome"] == "auth_stopped"

    def test_schema_drift_quarantines_and_archives_nothing(self, root):
        http = FakeHttp([ok("<html><script>var trades = 42;</script></html>")])
        out = _collect(root, http)
        assert out["outcome"] == "quarantined"
        assert A.coverage(K.SOURCE_FAMILY, path=root / "archive.sqlite")["observations"] == 0
        assert list((root / "quarantine" / "ktc").glob("*.json"))

    def test_429_honours_retry_after_then_gives_up(self, root):
        slept = []
        http = FakeHttp(
            [
                (429, {"retry-after": "1"}, b""),
                (429, {"retry-after": "1"}, b""),
                (429, {"retry-after": "1"}, b""),
            ]
        )
        out = K.collect(
            root=root,
            archive_path=root / "archive.sqlite",
            http=http,
            now=lambda: T0,
            sleep=slept.append,
        )
        assert out["outcome"] == "rate_limited"
        assert slept == [1.0, 1.0]

    @pytest.mark.parametrize(
        "first",
        [
            (401, {}, b"no"),
            (403, {}, b"no"),
            (200, {}, b"<html><title>Just a moment...</title>cf-challenge</html>"),
        ],
    )
    def test_force_never_bypasses_a_persisted_stop(self, root, first):
        assert _collect(root, FakeHttp([first]))["outcome"] == "auth_stopped"
        later = FakeHttp([ok(ktc_page(ROWS))])
        out = _collect(root, later, at=T0 + timedelta(hours=2), force=True)
        assert out["outcome"] == "stopped"
        assert later.calls == [], "--force must not touch the network while stopped"
        assert K.clear_stop(root) is True
        assert _collect(root, later, at=T0 + timedelta(hours=3))["outcome"] == "archived"

    def test_force_still_bypasses_the_min_interval(self, root):
        _collect(root, FakeHttp([ok(ktc_page(ROWS))]))
        http = FakeHttp([ok(ktc_page(ROWS))])
        out = _collect(
            root, http, at=T0 + timedelta(minutes=5), min_interval_minutes=25, force=True
        )
        assert out["outcome"] == "archived" and len(http.calls) == 1

    def test_repeated_schema_drift_stops_instead_of_quarantining_forever(self, root):
        qdir = root / "quarantine" / "ktc"
        pages = [f"<html><script>var trades = {n};</script></html>" for n in range(10)]
        outs = []
        for i in range(K.MAX_CONSECUTIVE_QUARANTINES):
            outs.append(_collect(root, FakeHttp([ok(pages[i])]), at=T0 + timedelta(minutes=30 * i)))
        assert [o["outcome"] for o in outs] == ["quarantined"] * K.MAX_CONSECUTIVE_QUARANTINES
        assert outs[-1].get("stopped") is True
        state = K.load_state(root)
        assert state["stopReason"] == K.STOP_REASON_SCHEMA_DRIFT
        gz_before = len(list(qdir.glob("*.html.gz")))
        assert gz_before == K.MAX_CONSECUTIVE_QUARANTINES
        # Later runs (even forced) neither fetch nor write another raw page.
        later = FakeHttp([ok(pages[9])])
        out = _collect(root, later, at=T0 + timedelta(hours=5), force=True)
        assert out["outcome"] == "stopped" and later.calls == []
        assert len(list(qdir.glob("*.html.gz"))) == gz_before
        assert K.clear_stop(root) is True
        assert "consecutiveQuarantines" not in K.load_state(root)

    def test_a_good_fetch_resets_the_quarantine_streak(self, root):
        bad = ok("<html><script>var trades = 42;</script></html>")
        _collect(root, FakeHttp([bad]))
        _collect(root, FakeHttp([ok(ktc_page(ROWS))]), at=T0 + timedelta(minutes=30))
        assert K.load_state(root)["consecutiveQuarantines"] == 0
        for i in range(K.MAX_CONSECUTIVE_QUARANTINES - 1):
            _collect(root, FakeHttp([bad]), at=T0 + timedelta(hours=1 + i))
        assert not K.load_state(root).get("stoppedAt")

    def test_min_interval_skips_without_a_request(self, root):
        http = FakeHttp([ok(ktc_page(ROWS))])
        _collect(root, http)
        out = _collect(root, FakeHttp([]), at=T0 + timedelta(minutes=5), min_interval_minutes=25)
        assert out["outcome"] == "skipped_recent"
