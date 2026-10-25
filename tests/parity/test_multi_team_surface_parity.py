"""Lane E surface parity for the N-team trade engine (spec
``docs/trade/NTEAM_TRADE_ENGINE_SPEC.md`` §7 Lane E row, §9 "parity" row).

ONE ``TradeSnapshot`` per case, four surfaces composed from it:

1. the private route ``POST /api/trade/analyze-multi`` (flag forced ON in-test,
   spec §6.1 — the production default stays OFF);
2. the shared engine ``analyze_service.analyze_trade_n`` called directly;
3. the public reduction (``public_advisor.evaluate`` / ``reduce_fairness``) and
   the public route ``POST /api/public/league/trade-advisor/analyze`` (flag and
   launch gate forced open in-test; ``brisket_trade_advisor`` stays OFF);
4. at N = 2, the existing 2-team War Room route ``POST /api/trade/analyze``
   driven by the War Room's real request shape (I4).

Invariants covered: I4 (2-team equivalence through the multi ROUTE, not only the
engine), I11 (public = reduction of private, and the public body is invariant
to every Team Context input: posture, projections, capacity scarcity, the
roster limit and so the forced drops), plus the one-snapshot property itself
(every surface reads the SAME snapshot object) and the spec §2.8 rule that
market fairness is identical in every mode.

What is deliberately NOT re-implemented here: the War Room request builder and
the route-only key sets (``test_trade_analyze_multi_route``), the structure
builders, route comparables provider and payload stripping
(``test_trade_analyze_multi_cross_surface``), and the real-board / synthetic
league / archived-trade builders (``tests/trade/multi_team_support``).

Two boards: the REAL archived board (skips when no complete archive exists),
and the LABELLED synthetic 4-team league of ``multi_team_support`` (always
runs; it reproduces the spec's I14 worked example), the latter through a
seeded ``random.Random`` property loop.
"""

from __future__ import annotations

import hashlib
import json
import random
from typing import Any

import pytest

from src.api import feature_flags
from src.trade import analyze_service as svc
from src.trade import public_advisor as pa
from src.trade import team_verdicts as tv
from src.trade import trade_ledger as tl
from tests.api import test_trade_analyze_multi_cross_surface as _xs
from tests.api import test_trade_analyze_multi_route as _route
from tests.trade import multi_team_support as mts

LEAGUE = "dynasty_main"
ANALYZE_PUBLIC = "/api/public/league/trade-advisor/analyze"
#: Private engine state -> public result (spec §4.3 reduction rules).
PUBLIC_RESULT = {"FAIR": "FAIR", "NOT_FAIR": "NOT_FAIR", "UNABLE": "UNABLE_TO_DETERMINE"}

#: The route module's fixtures (real ``dynasty_main`` registry copy, private
#: flag forced on, real archived board installed as the live contract).
app = _route.app
flag_on = _route.flag_on
real_registry = _route.real_registry

_canon = _xs._canon
_strip = _xs._strip


@pytest.fixture(autouse=True)
def _pinned_scarcity(monkeypatch):
    """R1-2: no live / TTL-cached team-strength read may decide a comparison
    (``multi_team_support.pin_league_scarcity``)."""
    return mts.pin_league_scarcity(monkeypatch)


# ── Deterministic Team Context inputs (LABELLED, invented for tests) ───────


def _labelled_ppg(salt: str):
    """A LABELLED deterministic projection lookup at the best-ball seam.  The
    numbers are invented; only the wiring is under test."""

    def lookup(ids, season=None, scoring_settings=None):
        out = {}
        for i in ids:
            h = int(hashlib.sha256(f"{salt}|{i}".encode()).hexdigest()[:6], 16)
            out[str(i)] = round(2.0 + (h % 220) / 10.0, 1)
        return out, {"state": "available", "source": f"LABELLED_TEST_PPG_{salt}", "season": 2026}

    return lookup


def _install_ppg(monkeypatch, lookup) -> None:
    from src.bestball import replacement
    from src.roster_intel import best_ball_utility as bbu

    monkeypatch.setattr(bbu, "league_scored_ppg_by_id", lookup)
    monkeypatch.setattr(replacement, "league_scored_ppg_by_id", lookup)


