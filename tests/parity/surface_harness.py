"""Lane E shared HTTP harness: ONE Lane E scenario board served through BOTH the
real private route (``POST /api/trade/analyze-multi``) and the real public
routes (``/api/public/league/trade-advisor/*``), plus the engine called
directly, all on the SAME ``TradeSnapshot`` object.

TEST-ONLY.  Nothing here touches ``src/``, ``server.py``, ``frontend/`` or
``config/``; every flag, registry and seam is installed with ``monkeypatch``
and removed again.  The board generators, scenario catalogue, seeded ledger
generator and labelled Team Context stand-ins are IMPORTED from
``tests/trade/test_multi_team_properties.py`` (PR #1935) and never copied:

* ``P._league(scenario)`` -- the eleven board scenarios (clean, off-board,
  quarantined, stale value, multi-holder, unknown pick inventory, unpriced
  pick, stale / unknown rosters, over-cap, traded picks);
* ``P.gen_ledger`` -- the seeded routed-ledger generator;
* ``P._posture_resolver`` / ``P._constant_utility`` /
  ``P._labelled_roster_utility`` -- LABELLED Team Context stand-ins.

Why a registry per world.  The routes resolve the league, its roster settings
and the public-league identity from the league registry; the Lane E league is
the LABELLED synthetic ``synth`` league, so each world writes a one-league
registry (default, active) whose ``rosterSettings`` are the scenario's.
Rosters are stamped ``live`` and fetched an hour ago so ownership is provable
on the real clock the routes read (``rosterFetchedAt`` of the generator is a
pinned 2026-10-20 time, six days stale today); the ``stale_rosters`` /
``unknown_rosters`` scenarios keep their own stamps and so stay unprovable.

Who is authenticated.  ``X-Lane-E-Private: 1`` marks a private call; the
public routes are called WITHOUT it, so a public answer can never lean on a
session by accident.
"""

from __future__ import annotations

import copy
import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from src.trade import trade_ledger as tl
from tests.trade import multi_team_support as mts
from tests.trade import test_multi_team_properties as P

KEY = P.KEY
#: A distinctive fake Sleeper league id: any appearance in a public body or
#: header is a raw-Sleeper-id leak (the privacy suite scans for it).
SLEEPER_LEAGUE_ID = "L-SYNTH-7731"
PRIVATE_HEADER = {"X-Lane-E-Private": "1"}
ANALYZE = "/api/public/league/trade-advisor/analyze"
TEAMS_URL = "/api/public/league/trade-advisor/teams"
PRIVATE_ANALYZE = "/api/trade/analyze-multi"

SCENARIOS = P.SCENARIOS
#: ``team_context`` is only meaningful where the generator can produce a YES /
#: NO; every scenario is exercised in every mode below.
MODES = ("team_context", "asset_only")


def settings_for(scenario: str) -> dict[str, Any]:
    return dict(P.OVER_CAP_SETTINGS if scenario == "over_cap" else mts.SYNTH_SETTINGS)


def registry_json(settings: dict[str, Any], *, extra_leagues: bool = True) -> dict[str, Any]:
    leagues: list[dict[str, Any]] = [
        {
            "key": KEY,
            "displayName": "Synthetic League",
            "sleeperLeagueId": SLEEPER_LEAGUE_ID,
            "scoringProfile": "superflex_tep15_ppr1",
            "active": True,
            "rosterSettings": settings,
        }
    ]
    if extra_leagues:
        leagues += [
            {
                "key": "side",
                "displayName": "Side",
                "sleeperLeagueId": "L-SIDE-0042",
                "active": True,
                "rosterSettings": {"teamCount": 10},
            },
            {
                "key": "retired",
                "displayName": "Retired",
                "sleeperLeagueId": "L-RET-0043",
                "active": False,
                "rosterSettings": {},
            },
        ]
    return {"schemaVersion": 1, "defaultLeagueKey": KEY, "leagues": leagues}


class _Posture:
    """A LABELLED synthetic posture object (``.to_dict()`` like the owner's)."""

    def __init__(self, owner_id: str, label: str) -> None:
        self.owner_id = owner_id
        self.label = label

    def to_dict(self) -> dict[str, Any]:
        probabilities = {k: 0.1 for k in ("PUSH", "HOLD", "RETOOL", "REBUILD")}
        probabilities[self.label] = 0.7
        return {
            "label": self.label,
            "probabilities": probabilities,
            "confidence": "LOW",
            "paramsVersion": "posture_v1_prior",
            "notes": ["LABELLED synthetic posture (Lane E)", self.owner_id],
        }


def stub_comparables(*_a: Any, **_k: Any) -> dict[str, Any]:
    """The non-voting ``marketCorroboration`` evidence, replaced by a fixed
    LABELLED answer so no box-local market ledger can decide a comparison."""
    return {"state": "unavailable", "reason": "lane_e_stub"}


