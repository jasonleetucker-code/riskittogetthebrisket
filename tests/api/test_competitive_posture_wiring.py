"""Wave B (C7-POST-01) — how the canonical posture reaches the trade routes."""

from __future__ import annotations

import pytest

from src.api import gameplan
from src.api import trade_simulator
from src.roster_intel.window import (
    CompetitiveWindow,
    WindowInputs,
    _softmax_affinities,
    competitive_posture,
    season_timing,
)


def _posture(comp=0.9, source="championshipOdds"):
    aff = _softmax_affinities(comp, 0.5, 0.18)
    w = CompetitiveWindow(aff, WindowInputs(comp, 0.5, source, 8), max(aff, key=aff.get))
    return competitive_posture(w, season_timing(None, False, 13))


def test_warm_only_path_never_loads_inputs(monkeypatch):
    """The plain-simulate path reads memory only — no disk, no network."""

    def boom(*a, **k):  # pragma: no cover - the assertion is that it is not called
        raise AssertionError("warm-only path must not load league inputs")

    monkeypatch.setattr(gameplan, "load_league_inputs", boom)
    monkeypatch.setattr(gameplan, "get_league_bundle", boom)
    monkeypatch.setattr(gameplan, "_BUNDLE_CACHE", {})
    with pytest.raises(gameplan.GameplanUnavailable) as exc:
        gameplan.league_competitive_postures(
            "lk", "sp", {}, week=None, in_season=False, build_if_missing=False
        )
    assert exc.value.reason == "league_bundle_not_warm"


def test_warm_only_path_labels_the_bundle_as_last_computed(monkeypatch):
    class _Intel:
        def __init__(self, window):
            self.window = window

    class _Bundle:
        intel = {"o1": _Intel(_posture().window)}
        notes = ()

    monkeypatch.setattr(gameplan, "_BUNDLE_CACHE", {"lk": ("stamp", _Bundle())})
    monkeypatch.setattr(
        gameplan, "load_league_inputs", lambda *a, **k: (_ for _ in ()).throw(AssertionError)
    )
    postures, meta = gameplan.league_competitive_postures(
        "lk", "sp", {}, week=None, in_season=False, build_if_missing=False
    )
    assert meta["bundleFreshness"] == "last_computed"
    assert postures["o1"].label == "PUSH"


def test_foreign_contract_never_supplies_this_leagues_deadline():
    contract = {
        "meta": {"leagueKey": "other"},
        "sleeper": {"leagueSettings": {"trade_deadline": 9}},
    }
    assert gameplan._league_settings_for(contract, "mine") == {}
    own = {"meta": {"leagueKey": "mine"}, "sleeper": {"leagueSettings": {"trade_deadline": 9}}}
    assert gameplan._league_settings_for(own, "mine")["trade_deadline"] == 9


def test_competitive_posture_for_returns_the_team_block(monkeypatch):
    monkeypatch.setattr(
        gameplan,
        "league_competitive_postures",
        lambda *a, **k: ({"o1": _posture()}, {"bundleFreshness": "current"}),
    )
    monkeypatch.setattr("src.api.league_registry.get_scoring_profile", lambda lk: "sp")
    block = trade_simulator.competitive_posture_for(
        {}, "lk", {"ownerId": "o1"}, build_if_missing=True
    )
    assert block["available"] is True and block["label"] == "PUSH"
    assert block["bundleFreshness"] == "current"
    missing = trade_simulator.competitive_posture_for(
        {}, "lk", {"ownerId": "nobody"}, build_if_missing=True
    )
    assert missing == {"available": False, "unavailableReason": "team_not_in_league_bundle"}


def test_competitive_posture_for_names_an_unavailable_bundle(monkeypatch):
    def unavailable(*a, **k):
        raise gameplan.GameplanUnavailable("league_bundle_not_warm", "x")

    monkeypatch.setattr(gameplan, "league_competitive_postures", unavailable)
    monkeypatch.setattr("src.api.league_registry.get_scoring_profile", lambda lk: "sp")
    block = trade_simulator.competitive_posture_for(
        {}, "lk", {"ownerId": "o1"}, build_if_missing=False
    )
    assert block == {"available": False, "unavailableReason": "league_bundle_not_warm"}


def test_no_evidence_posture_publishes_no_confidence():
    d = _posture(source="unavailable").to_dict()
    assert d["label"] == "HOLD" and d["evidence"] == "none"
    assert d["confidence"] is None and d["probabilities"] is None


def test_timing_edges():
    assert season_timing(None, True, 13).phase == "unknown"
    t = season_timing(5, True, 99)  # Sleeper-style "no deadline" sentinel
    assert t.trade_deadline_week is None and t.progress is None
