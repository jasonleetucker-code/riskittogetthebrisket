"""Lane E: surface parity from ONE ``TradeSnapshot`` per case (spec
``docs/trade/NTEAM_TRADE_ENGINE_SPEC.md`` §2.10 I4 / I11, §6.1, §7 Lane E).

TEST-ONLY.  For every case the same snapshot object is read by the engine
called directly, by the private route ``POST /api/trade/analyze-multi`` (flag
forced ON in-test, whatever the production default, §6.1), by the public route
``POST /api/public/league/trade-advisor/analyze`` and -- for the 2-team shape --
by the existing War Room route ``POST /api/trade/analyze``.  Boards, ledgers
and Team Context stand-ins are imported from
``tests/trade/test_multi_team_properties.py`` through
``tests/parity/surface_harness.py``; nothing is copied.

Already pinned elsewhere -- NOT repeated here (checked before writing):

* ``tests/api/test_trade_analyze_multi_cross_surface.py``: private route ==
  ``analyze_trade_n`` byte-for-byte at 2, 3 and 4 teams, both private modes, on
  the REAL archived board only (the module skips without an archive), plus
  decision traceability and quarantine on that board.
* ``tests/api/test_trade_analyze_multi_route.py``: I4 at N = 2 on the real
  board (five ledgers, orphan team listed), route shape, flag-off, errors.
* ``tests/trade/test_public_advisor_parity.py``: public == private route
  fairness (I11) over 14 FIXED shapes of the clean four-team ``main`` league,
  plus the N = 2 band relation; ``test_public_advisor_archive_parity.py`` the
  same engine-level on the real archive.
* ``tests/api/test_public_trade_advisor_privacy.py::
  test_team_context_inputs_never_change_the_public_body``: posture and
  projections only, on that clean league; ``test_multi_team_properties.py::
  test_i11_*``: the engine half (no HTTP, no roster-size change).

What this module adds:

1. **One snapshot object, three consumers** -- a spy on ``analyze_trade_n``
   proves the private route and the public route hand the engine the very
   ``TradeSnapshot`` (and an equal ledger) that the direct call and the test
   built; before this only ``len(trade_ledger._MEMO) == 1`` was asserted.
2. **Route == engine and public == private on every Lane E board scenario**
   (eleven boards: stale / unknown rosters, multi-holder, unknown pick
   inventory, quarantined, stale, off-board and unpriced assets, over-cap,
   traded picks), on seeded send-and-receive ledgers AND near-even package
   cycles (the only generator that reaches FAIR), at N = 2, 3 and 4, from
   every perspective, in both private modes.  No archive is required.
3. **The public body is invariant to every Team Context input over HTTP**,
   including roster capacity and forced drops (registry roster size / taxi
   sweeps) -- which the existing HTTP test never varied -- with the private
   route proving the inputs are live (decisions and forced drops DO move).
4. **I4 on synthetic boards, and its N >= 3 generalisation**: each team's
   ``simulation`` + ``analysis`` equal what the existing ``/api/trade/analyze``
   route returns for that team's own gives / receives (War Room request
   shape), with the allowed differences listed and justified below.
5. A **coverage guard**: the corpus reaches FAIR, NOT FAIR and UNABLE TO
   DETERMINE, per team and overall, at every team count.

Allowed differences from the existing 2-team route (spec I4: "must be listed in
the test with a justification as a correctness fix"):

* ``simulation.ownershipEvidence`` and the decision it gates: the ledger knows
  who owns what (R1); the legacy route is handed labels and cannot.  It only
  appears for a team touching an UNVERIFIABLE asset, and that team must then be
  UNABLE and never YES.
* the ``comparables`` lens at N >= 3: stamped ``not_computed`` by the engine
  (SD-12) while the legacy route always runs its provider.  Exactly three
  paths, exactly that value pair.
"""

from __future__ import annotations

import collections
import contextlib
import json
import re
from typing import Any

import pytest

from src.trade import analyze_service as svc
from src.trade import public_advisor
from src.trade import trade_ledger as tl
from tests.api import test_trade_analyze_multi_route as _route
from tests.api.test_trade_analyze_multi_cross_surface import _canon, _strip
from tests.parity import surface_harness as H
from tests.parity.surface_harness import (  # noqa: F401 -- pytest fixtures, used by name
    surface_client_fixture,
    world_factory_fixture,
)
from tests.trade import test_multi_team_properties as P
from tests.trade.test_multi_team_properties import _pinned  # noqa: F401 -- autouse pins

PUBLIC_RESULT = {"FAIR": "FAIR", "NOT_FAIR": "NOT_FAIR", "UNABLE": "UNABLE_TO_DETERMINE"}
TEAM_COUNTS = (2, 3, 4)


