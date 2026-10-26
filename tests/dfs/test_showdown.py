"""DraftKings NFL Showdown Captain: one athlete, two rows; the captain multiplier applied exactly once.

Synthetic data only.  The rule set itself is an UNVERIFIED research-mode
encoding; these tests prove the solver and identity handling under it.
"""

from __future__ import annotations

import csv
import io
import itertools
import random

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import feature_flags
from src.dfs import api as dfs_api
from src.dfs.imports import apply_projection_csv, parse_draftkings_salaries
from src.dfs.optimizer import optimize, parse_constraints, validate_lineup
from src.dfs.rules import get_ruleset

pytest.importorskip("scipy")

RS = get_ruleset("draftkings.nfl.showdown_captain")
HEAD = "Position,Name + ID,Name,ID,Roster Position,Salary,Game Info,TeamAbbrev,AvgPointsPerGame"


def _showdown_csv(seed: int, n: int = 9) -> tuple[str, dict[str, float]]:
    """n players x (CPT row with 1.5x salary, FLEX row); returns CSV + base projections by name."""
    rnd = random.Random(seed)
    lines, proj = [HEAD], {}
    pos_cycle = ["QB", "RB", "WR", "WR", "TE", "K", "DST", "RB", "WR", "WR", "TE"]
    for i in range(n):
        team = "AAA" if i % 2 == 0 else "BBB"
        pos = pos_cycle[i % len(pos_cycle)]
        name = f"Syn SD {i}"
        base = rnd.randrange(20, 110) * 100
        proj[name] = round(rnd.uniform(2, 25), 2)
        game = "AAA@BBB 10/05/2026 08:15PM ET"
        lines.append(
            f"{pos},{name} ({8000 + i}),{name},{8000 + i},CPT,{int(base * 1.5)},{game},{team},1.0"
        )
        lines.append(f"{pos},{name} ({9000 + i}),{name},{9000 + i},FLEX,{base},{game},{team},1.0")
    return "\n".join(lines) + "\n", proj


def _pool(seed: int):
    text, proj = _showdown_csv(seed)
    athletes, report = parse_draftkings_salaries(text)
    body = "Name,Team,Projection\n" + "\n".join(
        f"{n},{'AAA' if int(n.split()[-1]) % 2 == 0 else 'BBB'},{v}" for n, v in proj.items()
    )
    jr = apply_projection_csv(athletes, body)
    return athletes, report, jr, proj


def _brute(pool):
    groups: dict[str, dict[str, object]] = {}
    for a in pool:
        groups.setdefault(a.identity, {})["CPT" if "CPT" in a.eligible_slots else "FLEX"] = a
    best = None
    for cap_key, g in groups.items():
        cpt = g["CPT"]
        others = [v["FLEX"] for k, v in groups.items() if k != cap_key]
        for flex in itertools.combinations(others, 5):
            rows = [cpt, *flex]
            if sum(r.salary for r in rows) > RS.salary_cap:
                continue
            teams: dict[str, int] = {}
            for r in rows:
                teams[r.team] = teams.get(r.team, 0) + 1
            if len(teams) < RS.min_teams or max(teams.values()) > RS.max_players_per_team:
                continue
            tot = round(1.5 * cpt.projection + sum(r.projection for r in flex), 2)
            best = tot if best is None or tot > best else best
    return best


@pytest.mark.parametrize("seed", range(5))
def test_solver_matches_brute_force_with_the_captain_multiplier(seed):
    pool, _report, _jr, _proj = _pool(seed)
    res = optimize(RS, pool, parse_constraints({}, RS, pool))
    expected = _brute(pool)
    assert expected is not None, "fixture must be feasible (non-vacuous)"
    assert res["status"] == "optimal"
    assert res["lineups"][0]["projection"] == pytest.approx(expected, abs=1e-6)


def test_the_same_athlete_is_never_captain_and_flex():
    pool, *_ = _pool(1)
    res = optimize(RS, pool, parse_constraints({"lineups": 5, "minUnique": 1}, RS, pool))
    by_id = {a.player_id: a for a in pool}
    for lu in res["lineups"]:
        people = [by_id[p["playerId"]].identity for p in lu["players"]]
        assert len(set(people)) == 6
        assert lu["players"][0]["slot"] == "CPT"
    # The independent validator refuses it too.
    a_cpt = next(a for a in pool if a.eligible_slots == ["CPT"])
    a_flex = next(a for a in pool if a.identity == a_cpt.identity and a.eligible_slots == ["FLEX"])
    others = [a for a in pool if a.eligible_slots == ["FLEX"] and a.identity != a_cpt.identity][:4]
    bad = [("CPT", a_cpt.player_id), ("FLEX", a_flex.player_id)] + [
        ("FLEX", o.player_id) for o in others
    ]
    assert any("rostered twice" in e for e in validate_lineup(bad, RS, by_id))


