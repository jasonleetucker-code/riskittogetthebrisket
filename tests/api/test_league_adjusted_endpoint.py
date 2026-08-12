"""Contract tests for ``GET /api/valuation/league-adjusted`` (LI-9).

The endpoint shipped live on ``main`` with **zero** coverage.  It is the
only producer of a real ``leagueAdjustedDynastyValue``, it reprices every
player on the rankings page and inside trade evaluation, and nothing
guarded any of it.

Three jobs, in order of how loudly they should fail.

1. **The routing contract.**  CLAUDE.md's table — 400 ``unknown_league``,
   400 ``inactive_league``, 503 ``data_not_ready``, 404
   ``no_leagues_configured`` — plus the ``leagueKey`` stamp.  This
   endpoint is league-scoped *by necessity*: ``lineupScarcity`` is
   measured from one league's rosters, so serving league B off league
   A's contract would silently reprice B's board with A's roster shape.

2. **The overlay is not vacuously empty.**  This is the one that
   matters, and it is why the fixture below stamps ``rankDerivedValue``
   by hand.  ``build_board_adjustments`` reads consensus through
   ``_consensus_from_row``, which returns ``None`` for a row without
   it — every explanation then carries no consensus, no factor clears
   the 0.1% floor, and the endpoint answers ``isNoop: true`` with an
   empty ``factors`` map.  **A 200 with a well-formed empty overlay is
   exactly what a completely broken adjustment model also returns.**
   ``test_the_fixture_actually_moves_values`` asserts the mechanism was
   fed before anything else asserts what it produced (ORCHESTRATION.md
   §2b: an underfed fixture is indistinguishable from a collapsed
   metric).

3. **The invariants the design rests on.**  Factors and not absolute
   values, dense contiguous ranks, picks that never move, and caller-row
   isolation against the shared ``latest_contract_data`` global.  Each
   of these is load-bearing for a reason recorded in
   ``src/league_intel/publish.py``, and each regresses through a
   plausible-looking tidy-up rather than a rewrite.

The league fixture is imported from ``test_gameplan_endpoint`` rather
than duplicated — the two endpoints share ``get_league_bundle``, and two
drifting copies of the same synthetic league would be worse than the
coupling.
"""

from __future__ import annotations

import copy
import json

from fastapi.testclient import TestClient

import server
from src.api import gameplan, league_registry
from tests.api.scoring_fixture import SCORING_CARD
from tests.api.test_gameplan_endpoint import _roster
from tests.api.test_gameplan_endpoint import league  # noqa: F401 — pytest fixture

# ``league`` is re-exported into this module's namespace on purpose; that
# is how pytest resolves an imported fixture.


# ── The contract, with the field the adjustment model actually reads ──


def _players_array() -> list[dict]:
    """The gameplan fixture's rows PLUS the two fields the overlay reads.

    ``test_gameplan_endpoint`` omits both because the gameplan engines
    read ``rosValue`` off the roster snapshot instead.  The overlay needs
    them and fails *silently* without either:

    * ``rankDerivedValue`` — ``_consensus_from_row`` reads it first, and
      a row without it yields no consensus, hence no factor, hence an
      empty ``factors`` map.
    * ``canonicalConsensusRank`` — ``compact_ranks_and_tiers`` considers
      only rows that already carry a truthy one (a real contract row
      always does), so a board without it re-ranks to nothing and
      ``ranks`` comes back ``{}``.

    Both omissions produce a well-formed 200.  That is the whole reason
    ``test_the_fixture_actually_moves_values`` and
    ``test_ranks_are_dense_and_contiguous`` assert on content rather than
    shape.
    """
    out: list[dict] = []
    for i in range(4):
        for row in _roster(i):
            n = int(row["playerId"][-2:])
            out.append(
                {
                    "playerId": row["playerId"],
                    "displayName": row["canonicalName"],
                    "position": row["position"],
                    "assetClass": "offense",
                    "age": 22 + (n % 11),
                    # The consensus board this overlay composes against.
                    "rankDerivedValue": int(round(row["rosValue"] * 100)),
                    "canonicalSiteValues": {"ktcSfTep": 200.0 + row["rosValue"] * 40.0},
                }
            )
    return out