class _Posture:
    """A LABELLED synthetic posture object (``.to_dict()`` like the owner's)."""

    def __init__(self, owner_id: str, label: str, probs: dict[str, float]) -> None:
        self.owner_id, self.label, self.probs = owner_id, label, probs

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "probabilities": dict(self.probs),
            "confidence": "LOW",
            "paramsVersion": "posture_v1_prior",
            "notes": ["SYNTHETIC_FIXTURE_POSTURE (LABELLED)", self.owner_id],
        }


def _install_posture(monkeypatch, contract, label: str, probs: dict[str, float]) -> None:
    import src.api.gameplan as gameplan

    owners = {str(t.get("ownerId") or "") for t in contract["sleeper"]["teams"]} - {""}
    monkeypatch.setattr(
        gameplan,
        "league_competitive_postures",
        lambda league_key, profile, c, *, build_if_missing: (
            {o: _Posture(o, label, probs) for o in owners},
            {"bundleFreshness": "fresh"},
        ),
    )


def _install_scarcity(monkeypatch, scale: float) -> None:
    from src.league_intel.replacement import ScarcityComponents
    from src.trade import roster_capacity

    fixed = {
        pos: ScarcityComponents(pos, None, None, min(1.0, w * scale), None, None, None)
        for pos, w in mts.PINNED_WAIVER_SCARCITY.items()
    }
    monkeypatch.setattr(roster_capacity, "_league_scarcity", lambda lk, c: (dict(fixed), None))


def _raise(*_a, **_k):
    raise AssertionError("LANE-E: a Team Context reader was called on the public path")


class _Unlimited:
    """The public limiter, out of the way: these tests issue hundreds of
    identical-IP requests and the limiter is not what is under test."""

    def charge(self, _charges):
        return False, 0


@pytest.fixture
def surfaces(app, flag_on, monkeypatch):
    """Both private and public surfaces on the real board: private flag on
    (``flag_on``), public flag on and its owner-reserved launch gate forced
    open, LABELLED projections installed, the limiter out of the way.  Every
    snapshot any surface obtains is recorded."""
    from src.api import public_trade_advisor_api as api

    client, contract = app
    monkeypatch.setenv("RISKIT_FEATURE_BRISKET_TRADE_ADVISOR", "1")
    feature_flags.reload()
    monkeypatch.setattr(api, "_launch_gate_reason", lambda: None)
    monkeypatch.setattr(api, "_limiter", lambda: _Unlimited())
    monkeypatch.setattr("src.bdvm.actuals.current_nfl_season", lambda today=None: 2026)
    _install_ppg(monkeypatch, _labelled_ppg("A"))
    seen: list[Any] = []
    real = tl.snapshot_for

    def spy(*a, **k):
        snap = real(*a, **k)
        seen.append(snap)
        return snap

    monkeypatch.setattr(tl, "snapshot_for", spy)
    yield client, contract, seen
    monkeypatch.delenv("RISKIT_FEATURE_BRISKET_TRADE_ADVISOR", raising=False)
    feature_flags.reload()


# ── Helpers ────────────────────────────────────────────────────────────────


def _settings() -> dict[str, Any]:
    from src.api import league_registry

    return dict(league_registry.get_league_by_key(LEAGUE).roster_settings or {})


def _one_snapshot(contract) -> tl.TradeSnapshot:
    """The snapshot both routes obtain: same arguments, so the same memo entry."""
    return tl.snapshot_for(contract, league_key=LEAGUE, roster_settings=_settings())


def _sends_and_receives(teams, legs) -> bool:
    return {x["from"] for x in legs} == set(teams) == {x["to"] for x in legs}


