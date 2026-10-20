"""Lane E-1 gap tests for the N-team engine (directive §11; spec
``docs/trade/NTEAM_TRADE_ENGINE_SPEC.md``), on the REAL archived board.

Three properties the existing suites left unpinned:

1. **Route == engine at N = 3 and 4.**  ``test_trade_analyze_multi_route``
   proves byte equality with the 2-team route at N = 2 (I4) and the response
   SHAPE at N = 3.  Here the private ``/api/trade/analyze-multi`` body, minus
   the per-request additions, is byte-equal to
   ``analyze_service.multi_team_payload`` over a direct ``analyze_trade_n``
   call — at 2, 3 and 4 teams, in both private modes, over the directive §11
   structures built from real rosters and seeded random ledgers.
2. **Every per-team decision is traceable to its owner and its receipt.**  The
   all-team summary is a projection of the per-team rows (``team_verdicts``),
   the overall is the three-valued AND of the per-team fairness, and each
   served headline is the one recorded under its ``decisionRunId``.
3. **A quarantined value withholds the touching teams' answers, and only
   theirs** — synthetic (labelled) and as an invariant on the real board.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest

from src.trade import analyze_service as svc
from src.trade import team_verdicts as tv
from src.trade import trade_ledger as tl
from tests.api import test_trade_analyze_multi_route as _route
from tests.trade import multi_team_support as mts

LEAGUE = "dynasty_main"
#: The route module's fixtures (registry copy, flag, real-board app), reused.
app = _route.app
flag_on = _route.flag_on
real_registry = _route.real_registry
#: Per-request additions the route makes on top of ``multi_team_payload``.
ROUTE_ONLY_TOP = {
    "decisionRunIds",
    "tradeRunId",
    "analysisTiming",
    "valuationMode",
    "valuationNote",
}


@pytest.fixture(autouse=True)
def _pinned_scarcity(monkeypatch):
    """R1-2: see ``multi_team_support.pin_league_scarcity``."""
    return mts.pin_league_scarcity(monkeypatch)


def _snap(contract):
    return tl.snapshot_for(
        contract, league_key=LEAGUE, roster_settings=mts._dynasty_main_settings()
    )


def _canon(o: Any) -> str:
    return json.dumps(json.loads(json.dumps(o, default=str)), sort_keys=True)


def _strip(body: dict) -> dict:
    out = {k: v for k, v in body.items() if k not in ROUTE_ONLY_TOP}
    out["teams"] = [
        {**t, "analysis": {k: v for k, v in t["analysis"].items() if k != "decisionRunId"}}
        for t in body["teams"]
    ]
    return json.loads(json.dumps(out, default=str))


def _route_provider():
    """The private route's comparables provider, verbatim."""
    import server
    from src.trade import comparable_trades as _comparable

    def provider(flows, simulation):
        return _comparable.comparable_trades(
            LEAGUE,
            side_a=_comparable.side_refs_from_assets(simulation.get("receiving") or []),
            side_b=_comparable.side_refs_from_assets(simulation.get("sending") or []),
            names=server._board_names_by_player_id(),
        )

    return provider


def _priced(snap, contract, rid: int, positions: tuple[str, ...]) -> list[str]:
    rows = {str(r.get("playerId")): r for r in contract["playersArray"] if r.get("playerId")}
    out = []
    for aid in mts.team_assets(snap, rid):
        if not aid.startswith("p:"):
            continue
        r = rows.get(aid[2:]) or {}
        v = r.get("rankDerivedValue") or 0
        if v > 0 and not r.get("quarantined") and r.get("position") in positions:
            out.append((-v, aid))
    return [a for _v, a in sorted(out)]


def _picks(snap, rid: int) -> list[str]:
    return [a for a in mts.team_assets(snap, rid) if a.startswith("pick:")]


