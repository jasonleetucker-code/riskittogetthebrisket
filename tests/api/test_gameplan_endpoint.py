"""Contract tests for ``GET /api/gameplan``.

Three jobs, in order of how loudly they should fail.

1. **The routing contract.**  Every condition in CLAUDE.md's table —
   400 ``unknown_league``, 400 ``inactive_league``, 503
   ``data_not_ready``, 404 ``no_leagues_configured`` — plus the
   ``leagueKey`` stamp every league-scoped route carries.

2. **The honesty stamps survive serialization.**  Several fields exist
   because a previous version presented something as stronger than it
   was, and the way those regress is not a rewrite — it is a rename or
   a "tidy-up" in the API layer.  So there are tests that fail if
   ``acceptancePlausibility`` ever becomes a probability, if a null
   confidence interval ever collapses to zero width, if
   ``winNowWeight``'s nulls ever become zeroes, and if the Pareto
   frontier ever grows a blended score.

3. **The engines are actually reachable.**  The whole point of the
   endpoint is that ``git grep roster_intel`` outside its own package
   returned nothing; a test that only checks status codes would pass
   against an empty payload.

The fixture builds a small synthetic league rather than reading the
live snapshots, so these run in the blocking suite.  ``tests/roster_intel
/test_real_rosters.py`` already guards the engines against the real 12
rosters under the ``livedata`` marker.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import server
from src.api import gameplan, league_registry

# ── Fixture league ───────────────────────────────────────────────────
# 4 teams x 14 players over 7 starter slots.  Three properties are
# deliberate, and a fixture missing any of them passes the tests
# vacuously rather than exercising the engines:
#
# * every roster carries more startable RB/WR than it can start, so
#   ``PositionProfile.tradeable_surplus`` is non-empty and the target
#   and package engines have real candidates;
# * two rosters have a genuine HOLE (:data:`_WEAK_POSITION`), so an
#   acquisition can clear the materiality floor — ``max(3.0, 1% of
#   lineup score)`` — and ``TargetViability.VIABLE`` is reachable.  A
#   flat fixture makes every position read ``immaterialGain`` and the
#   viability branch is never tested;
# * nobody carries a TE surplus, so TE reports ``noCandidates`` and the
#   "not measured, never nothing-available" distinction is exercised.

_SLOTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1}

_SHAPE = [
    ("QB", 3),
    ("RB", 4),
    ("WR", 5),
    ("TE", 2),
]

_WEAK_POSITION = {2: "WR", 3: "WR"}
"""Owners 2 and 3 field replacement-level receivers.  Their hole is
what makes an obtainable upgrade material."""


def _roster(owner_seed: int) -> list[dict]:
    """One roster.  Values descend within a position and are offset per
    team so no two rosters tie on a headline metric."""
    weak = _WEAK_POSITION.get(owner_seed)
    rows: list[dict] = []
    idx = 0
    for pos, count in _SHAPE:
        for n in range(count):
            idx += 1
            if pos == weak:
                value = 9.0 - (n * 1.4) - (owner_seed * 0.3)
            else:
                value = 90.0 - (n * 9.0) - (owner_seed * 3.5)
            rows.append(
                {
                    "playerId": f"p{owner_seed}{idx:02d}",
                    "canonicalName": f"{pos.lower()} {owner_seed}-{n}",
                    "position": pos,
                    "rosValue": round(max(value, 1.0), 2),
                    "fantasyPositions": [pos],
                    "injured": False,
                    "bye": False,
                }
            )
    return rows


def _snapshot() -> list[dict]:
    return [
        {
            "ownerId": f"owner{i}",
            "teamName": f"Team {i}",
            "fullRoster": _roster(i),
        }
        for i in range(4)
    ]


def _players_array() -> list[dict]:
    """The scoring-profile-scoped half of the inputs: ages and market
    prices, keyed by Sleeper id, exactly as ``/api/data`` stamps them."""
    out: list[dict] = []
    for i in range(4):
        for row in _roster(i):
            n = int(row["playerId"][-2:])
            out.append(
                {
                    "playerId": row["playerId"],
                    "displayName": row["canonicalName"],
                    "position": row["position"],
                    # ``assetClass`` + ``rankDerivedValue`` are on every
                    # live contract row and are what
                    # ``league_intel.values.build_player_values`` reads
                    # for the market anchor and the consensus scale.  A
                    # fixture without them exercises the roster value
                    # rollup vacuously (W20-F010).
                    "assetClass": "offense",
                    "age": 22 + (n % 11),
                    "rankDerivedValue": 180.0 + row["rosValue"] * 38.0,
                    "canonicalSiteValues": {
                        "ktcSfTep": 200.0 + row["rosValue"] * 40.0,
                    },
                }
            )
    return out


def _expected_market_total(owner_index: int) -> float:
    """Sum of the ktcSfTep anchors for one fixture roster."""
    return sum(200.0 + row["rosValue"] * 40.0 for row in _roster(owner_index))


def _sim_rows() -> list[dict]:
    """Playoff-sim rows for SOME owners only, with real intervals on
    one and none on another — both branches of ``engine._odds_for``
    matter and the endpoint must carry each through unchanged."""
    return [
        {
            "ownerId": "owner0",
            "playoffOdds": 0.81,
            "playoffOddsCi": [0.79, 0.83],
            "championshipOdds": 0.31,
            "championshipOddsCi": [0.28, 0.34],
        },
        {
            "ownerId": "owner1",
            "playoffOdds": 0.42,
            "championshipOdds": 0.09,
        },
    ]


@pytest.fixture
def league(tmp_path, monkeypatch):
    """Two active leagues plus a retired one, with the gameplan inputs
    stubbed onto ``main`` only."""
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "defaultLeagueKey": "main",
                "leagues": [
                    {
                        "key": "main",
                        "displayName": "Main",
                        "sleeperLeagueId": "L-MAIN",
                        "scoringProfile": "prof_a",
                        "active": True,
                        "aliases": ["primary"],
                        "rosterSettings": {
                            "teamCount": 4,
                            "rosterSize": 14,
                            "starters": _SLOTS,
                        },
                    },
                    {
                        "key": "side",
                        "displayName": "Side",
                        "sleeperLeagueId": "L-SIDE",
                        "scoringProfile": "prof_a",
                        "active": True,
                        "rosterSettings": {"teamCount": 4, "starters": _SLOTS},
                    },
                    {
                        "key": "retired",
                        "displayName": "Retired",
                        "sleeperLeagueId": "L-RET",
                        "active": False,
                        "rosterSettings": {},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()

    from src.api import user_kv

    monkeypatch.setattr(user_kv, "USER_KV_PATH", tmp_path / "user_kv.sqlite")
    user_kv._SETUP_DONE.clear()
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)

    snapshot_path = tmp_path / "team_strength.json"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    sim_path = tmp_path / "sims.json"
    sim_path.write_text(json.dumps({"playoffOdds": _sim_rows()}), encoding="utf-8")

    monkeypatch.setattr(
        gameplan,
        "load_team_strength_snapshot",
        lambda key=None: _snapshot() if key == "main" else None,
    )
    monkeypatch.setattr(gameplan, "_team_strength_stamp_path", lambda key: snapshot_path)
    monkeypatch.setattr(gameplan, "_sim_playoff_path", lambda key: sim_path)
    gameplan.invalidate_cache()

    yield {"snapshot": snapshot_path, "sim": sim_path, "tmp": tmp_path}

    gameplan.invalidate_cache()
    league_registry.reload_registry()


def _install_contract(monkeypatch, league_key: str = "main", profile: str = "prof_a"):
    stub = {
        "meta": {"leagueKey": league_key, "scoringProfile": profile},
        "players": {},
        "playersArray": _players_array(),
        "sleeper": {"teams": []},
    }
    monkeypatch.setattr(server, "latest_contract_data", stub)
    return stub


def _get(client, path: str):
    return client.get(path)


# ── 1. The routing contract ──────────────────────────────────────────


def test_happy_path_returns_the_full_surface(league, monkeypatch):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        res = _get(c, "/api/gameplan?team=owner0")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["leagueKey"] == "main"
    assert body["scoringProfile"] == "prof_a"
    assert body["contractVersion"] == gameplan.GAMEPLAN_CONTRACT_VERSION
    assert body["team"]["ownerId"] == "owner0"
    for key in (
        "roster",
        "partners",
        "targetPositions",
        "targetPlayers",
        "league",
        "coverage",
        "fieldPolicy",
        "limitations",
        "timing",
    ):
        assert key in body, f"missing {key}"
    assert res.headers.get("Cache-Control") == "no-store"


def test_unknown_league_key_returns_400(league, monkeypatch):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        res = _get(c, "/api/gameplan?leagueKey=ghost&team=owner0")
    assert res.status_code == 400
    body = res.json()
    assert body["error"] == "unknown_league"
    assert body["leagueKey"] == "ghost"


def test_inactive_league_key_returns_400(league, monkeypatch):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        res = _get(c, "/api/gameplan?leagueKey=retired&team=owner0")
    assert res.status_code == 400
    assert res.json()["error"] == "inactive_league"


def test_non_loaded_league_returns_503_data_not_ready(league, monkeypatch):
    """Gameplan is roster intelligence, so it is league-scoped end to
    end and cannot serve league B off league A's loaded contract —
    same rule as /api/terminal and /api/trade/*."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch, league_key="main")
        res = _get(c, "/api/gameplan?leagueKey=side&team=owner0")
    assert res.status_code == 503
    body = res.json()
    assert body["error"] == "data_not_ready"
    assert body["leagueKey"] == "side"


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
            res = _get(c, "/api/gameplan?team=owner0")
        assert res.status_code == 404
        assert res.json()["error"] == "no_leagues_configured"
    finally:
        league_registry.reload_registry()


def test_missing_roster_snapshot_returns_503_with_a_reason(league, monkeypatch):
    """A league with no team-strength snapshot is data_not_ready, not a
    500 and not an empty 200 that reads as 'this roster has nothing'."""
    monkeypatch.setattr(gameplan, "load_team_strength_snapshot", lambda key=None: None)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        res = _get(c, "/api/gameplan?team=owner0")
    assert res.status_code == 503
    body = res.json()
    assert body["error"] == "data_not_ready"
    assert body["reason"] == "roster_snapshot_missing"
    assert body["leagueKey"] == "main"


def test_unknown_team_returns_404(league, monkeypatch):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        res = _get(c, "/api/gameplan?team=nobody")
    assert res.status_code == 404
    body = res.json()
    assert body["error"] == "team_not_found"
    assert body["leagueKey"] == "main"


def test_team_cannot_be_inferred_returns_400(league, monkeypatch):
    """No ?team, no Sleeper id on the session, no default_team_map —
    the endpoint must say which input is missing rather than silently
    picking somebody's roster."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        monkeypatch.setattr(server, "_get_auth_session", lambda request: {"username": "alice"})
        res = _get(c, "/api/gameplan")
    assert res.status_code == 400
    assert res.json()["error"] == "team_required"


def test_team_resolves_from_the_session_sleeper_id(league, monkeypatch):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        monkeypatch.setattr(
            server,
            "_get_auth_session",
            lambda request: {"username": "alice", "sleeper_user_id": "owner2"},
        )
        res = _get(c, "/api/gameplan")
    assert res.status_code == 200, res.text
    assert res.json()["team"]["ownerId"] == "owner2"


def test_alias_resolves_to_the_canonical_key(league, monkeypatch):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        res = _get(c, "/api/gameplan?leagueKey=primary&team=owner0")
    assert res.status_code == 200, res.text
    assert res.json()["leagueKey"] == "main"


# ── 2. The honesty stamps ────────────────────────────────────────────


def _payload(monkeypatch, query: str = "?team=owner0"):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        res = c.get(f"/api/gameplan{query}")
    assert res.status_code == 200, res.text
    return res.json()


def _walk(node, path="$"):
    """Every (json-path, key, value) in the payload."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield f"{path}.{key}", key, value
            yield from _walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _walk(value, f"{path}[{i}]")


def test_acceptance_plausibility_is_never_renamed_to_a_probability(league, monkeypatch):
    """MECHANISM TEST.  Fails if the acceptance estimate is ever
    presented as a calibrated probability.

    Rejections are never observed — the league snapshot ingests only
    completed transactions — so an acceptance RATE is statistically
    unidentifiable from this data.  The field names are the last thing
    standing between that fact and a UI that renders "78% likely to
    accept", and a rename is exactly how it would be lost.
    """
    body = _payload(monkeypatch, "?team=owner3&partner=owner0")

    offenders = [
        p for p, key, _ in _walk(body) if "probabilit" in key.lower() and "acceptance" in p.lower()
    ]
    assert not offenders, f"acceptance quantity renamed to a probability at: {offenders}"

    frontier = (body.get("packages") or {}).get("frontier") or []
    assert frontier, "fixture produced no packages — this test would pass vacuously"
    for member in frontier:
        assert "acceptancePlausibility" in member
        assert "acceptanceProbability" not in member
        caveat = member["acceptanceCaveat"]
        assert "not a calibrated acceptance probability" in caveat
        assert "Never render as" in caveat

    for row in body["partners"]:
        assert "tradeAcceptanceEstimate" in row
        assert not any("probabilit" in k.lower() for k in row)

    # The model's own limitations must ship with the estimate, because
    # partner.describe_limitations says any surface rendering the
    # estimate has to render them alongside it.
    limits = body["limitations"]["partner"]
    assert limits["keyAssumptions"]["baseAcceptancePriorIsMeasured"] is False
    assert any("unidentifiable" in c for c in limits["cannotSupport"])


def test_null_confidence_intervals_never_collapse_to_zero_width(league, monkeypatch):
    """MECHANISM TEST.  A zero-width interval reads as certainty.

    ``owner1`` has simulated odds but no intervals; ``owner0`` has
    both.  The absent pair must stay null rather than becoming
    ``[0.42, 0.42]`` — or worse ``[0, 0]`` — on the way through the
    API.
    """
    body = _payload(monkeypatch, "?team=owner1")
    roster = body["roster"]
    assert roster["playoffOdds"] == pytest.approx(0.42)
    assert roster["playoffOddsCi"] is None
    assert roster["championshipOddsCi"] is None
    assert any("confidence interval" in n for n in roster["notes"])

    # ...and the team that HAS intervals keeps them, so the assertion
    # above is not just measuring an endpoint that drops all intervals.
    with_ci = next(r for r in body["league"] if r["ownerId"] == "owner0")
    assert with_ci["playoffOddsCi"] == [0.79, 0.83]
    assert with_ci["championshipOddsCi"] == [0.28, 0.34]

    for path, key, value in _walk(body):
        if not key.endswith("Ci") or not isinstance(value, list) or len(value) != 2:
            continue
        assert value[0] != value[1], f"zero-width interval at {path}: {value}"


def test_win_now_weight_nulls_survive_and_the_field_is_declared_unsortable(league, monkeypatch):
    """``winNowWeight`` is null when candidate ages are missing, and its
    nulls are not a random subset — they cluster on positions whose
    obtainable upgrades happen to be un-aged.  Sorting on it would
    reorder by data availability, so the API declares it off-limits.
    """
    body = _payload(monkeypatch)
    policy = body["fieldPolicy"]
    assert "targetPositions[].winNowWeight" in policy["nonFilterable"]
    entry = next(e for e in policy["nonSortable"] if e["field"] == "targetPositions[].winNowWeight")
    # The second reason the field is unsortable: it carries the
    # per-position horizon weight on viable rows and the GLOBAL win-now
    # scalar on non-viable ones, under one name.
    assert "alsoNotComparableAcrossRows" in entry

    for target in body["targetPositions"]:
        assert "winNowWeight" in target
        weight = target["winNowWeight"]
        assert weight is None or isinstance(weight, (int, float))

    # No sort/filter parameter is offered, and passing one must not
    # silently reorder the list — that is the loophole the declaration
    # exists to close.
    plain = [t["position"] for t in body["targetPositions"]]
    sneaky = _payload(monkeypatch, "?team=owner0&sort=winNowWeight&filter=winNowWeight")
    assert [t["position"] for t in sneaky["targetPositions"]] == plain


def test_win_now_weight_is_null_when_no_ages_reach_the_engines(league, monkeypatch):
    """MECHANISM TEST for the null branch itself.  Strip ages from the
    contract and the horizon weight must report that it did not apply,
    rather than stamping a number that looks applied."""
    stub = {
        "meta": {"leagueKey": "main", "scoringProfile": "prof_a"},
        "players": {},
        "playersArray": [{**row, "age": None} for row in _players_array()],
        "sleeper": {"teams": []},
    }
    with TestClient(server.app, raise_server_exceptions=True) as c:
        monkeypatch.setattr(server, "latest_contract_data", stub)
        res = c.get("/api/gameplan?team=owner3")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["coverage"]["ageCoverage"]["withAge"] == 0
    viable = [t for t in body["targetPositions"] if t["viability"] == "viable"]
    assert viable, "fixture produced no viable target — this test would pass vacuously"
    for target in viable:
        assert target["winNowWeight"] is None
        assert any("could not be computed" in n for n in target["notes"])

    # ...and the non-viable rows still carry a NUMBER, because the
    # engine stamps the global win-now scalar there rather than the
    # per-position horizon weight. Same field name, different quantity —
    # which is the second reason it must not be sorted on, and is
    # asserted here so a reader cannot mistake the mixture for a bug in
    # this endpoint.
    non_viable = [t for t in body["targetPositions"] if t["viability"] != "viable"]
    assert non_viable
    assert all(t["winNowWeight"] is not None for t in non_viable)
    assert len({t["winNowWeight"] for t in non_viable}) == 1, "global scalar should be uniform"


def test_unmeasured_thresholds_are_declared_unmeasured(league, monkeypatch):
    """Every tunable in these engines is a judgement call, and each
    module says so in machine-readable form.  That flag must reach the
    API or the constants read as fitted values."""
    body = _payload(monkeypatch, "?team=owner3&partner=owner0")
    assert body["limitations"]["packages"]["keyAssumptions"]["thresholdsAreMeasured"] is False
    targets = body["limitations"]["targets"]["keyAssumptions"]
    assert targets["materialityFloorIsMeasured"] is False
    assert targets["winNowWeightsAreMeasured"] is False
    assert (
        body["limitations"]["partner"]["keyAssumptions"]["baseAcceptancePriorIsMeasured"] is False
    )


def test_the_pareto_frontier_is_returned_wide_with_no_blended_score(league, monkeypatch):
    """No exchange rate exists between market points, lineup points and
    plausibility, so the frontier is a set of alternatives and must not
    acquire a single number that ranks them."""
    body = _payload(monkeypatch, "?team=owner3&partner=owner0")
    packages = body["packages"]
    frontier = packages["frontier"]
    assert frontier

    banned = {"score", "overallScore", "compositeScore", "rank", "blendedScore"}
    for member in frontier:
        assert not (banned & set(member)), f"frontier member grew a ranking score: {member.keys()}"

    assert packages["bestBy"], "bestBy must name which axis each member wins"
    assert "not a ranking" in packages["note"]
    assert "noBlendedFrontierScore" in body["fieldPolicy"]

    # The frontier really is non-dominated on more than one axis — if
    # every member won on the same axis, "wide" would be decoration.
    if len(frontier) > 1:
        assert len({member["acceptancePlausibility"] for member in frontier}) > 1


def test_engine_notes_and_semantics_survive_serialization(league, monkeypatch):
    """The ``_semantics`` block on each need exists because a consumer
    derived deficit as ``fragility x marginal`` and got the roster's
    STRONGEST position reported as its biggest hole.  Stripping it in
    the API layer re-arms that."""
    body = _payload(monkeypatch)
    needs = body["roster"]["needs"]
    assert needs
    for need in needs.values():
        semantics = need["_semantics"]
        assert "do NOT multiply these" in semantics["warning"]
        assert need["deficit"] >= 0.0
        assert 0.0 <= need["concentrationRisk"] <= 1.0

    window = body["roster"]["competitiveWindow"]
    assert "ordering as soft" in window["orderingCaveat"]
    assert abs(sum(window["probabilities"].values()) - 1.0) < 1e-9


def test_partial_playoff_sim_coverage_is_flagged_not_papered_over(league, monkeypatch):
    """The sim covers 2 of 4 owners.  Covered teams take a
    championship-odds percentile over that smaller pool while the rest
    fall back to a lineup-score percentile over the whole league — two
    denominators feeding one window axis.  That must be stated."""
    body = _payload(monkeypatch)
    coverage = body["coverage"]["playoffSimCoverage"]
    assert coverage["owners"] == 2
    assert coverage["total"] == 4
    assert any("NOT comparable" in n for n in body["notes"])

    sources = {r["competitiveWindow"]["inputs"]["competitivenessSource"] for r in body["league"]}
    assert sources == {"championshipOdds", "lineupScoreRank"}

    uncovered = next(r for r in body["league"] if r["ownerId"] == "owner3")
    assert uncovered["oddsSource"] == "owner_not_in_simulation"
    assert uncovered["playoffOdds"] is None


def test_market_edge_is_reported_unmeasured_rather_than_computed_across_scales(league, monkeypatch):
    """MECHANISM TEST for the scale trap.

    ``rosValue`` is 0-100 rest-of-season points; ``canonicalSiteValues``
    is the 0-9999 dynasty market.  Feeding one to the other yields an
    edge near -1 for every player — a dead signal that still looks
    computed.  The endpoint must decline to supply it and say why.
    """
    body = _payload(monkeypatch)
    assert "rosValue" in body["coverage"]["marketEdgeUnmeasured"]["reason"]
    for target in body["targetPlayers"]:
        assert target["marketEdge"] is None
        assert "marketEdge" not in target["signals"]
    for target in body["targetPositions"]:
        assert target["marketEfficiency"] is None


# ── 3. The engines are genuinely reachable ───────────────────────────


def test_the_roster_payload_carries_real_engine_output(league, monkeypatch):
    """A status-code-only test would pass against an empty payload.
    This one fails unless the lineup was actually solved."""
    body = _payload(monkeypatch)
    roster = body["roster"]
    assert roster["lineupScore"] > 0
    assert roster["totalSlots"] == sum(_SLOTS.values())
    assert roster["filledSlots"] == roster["totalSlots"]
    # The optimizer's assignment, not a copy of the whole roster.
    assert roster["values"]["startersRos"] > 0
    assert roster["values"]["benchRos"] > 0
    assert roster["values"]["startersRos"] < roster["values"]["ros"]
    assert abs(roster["lineupScore"] - roster["values"]["startersRos"]) < 0.01

    positions = roster["positions"]
    assert {"QB", "RB", "WR", "TE"} <= set(positions)
    assert any(p["tradeableSurplus"] > 0 for p in positions.values())

    assert len(body["partners"]) == 3
    assert body["partners"] == sorted(
        body["partners"], key=lambda p: (-p["tradePartnerFitScore"], p["ownerId"])
    )
    assert len(body["league"]) == 4


def test_roster_market_values_are_computed_not_left_at_zero(league, monkeypatch):
    """W20-F010 — the assembler must hand the engine the values it built.

    ``build_league_bundle`` called ``analyze_roster`` without
    ``player_values``, so ``_rollup_values`` summed an empty mapping and
    the ``RosterValues`` 0.0 defaults survived.  All four parallel
    scales came back 0.0 for all 12 real teams while the SAME payload
    reported ``marketPriceCoverage 627 of 666 priced`` — a payload that
    reads "everything is priced, and the total is zero".
    """
    body = _payload(monkeypatch)
    values = body["roster"]["values"]

    assert values["market"] == pytest.approx(_expected_market_total(0))
    assert values["consensus"] > 0
    assert values["leagueAdjusted"] > 0
    # The rollup counts what it priced, so a zero total can never again
    # sit next to a full-coverage claim without contradicting itself.
    assert values["marketPricedPlayers"] == len(_roster(0))
    assert values["marketUnpricedPlayers"] == 0

    coverage = body["coverage"]["marketPriceCoverage"]
    assert coverage["priced"] == coverage["total"]


def test_unsupplied_pick_capital_is_null_rather_than_zero(league, monkeypatch):
    """A roster's pick capital is not an input to this surface.

    Reporting it as ``0.0`` says "this team owns no picks", which is a
    claim.  ``null`` plus a note says "not measured", which is the
    truth (W20-F010).
    """
    body = _payload(monkeypatch)
    assert body["roster"]["values"]["pickValue"] is None
    assert any("pick" in n.lower() for n in body["roster"]["notes"])


def test_target_positions_report_non_viability_instead_of_omitting_it(league, monkeypatch):
    """ "No candidates" is 'we could not tell', not 'nothing available',
    and the distinction is never collapsed — so non-viable positions
    come back too, unranked."""
    body = _payload(monkeypatch)
    targets = body["targetPositions"]
    assert targets
    viabilities = {t["viability"] for t in targets}
    assert viabilities <= {"viable", "noCandidates", "noObtainableUpgrade", "immaterialGain"}
    for target in targets:
        assert target["reason"]
        if target["viability"] != "viable":
            assert target["priority"] == 0.0

    viable = [t for t in targets if t["viability"] == "viable"]
    assert viable == sorted(viable, key=lambda t: (-t["priority"], t["position"]))


def test_rejected_target_players_carry_their_reason(league, monkeypatch):
    body = _payload(monkeypatch)
    players = body["targetPlayers"]
    assert players
    rejected = [t for t in players if not t["recommended"]]
    # Non-vacuity. Every assertion below is inside a loop over rejected
    # targets, so an empty list would pass the whole test having checked
    # nothing. Measured on this fixture: 15 rejected, 0 recommended.
    assert rejected, "fixture produced no rejected targets; the loop below would be a no-op"

    for target in players:
        assert target["reason"]

    for target in rejected:
        # This previously read
        #     assert t["corroborating"] == [] or len(t["corroborating"]) >= 0
        # and ``len(x) >= 0`` is true of every list, so the disjunction
        # was a tautology — the one assertion about rejected targets
        # asserted nothing at all about them.
        #
        # The real invariant, measured across all 15 rejected targets on
        # this fixture: a target is rejected precisely because nothing
        # corroborated it, so the list is empty.
        assert target["corroborating"] == [], (
            f"{target.get('name') or target.get('displayName')!r} was rejected but "
            f"carries corroboration {target['corroborating']!r} — rejection and "
            "corroboration disagree"
        )
    yields = body["coverage"]["corroborationYield"]
    assert yields["evaluated"] == len(players)
    assert yields["recommended"] == sum(1 for t in players if t["recommended"])


def test_candidate_policy_declares_the_search_non_exhaustive(league, monkeypatch):
    body = _payload(monkeypatch)
    policy = body["coverage"]["candidatePolicy"]
    assert policy["exhaustive"] is False
    assert policy["maxPerPosition"] == gameplan.MAX_CANDIDATES_PER_POSITION
    assert "NOT MEASURED" in policy["note"]


def test_packages_are_omitted_without_a_named_partner(league, monkeypatch):
    body = _payload(monkeypatch)
    assert body["packages"] is None
    assert "partner=" in body["packagesOmitted"]["howTo"]


def test_unknown_partner_is_reported_not_crashed(league, monkeypatch):
    body = _payload(monkeypatch, "?team=owner0&partner=ghost")
    assert body["packages"]["error"] == "unknown_partner"
    assert body["packages"]["frontier"] == []


def test_every_package_rejection_is_explained(league, monkeypatch):
    body = _payload(monkeypatch, "?team=owner3&partner=owner0")
    packages = body["packages"]
    assert packages["rejected"]
    for member in packages["rejected"]:
        assert member["rejection"] != "none"
        assert member["rejectionDetail"], member
    assert packages["stages"]
    assert packages["partner"]["ownerId"] == "owner0"


# ── Caching ──────────────────────────────────────────────────────────


def test_second_request_is_served_from_cache(league, monkeypatch):
    """The league build is ~1.35 s on the real league, so a warm
    request must not redo it."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        first = c.get("/api/gameplan?team=owner0").json()
        second = c.get("/api/gameplan?team=owner0").json()
    assert first["timing"]["leagueBuildCached"] is False
    assert first["timing"]["teamBuildCached"] is False
    assert second["timing"]["leagueBuildCached"] is True
    assert second["timing"]["teamBuildCached"] is True
    assert first["timing"]["sourceStamp"] == second["timing"]["sourceStamp"]
    assert second["roster"] == first["roster"]


def test_a_new_contract_invalidates_the_cache(league, monkeypatch):
    """Keyed on the identity of the inputs, not a clock: a refresh must
    invalidate immediately rather than serving a stale build until a
    TTL expires."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        stub = _install_contract(monkeypatch)
        first = c.get("/api/gameplan?team=owner0").json()
        monkeypatch.setattr(
            server,
            "latest_contract_data",
            {**stub, "scrapeTimestamp": "2026-07-28T00:00:00Z"},
        )
        second = c.get("/api/gameplan?team=owner0").json()
    assert first["timing"]["sourceStamp"] != second["timing"]["sourceStamp"]
    assert second["timing"]["leagueBuildCached"] is False


def test_a_new_roster_snapshot_invalidates_the_cache(league, monkeypatch):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch)
        first = c.get("/api/gameplan?team=owner0").json()
        league["snapshot"].write_text(json.dumps(_snapshot() + [{}]), encoding="utf-8")
        second = c.get("/api/gameplan?team=owner0").json()
    assert first["timing"]["sourceStamp"] != second["timing"]["sourceStamp"]
    assert second["timing"]["leagueBuildCached"] is False


# ── The scoring-profile / league-key split ───────────────────────────


def test_rosters_follow_the_league_and_ages_follow_the_scoring_profile(league, monkeypatch):
    """CLAUDE.md's central rule, asserted at the seam.

    Rosters, slots and replacement levels come from the LEAGUE's own
    snapshot and registry entry; ages and market prices come from the
    scoring-profile-scoped contract.  If ages were league-scoped, a
    contract carrying a different profile's players would still have to
    feed them — and it does, which is the point.
    """
    body = _payload(monkeypatch)
    coverage = body["coverage"]
    # 4 rosters x 14 players, straight from the league snapshot.
    assert coverage["rosters"] == 4
    assert coverage["rosteredPlayers"] == 4 * sum(count for _pos, count in _SHAPE)
    assert coverage["starterSlots"] == sum(_SLOTS.values())
    # Ages joined off the contract, not off the roster snapshot (which
    # carries none).
    assert coverage["ageCoverage"]["withAge"] == coverage["rosteredPlayers"]
    assert "scoring-profile scoped" in coverage["ageCoverage"]["source"]
    assert coverage["marketPriceCoverage"]["priced"] == coverage["rosteredPlayers"]