def _cases(snap, contract) -> list[tuple[str, list[int], list[dict]]]:
    """Directive §11 structures on real rosters, seeded random ledgers, and the
    real recorded own-league trades (reversed, and their structures), kept only
    when every team both sends and receives (the public participation rule,
    privacy M5) so all four surfaces answer the same ledger."""
    out = [c for c in _xs._structures(snap, contract) if not c[0].endswith("random")]
    rng = random.Random(20261025)
    for n in (2, 3, 4):
        teams, legs = mts.random_ledger(snap, rng, n_teams=n, max_per_team=2, send_and_receive=True)
        out.append((f"{n}: seeded random", teams, legs))
    for sides in (2, 3, 4):
        for r in mts.reverse_replays(snap, sides=sides)[:1]:
            out.append(
                (f"{sides}: archived trade reversed @{r['timestamp']}", r["teams"], r["legs"])
            )
        for r in mts.structure_replays(snap, sides=sides)[:2]:
            out.append((f"{sides}: archived structure @{r['timestamp']}", r["teams"], r["legs"]))
    return [(n, sorted(t), [dict(x) for x in lg]) for n, t, lg in out if _sends_and_receives(t, lg)]


def _private_http(client, teams, legs, *, team_context: bool) -> dict:
    res = client.post(
        "/api/trade/analyze-multi",
        json={"leagueKey": LEAGUE, "teams": teams, "assets": legs, "useTeamContext": team_context},
    )
    assert res.status_code == 200, res.text
    return res.json()


def _public_http(client, teams, legs, perspective: int) -> dict:
    res = client.post(
        ANALYZE_PUBLIC,
        json={"perspectiveRosterId": perspective, "teams": teams, "assets": legs},
    )
    assert res.status_code == 200, res.text
    return res.json()


def _public_ledger(snap, teams, legs, perspective: int):
    from src.api import public_trade_advisor_api as api

    policy = pa.public_policy(max_teams=api._config_max_teams(), max_legs=api._config_max_legs())
    return pa.validate(
        snap,
        perspective=perspective,
        teams=teams,
        legs=[(x["id"], x["from"], x["to"]) for x in legs],
        policy=policy,
    )


def _public_body_from(snap, result: pa.FairnessResult, perspective: int) -> dict:
    """The public route's own body assembly over a reduction we computed."""
    from src.api import public_trade_advisor_api as api

    return api._safe_dump(api._analyze_body(LEAGUE, snap, perspective, None, result))


def _reduce_private_body(private: dict, ledger) -> pa.FairnessResult:
    """The public reduction applied to the PRIVATE route's own team entries."""
    inputs = [pa.team_fairness_input(t) for t in private["teams"]]
    return pa.reduce_fairness(
        inputs, overall_state=pa.public_overall_state(inputs), legs=ledger.legs
    )


def _no_perspective(body: dict) -> dict:
    return {k: v for k, v in body.items() if k != "perspectiveRosterId"}


# ══ 1. One snapshot, four surfaces ═════════════════════════════════════════