@dataclass
class World:
    """One scenario board and the three ways to ask about it."""

    client: Any
    scenario: str
    contract: dict[str, Any]
    settings: dict[str, Any]
    snap: tl.TradeSnapshot
    registry_path: Any
    #: The posture label every team reports to Team Context (mutable: tests
    #: sweep it; shared by every world of one factory).  ``None`` = the league
    #: bundle is unavailable.
    posture: dict[str, str | None] = field(default_factory=lambda: {"label": "HOLD"})

    # -- ledgers -----------------------------------------------------------

    def ledger(self, teams, legs, *, policy: tl.LedgerPolicy | None = None) -> tl.ValidatedLedger:
        return tl.validate_ledger(
            self.snap, teams=list(teams), legs=[dict(x) for x in legs], policy=policy or P.POLICY
        )

    # -- the engine, called directly --------------------------------------

    def engine(self, ledger: tl.ValidatedLedger, mode: str, *, counterfactuals: bool = True):
        from src.trade import analyze_service as svc

        return svc.analyze_trade_n(
            self.snap,
            ledger,
            mode=mode,
            counterfactuals=counterfactuals,
            comparables_provider=lambda flows, simulation: stub_comparables(),
        )

    # -- the private route --------------------------------------------------

    def private_response(
        self,
        teams,
        legs,
        *,
        team_context: bool,
        perspective: int | None = None,
        counterfactuals: bool = True,
    ):
        body: dict[str, Any] = {
            "leagueKey": KEY,
            "teams": list(teams),
            "assets": [dict(x) for x in legs],
            "useTeamContext": team_context,
            "counterfactuals": counterfactuals,
        }
        if perspective is not None:
            body["perspectiveRosterId"] = perspective
        return self.client.post(PRIVATE_ANALYZE, json=body, headers=PRIVATE_HEADER)

    def private(self, teams, legs, **kw) -> dict[str, Any]:
        res = self.private_response(teams, legs, **kw)
        assert res.status_code == 200, res.text
        return res.json()

    # -- the public route ----------------------------------------------------

    def public_response(self, teams, legs, perspective: int, **extra):
        body = {
            "perspectiveRosterId": perspective,
            "teams": list(teams),
            "assets": [dict(x) for x in legs],
            **extra,
        }
        return self.client.post(ANALYZE, json=body)

    def public(self, teams, legs, perspective: int, **extra) -> dict[str, Any]:
        res = self.public_response(teams, legs, perspective, **extra)
        assert res.status_code == 200, res.text
        return res.json()


_FETCHED_AT: list[datetime] = []


def fetched_at() -> datetime:
    """The roster-fetch stamp of every world in this process: one hour before the
    first world was built (well inside the six-hour freshness budget for any
    realistic run), then FIXED -- so bodies compared across separately built
    worlds carry the same ``rosters.asOf`` date even across UTC midnight."""
    if not _FETCHED_AT:
        _FETCHED_AT.append(datetime.now(timezone.utc) - timedelta(hours=1))
    return _FETCHED_AT[0]


def contract_for(scenario: str) -> dict[str, Any]:
    """The scenario contract with its rosters stamped fresh on the REAL clock
    (see the module docstring); a fresh deep copy per call."""
    contract = P._league(scenario)
    sleeper = contract["sleeper"]
    if sleeper.get("rosterSource") is not None:
        sleeper["rosterFetchedAt"] = fetched_at().isoformat()
    return contract


@pytest.fixture(scope="module", name="surface_client")
def surface_client_fixture():
    """One TestClient (one lifespan startup) per test module."""
    from fastapi.testclient import TestClient

    import server

    with TestClient(server.app) as client:
        yield client