@contextlib.contextmanager
def _spying(monkeypatch):
    """Record every ``analyze_trade_n`` call made inside the block (the routes
    reach it through the module attribute, so the spy sees both)."""
    calls: list[dict[str, Any]] = []
    real = svc.analyze_trade_n

    def spy(snap, ledger, **kw):
        calls.append(
            {
                "snap": snap,
                "ledger": ledger,
                "mode": kw.get("mode"),
                "counterfactuals": kw.get("counterfactuals"),
            }
        )
        return real(snap, ledger, **kw)

    with monkeypatch.context() as m:
        m.setattr(svc, "analyze_trade_n", spy)
        yield calls


def _mode(team_context: bool) -> str:
    return "team_context" if team_context else "asset_only"


# ══ 1 + 2. One snapshot; route == engine; public == private (I11) ═════════════


@pytest.mark.parametrize("scenario", H.SCENARIOS)
def test_one_snapshot_feeds_the_engine_the_private_route_and_the_public_route(
    world_factory, monkeypatch, scenario
):
    w = world_factory(scenario)
    public_policy = public_advisor.public_policy(max_teams=4, max_legs=128)
    checked: collections.Counter = collections.Counter()
    for n in TEAM_COUNTS:
        for teams, legs in H.corpus(w, n):
            where = (scenario, n, teams, legs)
            ledger = w.ledger(teams, legs)
            # One ledger under both products' policies.
            assert w.ledger(teams, legs, policy=public_policy) == ledger, where

            routes: dict[bool, dict[str, Any]] = {}
            for team_context in (True, False):
                mode = _mode(team_context)
                with _spying(monkeypatch) as calls:
                    routes[team_context] = w.private(teams, legs, team_context=team_context)
                # The private route asked the engine once, for this mode, with
                # the ONE snapshot object and an equal ledger.
                assert [(c["mode"], c["counterfactuals"]) for c in calls] == [(mode, True)], where
                assert calls[0]["snap"] is w.snap, where
                assert calls[0]["ledger"] == ledger, where
                # Private route == the engine called directly (flag ON).
                expected = svc.multi_team_payload(
                    w.engine(ledger, mode),
                    snap=w.snap,
                    ledger=ledger,
                    league_key=H.KEY,
                    perspective=None,
                    expected_generation=None,
                )
                assert _canon(_strip(routes[team_context])) == _canon(expected), (where, mode)
            assert routes[True]["generation"] == routes[False]["generation"] == w.snap.generation

            legs_out = [
                {"id": x.asset_id, "from": x.from_roster_id, "to": x.to_roster_id}
                for x in sorted(ledger.legs, key=lambda leg: leg.asset_id)
            ]
            for perspective in teams:
                with _spying(monkeypatch) as calls:
                    pub = w.public(teams, legs, perspective)
                # The public route asked for the market-fairness reduction only,
                # from the same snapshot object and ledger.
                assert [(c["mode"], c["counterfactuals"]) for c in calls] == [
                    ("market_fairness", False)
                ], where
                assert calls[0]["snap"] is w.snap and calls[0]["ledger"] == ledger, where
                assert pub["generation"] == public_advisor.public_generation(w.snap), where
                assert pub["perspectiveRosterId"] == perspective and pub["teamCount"] == n, where
                assert [t["rosterId"] for t in pub["teams"]] == sorted(teams), where
                assert pub["trade"] == legs_out, where
                # I11: per-team result == private fairness.state, overall ==
                # fairnessOverall, in BOTH private modes.
                for team_context, route in routes.items():
                    by_rid = {t["rosterId"]: t for t in route["teams"]}
                    for row in pub["teams"]:
                        private_team = by_rid[row["rosterId"]]
                        fairness = private_team["fairness"]
                        ctx = (where, perspective, row["rosterId"], _mode(team_context))
                        assert row["result"] == PUBLIC_RESULT[fairness["state"]], ctx
                        assert row["reasonCode"] == fairness["reasonCode"], ctx
                        own = {
                            r["assetId"]
                            for r in (*private_team["gives"], *private_team["receives"])
                        }
                        assert set(row["unavailableAssetIds"]) <= own, ctx
                    overall = route["summary"]["fairnessOverall"]
                    assert pub["overall"]["result"] == PUBLIC_RESULT[overall["state"]], where
                    assert pub["overall"]["reasonCode"] == overall["reasonCode"], where
            checked[n] += 1
    assert all(checked[n] >= 2 for n in TEAM_COUNTS), checked