def _structures(snap, contract) -> list[tuple[str, list[int], list[dict]]]:
    """Directive §11 shapes on real rosters (teams with deep pick inventories)."""
    off = ("QB", "RB", "WR", "TE")
    rids = sorted(snap.teams_by_roster_id)
    holders = [r for r in rids if len(_picks(snap, r)) >= 2]
    if len(holders) < 4:
        pytest.skip("archived board has fewer than four pick-holding teams")
    a, b, c, d = holders[:4]
    o = {r: _priced(snap, contract, r, off) for r in (a, b, c, d)}
    lb = {r: _priced(snap, contract, r, ("LB",)) for r in (a, b, c, d)}
    dl = {r: _priced(snap, contract, r, ("DL",)) for r in (a, b, c, d)}
    pk = {r: _picks(snap, r) for r in (a, b, c, d)}

    def leg(aid, f, t):
        return {"id": aid, "from": f, "to": t}

    out = [
        ("2: offense 1-for-1", [a, b], [leg(o[a][2], a, b), leg(o[b][2], b, a)]),
        ("3: circular", [a, b, c], [leg(o[a][3], a, b), leg(o[b][3], b, c), leg(o[c][3], c, a)]),
        (
            "4: circular",
            [a, b, c, d],
            [leg(o[a][4], a, b), leg(o[b][4], b, c), leg(o[c][4], c, d), leg(o[d][4], d, a)],
        ),
        (
            "3: one to many",
            [a, b, c],
            [leg(o[a][1], a, b), leg(o[a][6], a, c), leg(o[b][1], b, a), leg(pk[c][0], c, a)],
        ),
        (
            "3: many to one",
            [a, b, c],
            [leg(o[b][2], b, a), leg(o[c][2], c, a), leg(pk[a][0], a, b), leg(pk[a][1], a, c)],
        ),
        (
            "3: offense + IDP",
            [a, b, c],
            [leg(o[a][6], a, b), leg(lb[b][1], b, c), leg(dl[b][1], b, c), leg(o[c][7], c, a)],
        ),
        (
            "3: picks only",
            [a, b, c],
            [leg(pk[a][0], a, b), leg(pk[b][0], b, c), leg(pk[c][0], c, a)],
        ),
        (
            "4: deep mixed",
            [a, b, c, d],
            [
                leg(o[a][2], a, c),
                leg(lb[a][0], a, d),
                leg(o[c][1], c, b),
                leg(pk[c][0], c, a),
                leg(o[b][2], b, a),
                leg(dl[b][0], b, c),
                leg(o[d][1], d, b),
                leg(pk[d][0], d, c),
            ],
        ),
    ]
    rng = random.Random(1102)
    for n in (2, 3, 4, 3, 4):
        teams, legs = mts.random_ledger(snap, rng, n_teams=n, max_per_team=3)
        out.append((f"{n}: random", teams, [dict(x) for x in legs]))
    return out


@pytest.mark.parametrize("team_context", [True, False])
def test_route_equals_engine_byte_for_byte_at_two_three_and_four_teams(app, flag_on, team_context):
    client, contract = app
    snap = _snap(contract)
    mode = "team_context" if team_context else "asset_only"
    seen = set()
    for name, teams, legs in _structures(snap, contract):
        res = client.post(
            "/api/trade/analyze-multi",
            json={
                "leagueKey": LEAGUE,
                "teams": teams,
                "assets": legs,
                "useTeamContext": team_context,
            },
        )
        assert res.status_code == 200, (name, res.text)
        ledger = tl.validate_ledger(snap, teams=teams, legs=legs, policy=tl.private_policy())
        out = svc.analyze_trade_n(
            snap,
            ledger,
            mode=mode,
            counterfactuals=True,
            comparables_provider=_route_provider(),
        )
        expected = svc.multi_team_payload(
            out,
            snap=snap,
            ledger=ledger,
            league_key=LEAGUE,
            perspective=None,
            expected_generation=None,
        )
        assert _canon(_strip(res.json())) == _canon(expected), (name, mode)
        seen.add(len(set(teams)))
    assert seen == {2, 3, 4}