@pytest.fixture(name="world_factory")
def world_factory_fixture(surface_client, monkeypatch, tmp_path):
    """``build(scenario, *, settings=None, mutate=None, contract=None) -> World``.

    ``settings`` overrides the scenario's registry roster settings (capacity
    sweeps); ``mutate`` edits the fresh scenario contract before the snapshot is
    built; ``contract`` reuses an existing contract OBJECT (so a settings sweep
    or a value sweep reads one board).  Each call re-points the registry,
    ``server.latest_contract_data`` and the snapshot memo at the new world.

    Installs, for the test: the one-league registry, both feature flags (the
    private multi-team flag is forced ON in-test whatever the production
    default, spec §6.1; the public flag likewise), the open public launch gate
    (its closed state is pinned in ``test_public_trade_advisor_validation``),
    roomy limiter capacities, header-based auth for private calls, a
    comparables stub, and a posture bundle every test can sweep.
    """
    import server
    import src.api.gameplan as gameplan
    from src.api import feature_flags, league_registry, rate_limit
    from src.api import public_trade_advisor_api as api
    from src.trade import comparable_trades
    from src.trade import public_advisor

    created: list[World] = []

    posture: dict[str, str | None] = {"label": "HOLD"}

    def build(
        scenario: str = "clean",
        *,
        settings: dict[str, Any] | None = None,
        mutate: Any = None,
        contract: dict[str, Any] | None = None,
    ) -> World:
        settings = dict(settings) if settings is not None else settings_for(scenario)
        if contract is None:
            contract = contract_for(scenario)
            if mutate is not None:
                mutate(contract)
        path = tmp_path / f"registry-{len(created)}.json"
        path.write_text(json.dumps(registry_json(settings)), encoding="utf-8")
        monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
        league_registry.reload_registry()
        monkeypatch.setattr(server, "latest_contract_data", contract)
        tl.clear_snapshot_memo()
        api.reset_for_tests()
        rate_limit.reset_for_tests()
        public_advisor.reset_memos_for_tests()
        # The ONE snapshot: the exact call both routes make, so the routes read
        # this very object back from the ledger owner's memo.
        snap = tl.snapshot_for(contract, league_key=KEY, roster_settings=dict(settings))
        world = World(
            client=surface_client,
            scenario=scenario,
            contract=contract,
            settings=settings,
            snap=snap,
            registry_path=path,
            posture=posture,
        )
        created.append(world)
        return world

    # -- the seams (installed once; every world shares them) ------------------
    monkeypatch.setenv("RISKIT_FEATURE_TRADE_MULTI_TEAM_ANALYSIS", "1")
    monkeypatch.setenv("RISKIT_FEATURE_BRISKET_TRADE_ADVISOR", "1")
    feature_flags.reload()
    cfg = copy.deepcopy(api.advisor_config())
    for spec in cfg["rateLimits"].values():
        spec["capacity"] = 100000
    monkeypatch.setattr(api, "advisor_config", lambda: cfg)
    monkeypatch.setattr(api, "_launch_gate_reason", lambda: None)
    # The GENERIC public limiter in ``server._private_api_gate`` (60 / minute per
    # exact IP, privacy finding F-5) sits in front of the advisor's own one and
    # would 429 a sweep of hundreds of calls from one test client.  It carries
    # no evaluation information and is not under test here; the advisor's own
    # limiter keeps its (roomy) configured capacities and is pinned in
    # ``test_public_trade_advisor_privacy``.
    monkeypatch.setattr(rate_limit, "should_rate_limit", lambda ip: (False, 0))
    monkeypatch.setattr(
        server, "_is_authenticated", lambda request: request.headers.get("x-lane-e-private") == "1"
    )
    monkeypatch.setattr(
        server,
        "_get_auth_session",
        lambda request: (
            {"username": "lane-e", "sleeper_user_id": "u1"}
            if request.headers.get("x-lane-e-private") == "1"
            else None
        ),
    )
    monkeypatch.setattr(comparable_trades, "comparable_trades", stub_comparables)

    def postures(league_key, profile, contract, *, build_if_missing):
        label = posture.get("label")
        if label is None:
            raise gameplan.GameplanUnavailable("lane_e_no_bundle")
        owners = {str(t.get("ownerId") or "") for t in contract["sleeper"]["teams"]} - {""}
        return {o: _Posture(o, label) for o in owners}, {"bundleFreshness": "fresh"}

    monkeypatch.setattr(gameplan, "league_competitive_postures", postures)
    yield build
    monkeypatch.undo()
    league_registry.reload_registry()
    feature_flags.reload()
    api.reset_for_tests()
    rate_limit.reset_for_tests()
    tl.clear_snapshot_memo()


# ── Seeded ledgers valid under BOTH policies ─────────────────────────────────


def public_valid_ledgers(
    snap: tl.TradeSnapshot, rng: random.Random, *, n_teams: int, count: int
) -> list[tuple[list[int], list[dict[str, Any]]]]:
    """``count`` seeded ledgers over ``n_teams`` teams where EVERY team both
    sends and receives (the public ``send_and_receive`` policy; the private
    ``any_leg`` policy accepts them too), drawn from the Lane E generator so
    multi-holder players, unknown-inventory picks, off-board ghosts and
    unpriced picks all appear where the scenario has them."""
    out: list[tuple[list[int], list[dict[str, Any]]]] = []
    for _ in range(count * 80):
        if len(out) == count:
            break
        teams, legs = P.gen_ledger(snap, rng, n_teams=n_teams, gifts=False)
        if {x["to"] for x in legs} != set(teams) or {x["from"] for x in legs} != set(teams):
            continue
        out.append((teams, legs))
    assert len(out) == count, "could not draw enough send-and-receive ledgers"
    return out


#: The near-even package-cycle tolerances swept by :func:`corpus` (inside the
#: fair band, around the cut, and outside it).
NEAR_EVEN_TOLERANCES = (40, 900, 260, 1700)


def corpus(
    world: World,
    n_teams: int,
    *,
    random_count: int = 2,
    near_even: int = 1,
    tag: str = "corpus",
) -> list[tuple[list[int], list[dict[str, Any]]]]:
    """The deterministic ledger corpus for one world and team count: seeded
    send-and-receive ledgers from the Lane E generator, plus near-even package
    cycles (the generator that actually reaches FAIR, which uniform random
    ledgers almost never do).  The seed names the scenario and the team count,
    never the clock, so a failure reproduces."""
    rng = random.Random(f"{tag}|{world.scenario}|{n_teams}")
    out = public_valid_ledgers(world.snap, rng, n_teams=n_teams, count=random_count)
    for tol in NEAR_EVEN_TOLERANCES[:near_even]:
        built = P.gen_near_even_ledger(world.contract, world.snap, rng, tol, n_teams=n_teams)
        if built is not None:
            out.append(built)
    return out
