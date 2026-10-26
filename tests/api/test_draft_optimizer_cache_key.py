"""Perfect Draft context cache key vs the LI-5 flag (LI-5 P3 review finding F-B).

``draft_optimizer_api.get_roster_context`` keeps a built context until its
contract is replaced.  With ``replacement_level_li5_consolidation`` ON the build
also reads the date's rookie window, the league's current week and the players
DB's ``fetchedAt`` (design
``docs/valuation/LI5_REPLACEMENT_CONSOLIDATION_DESIGN_2026-10-21.md`` §8 item
10), so the key must carry them or a changed input is answered from a stale
context.  With the flag OFF none of that is read and the key must be exactly
what it was before.

What this file proves:

* **flag OFF — the key is unchanged.**  Pinned as a literal tuple, and the flag
  OFF path reads NONE of the new inputs (each is patched to raise), and a change
  in all of them is still a cache hit, i.e. behaviour is the incumbent's;
* **flag ON — each input is in the key.**  Rookie window, evaluation date,
  league week, availability reason, players-DB ``fetchedAt`` and the DB crossing
  its age bound each rebuild; identical inputs hit;
* ``persisted_players_db_fetched_at`` is disk-only, unknown (``None``) rather
  than "now", and shares the parse cache with ``persisted_players_meta``.

Hermetic: stub builder, synthetic contract, temp players DB; no network.
"""

from __future__ import annotations

import json
import time
import types
from datetime import date

import pytest

from src.api import draft_optimizer_api as api
from src.api import feature_flags
from src.draft import waiver_population as WP

LI5_ENV = "RISKIT_FEATURE_REPLACEMENT_LEVEL_LI5_CONSOLIDATION"
CONTRACT = {"generatedAt": "2026-10-25T00:00:00+00:00", "scrapeTimestamp": "2026-10-25T00:00:01"}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    api.reset_cache()
    WP.reset_cache()
    yield
    api.reset_cache()
    WP.reset_cache()
    monkeypatch.delenv(LI5_ENV, raising=False)
    feature_flags.reload()


