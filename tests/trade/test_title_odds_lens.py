"""Trade -> title-odds delta: Analyze Trade's non-voting ``titleOdds`` lens
(DYN10 #4, ``src/trade/title_odds_lens.py``).

Pinned here:

* a hand-checkable synthetic league: the roster bridge's weekly-mean change is
  the traded quarterbacks' point difference (rosValue / 2.7, the fallback
  points model), exactly opposite for the two teams, and the odds move the way
  that change says, outside the noise band;
* a change inside the noise band is reported, with ``significant: false``;
* every unavailable state is ``state: "unavailable"`` with a reason and no
  team rows — never a zero delta;
* the lens never votes and never reaches ``trade_decision``: the decision is
  identical with and without it;
* flag OFF (the default): nothing is computed and every payload is
  byte-identical, on the packet, on the N-team composer and on the route;
* the public advisor never receives it;
* the disclosure is the owner-approved wording, byte for byte.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.api import feature_flags
from src.league_intel import sim_calibration
from src.public_league import playoff_odds
from src.ros import lineup, playoff_sim
from src.trade import analyze_service, trade_decision
from src.trade import title_odds_lens as tol
from src.trade.analyze_trade import TITLE_ODDS_DIMENSION, analyze_trade

_ENV = "RISKIT_FEATURE_TRADE_TITLE_ODDS_LENS"
_REPO = Path(__file__).resolve().parents[2]
_OWNERS = ("a", "b", "c", "d")
_SLOTS = ["QB", "RB"]


# ── the synthetic league ─────────────────────────────────────────────────


def _player(pid: str, pos: str, ros: float) -> dict:
    return {
        "playerId": pid,
        "canonicalName": pid,
        "position": pos,
        "rosValue": ros,
        "fantasyPositions": [pos],
    }


def _roster(owner: str, qb: float, rb: float) -> list[dict]:
    # Two lineup slots (QB, RB).  Four kickers are priced (the bridge needs
    # five priced players) but can never start, so the weekly score is the
    # QB's draw plus the RB's draw — which is what makes the delta checkable.
    return [
        _player(f"{owner}_qb", "QB", qb),
        _player(f"{owner}_rb", "RB", rb),
        *(_player(f"{owner}_k{i}", "K", 1.0) for i in range(4)),
    ]


def _rows(**overrides) -> list[dict]:
    rosters = {
        "a": _roster("a", 60.0, 30.0),
        "b": _roster("b", 20.0, 30.0),
        "c": _roster("c", 40.0, 30.0),
        "d": _roster("d", 40.0, 30.0),
    }
    rosters.update(overrides)
    # Equal ROS strength everywhere: every z-score is 0, so the bridge's blend
    # factor is exactly 1.0 and its delta is in plain points.
    return [{"ownerId": o, "teamRosStrength": 50.0, "fullRoster": r} for o, r in rosters.items()]


_SCHEDULE = [(w, x, y) for w in (8, 9, 10) for x, y in (("a", "b"), ("c", "d"))]
_RECORD = {o: {"wins": 4, "losses": 3, "ties": 0} for o in _OWNERS}


def _snapshot():
    season = SimpleNamespace(
        season="2026",
        league_id="L1",
        league={"settings": {"playoff_teams": 2, "playoff_seed_type": 1, "playoff_week_start": 11}},
        rosters=[],
        matchups_by_week={},
        regular_season_weeks=[],
        num_teams=4,
    )
    return SimpleNamespace(
        managers=SimpleNamespace(by_owner_id={}),
        current_season=season,
        seasons=[season],
        root_league_id="L1",
        generated_at=None,
    )


@pytest.fixture
def league(monkeypatch):
    """dynasty_main's real recorded playoff rules and registry; a 4-team,
    2-seed bracket; a fixed base distribution per team; no I/O."""
    dists = {
        o: playoff_sim._TeamDist(owner_id=o, mean=100.0, sd=15.0, pf_to_date=700.0, basis="presim")
        for o in _OWNERS
    }
    pf = {o: 700.0 for o in _OWNERS}
    monkeypatch.setattr(
        "src.ros.team_strength.resolve_snapshot_league_key", lambda *_a, **_k: "dynasty_main"
    )
    monkeypatch.setattr(playoff_sim, "remaining_schedule", lambda *_a, **_k: list(_SCHEDULE))
    monkeypatch.setattr(playoff_sim, "_remaining_schedule", lambda *_a, **_k: list(_SCHEDULE))
    monkeypatch.setattr(
        playoff_sim,
        "_current_standings",
        lambda *_a, **_k: (dict(_RECORD), {"medianGame": False, "state": "not_applicable"}),
    )
    monkeypatch.setattr(
        playoff_sim, "_build_team_distributions", lambda *_a, **_k: (dict(dists), dict(pf))
    )
    monkeypatch.setattr(
        playoff_sim, "_load_ros_strength_map", lambda *_a, **_k: {o: 50.0 for o in _OWNERS}
    )
    monkeypatch.setattr(playoff_sim, "_league_best_ball", lambda *_a, **_k: True)
    # The suite points the league registry at nothing (tests/conftest.py); in
    # production dynasty_main's ``bestBall: true`` answers this.
    monkeypatch.setattr(tol, "_league_best_ball", lambda _k: True)
    monkeypatch.setattr(playoff_sim.metrics, "display_name_for", lambda _s, o: f"Team {o}")
    monkeypatch.setattr(playoff_odds, "_final_week_set", lambda *_a, **_k: set(range(1, 8)))
    monkeypatch.setattr(lineup, "load_league_starter_slots", lambda *_a, **_k: list(_SLOTS))
    monkeypatch.setattr(
        sim_calibration, "load_points_model", lambda *_a, **_k: sim_calibration.PointsModel()
    )
    return _snapshot()


def _moves(*moves, teams=("a", "b")):
    return tol.TradeMoves(teams=tuple(teams), player_moves=tuple(moves))


def _compute(snapshot, moves, rows=None, **kw):
    return tol.compute_title_odds(
        snapshot,
        league_key="dynasty_main",
        moves=moves,
        team_strength_rows=_rows() if rows is None else rows,
        n_simulations=kw.pop("n_simulations", 3000),
        twin_weeks=kw.pop("twin_weeks", 200),
        **kw,
    )


def _team(payload, owner):
    return next(t for t in payload["teams"] if t["ownerId"] == owner)


# ── a hand-checkable league ──────────────────────────────────────────────


def test_star_quarterback_trade_moves_both_teams_the_checkable_way(league):
    """a sends its 60-rosValue QB to b for b's 20-rosValue QB.

    By hand: the fallback points model scores a QB at rosValue / 2.7 a week,
    so a's QB slot falls from 22.2 to 7.4 points, about -14.8 a week, and b's
    rises by the same.  The bridge seeds every draw by PLAYER, so the two
    deltas are exact mirror images.  With every team at 100 points a week, a
    15-point swing must cost a playoff odds and hand them to b — far outside
    the noise band.
    """
    payload = _compute(league, _moves(("a_qb", "a", "b"), ("b_qb", "b", "a")))
    assert payload["state"] == "ok", payload
    a, b = _team(payload, "a"), _team(payload, "b")
    a_delta = a["strengthDelta"]["meanDelta"]
    b_delta = b["strengthDelta"]["meanDelta"]
    assert -16.5 < a_delta < -13.0, a_delta
    # Mirror images up to the bridge's rounding of each arm's mean.
    assert b_delta == pytest.approx(-a_delta, abs=1e-3)
    assert a["strengthDelta"]["blendFactor"] == 1.0  # every z is 0
    assert a["rosterChanged"] and b["rosterChanged"]

    assert a["playoff"]["delta"] < -0.05 and a["playoff"]["significant"] is True
    assert b["playoff"]["delta"] > 0.05 and b["playoff"]["significant"] is True
    lo, hi = a["playoff"]["deltaCi"]
    assert lo <= a["playoff"]["delta"] <= hi and hi < 0
    assert a["playoff"]["after"] == pytest.approx(a["playoff"]["before"] + a["playoff"]["delta"])
    assert a["championship"]["delta"] < 0 and b["championship"]["delta"] > 0
    # Only the trade's own teams are reported.
    assert {t["ownerId"] for t in payload["teams"]} == {"a", "b"}
    assert payload["nSimulations"] == 3000 and payload["twinWeeks"] == 200
    assert payload["sharedSeed"] == tol.IMPACT_SEED
    assert payload["disclosure"]["text"] == tol.ODDS_DISCLOSURE
    assert payload["role"] == "context_not_vote"
    # What the bridge says not to feed is reported, not fed.
    assert any("NOT fed into simulate_trade_impact" in s for s in payload["assumptions"])
    assert "sdDelta" in a["strengthDelta"]


def test_the_computation_is_deterministic(league):
    moves = _moves(("a_qb", "a", "b"), ("b_qb", "b", "a"))
    assert json.dumps(_compute(league, moves), sort_keys=True) == json.dumps(
        _compute(league, moves), sort_keys=True
    )


def test_both_arms_share_one_bracket_and_one_seed(league, monkeypatch):
    """The lens hands the bracket to ``simulate_trade_impact`` to resolve ONCE;
    it never passes its own seeds, byes or reseed rule."""
    seen = []
    real = playoff_sim.simulate_trade_impact

    def spy(snapshot, **kwargs):
        seen.append(dict(kwargs))
        return real(snapshot, **kwargs)

    monkeypatch.setattr(playoff_sim, "simulate_trade_impact", spy)
    _compute(league, _moves(("a_qb", "a", "b"), ("b_qb", "b", "a")))
    assert len(seen) == 1
    assert not {"playoff_seeds", "bye_seeds", "reseed"} & set(seen[0])
    assert seen[0]["seed"] == tol.IMPACT_SEED
    assert set(seen[0]["strength_delta"]) == {"a", "b"}


def test_a_change_inside_the_noise_band_is_not_significant(league):
    """Swapping running backs of 30 and 30.3 rosValue moves each team well
    under a point a week (0.1 by value; the rest is the bridge's own sampling
    noise over 200 paired weeks of two different players' draws — the noise
    the lens's assumptions disclose).  That is far inside the season
    simulation's noise, so the interval spans zero and ``significant`` is
    false."""
    rows = _rows(
        b=[
            *_roster("b", 20.0, 30.0)[:1],
            _player("b_rb", "RB", 30.3),
            *_roster("b", 20.0, 30.0)[2:],
        ]
    )
    payload = _compute(league, _moves(("a_rb", "a", "b"), ("b_rb", "b", "a")), rows=rows)
    assert payload["state"] == "ok", payload
    for owner in ("a", "b"):
        team = _team(payload, owner)
        assert 0 < abs(team["strengthDelta"]["meanDelta"]) < 1.0
        for metric in ("playoff", "championship"):
            lo, hi = team[metric]["deltaCi"]
            assert lo <= 0.0 <= hi, (owner, metric, team[metric])
            assert team[metric]["significant"] is False


def test_a_picks_only_trade_is_measured_as_exactly_zero(league):
    """No rostered player moves: both rosters are unchanged, so the delta is a
    MEASURED zero (the bridge is not even run), never a default."""
    payload = _compute(league, _moves())
    assert payload["state"] == "ok"
    for owner in ("a", "b"):
        team = _team(payload, owner)
        assert team["rosterChanged"] is False
        assert team["strengthDelta"] == {
            "ownerId": owner,
            "meanDelta": 0.0,
            "rosterUnchanged": True,
        }
        assert team["playoff"]["delta"] == 0.0 and team["playoff"]["significant"] is False
    assert payload["twinWeeks"] == 0


# ── unavailable is never zero ────────────────────────────────────────────


def _assert_unavailable(payload, reason):
    assert payload["state"] == "unavailable", payload
    assert payload["reason"] == reason
    assert payload["teams"] == []
    assert payload["detail"]
    assert payload["disclosure"]["text"] == tol.ODDS_DISCLOSURE


def test_a_league_without_recorded_playoff_rules_is_not_configured(league):
    payload = tol.compute_title_odds(
        league, league_key="dynasty_new", moves=_moves(), team_strength_rows=_rows()
    )
    _assert_unavailable(payload, tol.REASON_LEAGUE_NOT_CONFIGURED)
    _assert_unavailable(
        tol.compute_title_odds(league, league_key=None, moves=_moves(), team_strength_rows=_rows()),
        tol.REASON_LEAGUE_NOT_CONFIGURED,
    )


def test_a_start_sit_league_is_refused(league, monkeypatch):
    monkeypatch.setattr(tol, "_league_best_ball", lambda _k: False)
    _assert_unavailable(_compute(league, _moves()), tol.REASON_NOT_BEST_BALL)


def test_no_snapshot_and_a_foreign_snapshot_are_refused(league, monkeypatch):
    _assert_unavailable(_compute(None, _moves()), tol.REASON_NO_SNAPSHOT)
    monkeypatch.setattr(
        "src.ros.team_strength.resolve_snapshot_league_key", lambda *_a, **_k: "dynasty_new"
    )
    _assert_unavailable(_compute(league, _moves()), tol.REASON_SNAPSHOT_MISMATCH)


def test_preseason_with_no_schedule_is_refused(league, monkeypatch):
    monkeypatch.setattr(playoff_sim, "remaining_schedule", lambda *_a, **_k: [])
    _assert_unavailable(_compute(league, _moves(("a_qb", "a", "b"))), tol.REASON_NO_SCHEDULE)


def test_missing_team_strength_and_truncated_rosters_are_refused(league):
    _assert_unavailable(
        _compute(league, _moves(("a_qb", "a", "b")), rows=[]),
        playoff_sim.TEAM_STRENGTH_UNAVAILABLE,
    )
    rows = _rows()
    rows[1] = {"ownerId": "b", "teamRosStrength": 50.0, "startingLineup": rows[1]["fullRoster"]}
    _assert_unavailable(
        _compute(league, _moves(("a_qb", "a", "b")), rows=rows), tol.REASON_FULL_ROSTER
    )


def test_a_player_not_on_the_sending_roster_is_refused(league):
    _assert_unavailable(_compute(league, _moves(("c_qb", "a", "b"))), tol.REASON_ROSTER_MISMATCH)


def test_an_unsimulable_changed_roster_refuses_the_whole_lens(league):
    """A changed roster with too few priced players: the lens refuses rather
    than enter a partial map, which would present a one-sided trade."""
    thin = [_player("b_qb", "QB", 20.0), _player("b_rb", "RB", 30.0)]
    payload = _compute(league, _moves(("a_k0", "a", "b")), rows=_rows(b=thin))
    _assert_unavailable(payload, tol.REASON_STRENGTH_DELTA)
    reasons = {d["ownerId"]: d["unavailableReason"] for d in payload["strengthDeltas"]}
    assert reasons["b"] and reasons["a"] is None


def test_a_playoff_engine_refusal_passes_through_with_its_reason(league, monkeypatch):
    monkeypatch.setattr(
        playoff_sim,
        "simulate_trade_impact",
        lambda *_a, **_k: {
            "playoff": [],
            "championship": [],
            "nSimulations": 0,
            "methodology": "m",
            "unsimulable": {"reason": "median_setting_unknown", "detail": "not a 0% chance"},
        },
    )
    payload = _compute(league, _moves(("a_qb", "a", "b"), ("b_qb", "b", "a")))
    _assert_unavailable(payload, "median_setting_unknown")
    assert payload["detail"] == "not a 0% chance"


def test_an_exception_is_the_lens_unavailable_not_a_broken_analysis():
    def boom():
        raise RuntimeError("x")

    _assert_unavailable(tol.guarded(boom), tol.REASON_ERROR)


# ── the 2-team route's counterparty ──────────────────────────────────────


def _sim(sending=(), receiving=(), picks_from=None, owner="a"):
    def _asset(pid):
        return {"name": pid, "pos": "QB", "assetClass": "offense", "playerId": pid, "value": 1}

    sim = {
        "team": {"ownerId": owner, "name": owner, "rosterId": 1},
        "sending": [_asset(p) for p in sending],
        "receiving": [_asset(p) for p in receiving],
        "unresolvedIn": [],
        "unresolvedOut": [],
        "ownedPickChecks": {"incomingPickHolders": []},
    }
    if picks_from is not None:
        sim["receiving"].append({"name": "2027 1.05", "pos": "PICK", "assetClass": "pick"})
        sim["ownedPickChecks"]["incomingPickHolders"] = [
            {"assetId": "pick:x", "ownershipState": "owned", "holderRosterId": picks_from}
        ]
    return sim


def test_two_team_counterparty_is_the_holder_of_the_incoming_players():
    moves = tol.moves_from_two_team(_sim(["a_qb"], ["b_qb"]), _rows())
    assert moves.unavailable_reason is None
    assert moves.teams == ("a", "b") and moves.counterparty_inferred is True
    assert set(moves.player_moves) == {("a_qb", "a", "b"), ("b_qb", "b", "a")}


def test_two_team_counterparty_from_an_incoming_pick_holder():
    moves = tol.moves_from_two_team(_sim(["a_qb"], picks_from=3), _rows(), owner_by_rid={3: "c"})
    assert moves.teams == ("a", "c") and moves.player_moves == (("a_qb", "a", "c"),)


def test_two_team_counterparty_states_that_cannot_be_resolved():
    rows = _rows()
    assert (
        tol.moves_from_two_team(_sim(["a_qb"]), rows).unavailable_reason
        == tol.REASON_COUNTERPARTY_UNRESOLVED
    )
    assert (
        tol.moves_from_two_team(_sim(["a_qb"], ["b_qb", "c_qb"]), rows).unavailable_reason
        == tol.REASON_MULTIPLE_COUNTERPARTIES
    )
    assert (
        tol.moves_from_two_team(_sim(["c_qb"], ["b_qb"]), rows).unavailable_reason
        == tol.REASON_ROSTER_MISMATCH
    )
    unresolved = {**_sim(["a_qb"], ["b_qb"]), "unresolvedIn": ["Nobody"]}
    assert (
        tol.moves_from_two_team(unresolved, rows).unavailable_reason == tol.REASON_ASSET_UNRESOLVED
    )
    # Picks only, no holder: nothing moves, nothing to resolve.
    assert tol.moves_from_two_team(_sim(), rows) == tol.TradeMoves(teams=("a",))


def test_two_team_entry_point_composes_the_inferred_trade(league):
    payload = tol.title_odds_for_two_team(
        _sim(["a_qb"], ["b_qb"]),
        snapshot=league,
        league_key="dynasty_main",
        contract=None,
        team_strength_rows=_rows(),
        n_simulations=2000,
        twin_weeks=120,
    )
    assert payload["state"] == "ok" and payload["counterpartyInferred"] is True
    assert any("inferred" in s for s in payload["assumptions"])
    assert _team(payload, "a")["playoff"]["delta"] < 0


# ── the lens in the packet: context, never a vote ────────────────────────


@pytest.fixture(scope="module")
def war_room_sim():
    from tests.trade import war_room_ui_payloads as gen

    built = gen.build("consolidation")
    return {k: v for k, v in built.items() if k not in ("analysis", "_fixture")}


def _ok_payload(owner="o1"):
    row = {
        "ownerId": owner,
        "displayName": "Us",
        "rosterChanged": True,
        "strengthDelta": {"ownerId": owner, "meanDelta": 4.0},
        "available": True,
        "playoff": {
            "before": 0.4,
            "after": 0.5,
            "delta": 0.1,
            "deltaCi": [0.05, 0.15],
            "significant": True,
        },
        "championship": {
            "before": 0.1,
            "after": 0.12,
            "delta": 0.02,
            "deltaCi": [-0.01, 0.05],
            "significant": False,
        },
    }
    return {
        "version": tol.LENS_VERSION,
        "state": "ok",
        "teams": [row],
        "disclosure": tol.disclosure(),
    }


def test_the_lens_is_context_and_never_votes(war_room_sim):
    packet = analyze_trade(war_room_sim, title_odds=_ok_payload())
    lens = packet["lenses"]["titleOdds"]
    assert lens["dimension"] == TITLE_ODDS_DIMENSION
    assert lens["votes"] is False and lens["available"] is True
    assert lens["direction"] == "context"
    assert lens["detail"]["playoff"]["delta"] == 0.1
    assert lens["detail"]["role"] == "context_not_vote"
    dims = {d["dimension"]: d for d in packet["dimensions"]}
    assert dims[TITLE_ODDS_DIMENSION]["votes"] is False
    assert TITLE_ODDS_DIMENSION not in {d["dimension"] for d in packet["unavailableDimensions"]}


def test_an_unavailable_lens_keeps_the_dimension_named_unavailable(war_room_sim):
    """An unavailable (or mode-excluded) lens must not retire the "not included
    yet" entry the client renders its season-odds caveat from."""
    packet = analyze_trade(war_room_sim, title_odds=tol.unavailable(tol.REASON_NO_SCHEDULE))
    assert packet["lenses"]["titleOdds"]["available"] is False
    assert TITLE_ODDS_DIMENSION in {d["dimension"] for d in packet["unavailableDimensions"]}
    sim = {**war_room_sim, "teamContext": {"applied": False, "mode": "asset_only"}}
    asset_only = analyze_trade(sim, title_odds=_ok_payload())
    assert asset_only["lenses"]["titleOdds"]["available"] is False
    assert TITLE_ODDS_DIMENSION in {d["dimension"] for d in asset_only["unavailableDimensions"]}


def test_an_unavailable_payload_stays_unavailable_and_never_votes(war_room_sim):
    payload = tol.unavailable(tol.REASON_NO_SCHEDULE)
    lens = analyze_trade(war_room_sim, title_odds=payload)["lenses"]["titleOdds"]
    assert lens["available"] is False and lens["votes"] is False
    assert lens["unavailableReason"] == tol.REASON_NO_SCHEDULE
    assert "direction" not in lens
    other = analyze_trade(war_room_sim, title_odds=_ok_payload(owner="someone_else"))
    assert other["lenses"]["titleOdds"]["unavailableReason"] == tol.REASON_TEAM_NOT_SIMULATED


def test_asset_only_excludes_the_lens_by_mode(war_room_sim):
    sim = {**war_room_sim, "teamContext": {"applied": False, "mode": "asset_only"}}
    lens = analyze_trade(sim, title_odds=dict(tol.ASSET_ONLY_MARKER))["lenses"]["titleOdds"]
    assert lens["available"] is False and lens["votes"] is False
    assert lens["unavailableReason"] == tol.REASON_ASSET_ONLY


def test_the_lens_never_reaches_trade_decision(war_room_sim, monkeypatch):
    """Nothing the lens carries is an input to the decision owner, and the
    decision, leaning, confidence, reasons and status quo are identical with
    and without it — significant or not."""
    calls: list[tuple] = []
    for name in ("leaning", "decide", "status_quo"):
        real = getattr(trade_decision, name)

        def spy(*args, _real=real, _name=name, **kwargs):
            calls.append((_name, args, kwargs))
            return _real(*args, **kwargs)

        monkeypatch.setattr(trade_decision, name, spy)
    without = analyze_trade(war_room_sim)
    calls_without = len(calls)
    with_lens = analyze_trade(war_room_sim, title_odds=_ok_payload())
    for _name, args, kwargs in calls[calls_without:]:
        for value in (*args, *kwargs.values()):
            assert getattr(value, "name", None) != TITLE_ODDS_DIMENSION
            assert "titleOdds" not in json.dumps(value, default=str)
    for key in (
        "decision",
        "statusQuo",
        "recommendation",
        "confidence",
        "basis",
        "reasonsFor",
        "reasonsAgainst",
        "uncertainty",
        "topUncertainty",
    ):
        assert with_lens[key] == without[key], key
    for key in ("market", "roster", "feasibility", "evidence", "posture", "comparables"):
        assert with_lens["lenses"][key] == without["lenses"][key], key


# ── flag OFF: byte-identical ─────────────────────────────────────────────


@pytest.fixture
def flag_off(monkeypatch):
    monkeypatch.setenv(_ENV, "0")
    feature_flags.reload()
    yield
    feature_flags.reload()


def test_flag_is_off_by_default(monkeypatch):
    monkeypatch.delenv(_ENV, raising=False)
    feature_flags.reload()
    try:
        assert tol.enabled() is False
    finally:
        feature_flags.reload()


def test_flag_off_packet_is_byte_identical(war_room_sim, flag_off):
    """No ``title_odds`` -> no ``titleOdds`` key, the dimension still named
    unavailable, and the committed War Room fixtures (generated without the
    lens) still regenerate byte for byte."""
    from tests.trade import war_room_ui_payloads as gen

    packet = analyze_trade(war_room_sim)
    assert "titleOdds" not in packet["lenses"]
    assert TITLE_ODDS_DIMENSION not in {d["dimension"] for d in packet["dimensions"]}
    assert [
        d["reason"]
        for d in packet["unavailableDimensions"]
        if d["dimension"] == TITLE_ODDS_DIMENSION
    ] == ["counterfactual_not_wired"]
    assert json.dumps(packet, sort_keys=True) == json.dumps(
        analyze_trade(war_room_sim, title_odds=None), sort_keys=True
    )
    for name in ("consolidation", "asset-only"):
        assert gen.fixture_path(name).read_text(encoding="utf-8") == gen.serialize(gen.build(name))


def _multi(snap, mode, teams=(1, 2, 3), legs=None, **kw):
    from src.trade import trade_ledger as tl

    legs = legs or [("p:101", 1, 2), ("p:102", 1, 3), ("p:201", 2, 1), ("p:301", 3, 1)]
    ledger = tl.validate_ledger(
        snap,
        teams=list(teams),
        legs=[{"id": a, "from": f, "to": t} for a, f, t in legs],
        policy=tl.LedgerPolicy(),
    )
    if mode != "market_fairness":
        kw.setdefault(
            "posture_resolver", lambda *_a, **_k: {"available": False, "unavailableReason": "t"}
        )
    out = analyze_service.analyze_trade_n(snap, ledger, mode=mode, counterfactuals=False, **kw)
    return ledger, out


def _teams_json(out: dict) -> str:
    return json.dumps(out["teams"], sort_keys=True, default=str)


def test_n_team_composer_one_payload_per_trade_and_flag_off_identity(monkeypatch):
    """Without a provider (flag OFF) every team's analysis is byte-identical to
    the pre-lens one.  With one, it is called ONCE for the whole trade, every
    team projects its own row, and no decision moves.  Asset-Only passes the
    excluded-by-mode marker without computing; market fairness (the public
    advisor) never calls it."""
    from tests.trade import multi_team_support as mts

    mts.pin_league_scarcity(monkeypatch)
    snap = mts.synthetic_snapshot()
    calls = []

    def provider(ledger):
        calls.append(ledger)
        rows = []
        for i, owner in enumerate(("owner1", "owner2", "owner3")):
            row = _ok_payload(owner)["teams"][0]
            row["playoff"] = {**row["playoff"], "delta": 0.01 * (i + 1)}
            rows.append(row)
        return {**_ok_payload(), "teams": rows}

    _ledger, base = _multi(snap, "team_context")
    _ledger, none = _multi(snap, "team_context", title_odds_provider=None)
    assert _teams_json(base) == _teams_json(none)
    for team in base["teams"].values():
        assert "titleOdds" not in team["analysis"]["lenses"]

    ledger, lit = _multi(snap, "team_context", title_odds_provider=provider)
    assert len(calls) == 1 and calls[0].canonical_key() == ledger.canonical_key()
    for rid, team in lit["teams"].items():
        lens = team["analysis"]["lenses"]["titleOdds"]
        assert lens["votes"] is False and lens["available"] is True
        assert lens["detail"]["perspectiveOwnerId"] == f"owner{rid}"
        assert lens["detail"]["playoff"]["delta"] == pytest.approx(0.01 * rid)
        assert team["analysis"]["decision"] == base["teams"][rid]["analysis"]["decision"]
        assert team["fairness"] == base["teams"][rid]["fairness"]
        assert team["category"] == base["teams"][rid]["category"]
    assert lit["summary"] == base["summary"]

    _ledger, asset_only = _multi(snap, "asset_only", title_odds_provider=provider)
    assert len(calls) == 1
    for team in asset_only["teams"].values():
        lens = team["analysis"]["lenses"]["titleOdds"]
        assert lens["unavailableReason"] == tol.REASON_ASSET_ONLY and lens["votes"] is False

    _ledger, public = _multi(snap, "market_fairness", title_odds_provider=provider)
    _ledger, public_base = _multi(snap, "market_fairness")
    assert len(calls) == 1
    assert _teams_json(public) == _teams_json(public_base)


def test_n_team_moves_come_from_the_ledger():
    from src.trade import trade_ledger as tl
    from tests.trade import multi_team_support as mts

    snap = mts.synthetic_snapshot()
    ledger = tl.validate_ledger(
        snap,
        teams=[1, 2],
        legs=[{"id": "p:101", "from": 1, "to": 2}, {"id": "p:201", "from": 2, "to": 1}],
        policy=tl.LedgerPolicy(),
    )
    moves = tol.moves_from_ledger(ledger, snap)
    assert moves.teams == ("owner1", "owner2")
    assert set(moves.player_moves) == {("101", "owner1", "owner2"), ("201", "owner2", "owner1")}
    assert moves.counterparty_inferred is False


def test_the_public_advisor_never_builds_the_lens():
    text = (_REPO / "src/trade/public_advisor.py").read_text(encoding="utf-8")
    assert "title_odds" not in text and "titleOdds" not in text


def test_server_passes_the_lens_only_behind_the_flag():
    """Both private routes reach the lens only through ``enabled()``: OFF
    passes nothing, so ``analyze_for_team`` / ``analyze_trade_n`` see exactly
    the pre-lens call."""
    text = (_REPO / "server.py").read_text(encoding="utf-8")
    assert text.count("_title_odds_lens.enabled()") == 2
    assert "**_title_odds_extra" in text and "**_title_odds_kw" in text
    assert (
        '_title_odds_kw = {"title_odds_provider": _title_odds} if _title_odds_lens.enabled() else {}'
        in text
    )


# ── the disclosure ───────────────────────────────────────────────────────


def test_the_disclosure_is_the_owner_approved_wording():
    js = (_REPO / "frontend/lib/odds-disclosure.js").read_text(encoding="utf-8")
    match = re.search(r"ODDS_EXPERIMENTAL_DISCLOSURE\s*=\s*\"([^\"]+)\"", js)
    assert match, "the frontend owner of the odds disclosure moved"
    assert tol.ODDS_DISCLOSURE == match.group(1)
    register = (_REPO / "docs/owner/OWNER_DECISION_REGISTER.md").read_text(encoding="utf-8")
    assert tol.ODDS_DISCLOSURE_DECISION in register and tol.ODDS_DISCLOSURE in register


def test_the_bounds_are_fixed_and_small():
    assert tol.N_SIMULATIONS <= playoff_sim.DEFAULT_SIMULATIONS
    assert 0 < tol.TWIN_WEEKS <= 500
