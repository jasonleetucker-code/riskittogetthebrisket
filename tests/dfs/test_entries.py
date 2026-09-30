"""Entry files: parse existing DraftKings entries (assumed layout) and export lineups into them.

Synthetic data only; the layout is recorded as ``assumed`` until an official
entry-file template is supplied.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import feature_flags
from src.dfs import api as dfs_api
from src.dfs.entries import parse_entries
from src.dfs.imports import ImportError_, parse_draftkings_salaries
from src.dfs.rules import get_ruleset

pytest.importorskip("scipy")

FIX = Path(__file__).parent / "fixtures"
RS = get_ruleset("draftkings.nfl.classic")
HEAD = "Entry ID,Contest Name,Contest ID,Entry Fee,QB,RB,RB,WR,WR,WR,TE,FLEX,DST,,Instructions"


def _athletes():
    athletes, _ = parse_draftkings_salaries(
        (FIX / "synthetic_dk_nfl_classic_salaries.csv").read_text(encoding="utf-8")
    )
    return athletes


def _legal_ids(athletes):
    by = {}
    for a in athletes:
        by.setdefault(a.positions[0], []).append(a)
    # Cheapest legal-ish shape across two games (validator enforces the rest).
    pick = lambda pos, n: sorted(by[pos], key=lambda a: a.salary)[:n]  # noqa: E731
    lu = (
        pick("QB", 1)
        + pick("RB", 3)[:2]
        + pick("WR", 3)
        + pick("TE", 1)
        + [pick("RB", 3)[2]]
        + pick("DST", 1)
    )
    return [a.player_id for a in lu]


def test_parses_empty_complete_and_unresolved_entries():
    athletes = _athletes()
    ids = _legal_ids(athletes)
    named = [f"Syn Name ({pid})" for pid in ids]
    text = "\n".join(
        [
            HEAD,
            "4001,Milly Maker,99,$20.00" + "," * 9 + ",,",
            "4002,Milly Maker,99,$20.00," + ",".join(named) + ",,",
            "4003,Milly Maker,99,$20.00,999999999" + "," * 8 + ",,",
            ",,,,,,,,,,,,,,Position,Name + ID",  # appended player-list block: ignored, counted
        ]
    )
    out = parse_entries(text, RS, athletes)
    states = {e["entry_id"]: e["state"] for e in out["entries"]}
    assert states == {"4001": "empty", "4002": "complete", "4003": "unresolved"}
    assert out["entries"][1]["lineup"] == ids
    assert out["entries"][1]["entry_fee_cents"] == 2000
    assert "not a player on this slate" in out["entries"][2]["problems"][0]
    assert out["layoutVerification"] == "assumed" and out["ignoredRows"] >= 1


def test_wrong_layout_is_refused_not_guessed():
    with pytest.raises(ImportError_) as exc:
        parse_entries("entry_id,contest_id\n1,2\n", RS, _athletes())
    assert exc.value.code == "ENTRY_FILE_UNRECOGNISED"


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


def test_build_exports_into_existing_entries_and_never_touches_unresolved_ones(client):
    h = {"x-user": "a"}
    snap = client.post(
        "/api/dfs/slates",
        json={
            "salaryCsv": (FIX / "synthetic_dk_nfl_classic_salaries.csv").read_text(
                encoding="utf-8"
            ),
            "projectionCsv": (FIX / "synthetic_dk_nfl_classic_projections.csv").read_text(
                encoding="utf-8"
            ),
        },
        headers=h,
    ).json()
    build = client.post(
        "/api/dfs/builds",
        json={
            "snapshotId": snap["snapshotId"],
            "objective": "projection_baseline",
            "constraints": {"lineups": 3, "minUnique": 2},
        },
        headers=h,
    ).json()
    entries_csv = "\n".join(
        [
            HEAD,
            "5001,GPP,77,$5.00" + "," * 9 + ",,",
            "5002,GPP,77,$5.00,nope123" + "," * 8 + ",,",  # unresolved: must be left alone
            "5003,GPP,77,$5.00" + "," * 9 + ",,",
        ]
    )
    parsed = client.post(
        "/api/dfs/entries/parse",
        json={"snapshotId": snap["snapshotId"], "entriesCsv": entries_csv},
        headers=h,
    ).json()
    assert parsed["counts"] == {"empty": 2, "complete": 0, "partial": 0, "unresolved": 1}
    r = client.post(
        f"/api/dfs/builds/{build['buildId']}/export-entries",
        json={"entriesCsv": entries_csv},
        headers=h,
    )
    assert r.status_code == 200
    assert r.headers["x-dfs-export-verified"] == "false"
    assert (
        r.headers["x-dfs-entries-assigned"] == "2" and r.headers["x-dfs-entries-untouched"] == "1"
    )
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][:4] == ["Entry ID", "Contest Name", "Contest ID", "Entry Fee"]
    assert [row[0] for row in rows[1:]] == ["5001", "5003"]
    first = [p["playerId"] for p in build["result"]["lineups"][0]["players"]]
    assert rows[1][4:] == first
    # Another owner cannot use this build.
    assert (
        client.post(
            f"/api/dfs/builds/{build['buildId']}/export-entries",
            json={"entriesCsv": entries_csv},
            headers={"x-user": "b"},
        ).status_code
        == 404
    )


def test_late_swap_api_plans_from_the_entry_file_and_exports_without_submitting(client):
    h = {"x-user": "a"}
    snap = client.post(
        "/api/dfs/slates",
        json={
            "salaryCsv": (FIX / "synthetic_dk_nfl_classic_salaries.csv").read_text(
                encoding="utf-8"
            ),
            "projectionCsv": (FIX / "synthetic_dk_nfl_classic_projections.csv").read_text(
                encoding="utf-8"
            ),
        },
        headers=h,
    ).json()
    athletes = {a["player_id"]: a for a in snap["athletes"]}
    # A legal lineup deliberately built from the LOWEST projections, so swaps exist.
    flipped = client.post(
        "/api/dfs/builds",
        json={
            "snapshotId": snap["snapshotId"],
            "objective": "projection_baseline",
            "constraints": {
                "lineups": 1,
                "projectionOverrides": {
                    pid: -(a["projection"] or 0) for pid, a in athletes.items()
                },
            },
        },
        headers=h,
    ).json()
    poor = [p["playerId"] for p in flipped["result"]["lineups"][0]["players"]]
    entries_csv = "\n".join(
        [
            HEAD,
            "7001,GPP,77,$5.00," + ",".join(poor) + ",,",
            "7002,GPP,77,$5.00,nope123" + "," * 8 + ",,",
        ]
    )
    body = {
        "snapshotId": snap["snapshotId"],
        "entriesCsv": entries_csv,
        "asOf": "2026-10-04T18:00:00Z",
    }
    plan = client.post("/api/dfs/late-swap", json=body, headers=h).json()
    assert plan["submitted"] is False and plan["clockSource"] == "owner_supplied"
    e1, e2 = plan["entries"]
    assert e2["status"] == "entry_unresolved"
    assert e1["status"] == "swap_recommended"
    early = [i for i, pid in enumerate(poor) if athletes[pid]["game"] == "AAA@BBB"]
    assert early, "fixture should put some of the poor lineup in the 1 PM game"
    for i in early:
        assert e1["finalLineup"][i] == poor[i]
    r = client.post("/api/dfs/late-swap/export", json=body, headers=h)
    assert r.status_code == 200 and r.headers["x-dfs-export-verified"] == "false"
    assert r.headers["x-dfs-entries-written"] == "1" and r.headers["x-dfs-entries-skipped"] == "1"
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[1][0] == "7001" and rows[1][4:] == e1["finalLineup"]

    bad = client.post("/api/dfs/late-swap", json={**body, "asOf": "2026-10-04T18:00:00"}, headers=h)
    assert bad.status_code == 422 and bad.json()["error"] == "INVALID_CLOCK"
    assert client.post("/api/dfs/late-swap", json=body, headers={"x-user": "b"}).status_code == 404
