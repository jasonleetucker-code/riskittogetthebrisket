"""Manager Intelligence Batch F — leaderboards over a NAMED, visible population.

A leaderboard ranks only a population the user can see and that the board
names, never "all of Sleeper".  Two populations exist in code today:

* ``league`` — the current teams of ONE Sleeper league, over the Batch C
  scouting rows (``manager_league.cached_league_scouting``) and the same
  metric paths the Batch E league percentile reads
  (``manager_compare.LEAGUE_METRICS``).
* ``saved`` — the signed-in user's saved managers, over the metrics snapshot
  the saved-manager detector stores with each read
  (``manager_alerts.build_snapshot``).  No Sleeper call is spent here.

A third population the workstream allows, a "discovered network", is NOT
offered: Manager Intelligence has no discovered-manager population of its own
(the Sharp cohort is a different population, with its own qualification
rules, and none of these metrics are computed for it).

Every board names its population and ``n`` (how many members were ranked),
ranks with competition ranking (ties share a rank) over the members that
HAVE a value, and lists the rest as unranked with the reason — a missing
value is never ranked last and never read as 0.  Each metric is passed
through from the block that computed it; nothing is re-valued.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from src.intel import manager_activity as ma
from src.intel import manager_alerts as mal
from src.intel import manager_compare as mcmp
from src.intel import manager_league as ml
from src.intel import manager_saved as ms

POPULATION_LEAGUE = "league"
POPULATION_SAVED = "saved"
POPULATIONS = (POPULATION_LEAGUE, POPULATION_SAVED)

RANKING_RULE = (
    "Competition ranking, highest first: tied members share a rank and the next rank "
    "skips. Members without a value are listed unranked with the reason, never last."
)

#: Saved-manager metrics: ``(key, label)`` — keys of the detector snapshot.
SAVED_METRICS: tuple[tuple[str, str], ...] = (
    ("trades", "Completed trades (last 7 days)"),
    ("events", "Transactions, all kinds (last 7 days)"),
    ("playersAdded", "Players added (last 7 days)"),
    ("picksHeld", "Draft picks held"),
    ("pickValue", "Draft pick value (canonical board)"),
)


def _board(
    key: str,
    label: str,
    members: list[dict[str, Any]],
    values: dict[str, float | None],
    reasons: dict[str, str | None],
) -> dict[str, Any]:
    ranks = ml._competition_ranks(values)  # noqa: SLF001 — one ranking rule
    ranked, unranked = [], []
    for m in members:
        mid = m["id"]
        if ranks.get(mid) is None:
            unranked.append({**m, "value": None, "reason": reasons.get(mid) or "unavailable"})
        else:
            ranked.append({**m, "rank": ranks[mid], "value": values[mid]})
    ranked.sort(key=lambda r: (r["rank"], str(r.get("displayName") or "").lower(), r["id"]))
    unranked.sort(key=lambda r: (str(r.get("displayName") or "").lower(), r["id"]))
    return {"key": key, "label": label, "n": len(ranked), "rows": ranked, "unranked": unranked}


def league_leaderboards(payload: dict[str, Any]) -> dict[str, Any]:
    """Boards over one league's current teams (a Batch C payload)."""
    rows = payload.get("managers") or []
    cov = payload.get("coverage") or {}
    activity_read = (
        cov.get("transactions") == ma.COV_COMPLETE and cov.get("drafts") == ma.COV_COMPLETE
    )
    league = payload.get("league") or {}
    members = [
        {
            "id": str(r["rosterId"]),
            "rosterId": r["rosterId"],
            "userId": r.get("ownerUserId"),
            "displayName": r.get("displayName"),
            "teamName": r.get("teamName"),
        }
        for r in rows
    ]
    boards = []
    for key, label, path in mcmp.LEAGUE_METRICS:
        values: dict[str, float | None] = {}
        reasons: dict[str, str | None] = {}
        for r in rows:
            rid = str(r["rosterId"])
            if path[0] == "activity" and not activity_read:
                values[rid], reasons[rid] = None, "activity_partially_read"
                continue
            if r.get("ownerUserId") is None:
                # An orphaned roster has no manager to rank.
                values[rid], reasons[rid] = None, "no_current_owner"
                continue
            v = mcmp._dig(r, path)  # noqa: SLF001 — the percentile's own reader
            values[rid] = v
            reasons[rid] = None if v is not None else mcmp.metric_reason(r, path)
        boards.append(_board(key, label, members, values, reasons))
    name = league.get("name") or "this league"
    return {
        "population": {
            "kind": POPULATION_LEAGUE,
            "label": f"Current teams in {name}",
            "leagueId": league.get("leagueId"),
            "leagueName": league.get("name"),
            "season": payload.get("season"),
            "window": payload.get("windowApplied") or payload.get("window"),
            "n": len(rows),
        },
        "status": payload.get("status"),
        "boards": boards,
        "rankingRule": RANKING_RULE,
        "coverage": {
            "transactions": cov.get("transactions"),
            "drafts": cov.get("drafts"),
            "tradedPicks": cov.get("tradedPicks"),
            "budgetExhausted": cov.get("budgetExhausted"),
        },
        "valueBasis": payload.get("valueBasis"),
    }