def _log_lines(log_dir: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in sorted(log_dir.rglob("*")):
        if not f.is_file():
            continue
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("runId"):
                out[row["runId"]] = row
    return out


def test_every_team_decision_is_traceable_to_its_owner_and_receipt(app, flag_on, tmp_path):
    client, contract = app
    snap = _snap(contract)
    for name, teams, legs in _structures(snap, contract):
        res = client.post(
            "/api/trade/analyze-multi",
            json={"leagueKey": LEAGUE, "teams": teams, "assets": legs, "useTeamContext": False},
        )
        assert res.status_code == 200, (name, res.text)
        body = res.json()
        by_rid = {t["rosterId"]: t for t in body["teams"]}
        assert [r["rosterId"] for r in body["summary"]["perTeam"]] == sorted(set(teams))
        for row in body["summary"]["perTeam"]:
            team = by_rid[row["rosterId"]]
            decision = team["analysis"]["decision"]
            assert row["headline"] == decision["headline"], name
            assert row["category"] == team["category"] == tv.team_category(decision), name
            assert row["fairness"] == team["fairness"]["state"], name
            assert _canon(tv.team_fairness(team["simulation"], team["analysis"])) == _canon(
                team["fairness"]
            ), name
            assert decision["recommendationOnly"] is True and decision["executes"] is False
        overall = tv.fairness_overall(t["fairness"]["state"] for t in body["teams"])
        assert overall == body["summary"]["fairnessOverall"], name
        logged = _log_lines(tmp_path)
        for t in body["teams"]:
            run_id = t["analysis"]["decisionRunId"]
            assert body["decisionRunIds"][str(t["rosterId"])] == run_id
            assert run_id in logged, (name, t["rosterId"])
            assert logged[run_id]["headline"] == t["analysis"]["decision"]["headline"]
            assert logged[run_id]["deciding"] == t["analysis"]["decision"]["deciding"]


# ── Quarantined values ─────────────────────────────────────────────────────


def _no_posture(*_a, **_k):
    return None


def _run(snap, teams, legs, mode):
    ledger = tl.validate_ledger(snap, teams=teams, legs=legs, policy=tl.LedgerPolicy())
    kw = {"posture_resolver": _no_posture} if mode != "market_fairness" else {}
    return svc.analyze_trade_n(snap, ledger, mode=mode, counterfactuals=False, **kw)


def _strip_team(t: dict) -> dict:
    return {
        "fairness": t["fairness"],
        "category": t["category"],
        "headline": t["analysis"]["decision"]["headline"],
        "gives": t["gives"],
        "receives": t["receives"],
    }


@pytest.mark.parametrize("mode", ["team_context", "asset_only", "market_fairness"])
def test_quarantined_value_withholds_only_the_touching_teams(mode):
    """LABELLED synthetic league: team 2's ``B Two`` is quarantined.  Teams 2
    and 3 (sender and receiver) are UNABLE with ``evaluation_unavailable`` and
    the decision names ``quarantined_values``; team 1 — not touching it — is
    byte-identical to the same trade on the unquarantined board."""
    legs = [
        {"id": "p:202", "from": 2, "to": 3},
        {"id": "p:302", "from": 3, "to": 1},
        {"id": "p:102", "from": 1, "to": 2},
    ]
    clean = mts.synthetic_league()
    dirty = mts.synthetic_league()
    for row in dirty["playersArray"]:
        if row.get("playerId") == "202":
            row["quarantined"] = True
            row["anomalyFlags"] = ["no_valid_source_values"]
    base = _run(mts.synthetic_snapshot(clean), [1, 2, 3], legs, mode)
    out = _run(mts.synthetic_snapshot(dirty), [1, 2, 3], legs, mode)
    for rid in (2, 3):
        t = out["teams"][rid]
        assert t["fairness"]["state"] == "UNABLE", (mode, rid)
        assert t["fairness"]["reasonCode"] == "evaluation_unavailable", (mode, rid)
        assert t["fairness"]["gap"] is None
        codes = [g["code"] for g in t["analysis"]["decision"]["missingEvidence"]]
        assert "quarantined_values" in codes, (mode, rid)
        assert t["analysis"]["decision"]["headline"] == "NOT_ENOUGH_EVIDENCE"
    assert _canon(_strip_team(out["teams"][1])) == _canon(_strip_team(base["teams"][1])), mode
    assert out["summary"]["fairnessOverall"]["state"] in ("UNABLE", "NOT_FAIR")
    # R1-L2 / F2: the quarantined asset is never presented as "priced" — the
    # sender's and the receiver's rows both carry the explicit state and no
    # number (withheld, never 0), and it stays out of the raw totals.
    rows = [
        *[g for g in out["teams"][2]["gives"] if g["assetId"] == "p:202"],
        *[r for r in out["teams"][3]["receives"] if r["assetId"] == "p:202"],
    ]
    assert [(r["valueState"], r["value"]) for r in rows] == [("quarantined", None)] * 2, mode
    clean_rows = [g for g in base["teams"][2]["gives"] if g["assetId"] == "p:202"]
    assert [(r["valueState"], r["value"]) for r in clean_rows] == [("priced", 2000)], mode
    # One value per asset: the withheld value is not rewritten in the ledger rows.
    assert out["summary"]["conservation"]["balanced"] is True


@pytest.mark.parametrize("mode", ["team_context", "asset_only", "market_fairness"])
def test_stale_value_is_an_explicit_state_not_priced(mode):
    """LABELLED synthetic league: team 3's ``C Four`` carries a ``low``
    freshness axis.  Its rows read ``stale`` with no number, its teams are
    UNABLE naming ``stale_values``, and a quarantined-and-stale asset reads
    ``quarantined`` (the evidence gates' own order)."""
    legs = [
        {"id": "p:302", "from": 3, "to": 1},
        {"id": "p:101", "from": 1, "to": 3},
    ]
    dirty = mts.synthetic_league()
    for row in dirty["playersArray"]:
        if row.get("playerId") == "302":
            row["confidenceAxes"] = {**(row.get("confidenceAxes") or {}), "freshness": "low"}
    out = _run(mts.synthetic_snapshot(dirty), [1, 3], legs, mode)
    for rid, side in ((3, "gives"), (1, "receives")):
        t = out["teams"][rid]
        (row,) = [x for x in t[side] if x["assetId"] == "p:302"]
        assert (row["valueState"], row["value"]) == ("stale", None), (mode, rid)
        assert t["fairness"]["state"] == "UNABLE", (mode, rid)
        codes = [g["code"] for g in t["analysis"]["decision"]["missingEvidence"]]
        assert "stale_values" in codes, (mode, rid)
    for row in dirty["playersArray"]:
        if row.get("playerId") == "302":
            row["quarantined"] = True
    out = _run(mts.synthetic_snapshot(dirty), [1, 3], legs, mode)
    (row,) = [x for x in out["teams"][3]["gives"] if x["assetId"] == "p:302"]
    assert (row["valueState"], row["value"]) == ("quarantined", None), mode
    assert set(svc.VALUE_STATES) >= {
        r["valueState"] for t in out["teams"].values() for r in (*t["gives"], *t["receives"])
    }


def test_real_board_quarantine_invariant():
    """On the real board: a team's fairness is UNABLE and its decision names
    ``quarantined_values`` exactly when an asset it sends or receives carries
    the board's quarantine flag (as the simulation reads it)."""
    contract, snap, _label = mts.real_board()
    rng = random.Random(77)
    for _ in range(30):
        teams, legs = mts.random_ledger(snap, rng, max_per_team=3)
        out = _run(snap, teams, legs, "asset_only")
        for rid, t in out["teams"].items():
            sim = t["simulation"]
            q = any(
                r.get("quarantined") is True
                for r in [*(sim.get("sending") or []), *(sim.get("receiving") or [])]
            )
            codes = {g["code"] for g in t["analysis"]["decision"]["missingEvidence"]}
            assert ("quarantined_values" in codes) == q, (teams, rid)
            if q:
                assert t["fairness"]["state"] == "UNABLE", (teams, rid)
            # R1-L2 / F2: a quarantined asset's ledger row is never "priced".
            by_pid = {
                f"p:{a.get('playerId')}": a
                for a in [*(sim.get("sending") or []), *(sim.get("receiving") or [])]
                if a.get("playerId")
            }
            for r in (*t["gives"], *t["receives"]):
                a = by_pid.get(r["assetId"])
                if a is not None and a.get("quarantined") is True:
                    assert r["valueState"] != "priced" and r["value"] is None, (teams, rid)
    # Injected on a real row, so the property is exercised whatever the
    # newest archive happens to quarantine.
    teams, legs = mts.random_ledger(snap, rng, n_teams=3, max_per_team=1, picks=False)
    victim = legs[0]["id"][2:]
    for row in contract["playersArray"]:
        if str(row.get("playerId")) == victim:
            row["quarantined"] = True
    snap2 = tl.build_trade_snapshot(
        contract,
        league_key=LEAGUE,
        roster_settings=mts._dynasty_main_settings(),
        now=mts.PINNED_NOW,
    )
    out = _run(snap2, teams, legs, "asset_only")
    for rid in (legs[0]["from"], legs[0]["to"]):
        t = out["teams"][rid]
        assert t["fairness"]["state"] == "UNABLE", rid
        codes = {g["code"] for g in t["analysis"]["decision"]["missingEvidence"]}
        assert "quarantined_values" in codes, rid