def test_multiplier_is_applied_once_and_the_stored_projection_is_untouched():
    pool, _r, _jr, proj = _pool(2)
    res = optimize(RS, pool, parse_constraints({}, RS, pool))
    cpt = res["lineups"][0]["players"][0]
    assert cpt["slotMultiplier"] == 1.5
    assert cpt["projection"] == proj[cpt["name"]]  # base, as imported
    assert cpt["slotProjection"] == round(1.5 * proj[cpt["name"]], 2)
    for p in res["lineups"][0]["players"][1:]:
        assert p["slotMultiplier"] == 1.0 and p["slotProjection"] == p["projection"]


def test_one_projection_row_reaches_both_rows_of_the_athlete():
    pool, _r, jr, _proj = _pool(3)
    assert jr["ambiguous"] == [] and jr["athletesWithoutProjection"] == 0
    text, _ = _showdown_csv(3)
    athletes, _ = parse_draftkings_salaries(text)
    flex = next(a for a in athletes if a.eligible_slots == ["FLEX"])
    apply_projection_csv(athletes, f"ID,Projection\n{flex.player_id},12.5\n")
    twins = [a for a in athletes if a.identity == flex.identity]
    assert len(twins) == 2 and all(a.projection == 12.5 for a in twins)


def test_a_non_captain_name_collision_stays_quarantined():
    text = (
        HEAD + "\n"
        "WR,Syn Same (1),Syn Same,1,WR/FLEX,5000,AAA@BBB 10/04/2026 01:00PM ET,AAA,1.0\n"
        "WR,Syn Same (2),Syn Same,2,WR/FLEX,4000,AAA@BBB 10/04/2026 01:00PM ET,AAA,1.0\n"
    )
    athletes, report = parse_draftkings_salaries(text)
    assert all(a.group_key is None for a in athletes)
    assert any(r["reason"] == "same_name_team_position_not_a_captain_pair" for r in report.rejected)
    jr = apply_projection_csv(athletes, "Name,Team,Projection\nSyn Same,AAA,10\n")
    assert jr["ambiguous"] and all(a.projection is None for a in athletes)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DFS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("RISKIT_FEATURE_DFS_WORKSPACE", raising=False)
    feature_flags.reload()
    app = FastAPI()
    app.include_router(dfs_api.router)
    dfs_api.configure_session_resolver(
        lambda req: {"username": req.headers["x-user"]} if req.headers.get("x-user") else None
    )
    yield TestClient(app)
    feature_flags.reload()


def test_showdown_file_imports_builds_and_exports_captain_first(client):
    text, proj = _showdown_csv(4)
    body = "Name,Team,Projection\n" + "\n".join(
        f"{n},{'AAA' if int(n.split()[-1]) % 2 == 0 else 'BBB'},{v}" for n, v in proj.items()
    )
    h = {"x-user": "a"}
    snap = client.post(
        "/api/dfs/slates", json={"salaryCsv": text, "projectionCsv": body}, headers=h
    ).json()
    assert snap["ruleset"]["key"] == "draftkings.nfl.showdown_captain@2026.1"
    assert snap["eligibilityCrossCheck"]["state"] == "not_applicable"
    b = client.post(
        "/api/dfs/builds",
        json={
            "snapshotId": snap["snapshotId"],
            "objective": "projection_baseline",
            "constraints": {"lineups": 2},
        },
        headers=h,
    ).json()
    assert b["result"]["built"] == 2
    rows = list(
        csv.reader(
            io.StringIO(client.get(f"/api/dfs/builds/{b['buildId']}/export", headers=h).text)
        )
    )
    assert rows[0] == ["CPT", "FLEX", "FLEX", "FLEX", "FLEX", "FLEX"]
    assert all(
        r[0].startswith("80") for r in rows[1:]
    )  # captain column carries the CPT row's own ID
