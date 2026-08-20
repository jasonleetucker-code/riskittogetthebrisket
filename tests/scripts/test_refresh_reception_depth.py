"""Exit-code contract for the reception-depth refresh.

Three outcomes that a scheduler must be able to tell apart:

    0  refreshed something
    1  a season that SHOULD exist could not be fetched  -> page someone
    2  nothing to do (season not started, or all complete)

Collapsing 1 and 2 is the failure this guards. nflverse publishes a
season's play-by-play only once it kicks off, so a 404 every offseason
is normal — reporting it as failure would make the unit red for months
and train everyone to ignore it, which is exactly when a genuinely
broken release path would slip through.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "refresh_reception_depth.py"


def _load():
    spec = importlib.util.spec_from_file_location("refresh_reception_depth", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def script():
    return _load()


def test_a_season_that_has_not_started_is_nothing_to_do_not_failure(script, monkeypatch):
    called = []
    monkeypatch.setattr(script, "persist_reception_depth", lambda s: called.append(s) or {})
    monkeypatch.setattr(script, "season_has_plausibly_started", lambda s, **k: False)
    assert script.main(["--seasons", "2026"]) == 2
    assert called == [], "must not even attempt a season that has not kicked off"


def test_a_started_season_that_yields_nothing_is_a_failure(script, monkeypatch):
    """The case that must page someone: the season has started, so a
    missing file means the release path moved."""
    monkeypatch.setattr(script, "season_has_plausibly_started", lambda s, **k: True)
    monkeypatch.setattr(script, "depth_path", lambda s, **k: Path("/nonexistent"))
    monkeypatch.setattr(
        script, "persist_reception_depth", lambda s: {"seasons": [], "players": 0, "receptions": 0}
    )
    assert script.main(["--seasons", "2025"]) == 1


def test_a_successful_refresh_returns_zero(script, monkeypatch):
    monkeypatch.setattr(script, "season_has_plausibly_started", lambda s, **k: True)
    monkeypatch.setattr(script, "depth_path", lambda s, **k: Path("/nonexistent"))
    monkeypatch.setattr(
        script,
        "persist_reception_depth",
        lambda s: {"seasons": list(s), "players": 400, "receptions": 11000},
    )
    assert script.main(["--seasons", "2025"]) == 0


def test_completed_seasons_on_disk_are_not_refetched(script, monkeypatch):
    """Historical seasons are immutable. Re-streaming a 98 MB CSV weekly
    for data that cannot change is pure waste."""
    monkeypatch.setattr(script, "season_has_plausibly_started", lambda s, **k: True)
    monkeypatch.setattr(script, "_current_season", lambda now=None: 2026)
    monkeypatch.setattr(script, "depth_path", lambda s, **k: Path(__file__))  # "exists"
    # Readable at the CURRENT schema — which is what "already on disk"
    # has to mean since v2 changed what a band means (see below).
    monkeypatch.setattr(script, "load_reception_depth", lambda s, **k: {"players": {}})
    called = []
    monkeypatch.setattr(script, "persist_reception_depth", lambda s: called.append(s) or {})
    assert script.main(["--seasons", "2024"]) == 2
    assert called == []


def test_a_completed_season_at_a_STALE_schema_is_rebuilt(script, monkeypatch):
    """ "Already on disk" is not enough, and this is the half that bit.

    v2 moved lost-yardage catches out of ``rec_0_4``, so a v1 file carries
    a DIFFERENT measurement under the same field names.
    ``load_reception_depth`` refuses it, and without this check the season
    would keep that refusal forever — the overlay silently absent rather
    than the file rebuilt.
    """
    monkeypatch.setattr(script, "season_has_plausibly_started", lambda s, **k: True)
    monkeypatch.setattr(script, "_current_season", lambda now=None: 2026)
    monkeypatch.setattr(script, "depth_path", lambda s, **k: Path(__file__))  # "exists"
    monkeypatch.setattr(script, "load_reception_depth", lambda s, **k: None)  # refused
    called = []
    monkeypatch.setattr(
        script,
        "persist_reception_depth",
        lambda s: called.append(list(s)) or {"seasons": list(s), "players": 1, "receptions": 1},
    )
    assert script.main(["--seasons", "2024"]) == 0
    assert called == [[2024]]


def test_force_overrides_the_skip(script, monkeypatch):
    monkeypatch.setattr(script, "season_has_plausibly_started", lambda s, **k: True)
    monkeypatch.setattr(script, "depth_path", lambda s, **k: Path(__file__))
    monkeypatch.setattr(
        script,
        "persist_reception_depth",
        lambda s: {"seasons": list(s), "players": 1, "receptions": 1},
    )
    assert script.main(["--seasons", "2024", "--force"]) == 0


def test_january_belongs_to_the_previous_season(script):
    """The off-by-one that would silence the entire postseason.

    In January the games being played are the PREVIOUS season's
    playoffs. A naive ``now.year`` would ask for a season that has not
    started, report "nothing to do", and stop updating shapes through
    the most valuable weeks of the year.
    """
    jan = datetime(2027, 1, 15, tzinfo=timezone.utc)
    assert script._current_season(jan) == 2026
    feb = datetime(2027, 2, 20, tzinfo=timezone.utc)
    assert script._current_season(feb) == 2026
    sep = datetime(2027, 9, 15, tzinfo=timezone.utc)
    assert script._current_season(sep) == 2027


def test_the_default_lookback_covers_what_the_blend_uses(script):
    """The blend uses a one-season half-life, so the third season back
    already counts a quarter. Fetching more would be filenames, not
    signal."""
    assert script.DEFAULT_LOOKBACK_SEASONS == 3