def _ranked(rows: list[dict]) -> list[dict]:
    """Stamp the contiguous 1..N ``canonicalConsensusRank`` the contract
    builder would have stamped, in ``rankDerivedValue`` order."""
    ordered = sorted(rows, key=lambda r: (-int(r["rankDerivedValue"]), r["displayName"]))
    for i, row in enumerate(ordered, start=1):
        row["canonicalConsensusRank"] = i
    return rows


_PICK_NAME = "2027 Round 1 Pick"


def _pick_row() -> dict:
    """One draft pick.  ``compute_scarcity`` keys off rostered players
    and has no ``PICK`` entry, so a pick must come back with an ABSENT
    axis and factor 1.0 — the single largest behavioural consequence of
    this feature (see publish.py's module docstring)."""
    return {
        "playerId": "pick-2027-1",
        "displayName": _PICK_NAME,
        "position": "PICK",
        "assetClass": "pick",
        "rankDerivedValue": 4200,
    }


def _install_contract(
    monkeypatch,
    league_key: str = "main",
    profile: str = "prof_a",
    *,
    rows: list[dict] | None = None,
):
    stub = {
        "meta": {"leagueKey": league_key, "scoringProfile": profile},
        "date": "2026-07-27",
        "contractVersion": "2026-03-10.v2",
        "scrapeTimestamp": "2026-07-27T10:00:00+00:00",
        "players": {},
        "playersArray": _ranked(
            list(rows) if rows is not None else _players_array() + [_pick_row()]
        ),
        # The contract's own scoring card is its factual identity
        # (W18-F001); without one it is unverifiable and cannot be
        # served for any OTHER league, which several tests here do.
        "sleeper": {"teams": [], "scoringSettings": dict(SCORING_CARD)},
    }
    monkeypatch.setattr(server, "latest_contract_data", stub)
    return stub


def _get(client, path: str = "/api/valuation/league-adjusted"):
    return client.get(path)


# ── 2. Non-vacuity — assert the mechanism was fed, first ─────────────


def test_the_fixture_actually_moves_values(league, monkeypatch):  # noqa: F811
    """Everything below is meaningless if this fails.

    A no-op overlay and a catastrophically broken adjustment model
    produce byte-identical responses: ``isNoop: true``, ``factors: {}``,
    HTTP 200.  So the suite proves the input reached the model before it
    asserts anything about the output.

    Drop ``rankDerivedValue`` from ``_players_array`` and this is the
    only test that notices.
    """
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        res = _get(c)
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["isNoop"] is False, "the adjustment model produced no factors at all"
    assert body["adjustedCount"] > 0
    assert body["factors"], "factors map is empty — nothing to overlay"
    # A factor of exactly 1.0 would clear no floor and never be emitted,
    # but assert it anyway: a model that emitted unity for everything
    # would satisfy "factors is non-empty".
    assert any(abs(f - 1.0) > 1e-9 for f in body["factors"].values())
    # And the scarcity that drove it must be real, not an empty dict
    # standing in for "measured nothing".
    assert body["scarcity"], "no scarcity measured — the league bundle fed nothing in"
    assert any(
        isinstance(comp.get("lineupScarcity"), (int, float)) for comp in body["scarcity"].values()
    ), "every position reported an unmeasurable lineupScarcity"


# ── 1. The routing contract ──────────────────────────────────────────


def test_happy_path_returns_the_overlay_surface(league, monkeypatch):  # noqa: F811
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        res = _get(c)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["leagueKey"] == "main"
    for key in (
        "schemaVersion",
        "modelVersion",
        "adjustmentModelVersion",
        "configVersion",
        "dataThrough",
        "contractVersion",
        "scrapeTimestamp",
        "isNoop",
        "adjustedCount",
        "playerCount",
        "rankedCount",
        "monotonicityViolations",
        "scarcity",
        "factors",
        "ranks",
        "tiers",
        "warnings",
        "inactiveAxes",
        "cacheHit",
    ):
        assert key in body, f"missing {key}"
    assert body["monotonicityViolations"] == []
    assert body["warnings"] == []


def test_unknown_league_key_returns_400(league, monkeypatch):  # noqa: F811
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        res = _get(c, "/api/valuation/league-adjusted?leagueKey=ghost")
    assert res.status_code == 400
    body = res.json()
    assert body["error"] == "unknown_league"
    assert body["leagueKey"] == "ghost"


