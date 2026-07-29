"""A 404 from nflverse means one of two opposite things.

Either our URL template went stale (the 2025 rename — permanent, our
fault, actionable) or the season simply has not started yet (nflverse
publishes a season's release assets once it is under way, so every
``*_{next_year}.csv`` 404s for the whole Feb–Aug window by design).

The module treated both as a transient failure.  That mislabelled a
correct URL as broken in the logs, and — the part with teeth — reported
it to a circuit breaker scoped to the WHOLE module at threshold 3 over
a 180s window.  Three future-season datasets probed together is exactly
three failures inside that window, which opens the breaker for 300s and
takes down the *working* current-season fetches with it.

Measured against the live release host on 2026-07-29, before the 2026
season began:

    stats_player/stats_player_week_2025.csv     200
    stats_player/stats_player_week_2026.csv     404
    snap_counts/snap_counts_2025.csv            200
    snap_counts/snap_counts_2026.csv            404
    pbp/play_by_play_2025.csv                   200
    pbp/play_by_play_2026.csv                   404

No network here — the HTTP layer is stubbed so these assert the
decision, not nflverse's uptime.
"""

from __future__ import annotations

import urllib.error
from datetime import date

import pytest

from src.nfl_data import nflverse_direct as nd


class _Recorder:
    """Stands in for the shared circuit breaker."""

    def __init__(self) -> None:
        self.failures = 0

    def can_call(self) -> bool:
        return True

    def report_failure(self, _exc: object) -> None:
        self.failures += 1


@pytest.fixture
def breaker(monkeypatch):
    rec = _Recorder()
    import src.utils.circuit_breaker as cb

    monkeypatch.setattr(cb, "get_or_create", lambda *a, **k: rec)
    return rec


@pytest.fixture
def http_404(monkeypatch):
    def _raise(*_a, **_k):
        raise urllib.error.HTTPError(url="x", code=404, msg="Not Found", hdrs=None, fp=None)

    monkeypatch.setattr(nd.urllib.request, "urlopen", _raise)


# ── which season could nflverse have published? ──────────────────────


@pytest.mark.parametrize(
    "today,expected",
    [
        (date(2026, 7, 29), 2025),  # the measurement above: preseason
        (date(2026, 8, 31), 2025),  # last day before publication
        (date(2026, 9, 1), 2026),  # season starts, assets appear
        (date(2026, 12, 15), 2026),
        (date(2027, 1, 20), 2026),  # January still reads as last season
    ],
)
def test_latest_published_season(today, expected):
    assert nd._latest_published_season(today) == expected


def test_latest_published_season_is_not_current_nfl_season():
    """These answer different questions and must not be conflated.

    ``current_nfl_season`` returns None across Feb–Aug because no season
    is being *played*.  nflverse still serves last season's finished
    data throughout that window, so using it here would classify every
    offseason fetch as a future season and suppress genuine staleness.
    """
    from src.bdvm.actuals import current_nfl_season

    july = date(2026, 7, 29)
    assert current_nfl_season(july) is None
    assert nd._latest_published_season(july) == 2025


# ── year extraction is anchored to the filename ──────────────────────


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://x/download/stats_player/stats_player_week_2026.csv", 2026),
        ("https://x/download/snap_counts/snap_counts_2025.csv", 2025),
        ("https://x/download/pbp/play_by_play_2026.csv", 2026),
        ("https://x/download/players/players.csv", None),  # no season in path
    ],
)
def test_season_in_url(url, expected):
    assert nd._season_in_url(url) == expected


def test_season_extraction_ignores_years_outside_the_filename():
    """A year in the host or release base is not the requested season."""
    url = "https://cdn2024.example.com/2019/releases/players.csv"
    assert nd._season_in_url(url) is None


# ── the behaviour that matters ───────────────────────────────────────


def test_unpublished_season_does_not_poison_the_breaker(monkeypatch, breaker, http_404):
    """The live-production case: July, asking for 2026."""
    monkeypatch.setattr(nd, "_latest_published_season", lambda *_a: 2025)

    rows = nd._fetch_csv(
        "https://x/download/stats_player/stats_player_week_2026.csv",
        label="weekly_stats",
    )

    assert rows == []
    assert (
        breaker.failures == 0
    ), "a permanent, correct-by-design 404 was counted as a transient fault"


def test_three_future_season_probes_still_leave_the_breaker_clean(monkeypatch, breaker, http_404):
    """Threshold is 3 over 180s — this is the exact shape that tripped it.

    weekly stats, snap counts and pbp are fetched together, so before
    the fix a single preseason refresh contributed all three failures
    and opened the breaker against the working 2025 URLs.
    """
    monkeypatch.setattr(nd, "_latest_published_season", lambda *_a: 2025)

    for path, label in (
        ("stats_player/stats_player_week_2026.csv", "weekly_stats"),
        ("snap_counts/snap_counts_2026.csv", "snap_counts"),
        ("pbp/play_by_play_2026.csv", "pbp"),
    ):
        assert nd._fetch_csv(f"https://x/download/{path}", label=label) == []

    assert breaker.failures == 0


def test_stale_template_is_still_reported_as_a_failure(monkeypatch, breaker, http_404):
    """The 2025-rename case must keep shouting.

    A 404 for a season nflverse HAS published is a real defect, and
    suppressing it is how the original rename went unnoticed.
    """
    monkeypatch.setattr(nd, "_latest_published_season", lambda *_a: 2025)

    rows = nd._fetch_csv(
        "https://x/download/player_stats/player_stats_2025.csv",
        label="weekly_stats",
    )

    assert rows == []
    assert breaker.failures == 1, "a genuinely stale URL template must reach the breaker"


def test_seasonless_url_404_is_treated_as_stale(monkeypatch, breaker, http_404):
    """``players/players.csv`` carries no season, so a 404 there is real."""
    monkeypatch.setattr(nd, "_latest_published_season", lambda *_a: 2025)

    assert nd._fetch_csv("https://x/download/players/players.csv", label="id_map") == []
    assert breaker.failures == 1


def test_non_404_errors_are_unaffected(monkeypatch, breaker):
    """5xx stays a transient fault regardless of the season asked for."""

    def _raise(*_a, **_k):
        raise urllib.error.HTTPError(url="x", code=503, msg="nope", hdrs=None, fp=None)

    monkeypatch.setattr(nd.urllib.request, "urlopen", _raise)
    monkeypatch.setattr(nd, "_latest_published_season", lambda *_a: 2025)

    assert nd._fetch_csv("https://x/download/pbp/play_by_play_2026.csv", label="pbp") == []
    assert breaker.failures == 1