def test_the_corpus_reaches_every_public_result_at_every_team_count(world_factory):
    """Coverage guard for the parity sweep above (same corpus and seeds): FAIR,
    NOT FAIR and UNABLE TO DETERMINE all occur, for single teams and for the
    overall verdict, at 2, 3 and 4 teams -- so the equalities are not vacuous
    on one result class."""
    per_team: dict[int, set[str]] = collections.defaultdict(set)
    overall: dict[int, set[str]] = collections.defaultdict(set)
    for scenario in H.SCENARIOS:
        w = world_factory(scenario)
        for n in TEAM_COUNTS:
            for teams, legs in H.corpus(w, n):
                pub = w.public(teams, legs, teams[0])
                per_team[n] |= {t["result"] for t in pub["teams"]}
                overall[n].add(pub["overall"]["result"])
    every = {"FAIR", "NOT_FAIR", "UNABLE_TO_DETERMINE"}
    for n in TEAM_COUNTS:
        assert per_team[n] == every, (n, per_team[n])
        assert overall[n] == every, (n, overall[n])


# ══ 3. The public body ignores every Team Context input (I11 / privacy M1) ════

#: Scenarios whose private decisions can move with the inputs (the others are
#: dominated by evidence gates, where the public answer is trivially stable).
LIVE_SCENARIOS = ("clean", "over_cap", "traded_picks")
TC_SCENARIOS = LIVE_SCENARIOS + ("off_board", "quarantined", "stale_value", "pick_unknown")
POSTURES = ("PUSH", "HOLD", "RETOOL", "REBUILD", None)
UTILITY_PPG = (None, -3.0, 0.0, 3.0)
ROSTER_SIZES = (99, 6, 3)
TAXI_SIZES = (0, 2)


def _private_signature(w: H.World, cases) -> tuple[Any, ...]:
    """What the PRIVATE route says under the current inputs: every team's
    headline and its roster-capacity read (limit, over-limit, forced drops)."""
    out = []
    for teams, legs in cases:
        body = w.private(teams, legs, team_context=True, counterfactuals=False)
        for t in body["teams"]:
            cap = t["simulation"].get("rosterCapacity") or {}
            out.append(
                (
                    t["rosterId"],
                    t["analysis"]["decision"]["headline"],
                    cap.get("rosterLimit"),
                    cap.get("overLimitAfter"),
                    tuple(
                        sorted(
                            str(d.get("playerId") or d.get("name") or d)
                            for d in cap.get("forcedDrops") or []
                        )
                    ),
                )
            )
    return tuple(out)


@pytest.mark.parametrize("scenario", TC_SCENARIOS)
def test_public_payload_is_invariant_to_every_team_context_input(
    world_factory, monkeypatch, scenario
):
    from src.trade import roster_capacity

    w = world_factory(scenario)
    cases = [
        case for n in TEAM_COUNTS for case in H.corpus(w, n, random_count=1, near_even=1, tag="tc")
    ]
    assert len(cases) >= 5

    def public_bodies(world: H.World) -> list[dict[str, Any]]:
        return [world.public(teams, legs, teams[0]) for teams, legs in cases]

    reference = public_bodies(w)
    signatures: set[tuple[Any, ...]] = set()
    capacity_signatures: set[tuple[Any, ...]] = set()

    # Posture: four labels and an unavailable bundle.
    for label in POSTURES:
        w.posture["label"] = label
        signatures.add(_private_signature(w, cases))
        assert public_bodies(w) == reference, ("posture", label)
    w.posture["label"] = "HOLD"

    # Roster utility ("projections"): none, three constants, the labelled lens.
    for ppg in (*UTILITY_PPG, "labelled"):
        utility = P._labelled_roster_utility if ppg == "labelled" else P._constant_utility(ppg)
        with monkeypatch.context() as m:
            m.setattr(roster_capacity, "evaluate_final_roster_utility", utility)
            signatures.add(_private_signature(w, cases))
            assert public_bodies(w) == reference, ("utility", ppg)

    # Roster capacity and forced drops: the registry's roster size / taxi slots
    # (same contract object, so only the capacity input moves).
    for size in ROSTER_SIZES:
        for taxi in TAXI_SIZES:
            variant = w.settings | {"rosterSize": size, "taxiSize": taxi}
            v = world_factory(scenario, settings=variant, contract=w.contract)
            assert v.snap is not w.snap
            capacity_signatures.add(_private_signature(v, cases))
            assert public_bodies(v) == reference, ("capacity", size, taxi)
            # The private route reads the SAME snapshot the public one does.
            assert v.snap.roster_settings["rosterSize"] == size

    if scenario in LIVE_SCENARIOS:
        # The inputs are live: private decisions and capacity reads DO move.
        assert len(signatures) >= 2, "Team Context inputs never moved a private decision"
        assert len(capacity_signatures) >= 3, "roster size never moved the private capacity read"
        # Forced drops really occur at the smallest roster size, privately.
        small = world_factory(
            scenario, settings=w.settings | {"rosterSize": 3, "taxiSize": 0}, contract=w.contract
        )
        assert any(sig[4] for sig in _private_signature(small, cases)), "no forced drop reached"
        assert public_bodies(small) == reference