def test_inactive_league_key_returns_400(league, monkeypatch):  # noqa: F811
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        res = _get(c, "/api/valuation/league-adjusted?leagueKey=retired")
    assert res.status_code == 400
    assert res.json()["error"] == "inactive_league"


def test_non_loaded_league_returns_503_even_on_a_shared_scoring_profile(
    league,  # noqa: F811
    monkeypatch,
):
    """``main`` and ``side`` share ``prof_a``, so ``/api/data`` would
    happily serve ``side`` the shared rankings.  This endpoint must NOT:
    its whole output is derived from one league's twelve rosters, and
    serving A's scarcity under B's key is the cross-league collapse the
    scoring-profile/leagueKey split exists to prevent.
    """
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch, league_key="main")
        res = _get(c, "/api/valuation/league-adjusted?leagueKey=side")
    assert res.status_code == 503
    body = res.json()
    assert body["error"] == "data_not_ready"
    assert body["leagueKey"] == "side"


def test_no_contract_loaded_returns_503(league, monkeypatch):  # noqa: F811
    with TestClient(server.app, raise_server_exceptions=True) as c:
        monkeypatch.setattr(server, "latest_contract_data", None)
        res = _get(c)
    assert res.status_code == 503
    assert res.json()["error"] == "data_not_ready"


def test_no_leagues_configured_returns_404(tmp_path, monkeypatch):
    path = tmp_path / "empty.json"
    path.write_text(json.dumps({"leagues": []}), encoding="utf-8")
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    monkeypatch.delenv("SLEEPER_LEAGUE_ID", raising=False)
    league_registry.reload_registry()
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    try:
        with TestClient(server.app, raise_server_exceptions=True) as c:
            monkeypatch.setattr(server, "latest_contract_data", {"meta": {}})
            res = _get(c)
        assert res.status_code == 404
        assert res.json()["error"] == "no_leagues_configured"
    finally:
        league_registry.reload_registry()


def test_missing_roster_snapshot_degrades_to_a_200_noop_not_a_503(
    league,  # noqa: F811
    monkeypatch,
):
    """Deliberately asymmetric with ``/api/gameplan``, which 503s here.

    Scarcity is unmeasurable without rosters, but the consensus board is
    still perfectly usable — taking the whole rankings page down for a
    missing optional lens would be the wrong trade.  The response says
    *why* it is empty rather than presenting a no-op as a measurement.
    """
    monkeypatch.setattr(gameplan, "load_team_strength_snapshot", lambda key=None: None)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        res = _get(c)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["isNoop"] is True
    assert body["adjustedCount"] == 0
    assert body["values"] == {}
    assert body["unavailable"]["reason"]
    assert body["leagueKey"] == "main"


# ── 3. The invariants the design rests on ────────────────────────────


def test_factors_are_ratios_not_absolute_values(league, monkeypatch):  # noqa: F811
    """The overlay must compose against a board the server never
    computed — e.g. one the user re-weighted on /settings.

    A factor depends only on position, so it composes exactly.  An
    absolute value would carry the default board's numbers into a
    different board.  The tell is the magnitude: ratios sit near 1.0,
    values sit in the thousands.
    """
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        body = _get(c).json()
    for name, factor in body["factors"].items():
        assert isinstance(factor, float), name
        assert 0.5 < factor < 2.0, f"{name}={factor} is not a ratio"


def test_the_same_position_gets_the_same_factor(league, monkeypatch):  # noqa: F811
    """The composability guarantee, stated as a property rather than a
    comment: the factor is a function of position ALONE.  If it ever
    started reading the consensus value, two players at one position
    with different values would diverge — and the overlay would
    silently stop being valid against a re-weighted board."""
    rows = _players_array()
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch, rows=rows)
        body = _get(c).json()

    by_position: dict[str, set[float]] = {}
    for row in rows:
        factor = body["factors"].get(row["displayName"])
        if factor is not None:
            by_position.setdefault(row["position"], set()).add(factor)
    assert by_position, "no factors to check"
    for position, factors in by_position.items():
        assert len(factors) == 1, f"{position} got {len(factors)} distinct factors: {factors}"