def _set_flag(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(LI5_ENV, raising=False)
    else:
        monkeypatch.setenv(LI5_ENV, value)
    feature_flags.reload()


class _Builds:
    def __init__(self, monkeypatch):
        self.count = 0
        monkeypatch.setattr(api, "build_roster_context", self._build)

    def _build(self, contract, league_key, **_kw):
        self.count += 1
        return {"build": self.count}


class _World:
    """The inputs a flag-ON build reads beside the contract, all controllable."""

    def __init__(self, monkeypatch):
        self.rookies = True
        self.today = date(2026, 10, 25)
        self.week = 8
        self.reason = None
        self.fetched = 1_800_000_000.0
        self.now = self.fetched + 3600.0
        monkeypatch.setattr(WP, "resolve_request_inputs", self._inputs)
        monkeypatch.setattr(
            "src.ros.game_day_live.persisted_players_db_fetched_at", lambda: self.fetched
        )
        monkeypatch.setattr(
            WP, "time", types.SimpleNamespace(time=lambda: self.now, monotonic=time.monotonic)
        )

    def _inputs(self, contract, *, today=None, rookies_eligible=None):
        availability = None if self.week is None else types.SimpleNamespace(current_week=self.week)
        return WP.RequestInputs(self.rookies, availability, self.today, self.reason, ("world",))


# ── flag OFF: the key and the behaviour are the incumbent's ───────────────


@pytest.mark.parametrize("value", [None, "0"], ids=["default", "explicit_off"])
def test_flag_off_key_is_exactly_the_incumbent_tuple(monkeypatch, value):
    _set_flag(monkeypatch, value)
    builds = _Builds(monkeypatch)

    def _forbidden(*_a, **_k):
        raise AssertionError("flag OFF must not read the LI-5 request inputs")

    monkeypatch.setattr(WP, "request_cache_stamp", _forbidden)
    monkeypatch.setattr(WP, "resolve_request_inputs", _forbidden)
    monkeypatch.setattr("src.ros.game_day_live.persisted_players_db_fetched_at", _forbidden)

    api.get_roster_context(CONTRACT, "dynasty_main", owner_id="o1", team_name=" Team A ")

    assert builds.count == 1
    # Contract stamp, league, owner, roster id, lower-cased team name, then the
    # flag state — nothing else.  Pinned as a literal.
    assert list(api._context_cache) == [
        (id(CONTRACT), CONTRACT["generatedAt"], CONTRACT["scrapeTimestamp"])
        + ("dynasty_main", "o1", "", "team a", False)
    ]


def test_flag_off_ignores_every_li5_input(monkeypatch):
    """Behaviour, not just shape: with the flag OFF a change in the rookie
    window, date, week, players-DB time or its age is still a cache HIT."""
    _set_flag(monkeypatch, "0")
    builds = _Builds(monkeypatch)
    world = _World(monkeypatch)

    first = api.get_roster_context(CONTRACT, None, owner_id="o1")
    world.rookies, world.today = False, date(2026, 12, 1)
    world.week, world.reason = 14, "availability_context_unavailable:X"
    world.fetched, world.now = world.fetched + 10 * 86400, world.now + 40 * 86400
    again = api.get_roster_context(CONTRACT, None, owner_id="o1")

    assert builds.count == 1 and again is first


# ── flag ON: every input the build reads is in the key ────────────────────


def test_flag_on_key_is_the_incumbent_prefix_plus_the_request_stamp(monkeypatch):
    _set_flag(monkeypatch, "1")
    _Builds(monkeypatch)
    world = _World(monkeypatch)

    api.get_roster_context(CONTRACT, None, owner_id="o1")

    (key,) = list(api._context_cache)
    assert key[:8] == (id(CONTRACT), CONTRACT["generatedAt"], CONTRACT["scrapeTimestamp"]) + (
        "",
        "o1",
        "",
        "",
        True,
    )
    assert key[8] == (True, "2026-10-25", 8, None, world.fetched, True)
    assert len(key) == 9


def test_flag_on_identical_inputs_hit_the_cache(monkeypatch):
    _set_flag(monkeypatch, "1")
    builds = _Builds(monkeypatch)
    _World(monkeypatch)

    first = api.get_roster_context(CONTRACT, None, owner_id="o1")
    again = api.get_roster_context(CONTRACT, None, owner_id="o1")

    assert builds.count == 1 and again is first


@pytest.mark.parametrize(
    ("label", "change"),
    [
        ("rookie window", lambda w: setattr(w, "rookies", False)),
        ("evaluation date", lambda w: setattr(w, "today", date(2026, 10, 26))),
        ("league week", lambda w: setattr(w, "week", 9)),
        ("availability absent", lambda w: setattr(w, "week", None)),
        ("availability reason", lambda w: setattr(w, "reason", "no_league_settings")),
        ("players DB fetchedAt", lambda w: setattr(w, "fetched", w.fetched + 3600.0)),
        # The same fetchedAt, now past the 24 h bound the health read enforces.
        ("players DB age bound", lambda w: setattr(w, "now", w.fetched + 25 * 3600.0)),
    ],
)
def test_flag_on_each_input_change_rebuilds(monkeypatch, label, change):
    _set_flag(monkeypatch, "1")
    builds = _Builds(monkeypatch)
    world = _World(monkeypatch)

    first = api.get_roster_context(CONTRACT, None, owner_id="o1")
    change(world)
    second = api.get_roster_context(CONTRACT, None, owner_id="o1")

    assert builds.count == 2, label
    assert second is not first, label


def test_flag_on_unknown_players_db_time_is_a_value_not_now(monkeypatch):
    _set_flag(monkeypatch, "1")
    builds = _Builds(monkeypatch)
    world = _World(monkeypatch)
    world.fetched = None

    api.get_roster_context(CONTRACT, None, owner_id="o1")
    (key,) = list(api._context_cache)

    assert key[8][4:] == (None, False)
    api.get_roster_context(CONTRACT, None, owner_id="o1")
    assert builds.count == 1


def test_flag_on_real_rookie_window_read_reaches_the_key(monkeypatch):
    """Through the real ``resolve_request_inputs`` (no stub): the date's rookie
    window flipping rebuilds the context."""
    _set_flag(monkeypatch, "1")
    builds = _Builds(monkeypatch)
    window = {"open": True}
    monkeypatch.setattr("src.trade.suggestions._rookies_eligible_today", lambda: window["open"])
    monkeypatch.setattr("src.ros.game_day_live.persisted_players_db_fetched_at", lambda: None)

    api.get_roster_context(CONTRACT, None, owner_id="o1")
    api.get_roster_context(CONTRACT, None, owner_id="o1")
    assert builds.count == 1
    window["open"] = False
    api.get_roster_context(CONTRACT, None, owner_id="o1")
    assert builds.count == 2


def test_a_flag_flip_still_never_serves_across_states(monkeypatch):
    builds = _Builds(monkeypatch)
    _World(monkeypatch)
    _set_flag(monkeypatch, "0")
    api.get_roster_context(CONTRACT, None, owner_id="o1")
    _set_flag(monkeypatch, "1")
    api.get_roster_context(CONTRACT, None, owner_id="o1")
    _set_flag(monkeypatch, "0")
    api.get_roster_context(CONTRACT, None, owner_id="o1")
    assert builds.count == 2  # OFF built once and answered again from its own entry


# ── the players-DB fetchedAt accessor ─────────────────────────────────────


def _db(tmp_path, monkeypatch, body):
    import src.ros.game_day_live as gdl

    path = tmp_path / "nfl_players.json"
    monkeypatch.setattr(gdl, "_players_db_path", lambda: path)
    monkeypatch.setattr(gdl, "_players_db_cache", {})
    if body is not None:
        path.write_text(json.dumps(body), encoding="utf-8")
    return gdl


def test_fetched_at_accessor_is_disk_only_and_unknown_is_none(tmp_path, monkeypatch):
    gdl = _db(tmp_path, monkeypatch, None)
    assert gdl.persisted_players_db_fetched_at() is None  # no file

    gdl = _db(tmp_path, monkeypatch, {"fetchedAt": "2027-01-15T07:59:00+00:00", "players": {}})
    assert gdl.persisted_players_db_fetched_at() == 1_799_999_940.0

    gdl = _db(tmp_path, monkeypatch, {"fetchedAt": "not a time", "players": {}})
    assert gdl.persisted_players_db_fetched_at() is None  # unparseable: unknown, not now

    gdl = _db(tmp_path, monkeypatch, {"fetchedAt": "2027-01-15T07:59:00+00:00"})
    assert gdl.persisted_players_db_fetched_at() is None  # no players mapping: unusable


def test_persisted_players_meta_is_unchanged_by_the_shared_entry(tmp_path, monkeypatch):
    gdl = _db(
        tmp_path,
        monkeypatch,
        {"fetchedAt": "2027-01-15T07:59:00+00:00", "players": {"a": {"team": "X"}}},
    )
    now = 1_800_000_000.0
    assert gdl.persisted_players_meta({"a"}, now=now) == {"a": {"team": "X"}}
    assert gdl.persisted_players_meta({"a", "b"}, now=now) is None  # missing id
    assert gdl.persisted_players_meta({"a"}, now=now + 25 * 3600) is None  # past 24 h
