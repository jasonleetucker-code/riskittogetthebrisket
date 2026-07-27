"""nflverse release-path templates.

Why this file exists: nflverse renamed and unified its per-week player
release in 2025. The old path kept serving <=2024 while 404ing 2025, so
`_fetch_csv` swallowed the 404, returned [], and every consumer read it
as "the season has no data yet". A break that only affects the CURRENT
season, and only looks like emptiness, is the kind that survives a long
time.

These tests are structural — they pin the template shape and the
severity of a stale-path failure without hitting the network. The live
probe that established the fix is recorded in the module comment on
`_URL_TEMPLATES`:

    player_stats/player_stats_2025.csv        404
    stats_player/stats_player_week_2025.csv   200   (and 2024: 200)
"""

from __future__ import annotations

import logging
import urllib.error

import pytest

from src.nfl_data import nflverse_direct as nd


class TestWeeklyTemplatesUseTheCurrentPath:
    """Fails against the pre-fix templates, which is the point."""

    @pytest.mark.parametrize("key", ["weekly_stats", "weekly_defensive_stats"])
    def test_uses_the_renamed_release(self, key):
        tmpl = nd._URL_TEMPLATES[key]
        assert "stats_player/stats_player_week_" in tmpl, (
            f"{key} still points at a release path that 404s for 2025+; "
            "nflverse renamed it to stats_player/stats_player_week_{year}.csv"
        )

    @pytest.mark.parametrize("key", ["weekly_stats", "weekly_defensive_stats"])
    def test_does_not_use_the_retired_path(self, key):
        tmpl = nd._URL_TEMPLATES[key]
        assert "player_stats/player_stats_" not in tmpl

    def test_offense_and_defense_resolve_to_one_file(self):
        """The new release unifies them — it carries 15 def_* columns
        alongside the offensive ones. Two URLs would mean two fetches of
        the same bytes."""
        assert nd._URL_TEMPLATES["weekly_stats"] == nd._URL_TEMPLATES["weekly_defensive_stats"]

    @pytest.mark.parametrize("year", [2024, 2025])
    def test_template_formats_for_recent_seasons(self, year):
        url = nd._URL_TEMPLATES["weekly_stats"].format(year=year)
        assert url.endswith(f"stats_player_week_{year}.csv")
        assert url.startswith("https://github.com/nflverse/nflverse-data/releases/download")


class TestStalePathIsLoudNotQuiet:
    """A 404 means OUR template is wrong. It must not read like a
    transient blip, because retrying can never fix it."""

    def _raise_http(self, status):
        def _fake(req, timeout=None):  # noqa: ARG001
            raise urllib.error.HTTPError(
                req.full_url if hasattr(req, "full_url") else "u", status, "err", {}, None
            )

        return _fake

    def test_404_logs_at_error_with_a_pointer_to_the_template(self, monkeypatch, caplog):
        monkeypatch.setattr(nd.urllib.request, "urlopen", self._raise_http(404))
        with caplog.at_level(logging.ERROR):
            rows = nd._fetch_csv("https://example.invalid/x.csv", label="weekly_stats:2025")
        assert rows == []
        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert errors, "a stale release path must log at ERROR, not WARNING"
        assert "url_stale" in errors[0].getMessage()
        assert (
            "_URL_TEMPLATES" in errors[0].getMessage()
        ), "the log must name what to fix; 'fetch failed' sends nobody anywhere"

    def test_500_stays_a_warning(self, monkeypatch, caplog):
        """A server error IS transient. Escalating it too would make
        ERROR meaningless for the case that matters."""
        monkeypatch.setattr(nd.urllib.request, "urlopen", self._raise_http(500))
        with caplog.at_level(logging.DEBUG):
            rows = nd._fetch_csv("https://example.invalid/x.csv", label="weekly_stats:2025")
        assert rows == []
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
