"""Multi-team War Room fixtures ARE the engine's output (spec §7: Lane A
produces ``frontend/__tests__/fixtures/trade-multi/*``; consumers never edit).

The scenarios on the real archived board move whenever a valuation input
moves, so this regenerates every scenario and requires the committed file to
have the SAME CONTRACT SHAPE (every key the UI reads, at every level it reads
it) plus the invariants every response holds.  Regenerate with::

    python -m tests.trade.multi_team_ui_payloads
"""

from __future__ import annotations

import json

import pytest

from tests.trade import multi_team_ui_payloads as gen

TOP_KEYS = {
    "multiTeamVersion",
    "leagueKey",
    "valuationMode",
    "generation",
    "snapshotChanged",
    "rosters",
    "mode",
    "perspectiveRosterId",
    "teamCount",
    "teams",
    "summary",
    "ledger",
    "packageModel",
    "fairnessBands",
    "decisionRunIds",
    "tradeRunId",
    "_fixture",
}
TEAM_KEYS = {
    "rosterId",
    "team",
    "gives",
    "receives",
    "simulation",
    "analysis",
    "category",
    "categoryText",
    "categoryReason",
    "fairness",
    "unverifiableAssetIds",
}
FAIRNESS_KEYS = {
    "state",
    "level",
    "reasonCode",
    "gap",
    "largerAdjustedSide",
    "largerPackageUtility",
    "relativePct",
    "bands",
}
SUMMARY_KEYS = {
    "teamCount",
    "legCount",
    "perTeam",
    "lines",
    "fairnessOverall",
    "conservation",
    "nonConservedNote",
}


def _shape(body: dict) -> dict:
    teams = body["teams"]
    return {
        "top": sorted(body),
        "team": sorted({k for t in teams for k in t} - {"comparables"}),
        "gives": sorted({k for t in teams for g in t["gives"] for k in g}),
        "receives": sorted({k for t in teams for r in t["receives"] for k in r}),
        "fairness": sorted({k for t in teams for k in t["fairness"]}),
        "decision": sorted({k for t in teams for k in t["analysis"]["decision"]}),
        "summary": sorted(body["summary"]),
        "perTeam": sorted({k for p in body["summary"]["perTeam"] for k in p}),
    }


@pytest.mark.parametrize("name", sorted(gen.SCENARIOS))
def test_committed_fixture_has_the_engines_shape(name):
    path = gen.fixture_path(name)
    assert path.exists(), f"missing {path}; run python -m tests.trade.multi_team_ui_payloads"
    committed = json.loads(path.read_text(encoding="utf-8"))
    fresh = gen.build(name)
    assert _shape(committed) == _shape(fresh), (
        f"{path.name} no longer has the engine's contract shape; regenerate with "
        "python -m tests.trade.multi_team_ui_payloads"
    )
    assert committed["_fixture"]["request"] == fresh["_fixture"]["request"] or (
        committed["_fixture"]["board"] != "synthetic"
    )


@pytest.mark.parametrize("name", sorted(gen.SCENARIOS))
def test_committed_fixture_holds_the_response_invariants(name):
    body = json.loads(gen.fixture_path(name).read_text(encoding="utf-8"))
    assert set(body) == TOP_KEYS
    ids = [t["rosterId"] for t in body["teams"]]
    assert ids == sorted(ids) and body["teamCount"] == len(ids)
    for t in body["teams"]:
        assert TEAM_KEYS <= set(t)
        assert set(t["fairness"]) == FAIRNESS_KEYS
        for row in (*t["gives"], *t["receives"]):
            if row["valueState"] != "priced":
                assert row["value"] is None  # missing is never zero
    assert set(body["summary"]) == SUMMARY_KEYS
    assert body["summary"]["conservation"]["balanced"] is True
    assert len(body["summary"]["lines"]) == len(ids)
    legs = {leg["id"] for leg in body["ledger"]["legs"]}
    assert legs == {g["assetId"] for t in body["teams"] for g in t["gives"]}
    assert legs == {r["assetId"] for t in body["teams"] for r in t["receives"]}


def test_fixtures_cover_the_states_the_ui_renders():
    load = {n: json.loads(gen.fixture_path(n).read_text(encoding="utf-8")) for n in gen.SCENARIOS}
    assert load["four-team-asset-only"]["teamCount"] == 4
    assert load["three-team-team-context"]["mode"] == "team_context"
    stale = load["three-team-stale-rosters"]
    assert stale["rosters"]["state"] == "stale"
    assert {t["fairness"]["state"] for t in stale["teams"]} == {"UNABLE"}
    cut = load["three-team-forced-cut"]
    assert any(
        (t["simulation"].get("rosterCapacity") or {}).get("forcedDrops") for t in cut["teams"]
    )
    unpriced = load["three-team-unpriced-asset"]
    assert any(g["valueState"] == "unpriced" for t in unpriced["teams"] for g in t["gives"])