def test_picks_never_move(league, monkeypatch):  # noqa: F811
    """``compute_scarcity`` has no PICK key, so a pick's axis is ABSENT
    and its factor is 1.0 — below the 0.1% floor, so it is absent from
    ``factors`` entirely.

    This is not an oversight to be fixed here: league-adjusted mode
    systematically reprices every player against every pick, and that
    lands in the trade calculator.  Pinning it means the behaviour is a
    decision rather than a surprise.
    """
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        body = _get(c).json()
    assert _PICK_NAME not in body["factors"]
    # It is still RANKED — the pick's position on the adjusted board
    # moves because the players around it moved.
    assert _PICK_NAME in body["ranks"]


def test_ranks_are_dense_and_contiguous(league, monkeypatch):  # noqa: F811
    """Sparse ranks would reintroduce the three-state ambiguity
    (changed / unchanged / now-unranked) that this design rejects."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        body = _get(c).json()
    ranks = sorted(body["ranks"].values())
    assert ranks, "no ranks emitted"
    assert ranks == list(range(1, len(ranks) + 1))
    assert body["rankedCount"] == len(ranks)
    # Every ranked row carries a tier too, or the client renders a
    # tier-less board next to a tiered one.
    assert set(body["tiers"]) <= set(body["ranks"])


def test_the_shared_contract_global_is_not_mutated(league, monkeypatch):  # noqa: F811
    """``latest_contract_data`` is a module global read by every other
    request.  ``build_league_adjusted_payload`` multiplies
    ``rankDerivedValue`` by the factor to re-rank; doing that in place
    would reprice the live board for every league on the process.

    Deep-copied before and compared after, so a mutation anywhere in the
    row tree fails this — not just at the top level.
    """
    with TestClient(server.app, raise_server_exceptions=True) as c:
        stub = _install_contract(monkeypatch)
        before = copy.deepcopy(stub)
        res = _get(c)
        assert res.status_code == 200
        assert stub == before


def test_explanations_are_off_by_default_and_available_on_request(
    league,  # noqa: F811
    monkeypatch,
):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        default = _get(c).json()
        verbose = _get(c, "/api/valuation/league-adjusted?explanations=1").json()
    assert "explanations" not in default
    assert verbose["explanations"], "explanations=1 returned nothing"
    axes = {a["name"] for e in verbose["explanations"] for a in e.get("axes", [])}
    assert "structuralScarcity" in axes


def test_the_version_pin_is_stamped_from_the_contract(league, monkeypatch):  # noqa: F811
    """The client refuses to apply an overlay whose contract build does
    not match the base it fetched.  A null pin disables that check
    without anything saying so."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        body = _get(c).json()
    assert body["contractVersion"] == "2026-03-10.v2"
    assert body["scrapeTimestamp"] == "2026-07-27T10:00:00+00:00"
    assert body["dataThrough"] == "2026-07-27"