def test_one_snapshot_private_route_engine_public_and_war_room_agree(surfaces):
    client, contract, seen = surfaces
    snap = _one_snapshot(contract)
    cases = _cases(snap, contract)
    by_n: dict[int, int] = {}
    archived = 0
    war_room_teams = 0
    for name, teams, legs in cases:
        priv_ledger = tl.validate_ledger(snap, teams=teams, legs=legs, policy=tl.private_policy())
        privates: dict[bool, dict] = {}
        for tc in (True, False):
            body = _private_http(client, teams, legs, team_context=tc)
            # (1) == (2): the private route is the engine over this snapshot.
            out = svc.analyze_trade_n(
                snap,
                priv_ledger,
                mode="team_context" if tc else "asset_only",
                counterfactuals=True,
                comparables_provider=_xs._route_provider(),
            )
            expected = svc.multi_team_payload(
                out,
                snap=snap,
                ledger=priv_ledger,
                league_key=LEAGUE,
                perspective=None,
                expected_generation=None,
            )
            assert _canon(_strip(body)) == _canon(expected), (name, tc)
            privates[tc] = body
        market = svc.analyze_trade_n(
            snap, priv_ledger, mode="market_fairness", counterfactuals=False
        )

        # Spec §2.8: per-team market fairness is gross and identical in every
        # mode (the public mode included), so the public answer cannot depend
        # on which private mode it is compared against.
        for rid in priv_ledger.teams:
            ref = _canon(market["teams"][rid]["fairness"])
            for tc, body in privates.items():
                team = next(t for t in body["teams"] if t["rosterId"] == rid)
                assert _canon(team["fairness"]) == ref, (name, rid, tc)
            assert (
                market["summary"]["fairnessOverall"] == privates[True]["summary"]["fairnessOverall"]
            ), name

        # (3) public: the route body == the reduction computed here from the
        # same snapshot, from every perspective (byte-identical apart from the
        # perspective echo).
        public_bodies = []
        for p in teams:
            pub_ledger = _public_ledger(snap, teams, legs, p)
            body = _public_http(client, teams, legs, p)
            assert body == _public_body_from(snap, pa.evaluate(snap, pub_ledger), p), (name, p)
            # I11: the public reduction of the PRIVATE route's team entries is
            # the public answer, with no fail-closed downgrade in between.
            for tc, private in privates.items():
                assert body == _public_body_from(
                    snap, _reduce_private_body(private, pub_ledger), p
                ), (
                    name,
                    p,
                    tc,
                )
            public_bodies.append(_no_perspective(body))
        assert all(b == public_bodies[0] for b in public_bodies), name
        public = public_bodies[0]

        # I11 stated directly: per-team result == private fairness.state (never
        # the headline), reason code carried, overall == fairnessOverall.
        for tc, private in privates.items():
            by_rid = {t["rosterId"]: t for t in private["teams"]}
            assert [r["rosterId"] for r in public["teams"]] == sorted(by_rid)
            for row in public["teams"]:
                fairness = by_rid[row["rosterId"]]["fairness"]
                assert row["result"] == PUBLIC_RESULT[fairness["state"]], (
                    name,
                    row["rosterId"],
                    tc,
                )
                assert row["reasonCode"] == fairness["reasonCode"], (name, row["rosterId"], tc)
                own = {
                    r["assetId"]
                    for r in (
                        *by_rid[row["rosterId"]]["gives"],
                        *by_rid[row["rosterId"]]["receives"],
                    )
                }
                assert set(row["unavailableAssetIds"]) <= own, (name, row["rosterId"])
            overall = private["summary"]["fairnessOverall"]
            assert public["overall"]["result"] == PUBLIC_RESULT[overall["state"]], (name, tc)
            assert public["overall"]["reasonCode"] == overall["reasonCode"], (name, tc)
            assert overall == tv.fairness_overall(t["fairness"]["state"] for t in private["teams"])
        assert public["teamCount"] == len(teams)
        assert public["trade"] == sorted(
            ({"id": x["id"], "from": x["from"], "to": x["to"]} for x in legs), key=lambda x: x["id"]
        )

        # (4) N = 2: the existing War Room route, on its real request shape,
        # equals the multi ROUTE's team entry; the one fairness owner over the
        # War Room's own output gives the same state the public side published.
        if len(teams) == 2:
            two = tl.validate_ledger(snap, teams=teams, legs=legs, policy=tl.LedgerPolicy())
            for tc, private in privates.items():
                by_rid = {t["rosterId"]: t for t in private["teams"]}
                for rid in two.teams:
                    flows = tl.team_flows(two, rid)
                    res = client.post(
                        "/api/trade/analyze",
                        json=_route._war_room_request(snap, rid, flows, team_context=tc),
                    )
                    assert res.status_code == 200, res.text
                    route = res.json()
                    mine = by_rid[rid]
                    route_sim = {
                        k: v for k, v in route.items() if k not in _route.ROUTE_ONLY_SIMULATION_KEYS
                    }
                    route_analysis = {
                        k: v
                        for k, v in route["analysis"].items()
                        if k not in _route.ROUTE_ONLY_ANALYSIS_KEYS
                    }
                    mine_analysis = {
                        k: v
                        for k, v in mine["analysis"].items()
                        if k not in _route.ROUTE_ONLY_ANALYSIS_KEYS
                    }
                    # Fairness is posture-free, so it is compared even for the
                    # orphan team (R15's one listed difference is posture).
                    assert _canon(tv.team_fairness(route_sim, route_analysis)) == _canon(
                        mine["fairness"]
                    ), (name, rid, tc)
                    row = next(r for r in public["teams"] if r["rosterId"] == rid)
                    assert row["result"] == PUBLIC_RESULT[mine["fairness"]["state"]]
                    if not str(snap.teams_by_roster_id[rid].get("ownerId") or ""):
                        # The ONE listed I4 difference (spec R15): an orphan team.
                        assert (
                            mine["simulation"]["competitivePosture"]["unavailableReason"]
                            == "owner_identity_ambiguous"
                        )
                        assert route["competitivePosture"]["available"] is False
                        assert (
                            mine["analysis"]["decision"]["headline"]
                            == route["analysis"]["decision"]["headline"]
                        )
                        continue
                    assert _canon(mine["simulation"]) == _canon(route_sim), (name, rid, tc)
                    assert _canon(mine_analysis) == _canon(route_analysis), (name, rid, tc)
                    war_room_teams += 1
        by_n[len(teams)] = by_n.get(len(teams), 0) + 1
        archived += "archived" in name

    # One snapshot: every surface read the very object this test evaluated.
    assert seen and all(s is snap for s in seen)
    assert set(by_n) == {2, 3, 4}, by_n
    assert war_room_teams >= 4
    # Real recorded own-league trades are in the parity set whenever the
    # tracked trade history still validates against the archived rosters
    # (it is refreshed by automation, so this is conditional, never assumed).
    replayable = any(
        _sends_and_receives(r["teams"], r["legs"])
        for s in (2, 3, 4)
        for r in (*mts.reverse_replays(snap, sides=s), *mts.structure_replays(snap, sides=s))
    )
    assert archived >= 1 or not replayable