# ══ 4. I4 on synthetic boards, generalised to every team of N >= 3 ═══════════

_COMPARABLES_PATHS = (
    re.compile(r"^analysis\.decision\.coverage\[\d+\]\.exclusionReason$"),
    re.compile(r"^analysis\.dimensions\[\d+\]\.unavailableReason$"),
    re.compile(r"^analysis\.lenses\.comparables\.unavailableReason$"),
)


def _diff_paths(a: Any, b: Any, path: str = "") -> list[tuple[str, Any, Any]]:
    """Every leaf path where ``a`` and ``b`` differ: ``(path, a, b)``; a key in
    only one side reads ``<absent>`` on the other."""
    absent = "<absent>"
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[tuple[str, Any, Any]] = []
        for key in sorted(set(a) | set(b)):
            sub = f"{path}.{key}" if path else str(key)
            out += _diff_paths(a.get(key, absent), b.get(key, absent), sub)
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += _diff_paths(x, y, f"{path}[{i}]")
        return out
    return [] if _canon(a) == _canon(b) else [(path, a, b)]


def _war_room(w: H.World, rid: int, ledger: tl.ValidatedLedger, team_context: bool):
    flows = tl.team_flows(ledger, rid)
    request = {
        **_route._war_room_request(w.snap, rid, flows, team_context=team_context),
        "leagueKey": H.KEY,
    }
    res = w.client.post("/api/trade/analyze", json=request, headers=H.PRIVATE_HEADER)
    assert res.status_code == 200, res.text
    return res.json()


@pytest.mark.parametrize("n_teams", TEAM_COUNTS)
@pytest.mark.parametrize("scenario", H.SCENARIOS)
def test_each_team_equals_the_war_room_route_for_its_own_flows(world_factory, scenario, n_teams):
    """I4 (N = 2) and its generalisation (N = 3, 4): a team's ``simulation`` +
    ``analysis`` from ``analyze_trade_n`` equal the EXISTING ``/api/trade/analyze``
    route's answer for that team's own gives / receives, driven by the War
    Room's real request shape.  The public per-team result relates to the same
    route's market band: FAIR  <=>  band ``fair`` whenever the team is
    evaluable."""
    w = world_factory(scenario)
    verified = unverifiable_teams = 0
    for teams, legs in H.corpus(w, n_teams, random_count=2, near_even=1, tag="i4"):
        where = (scenario, n_teams, teams, legs)
        ledger = w.ledger(teams, legs)
        pub = w.public(teams, legs, teams[0])
        public_by_rid = {t["rosterId"]: t["result"] for t in pub["teams"]}
        for team_context in (True, False):
            engine = w.engine(ledger, _mode(team_context))
            for rid in ledger.teams:
                ctx = (where, rid, _mode(team_context))
                route = _war_room(w, rid, ledger, team_context)
                eng = json.loads(json.dumps(engine["teams"][rid], default=str))
                route_sim = {
                    k: v for k, v in route.items() if k not in _route.ROUTE_ONLY_SIMULATION_KEYS
                }
                route_analysis = {
                    k: v
                    for k, v in route["analysis"].items()
                    if k not in _route.ROUTE_ONLY_ANALYSIS_KEYS
                }
                touches_unverifiable = bool(eng["unverifiableAssetIds"])
                sim_diff = _diff_paths(eng["simulation"], route_sim)
                if touches_unverifiable:
                    # Listed difference 1: ownership evidence only the ledger has.
                    assert [p for p, _a, _b in sim_diff] == ["ownershipEvidence"], ctx
                    assert eng["fairness"]["state"] == "UNABLE", ctx
                    assert eng["analysis"]["decision"]["headline"] != "YES", ctx
                    unverifiable_teams += 1
                    continue
                assert sim_diff == [], ctx
                for path, got, want in _diff_paths(eng["analysis"], route_analysis, "analysis"):
                    # Listed difference 2: comparables are not computed at N >= 3.
                    assert n_teams >= 3, (ctx, path, got, want)
                    assert any(rx.match(path) for rx in _COMPARABLES_PATHS), (ctx, path)
                    assert (got, want) == ("not_computed", "lane_e_stub"), (ctx, path, got, want)
                verified += 1
                if not team_context and public_by_rid[rid] != "UNABLE_TO_DETERMINE":
                    level = route["analysis"]["lenses"]["market"]["detail"]["band"]["level"]
                    assert (public_by_rid[rid] == "FAIR") == (level == "fair"), (ctx, level)
    assert verified + unverifiable_teams > 0
    if scenario in ("stale_rosters", "unknown_rosters"):
        # Nothing is provable on these boards: every team is the listed case.
        assert verified == 0 and unverifiable_teams > 0
    elif scenario in ("clean", "over_cap", "traded_picks"):
        assert verified > 0
