"""Roster freshness evidence (Brisket Trade Advisor B0-f).

The scraper stamps how its roster block was obtained ON the block
(``Dynasty Scraper.py::_stamp_roster_source``); ``src.api.roster_freshness``
is the one reader.  Unknown is never current.
"""

from __future__ import annotations

import ast
import datetime as _dt
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.api.roster_freshness import roster_freshness

NOW = datetime(2026, 10, 19, 21, 0, tzinfo=timezone.utc)
REPO = Path(__file__).resolve().parents[2]


def _c(source, fetched):
    sleeper = {"teams": []}
    if source is not None:
        sleeper["rosterSource"] = source
    if fetched is not None:
        sleeper["rosterFetchedAt"] = fetched
    return {"sleeper": sleeper}


@pytest.mark.parametrize(
    ("source", "age_h", "state"),
    [
        ("live", 0.0, "current"),
        ("live", 5.9, "current"),
        ("live", 6.0, "current"),
        ("live", 6.1, "stale"),
        ("last_good", 0.5, "stale"),
        ("last_good", 30.0, "stale"),
    ],
)
def test_states(source, age_h, state):
    fetched = (NOW - timedelta(hours=age_h)).isoformat()
    out = roster_freshness(_c(source, fetched), now=NOW)
    assert out["state"] == state
    assert out["asOf"] == (NOW - timedelta(hours=age_h)).date().isoformat()
    assert out["source"] == source


@pytest.mark.parametrize(
    "contract",
    [
        None,
        {},
        {"sleeper": None},
        _c(None, None),  # an older build: no stamp at all
        _c("live", None),
        _c("live", "not a date"),
        _c("live", "2026-10-19T20:00:00"),  # unzoned
        _c("restored", NOW.isoformat()),
        _c("live", (NOW + timedelta(hours=2)).isoformat()),  # in the future
    ],
)
def test_unprovable_is_unknown_never_current(contract):
    assert roster_freshness(contract, now=NOW)["state"] == "unknown"


def test_small_clock_skew_is_tolerated():
    out = roster_freshness(_c("live", (NOW + timedelta(minutes=5)).isoformat()), now=NOW)
    assert out["state"] == "current"


def test_only_the_date_is_exposed():
    out = roster_freshness(_c("live", NOW.isoformat()), now=NOW)
    assert set(out) == {"state", "asOf", "source"}
    assert out["asOf"] == "2026-10-19"


def _scraper_stamp():
    text = (REPO / "Dynasty Scraper.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    node = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_stamp_roster_source"
    )
    ns: dict = {"datetime": _dt, "time": time}
    exec(compile(ast.get_source_segment(text, node), "<stamp>", "exec"), ns)
    return ns["_stamp_roster_source"]


def test_scraper_stamp_round_trips_through_the_reader():
    stamp = _scraper_stamp()
    live: dict = {"teams": []}
    stamp(live, "live", 0.0)
    assert live["rosterSource"] == "live" and live["rosterSnapshotAgeHours"] == 0.0
    assert roster_freshness({"sleeper": live})["state"] == "current"

    restored: dict = {"teams": []}
    stamp(restored, "last_good", 1.5)
    assert restored["rosterSnapshotAgeHours"] == 1.5
    assert roster_freshness({"sleeper": restored})["state"] == "stale"

    unknown_age: dict = {}
    stamp(unknown_age, "last_good", None)
    assert unknown_age["rosterFetchedAt"] is None
    assert roster_freshness({"sleeper": unknown_age})["state"] == "unknown"

    stamp(None, "live", 0.0)  # tolerated, no raise


def test_scraper_stamps_every_branch_that_publishes_rosters():
    text = (REPO / "Dynasty Scraper.py").read_text(encoding="utf-8")
    assert text.count('_stamp_roster_source(SLEEPER_ROSTER_DATA, "live", 0.0)') == 2
    assert '_stamp_roster_source(SLEEPER_ROSTER_DATA, "last_good", _cache_age_h)' in text