# ══ 2. The public body is invariant to every Team Context input ════════════


def _invariance_cases(snap, contract):
    picked: dict[int, list] = {}
    for case in _cases(snap, contract):
        bucket = picked.setdefault(len(case[1]), [])
        if len(bucket) < 2:
            bucket.append(case)
    return [c for n in sorted(picked) for c in picked[n]]


def _publics(client, cases) -> list[dict]:
    return [_public_http(client, t, lg, t[0]) for _n, t, lg in cases]


def _team_context_privates(client, cases) -> list[str]:
    return [_canon(_strip(_private_http(client, t, lg, team_context=True))) for _n, t, lg in cases]


def _write_registry(tmp_path, monkeypatch, *, roster_size: int) -> None:
    from src.api import league_registry

    real = json.loads((mts.REPO / "config/leagues/registry.json").read_text(encoding="utf-8"))
    main = next(lg for lg in real["leagues"] if lg["key"] == LEAGUE)
    main = {**main, "rosterSettings": {**main["rosterSettings"], "rosterSize": roster_size}}
    path = tmp_path / f"registry_{roster_size}.json"
    path.write_text(
        json.dumps({"schemaVersion": 1, "defaultLeagueKey": LEAGUE, "leagues": [main]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()


def test_public_payload_is_invariant_to_team_context_inputs(surfaces, monkeypatch, tmp_path):
    """I11 / privacy M1.  Each Team Context input is changed twice: once to a
    DIFFERENT value (the private Team Context answer must move on at least one
    case — so the invariance is not vacuous), and once to a reader that
    RAISES (the public path must not read it at all).  The public body stays
    byte-identical throughout."""
    client, contract, _seen = surfaces
    snap = _one_snapshot(contract)
    cases = _invariance_cases(snap, contract)
    assert {len(t) for _n, t, _lg in cases} == {2, 3, 4}
    baseline = _publics(client, cases)
    private_base = _team_context_privates(client, cases)
    moved: dict[str, bool] = {}

    def check(kind: str, *, private_should_move: bool) -> None:
        assert _publics(client, cases) == baseline, kind
        if private_should_move:
            moved[kind] = _team_context_privates(client, cases) != private_base

    with monkeypatch.context() as m:
        _install_posture(
            m, contract, "REBUILD", {"PUSH": 0.02, "HOLD": 0.08, "RETOOL": 0.2, "REBUILD": 0.7}
        )
        check("posture", private_should_move=True)
    with monkeypatch.context() as m:
        import src.api.gameplan as gameplan
        from src.api import trade_simulator

        m.setattr(gameplan, "league_competitive_postures", _raise)
        m.setattr(trade_simulator, "competitive_posture_for", _raise)
        check("posture readers raise", private_should_move=False)

    with monkeypatch.context() as m:
        _install_ppg(m, _labelled_ppg("B"))
        check("projections", private_should_move=True)
    with monkeypatch.context() as m:
        _install_ppg(m, _raise)
        check("projection readers raise", private_should_move=False)

    with monkeypatch.context() as m:
        _install_scarcity(m, 3.0)
        check("capacity scarcity", private_should_move=True)
    with monkeypatch.context() as m:
        from src.trade import roster_capacity

        m.setattr(roster_capacity, "_league_scarcity", _raise)
        m.setattr(roster_capacity, "forced_drop_cost", _raise)
        check("capacity readers raise", private_should_move=False)

    # Roster limit -> forced drops.  A cap far below every real roster forces
    # releases on any trade that grows a roster; a huge cap forces none.  A
    # different registry setting is a different snapshot memo key, so this is
    # the one variant that does not reuse the case's snapshot object.
    with monkeypatch.context() as m:
        _write_registry(tmp_path, m, roster_size=12)
        tl.clear_snapshot_memo()
        check("roster limit (forced drops)", private_should_move=True)
        _write_registry(tmp_path, m, roster_size=500)
        tl.clear_snapshot_memo()
        check("roster limit (no forced drops)", private_should_move=False)
    from src.api import league_registry

    league_registry.reload_registry()
    tl.clear_snapshot_memo()
    assert _publics(client, cases) == baseline

    # Liveness: each varied input really is a Team Context input on this board.
    assert moved == {
        "posture": True,
        "projections": True,
        "capacity scarcity": True,
        "roster limit (forced drops)": True,
    }, moved


# ══ 3. LABELLED synthetic league: seeded property loop (always runs) ═══════


def _labelled_posture(contract, league_key, team, *, build_if_missing):
    return {
        "available": True,
        "label": "PUSH",
        "evidence": "measured",
        "probabilities": {"PUSH": 0.7, "HOLD": 0.2, "RETOOL": 0.05, "REBUILD": 0.05},
        "confidence": "medium",
        "paramsVersion": "posture_v1_prior",
        "notes": ["SYNTHETIC_FIXTURE_POSTURE (LABELLED)"],
    }


def _synthetic_surfaces(snap, teams, legs) -> tuple[dict, dict, pa.FairnessResult]:
    """``(team_context result, asset_only result, public reduction)`` from one
    snapshot."""
    ledger = tl.validate_ledger(snap, teams=teams, legs=legs, policy=tl.private_policy())
    tc = svc.analyze_trade_n(
        snap, ledger, mode="team_context", counterfactuals=False, posture_resolver=_labelled_posture
    )
    ao = svc.analyze_trade_n(
        snap, ledger, mode="asset_only", counterfactuals=False, posture_resolver=_labelled_posture
    )
    pub_ledger = pa.validate(
        snap,
        perspective=teams[0],
        teams=teams,
        legs=[(x["id"], x["from"], x["to"]) for x in legs],
        policy=pa.public_policy(max_teams=4, max_legs=128),
    )
    return tc, ao, pa.evaluate(snap, pub_ledger)


def _assert_public_is_reduction(name, snap, teams, legs) -> pa.FairnessResult:
    tc, ao, public = _synthetic_surfaces(snap, teams, legs)
    pub_ledger = pa.validate(
        snap,
        perspective=teams[0],
        teams=teams,
        legs=[(x["id"], x["from"], x["to"]) for x in legs],
        policy=pa.public_policy(max_teams=4, max_legs=128),
    )
    for mode, out in (("team_context", tc), ("asset_only", ao)):
        entries = [out["teams"][rid] for rid in sorted(out["teams"])]
        inputs = [pa.team_fairness_input(e) for e in entries]
        assert (
            pa.reduce_fairness(
                inputs, overall_state=pa.public_overall_state(inputs), legs=pub_ledger.legs
            )
            == public
        ), (name, mode)
        for row in public.teams:
            fairness = out["teams"][row.roster_id]["fairness"]
            assert row.result == PUBLIC_RESULT[fairness["state"]], (name, mode, row.roster_id)
            assert row.reason_code == fairness["reasonCode"], (name, mode, row.roster_id)
        overall = out["summary"]["fairnessOverall"]
        assert public.overall.result == PUBLIC_RESULT[overall["state"]], (name, mode)
        assert public.overall.reason_code == overall["reasonCode"], (name, mode)
    return public


def test_synthetic_i14_example_public_equals_private():
    """The spec's I14 one-to-many case on the LABELLED synthetic board: A +610
    ``slight``, B -1000 ``unfair``, C +500 ``unfair``.  Under fairness_bands_v2
    only ``fair`` counts as a fair trade (OD-F1), so all three teams and the
    overall are NOT FAIR, publicly and privately alike."""
    snap = mts.synthetic_snapshot()
    legs = [
        {"id": "p:101", "from": 1, "to": 2},
        {"id": "p:102", "from": 1, "to": 3},
        {"id": "p:201", "from": 2, "to": 1},
        {"id": "p:301", "from": 3, "to": 1},
    ]
    tc, _ao, _pub = _synthetic_surfaces(snap, [1, 2, 3], legs)
    levels = {rid: tc["teams"][rid]["fairness"]["level"] for rid in (1, 2, 3)}
    assert levels == {1: "slight", 2: "unfair", 3: "unfair"}
    public = _assert_public_is_reduction("I14", snap, [1, 2, 3], legs)
    assert [(r.roster_id, r.result) for r in public.teams] == [
        (1, "NOT_FAIR"),
        (2, "NOT_FAIR"),
        (3, "NOT_FAIR"),
    ]
    assert public.overall.result == "NOT_FAIR"
    assert public.overall.note is not None  # N >= 3 note


def test_synthetic_seeded_property_public_is_reduction_and_team_context_free(monkeypatch):
    """Seeded property loop over the LABELLED synthetic league: 2, 3 and 4-team
    ledgers (players, owned picks, the unpriced asset), every one with every
    team sending and receiving.  For each: the public reduction equals the
    private fairness in both private modes, and it is unchanged — the very
    same ``FairnessResult`` — when every Team Context reader is made to raise
    and when the roster limit is shrunk to 3 (below every synthetic roster, so
    any roster-growing trade is over the cap on the private side)."""
    snap = mts.synthetic_snapshot()
    small = tl.build_trade_snapshot(
        mts.synthetic_league(),
        league_key=mts.SYNTH_KEY,
        roster_settings={**mts.SYNTH_SETTINGS, "rosterSize": 3},
        now=mts.PINNED_NOW,
    )
    rng = random.Random(1025)
    seen_n: dict[int, int] = {}
    seen_results: set[str] = set()
    for i in range(48):
        n = (2, 3, 4)[i % 3]
        teams, legs = mts.random_ledger(snap, rng, n_teams=n, max_per_team=3, send_and_receive=True)
        public = _assert_public_is_reduction(f"seed#{i}", snap, teams, legs)
        seen_n[n] = seen_n.get(n, 0) + 1
        seen_results |= {r.result for r in public.teams} | {public.overall.result}
        pub_ledger = pa.validate(
            snap,
            perspective=teams[-1],
            teams=teams,
            legs=[(x["id"], x["from"], x["to"]) for x in legs],
            policy=pa.public_policy(max_teams=4, max_legs=128),
        )
        # Perspective selects the default view only: the reduction is the same.
        assert pa.evaluate(snap, pub_ledger) == public, i
        small_ledger = pa.validate(
            small,
            perspective=teams[0],
            teams=teams,
            legs=[(x["id"], x["from"], x["to"]) for x in legs],
            policy=pa.public_policy(max_teams=4, max_legs=128),
        )
        assert pa.evaluate(small, small_ledger) == public, i
        with monkeypatch.context() as m:
            import src.api.gameplan as gameplan
            from src.api import trade_simulator
            from src.trade import roster_capacity

            m.setattr(gameplan, "league_competitive_postures", _raise)
            m.setattr(trade_simulator, "competitive_posture_for", _raise)
            m.setattr(roster_capacity, "_league_scarcity", _raise)
            m.setattr(roster_capacity, "forced_drop_cost", _raise)
            _install_ppg(m, _raise)
            assert pa.evaluate(snap, pub_ledger) == public, i
    assert seen_n == {2: 16, 3: 16, 4: 16}
    # The generator reaches every public result (the unpriced asset gives UNABLE).
    assert seen_results >= {"NOT_FAIR", "UNABLE_TO_DETERMINE"}, seen_results