def test_inactive_axes_are_named_not_silently_omitted(league, monkeypatch):  # noqa: F811
    """A reader must not have to infer the TE axis's absence from an
    empty diff.  ``tePremium`` is out because ``ktcSfTep`` IS the TE++
    board and the blend already embeds the premium — see
    tests/league_intel/test_te_premium_invariants.py."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        body = _get(c).json()
    assert "tePremium" in body["inactiveAxes"]
    assert "projectionCorroboration" in body["inactiveAxes"]


def test_an_empty_players_array_is_a_clean_noop(league, monkeypatch):  # noqa: F811
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch, rows=[])
        res = _get(c)
    assert res.status_code == 200
    body = res.json()
    assert body["isNoop"] is True
    assert body["factors"] == {}
    assert body["ranks"] == {}
    assert body["playerCount"] == 0


# ── 4. Server-side composition on POST /api/rankings/overrides ───────
#
# Custom source weights + the league lens used to be refused. The
# refusal was correct — the overlay's ranks belong to the un-overridden
# board — but it meant a user with any custom weight silently lost the
# lens. The composition now happens server-side.
#
# The scope consequence is the subtle part and is what these pin:
# rankings follow the SCORING PROFILE and are shared across leagues,
# but scarcity is measured from ONE league's rosters. So asking for the
# lens narrows a shared response into a league-scoped one, and the
# endpoint has to start enforcing the stricter rule for that request
# only.


def _raw_payload() -> dict:
    """The RAW scraper payload the override endpoint rebuilds from.

    ``POST /api/rankings/overrides`` reads ``server.latest_data`` (the
    pre-contract scrape), not ``latest_contract_data`` — it re-runs the
    whole pipeline rather than patching the built board. The player
    names must match the league fixture's roster, or the scarcity
    factors key off nothing and every composition assertion passes
    vacuously against an empty adjustment.
    """
    players: dict[str, dict] = {}
    for row in _players_array():
        v = int(row["rankDerivedValue"])
        players[row["displayName"]] = {
            "_composite": v,
            "_rawComposite": v,
            "_finalAdjusted": v,
            "_canonicalSiteValues": {"ktcSfTep": v, "dlfSf": v},
            "position": row["position"],
        }
    return {
        "players": players,
        "sites": [{"key": "ktcSfTep"}, {"key": "dlfSf"}],
        "maxValues": {"ktcSfTep": 9999, "dlfSf": 9999},
        "sleeper": {"positions": {}},
    }


def _install_raw(monkeypatch):
    monkeypatch.setattr(server, "latest_data", _raw_payload())
    monkeypatch.setattr(server, "latest_data_source", None)


def _post(client, body, view="delta"):
    return client.post(f"/api/rankings/overrides?view={view}", json=body)


def test_overrides_without_the_lens_stay_scoring_profile_scoped(league, monkeypatch):  # noqa: F811
    """The default path must be untouched. `side` shares `prof_a` with
    `main`, so a plain override request for it still succeeds off the
    loaded contract."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch, league_key="main")
        _install_raw(monkeypatch)
        res = _post(c, {"leagueKey": "side", "ktcSfTep": {"include": False}})
    assert res.status_code == 200, res.text
    assert res.json()["meta"]["valuationMode"] == "market"


def test_asking_for_the_lens_narrows_the_scope_to_one_league(league, monkeypatch):  # noqa: F811
    """The same request that succeeds above must 503 once the lens is
    requested — scarcity from `main`'s rosters is not `side`'s answer.

    This is the assertion that makes the composition safe. Without it
    the endpoint would happily hand league B a board priced by league
    A's roster shape, which is worse than the refusal it replaced.
    """
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch, league_key="main")
        _install_raw(monkeypatch)
        res = _post(
            c,
            {
                "leagueKey": "side",
                "ktcSfTep": {"include": False},
                "valuation_mode": "leagueAdjusted",
            },
        )
    assert res.status_code == 503
    body = res.json()
    assert body["error"] == "data_not_ready"
    assert body["leagueKey"] == "side"


def test_the_composed_board_is_stamped_as_league_adjusted(league, monkeypatch):  # noqa: F811
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        _install_raw(monkeypatch)
        res = _post(c, {"ktcSfTep": {"include": False}, "valuation_mode": "leagueAdjusted"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["meta"]["valuationMode"] == "leagueAdjusted"
    assert body["valuationAdjustment"]["applied"] is True
    assert body["valuationAdjustment"]["adjustedCount"] > 0, (
        "the lens was requested and reported applied but moved nothing — "
        "either the fixture is starved or the factors never reached the board"
    )


def test_a_missing_roster_snapshot_degrades_to_market_and_says_so(
    league,  # noqa: F811
    monkeypatch,
):
    """Without rosters there is no measurable scarcity. Serving the
    overridden market board is right; presenting it AS league-adjusted
    is not. The response has to disclose which one the caller got."""
    monkeypatch.setattr(gameplan, "load_team_strength_snapshot", lambda key=None: None)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        _install_raw(monkeypatch)
        res = _post(c, {"ktcSfTep": {"include": False}, "valuation_mode": "leagueAdjusted"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["meta"]["valuationMode"] == "market"
    assert "league_adjusted_unavailable" in body["meta"]["valuationNote"]
    assert any("league_adjusted_unavailable" in w for w in body.get("warnings") or [])


def test_the_full_view_refuses_the_lens_rather_than_ignoring_it(league, monkeypatch):  # noqa: F811
    """A silently-dropped field would return a market board labelled as
    adjusted. Say no instead."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        _install_raw(monkeypatch)
        res = _post(
            c,
            {"ktcSfTep": {"include": False}, "valuation_mode": "leagueAdjusted"},
            view="full",
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["meta"]["valuationMode"] == "market"
    assert body["meta"]["valuationNote"] == "league_adjusted_requires_delta_view"
