"""Fetcher half of the Flock rookie seasonal window (owner decision 2026-10-03).

``scripts/fetch_flock_fantasy_rookies.py`` must tell three outcomes apart:

* expected empty — a verified response matching the declared signature
  inside the window → exit 4, explicit state, NO CSV write, NO success stamp;
* unexpected empty / failure → exit 1 (or 2), exactly as before;
* valid data → exit 0, CSV written, and an inactive source reactivates.

Hermetic: ``--from-file`` input, a temporary ``--state-dir`` and a fixed
``--now``.  Kept OUT of ``test_fetch_flock_fantasy_rookies.py`` because that
module sits in the advisory livedata tier (``tests/conftest.py``); these
assertions read nothing live and belong in the blocking gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import fetch_flock_fantasy_rookies as ffr
from src.sources import seasonal_policy as sp
from src.sources.acquisition_state import SEASONALLY_INACTIVE_EXIT_CODE

KEY = "flockFantasySfRookies"
OCT_2 = "2026-10-02T12:00:00Z"
OLD_CSV = "name,Rank\nOld Graduate,1.0\n"


def _board(n: int, year: int = 2027) -> dict:
    return {
        "format": "PROSPECTS_SF",
        "year": year,
        "lastUpdated": "2027-01-10T00:00:00Z",
        "data": [
            {
                "playerName": f"Prospect {i}",
                "position": ("QB", "RB", "WR", "TE")[i % 4],
                "averageRank": float(i + 1),
                "isDraftPick": False,
                "isRookie": True,
            }
            for i in range(n)
        ],
    }


def _empty(year: int = 2026, fmt: str | None = "PROSPECTS_SF") -> dict:
    out: dict = {"year": year, "data": [], "lastUpdated": "2026-09-30T16:00:00Z"}
    if fmt is not None:
        out["format"] = fmt
    return out


@pytest.fixture()
def env(tmp_path: Path):
    dest = tmp_path / "flockFantasySfRookies.csv"
    dest.write_text(OLD_CSV, encoding="utf-8")
    state_dir = tmp_path / "scrape_state"
    state_dir.mkdir()

    def run(payload, now: str = OCT_2) -> int:
        src = tmp_path / "resp.json"
        src.write_text(json.dumps(payload), encoding="utf-8")
        return ffr.main(
            [
                "--from-file",
                str(src),
                "--dest",
                str(dest),
                "--state-dir",
                str(state_dir),
                "--now",
                now,
            ]
        )

    def state():
        return sp.load_state(sp.state_path(state_dir, KEY))

    return run, dest, state_dir, state


def test_empty_after_cutoff_is_seasonally_inactive(env):
    run, dest, state_dir, state = env
    assert run(_empty()) == SEASONALLY_INACTIVE_EXIT_CODE
    assert state()["state"] == sp.SEASONALLY_INACTIVE
    # Historical CSV untouched — provenance and replay keep the graduated class.
    assert dest.read_text(encoding="utf-8") == OLD_CSV


def test_inactive_writes_no_success_or_freshness_stamp(env):
    run, _dest, state_dir, _state = env
    run(_empty())
    assert sorted(p.name for p in state_dir.iterdir()) == [f"{KEY}_seasonal.json"]


def test_attempts_continue_and_each_one_reverifies(env):
    run, _dest, _sd, state = env
    run(_empty(), now="2026-10-02T12:00:00Z")
    run(_empty(), now="2026-10-02T14:00:00Z")
    s = state()
    assert s["since"] == "2026-10-02T12:00:00Z"
    assert s["lastInactiveVerifiedAt"] == "2026-10-02T14:00:00Z"


def test_empty_before_cutoff_still_fails_closed(env):
    run, dest, state_dir, _state = env
    assert run(_empty(), now="2026-09-20T00:00:00Z") == 1
    assert not any(state_dir.iterdir())
    assert dest.read_text(encoding="utf-8") == OLD_CSV


@pytest.mark.parametrize(
    "payload",
    [_empty(year=2027), _empty(fmt=None), _empty(fmt="SUPERFLEX"), {"data": []}],
)
def test_off_signature_empty_fails_closed(env, payload):
    run, _dest, state_dir, _state = env
    assert run(payload) == 1
    assert not any(state_dir.iterdir())


def test_nonempty_but_all_filtered_is_not_inactive(env):
    run, _dest, state_dir, _state = env
    payload = _empty()
    payload["data"] = [{"playerName": "Vet", "position": "WR", "averageRank": 1, "isRookie": False}]
    assert run(payload) == 1
    assert not any(state_dir.iterdir())


def test_valid_next_class_reactivates_immediately(env):
    run, dest, _sd, state = env
    run(_empty())
    # Any date: reactivation is the data, not the calendar.
    assert run(_board(40), now="2026-11-05T00:00:00Z") == 0
    assert state()["state"] == sp.ACTIVE
    assert "Prospect 0" in dest.read_text(encoding="utf-8")
    assert sp.inactive_sources_as_of(env[2], None) == {}


def test_malformed_nonempty_still_fails_its_guards_while_inactive(env):
    run, dest, _sd, state = env
    run(_empty())
    # Below the truncation floor: exit 2, CSV untouched, still inactive
    # (the graduated board must not start voting again).
    assert run(_board(ffr._FF_ROOKIE_ROW_COUNT_FLOOR - 1)) == 2
    assert dest.read_text(encoding="utf-8") == OLD_CSV
    assert state()["state"] == sp.SEASONALLY_INACTIVE
    # Shape regression: exit 2 as well.
    assert run(["not", "a", "dict"]) == 2
    assert state()["state"] == sp.SEASONALLY_INACTIVE


def test_valid_board_without_a_window_writes_no_state(env):
    run, _dest, state_dir, _state = env
    assert run(_board(40)) == 0
    assert not any(state_dir.iterdir())