def saved_leaderboards(
    saved: dict[str, Any],
    alerts: dict[str, dict[str, Any]],
    *,
    now: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Boards over the user's saved managers, from stored snapshots.

    A manager never read yet is unranked ``not_yet_read``; one whose snapshot
    is older than ``manager_alerts.SNAPSHOT_STALE_MS`` is unranked
    ``snapshot_stale`` (stale is not current)."""
    now_ms = int(now() * 1000)
    managers = saved.get("managers") or []
    members = []
    snapshots: dict[str, dict[str, Any] | None] = {}
    with_data = 0
    for m in managers:
        uid = m["userId"]
        snap = (alerts.get(uid) or {}).get("snapshot")
        snap = snap if isinstance(snap, dict) else None
        fresh = snap is not None and now_ms - int(snap.get("asOf") or 0) <= mal.SNAPSHOT_STALE_MS
        snapshots[uid] = snap if fresh else None
        with_data += 1 if fresh else 0
        members.append(
            {
                "id": uid,
                "userId": uid,
                "username": m.get("username"),
                "displayName": m.get("displayName") or m.get("username"),
                "asOf": snap.get("asOf") if snap else None,
                "_stale": snap is not None and not fresh,
            }
        )
    boards = []
    for key, label in SAVED_METRICS:
        values: dict[str, float | None] = {}
        reasons: dict[str, str | None] = {}
        for mem in members:
            uid = mem["id"]
            snap = snapshots.get(uid)
            if snap is None:
                values[uid] = None
                reasons[uid] = "snapshot_stale" if mem["_stale"] else "not_yet_read"
                continue
            v = (snap.get("metrics") or {}).get(key)
            values[uid] = v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
            reasons[uid] = (
                None
                if values[uid] is not None
                else ((snap.get("reasons") or {}).get(key) or "unavailable")
            )
        public = [{k: v for k, v in mem.items() if k != "_stale"} for mem in members]
        boards.append(_board(key, label, public, values, reasons))
    as_ofs = [s["asOf"] for s in snapshots.values() if s and s.get("asOf")]
    return {
        "population": {
            "kind": POPULATION_SAVED,
            "label": "Your saved managers",
            "n": len(managers),
            "withData": with_data,
            "window": mal.ALERT_WINDOW,
            "asOfOldest": min(as_ofs) if as_ofs else None,
            "asOfNewest": max(as_ofs) if as_ofs else None,
        },
        "status": "ok",
        "boards": boards,
        "rankingRule": RANKING_RULE,
        "note": (
            "Built from each saved manager's last activity read (the daily alert sweep, or "
            "“Check for new activity”). A manager not read in the last 72 hours is "
            "listed unranked."
        ),
    }


def saved_population(kv_user: str, *, path: Any = None, now=time.time) -> dict[str, Any]:
    """The saved-population boards for one user, straight from user_kv."""
    from src.api import user_kv  # noqa: PLC0415

    state = user_kv.get_user_state(kv_user, path=path)
    entries = ms.entries_from_state(state)
    alerts = ms.alert_states(state)
    return saved_leaderboards(ms.saved_payload(entries, alerts), alerts, now=now)


__all__ = [
    "POPULATIONS",
    "RANKING_RULE",
    "SAVED_METRICS",
    "league_leaderboards",
    "saved_leaderboards",
    "saved_population",
]
