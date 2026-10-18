"""Batch G — the read-only Sleeper reconciliation script, driven offline.

``scripts/reconcile_draft_capital_sleeper.py`` compares the served board's
216 owned-pick identities with Sleeper's rosters, users and ``/traded_picks``.
Its LIVE run is never part of CI (third-party data); this test feeds it
saved copies (``--sleeper-dir``) and a saved board (``--payload``), so it
exercises every check without a network call, and proves it can fail.
"""

from __future__ import annotations

import ast
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "reconcile_draft_capital_sleeper.py"
CLASSES = (2027, 2028, 2029)
TRADES = [
    {"season": "2027", "round": 1, "roster_id": 3, "owner_id": 7},
    {"season": "2029", "round": 2, "roster_id": 12, "owner_id": 1},
    {"season": "2028", "round": 4, "roster_id": 5, "owner_id": 5},  # traded back
]


def _sleeper():
    return {
        "league": {"settings": {"draft_rounds": 6, "num_teams": 12}},
        "rosters": [{"roster_id": r, "owner_id": f"u{r}"} for r in range(1, 13)],
        "users": [
            {"user_id": f"u{r}", "display_name": f"user{r}", "metadata": {"team_name": f"Team {r}"}}
            for r in range(1, 12)
        ]
        + [{"user_id": "u12", "display_name": "user12", "metadata": {}}],  # no team_name
        "traded_picks": TRADES,
    }


def _board():
    holder = {(int(t["season"]), t["round"], t["roster_id"]): t["owner_id"] for t in TRADES}
    name = {r: f"Team {r}" for r in range(1, 12)} | {12: "user12"}
    rows = []
    for season in CLASSES:
        for rnd in range(1, 7):
            for origin in range(1, 13):
                owner = holder.get((season, rnd, origin), origin)
                rows.append(
                    {
                        "season": season,
                        "round": rnd,
                        "assetId": f"pick:dynasty_main:{season}:r{rnd}:o{origin}",
                        "originRosterId": origin,
                        "currentOwnerRosterId": owner,
                        "originalOwner": name[origin],
                        "currentOwner": name[owner],
                        "isTraded": owner != origin,
                        "dollarValue": 1,
                    }
                )
    return {
        "availableYears": list(CLASSES),
        "picks": [r for r in rows if r["season"] == 2027],
        "additionalClassPicks": [r for r in rows if r["season"] != 2027],
        "teamTotals": [
            {"team": f"Team {r}", "pickOwnershipState": "observed"} for r in range(1, 13)
        ],
    }


def _run(tmp_path, board, sleeper):
    sdir = tmp_path / "sleeper"
    sdir.mkdir(exist_ok=True)
    for key, value in sleeper.items():
        (sdir / f"{key}.json").write_text(json.dumps(value), "utf-8")
    payload = tmp_path / "board.json"
    payload.write_text(json.dumps(board), "utf-8")
    out = tmp_path / "report.json"
    done = subprocess.run(
        [
            sys.executable,
            "-I",
            str(SCRIPT),
            "--payload",
            str(payload),
            "--sleeper-dir",
            str(sdir),
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    report = json.loads(out.read_text("utf-8")) if out.exists() else None
    return done, report


def test_script_is_stdlib_only_and_get_only():
    tree = ast.parse(SCRIPT.read_text("utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mods.add((node.module or "").split(".")[0])
    assert mods <= {"__future__", "argparse", "json", "sys", "urllib", "collections", "pathlib"}
    text = SCRIPT.read_text("utf-8")
    assert 'method="GET"' in text
    for verb in ("POST", "PUT", "PATCH", "DELETE"):
        assert f'"{verb}"' not in text


def test_a_consistent_board_reconciles(tmp_path):
    done, report = _run(tmp_path, _board(), _sleeper())
    assert done.returncode == 0, done.stdout
    assert report["fail"] == 0 and report["pass"] == 10


def _wrong_owner(board, _s):
    board["additionalClassPicks"][0]["currentOwnerRosterId"] = 9


def _missing_trade(_b, sleeper):
    sleeper["traded_picks"] = TRADES[1:]


def _duplicate(board, _s):
    board["picks"][1] = copy.deepcopy(board["picks"][0])


def _name(board, _s):
    board["picks"][0]["currentOwner"] = "Somebody Else"


def _flag(board, _s):
    board["picks"][5]["isTraded"] = True


def _unobserved(board, _s):
    board["teamTotals"][0]["pickOwnershipState"] = "unavailable"


def _not_a_list(_b, sleeper):
    sleeper["traded_picks"] = {"error": "rate limited"}


@pytest.mark.parametrize(
    ("mutate", "named"),
    [
        (_wrong_owner, "every current owner = Sleeper fold"),
        (_missing_trade, "every current owner = Sleeper fold"),
        (_duplicate, "216 unique identities on the board"),
        (_name, "owner names = Sleeper team names"),
        (_flag, "isTraded = holder differs from origin"),
        (_unobserved, "no team publishes unavailable pick ownership"),
        (_not_a_list, "Sleeper /traded_picks is an observation (a list)"),
    ],
)
def test_every_discrepancy_fails_and_is_named(tmp_path, mutate, named):
    board, sleeper = _board(), _sleeper()
    mutate(board, sleeper)
    done, report = _run(tmp_path, board, sleeper)
    assert done.returncode == 1, done.stdout
    assert named in [r["check"] for r in report["results"] if r["status"] == "FAIL"]


def test_a_refused_or_unreadable_board_is_blocked_never_a_result(tmp_path):
    done, report = _run(
        tmp_path, {"error": "pick_ownership_unavailable", "message": "x"}, _sleeper()
    )
    assert done.returncode == 2 and "BLOCKED" in done.stdout and report is None
    sdir = tmp_path / "empty"
    sdir.mkdir()
    payload = tmp_path / "b.json"
    payload.write_text(json.dumps(_board()), "utf-8")
    missing = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--payload", str(payload), "--sleeper-dir", str(sdir)],
        capture_output=True,
        text=True,
    )
    assert missing.returncode == 2 and "BLOCKED" in missing.stdout
