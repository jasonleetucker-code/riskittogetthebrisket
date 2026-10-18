"""Manager Intelligence Batch F — leaderboards over a named population
(``src/intel/manager_leaderboard.py``).  Every board names its population and
n; a member without a value is unranked with a reason, never last or 0."""

from __future__ import annotations

from src.intel import manager_alerts as mal
from src.intel import manager_compare as mcmp
from src.intel import manager_leaderboard as mlb
from src.intel import manager_saved as ms

NOW_MS = 1_700_000_000_000


def row(rid, owner, name, value=None, picks=None, trades=0, note=None, cap=None):
    return {
        "rosterId": rid,
        "ownerUserId": owner,
        "displayName": name,
        "teamName": f"Team {name}",
        "roster": {"pricedValue": value, "valueNote": note},
        "draftCapital": cap
        if cap is not None
        else {"pricedValue": None, "counts": {"held": picks} if picks is not None else None},
        "activity": {"trades": trades, "events": trades, "playersAdded": 0},
    }


def league_payload(rows, tx="complete", drafts="complete"):
    return {
        "status": "ok" if tx == "complete" else "partial",
        "league": {"leagueId": "42", "name": "Alleys"},
        "season": "2026",
        "windowApplied": "30d",
        "managers": rows,
        "coverage": {"transactions": tx, "drafts": drafts, "tradedPicks": "complete"},
    }


def _board(out, key):
    return next(b for b in out["boards"] if b["key"] == key)


def test_league_population_is_named_with_n_and_every_metric_has_a_board():
    out = mlb.league_leaderboards(league_payload([row(1, "u1", "A", 10), row(2, "u2", "B", 20)]))
    pop = out["population"]
    assert pop == {
        "kind": "league",
        "label": "Current teams in Alleys",
        "leagueId": "42",
        "leagueName": "Alleys",
        "season": "2026",
        "window": "30d",
        "n": 2,
    }
    assert [b["key"] for b in out["boards"]] == [k for k, _l, _p in mcmp.LEAGUE_METRICS]
    assert out["rankingRule"] == mlb.RANKING_RULE


def test_competition_ranking_ties_share_a_rank_and_missing_is_unranked():
    rows = [
        row(1, "u1", "A", 300),
        row(2, "u2", "B", 300),
        row(3, "u3", "C", 100),
        row(4, "u4", "D", None, note="canonical_board_is_superflex"),
    ]
    board = _board(mlb.league_leaderboards(league_payload(rows)), "rosterValue")
    assert [(r["displayName"], r["rank"], r["value"]) for r in board["rows"]] == [
        ("A", 1, 300),
        ("B", 1, 300),
        ("C", 3, 100),
    ]
    assert board["n"] == 3
    assert board["unranked"] == [
        {
            "id": "4",
            "rosterId": 4,
            "userId": "u4",
            "displayName": "D",
            "teamName": "Team D",
            "value": None,
            "reason": "canonical_board_is_superflex",
        }
    ]


def test_zero_is_a_value_but_unknown_pick_ownership_is_not():
    rows = [row(1, "u1", "A", picks=0), row(2, "u2", "B", picks=None)]
    board = _board(mlb.league_leaderboards(league_payload(rows)), "picksHeld")
    assert [(r["displayName"], r["value"]) for r in board["rows"]] == [("A", 0)]
    assert board["unranked"][0]["reason"] == "pick_ownership_unavailable"


def test_partially_read_activity_is_not_ranked():
    rows = [row(1, "u1", "A", trades=3), row(2, "u2", "B", trades=1)]
    out = mlb.league_leaderboards(league_payload(rows, tx="partial"))
    board = _board(out, "trades")
    assert board["rows"] == [] and board["n"] == 0
    assert {u["reason"] for u in board["unranked"]} == {"activity_partially_read"}
    assert out["coverage"]["transactions"] == "partial"


def test_an_orphan_roster_is_unranked():
    rows = [row(1, None, None, 500), row(2, "u2", "B", 100)]
    board = _board(mlb.league_leaderboards(league_payload(rows)), "rosterValue")
    assert [r["displayName"] for r in board["rows"]] == ["B"]
    assert board["unranked"][0]["reason"] == "no_current_owner"


def _saved(*uids):
    entries = [
        {"userId": u, "username": f"m{u}", "displayName": f"M{u}", "savedAt": 1} for u in uids
    ]
    return ms.saved_payload(entries, {})


def _snap(as_of, trades=None, reasons=None):
    return {
        "snapshot": {
            "asOf": as_of,
            "metrics": {"trades": trades, "events": trades, "playersAdded": 0},
            "reasons": reasons or {},
        }
    }


def test_saved_population_is_named_and_counts_members_with_data():
    alerts = {
        "1": _snap(NOW_MS - 1000, trades=4),
        "2": _snap(NOW_MS - 2000, trades=4),
        "3": _snap(NOW_MS - mal.SNAPSHOT_STALE_MS - 1, trades=9),
        "4": _snap(NOW_MS - 1000, trades=None, reasons={"trades": "activity_partially_read"}),
    }
    out = mlb.saved_leaderboards(_saved("1", "2", "3", "4", "5"), alerts, now=lambda: NOW_MS / 1000)
    pop = out["population"]
    assert pop["kind"] == "saved" and pop["label"] == "Your saved managers"
    assert pop["n"] == 5 and pop["withData"] == 3 and pop["window"] == mal.ALERT_WINDOW
    board = _board(out, "trades")
    assert [(r["userId"], r["rank"]) for r in board["rows"]] == [("1", 1), ("2", 1)]
    assert board["n"] == 2
    reasons = {u["userId"]: u["reason"] for u in board["unranked"]}
    assert reasons == {
        "3": "snapshot_stale",
        "4": "activity_partially_read",
        "5": "not_yet_read",
    }
    assert [b["key"] for b in out["boards"]] == [k for k, _l in mlb.SAVED_METRICS]


def test_saved_population_with_no_managers_is_an_empty_named_board():
    out = mlb.saved_leaderboards(_saved(), {}, now=lambda: NOW_MS / 1000)
    assert out["population"]["n"] == 0 and out["population"]["withData"] == 0
    assert all(b["rows"] == [] and b["unranked"] == [] for b in out["boards"])


def test_there_is_no_all_of_sleeper_population():
    assert set(mlb.POPULATIONS) == {"league", "saved"}
